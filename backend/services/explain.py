"""Explainability — WHERE the model looked, alongside WHAT it scored.

GRAD-CAM (Selvaraju et al. 2017) — coarse, cheap, and about REGIONS. One
forward plus one partial backward to the last spatial feature map: the channel
weights are the global-average-pooled gradients of one logit, and the map is
the ReLU'd weighted channel sum. At nat768 the feature grid is 24x32, so a cell
is ~32x32 input pixels — roughly one small ECG box. That is the resolution of
the claim: "this LEAD", never "this ST segment".

WHAT EVERY MAP IS MEASURED AGAINST
----------------------------------
The printed ID/Age/Sex block separates STEMI EXACTLY in the synthetic corpus.
The hybrids_v2 checkpoints trained with that block painted out; the application
deliberately does not redact an uploaded photograph (see preprocess.py). So
every map produced here is scored for the fraction of its attribution mass that
lands inside `descriptor.explain.header_box`, and that number — `header_frac` —
travels in the record next to the picture. A pretty heatmap over lead II and a
header_frac of 0.4 are the same run, and only one of them is reassuring.

GEOMETRY
--------
Maps are computed at each view's own resolution and resampled to the STORED
model_input.png geometry, which is what the overlays are drawn on and what the
header box is expressed in. Views are (height, width) throughout, as everywhere
else in this app.

COST
----
One forward under `no_grad` plus a backward that stops at the feature map, per
label — seconds on CPU, and near-`no_grad` memory because nothing upstream of
the target layer is recorded (see `grad_cam`). `estimate_passes()` is what the
API reports so the UI can say so before the user waits.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T

from backend.errors import ApiError
from backend.services.preprocess import resize_hw
from backend.services.runner import LoadedModel, call_model
from backend.settings import settings

log = logging.getLogger("cardiosentry.explain")

METHODS = ("gradcam",)

_COLORMAPS = {
    "turbo": getattr(cv2, "COLORMAP_TURBO", cv2.COLORMAP_JET),
    "jet": cv2.COLORMAP_JET,
    "inferno": cv2.COLORMAP_INFERNO,
    "magma": cv2.COLORMAP_MAGMA,
    "viridis": cv2.COLORMAP_VIRIDIS,
    "plasma": cv2.COLORMAP_PLASMA,
    "hot": cv2.COLORMAP_HOT,
}


class ExplainError(ApiError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(status, code, message)


# ===================================================================== memory
#
# Enabling autograd on this model at this input size from the INPUT costs
# ~2.3 GB of stored activations, against 84 MB for the same forward under
# `no_grad`. Grad-CAM avoids that by recording no graph before its target
# layer (see `grad_cam`), so a run needs almost nothing above an idle server —
# but a laptop serving this app with a browser open can still be short of even
# that, and being refused beats the OOM killer taking the server down
# mid-request, losing the loaded model and a 30 s restart with it.

def available_mb() -> float | None:
    """Memory the OS says we can still get, or None where that is unknowable.

    MemAvailable, not MemFree: the kernel's own estimate of what is obtainable
    without swapping, which already accounts for reclaimable page cache. Free
    alone would read ~2 GB on a box with 8 GB of reclaimable cache and refuse
    runs that would have been fine.
    """
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None                      # not Linux, or /proc unreadable


# Extra resident MB per input pixel for the late-graph Grad-CAM, measured on
# this app's checkpoints at 768x1024. An estimate for a GUARD, not a
# specification, and deliberately on the pessimistic side.
_MB_PER_MPX_LATE_GRAPH = 120.0       # ~44 MB at 0.79 Mpx, i.e. ~no_grad
_MEMORY_SAFETY_FACTOR = 1.35         # headroom for fragmentation and the peak
                                     # we sample at 20 ms landing between samples


def _input_mpx(lm: LoadedModel) -> float:
    return sum(h * w for h, w in lm.views) / 1e6


def estimate_peak_mb(lm: LoadedModel) -> float:
    """Extra resident MB this run is expected to need above the idle server."""
    return _MB_PER_MPX_LATE_GRAPH * _input_mpx(lm)


def plan_memory(lm: LoadedModel) -> dict:
    """Refuse before the OOM killer does, and say by how much.

    Returns the numbers behind the decision, because they are what make the
    507 actionable: "close something and retry" is only useful advice when the
    message says how much short the machine was.
    """
    avail = available_mb()
    need = estimate_peak_mb(lm) * _MEMORY_SAFETY_FACTOR
    plan = {"available_mb": round(avail) if avail is not None else None,
            "estimated_need_mb": round(need)}
    if avail is not None and need > avail:
        raise ExplainError(
            "EXPLAIN_INSUFFICIENT_MEMORY",
            f"gradcam on {lm.id} at "
            f"{'x'.join(str(v) for v in lm.views[0])} needs about "
            f"{need:.0f} MB and the machine has {avail:.0f} MB available. "
            "Refusing rather than risking the OOM killer, which would take "
            "the whole server down mid-request. Close something and retry.",
            status=507)
    return plan


# ===================================================================== layers
@dataclass
class LayerCandidate:
    name: str                       # dotted module path, as passed to target_layer
    module_type: str
    channels: int
    grid: tuple[int, int]           # (height, width) of the feature map
    order: int                      # execution order in the probe forward


def probe_layers(lm: LoadedModel) -> list[LayerCandidate]:
    """Every module that produced a usable 4-D feature map, in execution order.

    Discovery is by OBSERVATION rather than by isinstance: what makes a module a
    Grad-CAM target is the shape of what it returned during a real forward, and
    the three architecture families vendored here disagree about which class
    that is (`HybridModel.attn` is a CBAM, `runs_v1` ends in a timm backbone,
    `hybrids_v1` runs two streams). One probe forward answers it for all of them.
    """
    found: list[LayerCandidate] = []
    counter = {"n": 0}
    handles = []

    def hook(name, mod):
        def fn(_m, _inp, out):
            t = out[0] if isinstance(out, (tuple, list)) and out and \
                isinstance(out[0], torch.Tensor) else out
            if not isinstance(t, torch.Tensor) or t.dim() != 4:
                return
            _b, c, h, w = t.shape
            if h * w <= 1 or c < 8:
                return          # 1x1 channel descriptors and 1-channel gates
            counter["n"] += 1
            found.append(LayerCandidate(name=name, module_type=type(mod).__name__,
                                        channels=int(c), grid=(int(h), int(w)),
                                        order=counter["n"]))
        return fn

    for name, mod in lm.model.named_modules():
        if not name:
            continue
        handles.append(mod.register_forward_hook(hook(name, mod)))
    try:
        with torch.no_grad():
            call_model(lm, {hw: torch.zeros(1, 3, *hw) for hw in lm.views})
    finally:
        for h in handles:
            h.remove()
    return found


def auto_target_layer(lm: LoadedModel) -> LayerCandidate:
    """The feature map the classification head actually consumes.

    The rule is the last 4-D feature map the model emitted, in execution order,
    once 1x1 channel descriptors and single-channel gates are filtered out (see
    `probe_layers`). "Last" is the right notion of "deepest" here in a way that
    neither the coarsest grid nor the widest channel count is:

      coarsest grid  picks `resnet50_dual`'s 12x12 LOW-resolution stream over
                     its 24x24 detail stream — explaining the half of that
                     model the run does not exist to test.
      widest channel picks an inverted-residual expansion inside
                     EfficientNetV2-S (1536 ch) over its own final conv_head
                     (1280 ch) — a mid-block tensor, one stage too early.

    Last-in-order gets all five vendored checkpoints right, resolving to `attn`
    on the CBAM hybrids: the tensor after attention has re-weighted it, which is
    exactly what `forward_head` pools. `backbone.layer4` would explain a model
    one block shallower than the one that produced the score.

    KNOWN LIMIT. On a hybrid built with the lightweight transformer
    (`use_lt=True`), `lt.proj` is a 1x1 Conv2d and therefore runs last, so it
    would win here over `attn`. None of the vendored checkpoints use it, and
    the fix is a line of YAML rather than a heuristic: the two CBAM descriptors
    pin `explain.target_layer: attn` explicitly for exactly this reason.
    """
    cands = probe_layers(lm)
    if not cands:
        raise ExplainError(
            "NO_TARGET_LAYER",
            f"{lm.id}: no 4-D feature map found in a probe forward, so Grad-CAM "
            "has nothing to hook. Name an explicit `target_layer` in the "
            "descriptor's explain block.", status=500)
    return max(cands, key=lambda c: c.order)


def resolve_target_layer(lm: LoadedModel,
                         name: str | None) -> tuple[str, torch.nn.Module]:
    """A dotted module path -> (name, module), or the auto choice when None."""
    if not name:
        cand = auto_target_layer(lm)
        name = cand.name
    mods = dict(lm.model.named_modules())
    if name not in mods:
        near = [n for n in mods if n and name.split(".")[-1] in n][:8]
        raise ExplainError(
            "UNKNOWN_TARGET_LAYER",
            f"{lm.id} has no module {name!r}. "
            + (f"Did you mean one of: {', '.join(near)}?" if near
               else "GET /api/models/{id}/layers lists the usable ones."))
    return name, mods[name]


# ===================================================================== inputs
def _load_input_rgb(model_input_path: Path) -> Image.Image:
    with Image.open(model_input_path) as im:
        im.load()
        return im.convert("RGB")


def _stored_hw(img: Image.Image) -> tuple[int, int]:
    """The STORED model_input.png geometry, (height, width) — read, not assumed.

    Every map is resampled to this, NOT to `descriptor.preprocess.input_hw`, and
    the two are not always the same number. A capture stored at 768x1024 by the
    round-3 model can be re-explained by `resnet50_hires`, whose own input is
    768x768: attributions computed at the model's geometry but drawn against
    the descriptor's would be a 768x768 map composited onto a 768x1024
    photograph. Using the file's own size keeps the overlay, the header box and
    every reported centroid in ONE coordinate frame — the sheet's.
    """
    return (img.height, img.width)


def _views_from_image(lm: LoadedModel, img: Image.Image,
                      mean, std) -> dict[tuple[int, int], torch.Tensor]:
    """The same ONE-decode / per-view BICUBIC chain runner.derive_views uses.

    It is duplicated rather than called because Grad-CAM runs its own forward
    with a hook on the target layer. Any divergence from the scoring chain
    would attribute a different input than the one that was scored, so the two
    must be read together.
    """
    tf = T.Compose([T.ToTensor(), T.Normalize(mean=mean, std=std)])
    return {hw: tf(resize_hw(img, hw)).unsqueeze(0) for hw in lm.views}


def _label_index(lm: LoadedModel, label: str) -> int:
    try:
        return lm.descriptor.labels.index(label)
    except ValueError:
        raise ExplainError("UNKNOWN_LABEL",
                           f"unknown label {label!r} — this model scores "
                           + ", ".join(lm.descriptor.labels))


# ==================================================================== results
@dataclass
class LabelMap:
    """One label's attribution, already resampled to model_input geometry."""
    label: str
    data: np.ndarray                 # float32 (H, W), >= 0
    stats: dict = field(default_factory=dict)


