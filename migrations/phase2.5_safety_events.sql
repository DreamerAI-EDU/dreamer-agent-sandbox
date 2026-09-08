-- Phase 2.5: Safety Events table for Input Guard audit trail
-- Run against Dreamer DB (SQLite phase1_sqlite.db or equivalent)

CREATE TABLE IF NOT EXISTS safety_events (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,        -- welfare / injection / age_inappropriate
    severity TEXT NOT NULL,          -- high (welfare) / medium / low
    raw_input TEXT NOT NULL,
    matched_rule TEXT,
    age_band TEXT,
    lang_code TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_safety_unreviewed
    ON safety_events(reviewed, severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_safety_student
    ON safety_events(student_id, created_at DESC);

-- Retention note (per PDPO risk register; W6 PR-B code-vs-doc fix):
-- Reviewed safety events are DELETED after 90 days by the retention
-- cleanup job (scripts/retention_cleanup.py). The earlier "anonymized
-- after 90 days" wording was superseded by the privacy-policy promise of
-- deletion (90 days, aligned with the AI-chat 90-day retention).
-- Unreviewed events are NEVER deleted by the retention job; the real
-- defence is health_monitor --check-retention failing loud when an
-- unreviewed event is older than 7 days (W6-R1 family).
-- Parental consent clause for B2C T&C is pending.
