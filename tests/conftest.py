"""Shared test configuration.

Environment overrides MUST be set before any `backend.*` import (settings is a
module-level singleton), which is why they live here at conftest import time.
Tests never touch the real captures/ directory or the real database.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

os.environ.setdefault("CARDIOSENTRY_DATA_DIR", str(
    Path(tempfile.gettempdir()) / "cardiosentry_test_captures"))
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

if settings.database_url is not None:
    _url = settings.database_url.get_secret_value()
    _real_dbname = conninfo_to_dict(_url)["dbname"]
    _test_dbname = f"{_real_dbname}_test"
    assert _test_dbname.endswith("_test") and _test_dbname != _real_dbname
    # PostgreSQL truncates identifiers at 63 bytes, which must not lose the suffix.
    assert len(_test_dbname.encode("utf-8")) <= 63
    settings.database_url = SecretStr(make_conninfo(_url, dbname=_test_dbname))

from backend.services import db

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


def _recreate(dbname: str) -> None:
    url = settings.database_url.get_secret_value()
    test_dbname = conninfo_to_dict(url)["dbname"]
    assert test_dbname.endswith("_test")
    assert dbname in (test_dbname, f"{test_dbname}_unit")
    assert len(dbname.encode("utf-8")) <= 63
    with psycopg.connect(make_conninfo(url, dbname="postgres"),
                         autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(dbname),
        ))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


@pytest.fixture(scope="session")
def database_url() -> str:
    if settings.database_url is None:
        db.connect()  # Raises the app's readable missing-configuration error.
    url = settings.database_url.get_secret_value()
    _recreate(conninfo_to_dict(url)["dbname"])
    return url


@pytest.fixture
def isolated_db():
    if settings.database_url is None:
        db.connect()
    url = settings.database_url.get_secret_value()
    dbname = f"{conninfo_to_dict(url)['dbname']}_unit"
    _recreate(dbname)
    pool = None
    try:
        pool = db.connect(make_conninfo(url, dbname=dbname))
        yield pool
    finally:
        if pool is not None:
            pool.close()
        with psycopg.connect(make_conninfo(url, dbname="postgres"),
                             autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(dbname),
            ))


@pytest.fixture(scope="session")
def client(database_url):
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
