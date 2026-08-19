-- Dreamer AI Phase 4 — Portfolio DB Schema
-- portfolio_items: student-facing artifact showcase items (Phase 6 Day 25)
-- Auto-candidates: assessment_logs label IN (achieved, exemplary) AND confidence >= 0.45
-- internal_label / confidence / rubric_id stored but NEVER rendered (PDPO + de-grading)

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS portfolio_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL UNIQUE,
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_excerpt TEXT NOT NULL DEFAULT '',
    competencies_4d TEXT NOT NULL DEFAULT '[]',
    growth_note TEXT NOT NULL DEFAULT '',
    kid_label TEXT NOT NULL DEFAULT '',
    internal_label TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    rubric_id TEXT NOT NULL DEFAULT '',
    achieved_at TEXT NOT NULL,
    linked_project_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_portfolio_student
    ON portfolio_items(student_id, achieved_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_topic
    ON portfolio_items(topic_id);
