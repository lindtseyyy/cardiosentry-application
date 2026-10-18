"""Shared test configuration.

Environment overrides MUST be set before any `backend.*` import (settings is a
module-level singleton), which is why they live here at conftest import time.
Tests never touch the real captures/ directory.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Distinct from the PostgreSQL build's test dir so both suites can coexist.
_TEST_DATA_DIR = Path(tempfile.gettempdir()) / "cardiosentry_local_test_captures"
os.environ.setdefault("CARDIOSENTRY_DATA_DIR", str(_TEST_DATA_DIR))
# The suite pins ONE model on purpose: several assertions are specific to it
# (Grad-CAM's `attn` at 2048 channels on a 24x32 grid is a ResNet-50 fact, not
# an EfficientNetV2-S one). It is therefore independent of whatever
# models/active.yaml points at — but the startup self-check is not, so the
# reference scores must be pinned to the SAME model or every test run logs a
# spurious "self-check FAILED" against another run's numbers.
os.environ.setdefault("CARDIOSENTRY_ACTIVE_MODEL",
                      "resnet50_cbam_nat768")
os.environ.setdefault("CARDIOSENTRY_VERIFY_EXPECTED_SCORES_JSON", str(
    Path(__file__).resolve().parent / "fixtures"
    / "expected_scores_resnet50_cbam_nat768.json"))
# Model inference on CPU is slow; one thread keeps the smoke test fast enough
# without touching the production default.
os.environ.setdefault("CARDIOSENTRY_NUM_THREADS", "2")

from backend.settings import settings

# Records and accounts are files in data_dir, so every session starts from an
# empty test directory (the analogue of recreating a test database). Refuse to
# wipe anything else.
assert Path(settings.data_dir).resolve() == _TEST_DATA_DIR.resolve(), (
    f"tests must use {_TEST_DATA_DIR}, not {settings.data_dir}")
shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def client():
    """TestClient over the real app (lifespan loads the real model once)."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        r = c.post("/api/auth/login",
                   json={"username": "admin", "password": "admin"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def anon_client(client):
    """Share the running app without its admin cookie or another startup."""
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    yield c
    c.close()
