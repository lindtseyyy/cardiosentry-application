from __future__ import annotations

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from backend.schemas.ecg_gate import GATE_DESCRIPTOR
from backend.services.ecg_gate_ocr import OcrLeadGate, leads_in_text
from backend.settings import settings

GATE_YAMLS = sorted((settings.models_dir / "gates").glob("*.yaml"))


def _ocr_descriptor(**over):
    raw = {
        "kind": "ocr_lead_labels",
        "id": "ocr_test",
        "display_name": "OCR test",
        "counted_leads": ["AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6"],
        "min_leads": 4,
        "cleanup": [{"channel": "max"}],
    }
    return GATE_DESCRIPTOR.validate_python(raw | over)


def test_lead_tokens_are_normalised_and_eeg_channels_are_not_leads():
    text = "-aVR\naVF: v1 V1, II\nFp1-F7 C3 T4 O1 IV aVRx V7 aVL."
    assert leads_in_text(text) == {"AVR", "AVF", "V1", "II", "AVL"}


@pytest.mark.parametrize("path", GATE_YAMLS, ids=lambda p: p.stem)
def test_every_shipped_gate_descriptor_validates(path):
    desc = GATE_DESCRIPTOR.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert desc.id == path.stem


def test_default_gate_exists():
    assert settings.ecg_gate in {p.stem for p in GATE_YAMLS}


@pytest.mark.parametrize("over", [
    {"min_leads": 10},                          # more than can be counted
    {"counted_leads": ["AVR", "aVL"]},          # names are upper case
    {"counted_leads": ["AVR", "AVR"], "min_leads": 1},
])
def test_ocr_descriptor_rejects_impossible_rules(over):
    with pytest.raises(ValidationError):
        _ocr_descriptor(**over)


def test_only_counted_leads_reach_the_threshold(monkeypatch):
    gate = OcrLeadGate(descriptor=_ocr_descriptor(), tesseract_version="test")
    rgb = np.zeros((10, 10, 3), np.uint8)

    monkeypatch.setattr(gate, "read_leads", lambda _: {"I", "II", "III", "AVR", "AVL", "AVF"})
    info = gate.check(rgb)
    assert (info.score, info.accepted) == (3.0, False)
    assert info.leads_found == ["I", "II", "III", "AVR", "AVL", "AVF"]

    monkeypatch.setattr(gate, "read_leads", lambda _: {"AVR", "AVL", "AVF", "V6"})
    info = gate.check(rgb)
    assert (info.score, info.threshold, info.accepted) == (4.0, 4.0, True)
