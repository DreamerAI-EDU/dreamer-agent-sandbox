"""W3-B shared read-only Parent Report data layer (single source).

The W3-B dashboard surfaces are two lenses over ONE data layer:
  * Parent Dashboard  -> GET /api/parent/report
  * Teacher Lens      -> GET /api/teacher/classes/{id}/progress
                         GET /api/teacher/student/{id}/progress

Parent Report semantics are delegated to the canonical implementation in
``agents.parent_report_agent`` (frozen schema: docs/phase6-schemas.md) so the
two lenses can never drift (R5.8 same-source parity). Teacher-only rollups
(class average, latest snapshot per student, consent indicator) are computed
here against the same frozen tables with the same label semantics.

Hard boundaries:
  * read-only — this module never writes, never migrates schema;
  * never reads chat_history (W3-B-O1);
  * teacher console surfaces return full student ids (precedent:
    ``auth.classes.list_class_pending_students``), never the parent-side mask;
  * parent-facing responses mask student ids (``_mask_student_id``).

``agents`` imports are deliberately deferred to function scope: importing
this module (and therefore the whole auth package) must not pull the heavy
agent dependency graph until a report endpoint is actually called.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from . import db as auth_db

# Parent Report periods accepted by the agent (docs/phase6-schemas.md).
PARENT_PERIODS = ("weekly", "cycle", "journey")

_MEDIA_CONSENT = "media_consent"


def _subject_of(topic_id: str) -> str:
    """Subject slug of a topic id (``maths-multiplication-02`` -> ``maths``)."""
    return (topic_id or "").split("-")[0]


def _soften_label(internal: str, age_band: str, lang_code: str, audience: str) -> str:
    """label_soften passthrough (lazy agents import; unknown label -> raw)."""
    if not internal:
        return ""
    from agents.kid_safe.label_soften import soften_label  # lazy (see module doc)

    return soften_label(internal, age_band, lang_code, audience=audience)


# ---------------------------------------------------------------------------
# Parent Report (canonical agent path)
# ---------------------------------------------------------------------------


def parent_report_for_student(
    student: Any,
    period: str = "cycle",
    *,
    include_safety: bool = True,
    mask_student_id: bool = False,
) -> dict[str, Any]:
    """Full Parent Report envelope for one student (agent sync core).

    Delegates to ``agents.parent_report_agent.ParentReportAgent`` so the
    frozen phase6 schema and label semantics stay in a single implementation.
    ``mask_student_id=True`` replaces the full student id inside the report
    with the fixed-length prefix for parent-facing responses.
    """
    from agents.parent_report_agent import ParentReportAgent  # lazy (module doc)

    agent = ParentReportAgent(db_path=auth_db._db_path())
    report = agent.generate_report(
        student_id=student["id"],
        period=period,
        lang_code=student["lang_code"],
        age_band=student["age_band"],
        include_safety=include_safety,
    )
    # The canonical agent envelope carries ``topics[].last_label_internal``
    # (a P-series internal label). Every W3-B surface - parent AND teacher -
    # must never receive it, so it is stripped here once for both lenses.
    import copy

    report = copy.deepcopy(report)
    _strip_internal(report)
    if mask_student_id:
        inner = report.get("report") or {}
        if isinstance(inner.get("student_id"), str):
            inner["student_id"] = inner["student_id"][:8]
    return report


def _strip_internal(node: Any) -> None:
    """Recursively delete internal-label keys from a report payload."""
    if isinstance(node, dict):
        for key in list(node.keys()):
            if key == "last_label_internal":
                node.pop(key, None)
            else:
                _strip_internal(node[key])
    elif isinstance(node, list):
        for item in node:
            _strip_internal(item)


# ---------------------------------------------------------------------------
# Consent indicator (W3-B-O2: agreed = green, withdrawn = red, else unsigned)
# ---------------------------------------------------------------------------


def media_consent_status_for_student(parent_id: str, student_id: str) -> str:
    """Latest media_consent action covering the student -> status string.

    Scope matches sign/withdraw: student-bound rows plus account-level NULL
    rows both cover the student; the latest row decides (same rule as
    ``auth.consent.student_media_consent_withdrawn``).
    """
    conn = auth_db.connect()
    try:
        row = conn.execute(
            """SELECT action FROM consent_log
               WHERE user_id = ? AND doc_type = ?
                 AND (student_id = ? OR student_id IS NULL)
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (parent_id, _MEDIA_CONSENT, student_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return "unsigned"
    return row["action"]  # "agreed" | "withdrawn"


# ---------------------------------------------------------------------------
# Teacher Lens rollups (same frozen tables, teacher-owned class scope)
# ---------------------------------------------------------------------------


def teacher_class_progress(
    teacher_id: str, class_id: str
) -> Optional[dict[str, Any]]:
    """Confirmed students + rollups for a teacher-owned class.

    Returns None when the class does not exist or is not owned by the teacher
    (unified 403, same shape as ``list_class_pending_students``). Each student
    row carries the latest snapshot mastery + the latest assessment kid label;
    ``stats.average_mastery_pct`` is the mean of each confirmed student's
    latest-snapshot mastery (students without any snapshot are skipped; when
    none have snapshots the value is null).
    """
    conn = auth_db.connect()
    try:
        cls = conn.execute(
            "SELECT * FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
        if cls is None or cls["teacher_id"] != teacher_id:
            return None

        pending_count = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM class_students "
                "WHERE class_id = ? AND status = 'pending'",
                (class_id,),
            ).fetchone()["n"]
            or 0
        )
        rows = conn.execute(
            """SELECT s.id, s.first_name, s.age_band, s.lang_code, s.parent_id
               FROM class_students cs
               JOIN students s ON s.id = cs.student_id
               WHERE cs.class_id = ? AND cs.status = 'confirmed'
               ORDER BY s.created_at""",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()

    students = [
        _teacher_student_row(row) for row in rows
    ]
    mastery_values = [s["mastery_pct"] for s in students if s["mastery_pct"] is not None]
    return {
        "class": {
            "id": cls["id"],
            "name": cls["name"],
            "class_type": cls["class_type"],
            "grade_band": cls["grade_band"],
            "is_one_on_one": bool(cls["is_one_on_one"]),
        },
        "stats": {
            "student_count": len(students),
            "pending_count": pending_count,
            "average_mastery_pct": (
                _round1(sum(mastery_values) / len(mastery_values))
                if mastery_values
                else None
            ),
        },
        "students": students,
    }


def _round1(value: float) -> float:
    """Round to one decimal (same convention as the parent report agent)."""
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _teacher_student_row(student: Any) -> dict[str, Any]:
    """Rollup row for one confirmed class student (summary only)."""
    sid = student["id"]
    age_band = student["age_band"]
    lang_code = student["lang_code"]
    parent_id = student["parent_id"]

    conn = auth_db.connect()
    try:
        snap = conn.execute(
            """SELECT topic_id, mastery_pct, attempt_count, last_label, streak,
                      updated_at
               FROM progress_snapshots
               WHERE student_id = ?
               ORDER BY updated_at DESC, rowid DESC LIMIT 1""",
            (sid,),
        ).fetchone()
        latest = conn.execute(
            """SELECT internal_label, created_at FROM assessment_logs
               WHERE student_id = ?
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (sid,),
        ).fetchone()
        a_max = conn.execute(
            "SELECT MAX(created_at) AS m FROM assessment_logs WHERE student_id = ?",
            (sid,),
        ).fetchone()["m"]
        s_max = conn.execute(
            "SELECT MAX(created_at) AS m FROM session_logs WHERE student_id = ?",
            (sid,),
        ).fetchone()["m"]
    finally:
        conn.close()

    last_activity = max(
        [ts for ts in (a_max, s_max) if ts], default=None
    )
    return {
        # Full student id: trusted teacher console surface (never rendered by
        # the UI; the parent side continues to use the 8-char mask).
        "student_id": sid,
        "display_name": student["first_name"],  # B24: first_name only
        "age_band": age_band,
        "lang_code": lang_code,
        "media_consent": (
            media_consent_status_for_student(parent_id, sid)
            if parent_id
            else "unsigned"
        ),
        "last_activity_at": last_activity,
        "last_label_kid": (
            _soften_label(
                latest["internal_label"], age_band, lang_code, audience="kid_facing"
            )
            if latest
            else ""
        ),
        "mastery_pct": snap["mastery_pct"] if snap else None,  # raw rolling value
        "updated_at": snap["updated_at"] if snap else None,
    }


# ---------------------------------------------------------------------------
# Teacher student detail (canonical report + sanitised assessment history)
# ---------------------------------------------------------------------------


def teacher_student_progress(
    teacher_id: str, student: Any, period: str = "cycle"
) -> Optional[dict[str, Any]]:
    """Teacher-view individual progress for a taught student.

    Returns None when the teacher does not teach this student. The body reuses
    the canonical Parent Report for the requested period plus the student's
    full assessment history in a sanitised form — internal labels, confidence,
    rubric ids and evidence text never leave the server (P-series red line).
    """
    from . import classes as classes_mod

    if not classes_mod.teacher_teaches_student(teacher_id, student["id"]):
        return None

    conn = auth_db.connect()
    try:
        logs = conn.execute(
            """SELECT topic_id, mode, internal_label, created_at
               FROM assessment_logs
               WHERE student_id = ?
               ORDER BY created_at DESC, rowid DESC""",
            (student["id"],),
        ).fetchall()
    finally:
        conn.close()

    history = [
        {
            "date": (row["created_at"] or "")[:10],
            "topic_id": row["topic_id"],
            "subject": _subject_of(row["topic_id"]),
            "mode": row["mode"],
            "label_parent": _soften_label(
                row["internal_label"],
                student["age_band"],
                student["lang_code"],
                audience="parent_facing",
            ),
        }
        for row in logs
    ]

    return {
        "student": {
            "student_id": student["id"],
            "display_name": student["first_name"],
            "age_band": student["age_band"],
            "lang_code": student["lang_code"],
            "media_consent": (
                media_consent_status_for_student(student["parent_id"], student["id"])
                if student["parent_id"]
                else "unsigned"
            ),
        },
        "report": parent_report_for_student(student, period, include_safety=True),
        "assessment_history": history,
    }
