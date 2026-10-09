"""★ THE parity test (plan §9.4, Required).

One synthetic corpus sheet pushed through BOTH chains, asserted identical, for
each geometry the app can serve:

  round-2 square (768x768), reference = cardiosentry_hybrids_v1:
      prepare_dataset._one
          PIL open -> convert("RGB") -> resize((768,768), BICUBIC)
          -> JPEG q95 optimize=True        [writes the 768 dataset copy]
      + data.build_view_transform(768)     -> ToTensor -> Normalize

  round-3 native aspect (768x1024), reference = cardiosentry_hybrids_v2:
      resize_dataset._one
          PIL open -> convert("RGB") -> resize((1024,768), BICUBIC)
          -> JPEG q95 optimize=True
      + data.build_transforms(train=False) -> ToTensor -> Normalize

  app chain (backend/services/preprocess.py), both cases:
      corrected 1686x1311 RGB -> PIL resize BICUBIC -> in-memory JPEG q95
      -> decode -> ToTensor -> Normalize

The round-3 reference runs with redaction OFF, because the app does not redact
uploaded photographs (see preprocess.py, "THE ONE DELIBERATE DIVERGENCE"). What
this test therefore pins is the geometry and the encoder — the resize is
(h, w) = (768, 1024) and the q95 round-trip is the same operator — which is the
part that must be bit-identical. The header band is a known, documented and
deliberate train/serve difference, not a pipeline bug, and is worth ~1e-4 on
the fixture sheet's scores.

Without this test every real-world result is uninterpretable: a score drop
could be the photograph or a resize kernel, and nobody could tell which. It
should fail before the first real capture is collected.

The two prototype packages both expose top-level `config` / `data` /
`dimensions` modules, so importing them into the same interpreter would leave
whichever ran first in `sys.modules`. The v2 reference therefore runs in a
SUBPROCESS with its own sys.path and hands back a .npy — the v1 test keeps the
in-process import it has always used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

PROTO_DIR = Path(__file__).resolve().parents[2] / "prototype-code" / "cardiosentry_hybrids_v1"


def _load_training_code():
    assert PROTO_DIR.is_dir(), f"prototype code not found at {PROTO_DIR}"
    if str(PROTO_DIR) not in sys.path:
        sys.path.insert(0, str(PROTO_DIR))
    import prepare_dataset
    import data as D
    import config as C
    return prepare_dataset, D, C


def test_app_chain_matches_training_chain_768(fixtures):
    prepare_dataset, D, C = _load_training_code()
    from backend.services import preprocess as prep

    sheet = fixtures / "corpus_sheet.jpg"

    # ---- reference (training) path -----------------------------------------
    # prepare_dataset._one is the exact function that built the training copy.
    dst = fixtures / "_tmp_train768.jpg"
    prepare_dataset._one((sheet, dst, C.LOAD_SIZE, 95))
    assert dst.is_file()
    try:
        view_tf = D.build_view_transform(C.LOAD_SIZE)   # 768: no resize step
        with Image.open(dst) as im:
            ref = view_tf(im.convert("RGB")).unsqueeze(0)
    finally:
        dst.unlink(missing_ok=True)

    # ---- app path -----------------------------------------------------------
    with Image.open(sheet) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    res = prep.preprocess_corrected(rgb, input_size=768,
                                    match_training_jpeg=True, jpeg_quality=95)
    app_tensor = res.tensor

    assert app_tensor.shape == ref.shape == (1, 3, 768, 768)
    max_diff = float((app_tensor - ref).abs().max())
    assert max_diff < 1e-6, (
        f"app chain diverged from the training chain by {max_diff:.2e} — the "
        "two pipelines are NOT interchangeable; stop and find the difference "
        "before collecting real data (§9.3).")


def test_app_384_view_matches_training_384_view(fixtures):
    """The dual-stream 384 view must derive exactly like training did: one
    BICUBIC step down from the same decoded 768 image."""
    prepare_dataset, D, C = _load_training_code()
    from backend.services import preprocess as prep
    from backend.services import runner
    from backend.schemas.model_descriptor import ModelDescriptor

    sheet = fixtures / "corpus_sheet.jpg"
    with Image.open(sheet) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    res = prep.preprocess_corrected(rgb, input_size=768, match_training_jpeg=True)

    tmp = fixtures / "_tmp_input768.png"
    tmp.write_bytes(res.model_input_png)

    class _LM:
        views = [(384, 384), (768, 768)]
        descriptor = ModelDescriptor.model_validate({
            "id": "x", "display_name": "x", "weights": "w.pt",
            "architecture": {"module": "arch.hybrids_v1",
                             "registry_key": "resnet50_hires",
                             "call_style": "view_dict", "views": [384, 768]},
            "labels": ["STEMI", "AF", "LVH", "NORMAL"],
        })
    try:
        views, _ = runner.derive_views(_LM(), tmp, (0.485, 0.456, 0.406),
                                       (0.229, 0.224, 0.225))

        with Image.open(tmp) as im:
            img768 = im.convert("RGB")
        ref384 = D.build_view_transform(384)(img768).unsqueeze(0)

        assert torch.allclose(views[(384, 384)], ref384, atol=1e-6, rtol=1e-6)
        # And the 768 view must be the tensor as stored — zero resampling.
        assert torch.equal(views[(768, 768)], res.tensor)
    finally:
        tmp.unlink(missing_ok=True)


def test_jpeg_roundtrip_reproduces_training_encoder(fixtures):
    """match_training_jpeg=False must be a real, measurable difference, and
    the round-trip must exactly reproduce prepare_dataset's encoder settings
    (quality=95, optimize=True)."""
    prepare_dataset, D, C = _load_training_code()
    from backend.services import preprocess as prep

    sheet = fixtures / "corpus_sheet.jpg"
    with Image.open(sheet) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)

    with_jpeg = prep.preprocess_corrected(rgb, input_size=768,
                                          match_training_jpeg=True).tensor
    without_jpeg = prep.preprocess_corrected(rgb, input_size=768,
                                             match_training_jpeg=False).tensor
    diff = float((with_jpeg - without_jpeg).abs().max())
    assert diff > 0, "the q95 round-trip had no effect — the flag is not wired"
    # The 1mm grid is high-frequency content: q95 ringing legitimately moves a
    # few normalized pixels by several tenths. The bound just catches a broken
    # (e.g. q10) encoder.
    assert diff < 1.0, f"suspiciously large round-trip effect: {diff}"


# --------------------------------------------------------------------------
# round-3 (hybrids_v2): the sheet's native aspect
# --------------------------------------------------------------------------
PROTO_V2_DIR = (Path(__file__).resolve().parents[2] / "prototype-code"
                / "cardiosentry_hybrids_v2")

# Runs inside the v2 package's own sys.path — see the module docstring for why
# this cannot be an in-process import.
_V2_REFERENCE = r'''
import sys
from pathlib import Path
sys.path.insert(0, PROTO)
import numpy as np
import config as C
import data as D
import resize_dataset as RD

assert tuple(C.IMG_SIZE) == (768, 1024), C.IMG_SIZE
assert not C.CROP_HEADER, C.CROP_HEADER
# The corpus was built with C.REDACT_HEADER on; this reference passes False
# because the app deliberately does not redact. Asserting the flag is what it
# is keeps the difference visible rather than accidental.
assert C.REDACT_HEADER, "hybrids_v2 nat768 is expected to be a redacting geometry"

# 1. what built the training corpus, minus the redaction: resize -> JPEG q95
res = RD._one((Path(SHEET), Path(DST), C.IMG_SIZE, C.CROP_HEADER, False, 95))
assert not isinstance(res, str), res

# 2. exactly what the eval loader then did with that file. The corpus folder
#    carries the crop/redact baked in, so manifest.check_geometry turns both
#    off at runtime; pass that decision explicitly rather than importing the
#    marker machinery.
from PIL import Image
tf = D.build_transforms(train=False, apply_crop=False, apply_redact=False)
with Image.open(DST) as im:
    t = tf(im.convert("RGB")).unsqueeze(0)
np.save(OUT, t.numpy())
'''


def _v2_reference_tensor(sheet: Path, tmp: Path) -> "torch.Tensor":
    """Run the hybrids_v2 training chain on `sheet`, out of process."""
    import subprocess
    assert PROTO_V2_DIR.is_dir(), f"prototype code not found at {PROTO_V2_DIR}"
    dst, out = tmp / "_ref_nat768.jpg", tmp / "_ref_nat768.npy"
    prelude = (f"PROTO = {str(PROTO_V2_DIR)!r}\n"
               f"SHEET = {str(sheet)!r}\n"
               f"DST = {str(dst)!r}\n"
               f"OUT = {str(out)!r}\n")
    env = {**os.environ, "CS_DIM": "nat768"}
    r = subprocess.run([sys.executable, "-c", prelude + _V2_REFERENCE],
                       capture_output=True, text=True, env=env, cwd=str(PROTO_V2_DIR))
    if r.returncode != 0:
        pytest.fail("hybrids_v2 reference chain failed:\n"
                    f"{r.stdout}\n{r.stderr}")
    try:
        return torch.from_numpy(np.load(out))
    finally:
        dst.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def test_app_chain_matches_training_chain_nat768(fixtures, tmp_path):
    """The ACTIVE model's geometry: 768x1024, the sheet's own aspect.

    The load-bearing assertion is that the resize is (h, w) = (768, 1024): a
    transposed pair still trains, still scores, and is silently wrong. The
    reference runs unredacted to match what the app actually does — see the
    module docstring.
    """
    from backend.services import preprocess as prep

    sheet = fixtures / "corpus_sheet.jpg"
    ref = _v2_reference_tensor(sheet, tmp_path)

    with Image.open(sheet) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    res = prep.preprocess_corrected(
        rgb, input_size=(768, 1024), match_training_jpeg=True, jpeg_quality=95)

    assert res.tensor.shape == ref.shape == (1, 3, 768, 1024)
    max_diff = float((res.tensor - ref).abs().max())
    assert max_diff < 1e-6, (
        f"app chain diverged from the hybrids_v2 training chain by "
        f"{max_diff:.2e} — the two pipelines are NOT interchangeable (§9.3).")


# ---------------------------------------------------------------- clean12 fit
CLEAN12_RENDER_NB = (Path(__file__).resolve().parents[2] / "prototype-code"
                     / "clean_convnext_codes" / "clean12_ecg_signal_images_ec2"
                     / "Clean12_ECG_Signal_Images_EC2.ipynb")


def _clean12_to_final():
    """`to_final` and `_paper_colour` taken from the clean12 render worker's
    source in the notebook, so the reference cannot drift from what rendered
    the training images."""
    import ast
    import json

    nb = json.loads(CLEAN12_RENDER_NB.read_text(encoding="utf-8"))
    src = "\n".join("".join(c["source"]) for c in nb["cells"]
                    if c["cell_type"] == "code")
    start = src.index("WORKER_SOURCE = r'''") + len("WORKER_SOURCE = r'''")
    worker = src[start:src.index("'''", start)]
    keep = [n for n in ast.parse(worker).body
            if isinstance(n, ast.FunctionDef) and n.name in ("to_final", "_paper_colour")
            or isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in ("FINAL_W", "FINAL_H", "RESIZE_H")
                for target in n.targets
                for t in (target.elts if isinstance(target, ast.Tuple) else [target]))
            or isinstance(n, ast.ClassDef) and n.name == "InvalidRecordError"]
    ns = {"np": np, "Image": Image}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "clean12_worker", "exec"), ns)
    return ns["to_final"]


def _synthetic_sheet(w: int, h: int) -> Image.Image:
    rng = np.random.default_rng(7)
    arr = np.full((h, w, 3), (253, 249, 247), dtype=np.uint8)
    arr[::8, :] = (228, 180, 176)
    arr[:, ::8] = (228, 180, 176)
    arr[::40, :] = (178, 86, 84)
    arr[:, ::40] = (178, 86, 84)
    ys = (h * (0.3 + 0.1 * np.sin(np.linspace(0, 60, w)))).astype(int)
    arr[ys, np.arange(w)] = (20, 20, 20)
    arr[rng.integers(0, h, 500), rng.integers(0, w, 500)] = (20, 20, 20)
    return Image.fromarray(arr, "RGB")


@pytest.mark.skipif(not CLEAN12_RENDER_NB.is_file(), reason="clean12 render notebook absent")
@pytest.mark.parametrize("sheet_wh", [(2200, 1700), (1650, 1275)])
def test_height_pad_matches_clean12_render(sheet_wh):
    """fit=height_pad on a rectified sheet (+ the rectify paper margin) must be
    bit-identical to the clean12 worker's to_final on the bare sheet: LANCZOS
    fit to height 768, symmetric pad to 1024 with the p90 corner colour."""
    from backend.services import preprocess as prep

    to_final = _clean12_to_final()
    sheet = _synthetic_sheet(*sheet_wh)
    ref = np.asarray(to_final(sheet), dtype=np.uint8)

    margin = 18
    corrected = np.pad(np.asarray(sheet), ((margin, margin), (margin, margin), (0, 0)),
                       constant_values=250)
    res = prep.preprocess_corrected(
        corrected, input_size=(768, 1024), match_training_jpeg=False,
        fit="height_pad", resample="pil_lanczos", margin_px=margin)
    with Image.open(__import__("io").BytesIO(res.model_input_png)) as im:
        got = np.asarray(im.convert("RGB"), dtype=np.uint8)

    assert got.shape == ref.shape == (768, 1024, 3)
    assert np.array_equal(got, ref), (
        f"height_pad diverged from the clean12 render by up to "
        f"{np.abs(got.astype(int) - ref.astype(int)).max()} grey levels")


def test_height_pad_wider_sheet_stays_inside_the_box():
    """A native_aspect sheet wider than 4:3 is fitted inside and padded on
    both axes instead of overflowing the width."""
    from backend.services import preprocess as prep

    sheet = np.asarray(_synthetic_sheet(1650, 1000))
    res = prep.preprocess_corrected(sheet, input_size=(768, 1024),
                                    match_training_jpeg=False, fit="height_pad",
                                    resample="pil_lanczos")
    assert res.tensor.shape == (1, 3, 768, 1024)


def test_stretch_is_still_the_default():
    from backend.services import preprocess as prep

    rgb = np.asarray(_synthetic_sheet(1686, 1311))
    a = prep.preprocess_corrected(rgb, input_size=(768, 1024), match_training_jpeg=False)
    b = prep.preprocess_corrected(rgb, input_size=(768, 1024), match_training_jpeg=False,
                                  fit="stretch", resample="pil_bicubic", margin_px=18)
    assert a.tensor_sha256 == b.tensor_sha256
