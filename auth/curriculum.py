"""Bridge-2 — class ↔ curriculum mounting (DAO + "Week X/8" state machine).

Boss rulings locked 2026-09-11:
  #2 a class follows exactly ONE 8-week curriculum at a time, advancing
     linearly — week N+1 opens only when week N is completed. The rule lives
     in the data (status machine + partial unique index), not in the frontend.
  #3 a teacher may only mount a ready-made curriculum (8 authored weeks in
     ``topic_metadata``, the Bridge-1 source of truth) — never hand-pick a
     topic list.
  #4 "Week X/8" is the primary progress unit, so this module moves ``week_no``;
     mastery % stays a secondary lens elsewhere.

Layering follows auth/classes.py: business rules here, HTTP mapping (status
codes, role guards, audit rows) in auth/api.py. All SQL is parameterized.
"""

from __future__ import annotations

import datetime
import sqlite3
from typing import Any, Optional

from . import db as auth_db

CURRICULUM_WEEKS = 8
ALL_WEEKS: tuple[int, ...] = tuple(range(1, CURRICULUM_WEEKS + 1))

STATUS_LOCKED = "locked"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUSES: tuple[str, ...] = (STATUS_LOCKED, STATUS_ACTIVE, STATUS_COMPLETED)

# Error codes returned by the DAO; auth/api.py maps them to HTTP statuses.
ERR_NOT_FOUND = "not_found"              # no such curriculum  -> 404
ERR_INCOMPLETE = "incomplete"            # not a full 1..8 set -> 409
ERR_ALREADY_MOUNTED = "already_mounted"  # class already has one -> 409
ERR_NOT_MOUNTED = "not_mounted"          # advance before mount -> 409
ERR_NOT_LINEAR = "not_linear"            # gap / two open weeks -> 409
ERR_COURSE_COMPLETED = "course_completed"  # week 8 already done -> 409


class _AdvanceRace(Exception):
    """A concurrent writer moved the state machine between our read and write."""


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


_MIGRATED = False


def _prepare() -> None:
    """Make sure the Bridge-2 table / column exist before we touch them.

    ``ensure_schema()`` carries ``class_curriculum`` for both fresh and
    existing DBs; the ALTER helper covers the ``classes.curriculum_id`` column
    on DBs created before Bridge-2. Runs at most once per process.
    """
    global _MIGRATED
    auth_db.ensure_schema()
    if not _MIGRATED:
        auth_db.apply_class_curriculum_migration()
        _MIGRATED = True


# ---------------------------------------------------------------------------
# Curriculum catalog (read path — topic_metadata is the single source)
# ---------------------------------------------------------------------------

def _week_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "week_no": int(row["week"]),
        "topic_id": row["topic_id"],
        "topic": row["topic"] or "",
        "subject": row["subject"] or "",
        "grade_level": row["grade_level"] or "",
    }


def get_curriculum(curriculum_id: str) -> Optional[dict[str, Any]]:
    """Return one curriculum as ``{curriculum_id, title, week_count, ready,
    weeks[]}``, or ``None`` when ``topic_metadata`` has no week rows for it.

    ``ready`` is True only when the weeks are exactly 1..8 (no gap, no dupe) —
    the Bridge-2 precondition for mounting.
    """
    if not curriculum_id:
        return None
    conn = auth_db.connect()
    try:
        try:
            rows = conn.execute(
                "SELECT topic_id, subject, topic, grade_level, week "
                "FROM topic_metadata "
                "WHERE kb_name = ? AND week IS NOT NULL "
                "ORDER BY week ASC",
                (curriculum_id,),
            ).fetchall()
        except sqlite3.OperationalError:  # topic_metadata not built yet
            return None
    finally:
        conn.close()

    if not rows:
        return None

    weeks = [_week_entry(row) for row in rows]
    week_nos = [week["week_no"] for week in weeks]
    return {
        "curriculum_id": curriculum_id,
        "title": weeks[0]["subject"] or curriculum_id,
        "week_count": len(weeks),
        "ready": week_nos == list(ALL_WEEKS),
        "weeks": weeks,
    }


def list_catalog() -> list[dict[str, Any]]:
    """Ready-made curricula a teacher may pick, grouped out of topic_metadata.

    Only ``ready`` (complete 1..8) curricula are listed: ruling #3 means the
    UI never offers a half-authored course for mounting.
    """
    conn = auth_db.connect()
    try:
        try:
            rows = conn.execute(
                "SELECT DISTINCT kb_name FROM topic_metadata "
                "WHERE kb_name IS NOT NULL AND kb_name != '' "
                "AND week IS NOT NULL ORDER BY kb_name ASC"
            ).fetchall()
        except sqlite3.OperationalError:  # topic_metadata not built yet
            return []
    finally:
        conn.close()

    catalog: list[dict[str, Any]] = []
    for row in rows:
        curriculum = get_curriculum(str(row["kb_name"]))
        if curriculum is not None and curriculum["ready"]:
            catalog.append(curriculum)
    return catalog


# ---------------------------------------------------------------------------
# Class mount / advance (write path — the linear state machine)
# ---------------------------------------------------------------------------

def list_class_curriculum(class_id: str) -> list[dict[str, Any]]:
    """The class's 8 mounted weeks, ordered by ``week_no`` (empty if unmounted)."""
    _prepare()
    conn = auth_db.connect()
    try:
        rows = conn.execute(
            "SELECT topic_id, week_no, status, activated_at "
            "FROM class_curriculum WHERE class_id = ? ORDER BY week_no ASC",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "topic_id": row["topic_id"],
            "week_no": int(row["week_no"]),
            "status": row["status"],
            "activated_at": row["activated_at"],
        }
        for row in rows
    ]


