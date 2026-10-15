-- Dreamer AI PR-2 — Teacher score audit (design book v1.1 §4.4)
--
-- PUT /api/teacher/scores is idempotent-overwrite: re-scoring the same
-- (student_id, week_no, skill_code) updates the existing assessment_logs
-- row, and the OLD value must be archived BEFORE the overwrite. This file
-- is the canonical DDL for that archive. auth/db.py keeps a mirrored copy
-- in _DDL (pairing-test convention) so ensure_schema() creates the table on
-- any DB, old or fresh — additive + brand-new, no ALTER, no deploy window.
--
-- Append-only by construction (evidence trail, never an editable record):
-- UPDATE / DELETE are blocked at the DB by triggers, same discipline as
-- ws_chat_relay_audit (phase8f).
--
-- Red-line 8: audit rows carry only the 8-char student mask (never the full
-- student id) plus the assessment_logs row id for traceability.

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
