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


# ---------------------------------------------------------------------------
# Bridge-3a — kid-facing "Week X / 8" badge (read path, writes nothing)
# ---------------------------------------------------------------------------

# Badge states. "none" is the neutral state: the kid surface answers 200 with
# the badge hidden — it is never an error the child can trip over.
STATE_NONE = "none"
STATE_ACTIVE = "active"
STATE_COMPLETED = "completed"

BADGE_STATES: tuple[str, ...] = (STATE_NONE, STATE_ACTIVE, STATE_COMPLETED)


def _student_confirmed_classes(student_id: str) -> list[str]:
    """Class ids the student is a CONFIRMED member of, oldest first.

    Pending invites do not count: the parent has not accepted yet, so the kid
    surface must stay neutral rather than guess at a class the child is not in.
    """
    _prepare()
    conn = auth_db.connect()
    try:
        rows = conn.execute(
            "SELECT class_id FROM class_students "
            "WHERE student_id = ? AND status = 'confirmed' "
            "ORDER BY created_at ASC, class_id ASC",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["class_id"]) for row in rows]


def _resolve_week_state(weeks: list[dict[str, Any]]) -> tuple[Optional[int], str]:
    """Pure validator: (week_no, state) as the CHILD should see it.

    Healthy states are the Bridge-2 ones — exactly one ``active`` week with
    everything before it ``completed`` and everything after it ``locked``, or
    the full 1..8 set ``completed`` (``course_completed``). Anything else
    (partial mount, gap, two open weeks) degrades to ``(None, "none")``: the
    badge hides instead of showing a week number the data does not support.
    """
    statuses = {week["week_no"]: week["status"] for week in weeks}
    if set(statuses) != set(ALL_WEEKS):
        return None, STATE_NONE

    open_weeks = [w for w, s in statuses.items() if s == STATUS_ACTIVE]
    if len(open_weeks) > 1:
        return None, STATE_NONE

    current = open_weeks[0] if open_weeks else CURRICULUM_WEEKS + 1
    for w in range(1, current):
        if statuses[w] != STATUS_COMPLETED:
            return None, STATE_NONE

    if not open_weeks:
        # No open week: either the course is finished, or week 1 never opened.
        if all(statuses[w] == STATUS_COMPLETED for w in ALL_WEEKS):
            return CURRICULUM_WEEKS, STATE_COMPLETED
        return None, STATE_NONE

    for w in range(current + 1, CURRICULUM_WEEKS + 1):
        if statuses[w] != STATUS_LOCKED:
            return None, STATE_NONE
    return current, STATE_ACTIVE


def _kid_unit_title(topic_id: str) -> str:
    """Kid-facing unit title for one week, authored server-side (ruling #1).

    The string comes from ``topic_metadata.topic`` (Bridge-1 source of truth,
    authored for the child), falling back to the authored subject and then to
    "" — the internal ``topic_id`` (e.g. "curriculum-wk01") never leaves the
    server and the frontend never translates one.
    """
    if not topic_id:
        return ""
    conn = auth_db.connect()
    try:
        try:
            row = conn.execute(
                "SELECT topic, subject FROM topic_metadata "
                "WHERE topic_id = ? LIMIT 1",
                (topic_id,),
            ).fetchone()
        except sqlite3.OperationalError:  # topic_metadata not built yet
            return ""
    finally:
        conn.close()
    if row is None:
        return ""
    return str(row["topic"] or row["subject"] or "").strip()


def student_week_badge(student_id: str) -> dict[str, Any]:
    """The kid-facing reading of the student's class curriculum (Bridge-3a).

    Shape: ``{state, week_index, total_weeks, unit_title}``.

      * ``state="none"``       no confirmed class, no mounted course, or a
                               non-linear row set -> badge stays hidden.
      * ``state="active"``     ``week_index`` = the ``week_no`` of the class's
                               ONE active week — the backend states it, the
                               frontend never derives it (ruling #3).
      * ``state="completed"``  all 8 weeks done: ``week_index`` = 8 so the
                               badge reads "8/8 · 完成".

    The payload carries no student id and no internal ``topic_id``.
    """
    for class_id in _student_confirmed_classes(student_id):
        weeks = list_class_curriculum(class_id)
        if not weeks:
            continue  # class without a mounted course -> neutral for this one
        week_no, state = _resolve_week_state(weeks)
        if state == STATE_NONE or week_no is None:
            continue
        topic_id = next(
            (w["topic_id"] for w in weeks if w["week_no"] == week_no), None
        )
        return {
            "state": state,
            "week_index": week_no,
            "total_weeks": CURRICULUM_WEEKS,
            "unit_title": _kid_unit_title(topic_id or "") if topic_id else "",
        }
    return {
        "state": STATE_NONE,
        "week_index": None,
        "total_weeks": CURRICULUM_WEEKS,
        "unit_title": "",
    }


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


