"""PR-2 teacher weekly scoring input (design book v1.1 §4.4, boss work order 2026-10-15).

PUT /api/teacher/scores writes one weekly score into assessment_logs with
scored_by='teacher'. Idempotent overwrite: re-scoring the same
(student_id, week_no, skill_code) key updates the existing row — the old
value is FIRST appended to teacher_score_audit (append-only, enforced at the
DB by triggers, same discipline as ws_chat_relay_audit), never silently
discarded. Revoke semantics: score_0_3=null clears the current score (old
value still archived in the audit).

Ownership (class roster / cross-class) is enforced in auth/api.py; this
module is the thin DAO and owns row integrity only. age_band is written from
the students table by the API layer (server-derived), never trusted from the
client.
"""

from __future__ import annotations

import datetime
import sqlite3
from typing import Any, Optional

from . import db

SKILL_CODES = ("DREAM", "DISCOVER", "DESIGN", "DELIVER")
WEEK_MIN = 1
WEEK_MAX = 8
SCORE_MIN = 0
SCORE_MAX = 3
# Must stay aligned with agents.parent_report_agent.EVIDENCE_MAX_CHARS.
# T-7 asserts both equal 200 so the pair cannot drift silently.
EVIDENCE_MAX_CHARS = 200
SCORED_BY_TEACHER = "teacher"
TEACHER_INTERNAL_LABEL = "teacher_score"
# Red-line 8: audit rows carry only the 8-char student mask (never the full
# student id) plus the assessment_logs row id for traceability.
STUDENT_MASK_LEN = 8


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def find_teacher_score(
    conn: sqlite3.Connection,
    *,
    student_id: str,
    week_no: int,
    skill_code: str,
) -> Optional[Any]:
    """Latest teacher-scored row for the (student, week, skill) key.

    The key is unique per (student_id, week_no, skill_code) by the idempotent
    overwrite contract: at most one live teacher row per key exists. ORDER BY
    id DESC LIMIT 1 is belt-and-braces for any legacy data drift.
    """
    return conn.execute(
        """SELECT id, score_0_3, evidence_text
           FROM assessment_logs
           WHERE student_id = ? AND week_no = ? AND skill_code = ?
             AND scored_by = 'teacher'
           ORDER BY id DESC LIMIT 1""",
        (student_id, week_no, skill_code),
    ).fetchone()


def _audit_old_value(
    conn: sqlite3.Connection,
    *,
    student_id: str,
    week_no: int,
    skill_code: str,
    old_score: Optional[int],
    old_evidence: str,
    assessment_id: int,
    replaced_by: str,
) -> None:
    """Append-only archive of the value about to be overwritten."""
    conn.execute(
        """INSERT INTO teacher_score_audit
           (student_mask, week_no, skill_code, old_score, old_evidence,
            assessment_id, replaced_by, replaced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            student_id[:STUDENT_MASK_LEN],
            week_no,
            skill_code,
            old_score,
            old_evidence,
            assessment_id,
            replaced_by,
            _now_iso(),
        ),
    )


def upsert_teacher_score(
    *,
    student_id: str,
    class_id: str,
    week_no: int,
    skill_code: str,
    score: Optional[int],
    evidence: str,
    teacher_id: str,
    age_band: str,
    lang_code: str,
) -> dict[str, Any]:
    """Idempotent insert-or-overwrite; the old value goes to the audit first.

    class_id is accepted for API-contract symmetry and traceability in
    callers; row integrity only ever depends on (student_id, week_no,
    skill_code) plus the scored_by='teacher' marker.

    Returns {"status": str, "id": Optional[int]} where status is one of:
      - "inserted": new assessment_logs row created.
      - "updated":  existing row overwritten (old value archived first).
      - "unchanged": identical re-submission — no audit row, no DB change.
      - "noop":     revoke (score=None) for a key with no live score yet.
    """
    conn = db.connect()
    try:
        existing = find_teacher_score(
            conn, student_id=student_id, week_no=week_no, skill_code=skill_code
        )
        evidence = evidence or ""
        if existing is not None:
            old_score = existing["score_0_3"]
            old_evidence = existing["evidence_text"] or ""
            if old_score == score and old_evidence == evidence:
                return {"status": "unchanged", "id": existing["id"]}
            _audit_old_value(
                conn,
                student_id=student_id,
                week_no=week_no,
                skill_code=skill_code,
                old_score=old_score,
                old_evidence=old_evidence,
                assessment_id=existing["id"],
                replaced_by=teacher_id,
            )
            conn.execute(
                """UPDATE assessment_logs
                   SET score_0_3 = ?, evidence_text = ?
                   WHERE id = ?""",
                (score, evidence, existing["id"]),
            )
            conn.commit()
            return {"status": "updated", "id": existing["id"]}

        if score is None:
            # revoke for a key that has no live score yet — nothing to clear
            return {"status": "noop"}

        now = _now_iso()
        cur = conn.execute(
            """INSERT INTO assessment_logs
               (student_id, session_id, topic_id, mode, lang_code,
                internal_label, confidence, rubric_id, evidence_text,
                agent_used, cost_tokens, created_at,
                age_band, week_no, skill_code, score_0_3, scored_by, report_id)
               VALUES (?, '', '', 'DIRECT', ?, ?, 0.0, '', ?, ?, 0, ?,
                       ?, ?, ?, ?, ?, '')""",
            (
                student_id,
                lang_code,
                TEACHER_INTERNAL_LABEL,
                evidence,
                SCORED_BY_TEACHER,
                now,
                age_band,
                week_no,
                skill_code,
                score,
                SCORED_BY_TEACHER,
            ),
        )
        conn.commit()
        return {"status": "inserted", "id": cur.lastrowid}
    finally:
        conn.close()
