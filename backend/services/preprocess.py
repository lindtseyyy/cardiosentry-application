"""★ THE canonical training-input chain (plan §9). Do not edit casually.

This module reproduces the prototype's preprocessing exactly, so real-photo
scores are comparable to prototype scores. The training chain was:

    sheet 1686x1311 (post q85-JPEG stage-4 output)
      -> resize_dataset.py:   PIL open -> convert("RGB")
                              -> .resize((W,H), Image.BICUBIC)
                              -> RedactHeader (hybrids_v2 geometries only)
                              -> save JPEG quality=95, optimize=True
      -> data.py (eval):      PIL open -> convert("RGB")
                              -> [no resize: stored copy is already (H,W)]
                              -> ToTensor() -> Normalize(ImageNet)

The application chain mirrors it from the rectified sheet:

    corrected.png (lossless 1686x1311)
      -> PIL resize (W,H) BICUBIC              ← PIL, NOT OpenCV (§9.3.1)
      -> in-memory JPEG q95 round-trip         ← match_training_jpeg (§9.3.3)
      -> model_input.png (lossless, the exact tensorized pixels)
      -> ToTensor() -> Normalize(ImageNet)

THE ONE DELIBERATE DIVERGENCE. The hybrids_v2 corpus had a fixed rectangle
painted over the printed ID/Age/Sex block (`RedactHeader`), because the record
ID separates STEMI exactly in that synthetic corpus. **The application does not
redact.** An uploaded photograph is left as photographed: nothing is painted
over the sheet between the warp and the tensor. The consequence, which belongs
in any writeup of real-photo results: the model sees a header band it never saw
printed text in during training, and the app's score for a corpus sheet will not
reproduce that sheet's stored prototype score exactly. Everything else in this
chain is asserted identical (tests/test_preprocess_parity.py).

The target size is (height, width) throughout this module — torch order, the
same order the research code's `config.IMG_SIZE` uses, and the OPPOSITE of the
(w, h) PIL's `Image.resize` wants. Getting it backwards produces a portrait ECG
that still scores and is silently wrong, so the swap happens at exactly one
line (`_resize`) rather than at every call site.

Non-obvious requirements (§9.3), each a real bug if ignored:
  1. The final resize must be PIL BICUBIC — cv2.resize(INTER_CUBIC) is a
     different operator (no anti-aliasing support scaling) and the 1mm grid is
     exactly the high-frequency content that aliases.
  2. Channel order: OpenCV is BGR, PIL/torch are RGB. Convert once, at one
     named line (see `_pil_from_array`).
  3. The q95 round-trip happens BEFORE model_input.png is saved, so the PNG
     contains the post-JPEG pixels (§13.1).
  4. The tensor sha256 is recorded so a run can later prove which pixels were
     scored (§13.3).

THE SECOND GEOMETRY (`fit="height_pad"`). The HEEDB clean12 corpus was not
stretched to its input size. Its render worker took the edge-to-edge 2200x1700
kit master, resized it LANCZOS to height 768 keeping the aspect (994x768), and
padded it symmetrically to 1024x768 with the paper colour (the 90th percentile
of the four corner patches). `fit="height_pad"` reproduces that from the
rectified sheet: the rectify paper margin is cropped off first (the training
sheets have none), then the same fit, the same pad width and the same paper
colour rule. A sheet wider than the target aspect (only possible with
`native_aspect` geometry) is fitted inside the box and padded on both axes,
which reduces to the training operation for every training-aspect sheet.
"""
from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T


def as_hw(size) -> tuple[int, int]:
    """Normalize a descriptor `input_size` / view size to (height, width)."""
    if isinstance(size, int):
        return (size, size)
    h, w = size
    return (int(h), int(w))


_RESAMPLE = {"pil_bicubic": Image.BICUBIC, "pil_lanczos": Image.LANCZOS}


def resize_hw(img: Image.Image, size, resample: str = "pil_bicubic") -> Image.Image:
    """THE (h, w) -> PIL (w, h) swap. The only place in the app that reorders
    the pair, so a transposed input can only ever come from here."""
    h, w = as_hw(size)
    if (img.width, img.height) == (w, h):
        return img
    return img.resize((w, h), _RESAMPLE[resample])


