-- =============================================================================
-- Phase 1 — SQLite Metadata Index (Hermes-Side)
-- Populated by phase1_kb_export.py during KB export from DeepTutor.
-- Hermes queries this index to filter topics by mode, grade, phase, and agent.
-- dreamer_phase is the teaching mainline; ib_atl_skills is cross-reference only.
-- =============================================================================

-- Core topic metadata table (one row per DeepTutor KB document)
CREATE TABLE IF NOT EXISTS topic_metadata (
    topic_id              TEXT PRIMARY KEY,                 -- e.g. 'maths-fractions-01'
    subject               TEXT NOT NULL,                    -- e.g. 'maths'
    topic                 TEXT NOT NULL,                    -- Human-readable title
    ai_literacy_context   TEXT,                             -- How this topic fits AI literacy
    modes_allowed         TEXT NOT NULL,                    -- JSON: ["contextual","direct","hybrid"]
    grade_level           TEXT NOT NULL,                    -- e.g. 'P4-P6'
    prerequisites         TEXT,                             -- JSON: ["topic_id", ...]
    linked_projects       TEXT,                             -- JSON: ["project_id", ...]

    -- Dreamer 4D: Teaching mainline (PRIMARY AXIS)
    dreamer_phase         TEXT NOT NULL,                    -- Dream / Discover / Design / Deliver

    -- IB ATL: Cross-reference ONLY (internal; school alignment conversation)
    ib_atl_skills         TEXT,                             -- JSON: ["thinking-critical","research-info-lit",...]

    ethical_ai_tags       TEXT,                             -- JSON: ["fairness","bias","privacy",...]

    -- Source tracking
    kb_name               TEXT NOT NULL,                    -- Which KB this belongs to
    document_path         TEXT NOT NULL,                    -- Relative path within KB
    document_hash         TEXT NOT NULL,                    -- SHA256 for change detection
    domain_agent_owner    TEXT NOT NULL,                    -- Which Domain Agent owns this topic

    -- Timestamps
    exported_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_modified         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index: Fast lookup by KB name (Hermes filtering by agent ownership)
CREATE INDEX IF NOT EXISTS idx_topic_kb ON topic_metadata(kb_name);

-- Index: Dreamer 4D phase filtering (mode routing primary axis)
CREATE INDEX IF NOT EXISTS idx_topic_phase ON topic_metadata(dreamer_phase);

-- Index: Grade-level filtering
CREATE INDEX IF NOT EXISTS idx_topic_grade ON topic_metadata(grade_level);

-- Index: Subject filtering
CREATE INDEX IF NOT EXISTS idx_topic_subject ON topic_metadata(subject);

-- Index: Mode routing (DIRECT / CONTEXTUAL / HYBRID)
-- Note: modes_allowed is JSON; use json_each() in queries for exact filtering.
-- This index is on the raw text for LIKE-based pre-filtering.
CREATE INDEX IF NOT EXISTS idx_topic_modes ON topic_metadata(modes_allowed);

-- Index: Domain agent ownership (access control)
CREATE INDEX IF NOT EXISTS idx_topic_agent ON topic_metadata(domain_agent_owner);

-- View: Topics grouped by Dreamer 4D phase (for Curriculum Navigator)
CREATE VIEW IF NOT EXISTS v_phase_curriculum AS
SELECT
    dreamer_phase,
    grade_level,
    subject,
    COUNT(*) AS topic_count,
    GROUP_CONCAT(DISTINCT kb_name) AS kb_list,
    GROUP_CONCAT(DISTINCT domain_agent_owner) AS agent_list
FROM topic_metadata
GROUP BY dreamer_phase, grade_level, subject
ORDER BY
    CASE dreamer_phase
        WHEN 'Dream'   THEN 1
        WHEN 'Discover'    THEN 2
        WHEN 'Design' THEN 3
        WHEN 'Deliver'     THEN 4
    END,
    grade_level;

-- View: Prerequisite chain for Curriculum Navigator
CREATE VIEW IF NOT EXISTS v_prerequisite_chain AS
SELECT
    t1.topic_id AS topic,
    t1.topic AS topic_name,
    t1.dreamer_phase,
    t2.topic_id AS prerequisite,
    t2.topic AS prerequisite_name,
    t2.dreamer_phase AS prerequisite_phase
FROM topic_metadata t1
JOIN json_each(t1.prerequisites) j
JOIN topic_metadata t2 ON t2.topic_id = j.value;

-- View: Ethical AI coverage audit (all topics with ethical tags)
CREATE VIEW IF NOT EXISTS v_ethical_audit AS
SELECT
    kb_name,
    topic_id,
    topic,
    ethical_ai_tags,
    dreamer_phase
FROM topic_metadata
WHERE ethical_ai_tags IS NOT NULL AND ethical_ai_tags != '[]'
ORDER BY kb_name, topic_id;
