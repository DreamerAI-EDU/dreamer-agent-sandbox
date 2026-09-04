-- Phase 8 (W2 PR#1): Account system DB schema — users / sessions / invites / students / classes / consent
-- Run against Dreamer DB (SQLite, DREAMER_DB_PATH or default repo dreamer.db).
-- Idempotent: all statements use IF NOT EXISTS, safe to re-run.
-- NOTE: safety_events (phase2.5) is untouched; auth code never writes to it.

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,           -- uuid
    email         TEXT UNIQUE NOT NULL,       -- normalized lowercase before insert
    password_hash TEXT NOT NULL,              -- Argon2id ($argon2id$ prefix)
    role          TEXT NOT NULL,              -- 'parent' / 'teacher' / 'admin'
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_verify_token TEXT,                  -- single-use email verification token (W2 §4)
    email_verify_expires_at TEXT,             -- ISO timestamp; NULL = no pending verification
    failed_logins INT NOT NULL DEFAULT 0,
    lock_until    TEXT,                       -- ISO timestamp, NULL = not locked
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,           -- random token (>=32 bytes entropy)
    user_id       TEXT NOT NULL REFERENCES users(id),
    expires_at    TEXT NOT NULL,              -- login session 7 days
    created_ip    TEXT,
    created_at    TEXT NOT NULL,
    stepped_up_until TEXT                    -- ISO timestamp; step-up auth 10min window
);

CREATE TABLE IF NOT EXISTS teacher_invites (
    code          TEXT PRIMARY KEY,
    created_by    TEXT NOT NULL,              -- admin CLI operator
    expires_at    TEXT NOT NULL,              -- 7 days
    used_by       TEXT,                       -- user_id
    used_at       TEXT
);

CREATE TABLE IF NOT EXISTS students (
    id            TEXT PRIMARY KEY,
    parent_id     TEXT REFERENCES users(id),  -- nullable: filled after parent confirmation
    teacher_id    TEXT REFERENCES users(id),
    first_name    TEXT NOT NULL,              -- B24: first name only, no other PII columns
    age_band      TEXT NOT NULL,              -- P1-P3 / P4-P6 / S1-S3
    lang_code     TEXT NOT NULL,              -- en / zh-hk / zh-cn
    pin_hash      TEXT,                       -- Argon2id PIN hash (PR#3)
    pin_lock_until TEXT,                      -- ISO timestamp; set on 10 consecutive wrong PINs
    failed_pin_count INT NOT NULL DEFAULT 0,  -- consecutive wrong PIN counter
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id            TEXT PRIMARY KEY,
    teacher_id    TEXT NOT NULL REFERENCES users(id),
    name          TEXT NOT NULL,
    join_code     TEXT NOT NULL,
    class_type    TEXT NOT NULL DEFAULT 'monthly',   -- monthly / workshop (W3-C)
    grade_band    TEXT,                              -- P1-P3 / P4-P6 / S1-S3 (W3-C)
    is_one_on_one INTEGER NOT NULL DEFAULT 0,        -- 0 / 1 (W3-C)
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_students (
    class_id      TEXT NOT NULL REFERENCES classes(id),
    student_id    TEXT NOT NULL REFERENCES students(id),
    status        TEXT NOT NULL,              -- pending / confirmed
    created_at    TEXT NOT NULL,
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS invites (
    token         TEXT PRIMARY KEY,
    parent_email  TEXT NOT NULL,
    student_id    TEXT NOT NULL REFERENCES students(id),
    class_id      TEXT NOT NULL REFERENCES classes(id),
    expires_at    TEXT NOT NULL,              -- 72h
    used_at       TEXT,
    superseded_by TEXT,                       -- re-sent link points to new token; old link invalid
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_log (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id),
    student_id    TEXT REFERENCES students(id),
    doc_type      TEXT NOT NULL,              -- privacy_policy / media_consent
    doc_version   TEXT NOT NULL,              -- e.g. v2026-08-26
    action        TEXT NOT NULL,              -- agreed / withdrawn (withdraw = new row, never mutate old row)
    ip            TEXT,
    user_agent    TEXT,
    created_at    TEXT NOT NULL
);

-- Indexes for the auth hot paths.
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_teacher_invites_expires ON teacher_invites(expires_at);
CREATE INDEX IF NOT EXISTS idx_consent_log_user ON consent_log(user_id, created_at DESC);
