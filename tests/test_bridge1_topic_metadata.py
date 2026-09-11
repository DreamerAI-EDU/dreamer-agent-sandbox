"""Bridge-1: single-source topic_metadata schema + export ↔ B21 seed wiring.

Covers the four things Bridge-1 promises (red line #10 — real artefacts, not a
mock-green):
  1. cross-phase ``dreamer_phase`` (wk03–07 = ["Design","Deliver"]) exports
     without ``TypeError: unhashable type: 'list'`` and stays a JSON array;
  2. one canonical schema: no phantom ``domain_agent_owner``, ``week`` present;
  3. a frontmatter key a document does not declare never erases the DB value
     (the seeded maths/computing prerequisite chains share topic_ids);
  4. ``seed_kb.py`` actually runs the export (the two pipelines are joined).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.curriculum_navigator import CurriculumNavigator  # noqa: E402
from pipeline import phase1_kb_export as export  # noqa: E402
from pipeline import topic_metadata_schema as schema  # noqa: E402

_SKILL_SPEC = importlib.util.spec_from_file_location(
    "seed_kb_bridge1", REPO_ROOT / "scripts" / "seed_kb.py"
)
seed_kb = importlib.util.module_from_spec(_SKILL_SPEC)
_SKILL_SPEC.loader.exec_module(seed_kb)


CROSS_PHASE_DOC = """---
topic_id: curriculum-wk03
subject: AI Literacy
topic: "Movie Creator"
dreamer_phase:
  - Design
  - Deliver
modes_allowed:
  - contextual
  - direct
  - hybrid
grade_level: P4-P6
kb_name: dreamer-curriculum
week: 3
ib_atl_skills:
  - communication-exchange
ethical_ai_tags:
  - copyright
---

# Week 3
"""

SINGLE_PHASE_DOC = """---
topic_id: maths-fractions-01
subject: maths
topic: "分數"
dreamer_phase: Dream
modes_allowed:
  - contextual
  - direct
grade_level: P4-P6
kb_name: dreamer-maths-ai
week: 9
odd_key: something
---

# Fractions
"""


def _write_kb(root: Path) -> Path:
    """Build a miniature KB tree (one cross-phase doc + one shared topic_id)."""
    (root / "dreamer-curriculum").mkdir(parents=True, exist_ok=True)
    (root / "dreamer-maths-ai").mkdir(parents=True, exist_ok=True)
    (root / "dreamer-curriculum" / "curriculum-wk03.md").write_text(
        CROSS_PHASE_DOC, encoding="utf-8"
    )
    (root / "dreamer-maths-ai" / "maths-fractions-01.md").write_text(
        SINGLE_PHASE_DOC, encoding="utf-8"
    )
    return root


def _legacy_db(path: Path) -> sqlite3.Connection:
    """Create the pre-Bridge-1 6-column table + a seeded prerequisite row."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE topic_metadata (
            topic_id      TEXT PRIMARY KEY,
            subject       TEXT NOT NULL,
            grade_level   TEXT NOT NULL,
            prerequisites TEXT NOT NULL DEFAULT '[]',
            kb_list       TEXT NOT NULL DEFAULT '[]',
            created_at    TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO topic_metadata (topic_id, subject, grade_level, "
        "prerequisites, kb_list, created_at) VALUES (?,?,?,?,?,?)",
        (
            "maths-fractions-01",
            "maths",
            "P4-P6",
            json.dumps(["maths-division-01", "maths-multiplication-02"]),
            json.dumps(["dreamer-maths", "dreamer-ethical-ai"]),
            "2026-01-01 00:00:00",
        ),
    )
    conn.commit()
    return conn


# ── 1. cross-phase export ────────────────────────────────────────────────

