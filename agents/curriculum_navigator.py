"""
Dreamer AI Phase 4 Day 20 — Curriculum Navigator

Pure DB module: zero LLM dependency.
Reads topic_metadata to resolve prerequisites, KB lists, and prerequisite gaps.
Uses the same SQLite DB as assessment_agent (dreamer.db).

DB tables owned:
  - topic_metadata: topic prerequisites + kb_list mapping
Other tables read:
  - progress_snapshots: for check_prereq_gaps (created by assessment_agent)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────

VALID_AGE_BANDS = frozenset({"P1-P3", "P4-P6", "S1-S3"})

ETHICAL_AI_KB = "dreamer-ethical-ai"
# FILTER_IN_DIRECT is empty: psd / life_skills have no
# manifest counterpart (spec §1 naming unification), so DIRECT mode no
# longer filters any KB.
FILTER_IN_DIRECT: frozenset[str] = frozenset()

DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)
DB_PATH = os.path.abspath(DB_PATH)


# ── Helper utils (public for testing) ──────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    """Return a new SQLite connection with WAL mode."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    # Allow Navigator to read tables created by assessment_agent
    conn.execute("PRAGMA read_uncommitted=1")
    return conn


def _json_list(raw: str) -> List[str]:
    """Parse a JSON array string into a list of strings.
    Returns empty list on parse failure.
    """
    if not raw or raw == "[]":
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item) for item in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _query_one(
    db_path: str, sql: str, params: tuple
) -> Optional[tuple]:
    """Execute a SELECT returning at most one row."""
    conn = _connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


# ── Age Band Validation ────────────────────────────────

def validate_age_band(age_band: str) -> str:
    """Validate age_band; raise ValueError with clear message if invalid.

    Only three values are valid: P1-P3 / P4-P6 / S1-S3.
    Fail-fast design: wrong band = wrong kid-safe tone, must not silently default.
    """
    if age_band not in VALID_AGE_BANDS:
        raise ValueError(
            f"Invalid age_band '{age_band}'. Must be one of: "
            f"P1-P3, P4-P6, S1-S3"
        )
    return age_band


# ══════════════════════════════════════════════════════════
# CurriculumNavigator
# ══════════════════════════════════════════════════════════

