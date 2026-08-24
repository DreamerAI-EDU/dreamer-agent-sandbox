"""
Dreamer AI Phase 4 Day 20 — Curriculum Navigator tests

Test order (TDD):
  1. KB Matrix rules (ethical-ai always, DIRECT filters psd/life_skills)
  2. get_prerequisites / get_topic_metadata (DB read)
  3. check_prereq_gaps (pure DB, no LLM)
  4. Integration: resolve_kb_list with real topic_metadata

Fixture: in-memory SQLite seeded with topic_metadata + progress_snapshots.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

# Ensure agents is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.curriculum_navigator import (
    CurriculumNavigator,
    ETHICAL_AI_KB,
    FILTER_IN_DIRECT,
    _connect,
    _json_list,
    validate_age_band,
)

# ── Constants ──────────────────────────────────────────

SAMPLE_TOPIC_MATH = "maths-fractions-01"
SAMPLE_TOPIC_PSD = "psd-teamwork-u1"
SAMPLE_TOPIC_SCIENCE = "science-energy-02"
SAMPLE_TOPIC_ETHICS = "ethics-digital-citizen"
STUDENT_ALICE = "student-alice"
STUDENT_BOB = "student-bob"


# ── Helper ─────────────────────────────────────────────

def seed_topic_metadata(conn: sqlite3.Connection) -> None:
    """Insert sample topic_metadata rows."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_metadata (
            topic_id        TEXT PRIMARY KEY,
            subject         TEXT NOT NULL,
            grade_level     TEXT NOT NULL,
            prerequisites   TEXT NOT NULL DEFAULT '[]',
            kb_list         TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL DEFAULT ''
        );
    """)
    rows = [
        (
            "maths-fractions-01", "Mathematics", "P4-P6",
            json.dumps(["maths-numbers-01"]),
            json.dumps(["dreamer-maths-ai"]),
        ),
        (
            "maths-numbers-01", "Mathematics", "P4-P6",
            "[]",
            json.dumps(["dreamer-maths-ai"]),
        ),
        (
            "psd-teamwork-u1", "PSD", "P4-P6",
            "[]",
            json.dumps(["dreamer-portfolio"]),
        ),
        (
            "science-energy-02", "Science", "S1-S3",
            json.dumps(["science-matter-01"]),
            json.dumps(["dreamer-coding-python", "dreamer-game-design"]),
        ),
        (
            "science-matter-01", "Science", "S1-S3",
            "[]",
            json.dumps(["dreamer-coding-python"]),
        ),
        (
            "ethics-digital-citizen", "Computing", "S1-S3",
            "[]",
            json.dumps(["dreamer-coding-python", "dreamer-ethical-ai"]),
        ),
        (
            "english-grammar-03", "English", "P1-P3",
            json.dumps(["english-phonics-01"]),
            json.dumps(["dreamer-coding-python", "dreamer-game-design",
                        "dreamer-maths-ai"]),
        ),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO topic_metadata "
        "(topic_id, subject, grade_level, prerequisites, kb_list) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()


def seed_progress_snapshots(conn: sqlite3.Connection) -> None:
    """Insert sample progress data."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS progress_snapshots (
            student_id TEXT NOT NULL,
            topic_id   TEXT NOT NULL,
            mastery_pct REAL NOT NULL DEFAULT 0.0,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            last_label TEXT NOT NULL DEFAULT '',
            streak     INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (student_id, topic_id)
        );
    """)
    rows = [
        # Alice: maths-numbers-01 mastered
        ("student-alice", "maths-numbers-01", 0.75, 3, "Achieved", 2, "2025-01-01T00:00:00Z"),
        # Alice: science-matter-01 still Developing -> gap
        ("student-alice", "science-matter-01", 0.50, 1, "Developing", 0, "2025-01-01T00:00:00Z"),
        # Bob: no records at all -> all gaps
        # Bob: science-matter-01 Exemplary -> not gapped
        ("student-bob", "science-matter-01", 1.00, 4, "Exemplary", 3, "2025-01-01T00:00:00Z"),
        # Bob: english-phonics-01 Not Yet -> gap
        ("student-bob", "english-phonics-01", 0.25, 1, "Not Yet", 0, "2025-01-01T00:00:00Z"),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO progress_snapshots "
        "(student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


@pytest.fixture
def db_path(tmp_path):
    """SQLite file path for tests (not in-memory, for realism)."""
    return str(tmp_path / "test_navigator.db")


@pytest.fixture
def seeded_db(db_path):
    """Create and seed a SQLite DB, return the path."""
    conn = sqlite3.connect(db_path)
    try:
        seed_topic_metadata(conn)
        seed_progress_snapshots(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture
def nav(seeded_db):
    """Navigator instance pointing at seeded DB."""
    return CurriculumNavigator(db_path=seeded_db)


# ═══════════════════════════════════════════════════════════
# Part 1: KB Matrix 硬規則 — TDD (先紅後綠)
# ═══════════════════════════════════════════════════════════

class TestKBMatrixRules:
    """Two hard rules: ethical-ai always append; DIRECT filter is now an
    empty set (psd/life_skills have no manifest counterpart — B21 §1)."""

    def test_ethical_ai_appended_when_absent(self, nav):
        """Rule 1: dreamer-ethical-ai is always appended if not already present."""
        kbs = nav.resolve_kb_list("HYBRID", "maths-fractions-01")
        assert ETHICAL_AI_KB in kbs

    def test_ethical_ai_not_duplicated_when_present(self, nav):
        """Rule 1: dreamer-ethical-ai is NOT duplicated if already in kb_list."""
        kbs = nav.resolve_kb_list("HYBRID", "ethics-digital-citizen")
        assert kbs.count(ETHICAL_AI_KB) == 1

    def test_direct_filter_is_empty_set(self, nav):
        """Rule 2 (B21): FILTER_IN_DIRECT is empty — no KB is dropped in
        DIRECT mode anymore."""
        kbs = nav.resolve_kb_list("DIRECT", "psd-teamwork-u1")
        assert "dreamer-portfolio" in kbs

    def test_direct_keeps_all_kbs(self, nav):
        """Rule 2 (B21): DIRECT no longer filters coding/game kbs."""
        kbs = nav.resolve_kb_list("DIRECT", "science-energy-02")
        assert "dreamer-coding-python" in kbs
        assert "dreamer-game-design" in kbs

    def test_hybrid_does_not_filter(self, nav):
        """HYBRID mode: no KB is filtered."""
        kbs = nav.resolve_kb_list("HYBRID", "english-grammar-03")
        assert "dreamer-coding-python" in kbs
        assert "dreamer-game-design" in kbs
        assert "dreamer-maths-ai" in kbs

    def test_contextual_does_not_filter(self, nav):
        """CONTEXTUAL mode: no KB is filtered."""
        kbs = nav.resolve_kb_list("CONTEXTUAL", "english-grammar-03")
        assert "dreamer-coding-python" in kbs
        assert "dreamer-game-design" in kbs

    def test_combined_rules_direct_appends_ethical(self, nav):
        """DIRECT mode: ethical-ai appended; empty filter keeps all kbs."""
        kbs = nav.resolve_kb_list("DIRECT", "english-grammar-03")
        assert ETHICAL_AI_KB in kbs
        assert "dreamer-coding-python" in kbs
        assert "dreamer-game-design" in kbs
        assert "dreamer-maths-ai" in kbs

    def test_ethical_ai_stays_even_in_direct(self, nav):
        """Rule 1 + Rule 2: ethical-ai is NOT in FILTER_IN_DIRECT, stays."""
        kbs = nav.resolve_kb_list("DIRECT", "science-energy-02")
        assert ETHICAL_AI_KB in kbs


# ═══════════════════════════════════════════════════════════
# Part 2: get_prerequisites / get_topic_metadata
# ═══════════════════════════════════════════════════════════

class TestPrerequisites:
    """DB reads: get_prerequisites and get_topic_metadata."""

    def test_get_prerequisites_returns_list(self, nav):
        pre = nav.get_prerequisites("maths-fractions-01")
        assert pre == ["maths-numbers-01"]

    def test_get_prerequisites_empty_list(self, nav):
        pre = nav.get_prerequisites("maths-numbers-01")
        assert pre == []

    def test_get_prerequisites_missing_topic_returns_empty(self, nav):
        pre = nav.get_prerequisites("nonexistent-topic")
        assert pre == []

    def test_get_prerequisites_multiple(self, nav):
        pre = nav.get_prerequisites("english-grammar-03")
        assert pre == ["english-phonics-01"]

    def test_get_topic_metadata_full(self, nav):
        meta = nav.get_topic_metadata("science-energy-02")
        assert meta is not None
        assert meta["topic_id"] == "science-energy-02"
        assert meta["subject"] == "Science"
        assert meta["grade_level"] == "S1-S3"
        assert meta["prerequisites"] == ["science-matter-01"]
        assert "dreamer-coding-python" in meta["kb_list"]
        assert "dreamer-game-design" in meta["kb_list"]

    def test_get_topic_metadata_nonexistent(self, nav):
        meta = nav.get_topic_metadata("nonexistent")
        assert meta is None


# ═══════════════════════════════════════════════════════════
# Part 3: check_prereq_gaps — pure DB, zero LLM
# ═══════════════════════════════════════════════════════════

class TestPrereqGaps:
    """check_prereq_gaps: pure DB query, no LLM dependency."""

    def test_no_gaps_when_all_prereqs_mastered(self, nav):
        """Alice: maths-numbers-01 is Achieved → no gap."""
        gaps = nav.check_prereq_gaps("student-alice", "maths-fractions-01")
        assert gaps == []

    def test_gap_when_prereq_not_yet(self, nav):
        """Bob: english-phonics-01 is Not Yet → gap."""
        gaps = nav.check_prereq_gaps("student-bob", "english-grammar-03")
        assert len(gaps) == 1
        assert gaps[0]["topic_id"] == "english-phonics-01"
        assert gaps[0]["gap_reason"] == "not_mastered"

    def test_gap_when_prereq_developing(self, nav):
        """Alice: science-matter-01 is Developing → gap."""
        gaps = nav.check_prereq_gaps("student-alice", "science-energy-02")
        assert len(gaps) == 1
        assert gaps[0]["topic_id"] == "science-matter-01"
        assert gaps[0]["gap_reason"] == "not_mastered"

    def test_gap_when_no_record(self, nav):
        """Bob has no record for maths-numbers-01 → gap."""
        gaps = nav.check_prereq_gaps("student-bob", "maths-fractions-01")
        assert len(gaps) == 1
        assert gaps[0]["topic_id"] == "maths-numbers-01"
        assert gaps[0]["gap_reason"] == "no_record"

    def test_no_gaps_when_exemplary(self, nav):
        """Bob: science-matter-01 is Exemplary → no gap."""
        gaps = nav.check_prereq_gaps("student-bob", "science-energy-02")
        assert gaps == []

    def test_empty_prerequisites_returns_empty(self, nav):
        gaps = nav.check_prereq_gaps("student-alice", "maths-numbers-01")
        assert gaps == []

    def test_nonexistent_topic_returns_empty(self, nav):
        gaps = nav.check_prereq_gaps("student-alice", "nonexistent")
        assert gaps == []

    def test_gap_dict_structure(self, nav):
        """Verify all fields are present in gap dict."""
        gaps = nav.check_prereq_gaps("student-alice", "science-energy-02")
        g = gaps[0]
        assert "topic_id" in g
        assert "last_label" in g
        assert "mastery_pct" in g
        assert "attempt_count" in g
        assert "gap_reason" in g

    def test_multiple_gaps(self, nav, db_path):
        """A topic with 2 prereqs where both are gaps for a student."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO topic_metadata "
                "(topic_id, subject, grade_level, prerequisites, kb_list) "
                "VALUES (?,?,?,?,?)",
                (
                    "multi-prereq-01", "Science", "P4-P6",
                    json.dumps(["science-matter-01", "maths-fractions-01"]),
                    json.dumps(["dreamer-coding-python"]),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        # Alice has science-matter-01=Developing (gap) and
        # maths-fractions-01 has no snapshot for Alice (gap).
        gaps = nav.check_prereq_gaps("student-alice", "multi-prereq-01")
        assert len(gaps) == 2
        gap_ids = {g["topic_id"] for g in gaps}
        assert gap_ids == {"science-matter-01", "maths-fractions-01"}

    def test_gap_with_lowercase_snake_case_label(self, nav, db_path):
        """Real DB format: 'developing' (snake_case) must trigger gap.
        This test guards against silent format drift between
        assessment_agent (snake_case) and the old Title Case hardcode."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO progress_snapshots "
                "(student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("student-lowercase", "maths-multiplication-02",
                 0.50, 1, "developing", 0, "2025-01-01T00:00:00Z"),
            )
            # topic with prereq = maths-multiplication-02
            conn.execute(
                "INSERT OR REPLACE INTO topic_metadata "
                "(topic_id, subject, grade_level, prerequisites, kb_list) "
                "VALUES (?,?,?,?,?)",
                ("maths-division-01", "maths", "P4-P6",
                 json.dumps(["maths-multiplication-02"]),
                 json.dumps(["dreamer-maths-ai"])),
            )
            conn.commit()
        finally:
            conn.close()
        gaps = nav.check_prereq_gaps("student-lowercase", "maths-division-01")
        assert len(gaps) == 1
        assert gaps[0]["topic_id"] == "maths-multiplication-02"
        assert gaps[0]["gap_reason"] == "not_mastered"

    def test_gap_with_null_label(self, nav, db_path):
        """NULL last_label (unassessed row) → treated as not_mastered gap."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO topic_metadata "
                "(topic_id, subject, grade_level, prerequisites, kb_list) "
                "VALUES (?,?,?,?,?)",
                ("maths-division-01", "maths", "P4-P6",
                 json.dumps(["maths-multiplication-02"]),
                 json.dumps(["dreamer-maths-ai"])),
            )
            conn.execute(
                "INSERT OR REPLACE INTO progress_snapshots "
                "(student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("student-null", "maths-multiplication-02",
                 0.30, 1, None, 0, "2025-01-01T00:00:00Z"),
            )
            conn.commit()
        finally:
            conn.close()
        gaps = nav.check_prereq_gaps("student-null", "maths-division-01")
        assert len(gaps) == 1
        assert gaps[0]["topic_id"] == "maths-multiplication-02"
        assert gaps[0]["gap_reason"] == "not_mastered"


