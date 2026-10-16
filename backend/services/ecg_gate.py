"""ECG gate: refuse uploads that are not an ECG before a capture exists.

`load_gate(id)` reads `models/gates/<id>.yaml` (settings.ecg_gate) and builds
the implementation its `kind` names; both expose `.id` and `.check(rgb)`:

- `ocr_lead_labels` -> services/ecg_gate_ocr.py (Tesseract reads the printed
  lead labels).
- `learned` -> `LoadedGate` below: a small head (LayerNorm -> Linear(1536, 256)
  -> GELU -> Dropout -> Linear(1)) trained on top of a FROZEN clean12
  ConvNeXt-V1 Tiny + RFPN
  (prototype-code/clean_convnext_codes/convnext_tiny_v1_rfpn_ecg_gate_colab_v1).
  Its input is that model's pooled, LayerNorm'd stage-4 vector (768, the
  ConvNeXt head's pre-logits) concatenated with the RFPN's pooled P3-P5 maps
  (3 x 256). It loads its own copy of the Tiny base, whatever model
  `models/active.yaml` names; the 12 diagnostic logits are never computed.
  Input chain = the gate dataset's build (EXIF-oriented RGB, LANCZOS thumbnail
  to 1600 px, JPEG q95) followed by the training `fit` geometry (the app's
  fit_height_pad to 768x1024). The run also trained a `rectify` geometry;
  only `fit` is served.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from PIL import Image
from torch import nn

from backend.schemas.ecg_gate import GATE_DESCRIPTOR, EcgGateInfo, LearnedGateDescriptor
from backend.services.ecg_gate_ocr import OcrLeadGate, OcrUnavailable, load_ocr_gate
from backend.services.preprocess import (as_hw, fit_height_pad, jpeg95_roundtrip,
                                         normalize_tensor, pil_from_rgb_array)
from backend.services.registry import resolve_arch_module, sha256_file
from backend.services.runner import _load_blob, _select_state
from backend.settings import settings

log = logging.getLogger("cardiosentry.ecg_gate")

GATE_DIR = "gates"


class GateLoadError(Exception):
    pass


class GateHead(nn.Module):
    """The training notebook's GateHead, parameter names included."""

    def __init__(self, in_features: int, hidden: int, dropout: float):
        super().__init__()
        self.norm = nn.LayerNorm(in_features)
        self.fc1 = nn.Linear(in_features, hidden)
        self.drop = nn.Dropout(dropout)
        self.fc2 = nn.Linear(hidden, 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.drop(F.gelu(self.fc1(self.norm(features))))).squeeze(1)


def gate_features(base: nn.Module, x: torch.Tensor, stage_indices) -> torch.Tensor:
    """The notebook's GatedRFPN.forward_features, minus the diagnostic logits:
    concat[backbone.forward_head(norm_pre(stage4), pre_logits=True),
    GAP(FPN P3, P4, P5)] in fp32."""
    backbone = base.backbone
    h = backbone.stem(x)
    stages = []
    for stage in backbone.stages:
        h = stage(h)
        stages.append(h)
    maps = base.neck([stages[i] for i in stage_indices])
    pooled = torch.cat([torch.mean(m, dim=(2, 3), dtype=torch.float32) for m in maps], dim=1)
    pre_logits = backbone.forward_head(backbone.norm_pre(h), pre_logits=True)
    return torch.cat([pre_logits.float(), pooled.float()], dim=1)


@dataclass
class LoadedGate:
    descriptor: LearnedGateDescriptor
    base: nn.Module
    head: GateHead
    stage_indices: tuple[int, ...]
    threshold: float
    checkpoint_sha256: str
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def id(self) -> str:
        return self.descriptor.id

    def input_tensor(self, rgb: np.ndarray) -> torch.Tensor:
        """Oriented upload (H, W, 3 uint8 RGB) -> normalized [1, 3, h, w]."""
        p = self.descriptor.preprocess
        img = pil_from_rgb_array(rgb)
        img.thumbnail((p.max_side, p.max_side), Image.Resampling.LANCZOS)
        if p.jpeg_quality is not None:
            img = jpeg95_roundtrip(img, p.jpeg_quality)
        sheet = fit_height_pad(img, as_hw(p.input_size), p.resample)
        return normalize_tensor(sheet, p.normalize.mean, p.normalize.std).unsqueeze(0)

    def score(self, x: torch.Tensor) -> float:
        """P(ECG) for one normalized input tensor."""
        with self.lock, torch.no_grad():
            logit = self.head(gate_features(self.base, x, self.stage_indices))
        return float(torch.sigmoid(logit)[0])

    def check(self, rgb: np.ndarray) -> EcgGateInfo:
        t0 = time.perf_counter()
        p = self.score(self.input_tensor(rgb))
        return EcgGateInfo(
            gate_id=self.id,
            kind="learned",
            checkpoint_sha256_short=self.checkpoint_sha256[:8],
            score=round(p, 6),
            threshold=self.threshold,
            accepted=p >= self.threshold,
            forward_ms=round((time.perf_counter() - t0) * 1000.0, 1))


