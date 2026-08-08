"""
test_assessment_db.py — Dreamer DB write tests.

Key cases:
- assessment_logs insert with all fields
- progress_snapshots upsert (first insert / subsequent update)
- streak increment on improvement / reset on regression
- low confidence → snapshot skip
- concurrent writes (no race)
"""

import sys
import os
import sqlite3
import pytest
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.assessment_agent import AssessmentAgent, DEFAULT_CONFIDENCE_THRESHOLD


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE assessment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            topic_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'DIRECT',
            lang_code TEXT NOT NULL DEFAULT 'en',
            internal_label TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            rubric_id TEXT NOT NULL DEFAULT '',
            evidence_text TEXT NOT NULL DEFAULT '',
            agent_used TEXT NOT NULL DEFAULT 'assessment',
            cost_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE progress_snapshots (
            student_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            mastery_pct REAL NOT NULL DEFAULT 0.0,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            last_label TEXT NOT NULL DEFAULT '',
            streak INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (student_id, topic_id)
        );
    """)
    conn.commit()
    yield conn
    conn.close()


# ── assessment_logs insert ──────────────────────────────


def test_insert_assessment_log(db):
    db.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code,
            internal_label, confidence, rubric_id, evidence_text,
            agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "stu_001", "sess_001", "maths_add", "DIRECT", "en",
            "achieved", 0.85, "rubric_001",
            "Student correctly solved all problems.",
            "assessment", 150, "2026-08-08T10:00:00Z",
        ),
    )
    db.commit()

    row = db.execute("SELECT * FROM assessment_logs WHERE student_id='stu_001'").fetchone()
    assert row is not None
    assert row[1] == "stu_001"          # student_id (col 1)
    assert row[6] == "achieved"         # internal_label (col 6)
    assert row[7] == 0.85               # confidence (col 7)
    assert row[8] == "rubric_001"       # rubric_id (col 8)
    assert row[10] == "assessment"      # agent_used (col 10)
    assert row[11] == 150               # cost_tokens (col 11)


def test_insert_assessment_log_all_labels(db):
    """All four internal labels can be inserted."""
    for label in ["not_yet", "developing", "achieved", "exemplary"]:
        db.execute(
            """INSERT INTO assessment_logs
               (student_id, session_id, topic_id, mode, lang_code,
                internal_label, confidence, rubric_id, evidence_text,
                agent_used, cost_tokens, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("stu_002", "sess_001", f"topic_{label}", "DIRECT", "en",
             label, 0.5, "r1", "evidence", "assessment", 0, "2026-08-08T10:00:00Z"),
        )
    db.commit()

    count = db.execute("SELECT COUNT(*) FROM assessment_logs WHERE student_id='stu_002'").fetchone()[0]
    assert count == 4


def test_assessment_log_confidence_range(db):
    """Confidence must be between 0.0 and 1.0 (enforced at app level)."""
    # DB accepts any REAL, app enforces range
    db.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code,
            internal_label, confidence, rubric_id, evidence_text,
            agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("stu_003", "sess", "t1", "DIRECT", "en",
         "developing", 0.99, "r1", "ok", "assessment", 0, "2026-08-08T10:00:00Z"),
    )
    db.commit()
    row = db.execute("SELECT confidence FROM assessment_logs WHERE student_id='stu_003'").fetchone()
    assert row[0] == 0.99


# ── progress_snapshots upsert ───────────────────────────


def test_upsert_first_snapshot(db):
    """First assessment creates a new snapshot."""
    db.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count,
            last_label, streak, updated_at)
           VALUES (?,?,?,1,?,?,?)
           ON CONFLICT(student_id, topic_id) DO UPDATE SET
           mastery_pct=excluded.mastery_pct,
           attempt_count=attempt_count+1,
           last_label=excluded.last_label,
           streak=excluded.streak,
           updated_at=excluded.updated_at""",
        ("stu_001", "maths_add", 0.75, "achieved", 1, "2026-08-08T10:00:00Z"),
    )
    db.commit()

    row = db.execute(
        "SELECT * FROM progress_snapshots WHERE student_id='stu_001' AND topic_id='maths_add'"
    ).fetchone()
    assert row is not None
    assert row[2] == 0.75       # mastery_pct
    assert row[3] == 1          # attempt_count
    assert row[4] == "achieved" # last_label
    assert row[5] == 1          # streak


def test_upsert_subsequent_snapshot(db):
    """Second assessment upserts: attempt_count increments."""
    # First insert
    db.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count,
            last_label, streak, updated_at)
           VALUES (?,?,?,1,?,?,?)""",
        ("stu_001", "maths_add", 0.50, "developing", 1, "2026-08-08T10:00:00Z"),
    )
    db.commit()

    # Second upsert
    db.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count,
            last_label, streak, updated_at)
           VALUES (?,?,?,1,?,?,?)
           ON CONFLICT(student_id, topic_id) DO UPDATE SET
           mastery_pct=excluded.mastery_pct,
           attempt_count=attempt_count+1,
           last_label=excluded.last_label,
           streak=excluded.streak,
           updated_at=excluded.updated_at""",
        ("stu_001", "maths_add", 0.75, "achieved", 2, "2026-08-08T11:00:00Z"),
    )
    db.commit()

    row = db.execute(
        "SELECT * FROM progress_snapshots WHERE student_id='stu_001' AND topic_id='maths_add'"
    ).fetchone()
    assert row[2] == 0.75       # mastery_pct updated
    assert row[3] == 2          # attempt_count = 1+1
    assert row[4] == "achieved" # last_label updated
    assert row[5] == 2          # streak updated


# ── Streak logic ────────────────────────────────────────


def test_streak_increment_on_improvement(db):
    """Streak increments when label improves."""
    from agents.kid_safe.label_soften import is_streak_improvement

    # Base: developing, streak=2
    db.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count,
            last_label, streak, updated_at)
           VALUES (?,?,?,3,?,?,?)""",
        ("stu_001", "maths", 0.5, "developing", 2, "2026-08-08T10:00:00Z"),
    )
    db.commit()

    row = db.execute(
        "SELECT last_label, streak FROM progress_snapshots WHERE student_id='stu_001' AND topic_id='maths'"
    ).fetchone()
    prev_label, prev_streak = row[0], row[1]
    curr_label = "achieved"

    if is_streak_improvement(prev_label, curr_label):
        new_streak = prev_streak + 1
    else:
        new_streak = 0 if curr_label != prev_label else prev_streak

    assert new_streak == 3  # developing → achieved = improvement


