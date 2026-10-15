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

# PR-1 parent reports (design book v1.1 §3, boss sign-off 2026-10-15). Canonical
# DDL lives in migrations/phase8_parent_reports.sql; mirrored here (pairing-test
# convention) so ensure_schema() creates parent_reports on any DB, old or fresh.
# The assessment_logs ALTERs are NOT carried by _DDL — an existing DB applies
# them via apply_phase8_parent_reports_migration() (startup auto-migration is
# still backlog, same convention as class_curriculum / W3-C columns).
_PR_PARENT_REPORTS_DDL = """\
-- §3.2 报告主表 parent_reports（借 plan_proposals 样板）
CREATE TABLE IF NOT EXISTS parent_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     TEXT NOT NULL UNIQUE,
    version       INTEGER NOT NULL DEFAULT 1,
    student_id    TEXT NOT NULL,
    class_id      TEXT NOT NULL,                 -- 课程锚点（见 §3.4）
    week_from     INTEGER NOT NULL DEFAULT 1,
    week_to       INTEGER NOT NULL DEFAULT 8,
    status        TEXT NOT NULL DEFAULT 'pending_review',
    lang_code     TEXT NOT NULL DEFAULT 'zh-hk',
    age_band      TEXT NOT NULL DEFAULT '',      -- H-2 修复后恒为真实 band
    scores        TEXT NOT NULL DEFAULT '{}',    -- {"DREAM":3,"DISCOVER":2,...}
    payload       TEXT NOT NULL DEFAULT '{}',    -- 完整报告内容（按 lang_code 单语生成）
    teacher_edits TEXT NOT NULL DEFAULT '[]',    -- 老师修改审计，append-only
    review        TEXT NOT NULL DEFAULT '{}',
    cost_summary  TEXT NOT NULL DEFAULT '{}',
    generated_by  TEXT NOT NULL DEFAULT 'auto',
    pdf_path      TEXT NOT NULL DEFAULT '',
    pdf_sha256    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    approved_at   TEXT NOT NULL DEFAULT '',
    approved_by   TEXT NOT NULL DEFAULT '',
    published_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_parent_reports_student
    ON parent_reports(student_id, status, version);
CREATE INDEX IF NOT EXISTS idx_parent_reports_class
    ON parent_reports(class_id, status);

-- 幂等硬闸（借 uq_plan_proposals_one_pending 样板）：
-- 同一学生同一课程同时最多一份待审
CREATE UNIQUE INDEX IF NOT EXISTS uq_parent_reports_one_pending
    ON parent_reports(student_id, class_id) WHERE status = 'pending_review';
"""

# PR-2 teacher score audit (design book v1.1 §4.4, boss work order 2026-10-15).
# Canonical DDL lives in migrations/phase8h_teacher_score_audit.sql; mirrored
# here (pairing-test convention) so ensure_schema() creates it on any DB, old
# or fresh — additive and brand-new, no ALTER, no deploy window.
# Append-only by construction (evidence, never an editable record):
# UPDATE/DELETE are blocked at the DB by triggers, same discipline as
# ws_chat_relay_audit (phase8f). Red-line 8: audit rows carry only the 8-char
# student mask (never the full student id) plus the assessment_logs row id.
_TEACHER_SCORE_AUDIT_DDL = """\
CREATE TABLE IF NOT EXISTS teacher_score_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_mask  TEXT NOT NULL,
    week_no       INTEGER NOT NULL,
    skill_code    TEXT NOT NULL,
    old_score     INTEGER,
    old_evidence  TEXT NOT NULL DEFAULT '',
    assessment_id INTEGER NOT NULL DEFAULT 0,
    replaced_by   TEXT NOT NULL,
    replaced_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_teacher_score_audit_key
    ON teacher_score_audit(student_mask, week_no, skill_code);

CREATE INDEX IF NOT EXISTS idx_teacher_score_audit_assessment
    ON teacher_score_audit(assessment_id);

CREATE TRIGGER IF NOT EXISTS teacher_score_audit_no_update
BEFORE UPDATE ON teacher_score_audit
BEGIN
    SELECT RAISE(ABORT, 'teacher_score_audit is append-only (no UPDATE)');
END;

CREATE TRIGGER IF NOT EXISTS teacher_score_audit_no_delete
BEFORE DELETE ON teacher_score_audit
BEGIN
    SELECT RAISE(ABORT, 'teacher_score_audit is append-only (no DELETE)');
END;
"""


