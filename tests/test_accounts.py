"""Account-store regressions without app startup or model loading."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.errors import ApiError
from backend.services.accounts import Account, AccountStore, _password_hash, owner_of
from scripts.import_filesystem import import_filesystem


def test_renamed_admin_keeps_admin_account_id(isolated_db):
    store = AccountStore(isolated_db)
    store.ensure_admin()
    token = store.create_session("admin")

    account = store.update_account(
        token, "admin", username="boss", new_password="new-password-1",
    )
    assert account == Account("admin", "boss")
    assert store.user_for_token(token) == Account("admin", "boss")
    assert owner_of({}) == "admin"

    reloaded = AccountStore(isolated_db)
    reloaded.ensure_admin()
    with isolated_db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT username FROM accounts")] == ["boss"]
    assert reloaded.user_for_token(token) == Account("admin", "boss")
    with pytest.raises(ApiError) as error:
        reloaded.register("admin", "test-password")
    assert error.value.status_code == 409
    assert error.value.code == "USERNAME_TAKEN"
    assert reloaded.authenticate("boss", "new-password-1") == "boss"


def test_import_legacy_accounts_file(isolated_db, tmp_path: Path):
    path = tmp_path / "accounts.json"
    username = "legacy-user"
    token = "legacy-session-token"
    now = datetime.now(timezone.utc)
    created_utc = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    expires_utc = (now + timedelta(days=30)).isoformat(
        timespec="milliseconds",
    ).replace("+00:00", "Z")
    data = {
        "schema_version": 1,
        "users": {
            username: {
                "username": username,
                "password_hash": _password_hash("test-password"),
                "created_utc": created_utc,
            },
        },
        "sessions": {
            hashlib.sha256(token.encode("utf-8")).hexdigest(): {
                "username": username,
                "created_utc": created_utc,
                "expires_utc": expires_utc,
            },
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    original_bytes = path.read_bytes()

    report = import_filesystem(isolated_db, tmp_path)
    assert report.accounts_imported == 1
    assert report.sessions_imported == 1
    assert report.problems == []
    store = AccountStore(isolated_db)
    assert store.user_for_token(token) == Account(username, username)
    assert path.read_bytes() == original_bytes
    new_token = store.create_session(username)
    assert path.read_bytes() == original_bytes
    assert store.user_for_token(new_token) == Account(username, username)
    assert store.user_for_token(token) == Account(username, username)

    report = import_filesystem(isolated_db, tmp_path)
    assert report.accounts_imported == 0
    assert report.sessions_imported == 0
    assert path.read_bytes() == original_bytes

    data["users"]["other-user"] = {
        **data["users"][username],
        "username": "other-user",
        "account_id": username,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    duplicate_bytes = path.read_bytes()
    with pytest.raises(ValueError):
        import_filesystem(isolated_db, tmp_path)
    assert path.read_bytes() == duplicate_bytes
    with isolated_db.connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM accounts WHERE username=%s", ("other-user",),
        ).fetchone() is None
