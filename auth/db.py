"""SQLite connection + schema bootstrap + DAO helpers for the W2 account system.

Follows the repo's existing pattern (hermes_scheduler): SQLite DB, path from
DREAMER_DB_PATH env (default <repo>/dreamer.db), idempotent CREATE TABLE IF
NOT EXISTS bootstrap. The canonical DDL lives in migrations/phase8_auth.sql
and is mirrored here so a fresh DB can bootstrap without a migration runner
(same convention as safety_events / session_logs).

Only the eight W2 tables are touched. safety_events (phase2.5) is never
written here.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "phase8_auth.sql"

# Mirrors migrations/phase8_auth.sql (must be kept in sync; the schema-pairing
# test asserts the live PRAGMA output against the SQL file).
_DDL = """\
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_verify_token TEXT,
    email_verify_expires_at TEXT,
    failed_logins INT NOT NULL DEFAULT 0,
    lock_until    TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id),
    expires_at    TEXT NOT NULL,
    created_ip    TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teacher_invites (
    code          TEXT PRIMARY KEY,
    created_by    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    used_by       TEXT,
    used_at       TEXT
);

CREATE TABLE IF NOT EXISTS students (
    id            TEXT PRIMARY KEY,
    parent_id     TEXT REFERENCES users(id),
    teacher_id    TEXT REFERENCES users(id),
    first_name    TEXT NOT NULL,
    age_band      TEXT NOT NULL,
    lang_code     TEXT NOT NULL,
    pin_hash      TEXT,
    pin_lock_until TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id            TEXT PRIMARY KEY,
    teacher_id    TEXT NOT NULL REFERENCES users(id),
    name          TEXT NOT NULL,
    join_code     TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_students (
    class_id      TEXT NOT NULL REFERENCES classes(id),
    student_id    TEXT NOT NULL REFERENCES students(id),
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS invites (
    token         TEXT PRIMARY KEY,
    parent_email  TEXT NOT NULL,
    student_id    TEXT NOT NULL REFERENCES students(id),
    class_id      TEXT NOT NULL REFERENCES classes(id),
    expires_at    TEXT NOT NULL,
    used_at       TEXT,
    superseded_by TEXT,
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_log (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id),
    student_id    TEXT REFERENCES students(id),
    doc_type      TEXT NOT NULL,
    doc_version   TEXT NOT NULL,
    action        TEXT NOT NULL,
    ip            TEXT,
    user_agent    TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_teacher_invites_expires ON teacher_invites(expires_at);
CREATE INDEX IF NOT EXISTS idx_consent_log_user ON consent_log(user_id, created_at DESC);
"""


def _db_path() -> str:
    default = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dreamer.db"
    )
    return os.path.abspath(os.environ.get("DREAMER_DB_PATH", default))


def connect() -> sqlite3.Connection:
    """Open a SQLite connection with row factory (WAL like the rest of the repo)."""
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_schema() -> None:
    """Idempotently create the eight W2 tables + indexes."""
    conn = connect()
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# DAO helpers (thin, no business logic — auth/api.py owns the rules)
# ---------------------------------------------------------------------------

def create_user(
    *,
    user_id: str,
    email: str,
    password_hash: str,
    role: str,
    email_verified: bool = False,
    email_verify_token: Optional[str] = None,
    email_verify_expires_at: Optional[str] = None,
) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO users
               (id, email, password_hash, role, email_verified,
                email_verify_token, email_verify_expires_at,
                failed_logins, lock_until, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)""",
            (
                user_id, email, password_hash, role,
                1 if email_verified else 0,
                email_verify_token, email_verify_expires_at,
                _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower(),)
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[sqlite3.Row]:
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def insert_teacher_invite(
    *, code: str, created_by: str, expires_at: str
) -> None:
    """Insert an unused teacher invite (admin-side helper; used by tests and
    admin tooling until a dedicated CLI lands)."""
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO teacher_invites (code, created_by, expires_at)
               VALUES (?, ?, ?)""",
            (code, created_by, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def is_invite_valid(code: str) -> Optional[sqlite3.Row]:
    """Return the invite row if exists, unused and not expired; else None."""
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT * FROM teacher_invites WHERE code = ?", (code,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        if row["used_by"] is not None:
            return None
        expires_at = row["expires_at"]
        if expires_at and expires_at < _now_iso():
            return None
        return row
    finally:
        conn.close()


def mark_invite_used(code: str, user_id: str) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE teacher_invites SET used_by = ?, used_at = ? WHERE code = ?",
            (user_id, _now_iso(), code),
        )
        conn.commit()
    finally:
        conn.close()


def create_session(
    *,
    session_id: str,
    user_id: str,
    expires_at: str,
    created_ip: Optional[str] = None,
) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO sessions (id, user_id, expires_at, created_ip, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, user_id, expires_at, created_ip, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_user(session_id: str) -> Optional[sqlite3.Row]:
    """Return the user row if session exists and not expired; else None."""
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT u.* FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.id = ? AND s.expires_at > ?""",
            (session_id, _now_iso()),
        )
        return cur.fetchone()
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def set_user_lock(user_id: str, lock_until: str) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET lock_until = ? WHERE id = ?",
            (lock_until, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def increment_failed_logins(user_id: str, count: int) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET failed_logins = ? WHERE id = ?",
            (count, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def reset_failed_logins(user_id: str) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET failed_logins = 0, lock_until = NULL WHERE id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def set_email_verify_token(
    user_id: str, token: str, expires_at: str
) -> None:
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            """UPDATE users
               SET email_verify_token = ?, email_verify_expires_at = ?
               WHERE id = ?""",
            (token, expires_at, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def consume_email_verify_token(
    token: str,
) -> Optional[sqlite3.Row]:
    """Atomically consume a single-use email verification token.

    Returns the updated user row on success (token valid, not expired, user
    not yet verified); clears the token columns so the same token cannot be
    reused. Returns None on unknown / expired / already-used token.
    """
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM users
               WHERE email_verify_token = ? AND email_verify_expires_at > ?""",
            (token, _now_iso()),
        )
        row = cur.fetchone()
        if row is None:
            return None
        conn.execute(
            """UPDATE users
               SET email_verified = 1,
                   email_verify_token = NULL,
                   email_verify_expires_at = NULL
               WHERE id = ?""",
            (row["id"],),
        )
        conn.commit()
        # Re-read so the returned row reflects the updated state.
        cur = conn.execute(
            "SELECT * FROM users WHERE id = ?", (row["id"],)
        )
        return cur.fetchone()
    finally:
        conn.close()
