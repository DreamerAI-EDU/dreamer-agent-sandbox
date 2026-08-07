-- =============================================================================
-- Dreamer AI — Database Schema
-- Version: v3 Phase 0
-- Engine: PostgreSQL 16
-- =============================================================================
-- Data flow:
--   Student → Hermes → DeepTutor → Response
--                   ↓ (async write)
--             Dreamer DB (assessment_logs, progress_snapshots, session_logs)
--                   ↑
--         Parent Report Agent queries Dreamer DB
--         Portfolio Agent queries Dreamer DB
-- =============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- 1. assessment_logs — Every grading event from DeepTutor
-- =============================================================================
CREATE TABLE assessment_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    topic_id        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('DIRECT', 'CONTEXTUAL', 'HYBRID')),
    lang_code       TEXT NOT NULL CHECK (lang_code IN ('en', 'zh-hk', 'zh-cn')),
    internal_label  TEXT NOT NULL CHECK (internal_label IN ('Not Yet', 'Developing', 'Achieved', 'Exemplary')),
    confidence      REAL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    rubric_id       TEXT,
    evidence_text   TEXT,
    agent_used      TEXT NOT NULL,
    cost_tokens     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_assessment_student   ON assessment_logs (student_id, created_at DESC);
CREATE INDEX idx_assessment_topic     ON assessment_logs (topic_id);
CREATE INDEX idx_assessment_mode      ON assessment_logs (mode);
CREATE INDEX idx_assessment_subject   ON assessment_logs (subject);
CREATE INDEX idx_assessment_session   ON assessment_logs (session_id);

COMMENT ON TABLE assessment_logs IS 'Every DeepTutor grading event. Written async by Hermes after each student interaction.';
COMMENT ON COLUMN assessment_logs.internal_label IS 'Dreamer Progress Levels (cross-ref: IB-style criterion language)';
COMMENT ON COLUMN assessment_logs.mode IS 'DIRECT = exam tutoring, CONTEXTUAL = AI literacy projects, HYBRID = both';


-- =============================================================================
-- 2. progress_snapshots — Aggregated per student per topic, upserted
-- =============================================================================
CREATE TABLE progress_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id      TEXT NOT NULL,
    topic_id        TEXT NOT NULL,
    mastery_pct     REAL NOT NULL CHECK (mastery_pct >= 0.0 AND mastery_pct <= 1.0),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_label      TEXT CHECK (last_label IN ('Not Yet', 'Developing', 'Achieved', 'Exemplary')),
    streak          INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_student_topic UNIQUE (student_id, topic_id)
);

CREATE INDEX idx_snapshot_student ON progress_snapshots (student_id);
CREATE INDEX idx_snapshot_label   ON progress_snapshots (last_label);

COMMENT ON TABLE progress_snapshots IS 'Aggregate progress per student per topic. Upserted on every assessment event.';
COMMENT ON COLUMN progress_snapshots.mastery_pct IS '0.0 to 1.0, calculated from label progression over time';
COMMENT ON COLUMN progress_snapshots.streak IS 'Consecutive improvements on this topic';


-- =============================================================================
-- 3. session_logs — Audit trail for parent transparency
-- =============================================================================
CREATE TABLE session_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('DIRECT', 'CONTEXTUAL', 'HYBRID')),
    lang_code       TEXT NOT NULL CHECK (lang_code IN ('en', 'zh-hk', 'zh-cn')),
    agent_list      JSONB NOT NULL DEFAULT '[]',
    topic_ids       JSONB NOT NULL DEFAULT '[]',
    duration_seconds INTEGER,
    turn_count      INTEGER,
    exit_reason     TEXT CHECK (exit_reason IN ('completed', 'timeout', 'student_left', 'error')),
    cost_total_tokens INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_session_student   ON session_logs (student_id, created_at DESC);
CREATE INDEX idx_session_mode      ON session_logs (mode);
CREATE INDEX idx_session_lang      ON session_logs (lang_code);
CREATE INDEX idx_session_exit      ON session_logs (exit_reason);

COMMENT ON TABLE session_logs IS 'Per-session audit trail. One row per student session.';
COMMENT ON COLUMN session_logs.agent_list IS 'JSON array: ["Curriculum Agent", "Assessment Agent"]';
COMMENT ON COLUMN session_logs.topic_ids IS 'JSON array: ["maths-fractions-01", "science-energy-02"]';


