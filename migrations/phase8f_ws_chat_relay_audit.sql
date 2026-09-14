-- Phase 8f — WS chat relay audit (W3-C P3: relay resilience).
--
-- Boss work order 2026-09-14 (review condition 3): the relay must record all
-- three non-happy paths — a retry attempt (with which attempt number), a
-- non-retry mid-stream 429, and a watchdog kill — each carrying an
-- `upstream_error` code. Success-only logging is explicitly not enough, so the
-- table also keeps the plain turn_start / turn_end bookends for final_status.
--
-- Append-only by design: a relay audit row is evidence, never an editable
-- record. The two triggers below enforce that in the DB itself (UPDATE and
-- DELETE abort), so no code path — including a future housekeeping script —
-- can rewrite history. Retention / pruning scripts must skip this table.
--
-- Canonical DDL lives here; it is mirrored in auth/db.py::_DDL so
-- ensure_schema() creates the table on any DB, old or fresh (additive, no
-- ALTER — the deploy window needs no extra step).

CREATE TABLE IF NOT EXISTS ws_chat_relay_audit (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at    TEXT    NOT NULL,   -- ISO-8601 UTC
    event          TEXT    NOT NULL,   -- turn_start | turn_retry | midstream_error
                                       -- | watchdog_kill | turn_end
                                       -- | upstream_unavailable
    session_id     TEXT,               -- engine-assigned unified_xxx, when seen
    turn_id        TEXT,               -- upstream turn id, when seen
    student_mask   TEXT,               -- 8-char masked prefix ONLY (W2 PR#3:
                                       -- full student ids never leave the server,
                                       -- and never enter an append-only record)
    attempt        INTEGER,            -- 1-based retry attempt (turn_retry only)
    final_status   TEXT,               -- completed | failed | aborted (turn_end only)
    upstream_error TEXT,               -- normalized code; NULL on the happy path
    detail         TEXT                -- short operator note, no PII / no prompt text
);

CREATE INDEX IF NOT EXISTS idx_ws_relay_audit_session
    ON ws_chat_relay_audit(session_id);

CREATE INDEX IF NOT EXISTS idx_ws_relay_audit_event
    ON ws_chat_relay_audit(event);

CREATE TRIGGER IF NOT EXISTS ws_chat_relay_audit_no_update
BEFORE UPDATE ON ws_chat_relay_audit
BEGIN
    SELECT RAISE(ABORT, 'ws_chat_relay_audit is append-only (no UPDATE)');
END;

CREATE TRIGGER IF NOT EXISTS ws_chat_relay_audit_no_delete
BEFORE DELETE ON ws_chat_relay_audit
BEGIN
    SELECT RAISE(ABORT, 'ws_chat_relay_audit is append-only (no DELETE)');
END;