# ---------------------------------------------------------------------------
# Bridge-3b — parent-facing 8-week course map (read path, writes nothing)
# ---------------------------------------------------------------------------

def _topic_titles(topic_ids: list[str]) -> dict[str, str]:
    """Authored family-facing week titles, keyed by the bridge ``topic_id``.

    Same source and same ruling as ``_kid_unit_title`` (#1): the string is
    authored in ``topic_metadata.topic`` (fallback: the authored subject), so
    the parent grid renders it verbatim and the internal ``topic_id`` never
    crosses the wire. One query for the whole week set instead of eight.
    """
    ids = [str(t) for t in dict.fromkeys(topic_ids) if t]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    conn = auth_db.connect()
    try:
        try:
            rows = conn.execute(
                "SELECT topic_id, topic, subject FROM topic_metadata "
                f"WHERE topic_id IN ({placeholders})",
                ids,
            ).fetchall()
        except sqlite3.OperationalError:  # topic_metadata not built yet
            return {}
    finally:
        conn.close()
    return {
        str(row["topic_id"]): str(row["topic"] or row["subject"] or "").strip()
        for row in rows
    }


def _topic_mastery(student_id: str, topic_ids: list[str]) -> dict[str, float]:
    """Rolling mastery per week topic, straight out of ``progress_snapshots``.

    ABSENT key = the week has no data yet, and the caller reports ``null`` —
    the map never invents a 0%. A STORED ``0.0`` is real data (attempts scored
    zero) and stays ``0.0``. Values keep the backend's established raw 0..1
    scale — the same "raw rolling value" contract the portfolio surface uses
    (``reports.py``), with the ×100 left to the frontend.
    """
    ids = [str(t) for t in dict.fromkeys(topic_ids) if t]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    conn = auth_db.connect()
    try:
        try:
            rows = conn.execute(
                "SELECT topic_id, mastery_pct FROM progress_snapshots "
                f"WHERE student_id = ? AND topic_id IN ({placeholders})",
                [student_id, *ids],
            ).fetchall()
        except sqlite3.OperationalError:  # assessment DB not built yet
            return {}
    finally:
        conn.close()
    return {str(row["topic_id"]): float(row["mastery_pct"]) for row in rows}


def _course_title(class_id: str) -> str:
    """Authored course title for a class ("" when nothing is authored).

    Comes from the mounted curriculum's own ``topic_metadata`` subject, i.e.
    the same authored string ``get_curriculum`` calls the title — never the
    raw ``kb_name`` internal id.
    """
    conn = auth_db.connect()
    try:
        row = conn.execute(
            "SELECT curriculum_id FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return ""
    curriculum = get_curriculum(str(row["curriculum_id"] or ""))
    return str(curriculum["title"]) if curriculum is not None else ""


def parent_curriculum_map(student_id: str) -> dict[str, Any]:
    """The Parent Console's 8-week course map for one child (Bridge-3b).

    Shape: ``{course_title, current_week, total_weeks, state, weeks[]}``, each
    week being ``{week_no, title, status, mastery_pct}``.

      * ``state="none"``       no confirmed class, no mounted course, or a
                               non-linear row set -> neutral: ``weeks: []`` and
                               ``current_week: null`` (never a 500).
      * ``state="active"``     ``current_week`` = the ``week_no`` of the class's
                               ONE active week (same resolver as the kid badge,
                               so the two surfaces can never disagree).
      * ``state="completed"``  all 8 weeks done: ``current_week`` = 8, week 8
                               ``completed``.

    ``title`` is authored server-side (#1), ``mastery_pct`` is the raw 0..1
    rolling snapshot or ``null`` when that week has no data yet. The payload
    carries no ``topic_id`` and no student id.
    """
    for class_id in _student_confirmed_classes(student_id):
        weeks = list_class_curriculum(class_id)
        if not weeks:
            continue  # class without a mounted course -> neutral for this one
        current_week, state = _resolve_week_state(weeks)
        if state == STATE_NONE or current_week is None:
            continue
        topic_ids = [str(week["topic_id"] or "") for week in weeks]
        titles = _topic_titles(topic_ids)
        mastery = _topic_mastery(student_id, topic_ids)
        return {
            "course_title": _course_title(class_id),
            "current_week": current_week,
            "total_weeks": CURRICULUM_WEEKS,
            "state": state,
            "weeks": [
                {
                    "week_no": week["week_no"],
                    "title": titles.get(str(week["topic_id"] or ""), ""),
                    "status": week["status"],
                    "mastery_pct": mastery.get(str(week["topic_id"] or "")),
                }
                for week in weeks
            ],
        }
    return {
        "course_title": "",
        "current_week": None,
        "total_weeks": CURRICULUM_WEEKS,
        "state": STATE_NONE,
        "weeks": [],
    }
