"""OCR ECG gate: accept an upload when its printed lead labels can be read.

A 12-lead sheet prints its lead names (I, II, III, aVR, aVL, aVF, V1-V6) beside
the traces; EEG strips, charts, receipts and photos do not. The gate resizes the
oriented upload, turns it into black character-sized glyphs on white (one or
more `cleanup` passes from the descriptor), runs Tesseract on each pass, and
counts the distinct `counted_leads` it reads. At least `min_leads` = ECG.

Why the passes look like this (measured 2026-10-15 on the ecg_gate_v1 test
split + synthetic EEG sheets; models/README.md §ECG gate has the table):
- Reading the raw photo finds 3-5 labels at best: the grid and the traces
  break Tesseract's page layout. Removing every non-character-sized ink blob
  leaves the labels almost alone on white.
- `channel: max` deletes a red/pink grid outright; a black-grid scan needs
  `channel: min` + grid-line removal, run only if the first pass falls short.
- I, II and III are read as noise ("I" on half of the non-ECG images), so the
  shipped descriptor leaves them out of `counted_leads`; they are reported only.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

from backend.schemas.ecg_gate import STANDARD_LEADS, EcgGateInfo, OcrCleanupSpec, OcrGateDescriptor

log = logging.getLogger("cardiosentry.ecg_gate")

# Each pass is one Tesseract subprocess, so passes run truly in parallel.
_PASSES = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ecg-gate-ocr")
TESSERACT = "tesseract"
_TESSERACT_ENV = os.environ | {"OMP_THREAD_LIMIT": "1"}
_SPLIT = re.compile(r"[\s,;:]+")
_STRIP = ".-_|'\"()[]{}"
_STANDARD = frozenset(STANDARD_LEADS)


class OcrUnavailable(Exception):
    pass


def leads_in_text(text: str) -> set[str]:
    """Standard lead names among the OCR tokens ("-aVR", "aVF:" and "v1" included)."""
    found = set()
    for token in _SPLIT.split(text):
        name = token.strip(_STRIP).upper()
        if name in _STANDARD:
            found.add(name)
    return found


def resize_max_side(rgb: np.ndarray, max_side: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    s = max_side / max(h, w)
    if s == 1.0:
        return rgb
    interp = cv2.INTER_CUBIC if s > 1.0 else cv2.INTER_AREA
    return cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=interp)


def glyph_image(rgb: np.ndarray, spec: OcrCleanupSpec) -> np.ndarray:
    """uint8 image: character-sized ink blobs black (0), everything else white."""
    g = (rgb.max(axis=2) if spec.channel == "max" else rgb.min(axis=2)).astype(np.float32)
    k = max(15, (min(g.shape) // 40) | 1)
    paper = cv2.dilate(g, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    paper = cv2.GaussianBlur(paper, (0, 0), k / 2)
    ink = (g / np.maximum(paper, 1.0) < spec.ink_ratio).astype(np.uint8)
    h, w = ink.shape
    if spec.remove_grid_lines:
        horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 40), 1)))
        vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, h // 25))))
        ink = ink & ~(horiz | vert) & 1
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    lo, hi = spec.char_height
    bh, bw, area = stats[:, cv2.CC_STAT_HEIGHT], stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_AREA]
    keep = (bh >= lo * h) & (bh <= hi * h) & (bw <= spec.max_char_width * w) & (area >= 6)
    keep[0] = False        # background label
    return np.where(keep[labels], 0, 255).astype(np.uint8)


@dataclass
class OcrLeadGate:
    descriptor: OcrGateDescriptor
    tesseract_version: str

    @property
    def id(self) -> str:
        return self.descriptor.id

    def _tesseract_args(self) -> list[str]:
        o = self.descriptor.ocr
        args = [TESSERACT, "stdin", "stdout", "--psm", str(o.psm)]
        if o.char_whitelist:
            args += ["-c", f"tessedit_char_whitelist={o.char_whitelist}"]
        return args

    def _read_pass(self, img: np.ndarray, spec: OcrCleanupSpec) -> set[str]:
        ok, png = cv2.imencode(".png", glyph_image(img, spec))
        if not ok:
            raise RuntimeError("PNG encode of the glyph image failed")
        try:
            # OMP_THREAD_LIMIT=1: Tesseract's own OpenMP threads, oversubscribed
            # by parallel passes, made one 9 s pass exceed 20 s.
            proc = subprocess.run(self._tesseract_args(), input=png.tobytes(),
                                  capture_output=True, timeout=self.descriptor.ocr.timeout_s,
                                  env=_TESSERACT_ENV, check=False)
        except subprocess.TimeoutExpired:
            # So cluttered that no label was read in time: counts as none found.
            log.warning("ECG gate %s: Tesseract pass (%s) timed out after %.0f s",
                        self.id, spec.channel, self.descriptor.ocr.timeout_s)
            return set()
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract exited {proc.returncode}: "
                               f"{proc.stderr.decode(errors='replace')[-300:]}")
        return leads_in_text(proc.stdout.decode("utf-8", errors="replace"))

    def read_leads(self, rgb: np.ndarray) -> set[str]:
        """Every standard lead read over the cleanup passes. All passes start at
        once; results are unioned in descriptor order and returned as soon as
        the counted ones reach min_leads (later passes finish unused), so a
        clear sheet costs one pass and a rejection the slowest one."""
        d = self.descriptor
        img = resize_max_side(rgb, d.ocr.resize_max_side)
        counted = set(d.counted_leads)
        passes = [_PASSES.submit(self._read_pass, img, spec) for spec in d.cleanup]
        found: set[str] = set()
        for p in passes:
            found |= p.result()
            if len(found & counted) >= d.min_leads:
                break
        return found

    def check(self, rgb: np.ndarray) -> EcgGateInfo:
        t0 = time.perf_counter()
        found = self.read_leads(rgb)
        n = len(found & set(self.descriptor.counted_leads))
        return EcgGateInfo(
            gate_id=self.id,
            kind="ocr_lead_labels",
            score=float(n),
            threshold=float(self.descriptor.min_leads),
            accepted=n >= self.descriptor.min_leads,
            forward_ms=round((time.perf_counter() - t0) * 1000.0, 1),
            leads_found=[lead for lead in STANDARD_LEADS if lead in found])


def load_ocr_gate(desc: OcrGateDescriptor) -> OcrLeadGate:
    """Check the OCR engine is installed and runs, then return the gate."""
    if shutil.which(TESSERACT) is None:
        raise OcrUnavailable("the tesseract binary is not on PATH "
                             "(Debian/Ubuntu: sudo apt install tesseract-ocr)")
    out = subprocess.run([TESSERACT, "--version"], capture_output=True, text=True, check=False)
    first = (out.stdout or out.stderr).splitlines()
    gate = OcrLeadGate(descriptor=desc,
                       tesseract_version=first[0].removeprefix("tesseract ") if first else "?")
    try:   # one real call: a broken install fails here, not on the first upload
        gate.read_leads(np.full((600, 800, 3), 255, np.uint8))
    except Exception as exc:
        raise OcrUnavailable(f"Tesseract warm-up call failed: {exc}") from exc
    log.info("ECG gate %s loaded (OCR lead labels, Tesseract %s, >= %d of %d)",
             desc.id, gate.tesseract_version, desc.min_leads, len(desc.counted_leads))
    return gate
