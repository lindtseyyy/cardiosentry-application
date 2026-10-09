"""Database safety and read-only legacy-import regressions."""
from __future__ import annotations

import json
from pathlib import Path
from secrets import token_hex

import pytest
import psycopg

from backend.schemas.capture import CaptureRecord
from backend.services import db
from scripts.import_filesystem import import_filesystem


def test_connect_errors_are_readable_and_hide_password(monkeypatch):
    with pytest.raises(RuntimeError) as error:
        db.connect("postgresql://cardiosentry:s3cret-pw@127.0.0.1:1/cs_x")
    message = str(error.value)
    assert "127.0.0.1:1" in message and "cs_x" in message
    assert "s3cret-pw" not in message

    def unexpected_connect(*args, **kwargs):
        pytest.fail("A non-local database host must be rejected before connecting.")

    monkeypatch.setattr(psycopg, "connect", unexpected_connect)
    with pytest.raises(RuntimeError) as error:
        db.connect("postgresql://cardiosentry:s3cret-pw@10.255.255.1:5432/cs_x")
    assert "local" in str(error.value).lower()
    assert "s3cret-pw" not in str(error.value)


def test_import_filesystem_is_idempotent_and_read_only(isolated_db, tmp_path: Path):
    capture_id = f"2026-01-01_000000_{token_hex(3)}"
    trash_id = f"2026-01-02_000000_{token_hex(3)}"
    bad_id = f"2026-01-03_000000_{token_hex(3)}"
    run_id = "run_20260101_000000_000_resnet50_cbam_nat768"
    explain_id = "xai_20260101_000000_000_gradcam_resnet50_cbam_nat768"
    record = CaptureRecord(
        capture_id=capture_id,
        created_utc="2026-01-01T00:00:00.000Z",
        original={"exif": {"make": "X\u0000\u0000"}},
        predictions=[run_id],
        explanations=[explain_id],
    ).model_dump(mode="json", exclude={"owner"})
    directory = tmp_path / capture_id[:10] / capture_id
    files = {
        directory / "capture.json": record,
        directory / "predictions" / f"{run_id}.json": {
            "run_id": run_id,
            "model": {"id": "resnet50_cbam_nat768"},
            "positive": ["AF"],
        },
        directory / "explain" / explain_id / "record.json": {
            "explain_id": explain_id,
            "method": "gradcam",
            "model": {"id": "resnet50_cbam_nat768"},
            "created_utc": "2026-01-01T00:00:00.000Z",
            "labels": ["AF"],
            "attributions": [],
            "model_input_sha256": "0" * 64,
        },
        tmp_path / "_trash" / trash_id[:10] / trash_id / "capture.json": {
            **record, "capture_id": trash_id, "predictions": [], "explanations": [],
        },
        tmp_path / bad_id[:10] / bad_id / "capture.json": record,
    }
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    original_files = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files
    }

    report = import_filesystem(isolated_db, tmp_path)
    assert report.captures_imported == 1
    assert report.captures_present == 0
    assert report.runs_imported == 1
    assert report.explanations_imported == 1
    assert len(report.problems) == 1
    assert bad_id in report.problems[0]
    with isolated_db.connection() as conn:
        owner_id, stored = conn.execute(
            "SELECT owner_id, record FROM captures WHERE capture_id=%s",
            (capture_id,),
        ).fetchone()
        assert owner_id == "admin"
        assert "owner" not in stored
        assert stored["original"]["exif"]["make"] == "X"
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM captures), "
            "(SELECT count(*) FROM prediction_runs), "
            "(SELECT count(*) FROM explain_runs)",
        ).fetchone()
        assert counts == (1, 1, 1)
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files
    } == original_files

    report = import_filesystem(isolated_db, tmp_path)
    assert report.captures_imported == 0
    assert report.captures_present == 1
    assert report.runs_imported == 0
    assert report.explanations_imported == 0
    assert len(report.problems) == 1
    with isolated_db.connection() as conn:
        assert conn.execute(
            "SELECT (SELECT count(*) FROM captures), "
            "(SELECT count(*) FROM prediction_runs), "
            "(SELECT count(*) FROM explain_runs)",
        ).fetchone() == counts
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files
    } == original_files
