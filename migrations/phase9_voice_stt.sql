-- c1-13b Phase 1 — voice input (P1-P3 trial) usage meters.
-- Canonical DDL; mirrored in auth/db.py _DDL (the schema-pairing guard
-- compares the two, and _DDL is what ensure_schema() runs on a fresh DB).
--
-- 成本閘 #2/#3 (實施令 2026-10-04): the app-layer minute meters that stop
-- voice BEFORE the Azure budget alert (gate #1, portal-side $50) has a
-- chance to fire.
--
-- Privacy: minute counts only. Audio never reaches the database (原音即毁 is
-- enforced in auth/voice_stt.py: bytes live in memory for one request), and
-- no transcript text is stored here either.

CREATE TABLE IF NOT EXISTS voice_usage_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL,
    day         TEXT NOT NULL,      -- local (UTC+8) calendar day, YYYY-MM-DD
    seconds     INTEGER NOT NULL,   -- billed audio seconds for one segment
    provider    TEXT NOT NULL,      -- azure | deepgram (which meter moved)
    created_at  TEXT NOT NULL       -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_voice_usage_student_day
    ON voice_usage_ledger(student_id, day);

CREATE INDEX IF NOT EXISTS idx_voice_usage_day
    ON voice_usage_ledger(day);

-- One row per calendar month: the global minute meter plus the two markers
-- that make the auto-stop auditable (when it stopped, when ops was told).
CREATE TABLE IF NOT EXISTS voice_month_meter (
    month       TEXT PRIMARY KEY,   -- local (UTC+8) month, YYYY-MM
    seconds     INTEGER NOT NULL DEFAULT 0,
    stopped_at  TEXT,               -- set once, when the cap was reached
    alerted_at  TEXT,               -- set once, when the alert went out
    updated_at  TEXT NOT NULL
);