# PR-3 report state-machine guards (design book v1.1 §3.2 / §4.1, boss work
# order 2026-10-15). Canonical DDL lives in
# migrations/phase8i_pr3_report_state_machine.sql (②③); mirrored here so a
# fresh DB created by ensure_schema() carries exactly the same guards as an
# upgraded DB. Both triggers hang off parent_reports only, so they are safe to
# append to the tail of _DDL (table-first, trigger-last).
_PR3_PARENT_REPORTS_GUARDS_DDL = """\
-- ② 报告行永不 DELETE（§3.2：只 UPDATE status／版本 supersede）
CREATE TRIGGER IF NOT EXISTS parent_reports_no_delete
BEFORE DELETE ON parent_reports
BEGIN
    SELECT RAISE(ABORT, 'parent_reports is append-only (no DELETE, design book v1.1 §3.2)');
END;

-- ③ teacher_edits 只增不减、不可重写（§4.2：字段级 diff 审计链不可抹除）
CREATE TRIGGER IF NOT EXISTS parent_reports_teacher_edits_append_only
BEFORE UPDATE OF teacher_edits ON parent_reports
FOR EACH ROW
WHEN json_valid(OLD.teacher_edits) AND json_valid(NEW.teacher_edits)
     AND (
          json_array_length(NEW.teacher_edits) < json_array_length(OLD.teacher_edits)
          OR NEW.teacher_edits NOT LIKE
             substr(OLD.teacher_edits, 1, length(OLD.teacher_edits) - 1) || '%'
     )
BEGIN
    SELECT RAISE(ABORT, 'parent_reports.teacher_edits is append-only (no rewrite, no shrink)');
END;
"""


# PR-3 ① TOCTOU hard gate (PR-2 follow-up, boss red line). NOT part of _DDL:
# the index lives on assessment_logs, which auth/db.py does not own (the agent
# layer creates it), so it cannot be created by a fresh-DB executescript.
# apply_phase8i_pr3_migration() probes for the table first and is also called
# at the tail of apply_phase8_parent_reports_migration() (post-migration 补钉),
# so every path that has assessment_logs ends up with the gate.
_PR3_TEACHER_SCORE_UNIQUE_DDL = """\
CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_teacher_score
    ON assessment_logs(student_id, week_no, skill_code)
    WHERE scored_by = 'teacher';
"""


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
    created_at    TEXT NOT NULL,
    stepped_up_until TEXT
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
    failed_pin_count INT NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id            TEXT PRIMARY KEY,
    teacher_id    TEXT NOT NULL REFERENCES users(id),
    name          TEXT NOT NULL,
    join_code     TEXT NOT NULL,
    class_type    TEXT NOT NULL DEFAULT 'monthly',
    grade_band    TEXT,
    is_one_on_one INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    curriculum_id TEXT
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