def paper_colour_p90(img: Image.Image) -> tuple[int, int, int]:
    """The clean12 render worker's `_paper_colour`, verbatim in behavior: the
    90th percentile of the four corner patches (a median is dragged toward the
    grid tint by antialiased halo pixels; p90 recovers the paper white)."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]
    k = max(8, min(h, w) // 40)
    patches = np.concatenate([
        arr[:k, :k].reshape(-1, 3), arr[:k, -k:].reshape(-1, 3),
        arr[-k:, :k].reshape(-1, 3), arr[-k:, -k:].reshape(-1, 3)])
    return tuple(int(v) for v in np.percentile(patches, 90, axis=0))


def fit_height_pad(img: Image.Image, size, resample: str = "pil_lanczos") -> Image.Image:
    """Aspect-preserving fit into (h, w) plus a centred paper-colour pad — the
    clean12 `to_final` (fit to height 768, pad to 1024x768). The scale is
    min(h/H, w/W) so a sheet wider than the box cannot overflow it; for every
    sheet at the training aspect that is the height fit the worker used."""
    h, w = as_hw(size)
    scale = min(h / img.height, w / img.width)
    new_w = min(w, round(img.width * scale))
    new_h = min(h, round(img.height * scale))
    small = img.convert("RGB").resize((new_w, new_h), _RESAMPLE[resample])
    if (new_w, new_h) == (w, h):
        return small
    canvas = Image.new("RGB", (w, h), paper_colour_p90(small))
    canvas.paste(small, ((w - new_w) // 2, (h - new_h) // 2))
    return canvas


def pil_from_rgb_array(arr_rgb: np.ndarray) -> Image.Image:
    """ndarray (H,W,3) uint8 RGB -> PIL RGB. THE named BGR->RGB conversion point:
    callers are responsible for having converted OpenCV BGR output to RGB before
    this line (see rectify.py, which produces RGB throughout)."""
    return Image.fromarray(np.ascontiguousarray(arr_rgb), mode="RGB")


def jpeg95_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    """Encode->decode through a JPEG in memory, reproducing the training
    pipeline's second JPEG generation (prepare_dataset saved quality=95,
    optimize=True, and eval re-opened that file)."""
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    buf.seek(0)
    with Image.open(buf) as im:
        im.load()
        return im.convert("RGB")


def normalize_tensor(pil_img: Image.Image, mean, std) -> torch.Tensor:
    tf = T.Compose([T.ToTensor(), T.Normalize(mean=mean, std=std)])
    return tf(pil_img)


def tensor_sha256(t: torch.Tensor) -> str:
    return hashlib.sha256(t.detach().cpu().numpy().tobytes()).hexdigest()


class PreprocessResult:
    def __init__(self, tensor: torch.Tensor, model_input_png: bytes,
                 tensor_sha: str, ms: float, input_hw: tuple[int, int]):
        self.tensor = tensor                  # [1,3,H,W] float32, normalized
        self.model_input_png = model_input_png
        self.tensor_sha256 = tensor_sha
        self.ms = ms
        self.input_hw = input_hw              # (height, width)

    @property
    def input_size(self) -> list[int]:
        """[height, width] — what the API and the capture record store."""
        return list(self.input_hw)


def preprocess_corrected(corrected_rgb: np.ndarray, *,
                         input_size,
                         match_training_jpeg: bool = True,
                         jpeg_quality: int = 95,
                         mean=(0.485, 0.456, 0.406),
                         std=(0.229, 0.224, 0.225),
                         fit: str = "stretch",
                         resample: str = "pil_bicubic",
                         margin_px: int = 0) -> PreprocessResult:
    """Run the full canonical chain on the rectified sheet (RGB ndarray).

    `input_size` is an int (square) or (height, width). `fit="stretch"` resizes
    the whole rectified sheet, margin included, to the input size (every
    pre-clean12 model). `fit="height_pad"` crops the `margin_px` rectify border
    and runs the clean12 fit-and-pad (module docstring). Returns the normalized
    [1,3,H,W] tensor, the exact post-JPEG pixels as lossless PNG bytes, the
    tensor sha256, and elapsed ms.
    """
    t0 = time.perf_counter()
    hw = as_hw(input_size)

    img = pil_from_rgb_array(corrected_rgb)
    if fit == "stretch":
        img = resize_hw(img, hw, resample)
    elif fit == "height_pad":
        m = int(margin_px)
        if m < 0 or 2 * m >= min(img.width, img.height):
            raise ValueError(f"margin_px={m} does not fit a {img.width}x{img.height} sheet")
        if m:
            img = img.crop((m, m, img.width - m, img.height - m))
        img = fit_height_pad(img, hw, resample)
    else:
        raise ValueError(f"unknown fit {fit!r}")

    if match_training_jpeg:
        img = jpeg95_roundtrip(img, jpeg_quality)

    png_buf = io.BytesIO()
    img.save(png_buf, "PNG")
    model_input_png = png_buf.getvalue()

    tensor = normalize_tensor(img, mean, std).unsqueeze(0)
    ms = (time.perf_counter() - t0) * 1000.0
    return PreprocessResult(tensor, model_input_png, tensor_sha256(tensor), ms, hw)


def tensor_from_model_input(path: Path, *, mean=(0.485, 0.456, 0.406),
                            std=(0.229, 0.224, 0.225)) -> torch.Tensor:
    """Rebuild the exact tensor from a stored model_input.png (no re-encoding,
    no resize — the stored pixels ARE the tensorized pixels). Used by
    reprocess.py so re-runs score bit-identical inputs."""
    with Image.open(path) as im:
        im.load()
        img = im.convert("RGB")
    return normalize_tensor(img, mean, std).unsqueeze(0)


def load_corrected_rgb(path: Path) -> np.ndarray:
    """Decode a stored corrected.png into the RGB grid the chain consumes."""
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"), dtype=np.uint8)
