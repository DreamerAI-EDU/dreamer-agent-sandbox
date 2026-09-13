"""Bridge-3e — payment state (admin mark-paid / mark-pending).

Boss work order 2026-09-13 (decision ②, 0.5–1 day). ONE row per student
(``payments.student_id`` is the PRIMARY KEY): the table stores the CURRENT
status only, and a flip is an UPDATE of that row — never an inserted second
row. History lives in the append-only audit trail (``payment_marked`` events
carry actor + student pointer + timestamp; never an amount).

Vocabulary
  * a student with NO row is ``pending`` by definition — the read path never
    invents a row, so nothing in the invite / confirm flow has to know that
    payments exist at all (additive, zero coupling);
  * the first mark writes the row, every later mark updates it;
  * re-marking the status a student already has is a normal 200 (idempotent),
    never a 500 — the one-row invariant holds either way.

Storage only: the role gate (401 anonymous / 403 non-admin / 404 unknown) and
the audit write live in ``auth/api.py``, exactly like every other Bridge
surface. This module never touches roles.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from . import db

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
VALID_STATUSES = (STATUS_PENDING, STATUS_PAID)


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_payment_status(student_id: str) -> str:
    """The student's current status; no row means ``pending`` (never an error)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT status FROM payments WHERE student_id = ?", (student_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return STATUS_PENDING
    return str(row["status"])


def set_payment_status(
    *,
    student_id: str,
    status: str,
    marked_by: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotently write the CURRENT status for one student.

    ``INSERT .. ON CONFLICT(student_id) DO UPDATE`` keeps the one-row-per-
    student invariant: marking an already-``paid`` student again updates the
    same row (fresh ``marked_by`` / ``marked_at``) and returns normally.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown payment status: {status!r}")
    db.ensure_schema()
    now = _now_iso()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO payments (student_id, status, marked_by, marked_at, note) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(student_id) DO UPDATE SET "
            "status = excluded.status, "
            "marked_by = excluded.marked_by, "
            "marked_at = excluded.marked_at, "
            "note = excluded.note",
            (student_id, status, marked_by, now, note),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM payments WHERE student_id = ?", (student_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else {}


def list_payment_rows(*, status: Optional[str] = None) -> list[dict[str, Any]]:
    """Every student with their CURRENT payment status (``pending`` by default).

    ``LEFT JOIN`` so a never-marked student still shows up as ``pending`` —
    the admin reconciliation list ("邊個未付") must not hide untouched rows.
    ``status`` filters AFTER the coalesce, so ``status=pending`` returns both
    explicitly-pending and never-marked students.
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.id AS student_id, s.first_name, "
            "COALESCE(p.status, 'pending') AS status, "
            "p.marked_by, p.marked_at, p.note "
            "FROM students s LEFT JOIN payments p ON p.student_id = s.id "
            "ORDER BY s.created_at, s.id"
        ).fetchall()
    finally:
        conn.close()
    items = [dict(row) for row in rows]
    if status is not None:
        items = [item for item in items if item["status"] == status]
    return items