-- Bridge-2: class ↔ curriculum mounting (canonical DDL lives in
-- migrations/phase8c_class_curriculum.sql). Week 1..8 linear progression is
-- enforced by the status machine + the partial unique index below, never by
-- the frontend (boss ruling #2). classes.curriculum_id is declared above as
-- the last column so migrated DBs (ALTER appends) and fresh DBs agree.
CREATE TABLE IF NOT EXISTS class_curriculum (
    class_id     TEXT NOT NULL REFERENCES classes(id),
    topic_id     TEXT NOT NULL REFERENCES topic_metadata(topic_id),
    week_no      INTEGER NOT NULL CHECK (week_no BETWEEN 1 AND 8),
    status       TEXT NOT NULL CHECK (status IN ('locked', 'active', 'completed')),
    activated_at TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (class_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_class_curriculum_week
    ON class_curriculum(class_id, week_no);

-- At most one active week per class: two open weeks must be impossible.
CREATE UNIQUE INDEX IF NOT EXISTS idx_class_curriculum_one_active
    ON class_curriculum(class_id) WHERE status = 'active';

-- W4 PR-D: forgot-password reset tokens — DB stores ONLY the SHA-256 hash of
-- the raw token (three-iron-rule); plaintext appears only in the email link.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash TEXT PRIMARY KEY,           -- SHA-256 hex of the raw token (never the raw token)
    user_id    TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,              -- ISO timestamp; now + RESET_TOKEN_MINUTES
    used_at    TEXT,                       -- ISO timestamp; single-use marker
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id, expires_at);

-- Bridge-3d: student self-login (join code + PIN, no email). Canonical DDL
-- lives in migrations/phase8d_student_login.sql. A kid has no users row, so
-- student_sessions is an independent opaque-token store; student_login_locks
-- is a separate 5-strike/10-minute scope counter that never touches the
-- locked 10/1 pin-verify contract on students.failed_pin_count.
CREATE TABLE IF NOT EXISTS student_sessions (
    id         TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id),
    expires_at TEXT NOT NULL,
    created_ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_student_sessions_student
    ON student_sessions(student_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_student_sessions_expires
    ON student_sessions(expires_at);

CREATE TABLE IF NOT EXISTS student_login_locks (
    scope        TEXT PRIMARY KEY,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at   TEXT NOT NULL
);

-- Bridge-3e: payment mark-paid (boss work order 2026-09-13, decision ②).
-- Canonical DDL lives in migrations/phase8e_payments.sql. Additive and
-- brand-new: carried by _DDL means ensure_schema() creates it on any DB, old
-- or fresh — no ALTER, so the deploy window needs no extra step. One row per
-- student (PRIMARY KEY) holding the CURRENT status; a flip is an UPDATE of
-- that row and history lives in the append-only payment_marked audit events.
CREATE TABLE IF NOT EXISTS payments (
    student_id TEXT PRIMARY KEY REFERENCES students(id),
    status     TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'paid'
    marked_by  TEXT,                              -- admin users.id; NULL = never marked
    marked_at  TEXT,                              -- ISO timestamp of the last flip
    note       TEXT                               -- optional operator note
);

CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

-- W3-C P3: WS chat relay audit (boss work order 2026-09-14). Canonical DDL
-- lives in migrations/phase8f_ws_chat_relay_audit.sql. Additive and brand-new:
-- carried by _DDL means ensure_schema() creates it on any DB, old or fresh —
-- no ALTER, so the deploy window needs no extra step. Append-only is enforced
-- in the DB by the two triggers below (a relay audit row is evidence, never an
-- editable record); retention/pruning scripts must skip this table.
CREATE TABLE IF NOT EXISTS ws_chat_relay_audit (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at    TEXT    NOT NULL,
    event          TEXT    NOT NULL,
    session_id     TEXT,
    turn_id        TEXT,
    student_mask   TEXT,
    attempt        INTEGER,
    final_status   TEXT,
    upstream_error TEXT,
    detail         TEXT
);

CREATE INDEX IF NOT EXISTS idx_ws_relay_audit_session
    ON ws_chat_relay_audit(session_id);

CREATE INDEX IF NOT EXISTS idx_ws_relay_audit_event
    ON ws_chat_relay_audit(event);

CREATE TRIGGER IF NOT EXISTS ws_chat_relay_audit_no_update
BEFORE UPDATE ON ws_chat_relay_audit
BEGIN
    SELECT RAISE(ABORT, 'ws_chat_relay_audit is append-only (no UPDATE)');
END;

CREATE TRIGGER IF NOT EXISTS ws_chat_relay_audit_no_delete
BEFORE DELETE ON ws_chat_relay_audit
BEGIN
    SELECT RAISE(ABORT, 'ws_chat_relay_audit is append-only (no DELETE)');
END;

-- P4: WS chat session map (boss work order 2026-09-15). Canonical DDL lives
-- in migrations/phase8g_ws_chat_session_map.sql. Additive and brand-new:
-- carried by _DDL means ensure_schema() creates it on any DB, old or fresh —
-- no ALTER, so the deploy window needs no extra step. Business table (NOT
-- append-only): row is created when the engine assigns a fresh session and
-- replaced when a dead session is evicted (INSERT ... ON CONFLICT DO
-- UPDATE — atomic upsert, created_at kept). Red-line 8
-- ruling 2026-09-15: business tables keyed by student_id are precedent
-- (payments / students); the FK keeps integrity in the DB.
CREATE TABLE IF NOT EXISTS ws_chat_session_map (
    student_id     TEXT PRIMARY KEY,
    engine_session TEXT NOT NULL,            -- DeepTutor unified_xxx
    created_at     TEXT NOT NULL,            -- ISO-8601 UTC
    updated_at     TEXT NOT NULL,            -- last engine-session change
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE INDEX IF NOT EXISTS idx_ws_session_map_updated
    ON ws_chat_session_map(updated_at);

-- c1-13b Phase 1 voice usage meters (boss 實施令 2026-10-04). Canonical DDL
-- lives in migrations/phase9_voice_stt.sql. Additive and brand-new, carried by
-- _DDL means ensure_schema() creates them on any DB, old or fresh — no ALTER,
-- so the deploy window needs no extra step. Minutes only: audio never reaches
-- the database (原音即毁 enforced in auth/voice_stt.py).
CREATE TABLE IF NOT EXISTS voice_usage_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL,
    day         TEXT NOT NULL,      -- local (UTC+8) calendar day, YYYY-MM-DD
    seconds     INTEGER NOT NULL,
    provider    TEXT NOT NULL,      -- azure | deepgram
    created_at  TEXT NOT NULL       -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_voice_usage_student_day
    ON voice_usage_ledger(student_id, day);

CREATE INDEX IF NOT EXISTS idx_voice_usage_day
    ON voice_usage_ledger(day);

CREATE TABLE IF NOT EXISTS voice_month_meter (
    month       TEXT PRIMARY KEY,   -- local (UTC+8) month, YYYY-MM
    seconds     INTEGER NOT NULL DEFAULT 0,
    stopped_at  TEXT,
    alerted_at  TEXT,
    updated_at  TEXT NOT NULL
);
""" + _PR_PARENT_REPORTS_DDL + _TEACHER_SCORE_AUDIT_DDL + _PR3_PARENT_REPORTS_GUARDS_DDL


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


# W3-C class metadata columns (boss ruling 2026-09-04): one migration, three
# columns. Deliberately NOT run from ensure_schema — startup auto-migration is
# still backlog — so existing VPS DBs need a manual step (see runbook).
_CLASS_META_COLUMNS = {
    "class_type": "TEXT NOT NULL DEFAULT 'monthly'",
    "grade_band": "TEXT",
    "is_one_on_one": "INTEGER NOT NULL DEFAULT 0",
}


def apply_class_meta_migration() -> None:
    """Idempotently add the W3-C class metadata columns to an existing DB.

    Checks PRAGMA table_info before every ALTER; safe to re-run. Existing rows
    get class_type='monthly' / is_one_on_one=0 via the DEFAULT clause.
    """
    conn = connect()
    try:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(classes)")
        }
        for col, decl in _CLASS_META_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE classes ADD COLUMN {col} {decl}")
        conn.commit()
    finally:
        conn.close()


# Bridge-2 class↔curriculum column (boss work order 2026-09-11). Additive,
# idempotent, and — like the W3-C block above — deliberately NOT run from
# ensure_schema (startup auto-migration is still backlog); a deploy applies it
# via this helper. The class_curriculum table itself is carried by _DDL and is
# therefore created by ensure_schema() on any DB, old or fresh.
_CC_CLASS_COLUMNS = {
    "curriculum_id": "TEXT",
}


def apply_class_curriculum_migration() -> None:
    """Idempotently add classes.curriculum_id (Bridge-2). Safe to re-run."""
    conn = connect()
    try:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(classes)")
        }
        for col, decl in _CC_CLASS_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE classes ADD COLUMN {col} {decl}")
        conn.commit()
    finally:
        conn.close()


# PR-1 parent reports (design book v1.1 §3, boss sign-off 2026-10-15).
# Existing-DB half of migrations/phase8_parent_reports.sql: the assessment_logs
# ALTERs (probe-first, safe to re-run) plus the parent_reports table/indexes.
# Fresh DBs get the same table from ensure_schema()'s _DDL mirror.
_PR_ASSESSMENT_COLUMNS = {
    "age_band": "TEXT NOT NULL DEFAULT ''",
    "week_no": "INTEGER NOT NULL DEFAULT 0",
    "skill_code": "TEXT NOT NULL DEFAULT ''",
    "score_0_3": "INTEGER DEFAULT NULL CHECK (score_0_3 IS NULL OR (score_0_3 BETWEEN 0 AND 3))",
    "scored_by": "TEXT NOT NULL DEFAULT 'auto'",
    "report_id": "TEXT NOT NULL DEFAULT ''",
}


def apply_phase8_parent_reports_migration() -> None:
    """Idempotently apply migrations/phase8_parent_reports.sql to an existing DB.

    Mirrors apply_class_curriculum_migration: ALTERs probe PRAGMA table_info
    before every ADD COLUMN (safe to re-run); the parent_reports table + indexes
    are (re)created via IF NOT EXISTS. The _DDL mirror in ensure_schema() keeps
    fresh DBs identical (pairing-test convention).
    """
    conn = connect()
    try:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(assessment_logs)")
        }
        for col, decl in _PR_ASSESSMENT_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE assessment_logs ADD COLUMN {col} {decl}")
        conn.executescript(_PR_PARENT_REPORTS_DDL)
        conn.commit()
    finally:
        conn.close()
    # Post-migration 补钉 (PR-3 ①): every path that just prepared assessment_logs
    # for parent reports also gets the TOCTOU hard gate, so an existing VPS DB
    # can never end up with the teacher-score columns but without the index.
    apply_phase8i_pr3_migration()


def apply_phase8i_pr3_migration() -> None:
    """Idempotently apply migrations/phase8i_pr3_report_state_machine.sql.

    Two independent, additive pieces:

    * ① the teacher-score TOCTOU hard gate — a partial unique index on
      assessment_logs(student_id, week_no, skill_code) WHERE scored_by='teacher'
      (PR-2's only low-severity finding, folded into PR-3 by the boss). Skipped
      when assessment_logs is absent (fresh DB before the agent layer runs).
    * ②③ the parent_reports append-only guards — already carried by _DDL for
      fresh DBs, re-applied here so upgraded DBs match byte-for-byte.

    Safe to re-run: IF NOT EXISTS everywhere, no ALTER, no data movement.
    """
    conn = connect()
    try:
        has_assessment_logs = conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type='table' AND name='assessment_logs'"
        ).fetchone()
        if has_assessment_logs:
            conn.executescript(_PR3_TEACHER_SCORE_UNIQUE_DDL)
        has_parent_reports = conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type='table' AND name='parent_reports'"
        ).fetchone()
        if has_parent_reports:
            conn.executescript(_PR3_PARENT_REPORTS_GUARDS_DDL)
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


def get_session_row(session_id: str) -> Optional[sqlite3.Row]:
    """Return the raw session row (no expiry check) or None.

    Used by the step-up gate: the caller compares `stepped_up_until`
    against the current time itself so the check is performed fresh on
    every protected request (never cached outside the request).
    """
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        return cur.fetchone()
    finally:
        conn.close()


def set_session_stepped_up(session_id: str, until_iso: str) -> None:
    """Mark the session as step-up authorised until `until_iso` (W2 PR#4)."""
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE sessions SET stepped_up_until = ? WHERE id = ?",
            (until_iso, session_id),
        )
        conn.commit()
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


def revoke_all_sessions(user_id: str) -> None:
    """Delete every session row for a user (password-reset side effect).

    The user must re-login everywhere after a reset; existing cookies are
    useless once their session rows are gone.
    """
    ensure_schema()
    conn = connect()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def update_user_password(user_id: str, password_hash: str) -> None:
    """Replace the user's Argon2id password hash and clear lockout state."""
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, failed_logins = 0, "
            "lock_until = NULL WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_lang_code(user_id: str) -> Optional[str]:
    """Best-effort account language for email copy (W4 PR-D §3.3).

    users has no lang_code column; the account's language lives on its
    students rows (teacher via teacher_id, parent via parent_id). Return the
    first matching student's lang_code, or None when no student is linked
    (caller falls back to zh-hk)."""
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT lang_code FROM students "
            "WHERE parent_id = ? OR teacher_id = ? "
            "ORDER BY created_at ASC LIMIT 1",
            (user_id, user_id),
        )
        row = cur.fetchone()
        return row["lang_code"] if row is not None else None
    finally:
        conn.close()


def insert_password_reset_token(
    user_id: str, token_hash: str, expires_at: str
) -> None:
    """Store a new reset token hash, invalidating any older pending ones.

    New-application-wastes-old: every pending (unused) row for the user is
    deleted first so only one valid reset link exists at a time.
    """
    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        conn.execute(
            """INSERT INTO password_reset_tokens
               (token_hash, user_id, expires_at, used_at, created_at)
               VALUES (?, ?, ?, NULL, ?)""",
            (token_hash, user_id, expires_at, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def consume_password_reset_token(
    token_hash: str,
) -> Optional[sqlite3.Row]:
    """Atomically consume a single-use password reset token.

    Returns the joined user row on success (token valid, not expired, not yet
    used); marks used_at so the same token can never be reused. Returns None on
    unknown / expired / already-used tokens.
    """
    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT u.* FROM password_reset_tokens t
               JOIN users u ON u.id = t.user_id
               WHERE t.token_hash = ? AND t.used_at IS NULL
                 AND t.expires_at > ?""",
            (token_hash, _now_iso()),
        )
        row = cur.fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ?",
            (_now_iso(), token_hash),
        )
        conn.commit()
        return row
    finally:
        conn.close()