def test_cross_phase_dreamer_phase_exports_as_json_array(tmp_path):
    kb_root = _write_kb(tmp_path / "kb")
    db = tmp_path / "meta.db"

    report = export.export_kb(kb_root=str(kb_root), db_path=str(db))

    assert report["errors"] == [], report["errors"]
    assert report["indexed"] == 2
    conn = sqlite3.connect(str(db))
    try:
        phase, week = conn.execute(
            "SELECT dreamer_phase, week FROM topic_metadata WHERE topic_id=?",
            ("curriculum-wk03",),
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(phase) == ["Design", "Deliver"]
    assert week == 3


# ── 2. one canonical schema ─────────────────────────────────────────────

def test_schema_is_single_source_without_phantom_column(tmp_path):
    db = tmp_path / "meta.db"
    conn = export.init_sqlite_db(str(db))
    try:
        cols = schema.column_names(conn)
    finally:
        conn.close()

    assert set(schema.CANONICAL_COLUMNS) <= cols
    assert "week" in cols
    assert "domain_agent_owner" not in cols


# ── 3. frontmatter must not erase what it does not declare ──────────────

def test_export_preserves_prerequisites_it_does_not_declare(tmp_path):
    kb_root = _write_kb(tmp_path / "kb")
    db = tmp_path / "meta.db"
    _legacy_db(db).close()

    report = export.export_kb(kb_root=str(kb_root), db_path=str(db))

    assert report["errors"] == [], report["errors"]
    assert any("prerequisites" in p for p in report["preserved"]), report["preserved"]

    nav = CurriculumNavigator(db_path=str(db))
    assert nav.get_prerequisites("maths-fractions-01") == [
        "maths-division-01",
        "maths-multiplication-02",
    ]


def test_declared_frontmatter_key_still_wins(tmp_path):
    kb_root = _write_kb(tmp_path / "kb")
    db = tmp_path / "meta.db"
    _legacy_db(db).close()

    export.export_kb(kb_root=str(kb_root), db_path=str(db))

    conn = sqlite3.connect(str(db))
    try:
        kb_name, subject = conn.execute(
            "SELECT kb_name, subject FROM topic_metadata WHERE topic_id=?",
            ("maths-fractions-01",),
        ).fetchone()
    finally:
        conn.close()
    assert kb_name == "dreamer-maths-ai"
    assert subject == "maths"


# ── 4. navigator reads the canonical column ─────────────────────────────

def test_navigator_prefers_canonical_kb_name_over_legacy_kb_list(tmp_path):
    db = tmp_path / "meta.db"
    _legacy_db(db).close()
    conn = export.init_sqlite_db(str(db))
    try:
        conn.execute(
            "UPDATE topic_metadata SET kb_name=? WHERE topic_id=?",
            ("dreamer-maths-ai", "maths-fractions-01"),
        )
        conn.commit()
    finally:
        conn.close()

    nav = CurriculumNavigator(db_path=str(db))
    meta = nav.get_topic_metadata("maths-fractions-01")
    assert meta["kb_list"] == ["dreamer-maths-ai"]


def test_unmapped_frontmatter_key_is_reported(tmp_path):
    kb_root = _write_kb(tmp_path / "kb")
    report = export.export_kb(kb_root=str(kb_root), db_path=str(tmp_path / "m.db"))

    assert any("odd_key" in w for w in report["warnings"]), report["warnings"]


# ── 5. B21 seed ↔ export wiring ─────────────────────────────────────────

def test_seed_check_path_runs_export_dry_run_without_writing(tmp_path):
    db = tmp_path / "never_created.db"

    rc = seed_kb.index_topic_metadata(dry_run=True, db_path=str(db))

    assert rc == seed_kb.EXIT_OK
    assert not db.exists(), "dry-run must not create the DB"


def test_seed_check_path_sees_the_real_kb_sot():
    report = export.export_kb(kb_root=str(seed_kb.KB_SOT_DIR), dry_run=True)

    assert report["scanned"] == 19
    assert report["errors"] == [], report["errors"]
    assert report["skipped_no_frontmatter"] == 0


# ── 6. the legacy sample seeder must not wipe canonical columns ─────────

_SAMPLE_SPEC = importlib.util.spec_from_file_location(
    "seed_topic_metadata_bridge1", REPO_ROOT / "scripts" / "seed_topic_metadata.py"
)
seed_sample = importlib.util.module_from_spec(_SAMPLE_SPEC)
_SAMPLE_SPEC.loader.exec_module(seed_sample)


def test_legacy_sample_seeder_keeps_canonical_columns(tmp_path, monkeypatch):
    """Both pipes share topic_ids (maths-fractions-01). The sample seeder used
    INSERT OR REPLACE, which deletes the row first and would drop the canonical
    columns written by the KB export."""
    db = tmp_path / "meta.db"
    kb = _write_kb(tmp_path / "kb")
    export.export_kb(kb_root=str(kb), db_path=str(db))
    conn = sqlite3.connect(str(db))
    try:
        # linked_projects is a sentinel: neither the seeder nor these miniature
        # documents write it, so it stands for "columns the other pipe owns".
        conn.execute(
            "UPDATE topic_metadata SET linked_projects='[\"proj-x\"]' "
            "WHERE topic_id='maths-fractions-01'"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(seed_sample, "DB_PATH", str(db))
    seed_sample.main()
    # And the export afterwards must not erase the seeded chain either.
    export.export_kb(kb_root=str(kb), db_path=str(db))

    conn = sqlite3.connect(str(db))
    try:
        kb_name, doc_path, projects, prereqs = conn.execute(
            "SELECT kb_name, document_path, linked_projects, prerequisites "
            "FROM topic_metadata WHERE topic_id=?",
            ("maths-fractions-01",),
        ).fetchone()
    finally:
        conn.close()

    assert kb_name == "dreamer-maths-ai"
    assert doc_path
    assert json.loads(projects) == ["proj-x"]
    assert json.loads(prereqs) == ["maths-division-01", "maths-multiplication-02"]
