#!/usr/bin/env python3
"""Temporary seed script for topic_metadata — to be replaced by KB export script.

Phase 4 Day 20: populates topic_metadata with 5 sample topics
covering maths/computing chains needed for Day 21 trial_routing.py
four cases (DIRECT / CONTEXTUAL / HYBRID / en-override).

Idempotent: uses INSERT OR REPLACE, safe to re-run.
"""

from __future__ import annotations

import json
import os
import sqlite3

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


def main() -> None:
    abs_path = os.path.abspath(DB_PATH)
    print(f"Seeding topic_metadata → {abs_path}")

    conn = sqlite3.connect(abs_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS topic_metadata (
                topic_id      TEXT PRIMARY KEY,
                subject       TEXT NOT NULL,
                grade_level   TEXT NOT NULL,
                prerequisites TEXT NOT NULL DEFAULT '[]',
                kb_list       TEXT NOT NULL DEFAULT '[]',
                created_at    TEXT NOT NULL DEFAULT ''
            );
        """)
        for t in TOPICS:
            conn.execute(
                """INSERT OR REPLACE INTO topic_metadata
                   (topic_id, subject, grade_level, prerequisites, kb_list)
                   VALUES (?,?,?,?,?)""",
                (
                    t["topic_id"],
                    t["subject"],
                    t["grade_level"],
                    json.dumps(t["prerequisites"]),
                    json.dumps(t["kb_list"]),
                ),
            )
        conn.commit()

        cnt = conn.execute("SELECT COUNT(*) FROM topic_metadata").fetchone()[0]
        print(f"Done. topic_metadata row count: {cnt}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