# ═══════════════════════════════════════════════════════════
# Part 4: validate_age_band
# ═══════════════════════════════════════════════════════════

class TestAgeBandValidation:
    def test_valid_p1_p3(self):
        assert validate_age_band("P1-P3") == "P1-P3"

    def test_valid_p4_p6(self):
        assert validate_age_band("P4-P6") == "P4-P6"

    def test_valid_s1_s3(self):
        assert validate_age_band("S1-S3") == "S1-S3"

    def test_invalid_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid age_band"):
            validate_age_band("")

    def test_invalid_random_raises(self):
        with pytest.raises(ValueError, match="Invalid age_band"):
            validate_age_band("P7")

    def test_invalid_lowercase_raises(self):
        with pytest.raises(ValueError, match="Invalid age_band"):
            validate_age_band("p1-p3")


# ═══════════════════════════════════════════════════════════
# Part 5: DB auto-bootstrap (topic_metadata table creation)
# ═══════════════════════════════════════════════════════════

class TestBootstrap:
    """Ensure _ensure_db creates topic_metadata on first use."""

    def test_ensure_db_creates_table(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        nav = CurriculumNavigator(db_path=db)
        # First call triggers _ensure_db
        pre = nav.get_prerequisites("anything")
        assert pre == []
        # Verify table exists
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='topic_metadata'"
            ).fetchone()
            assert row is not None
        finally:
            conn.close()
