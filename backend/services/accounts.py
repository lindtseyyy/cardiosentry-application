"""Local password accounts and persistent, opaque sign-in sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.errors import ApiError
from backend.services import storage

log = logging.getLogger("cardiosentry.accounts")

ADMIN_ACCOUNT_ID = "admin"
SESSION_COOKIE = "cardiosentry_session"
SESSION_TTL_DAYS = 30

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
_PASSWORD_ITERATIONS = 600_000


@dataclass(frozen=True)
class Account:
    account_id: str
    username: str


def _account_id(user: dict) -> str:
    return user.get("account_id") or user["username"]


def owner_of(record: dict) -> str:
    """Return the owner account id, including admin's pre-accounts captures."""
    return record.get("owner") or ADMIN_ACCOUNT_ID


def _password_parts(encoded: str) -> tuple[int, bytes, bytes]:
    algorithm, iterations, salt, digest = encoded.split("$")
    count = int(iterations)
    salt_bytes = base64.b64decode(salt, validate=True)
    digest_bytes = base64.b64decode(digest, validate=True)
    if (algorithm != "pbkdf2_sha256" or count < 1
            or len(salt_bytes) != 16 or len(digest_bytes) != 32):
        raise ValueError("Invalid password hash.")
    return count, salt_bytes, digest_bytes


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt, _PASSWORD_ITERATIONS)
    return (f"pbkdf2_sha256${_PASSWORD_ITERATIONS}$"
            f"{base64.b64encode(salt).decode('ascii')}$"
            f"{base64.b64encode(digest).decode('ascii')}")


def _verify_password(encoded: str, password: str) -> bool:
    count, salt, expected = _password_parts(encoded)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, count)
    return hmac.compare_digest(actual, expected)


def _utc_datetime(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("Account timestamps must be UTC.")
    return timestamp


class AccountStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._snapshot: tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]] = ({}, {})
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Unable to load account store at {self.path}.") from exc
        try:
            data = json.loads(text)
            if (not isinstance(data, dict)
                    or type(data.get("schema_version")) is not int
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
                account_id = _account_id(user)
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
            self._snapshot = (data["users"], data["sessions"])
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise RuntimeError(f"Invalid account store at {self.path}.") from exc

    def _write_locked(self, users: dict[str, dict[str, str]],
                      sessions: dict[str, dict[str, str]]) -> None:
        now = datetime.now(timezone.utc)
        sessions = {key: session for key, session in sessions.items()
                    if _utc_datetime(session["expires_utc"]) > now}
        storage.atomic_write_json(self.path, {
            "schema_version": 1, "users": users, "sessions": sessions,
        })
        # Publish only after the write succeeds; readers never wait on disk I/O.
        self._snapshot = (users, sessions)

    def _add_user_locked(self, username: str, password: str) -> None:
        current_users, sessions = self._snapshot
        users = current_users.copy()
        users[username] = {
            "username": username,
            "account_id": username,
            "password_hash": _password_hash(password),
            "created_utc": storage.utcnow(),
        }
        self._write_locked(users, sessions)

    def ensure_admin(self) -> None:
        with self._lock:
            users, _ = self._snapshot
            if any(_account_id(user) == ADMIN_ACCOUNT_ID for user in users.values()):
                return
            self._add_user_locked(ADMIN_ACCOUNT_ID, "admin")
        log.warning("Created default account '%s'; restrict access on untrusted networks.",
                    ADMIN_ACCOUNT_ID)

    def register(self, username: str, password: str) -> str:
        username = username.strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ApiError(422, "INVALID_USERNAME",
                           "Use 3–32 letters, numbers, dots, dashes or underscores.")
        if not 8 <= len(password) <= 128:
            raise ApiError(422, "INVALID_PASSWORD", "Use 8–128 characters.")
        with self._lock:
            users, _ = self._snapshot
            if username in users or any(_account_id(user) == username for user in users.values()):
                raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.")
            self._add_user_locked(username, password)
        return username

    def authenticate(self, username: str, password: str) -> str:
        username = username.strip().lower()
        users, _ = self._snapshot
        user = users.get(username)
        if user is not None and _verify_password(user["password_hash"], password):
            return username
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong username or password.")

    def update_account(self, token: str | None, current_password: str,
                       username: str | None = None,
                       new_password: str | None = None) -> Account:
        with self._lock:
            account = self.user_for_token(token)
            if account is None:
                raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
            users, sessions = self._snapshot
            user = users[account.username]
            if not _verify_password(user["password_hash"], current_password):
                raise ApiError(403, "WRONG_PASSWORD", "Current password is incorrect.")
            username = account.username if username is None else username.strip().lower()
            if not _USERNAME_RE.fullmatch(username):
                raise ApiError(422, "INVALID_USERNAME",
                               "Use 3–32 letters, numbers, dots, dashes or underscores.")
            if new_password is not None and not 8 <= len(new_password) <= 128:
                raise ApiError(422, "INVALID_PASSWORD", "Use 8–128 characters.")
            renamed = username != account.username
            if renamed and (
                    username in users
                    or any(_account_id(other) == username and _account_id(other) != account.account_id
                           for other in users.values())):
                raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.")
            if not renamed and new_password is None:
                return account

            updated_user = {**user, "username": username, "account_id": account.account_id}
            changed_fields = []
            if renamed:
                changed_fields.append("username")
            if new_password is not None:
                updated_user["password_hash"] = _password_hash(new_password)
                changed_fields.append("password")
            updated_users = users.copy()
            del updated_users[account.username]
            updated_users[username] = updated_user
            current_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
            updated_sessions = {}
            for key, session in sessions.items():
                if session["username"] == account.username:
                    if new_password is not None and key != current_key:
                        continue
                    if renamed:
                        session = {**session, "username": username}
                updated_sessions[key] = session
            self._write_locked(updated_users, updated_sessions)
        log.info("Updated account '%s': %s.", account.account_id, ", ".join(changed_fields))
        return Account(account_id=account.account_id, username=username)

    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            users, current_sessions = self._snapshot
            if username not in users:
                raise ValueError("Unknown account.")
            expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
            sessions = current_sessions.copy()
            sessions[key] = {
                "username": username,
                "created_utc": storage.utcnow(),
                "expires_utc": expires.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            self._write_locked(users, sessions)
        return token

    def user_for_token(self, token: str | None) -> Account | None:
        if not token:
            return None
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        users, sessions = self._snapshot
        session = sessions.get(key)
        if session is None or _utc_datetime(session["expires_utc"]) <= datetime.now(timezone.utc):
            return None
        user = users[session["username"]]
        return Account(account_id=_account_id(user), username=user["username"])

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            users, current_sessions = self._snapshot
            if key not in current_sessions:
                return
            sessions = current_sessions.copy()
            del sessions[key]
            self._write_locked(users, sessions)
