-- Bridge-2 (2026-09-11) — class ↔ curriculum mounting.
--
-- Boss ruling #2/#3: a class follows exactly ONE 8-week curriculum, weeks run
-- linearly (week N+1 opens only when N is completed), and a teacher may only
-- mount a ready-made curriculum — never hand-pick topics.
--
-- Additive only (red line): one new table, one new nullable column on classes.
-- The linear state machine is enforced in the DB, not by the frontend:
--   * week_no CHECK 1..8;
--   * status CHECK locked/active/completed;
--   * idx_class_curriculum_one_active — at most ONE active week per class,
--     so even a manual UPDATE cannot leave two weeks open at once.
--
-- Apply to an existing DB (idempotent):
--   python -c "from auth.db import apply_class_curriculum_migration as m; m()"
-- Fresh DBs get everything from auth/db.py::ensure_schema() (the _DDL mirror,
-- same convention as phase8b_password_reset.sql / the W3-C class columns).

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_class_curriculum_one_active
    ON class_curriculum(class_id) WHERE status = 'active';

-- Which 8-week curriculum this class follows (NULL until mounted). Added last
-- on purpose: ALTER TABLE appends at the end, so fresh and migrated DBs keep
-- the same column order (tests/test_auth.py::test_migration_schema_pairing).
ALTER TABLE classes ADD COLUMN curriculum_id TEXT;