class CurriculumNavigator:
    """Pure DB operations for curriculum navigation.

    Responsibilities:
      - get_prerequisites(topic_id) → List[str]
      - get_topic_metadata(topic_id) → Optional[dict]
      - resolve_kb_list(mode, topic_id) → List[str]  (with KB rules)
      - check_prereq_gaps(student_id, topic_id) → List[dict]

    Design constraints:
      - Zero LLM dependency. All methods are pure SQLite reads.
      - Injected db_path for testability (in-memory or temp file).
      - Auto-bootstraps topic_metadata table on first access.
    """

    _db_ensured = False
    _ensured_path: Optional[str] = None

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or DB_PATH

    # ── DB bootstrap ─────────────────────────────────

    @classmethod
    def _ensure_db(cls, target_path: str) -> None:
        """Create topic_metadata table if not exist."""
        if cls._db_ensured and cls._ensured_path == target_path:
            return
        conn = _connect(target_path)
        try:
            conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS topic_metadata (
                    topic_id        TEXT PRIMARY KEY,
                    subject         TEXT NOT NULL,
                    grade_level     TEXT NOT NULL,
                    prerequisites   TEXT NOT NULL DEFAULT '[]',
                    kb_list         TEXT NOT NULL DEFAULT '[]',
                    created_at      TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_topic_grade
                    ON topic_metadata(grade_level);
            """)
            conn.commit()
        finally:
            conn.close()
        cls._db_ensured = True
        cls._ensured_path = target_path

    def _bootstrap(self) -> None:
        """Ensure DB tables exist before any read."""
        self._ensure_db(self._db_path)

    # ── Public API ───────────────────────────────────

    def get_prerequisites(self, topic_id: str) -> List[str]:
        """Return list of prerequisite topic_ids for a given topic.

        Returns empty list if topic not found or has no prerequisites.
        """
        self._bootstrap()
        row = _query_one(
            self._db_path,
            "SELECT prerequisites FROM topic_metadata WHERE topic_id=?",
            (topic_id,),
        )
        if row is None:
            return []
        return _json_list(row[0])

    def get_topic_metadata(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """Return full metadata dict for a topic, or None if not found.

        Returns dict keys: topic_id, subject, grade_level, prerequisites, kb_list, created_at.
        prerequisites and kb_list are parsed into Python lists.
        """
        self._bootstrap()
        row = _query_one(
            self._db_path,
            """SELECT topic_id, subject, grade_level, prerequisites, kb_list, created_at
               FROM topic_metadata WHERE topic_id=?""",
            (topic_id,),
        )
        if row is None:
            return None
        return {
            "topic_id": row[0],
            "subject": row[1],
            "grade_level": row[2],
            "prerequisites": _json_list(row[3]),
            "kb_list": _json_list(row[4]),
            "created_at": row[5],
        }

    def resolve_kb_list(self, mode: str, topic_id: str) -> List[str]:
        """Return KB list for a topic with mode-specific rules applied.

        Rules (apply in order):
          1. dreamer-ethical-ai is always appended if not already in the raw kb_list.
          2. DIRECT mode: no KB filters (FILTER_IN_DIRECT is empty post
             naming unification — psd/life_skills have no manifest counterpart).

        Args:
            mode: One of "DIRECT", "CONTEXTUAL", "HYBRID".
            topic_id: Topic to resolve KBs for.

        Returns:
            Ordered list of KB identifiers. Order: raw kb_list (minus
            filtered) + appended ethical-ai if not already present.
        """
        meta = self.get_topic_metadata(topic_id)
        raw_kbs: List[str] = meta["kb_list"] if meta else []

        kbs = list(raw_kbs)

        # Rule 1: ethical-ai always appended
        if ETHICAL_AI_KB not in kbs:
            kbs.append(ETHICAL_AI_KB)

        # Rule 2: DIRECT mode filters any KB in FILTER_IN_DIRECT (empty set
        # after naming unification — no manifest KBs are filtered).
        if mode == "DIRECT":
            kbs = [kb for kb in kbs if kb not in FILTER_IN_DIRECT]

        return kbs

    def check_prereq_gaps(
        self, student_id: str, topic_id: str
    ) -> List[Dict[str, Any]]:
        """Return list of prerequisite topics that are not yet mastered.

        A prerequisite is considered 'gapped' if:
          - No progress_snapshot record exists (no_record), OR
          - last_label is 'Not Yet' or 'Developing' (not_mastered)

        'Achieved' or 'Exemplary' prerequisites are NOT gapped.

        Pure DB query — zero LLM dependency. Reads progress_snapshots
        created by assessment_agent.

        Args:
            student_id: Student identifier.
            topic_id: Topic to check prerequisites for.

        Returns:
            List of gap dicts, each with: topic_id, last_label, mastery_pct,
            attempt_count, gap_reason. Empty list if all clear.
        """
        self._bootstrap()
        prereqs = self.get_prerequisites(topic_id)
        if not prereqs:
            return []

        gaps: List[Dict[str, Any]] = []
        conn = _connect(self._db_path)
        try:
            for pr in prereqs:
                row = conn.execute(
                    """SELECT last_label, mastery_pct, attempt_count
                       FROM progress_snapshots
                       WHERE student_id=? AND topic_id=?""",
                    (student_id, pr),
                ).fetchone()

                if row is None:
                    gaps.append({
                        "topic_id": pr,
                        "last_label": None,
                        "mastery_pct": 0.0,
                        "attempt_count": 0,
                        "gap_reason": "no_record",
                    })
                else:
                    label = (row[0] or "").lower().replace("_", " ").strip()
                    if label in ("not yet", "developing", ""):
                        gaps.append({
                            "topic_id": pr,
                            "last_label": row[0],
                            "mastery_pct": float(row[1]),
                            "attempt_count": int(row[2]),
                            "gap_reason": "not_mastered",
                        })
                # NULL label (no record of assessment) → also gapped (no_record above)
                # Achieved / Exemplary → not gapped
        finally:
            conn.close()

        return gaps
