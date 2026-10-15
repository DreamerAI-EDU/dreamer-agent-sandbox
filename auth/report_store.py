"""PR-3 report persistence + state machine (design book v1.1 §3.2 / §4.1).

The report domain used to be generate-on-the-fly (T-0 盘点 R5): every
``GET /api/parent/report`` re-ran the agent and nothing was ever stored. This
module is the persistence half of the design book's PR-3 slice — reports are
now drafted into ``parent_reports`` (phase8), reviewed by the owning teacher,
and only then become parent-visible.

State machine (借 plan_proposals 状态族; §4.1)::

    pending_review ──approve──▶ approved ──(newer version approved)──▶ superseded
          │
          └──reject──▶ rejected          (releases the one-pending gate)

* 批准即发布: ``approved_at`` == ``published_at``; the parent console only
  ever reads ``status='approved'``.
* 非法迁移 (rejected → approved, approved → pending_review, …) raises
  :class:`ReportConflict` and the API layer answers 409.
* 同区间重出: approving a newer version flips the older approved row to
  ``superseded`` (``version`` was already bumped at draft time), history kept.
* 永不 DELETE: enforced at the DB by the ``parent_reports_no_delete`` trigger
  (phase8i), not by convention — only status/version are ever UPDATEd.

Boundaries:
  * this module is a thin DAO + state machine; ownership (class belongs to the
    session teacher, student is a CONFIRMED roster member) is enforced in
    ``auth.api``;
  * ``teacher_edits`` is append-only at three levels: the API only allows edits
    on ``pending_review``, this module only ever APPENDS to the JSON array, and
    the DB trigger rejects any rewrite or shrink;
  * the 8-char student mask is applied by the API layer on parent-facing
    responses (the teacher console and the stored row keep the full id, same
    discipline as ``auth.scores``).
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any, Optional

from . import db

STATUS_PENDING_REVIEW = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_SUPERSEDED = "superseded"

REPORT_STATUSES = (
    STATUS_PENDING_REVIEW,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_SUPERSEDED,
)

# §4.1 legal transitions. Anything absent from this table is an illegal
# migration and must answer 409 (T-7).
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_PENDING_REVIEW: (STATUS_APPROVED, STATUS_REJECTED),
    STATUS_APPROVED: (STATUS_SUPERSEDED,),
    STATUS_REJECTED: (),
    STATUS_SUPERSEDED: (),
}

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT)

WEEK_MIN = 1
WEEK_MAX = 8

EDIT_FIELD_MAX_CHARS = 120
EDIT_VALUE_MAX_CHARS = 4000
EDIT_BATCH_MAX = 50
REVIEW_NOTE_MAX_CHARS = 500

# Mirrors agents.parent_report_agent.SKILL_CODES ordering for the 4D rollup.
SCORE_DIMENSIONS = ("DREAM", "DISCOVER", "DESIGN", "DELIVER")


class ReportNotFound(Exception):
    """404 — no such report_id (or not reachable by the session teacher)."""


class ReportConflict(Exception):
    """409 — one-pending gate hit, or an illegal state transition.

    ``existing`` carries the blocking ``pending_review`` row when the conflict
    came from the one-pending gate, so the API can answer 409＋草稿链接.
    """

    def __init__(self, message: str, *, existing: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.existing = existing


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _load(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except ValueError:
            return fallback
    return fallback


def _row_to_dict(row: sqlite3.Row, *, include_payload: bool = False) -> dict[str, Any]:
    out = {
        "report_id": row["report_id"],
        "version": row["version"],
        "student_id": row["student_id"],
        "class_id": row["class_id"],
        "week_from": row["week_from"],
        "week_to": row["week_to"],
        "status": row["status"],
        "lang_code": row["lang_code"],
        "age_band": row["age_band"],
        "scores": _load(row["scores"], {}),
        "review": _load(row["review"], {}),
        "cost_summary": _load(row["cost_summary"], {}),
        "generated_by": row["generated_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "published_at": row["published_at"],
        "teacher_edits_count": len(_load(row["teacher_edits"], []) or []),
    }
    if include_payload:
        # The stored envelope is the single-language report body (§3.2). Kept
        # out of list views so a 200-row teacher list stays a summary.
        out["payload"] = _load(row["payload"], {})
    return out


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_report(report_id: str) -> Optional[sqlite3.Row]:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
    finally:
        conn.close()


def get_report_for_teacher(
    report_id: str, teacher_id: str
) -> Optional[dict[str, Any]]:
    """Report row when the owning class belongs to the teacher, else None.

    Ownership is resolved in the SQL join (same discipline as the list
    helper) so a foreign report_id collapses to the unified 404/403 path
    instead of being readable by id guessing.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT pr.* FROM parent_reports pr
               JOIN classes c ON c.id = pr.class_id
               WHERE pr.report_id = ? AND c.teacher_id = ?""",
            (report_id, teacher_id),
        ).fetchone()
        return _row_to_dict(row, include_payload=True) if row is not None else None
    finally:
        conn.close()


def get_approved_for_student(
    report_id: str, student_id: str
) -> Optional[dict[str, Any]]:
    """One parent-visible row for one student — the parent-side read gate.

    Returns None for pending/rejected/superseded rows and for any student the
    caller does not own, so the endpoint cannot be used to probe report ids.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT * FROM parent_reports
               WHERE report_id = ? AND student_id = ? AND status = 'approved'""",
            (report_id, student_id),
        ).fetchone()
        return _row_to_dict(row, include_payload=True) if row is not None else None
    finally:
        conn.close()


def find_pending_report(student_id: str, class_id: str) -> Optional[sqlite3.Row]:
    """The live ``pending_review`` row for the key, if any (one-pending gate)."""
    conn = db.connect()
    try:
        return conn.execute(
            """SELECT * FROM parent_reports
               WHERE student_id = ? AND class_id = ? AND status = 'pending_review'
               ORDER BY version DESC LIMIT 1""",
            (student_id, class_id),
        ).fetchone()
    finally:
        conn.close()


def list_reports_for_teacher(
    teacher_id: str,
    *,
    status: Optional[str] = None,
    class_id: Optional[str] = None,
    student_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Teacher console list, scoped to the classes this teacher owns.

    The ownership join is in the SQL (never in the caller) so a foreign class
    id can only ever return an empty list.
    """
    conn = db.connect()
    try:
        sql = [
            """SELECT pr.* FROM parent_reports pr
               JOIN classes c ON c.id = pr.class_id
               WHERE c.teacher_id = ?"""
        ]
        params: list[Any] = [teacher_id]
        if status:
            sql.append("AND pr.status = ?")
            params.append(status)
        if class_id:
            sql.append("AND pr.class_id = ?")
            params.append(class_id)
        if student_id:
            sql.append("AND pr.student_id = ?")
            params.append(student_id)
        sql.append("ORDER BY pr.created_at DESC, pr.id DESC LIMIT 200")
        rows = conn.execute(" ".join(sql), tuple(params)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def latest_approved_for_student(student_id: str) -> Optional[sqlite3.Row]:
    """Newest parent-visible row for one student (§4.1 家长端只读 approved)."""
    conn = db.connect()
    try:
        return conn.execute(
            """SELECT * FROM parent_reports
               WHERE student_id = ? AND status = 'approved'
               ORDER BY version DESC, id DESC LIMIT 1""",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()


def list_approved_for_student(student_id: str) -> list[dict[str, Any]]:
    """All parent-visible rows for one student, newest version first."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT * FROM parent_reports
               WHERE student_id = ? AND status = 'approved'
               ORDER BY id DESC LIMIT 100""",
            (student_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def next_version(student_id: str, class_id: str) -> int:
    """Next version number for the (student, class) lineage — max + 1."""
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT MAX(version) AS v FROM parent_reports
               WHERE student_id = ? AND class_id = ?""",
            (student_id, class_id),
        ).fetchone()
    finally:
        conn.close()
    return int((row["v"] if row and row["v"] is not None else 0)) + 1


def build_dimension_scores(
    student_id: str, week_from: int, week_to: int
) -> dict[str, Optional[int]]:
    """Latest teacher score per 4D dimension inside the week window.

    Missing dimensions are ``null`` (never 0) so the descriptor pitch cannot
    be mistaken for a real "Not Yet" judgement (§3.2 scores contract).
    """
    conn = db.connect()
    try:
        out: dict[str, Optional[int]] = {}
        for dim in SCORE_DIMENSIONS:
            row = conn.execute(
                """SELECT score_0_3 FROM assessment_logs
                   WHERE student_id = ? AND scored_by = 'teacher'
                     AND skill_code = ?
                     AND week_no BETWEEN ? AND ?
                   ORDER BY week_no DESC, id DESC LIMIT 1""",
                (student_id, dim, week_from, week_to),
            ).fetchone()
            out[dim] = row["score_0_3"] if row is not None else None
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Writes (state machine)
# ---------------------------------------------------------------------------


def create_pending_report(
    *,
    student_id: str,
    class_id: str,
    lang_code: str,
    age_band: str,
    week_from: int,
    week_to: int,
    scores: dict[str, Any],
    payload: dict[str, Any],
    cost_summary: Optional[dict[str, Any]] = None,
    generated_by: str = "auto",
) -> dict[str, Any]:
    """Draft a report into ``pending_review``.

    The one-pending partial unique index (``uq_parent_reports_one_pending``) is
    the gate: a concurrent generate for the same (student, class) is rejected
    by the DB itself and surfaces as :class:`ReportConflict` carrying the
    existing draft.
    """
    now = _now_iso()
    report_id = "rpt_" + uuid.uuid4().hex
    conn = db.connect()
    try:
        existing = conn.execute(
            """SELECT * FROM parent_reports
               WHERE student_id = ? AND class_id = ? AND status = 'pending_review'
               LIMIT 1""",
            (student_id, class_id),
        ).fetchone()
        if existing is not None:
            raise ReportConflict(
                "one pending report already exists", existing=_row_to_dict(existing)
            )
        try:
            conn.execute(
                """INSERT INTO parent_reports
                   (report_id, version, student_id, class_id, week_from, week_to,
                    status, lang_code, age_band, scores, payload, teacher_edits,
                    review, cost_summary, generated_by, pdf_path, pdf_sha256,
                    created_at, updated_at, approved_at, approved_by, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, '[]',
                           '{}', ?, ?, '', '', ?, ?, '', '', '')""",
                (
                    report_id,
                    next_version(student_id, class_id),
                    student_id,
                    class_id,
                    week_from,
                    week_to,
                    lang_code,
                    age_band or "",
                    _dump(scores),
                    _dump(payload),
                    _dump(cost_summary or {}),
                    generated_by,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # Race: another request drafted between our SELECT and INSERT.
            raced = conn.execute(
                """SELECT * FROM parent_reports
                   WHERE student_id = ? AND class_id = ?
                     AND status = 'pending_review' LIMIT 1""",
                (student_id, class_id),
            ).fetchone()
            if raced is None:
                raise
            raise ReportConflict(
                "one pending report already exists",
                existing=_row_to_dict(raced),
            ) from exc
        conn.commit()
        row = conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return _row_to_dict(row, include_payload=True)
    finally:
        conn.close()


def _append_json_array(old_json: str, items: list[dict[str, Any]]) -> str:
    """Append items to a JSON array by string splicing.

    Deliberately NOT ``json.dumps(list)``: the phase8i trigger proves
    append-only by requiring the new text to start with the old text minus its
    closing bracket, so re-serialising the whole array (which can reorder keys
    or change separators) would be rejected — and rightly so, it is a rewrite.
    """
    base = old_json if isinstance(old_json, str) and old_json.startswith("[") else "[]"
    try:
        json.loads(base)
    except ValueError:
        base = "[]"
    if not items:
        return base
    parts = [
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in items
    ]
    body = base[:-1]  # drop the closing ']' — body stays a literal prefix
    if body.strip() != "[":
        body += ","
    return body + ",".join(parts) + "]"


def record_teacher_edits(
    *,
    report_id: str,
    teacher_id: str,
    edits: list[dict[str, Any]],
    payload_patch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append field-level diffs to ``teacher_edits`` (pending_review only).

    Each entry is stored as ``{field, before, after, by, at}`` — the §4.2
    "改前→改后→时间戳" shape. The audit trail can only grow.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise ReportNotFound(report_id)
        if row["status"] != STATUS_PENDING_REVIEW:
            raise ReportConflict(
                f"illegal transition: cannot edit a {row['status']} report"
            )

        now = _now_iso()
        entries = []
        for raw in edits[:EDIT_BATCH_MAX]:
            entries.append(
                {
                    "field": str(raw.get("field") or "")[:EDIT_FIELD_MAX_CHARS],
                    "before": str(raw.get("before") or "")[:EDIT_VALUE_MAX_CHARS],
                    "after": str(raw.get("after") or "")[:EDIT_VALUE_MAX_CHARS],
                    "by": teacher_id,
                    "at": now,
                }
            )

        new_edits = _append_json_array(row["teacher_edits"] or "[]", entries)
        payload_raw = row["payload"]
        if payload_patch:
            payload = _load(payload_raw, {})
            if isinstance(payload, dict):
                payload.update(payload_patch)
                payload_raw = _dump(payload)

        conn.execute(
            """UPDATE parent_reports
               SET payload = ?, teacher_edits = ?, updated_at = ?
               WHERE report_id = ? AND status = 'pending_review'""",
            (payload_raw, new_edits, now, report_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return _row_to_dict(updated, include_payload=True)
    finally:
        conn.close()


def decide_report(
    *,
    report_id: str,
    decision: str,
    teacher_id: str,
    note: str = "",
) -> dict[str, Any]:
    """Drive the state machine: approve / reject from ``pending_review``.

    ``approve`` publishes (``approved_at`` == ``published_at``) and supersedes
    the previous approved version of the same (student, class, week window),
    whose row is UPDATEd to ``superseded`` — never deleted.
    """
    if decision not in DECISIONS:
        raise ReportConflict(f"unknown decision {decision!r}")

    target = STATUS_APPROVED if decision == DECISION_APPROVE else STATUS_REJECTED
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise ReportNotFound(report_id)

        current = row["status"]
        if target not in LEGAL_TRANSITIONS.get(current, ()):
            raise ReportConflict(f"illegal transition: {current} -> {target}")

        now = _now_iso()
        review = _load(row["review"], {})
        if not isinstance(review, dict):
            review = {}
        review["decision"] = decision
        review["decided_by"] = teacher_id
        review["decided_at"] = now
        if note:
            review["note"] = note[:REVIEW_NOTE_MAX_CHARS]

        if target == STATUS_APPROVED:
            # supersede the previous approved version of the same window (§4.1)
            conn.execute(
                """UPDATE parent_reports
                   SET status = 'superseded', updated_at = ?
                   WHERE student_id = ? AND class_id = ?
                     AND week_from = ? AND week_to = ?
                     AND status = 'approved' AND report_id <> ?""",
                (
                    now,
                    row["student_id"],
                    row["class_id"],
                    row["week_from"],
                    row["week_to"],
                    report_id,
                ),
            )
            conn.execute(
                """UPDATE parent_reports
                   SET status = 'approved', approved_at = ?, approved_by = ?,
                       published_at = ?, review = ?, updated_at = ?
                   WHERE report_id = ? AND status = 'pending_review'""",
                (now, teacher_id, now, _dump(review), now, report_id),
            )
        else:
            conn.execute(
                """UPDATE parent_reports
                   SET status = 'rejected', review = ?, updated_at = ?
                   WHERE report_id = ? AND status = 'pending_review'""",
                (_dump(review), now, report_id),
            )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM parent_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return _row_to_dict(updated, include_payload=True)
    finally:
        conn.close()


def applied_status_counts(teacher_id: str) -> dict[str, int]:
    """Per-status counters for the teacher console summary line."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT pr.status AS status, COUNT(*) AS n
               FROM parent_reports pr
               JOIN classes c ON c.id = pr.class_id
               WHERE c.teacher_id = ?
               GROUP BY pr.status""",
            (teacher_id,),
        ).fetchall()
        counts = {s: 0 for s in REPORT_STATUSES}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts
    finally:
        conn.close()