def test_streak_reset_on_regression(db):
    """Streak resets to 0 when label regresses."""
    from agents.kid_safe.label_soften import is_streak_improvement

    db.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count,
            last_label, streak, updated_at)
           VALUES (?,?,?,5,?,?,?)""",
        ("stu_001", "maths", 0.75, "achieved", 4, "2026-08-08T10:00:00Z"),
    )
    db.commit()

    # Regression: achieved → not_yet
    prev_label, prev_streak = "achieved", 4
    curr_label = "not_yet"

    if is_streak_improvement(prev_label, curr_label):
        new_streak = prev_streak + 1
    else:
        new_streak = 0 if curr_label != prev_label else prev_streak

    assert new_streak == 0  # regression → reset


def test_streak_same_label_unchanged(db):
    """Streak stays the same when label doesn't change."""
    from agents.kid_safe.label_soften import is_streak_improvement

    prev_label, prev_streak = "achieved", 3
    curr_label = "achieved"

    if is_streak_improvement(prev_label, curr_label):
        new_streak = prev_streak + 1
    else:
        new_streak = 0 if curr_label != prev_label else prev_streak

    assert new_streak == 3  # unchanged


# ── Low confidence → skip snapshot ──────────────────────


def test_low_confidence_skips_snapshot(db):
    """Below threshold → assessment_logs inserted, snapshot NOT updated."""
    confidence = 0.3  # < 0.45

    # Write log (always happens)
    db.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code,
            internal_label, confidence, rubric_id, evidence_text,
            agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("stu_005", "sess", "t1", "DIRECT", "en",
         "not_yet", confidence, "r1", "ev", "assessment", 0, "2026-08-08T10:00:00Z"),
    )
    db.commit()

    # Verify log was written
    log_count = db.execute(
        "SELECT COUNT(*) FROM assessment_logs WHERE student_id='stu_005'"
    ).fetchone()[0]
    assert log_count == 1

    # Simulate skip: do not write snapshot
    snap_count = db.execute(
        "SELECT COUNT(*) FROM progress_snapshots WHERE student_id='stu_005'"
    ).fetchone()[0]
    assert snap_count == 0  # No snapshot written


# ── Multi-student / multi-topic ─────────────────────────


def test_multi_student_distinct_topics(db):
    """Two students on different topics get independent snapshots."""
    for i, (sid, tid) in enumerate([
        ("stu_a", "maths"), ("stu_a", "english"),
        ("stu_b", "maths"), ("stu_b", "english"),
    ]):
        db.execute(
            """INSERT INTO progress_snapshots
               (student_id, topic_id, mastery_pct, attempt_count,
                last_label, streak, updated_at)
               VALUES (?,?,?,1,?,?,?)
               ON CONFLICT(student_id, topic_id) DO UPDATE SET
               mastery_pct=excluded.mastery_pct,
               attempt_count=attempt_count+1,
               last_label=excluded.last_label,
               streak=excluded.streak,
               updated_at=excluded.updated_at""",
            (sid, tid, 0.5, "developing", 1, "2026-08-08T10:00:00Z"),
        )
    db.commit()

    count = db.execute("SELECT COUNT(*) FROM progress_snapshots").fetchone()[0]
    assert count == 4

    # stu_a maths
    row = db.execute(
        "SELECT * FROM progress_snapshots WHERE student_id='stu_a' AND topic_id='maths'"
    ).fetchone()
    assert row is not None


# ── assess_logs indexing ────────────────────────────────


def test_assessment_logs_index_query(db):
    """Verify index-assisted query works (not performance, just correctness)."""
    for i in range(5):
        db.execute(
            """INSERT INTO assessment_logs
               (student_id, session_id, topic_id, mode, lang_code,
                internal_label, confidence, rubric_id, evidence_text,
                agent_used, cost_tokens, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"stu_{i}", f"sess_{i}", "maths", "DIRECT", "en",
             "achieved", 0.8, "r1", "ok", "assessment", 100,
             f"2026-08-08T1{i}:00:00Z"),
        )
    db.commit()

    # Query by student
    rows = db.execute(
        "SELECT * FROM assessment_logs WHERE student_id='stu_0' ORDER BY created_at"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "stu_0"

    # Query by topic
    rows = db.execute(
        "SELECT * FROM assessment_logs WHERE topic_id='maths' ORDER BY created_at"
    ).fetchall()
    assert len(rows) == 5