@dataclass
class ExplainOutput:
    method: str
    maps: list[LabelMap]
    meta: dict                       # provenance (layer, grid…)


# =================================================================== grad-cam
def grad_cam(lm: LoadedModel, model_input_path: Path, labels: list[str],
             target_layer: str | None = None) -> ExplainOutput:
    """ReLU(sum_c alpha_c A_c), alpha = GAP of dlogit/dA.

    THE GRAPH STARTS AT THE TARGET LAYER, NOT AT THE INPUT.

    Grad-CAM's gradient is dlogit/dA for A the target layer's output. Nothing
    upstream of A appears in that derivative, so storing the backbone's
    activations for a backward that stops at A is pure waste — and on this
    model at this input size it is 2.3 GB of waste, which is the difference
    between a 3 s explanation and the OOM killer taking the server down.

    So the whole forward runs under `no_grad`, and a hook on the target module
    detaches its output into a fresh leaf, flips grad recording ON, and returns
    that leaf in place of the original. Everything before the hook is computed
    and freed; everything after it — attention's own tail, the pooling, the
    classifier — is recorded. Measured on efficientnetv2_s_cbam@768x1024:

        full graph   1.6 s   peak 3218 MB  (+2307 over idle)
        this         1.3 s   peak  979 MB  (+44 over idle)

    and the CAMs are bit-identical, because it is the same derivative: A is a
    leaf either way, and detaching it cannot change dlogit/dA.
    """
    pre = lm.descriptor.preprocess
    img = _load_input_rgb(model_input_path)
    store_hw = _stored_hw(img)
    layer_name, module = resolve_target_layer(lm, target_layer)

    activation: dict[str, torch.Tensor] = {}

    def fwd_hook(_m, _inp, out):
        t = out[0] if isinstance(out, (tuple, list)) else out
        if not isinstance(t, torch.Tensor) or t.dim() != 4:
            return None
        leaf = t.detach().requires_grad_(True)
        activation["a"] = leaf
        # Imperative, NOT a `with` block: the point is that recording stays on
        # for the REST of the forward. The enclosing `no_grad` restores the
        # flag on exit, so this cannot leak into another request.
        torch.set_grad_enabled(True)
        return leaf                      # a returned value replaces the output

    handle = module.register_forward_hook(fwd_hook)
    try:
        views = _views_from_image(lm, img, pre.normalize.mean, pre.normalize.std)
        with torch.no_grad():
            logits = call_model(lm, views)
            if logits.dim() == 1:
                logits = logits.unsqueeze(0)
            if "a" not in activation:
                raise ExplainError(
                    "TARGET_LAYER_NOT_EXECUTED",
                    f"module {layer_name!r} produced no 4-D output during the "
                    "forward — it is not on this model's execution path.",
                    status=500)
            acts = activation["a"]
            maps: list[LabelMap] = []
            for i, label in enumerate(labels):
                k = _label_index(lm, label)
                grads = torch.autograd.grad(logits[0, k], acts,
                                            retain_graph=i < len(labels) - 1)[0]
                # alpha_c: the mean gradient over the map = how much this
                # channel's presence anywhere raises the logit.
                alpha = grads.mean(dim=(2, 3), keepdim=True)
                cam = torch.relu((alpha * acts).sum(dim=1, keepdim=True))
                cam_np = cam[0, 0].detach().cpu().numpy().astype(np.float32)
                maps.append(LabelMap(
                    label=label, data=_to_input_geometry(cam_np, store_hw),
                    stats={"grid": list(cam_np.shape),
                           "cam_max_raw": float(cam_np.max()),
                           "all_zero": bool(np.all(cam_np <= 0))}))
    finally:
        handle.remove()

    grid = list(acts.shape[2:])
    h, w = store_hw
    return ExplainOutput(
        method="gradcam", maps=maps,
        meta={"target_layer": layer_name,
              "target_layer_type": type(module).__name__,
              "feature_grid": grid,
              "map_hw": [h, w],
              "feature_channels": int(acts.shape[1]),
              "graph_from": layer_name,   # nothing upstream was recorded
              "upsample": "cv2.INTER_LINEAR",
              # The honest resolution of every claim this map makes.
              "cell_px": [round(h / max(grid[0], 1), 1),
                          round(w / max(grid[1], 1), 1)]})


