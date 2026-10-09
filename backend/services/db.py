"""Local PostgreSQL connections and transactionally versioned schema."""
from __future__ import annotations

import getpass
import logging
import os
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool

from backend.settings import settings

log = logging.getLogger("cardiosentry.db")

MIGRATIONS: tuple[str, ...] = (
    """
CREATE TABLE schema_migrations (version integer PRIMARY KEY, applied_utc timestamptz NOT NULL DEFAULT now());

CREATE TABLE accounts (
  account_id    text PRIMARY KEY CHECK (account_id ~ '^[a-z0-9_.-]{3,32}$'),  -- permanent, never reused
  username      text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_.-]{3,32}$'), -- current sign-in name
  password_hash text NOT NULL,                                                  -- pbkdf2_sha256$600000$salt$hash
  created_utc   timestamptz NOT NULL
);
CREATE TABLE sessions (
  token_sha256 text PRIMARY KEY CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
  account_id   text NOT NULL REFERENCES accounts (account_id),   -- keyed by id => rename needs no session update
  created_utc  timestamptz NOT NULL,
  expires_utc  timestamptz NOT NULL
);
CREATE INDEX sessions_account_id_idx ON sessions (account_id);

CREATE TABLE captures (
  capture_id  text PRIMARY KEY CHECK (capture_id ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}_[0-9a-f]{6}$'),
  owner_id    text NOT NULL,          -- accounts.owner_of(record): record.owner or 'admin'. No FK on purpose
  created_utc timestamptz NOT NULL,   -- parsed from record.created_utc
  trashed_utc timestamptz,            -- NULL = live
  record      jsonb NOT NULL          -- CaptureRecord dump (legacy: as stored, minus NUL); owner NOT backfilled
);
CREATE INDEX captures_owner_live_idx ON captures (owner_id, capture_id DESC) WHERE trashed_utc IS NULL;
CREATE INDEX captures_created_utc_idx ON captures (created_utc);

CREATE TABLE prediction_runs (
  capture_id text NOT NULL REFERENCES captures (capture_id),
  run_id     text NOT NULL,           -- run ids are only unique per capture (ms stamp + model id)
  record     jsonb NOT NULL,          -- PredictionRecord dump / legacy run as stored
  PRIMARY KEY (capture_id, run_id)
);
CREATE TABLE explain_runs (
  capture_id text NOT NULL REFERENCES captures (capture_id),
  explain_id text NOT NULL,
  record     jsonb NOT NULL,          -- ExplainRecord dump / legacy record.json as stored
  PRIMARY KEY (capture_id, explain_id)
);
""",
)


def _parameters(url: str) -> dict[str, str]:
    try:
        parameters = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        destination = "unknown host:port/database"
        try:
            parsed = urlsplit(url)
            if parsed.scheme in {"postgres", "postgresql"}:
                host = parsed.hostname or "Unix socket"
                port = parsed.port or 5432
                database = unquote(parsed.path.lstrip("/")) or "unknown database"
                destination = f"{host}:{port}/{database}"
        except ValueError:
            pass
        raise RuntimeError(
            f"Invalid PostgreSQL connection URL for {destination}. "
            "Percent-encode special characters in the password."
        ) from None
    for key, variable in (
        ("host", "PGHOST"),
        ("hostaddr", "PGHOSTADDR"),
        ("port", "PGPORT"),
        ("dbname", "PGDATABASE"),
        ("user", "PGUSER"),
        ("password", "PGPASSWORD"),
        ("service", "PGSERVICE"),
    ):
        if not parameters.get(key) and os.environ.get(variable):
            parameters[key] = os.environ[variable]
    return parameters


def target(url: str) -> str:
    """Describe a connection without exposing its password."""
    parameters = _parameters(url)
    host = parameters.get("host") or parameters.get("hostaddr") or "Unix socket"
    port = parameters.get("port") or "5432"
    user = parameters.get("user") or getpass.getuser()
    database = parameters.get("dbname") or user
    return f"{host}:{port}/{database} (user {user})"


def connect(url: str | None = None) -> ConnectionPool:
    if url is None:
        if settings.database_url is None:
            raise RuntimeError(
                "Configure CARDIOSENTRY_DATABASE_URL / DATABASE_URL in .env "
                "to connect to the local PostgreSQL database."
            )
        url = settings.database_url.get_secret_value()
    if not url.strip():
        raise RuntimeError(
            "Configure CARDIOSENTRY_DATABASE_URL / DATABASE_URL in .env "
            "to connect to the local PostgreSQL database."
        )

    parameters = _parameters(url)
    destination = target(url)
    if parameters.get("service"):
        raise RuntimeError(
            f"PostgreSQL at {destination} must use an explicit local target, not service=."
        )
    for host in parameters.get("host", "").split(","):
        if host and host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
            raise RuntimeError(
                f"PostgreSQL at {destination} must be local "
                "(localhost, 127.0.0.1, ::1 or a Unix-socket path)."
            )
    for address in parameters.get("hostaddr", "").split(","):
        if address and address not in {"127.0.0.1", "::1"}:
            raise RuntimeError(f"PostgreSQL at {destination} must use a local hostaddr.")

    conninfo = make_conninfo(url, **parameters)
    pool: ConnectionPool | None = None
    try:
        with psycopg.connect(conninfo, connect_timeout=5):
            pass
        pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=8,
            timeout=10,
            open=True,
            check=ConnectionPool.check_connection,
            kwargs={"options": "-c TimeZone=UTC"},
            name="cardiosentry",
        )
        migrate(pool)
    except Exception as exc:
        if pool is not None:
            pool.close()
        detail = str(exc).replace(url, destination).replace(conninfo, destination)
        password = parameters.get("password")
        if password:
            detail = detail.replace(password, "<redacted>")
            detail = detail.replace(quote(password, safe=""), "<redacted>")
        detail = detail.splitlines()[0] if detail else type(exc).__name__
        action = "reach" if pool is None else "initialize"
        raise RuntimeError(
            f"Cannot {action} PostgreSQL at {destination}: {detail}. "
            "Is the container running? docker start postgres-db-cardiosentry"
        ) from None
    log.info("PostgreSQL at %s (schema v%d)", destination, len(MIGRATIONS))
    return pool


def migrate(pool: ConnectionPool) -> None:
    """Apply each schema version once, holding the lock through commit."""
    with pool.connection() as connection, connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (0x43415244494F,))
        exists = connection.execute("SELECT to_regclass('schema_migrations')").fetchone()[0]
        applied = (
            {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            if exists else set()
        )
        for version, sql in enumerate(MIGRATIONS, start=1):
            if version not in applied:
                connection.execute(sql)
                connection.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
