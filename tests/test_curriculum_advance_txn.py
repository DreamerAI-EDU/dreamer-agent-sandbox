"""Hygiene (advance-week transaction) — a week flip is all-or-nothing.

The bridge-2 nit under test: ``advance_week`` used to read the 8 rows, then
issue two UPDATEs and commit. The check-then-act pair sat across two separate
statement boundaries with no write lock, so a second advance could interleave
and land a half transition (week N closed but N+1 still locked, or N+1 opened
twice). It now runs in one ``BEGIN IMMEDIATE`` transaction whose UPDATEs are
guarded by the status that was read.

Negative cases (red line #9 — registered in the ci.yml manifest):
  * a crash between the two writes rolls the first one back;
  * a stale/racing write matches 0 rows, raises ``_AdvanceRace``, changes
    nothing.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import curriculum as curriculum_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from pipeline import topic_metadata_schema  # noqa: E402

CLASS_ID = "class-txn-001"
CURRICULUM_ID = "txn-curriculum"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _statuses(class_id: str = CLASS_ID) -> dict[int, str]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT week_no, status FROM class_curriculum "
            "WHERE class_id = ? ORDER BY week_no ASC",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()
    return {int(row["week_no"]): str(row["status"]) for row in rows}


@pytest.fixture
def mounted_class(tmp_path, monkeypatch):
    """A class with a freshly mounted 1..8 curriculum (week 1 active)."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "txn.db"))
    auth_db.ensure_schema()
    curriculum_mod._prepare()

    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO classes (id, teacher_id, name, join_code, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (CLASS_ID, "teacher-txn", "Txn Class", "TXN001",
             curriculum_mod._now_iso()),
        )
        topic_metadata_schema.ensure_schema(conn)
        for week in range(1, 9):
            conn.execute(
                "INSERT INTO topic_metadata (topic_id, subject, topic, "
                "modes_allowed, grade_level, week, dreamer_phase, kb_name, "
                "document_path, document_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{CURRICULUM_ID}-wk{week:02d}",
                    "AI Literacy",
                    f"Week {week}",
                    '["contextual"]',
                    "P4-P6",
                    week,
                    '["Design"]',
                    CURRICULUM_ID,
                    f"curriculum-wk{week:02d}.md",
                    f"hash-{week}",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    _, error = curriculum_mod.mount_curriculum(
        class_id=CLASS_ID, curriculum_id=CURRICULUM_ID
    )
    assert error is None
    return CLASS_ID


def test_crash_between_the_two_writes_rolls_everything_back(mounted_class):
    def _half_write(conn, class_id, *, expected_week, now):
        conn.execute(
            "UPDATE class_curriculum SET status = ? "
            "WHERE class_id = ? AND week_no = ?",
            (curriculum_mod.STATUS_COMPLETED, class_id, expected_week),
        )
        raise RuntimeError("simulated crash between the two writes")

    # A nested MonkeyPatch context: patching through the test's own monkeypatch
    # fixture and calling undo() later would also drop the fixture's DB env var.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(curriculum_mod, "_apply_advance", _half_write)
        with pytest.raises(RuntimeError):
            curriculum_mod.advance_week(mounted_class)

    statuses = _statuses()
    assert statuses[1] == curriculum_mod.STATUS_ACTIVE
    assert statuses[2] == curriculum_mod.STATUS_LOCKED

    # The rollback left the connection reusable: a real advance now works and
    # moves exactly one week.
    payload, error = curriculum_mod.advance_week(mounted_class)
    assert error is None, error
    assert payload["completed_week"] == 1
    assert payload["active_week"] == 2
    assert _statuses()[2] == curriculum_mod.STATUS_ACTIVE


def test_stale_guard_write_is_refused_and_writes_nothing(mounted_class):
    """A writer whose expectation no longer matches matches 0 rows."""
    conn = auth_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(curriculum_mod._AdvanceRace):
            curriculum_mod._apply_advance(
                conn,
                mounted_class,
                expected_week=5,  # week 5 is locked; only week 1 is active
                now=curriculum_mod._now_iso(),
            )
        conn.rollback()
    finally:
        conn.close()

    statuses = _statuses()
    assert statuses[1] == curriculum_mod.STATUS_ACTIVE
    assert statuses[5] == curriculum_mod.STATUS_LOCKED
    assert curriculum_mod.STATUS_COMPLETED not in statuses.values()


def test_advance_week_still_refuses_unmounted_and_completed_states(
    mounted_class, tmp_path, monkeypatch
):
    """The single-transaction rewrite must not weaken the linear rules."""
    _, error = curriculum_mod.advance_week("class-never-mounted")
    assert error == curriculum_mod.ERR_NOT_MOUNTED

    for _ in range(8):  # week 1 active -> ... -> week 8 completed
        payload, error = curriculum_mod.advance_week(mounted_class)
        assert error is None, error
    assert payload["course_completed"] is True

    payload, error = curriculum_mod.advance_week(mounted_class)
    assert payload is None
    assert error == curriculum_mod.ERR_COURSE_COMPLETED