# ==================================================================== shaping
def _to_input_geometry(m: np.ndarray, input_hw: tuple[int, int]) -> np.ndarray:
    """Resample a map to the stored model_input geometry (height, width).

    Bilinear, deliberately: a Grad-CAM cell IS a 32x32 region and nearest would
    draw a crisp square edge the model never asserted. The overlay must not
    claim more precision than the feature grid has.
    """
    h, w = input_hw
    if m.shape == (h, w):
        return m.astype(np.float32)
    return cv2.resize(m.astype(np.float32), (w, h),
                      interpolation=cv2.INTER_LINEAR)


def normalize_map(m: np.ndarray, pct: float) -> tuple[np.ndarray, dict]:
    """Map -> [0,1] on a percentile scale.

    A single hot pixel would otherwise flatten the whole map to black. The
    divisor actually used is recorded, so two runs' colours are comparable only
    when their `scale` matches — which is why it is in the record.
    """
    a = np.abs(m)
    scale = float(np.percentile(a, pct)) if a.size else 0.0
    if scale <= 0:
        scale = float(a.max())
    info = {"scale": scale, "percentile": pct,
            "raw_min": float(m.min()), "raw_max": float(m.max()),
            "clipped_frac": float((a > scale).mean()) if scale > 0 else 0.0}
    if scale <= 0:
        return np.zeros_like(m, dtype=np.float32), info
    return np.clip(m / scale, 0.0, 1.0).astype(np.float32), info


