-- Bridge-3e — payment mark-paid (boss work order 2026-09-13, decision ②).
--
-- Additive: ONE row per student. The table holds the CURRENT payment status
-- only; a status change is an UPDATE of that row — never a second row — so it
-- is a state store, not a ledger. History lives in the append-only audit
-- trail (`payment_marked` events carry actor + student pointer + timestamp,
-- and deliberately no amount).
--
-- `marked_by` / `marked_at` / `note` stay NULL until an admin marks the
-- student the first time. A student with no row is `pending` by definition,
-- so nothing in the invite / confirm flow has to know payments exist.
--
-- Canonical DDL: mirrored verbatim in auth/db.py (_DDL, the fresh-DB bootstrap
-- path) and therefore carried by ensure_schema() on any DB, old or fresh — a
-- brand-new table needs no ALTER, hence no runner step in a deploy window.

CREATE TABLE IF NOT EXISTS payments (
    student_id TEXT PRIMARY KEY REFERENCES students(id),
    status     TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'paid'
    marked_by  TEXT,                              -- admin users.id; NULL = never marked
    marked_at  TEXT,                              -- ISO timestamp of the last flip
    note       TEXT                               -- optional operator note
);

CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
