"""Account-store regressions without app startup or model loading."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.errors import ApiError
from backend.services.accounts import Account, AccountStore, _password_hash, owner_of


def test_renamed_admin_keeps_admin_account_id(tmp_path: Path):
    path = tmp_path / "accounts.json"
    store = AccountStore(path)
    store.ensure_admin()
    token = store.create_session("admin")

    account = store.update_account(
        token, "admin", username="boss", new_password="new-password-1",
    )
    assert account == Account("admin", "boss")
    assert store.user_for_token(token) == Account("admin", "boss")
    assert owner_of({}) == "admin"

    reloaded = AccountStore(path)
    reloaded.ensure_admin()
    assert set(json.loads(path.read_text(encoding="utf-8"))["users"]) == {"boss"}
    assert reloaded.user_for_token(token) == Account("admin", "boss")
    with pytest.raises(ApiError) as error:
        reloaded.register("admin", "test-password")
    assert error.value.status_code == 409
    assert error.value.code == "USERNAME_TAKEN"
    assert reloaded.authenticate("boss", "new-password-1") == "boss"


def test_pre_feature_store_loads_without_account_id(tmp_path: Path):
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

    store = AccountStore(path)
    assert store.user_for_token(token) == Account(username, username)
    assert path.read_bytes() == original_bytes
    new_token = store.create_session(username)
    assert path.read_bytes() != original_bytes
    assert store.user_for_token(new_token) == Account(username, username)
    assert store.user_for_token(token) == Account(username, username)

    data["users"]["other-user"] = {
        **data["users"][username],
        "username": "other-user",
        "account_id": username,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    duplicate_bytes = path.read_bytes()
    with pytest.raises(RuntimeError):
        AccountStore(path)
    assert path.read_bytes() == duplicate_bytes
