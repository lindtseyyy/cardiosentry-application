"""PostgreSQL capture, prediction and explanation records; files stay on disk."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path

from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from backend.schemas.capture import CaptureRecord
from backend.services import storage
from backend.services.accounts import owner_of


def _jsonb(record: dict) -> Jsonb:
    # PostgreSQL JSONB rejects the NUL padding found in phone EXIF strings.
    def clean(value: object) -> object:
        if isinstance(value, str):
            return value.replace("\x00", "")
        if isinstance(value, dict):
            return {clean(key): clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    return Jsonb(clean(record), dumps=partial(json.dumps, allow_nan=False))


def _created_utc(record: dict) -> datetime:
    created = datetime.fromisoformat(record["created_utc"])
    if created.utcoffset() is None:
        raise ValueError("Capture created_utc must be timezone-aware.")
    return created


class RecordStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def _locked_capture(self, conn: Connection, capture_id: str) -> dict:
        row = conn.execute(
            "SELECT record FROM captures "
            "WHERE capture_id=%s AND trashed_utc IS NULL FOR UPDATE",
            (capture_id,),
        ).fetchone()
        if row is None:
            raise KeyError(capture_id)
        return row[0]

    def _save_capture(self, conn: Connection, capture_id: str, record: dict) -> dict:
        payload = _jsonb(CaptureRecord.model_validate(record).model_dump(mode="json"))
        stored = payload.obj
        conn.execute(
            "UPDATE captures SET record=%s, owner_id=%s, created_utc=%s "
            "WHERE capture_id=%s",
            (payload, owner_of(stored), _created_utc(stored), capture_id),
        )
        return stored

    def create_capture(self, record: CaptureRecord) -> None:
        payload = _jsonb(record.model_dump(mode="json"))
        stored = payload.obj
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO captures (capture_id, owner_id, created_utc, record) "
                "VALUES (%s, %s, %s, %s)",
                (stored["capture_id"], owner_of(stored), _created_utc(stored), payload),
            )

    def get_capture(self, capture_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT record FROM captures "
                "WHERE capture_id=%s AND trashed_utc IS NULL",
                (capture_id,),
            ).fetchone()
        return row[0] if row is not None else None

    def owned_capture(self, capture_id: str, account_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT record FROM captures "
                "WHERE capture_id=%s AND owner_id=%s AND trashed_utc IS NULL",
                (capture_id, account_id),
            ).fetchone()
        return row[0] if row is not None else None

    def update_capture(self, capture_id: str, mutate: Callable[[dict], None]) -> dict:
        with self.pool.connection() as conn:
            record = self._locked_capture(conn, capture_id)
            mutate(record)
            return self._save_capture(conn, capture_id, record)

    def trash_capture(self, capture_id: str) -> Path:
        with self.pool.connection() as conn:
            updated = conn.execute(
                "UPDATE captures SET trashed_utc=now() "
                "WHERE capture_id=%s AND trashed_utc IS NULL",
                (capture_id,),
            )
            if updated.rowcount == 0:
                raise KeyError(capture_id)
            return storage.trash_capture(capture_id)

    def list_owned(
        self, account_id: str, limit: int, offset: int,
    ) -> tuple[int, list[tuple[dict, list[dict]]]]:
        with self.pool.connection() as conn:
            total = conn.execute(
                "SELECT count(*) FROM captures "
                "WHERE owner_id=%s AND trashed_utc IS NULL",
                (account_id,),
            ).fetchone()[0]
            page = conn.execute(
                "SELECT capture_id, record FROM captures "
                "WHERE owner_id=%s AND trashed_utc IS NULL "
                "ORDER BY capture_id DESC LIMIT %s OFFSET %s",
                (account_id, limit, offset),
            ).fetchall()
            if not page:
                return total, []
            runs = {
                (cid, run_id): run
                for cid, run_id, run in conn.execute(
                    "SELECT p.capture_id, p.run_id, p.record FROM prediction_runs AS p "
                    "JOIN captures AS c USING (capture_id) "
                    "WHERE p.capture_id = ANY(%s) AND c.trashed_utc IS NULL",
                    ([cid for cid, _ in page],),
                ).fetchall()
            }
        return total, [
            (record, [runs[(cid, run_id)] for run_id in record.get("predictions", [])
                      if (cid, run_id) in runs])
            for cid, record in page
        ]

    def all_captures(self) -> list[dict]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT record FROM captures WHERE trashed_utc IS NULL "
                "ORDER BY capture_id DESC",
            ).fetchall()
        return [row[0] for row in rows]

    def has_captures(self) -> bool:
        with self.pool.connection() as conn:
            return conn.execute("SELECT EXISTS (SELECT 1 FROM captures)").fetchone()[0]

    def add_prediction(self, capture_id: str, run: dict) -> None:
        payload = _jsonb(run)
        run_id = payload.obj["run_id"]
        with self.pool.connection() as conn:
            # Lock before the child insert: FK key-share locks can deadlock on upgrade.
            record = self._locked_capture(conn, capture_id)
            conn.execute(
                "INSERT INTO prediction_runs (capture_id, run_id, record) "
                "VALUES (%s, %s, %s)",
                (capture_id, run_id, payload),
            )
            record["predictions"] = list(dict.fromkeys(
                record.get("predictions", []) + [run_id]))
            self._save_capture(conn, capture_id, record)

    def prediction_runs(self, capture_id: str, run_ids: list[str]) -> list[dict]:
        if not run_ids:
            return []
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT p.run_id, p.record FROM prediction_runs AS p "
                "JOIN captures AS c USING (capture_id) "
                "WHERE p.capture_id=%s AND p.run_id = ANY(%s) "
                "AND c.trashed_utc IS NULL",
                (capture_id, run_ids),
            ).fetchall()
        runs = dict(rows)
        return [runs[run_id] for run_id in run_ids if run_id in runs]

    def prediction_run(self, capture_id: str, run_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT p.record FROM prediction_runs AS p "
                "JOIN captures AS c USING (capture_id) "
                "WHERE p.capture_id=%s AND p.run_id=%s AND c.trashed_utc IS NULL",
                (capture_id, run_id),
            ).fetchone()
        return row[0] if row is not None else None

    def add_explanation(self, capture_id: str, record: dict) -> None:
        payload = _jsonb(record)
        explain_id = payload.obj["explain_id"]
        with self.pool.connection() as conn:
            capture = self._locked_capture(conn, capture_id)
            conn.execute(
                "INSERT INTO explain_runs (capture_id, explain_id, record) "
                "VALUES (%s, %s, %s)",
                (capture_id, explain_id, payload),
            )
            capture["explanations"] = list(dict.fromkeys(
                capture.get("explanations", []) + [explain_id]))
            self._save_capture(conn, capture_id, capture)

    def explain_records(self, capture_id: str) -> list[dict]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT e.record FROM explain_runs AS e "
                "JOIN captures AS c USING (capture_id) "
                "WHERE e.capture_id=%s AND c.trashed_utc IS NULL "
                "ORDER BY e.explain_id DESC",
                (capture_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def explain_record(self, capture_id: str, explain_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT e.record FROM explain_runs AS e "
                "JOIN captures AS c USING (capture_id) "
                "WHERE e.capture_id=%s AND e.explain_id=%s AND c.trashed_utc IS NULL",
                (capture_id, explain_id),
            ).fetchone()
        return row[0] if row is not None else None

    def count_explanations(self, capture_id: str) -> int:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT count(*) FROM explain_runs AS e "
                "JOIN captures AS c USING (capture_id) "
                "WHERE e.capture_id=%s AND c.trashed_utc IS NULL",
                (capture_id,),
            ).fetchone()[0]

    def delete_explanation(self, capture_id: str, explain_id: str) -> bool:
        with self.pool.connection() as conn:
            capture = self._locked_capture(conn, capture_id)
            deleted = conn.execute(
                "DELETE FROM explain_runs WHERE capture_id=%s AND explain_id=%s",
                (capture_id, explain_id),
            ).rowcount > 0
            capture["explanations"] = [
                xid for xid in capture.get("explanations", []) if xid != explain_id
            ]
            self._save_capture(conn, capture_id, capture)
            return deleted

    def import_capture(
        self, record: dict, runs: list[dict], explanations: list[dict],
    ) -> bool:
        payload = _jsonb(record)
        stored = payload.obj
        capture_id = stored["capture_id"]
        with self.pool.connection() as conn:
            inserted = conn.execute(
                "INSERT INTO captures (capture_id, owner_id, created_utc, record) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (capture_id) DO NOTHING",
                (capture_id, owner_of(stored), _created_utc(stored), payload),
            )
            if inserted.rowcount == 0:
                return False
            for run in runs:
                run_payload = _jsonb(run)
                conn.execute(
                    "INSERT INTO prediction_runs (capture_id, run_id, record) "
                    "VALUES (%s, %s, %s)",
                    (capture_id, run_payload.obj["run_id"], run_payload),
                )
            for explanation in explanations:
                explain_payload = _jsonb(explanation)
                conn.execute(
                    "INSERT INTO explain_runs (capture_id, explain_id, record) "
                    "VALUES (%s, %s, %s)",
                    (capture_id, explain_payload.obj["explain_id"], explain_payload),
                )
        return True