def mount_curriculum(
    *, class_id: str, curriculum_id: str
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Mount a whole 8-week curriculum onto a class.

    Server expands the 8 rows itself (week 1 ``active``, weeks 2..8 ``locked``)
    — the caller only ever names a curriculum (ruling #3). Returns
    ``(payload, None)`` on success, ``(None, error_code)`` otherwise.
    """
    _prepare()
    curriculum = get_curriculum(curriculum_id)
    if curriculum is None:
        return None, ERR_NOT_FOUND
    if not curriculum["ready"]:
        return None, ERR_INCOMPLETE

    conn = auth_db.connect()
    try:
        cls = conn.execute(
            "SELECT id, curriculum_id FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
        if cls is None:
            return None, ERR_NOT_FOUND

        mounted = conn.execute(
            "SELECT COUNT(*) AS n FROM class_curriculum WHERE class_id = ?",
            (class_id,),
        ).fetchone()["n"]
        if mounted or cls["curriculum_id"]:
            return None, ERR_ALREADY_MOUNTED

        now = _now_iso()
        for week in curriculum["weeks"]:
            first = week["week_no"] == 1
            conn.execute(
                "INSERT INTO class_curriculum "
                "(class_id, topic_id, week_no, status, activated_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    class_id,
                    week["topic_id"],
                    week["week_no"],
                    STATUS_ACTIVE if first else STATUS_LOCKED,
                    now if first else None,
                    now,
                ),
            )
        conn.execute(
            "UPDATE classes SET curriculum_id = ? WHERE id = ?",
            (curriculum_id, class_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return None, ERR_ALREADY_MOUNTED
    finally:
        conn.close()

    return {
        "class_id": class_id,
        "curriculum_id": curriculum_id,
        "title": curriculum["title"],
        "week_count": curriculum["week_count"],
        "weeks": list_class_curriculum(class_id),
    }, None


def _resolve_active_week(
    rows: list[sqlite3.Row],
) -> tuple[Optional[int], Optional[str]]:
    """Pure validator: which week is open, and is the row set linear?

    Returns ``(current_week, None)`` when the state machine is healthy, or
    ``(None, error_code)`` when it is not. Kept side-effect free so the
    transaction below can bail out on a single ``rollback()``.
    """
    if not rows:
        return None, ERR_NOT_MOUNTED

    statuses = {int(row["week_no"]): str(row["status"]) for row in rows}
    if set(statuses) != set(ALL_WEEKS):
        return None, ERR_INCOMPLETE

    open_weeks = [w for w, s in statuses.items() if s == STATUS_ACTIVE]
    if not open_weeks:
        return None, ERR_COURSE_COMPLETED
    if len(open_weeks) > 1:
        return None, ERR_NOT_LINEAR

    current = open_weeks[0]
    for w in range(1, current):
        if statuses[w] != STATUS_COMPLETED:
            return None, ERR_NOT_LINEAR
    for w in range(current + 1, CURRICULUM_WEEKS + 1):
        if statuses[w] != STATUS_LOCKED:
            return None, ERR_NOT_LINEAR
    return current, None


def _apply_advance(
    conn: sqlite3.Connection, class_id: str, *, expected_week: int, now: str
) -> int:
    """Close ``expected_week`` and open ``expected_week + 1`` inside the caller's
    transaction.

    Both UPDATEs carry the status we read as a WHERE guard, so a concurrent
    advance cannot be applied twice: the loser matches 0 rows, raises
    ``_AdvanceRace``, and the caller rolls the whole transaction back.
    Returns the newly opened week number.
    """
    cur = conn.execute(
        "UPDATE class_curriculum SET status = ? "
        "WHERE class_id = ? AND week_no = ? AND status = ?",
        (STATUS_COMPLETED, class_id, expected_week, STATUS_ACTIVE),
    )
    if cur.rowcount != 1:
        raise _AdvanceRace(f"week {expected_week} was not active")

    next_week = expected_week + 1
    if next_week <= CURRICULUM_WEEKS:
        cur = conn.execute(
            "UPDATE class_curriculum SET status = ?, activated_at = ? "
            "WHERE class_id = ? AND week_no = ? AND status = ?",
            (STATUS_ACTIVE, now, class_id, next_week, STATUS_LOCKED),
        )
        if cur.rowcount != 1:
            raise _AdvanceRace(f"week {next_week} was not locked")
    return next_week


def advance_week(
    class_id: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Close the active week and open the next one ("下一週").

    Refuses anything that would break linear progression (ruling #2):
    an unmounted class, a gap (week N locked while a later week is open), or a
    second advance after week 8 has been completed.

    The read check and the two writes run in ONE transaction (``BEGIN
    IMMEDIATE``), and both UPDATEs are guarded by the status we just read — so
    a concurrent advance either loses the lock or fails the rowcount guard and
    changes nothing (hygiene: no half-applied advance).
    """
    _prepare()
    conn = auth_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT week_no, status FROM class_curriculum "
            "WHERE class_id = ? ORDER BY week_no ASC",
            (class_id,),
        ).fetchall()

        current, error = _resolve_active_week(rows)
        if error is not None:
            conn.rollback()
            return None, error

        next_week = _apply_advance(
            conn, class_id, expected_week=current, now=_now_iso()
        )
        conn.commit()
    except _AdvanceRace:
        conn.rollback()
        return None, ERR_NOT_LINEAR
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "class_id": class_id,
        "completed_week": current,
        "active_week": next_week if next_week <= CURRICULUM_WEEKS else None,
        "course_completed": next_week > CURRICULUM_WEEKS,
        "weeks": list_class_curriculum(class_id),
    }, None