EcgGate = LoadedGate | OcrLeadGate


def load_gate(gate_id: str) -> EcgGate:
    """Validate `models/gates/<gate_id>.yaml` and build the gate its kind names."""
    yp = settings.models_dir / GATE_DIR / f"{gate_id}.yaml"
    if not yp.is_file():
        raise GateLoadError(f"ECG gate descriptor not found: {yp} "
                            "(set CARDIOSENTRY_ECG_GATE to a file in models/gates/, "
                            "or to an empty value to disable the gate)")
    label = f"{GATE_DIR}/{yp.name}"
    try:
        desc = GATE_DESCRIPTOR.validate_python(yaml.safe_load(yp.read_text(encoding="utf-8")) or {})
    except Exception as exc:
        raise GateLoadError(f"{label}: invalid descriptor:\n  {exc}") from exc
    if desc.id != gate_id:
        raise GateLoadError(f"{label}: id {desc.id!r} does not match the file name")
    if desc.kind == "ocr_lead_labels":
        try:
            return load_ocr_gate(desc)
        except OcrUnavailable as exc:
            raise GateLoadError(f"{label}: {exc}") from exc
    return _load_learned(desc, label)


def _load_learned(desc: LearnedGateDescriptor, label: str) -> LoadedGate:
    """Load the descriptor's .pt strictly, then warm up."""
    weights = (settings.models_dir / desc.weights).resolve()
    if not weights.is_file() or weights.suffix != ".pt":
        raise GateLoadError(f"{label}: weights must be an existing .pt file: {weights}")
    sha = sha256_file(weights)
    if desc.expected_sha256 and desc.expected_sha256 != sha:
        raise GateLoadError(f"{label}: checkpoint sha256 mismatch — descriptor claims "
                            f"{desc.expected_sha256}, file is {sha}")

    arch_module = resolve_arch_module(desc.architecture.module,
                                      desc.architecture.registry_key, label)
    blob = _load_blob(weights)
    if not isinstance(blob, dict) or "gate_head" not in blob:
        raise GateLoadError(f"{label}: {weights.name} has no gate_head")
    fingerprint = blob.get("config_fingerprint") or blob.get("protocol_fingerprint")
    if desc.expected_protocol_fingerprint and fingerprint != desc.expected_protocol_fingerprint:
        raise GateLoadError(f"{label}: base fingerprint {fingerprint!r} != "
                            f"{desc.expected_protocol_fingerprint!r}")

    # strict=True for both parts: a partially loaded gate silently accepts or
    # rejects everything.
    base, _ = arch_module.build(desc.architecture.registry_key, False)
    state, _ = _select_state(desc.id, blob)
    base.load_state_dict(state, strict=True)
    spec = blob["gate_head_spec"]
    head = GateHead(int(spec["in_features"]), int(spec["hidden"]), float(spec["dropout"]))
    head.load_state_dict(blob["gate_head"], strict=True)
    base.eval()
    head.eval()

    if desc.threshold.source == "checkpoint":
        if "gate_threshold" not in blob:
            raise GateLoadError(f"{label}: threshold.source=checkpoint but the .pt "
                                "carries no gate_threshold")
        threshold = float(blob["gate_threshold"])
    else:
        threshold = float(desc.threshold.explicit)

    stage_indices = tuple(int(i) for i in blob.get("fusion_stage_indices", (1, 2, 3)))
    gate = LoadedGate(descriptor=desc, base=base, head=head, stage_indices=stage_indices,
                      threshold=threshold, checkpoint_sha256=sha)
    try:   # warm-up: the first CPU forward pays seconds of lazy init
        gate.score(torch.zeros(1, 3, *as_hw(desc.preprocess.input_size)))
    except Exception as exc:
        raise GateLoadError(f"{label}: warm-up forward failed:\n  {exc}") from exc
    log.info("ECG gate %s loaded (sha %s, threshold %.4g)", desc.id, sha[:8], threshold)
    return gate
