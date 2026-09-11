-- =============================================================================
-- Phase 1 — SQLite Metadata Index (Hermes-Side)
-- Populated by phase1_kb_export.py during KB export from DeepTutor.
-- Hermes queries this index to filter topics by mode, grade, phase, and KB.
--
-- SINGLE SOURCE OF TRUTH (Bridge-1, 2026-09):
--   pipeline/topic_metadata_schema.py reads THIS FILE to create/migrate the
--   table. agents/curriculum_navigator.py no longer bootstraps a private
--   6-column table; both go through topic_metadata_schema.ensure_schema().
--
-- FORMAT: list-valued fields (modes_allowed, prerequisites, linked_projects,
--   ib_atl_skills, ethical_ai_tags) are JSON arrays. dreamer_phase is ALSO a
--   JSON array — wk03-wk07 are genuinely cross-phase (["Design","Deliver"])
--   and must not be flattened to a single string.
--
-- REMOVED: domain_agent_owner — phantom field (B21 spec §5), never written.
--
-- EXTENSION (Bridge-1, decision 4): `week` — the curriculum week ordinal
--   1..8 taken from a document's frontmatter `week` key
--   (dreamer-curriculum/wkNN). Additive and nullable: non-curriculum rows
--   keep NULL. Decision 4 makes "Week X/8" the primary progress unit, so
--   the value must survive the export rather than be dropped.
-- =============================================================================

-- Core topic metadata table (one row per DeepTutor KB document)
CREATE TABLE IF NOT EXISTS topic_metadata (
    topic_id              TEXT PRIMARY KEY,                 -- e.g. 'maths-fractions-01'
    subject               TEXT NOT NULL,                    -- e.g. 'maths'
    topic                 TEXT NOT NULL,                    -- Human-readable title
    ai_literacy_context   TEXT,                             -- How this topic fits AI literacy
    modes_allowed         TEXT NOT NULL,                    -- JSON: ["contextual","direct","hybrid"]
    grade_level           TEXT NOT NULL,                    -- e.g. 'P4-P6'
    week                  INTEGER,                          -- Curriculum week 1..8 (NULL otherwise)
    prerequisites         TEXT,                             -- JSON: ["topic_id", ...]
    linked_projects       TEXT,                             -- JSON: ["project_id", ...]

    -- Dreamer 4D: Teaching mainline (PRIMARY AXIS)
    dreamer_phase         TEXT NOT NULL,                    -- JSON: ["Dream"|"Discover"|"Design"|"Deliver", ...]

    -- IB ATL: Cross-reference ONLY (internal; school alignment conversation)
    ib_atl_skills         TEXT,                             -- JSON: ["thinking-critical","research-info-lit",...]

    ethical_ai_tags       TEXT,                             -- JSON: ["fairness","bias","privacy",...]

    -- Source tracking
    kb_name               TEXT NOT NULL,                    -- Which KB this belongs to
    document_path         TEXT NOT NULL,                    -- Relative path within KB
    document_hash         TEXT NOT NULL,                    -- SHA256 for change detection

    -- Timestamps
    exported_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_modified         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index: Fast lookup by KB name (Hermes filtering by KB membership)
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

-- View: Topics grouped by Dreamer 4D phase (for Curriculum Navigator)
-- dreamer_phase is a JSON array, so the view expands it with json_each();
-- a legacy single-string value is coerced into a one-element array so old
-- rows stay visible.
CREATE VIEW IF NOT EXISTS v_phase_curriculum AS
SELECT
    j.value AS dreamer_phase,
    t.grade_level AS grade_level,
    t.subject AS subject,
    COUNT(*) AS topic_count,
    GROUP_CONCAT(DISTINCT t.kb_name) AS kb_list
FROM topic_metadata t,
     json_each(
        CASE
          WHEN json_valid(t.dreamer_phase)
           AND json_type(t.dreamer_phase) = 'array' THEN t.dreamer_phase
          ELSE json_array(t.dreamer_phase)
        END
     ) AS j
WHERE j.value IS NOT NULL
GROUP BY j.value, t.grade_level, t.subject
ORDER BY
    CASE j.value
        WHEN 'Dream'    THEN 1
        WHEN 'Discover' THEN 2
        WHEN 'Design'   THEN 3
        WHEN 'Deliver'  THEN 4
    END,
    t.grade_level;

-- View: Prerequisite chain for Curriculum Navigator
-- dreamer_phase columns are raw JSON arrays (informational only).
CREATE VIEW IF NOT EXISTS v_prerequisite_chain AS
SELECT
    t1.topic_id AS topic,
    t1.topic AS topic_name,
    t1.dreamer_phase,
    t2.topic_id AS prerequisite,
    t2.topic AS prerequisite_name,
    t2.dreamer_phase AS prerequisite_phase
FROM topic_metadata t1
JOIN json_each(COALESCE(NULLIF(t1.prerequisites, ''), '[]')) j
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
