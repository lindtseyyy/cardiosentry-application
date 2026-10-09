#!/usr/bin/env python3
"""Import frozen filesystem records into PostgreSQL without changing any files."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import psycopg  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.schemas.capture import CaptureRecord  # noqa: E402
from backend.services import db, storage  # noqa: E402
from backend.services.accounts import ADMIN_ACCOUNT_ID, _USERNAME_RE, _password_parts  # noqa: E402
from backend.services.records import RecordStore  # noqa: E402
from backend.settings import settings  # noqa: E402

_DATE_SHARD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ImportReport:
    accounts_imported: int = 0
    accounts_present: int = 0
    sessions_imported: int = 0
    captures_imported: int = 0
    captures_present: int = 0
    runs_imported: int = 0
    explanations_imported: int = 0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        record = json.load(source)
    if not isinstance(record, dict):
        raise ValueError("Expected a JSON object.")
    return record


def _utc_datetime(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("Account timestamps must be UTC.")
    return timestamp


def _load_accounts(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    try:
        data = _read_json(path)
        if (type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
                or not isinstance(data.get("users"), dict)
                or not isinstance(data.get("sessions"), dict)):
            raise ValueError("Invalid account store schema.")
        account_ids: set[str] = set()
        for username, user in data["users"].items():
            if (not _USERNAME_RE.fullmatch(username)
                    or not isinstance(user, dict)
                    or user.get("username") != username):
                raise ValueError("Invalid account record.")
            if "account_id" in user and (
                    not isinstance(user["account_id"], str)
                    or not _USERNAME_RE.fullmatch(user["account_id"])):
                raise ValueError("Invalid account id.")
            account_id = user.get("account_id") or username
            if account_id in account_ids:
                raise ValueError("Duplicate account id.")
            if username == ADMIN_ACCOUNT_ID and account_id != ADMIN_ACCOUNT_ID:
                raise ValueError("Admin username belongs to a non-admin account.")
            account_ids.add(account_id)
            _password_parts(user["password_hash"])
            _utc_datetime(user["created_utc"])
        for key, session in data["sessions"].items():
            if (not re.fullmatch(r"[0-9a-f]{64}", key)
                    or not isinstance(session, dict)
                    or session.get("username") not in data["users"]):
                raise ValueError("Invalid session record.")
            _utc_datetime(session["created_utc"])
            _utc_datetime(session["expires_utc"])
        return data["users"], data["sessions"]
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError(f"Invalid account store at {path}.") from None


def import_filesystem(pool: ConnectionPool, data_dir: Path) -> ImportReport:
    report = ImportReport()
    accounts_path = data_dir / "accounts.json"
    # Validate the entire snapshot before inserting any account or capture rows.
    if accounts_path.exists():
        users, sessions = _load_accounts(accounts_path)
        with pool.connection() as conn, conn.transaction():
            for username, user in users.items():
                inserted = conn.execute(
                    "INSERT INTO accounts (account_id, username, password_hash, created_utc) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (user.get("account_id") or username, username,
                     user["password_hash"], _utc_datetime(user["created_utc"])),
                ).rowcount
                report.accounts_imported += inserted
                report.accounts_present += 1 - inserted
            now = datetime.now(timezone.utc)
            for key, session in sessions.items():
                expires = _utc_datetime(session["expires_utc"])
                if expires <= now:
                    continue
                user = users[session["username"]]
                account_id = user.get("account_id") or session["username"]
                report.sessions_imported += conn.execute(
                    "INSERT INTO sessions (token_sha256, account_id, created_utc, expires_utc) "
                    "SELECT %s, %s, %s, %s "
                    "WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = %s) "
                    "ON CONFLICT DO NOTHING",
                    (key, account_id, _utc_datetime(session["created_utc"]),
                     expires, account_id),
                ).rowcount

    records = RecordStore(pool)
    for path in sorted(data_dir.glob("*/*/capture.json")):
        directory = path.parent
        capture_id = directory.name
        if (not storage.CAPTURE_ID_RE.fullmatch(capture_id)
                or not _DATE_SHARD_RE.fullmatch(directory.parent.name)):
            continue
        try:
            record = _read_json(path)
        except (OSError, UnicodeError, ValueError):
            report.problems.append(f"{capture_id}: capture.json is not a readable JSON object")
            continue
        if record.get("capture_id") != capture_id:
            report.problems.append(f"{capture_id}: capture_id differs from its folder")
            continue
        try:
            created = datetime.fromisoformat(record["created_utc"])
            if created.utcoffset() is None:
                raise ValueError("Timestamp is not timezone-aware.")
        except (KeyError, TypeError, ValueError):
            report.problems.append(f"{capture_id}: created_utc must be a timezone-aware ISO timestamp")
            continue
        try:
            CaptureRecord.model_validate(record)
        except ValidationError:
            # Legacy records stay visible even when the current schema rejects them.
            report.warnings.append(f"{capture_id}: capture does not match the current schema; importing as stored")

        runs: list[dict] = []
        explanations: list[dict] = []
        run_ids = record.get("predictions", [])
        if not isinstance(run_ids, list):
            run_ids = []
        listed: set[str] = set()
        try:
            for run_id in run_ids:
                if (not isinstance(run_id, str)
                        or Path(f"{run_id}.json").name != f"{run_id}.json"):
                    report.warnings.append(f"{capture_id}: listed run has no safe filename")
                    continue
                if run_id in listed:
                    continue
                listed.add(run_id)
                run_path = directory / "predictions" / f"{run_id}.json"
                if run_path.is_file():
                    runs.append(_read_json(run_path))
                else:
                    report.warnings.append(f"{capture_id}: listed run file is missing")
            unlisted = sum(1 for run_path in (directory / "predictions").glob("*.json")
                           if run_path.is_file() and run_path.stem not in listed)
            if unlisted:
                report.warnings.append(f"{capture_id}: {unlisted} unlisted run files not imported")
            for explain_path in sorted(directory.glob("explain/*/record.json")):
                if storage.EXPLAIN_ID_RE.fullmatch(explain_path.parent.name):
                    explanations.append(_read_json(explain_path))
        except (OSError, UnicodeError, ValueError):
            report.problems.append(f"{capture_id}: run or explain record is not a readable JSON object")
            continue
        try:
            imported = records.import_capture(record, runs, explanations)
        except (psycopg.Error, ValueError, TypeError, KeyError):
            # Database and validation exceptions can contain private record values.
            report.problems.append(f"{capture_id}: database import failed; no records imported for this capture")
            continue
        if imported:
            report.captures_imported += 1
            report.runs_imported += len(runs)
            report.explanations_imported += len(explanations)
        else:
            report.captures_present += 1
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    args = parser.parse_args()
    try:
        accounts_path = args.data_dir / "accounts.json"
        if accounts_path.exists():
            _load_accounts(accounts_path)
        with db.connect() as pool:
            report = import_filesystem(pool, args.data_dir)
    except ValueError as exc:
        print(f"PROBLEM: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error:
        print("PROBLEM: account import failed; account transaction rolled back", file=sys.stderr)
        return 1
    print(f"accounts: {report.accounts_imported} imported, {report.accounts_present} already present")
    print(f"sessions: {report.sessions_imported} imported")
    print(f"captures: {report.captures_imported} imported, {report.captures_present} already present")
    print(f"runs: {report.runs_imported} imported")
    print(f"explanations: {report.explanations_imported} imported")
    print(f"warnings: {len(report.warnings)}; problems: {len(report.problems)}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    for problem in report.problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
