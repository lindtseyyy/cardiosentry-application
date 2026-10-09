"""PostgreSQL password accounts and persistent, opaque sign-in sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass

from psycopg.errors import UniqueViolation
from psycopg_pool import ConnectionPool

from backend.errors import ApiError

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


class AccountStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def ensure_admin(self) -> None:
        with self.pool.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM accounts WHERE account_id = %s", (ADMIN_ACCOUNT_ID,),
            ).fetchone() is not None:
                return
        password_hash = _password_hash("admin")
        with self.pool.connection() as conn:
            inserted = conn.execute(
                """INSERT INTO accounts (account_id, username, password_hash, created_utc)
                   VALUES (%s, %s, %s, now())
                   ON CONFLICT DO NOTHING RETURNING account_id""",
                (ADMIN_ACCOUNT_ID, ADMIN_ACCOUNT_ID, password_hash),
            ).fetchone()
        if inserted is not None:
            log.warning("Created default account '%s'; restrict access on untrusted networks.",
                        ADMIN_ACCOUNT_ID)

    def register(self, username: str, password: str) -> str:
        username = username.strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ApiError(422, "INVALID_USERNAME",
                           "Use 3–32 letters, numbers, dots, dashes or underscores.")
        if not 8 <= len(password) <= 128:
            raise ApiError(422, "INVALID_PASSWORD", "Use 8–128 characters.")
        with self.pool.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM accounts WHERE username = %s OR account_id = %s",
                (username, username),
            ).fetchone() is not None:
                raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.")
        password_hash = _password_hash(password)
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """INSERT INTO accounts (account_id, username, password_hash, created_utc)
                       VALUES (%s, %s, %s, now())""",
                    (username, username, password_hash),
                )
        except UniqueViolation:
            raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.") from None
        return username

    def authenticate(self, username: str, password: str) -> str:
        username = username.strip().lower()
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT password_hash FROM accounts WHERE username = %s", (username,),
            ).fetchone()
        if row is not None and _verify_password(row[0], password):
            return username
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong username or password.")

    def update_account(self, token: str | None, current_password: str,
                       username: str | None = None,
                       new_password: str | None = None) -> Account:
        if not token:
            raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        password_hash = (
            _password_hash(new_password)
            if new_password is not None and 8 <= len(new_password) <= 128 else None
        )
        try:
            with self.pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """SELECT accounts.account_id, accounts.username, accounts.password_hash
                       FROM sessions JOIN accounts USING (account_id)
                       WHERE token_sha256 = %s AND expires_utc > now()
                       FOR UPDATE OF accounts""",
                    (key,),
                ).fetchone()
                if row is None:
                    raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
                account = Account(account_id=row[0], username=row[1])
                if not _verify_password(row[2], current_password):
                    raise ApiError(403, "WRONG_PASSWORD", "Current password is incorrect.")
                username = account.username if username is None else username.strip().lower()
                if not _USERNAME_RE.fullmatch(username):
                    raise ApiError(422, "INVALID_USERNAME",
                                   "Use 3–32 letters, numbers, dots, dashes or underscores.")
                if new_password is not None and not 8 <= len(new_password) <= 128:
                    raise ApiError(422, "INVALID_PASSWORD", "Use 8–128 characters.")
                renamed = username != account.username
                if renamed and conn.execute(
                    """SELECT 1 FROM accounts
                       WHERE (username = %s OR account_id = %s) AND account_id <> %s""",
                    (username, username, account.account_id),
                ).fetchone() is not None:
                    raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.")
                if not renamed and new_password is None:
                    return account
                changed_fields = []
                if renamed:
                    changed_fields.append("username")
                if new_password is not None:
                    changed_fields.append("password")
                conn.execute(
                    """UPDATE accounts SET username = %s, password_hash = %s
                       WHERE account_id = %s""",
                    (username, row[2] if password_hash is None else password_hash,
                     account.account_id),
                )
                if new_password is not None:
                    conn.execute(
                        "DELETE FROM sessions WHERE account_id = %s AND token_sha256 <> %s",
                        (account.account_id, key),
                    )
        except UniqueViolation:
            raise ApiError(409, "USERNAME_TAKEN", "That username is already taken.") from None
        log.info("Updated account '%s': %s.", account.account_id, ", ".join(changed_fields))
        return Account(account_id=account.account_id, username=username)

    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("DELETE FROM sessions WHERE expires_utc <= now()")
            inserted = conn.execute(
                """INSERT INTO sessions (token_sha256, account_id, created_utc, expires_utc)
                   SELECT %s, account_id, now(), now() + make_interval(days => %s)
                   FROM accounts WHERE username = %s""",
                (key, SESSION_TTL_DAYS, username),
            )
            if inserted.rowcount == 0:
                raise ValueError("Unknown account.")
        return token

    def user_for_token(self, token: str | None) -> Account | None:
        if not token:
            return None
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.pool.connection() as conn:
            row = conn.execute(
                """SELECT accounts.account_id, accounts.username
                   FROM sessions JOIN accounts USING (account_id)
                   WHERE token_sha256 = %s AND expires_utc > now()""",
                (key,),
            ).fetchone()
        return None if row is None else Account(account_id=row[0], username=row[1])

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token_sha256 = %s", (key,))
