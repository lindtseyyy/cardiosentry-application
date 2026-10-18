"""Filesystem JSON capture, prediction and explanation records (plan §2.2).

Layout under settings.data_dir (the pre-PostgreSQL format, which
scripts/import_filesystem.py in the PostgreSQL build imports unchanged):

    <date>/<capture_id>/capture.json
    <date>/<capture_id>/predictions/<run_id>.json
    <date>/<capture_id>/explain/<explain_id>/record.json

Deleting a capture moves its whole folder, records included, to _trash/, so
reads never see it again. The server is single-process (workers=1), so one
in-process lock serialises every read-modify-write of capture.json.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

from backend.schemas.capture import CaptureRecord
from backend.services import storage
from backend.services.accounts import owner_of
from backend.settings import settings


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _capture_path(capture_id: str) -> Path | None:
    try:
        return storage.capture_dir(capture_id) / "capture.json"
    except KeyError:
        return None


def _run_path(capture_id: str, run_id: str) -> Path | None:
    # The id shape is the path-traversal gate for client-supplied run ids.
    if not storage.PREDICTION_ID_RE.fullmatch(run_id):
        return None
    try:
        return storage.capture_dir(capture_id) / "predictions" / f"{run_id}.json"
    except KeyError:
        return None


def _explain_path(capture_id: str, explain_id: str) -> Path | None:
    try:
        return storage.explain_dir(capture_id, explain_id) / "record.json"
    except KeyError:
        return None


class RecordStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _save_capture(self, path: Path, record: dict) -> dict:
        stored = CaptureRecord.model_validate(record).model_dump(mode="json")
        storage.atomic_write_json(path, stored)
        return stored

    def _locked_update(self, capture_id: str, mutate: Callable[[dict], None]) -> dict:
        path = _capture_path(capture_id)
        record = _read_json(path) if path is not None else None
        if record is None:
            raise KeyError(capture_id)
        mutate(record)
        return self._save_capture(path, record)

    def create_capture(self, record: CaptureRecord) -> None:
        path = storage.capture_dir(record.capture_id) / "capture.json"
        with self._lock:
            if path.exists():
                raise FileExistsError(record.capture_id)
            storage.atomic_write_json(path, record.model_dump(mode="json"))

    def get_capture(self, capture_id: str) -> dict | None:
        path = _capture_path(capture_id)
        return _read_json(path) if path is not None else None

    def owned_capture(self, capture_id: str, account_id: str) -> dict | None:
        record = self.get_capture(capture_id)
        if record is None or owner_of(record) != account_id:
            return None
        return record

    def update_capture(self, capture_id: str, mutate: Callable[[dict], None]) -> dict:
        with self._lock:
            return self._locked_update(capture_id, mutate)

    def trash_capture(self, capture_id: str) -> Path:
        with self._lock:
            if _capture_path(capture_id) is None:
                raise KeyError(capture_id)
            return storage.trash_capture(capture_id)

    def _iter_records(self):
        """Live capture records, newest first (ids sort chronologically)."""
        if not settings.data_dir.is_dir():
            return
        paths = sorted(
            (p for p in settings.data_dir.glob("[0-9]*/*/capture.json")
             if storage.CAPTURE_ID_RE.fullmatch(p.parent.name)),
            key=lambda p: p.parent.name, reverse=True)
        for path in paths:
            record = _read_json(path)
            if record is not None:
                yield record

    def list_owned(
        self, account_id: str, limit: int, offset: int,
    ) -> tuple[int, list[tuple[dict, list[dict]]]]:
        owned = [record for record in self._iter_records()
                 if owner_of(record) == account_id]
        return len(owned), [
            (record, self.prediction_runs(record["capture_id"],
                                          record.get("predictions", [])))
            for record in owned[offset:offset + limit]
        ]

    def all_captures(self) -> list[dict]:
        return list(self._iter_records())

    def add_prediction(self, capture_id: str, run: dict) -> None:
        run_id = run["run_id"]
        with self._lock:
            path = _run_path(capture_id, run_id)
            if path is None:
                raise KeyError(capture_id)
            if path.exists():
                raise FileExistsError(run_id)
            storage.atomic_write_json(path, run)

            def mutate(record: dict) -> None:
                record["predictions"] = list(dict.fromkeys(
                    record.get("predictions", []) + [run_id]))

            try:
                self._locked_update(capture_id, mutate)
            except Exception:
                path.unlink(missing_ok=True)
                raise

    def prediction_runs(self, capture_id: str, run_ids: list[str]) -> list[dict]:
        runs = []
        for run_id in dict.fromkeys(run_ids):
            run = self.prediction_run(capture_id, run_id)
            if run is not None:
                runs.append(run)
        return runs

    def prediction_run(self, capture_id: str, run_id: str) -> dict | None:
        path = _run_path(capture_id, run_id)
        return _read_json(path) if path is not None else None

    def add_explanation(self, capture_id: str, record: dict) -> None:
        explain_id = record["explain_id"]
        if not storage.EXPLAIN_ID_RE.fullmatch(explain_id):
            raise KeyError(f"malformed explain_id: {explain_id!r}")
        with self._lock:
            # The explain route normally created this folder and removes it on failure.
            path = storage.capture_dir(capture_id) / "explain" / explain_id / "record.json"
            storage.atomic_write_json(path, record)

            def mutate(capture: dict) -> None:
                capture["explanations"] = list(dict.fromkeys(
                    capture.get("explanations", []) + [explain_id]))

            self._locked_update(capture_id, mutate)

    def _explain_paths(self, capture_id: str) -> list[Path]:
        try:
            explain_root = storage.capture_dir(capture_id) / "explain"
        except KeyError:
            return []
        return sorted(
            (p for p in explain_root.glob("*/record.json")
             if storage.EXPLAIN_ID_RE.fullmatch(p.parent.name)),
            key=lambda p: p.parent.name, reverse=True)

    def explain_records(self, capture_id: str) -> list[dict]:
        records = (_read_json(path) for path in self._explain_paths(capture_id))
        return [record for record in records if record is not None]

    def explain_record(self, capture_id: str, explain_id: str) -> dict | None:
        path = _explain_path(capture_id, explain_id)
        return _read_json(path) if path is not None else None

    def count_explanations(self, capture_id: str) -> int:
        return len(self._explain_paths(capture_id))

    def delete_explanation(self, capture_id: str, explain_id: str) -> bool:
        """Drop the record and its capture.json entry; the route removes the files."""
        with self._lock:
            path = _explain_path(capture_id, explain_id)
            deleted = path is not None and path.is_file()
            if deleted:
                path.unlink()

            def mutate(capture: dict) -> None:
                capture["explanations"] = [
                    xid for xid in capture.get("explanations", []) if xid != explain_id
                ]

            self._locked_update(capture_id, mutate)
            return deleted
