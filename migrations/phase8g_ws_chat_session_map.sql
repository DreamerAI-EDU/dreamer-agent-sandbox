-- Phase 8g — WS chat session map (P4: student session continuity).
--
-- Boss work order 2026-09-15 (P4 spec §4.1 relay layer items 1-3):
-- the relay owns the ONLY valid engine session for a student. Client
-- payloads carrying a session_id are never trusted (blanket rewrite,
-- not validation); the mapping below is how the relay remembers which
-- engine session belongs to which student across WS connections, page
-- refreshes and API restarts.
--
-- Red-line 8 applicability ruling (boss, 2026-09-15): full student ids
-- are forbidden in append-only audit records, any log and any external
-- surface (chat frame / API response / error message). BUSINESS tables
-- keyed by student_id are an existing precedent (payments Bridge-3e,
-- students itself); this table follows that precedent. The FK keeps
-- integrity in the DB.
--
-- Business table, NOT append-only (unlike ws_chat_relay_audit): the row
-- is created when the engine assigns a fresh session and replaced when a
-- dead session is evicted and a new one is opened (INSERT ... ON CONFLICT
-- DO UPDATE — atomic upsert, created_at kept, updated_at bumped).
--
-- Canonical DDL lives here; it is mirrored in auth/db.py::_DDL so
-- ensure_schema() creates the table on any DB, old or fresh (additive, no
-- ALTER — the deploy window needs no extra step).

CREATE TABLE IF NOT EXISTS ws_chat_session_map (
    student_id     TEXT PRIMARY KEY,
    engine_session TEXT NOT NULL,            -- DeepTutor unified_xxx
    created_at     TEXT NOT NULL,            -- ISO-8601 UTC
    updated_at     TEXT NOT NULL,            -- last engine-session change
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE INDEX IF NOT EXISTS idx_ws_session_map_updated
    ON ws_chat_session_map(updated_at);
