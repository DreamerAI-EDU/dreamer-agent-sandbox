-- Dreamer AI Phase 3 — Assessment DB Schema
-- assessment_logs: append-only audit trail for every auto_marking call
-- progress_snapshots: upsert-on-conflict for per-student per-topic progress

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS assessment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en',
    internal_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    rubric_id TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '',
    agent_used TEXT NOT NULL DEFAULT 'assessment',
    cost_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_student
    ON assessment_logs(student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_topic
    ON assessment_logs(topic_id, created_at);

CREATE TABLE IF NOT EXISTS progress_snapshots (
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    mastery_pct REAL NOT NULL DEFAULT 0.0,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    last_label TEXT NOT NULL DEFAULT '',
    streak INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (student_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_student
    ON progress_snapshots(student_id);