-- =============================================================================
-- 4. students — Minimal student profile (GDPR-compliant, no PII beyond ID)
-- =============================================================================
CREATE TABLE students (
    id              TEXT PRIMARY KEY,                -- Opaque student ID (not real name)
    grade_level     TEXT NOT NULL,                   -- P1-P6, S1-S3
    preferred_lang  TEXT NOT NULL DEFAULT 'zh-hk'    -- en / zh-hk / zh-cn
        CHECK (preferred_lang IN ('en', 'zh-hk', 'zh-cn')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ
);

COMMENT ON TABLE students IS 'Minimal student profile. Opaque ID only, no PII.';


-- =============================================================================
-- 5. rubric_registry — Dreamer 4D rubrics used by Assessment Agent
-- =============================================================================
CREATE TABLE rubric_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rubric_id       TEXT NOT NULL UNIQUE,
    subject         TEXT NOT NULL,
    topic_id        TEXT NOT NULL,
    grade_level     TEXT NOT NULL,
    criteria        JSONB NOT NULL,                  -- [{band, descriptor, examples}]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rubric_topic ON rubric_registry (topic_id);
CREATE INDEX idx_rubric_grade ON rubric_registry (grade_level);

COMMENT ON TABLE rubric_registry IS 'Dreamer 4D rubrics with IB ATL cross-reference. criteria JSONB maps band → descriptor → examples.';


-- =============================================================================
-- 6. ethical_ai_audit — Samples flagged by kid-safe output layer
-- =============================================================================
CREATE TABLE ethical_ai_audit (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      TEXT NOT NULL,
    student_id      TEXT NOT NULL,
    trigger_tag     TEXT NOT NULL,                   -- fairness, safety, privacy, bias, etc.
    raw_output      TEXT,
    rewritten_output TEXT,
    reviewer_action TEXT,                            -- approved / overridden / escalated
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ
);

CREATE INDEX idx_ethical_session ON ethical_ai_audit (session_id);
CREATE INDEX idx_ethical_tag     ON ethical_ai_audit (trigger_tag);
CREATE INDEX idx_ethical_reviewed ON ethical_ai_audit (reviewed_at) WHERE reviewed_at IS NULL;

COMMENT ON TABLE ethical_ai_audit IS 'Ethical AI flag log. Kid-safe layer writes here when tone rewrite is applied.';


-- =============================================================================
-- Helper: Upsert progress_snapshots on assessment_logs insert
-- =============================================================================
CREATE OR REPLACE FUNCTION upsert_progress_snapshot()
RETURNS TRIGGER AS $$
DECLARE
    prev_label TEXT;
BEGIN
    -- Get previous label for streak calculation
    SELECT last_label INTO prev_label
    FROM progress_snapshots
    WHERE student_id = NEW.student_id AND topic_id = NEW.topic_id;

    INSERT INTO progress_snapshots (student_id, topic_id, mastery_pct, attempt_count, last_label, streak)
    VALUES (
        NEW.student_id,
        NEW.topic_id,
        CASE NEW.internal_label
            WHEN 'Not Yet'    THEN 0.25
            WHEN 'Developing' THEN 0.50
            WHEN 'Achieved'   THEN 0.75
            WHEN 'Exemplary'  THEN 1.00
        END,
        1,
        NEW.internal_label,
        0
    )
    ON CONFLICT (student_id, topic_id) DO UPDATE SET
        mastery_pct = CASE NEW.internal_label
            WHEN 'Not Yet'    THEN GREATEST(progress_snapshots.mastery_pct, 0.25)
            WHEN 'Developing' THEN GREATEST(progress_snapshots.mastery_pct, 0.50)
            WHEN 'Achieved'   THEN GREATEST(progress_snapshots.mastery_pct, 0.75)
            WHEN 'Exemplary'  THEN 1.00
        END,
        attempt_count = progress_snapshots.attempt_count + 1,
        last_label = NEW.internal_label,
        streak = CASE
            WHEN prev_label IS NULL THEN 0
            WHEN (prev_label = 'Not Yet' AND NEW.internal_label IN ('Developing', 'Achieved', 'Exemplary')) THEN progress_snapshots.streak + 1
            WHEN (prev_label = 'Developing' AND NEW.internal_label IN ('Achieved', 'Exemplary')) THEN progress_snapshots.streak + 1
            WHEN (prev_label = 'Achieved' AND NEW.internal_label = 'Exemplary') THEN progress_snapshots.streak + 1
            ELSE 0
        END,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_upsert_progress
    AFTER INSERT ON assessment_logs
    FOR EACH ROW
    EXECUTE FUNCTION upsert_progress_snapshot();
