"""ECG gate: descriptor schemas (models/gates/*.yaml) and the per-capture result.

The gate answers one question before a capture is created — is this upload a
photograph or scan of an ECG sheet at all? Like a diagnostic model it is data:
one YAML, validated at startup, chosen by `CARDIOSENTRY_ECG_GATE`. Its `kind`
picks the implementation:

- `learned`: a `.pt` gate head over a frozen backbone (services/ecg_gate.py).
- `ocr_lead_labels`: Tesseract reads the printed lead labels and the upload
  passes when enough distinct ones are found (services/ecg_gate_ocr.py).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.schemas.model_descriptor import NormalizeSpec

# The twelve standard leads, as the OCR gate normalises tokens (upper case).
STANDARD_LEADS = ("I", "II", "III", "AVR", "AVL", "AVF",
                  "V1", "V2", "V3", "V4", "V5", "V6")


class GateArchitectureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str                    # vendored package under backend/arch/
    registry_key: str              # the frozen base model the head reads features from


class GateThresholdSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["checkpoint", "explicit"] = "checkpoint"
    explicit: float | None = None  # P(ECG) at or above this is accepted

    @model_validator(mode="after")
    def _check(self):
        if self.source == "explicit" and self.explicit is None:
            raise ValueError("threshold.source=explicit requires threshold.explicit")
        if self.explicit is not None and not 0.0 < self.explicit < 1.0:
            raise ValueError("threshold.explicit must be in (0, 1)")
        return self


class GatePreprocessSpec(BaseModel):
    """The gate dataset's image chain, then the `fit` training geometry."""
    model_config = ConfigDict(extra="forbid")
    max_side: int = Field(default=1600, gt=0)      # dataset build: LANCZOS thumbnail
    jpeg_quality: int | None = Field(default=95, ge=1, le=100)   # dataset build: JPEG q95
    input_size: list[int] = [768, 1024]             # [height, width] — torch order
    resample: Literal["pil_bicubic", "pil_lanczos"] = "pil_lanczos"
    normalize: NormalizeSpec = Field(default_factory=NormalizeSpec)

    @model_validator(mode="after")
    def _check(self):
        if len(self.input_size) != 2 or min(self.input_size) <= 0:
            raise ValueError("preprocess.input_size must be [height, width] > 0")
        if len(self.normalize.mean) != 3 or len(self.normalize.std) != 3:
            raise ValueError("normalize mean/std must have 3 channels")
        return self


class LearnedGateDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    kind: Literal["learned"]
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str
    notes: str = ""
    weights: str                               # path relative to models/
    expected_sha256: str | None = None         # mismatch = refuse to start
    expected_protocol_fingerprint: str | None = None
    architecture: GateArchitectureSpec
    threshold: GateThresholdSpec = Field(default_factory=GateThresholdSpec)
    preprocess: GatePreprocessSpec = Field(default_factory=GatePreprocessSpec)


class OcrCleanupSpec(BaseModel):
    """One way of turning the photo into black glyphs on white before OCR.

    Ink = pixels darker than `ink_ratio` x their local paper brightness (a
    dilated, blurred background), so shading and creases drop out. Connected
    ink blobs are kept only if they are character-sized; long blobs (traces,
    grid lines, borders) are removed. Sizes are fractions of the resized image.
    """
    model_config = ConfigDict(extra="forbid")
    # "max": max(R,G,B) — a coloured (red/pink) grid stays bright and vanishes.
    # "min": min(R,G,B) — keeps a black/grey grid, so pair it with grid_lines.
    channel: Literal["max", "min"]
    remove_grid_lines: bool = False
    ink_ratio: float = Field(default=0.55, gt=0.0, lt=1.0)
    char_height: tuple[float, float] = (0.004, 0.05)
    max_char_width: float = Field(default=0.06, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self):
        lo, hi = self.char_height
        if not 0.0 < lo < hi <= 1.0:
            raise ValueError("char_height must be 0 < low < high <= 1")
        return self


class OcrSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["tesseract"] = "tesseract"
    resize_max_side: int = Field(default=2400, ge=600)   # up- or down-scaled to this
    psm: int = Field(default=11, ge=0, le=13)            # 11 = sparse text
    char_whitelist: str | None = None
    timeout_s: float = Field(default=20.0, gt=0.0)       # per Tesseract call


class OcrGateDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    kind: Literal["ocr_lead_labels"]
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str
    notes: str = ""
    # Only these labels count towards min_leads; every standard lead read is
    # still reported in `leads_found`.
    counted_leads: list[str]
    min_leads: int = Field(ge=1)
    ocr: OcrSpec = Field(default_factory=OcrSpec)
    # Run in parallel; labels found are unioned in this order, and the check
    # returns once the counted ones reach min_leads.
    cleanup: list[OcrCleanupSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        unknown = set(self.counted_leads) - set(STANDARD_LEADS)
        if unknown:
            raise ValueError(f"counted_leads: not standard lead names {sorted(unknown)}; "
                             f"use {list(STANDARD_LEADS)}")
        if len(set(self.counted_leads)) != len(self.counted_leads):
            raise ValueError("counted_leads has duplicates")
        if self.min_leads > len(self.counted_leads):
            raise ValueError("min_leads exceeds the number of counted_leads")
        return self


GateDescriptor = Annotated[Union[LearnedGateDescriptor, OcrGateDescriptor],
                           Field(discriminator="kind")]
GATE_DESCRIPTOR = TypeAdapter(GateDescriptor)


class EcgGateInfo(BaseModel):
    """What the gate said about an accepted capture (stored in its record)."""
    gate_id: str
    kind: Literal["learned", "ocr_lead_labels"] = "learned"
    # learned: P(ECG) vs a probability threshold.
    # ocr_lead_labels: distinct counted lead labels read vs min_leads.
    score: float
    threshold: float
    accepted: bool
    forward_ms: float
    checkpoint_sha256_short: str | None = None     # learned only
    leads_found: list[str] | None = None           # ocr only, all standard leads read
