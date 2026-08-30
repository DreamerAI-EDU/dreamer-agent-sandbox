"""W2 PR#4 — safety_events read + review DAO for the teacher review API.

safety_events (phase2.5) is written by the agents/kid_safe pipeline. This
module only ever READS rows and runs the single sanctioned UPDATE path
(review marking). The list query deliberately never selects `raw_input`
(pointer-only discipline, B33a) — the column exists only in the detail path
which is gated by step-up auth in auth/api.py.

Table creation here is idempotent and mirrors migrations/phase2.5_safety_events.sql
so a fresh auth-only DB can bootstrap the review API without a migration
runner (same convention as auth/db.py).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from . import db as auth_db

# Mirrors migrations/phase2.5_safety_events.sql (must stay in sync).
_DDL = """\
CREATE TABLE IF NOT EXISTS safety_events (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    matched_rule TEXT,
    age_band TEXT,
    lang_code TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_safety_unreviewed
    ON safety_events(reviewed, severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_safety_student
    ON safety_events(student_id, created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = auth_db.connect()
    conn.executescript(_DDL)
    conn.commit()
    return conn


def list_events_for_teacher(
    teacher_id: str,
    *,
    admin: bool = False,
    unreviewed_only: bool = False,
) -> list[dict[str, Any]]:
    """Pointer-only list for the teacher safety review inbox.

    Only events for the teacher's own class students are returned (JOIN
    class_students + classes, same shape as classes.teacher_teaches_student).
    `admin` bypasses the class ownership filter but still goes through the
    same pointer-only projection.

    The SELECT explicitly lists pointer columns — `raw_input` is never
    selected here, so it cannot leak even if a future caller copies the
    whole dict into a response.
    """
    conn = _connect()
    try:
        where = ""
        params: list[Any] = []
        if not admin:
            where = (
                "JOIN class_students cs ON cs.student_id = e.student_id "
                "JOIN classes c ON c.id = cs.class_id "
                "WHERE c.teacher_id = ?"
            )
            params.append(teacher_id)
        if unreviewed_only:
            where += " AND e.reviewed = 0" if where else "WHERE e.reviewed = 0"
        sql = (
            "SELECT e.id AS event_id, e.created_at, e.event_type, e.severity,"
            "       e.reviewed, s.first_name AS student_first_name "
            "FROM safety_events e "
            "JOIN students s ON s.id = e.student_id "
            f"{where} "
            "ORDER BY e.created_at DESC, e.id DESC"
        )
        rows = conn.execute(sql, params).fetchall()
        events = [dict(row) for row in rows]
        for event in events:
            event["reviewed"] = bool(event["reviewed"])
        return events
    finally:
        conn.close()


def get_event_with_student(event_id: str) -> Optional[dict[str, Any]]:
    """Full event row (including raw_input) joined with the student first
    name. Returns None when the event id does not exist — callers map both
    unknown and foreign ids to the same 403 so existence never leaks."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT e.*, s.first_name AS student_first_name
               FROM safety_events e
               JOIN students s ON s.id = e.student_id
               WHERE e.id = ?""",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        event = dict(row)
        event["reviewed"] = bool(event["reviewed"])
        return event
    finally:
        conn.close()


def event_owned_by_teacher(event_id: str, teacher_id: str) -> bool:
    """True when the event's student appears in any class owned by the
    teacher (same JOIN shape as classes.teacher_teaches_student)."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT 1 FROM safety_events e
               JOIN class_students cs ON cs.student_id = e.student_id
               JOIN classes c ON c.id = cs.class_id
               WHERE e.id = ? AND c.teacher_id = ?
               LIMIT 1""",
            (event_id, teacher_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def review_event(
    event_id: str, *, reviewed_by: str, reviewed_at: str
) -> bool:
    """Mark the event reviewed (the single sanctioned UPDATE on
    safety_events). Returns False when the event id does not exist — the
    caller returns the unified 403/400 without revealing existence."""
    conn = _connect()
    try:
        cur = conn.execute(
            """UPDATE safety_events
               SET reviewed = 1, reviewed_by = ?, reviewed_at = ?
               WHERE id = ?""",
            (reviewed_by, reviewed_at, event_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
