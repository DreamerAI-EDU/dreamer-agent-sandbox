#!/usr/bin/env python3
"""Temporary seed script for topic_metadata — to be replaced by KB export script.

Phase 4 Day 20: populates topic_metadata with 5 sample topics
covering maths/computing chains needed for Day 21 trial_routing.py
four cases (DIRECT / CONTEXTUAL / HYBRID / en-override).

Idempotent: upserts on topic_id, and never clobbers the columns owned by the
KB export (``pipeline/phase1_kb_export.py``) — the two pipes can run in any
order (Bridge-1).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline import topic_metadata_schema as metadata_schema  # noqa: E402

DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)


TOPICS = [
    # ── maths chain (3 topics, linear prereqs) ────────────────────
    {
        "topic_id": "maths-multiplication-02",
        "subject": "maths",
        "grade_level": "P4-P6",
        "prerequisites": [],
        "kb_list": ["dreamer-maths"],
    },
    {
        "topic_id": "maths-division-01",
        "subject": "maths",
        "grade_level": "P4-P6",
        "prerequisites": ["maths-multiplication-02"],
        "kb_list": ["dreamer-maths"],
    },
    {
        "topic_id": "maths-fractions-01",
        "subject": "maths",
        "grade_level": "P4-P6",
        "prerequisites": ["maths-division-01", "maths-multiplication-02"],
        "kb_list": ["dreamer-maths"],
    },
    # ── computing chain (2 topics, psd/life_skills in kb_list for filter test) ──
    {
        "topic_id": "computing-scratch-basics-01",
        "subject": "computing",
        "grade_level": "P1-P3",
        "prerequisites": [],
        "kb_list": ["dreamer-computing"],
    },
    {
        "topic_id": "computing-game-design-01",
        "subject": "computing",
        "grade_level": "P4-P6",
        "prerequisites": ["computing-scratch-basics-01"],
        "kb_list": ["dreamer-computing", "dreamer-psd", "dreamer-life_skills"],
    },
]


def _build_row(t: dict, use_kb_name: bool) -> dict:
    """Map a sample topic onto the canonical topic_metadata columns.

    Sample rows are not KB documents, so the source-tracking columns get
    placeholders — a real ``phase1_kb_export.py`` run overwrites them (its
    frontmatter declares document_path / document_hash) and this seeder never
    touches them again afterwards. The legacy ``kb_list`` column only exists
    in old DBs; the canonical ``kb_name`` is written when it is available.
    """
    row = {
        "topic_id": t["topic_id"],
        "subject": t["subject"],
        "grade_level": t["grade_level"],
        "topic": t.get("topic") or t["topic_id"],
        "modes_allowed": json.dumps(
            t.get("modes_allowed") or list(metadata_schema.VALID_MODES)
        ),
        "dreamer_phase": json.dumps(
            t.get("dreamer_phase") or list(metadata_schema.VALID_DREAMER_PHASES)
        ),
        "prerequisites": json.dumps(t["prerequisites"]),
        "document_path": "",
        "document_hash": "",
    }
    if use_kb_name:
        row["kb_name"] = (t["kb_list"] or [""])[0]
    else:
        row["kb_list"] = json.dumps(t["kb_list"])
    return row


# Columns this seeder owns: it may overwrite them on conflict. Everything else
# — the KB binding (kb_name / kb_list) and the source tracking (document_path /
# document_hash / week / exported_at / …) — belongs to the KB export: written
# on insert only, never clobbered. That is the Bridge-1 two-pipes contract.
_OWNED_ON_CONFLICT = (
    "subject",
    "grade_level",
    "topic",
    "modes_allowed",
    "dreamer_phase",
    "prerequisites",
)


def main() -> None:
    abs_path = os.path.abspath(DB_PATH)
    print(f"Seeding topic_metadata → {abs_path}")

    conn = sqlite3.connect(abs_path)
    try:
        # Bridge-1: go through the single canonical schema definition instead
        # of bootstrapping a private 6-column table. On a legacy DB this only
        # ADDs the missing canonical columns; nothing is destroyed.
        metadata_schema.ensure_schema(conn)
        use_kb_name = "kb_name" in metadata_schema.column_names(conn)

        for t in TOPICS:
            row = _build_row(t, use_kb_name)
            cols_sql = ", ".join(row)
            placeholders = ", ".join("?" for _ in row)
            updates = ", ".join(
                f"{c} = excluded.{c}" for c in row if c in _OWNED_ON_CONFLICT
            )
            # Upsert rather than INSERT OR REPLACE: REPLACE deletes the row
            # first, which would drop the canonical columns the KB export had
            # written for the shared topic_ids (e.g. maths-fractions-01).
            conn.execute(
                f"""INSERT INTO topic_metadata ({cols_sql})
                    VALUES ({placeholders})
                    ON CONFLICT(topic_id) DO UPDATE SET {updates}""",
                list(row.values()),
            )
        conn.commit()

        cnt = conn.execute("SELECT COUNT(*) FROM topic_metadata").fetchone()[0]
        print(f"Done. topic_metadata row count: {cnt}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