def colorize(norm: np.ndarray, colormap: str) -> np.ndarray:
    """Normalized map -> BGR uint8."""
    u8 = np.clip(norm * 255.0, 0, 255).astype(np.uint8)
    cm = _COLORMAPS.get(colormap)
    if cm is None:
        raise ExplainError("UNKNOWN_COLORMAP",
                           f"colormap must be one of {', '.join(_COLORMAPS)}")
    return cv2.applyColorMap(u8, cm)


def overlay(base_rgb: np.ndarray, heat_bgr: np.ndarray, norm: np.ndarray,
            alpha: float) -> np.ndarray:
    """Blend the heat map over the sheet, weighted by attribution.

    The blend weight is per-pixel rather than global, so a region the map said
    nothing about shows the PHOTOGRAPH rather than a wash of colour.
    """
    base_bgr = cv2.cvtColor(base_rgb, cv2.COLOR_RGB2BGR).astype(np.float32)
    w = norm.astype(np.float32)[..., None] * float(alpha)
    return np.clip(base_bgr * (1 - w) + heat_bgr.astype(np.float32) * w,
                   0, 255).astype(np.uint8)


def box_fraction(m: np.ndarray, box: list[float] | None) -> dict | None:
    """How much of the attribution mass fell inside the header box.

    `frac` is that mass over the total; `lift` is that fraction divided by the
    box's share of the sheet's AREA. lift = 1.0 means the box got exactly the
    attention its size would predict; lift = 4.0 means the model concentrated
    four times as hard there as anywhere else, which on a band containing the
    printed record ID is the shortcut this metric exists to catch.
    """
    if not box:
        return None
    h, w = m.shape[:2]
    x0, y0, x1, y1 = box
    c0, r0 = int(round(x0 * w)), int(round(y0 * h))
    c1, r1 = int(round(x1 * w)), int(round(y1 * h))
    c0, r0 = max(0, c0), max(0, r0)
    c1, r1 = min(w, max(c1, c0 + 1)), min(h, max(r1, r0 + 1))
    a = np.abs(m)
    total = float(a.sum())
    inside = float(a[r0:r1, c0:c1].sum())
    area_frac = ((r1 - r0) * (c1 - c0)) / float(h * w)
    frac = inside / total if total > 0 else 0.0
    return {"box": [x0, y0, x1, y1],
            "box_area_frac": round(area_frac, 4),
            "frac": round(frac, 4),
            "lift": round(frac / area_frac, 3) if area_frac > 0 else None,
            "peak_inside": bool(
                (r0 <= int(np.argmax(a) // w) < r1) and
                (c0 <= int(np.argmax(a) % w) < c1))}


def map_summary(m: np.ndarray) -> dict:
    """Where the mass is, in fractions of the sheet — readable without the PNG."""
    h, w = m.shape[:2]
    a = np.abs(m)
    total = float(a.sum())
    if total <= 0:
        return {"empty": True}
    ys, xs = np.mgrid[0:h, 0:w]
    flat_peak = int(np.argmax(a))
    # Smallest fraction of pixels holding half the total mass: a compact,
    # scale-free concentration measure. 0.01 means half the evidence is in 1%
    # of the sheet; 0.4 means the map is diffuse and says little.
    order = np.sort(a.reshape(-1))[::-1]
    csum = np.cumsum(order)
    k = int(np.searchsorted(csum, total * 0.5)) + 1
    return {
        "empty": False,
        "centroid_xy": [round(float((xs * a).sum() / total) / w, 4),
                        round(float((ys * a).sum() / total) / h, 4)],
        "peak_xy": [round((flat_peak % w) / w, 4), round((flat_peak // w) / h, 4)],
        "peak_value": float(a.max()),
        "mass_half_area_frac": round(k / float(h * w), 5),
    }


def png_bytes(bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise ExplainError("RENDER_FAILED", "could not encode PNG", status=500)
    return buf.tobytes()


# =============================================================== cost estimate
def estimate_passes(n_labels: int) -> dict:
    """Whole model passes this run will cost, so the UI can warn BEFORE the wait.

    A "pass" is one forward or one full backward; they cost about the same at
    these input sizes. Grad-CAM's backwards stop at the feature map, so they are
    counted separately as partial — measured, not assumed, on
    resnet50_cbam@768x1024.
    """
    return {"forward": 1, "backward_full": 0,
            "backward_partial": n_labels, "note": "partial backwards are cheap"}


def run(lm: LoadedModel, model_input_path: Path, method: str,
        labels: list[str], *,
        target_layer: str | None = None) -> tuple[ExplainOutput, float]:
    """Dispatch one method under the model lock, returning (output, ms).

    Serialized on the SAME lock inference uses: two model passes at once is
    how a 4 GB serving laptop gets OOM-killed mid-capture.
    """
    if method not in METHODS:
        raise ExplainError("UNKNOWN_METHOD",
                           f"method must be one of {', '.join(METHODS)}")
    # Planned BEFORE the lock: refusing takes microseconds, and a request that
    # cannot fit should not first wait behind one that can.
    plan = plan_memory(lm)
    t0 = time.perf_counter()
    with lm.lock:
        try:
            out = grad_cam(lm, model_input_path, labels, target_layer)
        except ApiError:
            raise
        except (MemoryError, RuntimeError) as exc:
            msg = str(exc).lower()
            if "memory" in msg or "alloc" in msg or "cannot allocate" in msg:
                raise ExplainError(
                    "EXPLAIN_OUT_OF_MEMORY",
                    f"Ran out of memory building the attribution "
                    f"(estimated {plan['estimated_need_mb']} MB needed, "
                    f"{plan['available_mb']} MB available). Try fewer labels.",
                    status=507) from exc
            raise ExplainError("EXPLAIN_FAILED",
                               f"{method} failed: {exc}", status=500) from exc
    out.meta["memory"] = plan
    return out, (time.perf_counter() - t0) * 1000.0
