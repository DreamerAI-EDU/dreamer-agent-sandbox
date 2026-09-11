#!/usr/bin/env python3
"""Canonical ``topic_metadata`` schema — single source of truth (Bridge-1).

Background
----------
The ``topic_metadata`` SQLite index used to be defined in two half-aligned
places: ``pipeline/phase1_kb_export.py`` wrote a 12-field row while
``agents/curriculum_navigator.py`` auto-bootstrapped a 6-column table of its
own (the "兩套 schema" bug). Bridge-1 collapses both onto one definition:

    pipeline/phase1_sqlite_schema.sql   <- DDL source of truth
        read by this module (``load_schema_sql`` / ``ensure_schema``)

Canonical 12 fields (Hermes_Integration_Plan_v3 §4.2):
    topic_id, subject, topic, ai_literacy_context, modes_allowed,
    grade_level, prerequisites, linked_projects, dreamer_phase,
    ib_atl_skills, ethical_ai_tags, kb_name
plus source tracking / timestamps:
    document_path, document_hash, exported_at, last_modified
plus one additive curriculum column (Bridge-1, decision 4):
    week — the week ordinal (1..8) of a ``dreamer-curriculum/wkNN``
    document; nullable, so every non-curriculum row keeps NULL. Decision 4
    makes "Week X/8" the primary progress unit, so the value has to
    survive the export instead of being dropped as an unknown key.

Format rules
------------
- List-valued fields (``modes_allowed``, ``prerequisites``,
  ``linked_projects``, ``ib_atl_skills``, ``ethical_ai_tags``,
  ``dreamer_phase``) are stored as JSON arrays inside a single TEXT column.
  ``dreamer_phase`` is a JSON array too: wk03-wk07 are genuinely cross-phase
  (``["Design", "Deliver"]``) and must not be flattened to one string.
- ``domain_agent_owner`` is a phantom field (B21 spec §5): it must not exist
  in the canonical shape.

Legacy compatibility (readers)
------------------------------
Older DBs (and several tests) hold the 6-column bootstrap table
(``topic_id/subject/grade_level/prerequisites/kb_list/created_at``) and/or a
``domain_agent_owner`` snapshot column. ``ensure_schema`` never destroys
them — it only ADDs missing columns — and readers must keep honouring the
legacy ``kb_list`` / ``created_at`` columns when present
(see ``agents/curriculum_navigator.py``).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

# ── Paths ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).parent / "phase1_sqlite_schema.sql"
DEFAULT_DB_FILENAME = "dreamer.db"

# ── Canonical shape ──────────────────────────────────────────────────────
CANONICAL_FIELDS: tuple[str, ...] = (
    "topic_id",
    "subject",
    "topic",
    "ai_literacy_context",
    "modes_allowed",
    "grade_level",
    "prerequisites",
    "linked_projects",
    "dreamer_phase",
    "ib_atl_skills",
    "ethical_ai_tags",
    "kb_name",
)
SOURCE_FIELDS: tuple[str, ...] = (
    "document_path",
    "document_hash",
    "exported_at",
    "last_modified",
)
EXTENSION_FIELDS: tuple[str, ...] = ("week",)
CANONICAL_COLUMNS: tuple[str, ...] = (
    CANONICAL_FIELDS + SOURCE_FIELDS + EXTENSION_FIELDS
)

# Frontmatter keys the canonical shape consumes. Anything else found in a
# document's frontmatter is surfaced as a warning by the export / seed
# validators — never silently dropped.
KNOWN_FRONTMATTER_KEYS: frozenset[str] = (
    frozenset(CANONICAL_FIELDS) | frozenset(EXTENSION_FIELDS)
)

# Fields the export must never erase. ``topic_metadata`` has more than one
# writer (the temporary scripts/seed_topic_metadata.py sample rows still
# carry the maths / computing prerequisite chains), so a blind overwrite
# would null out edges the SoT document simply does not talk about.
# Rule: frontmatter wins when the key is declared; otherwise keep the DB
# value (and report it).
PRESERVE_IF_ABSENT: tuple[str, ...] = CANONICAL_FIELDS + EXTENSION_FIELDS

# Legacy-only columns: present in old DBs, never created by the canonical DDL.
LEGACY_KB_LIST_COLUMN = "kb_list"
LEGACY_CREATED_AT_COLUMN = "created_at"

# Phantom field — must never be written again (spec §5).
FORBIDDEN_COLUMNS: tuple[str, ...] = ("domain_agent_owner",)

# Column type used when migrating an old table (ALTER TABLE ADD COLUMN).
_ALTER_TYPES: dict[str, str] = {
    "topic_id": "TEXT",
    "subject": "TEXT",
    "topic": "TEXT",
    "ai_literacy_context": "TEXT",
    "modes_allowed": "TEXT",
    "grade_level": "TEXT",
    "prerequisites": "TEXT",
    "linked_projects": "TEXT",
    "dreamer_phase": "TEXT",
    "ib_atl_skills": "TEXT",
    "ethical_ai_tags": "TEXT",
    "kb_name": "TEXT",
    "document_path": "TEXT",
    "document_hash": "TEXT",
    "exported_at": "TIMESTAMP",
    "last_modified": "TIMESTAMP",
    "week": "INTEGER",
}

# Views are derived objects: recreating them is safe (no user data), and the
# old v_phase_curriculum definition (it grouped on the raw dreamer_phase text
# and exposed agent_list from the phantom column) must not survive.
MANAGED_VIEWS: tuple[str, ...] = (
    "v_phase_curriculum",
    "v_prerequisite_chain",
    "v_ethical_audit",
)

# ── Domain constants (shared by export + navigator + seed) ───────────────
VALID_DREAMER_PHASES: tuple[str, ...] = ("Dream", "Discover", "Design", "Deliver")
VALID_MODES: tuple[str, ...] = ("contextual", "direct", "hybrid")


# ── DB path resolution ───────────────────────────────────────────────────
def resolve_db_path(db_path: Optional[str] = None) -> Path:
    """Resolve the Hermes SQLite DB path.

    Precedence: explicit argument → ``DREAMER_DB_PATH`` env → repo-root
    ``dreamer.db``. Before Bridge-1 the export defaulted to ``./metadata.db``,
    a file no runtime component ever reads.
    """
    if db_path:
        return Path(db_path).expanduser()
    env = os.environ.get("DREAMER_DB_PATH")
    if env and env.strip():
        return Path(env.strip()).expanduser()
    return REPO_ROOT / DEFAULT_DB_FILENAME


# ── DDL loading / execution ──────────────────────────────────────────────
def load_schema_sql() -> str:
    """Return the DDL source of truth (``pipeline/phase1_sqlite_schema.sql``)."""
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _iter_statements(sql: str) -> list[str]:
    """Split the DDL file into statements, dropping ``--`` comment lines.

    Naive ``split(";")`` is unsafe here: the file's comments contain
    semicolons and parentheses (e.g. "use json_each() in queries").
    """
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


def column_names(conn: sqlite3.Connection, table: str = "topic_metadata") -> set[str]:
    """Return the set of existing column names of ``table`` (empty if absent)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create / migrate the canonical ``topic_metadata`` schema in place.

    Order matters: the table is created first, missing columns are added
    (legacy DBs), and only then are indexes + views applied — an index on a
    column that does not exist yet would abort the whole script.
    Managed views are dropped first so a stale definition cannot survive
    ``CREATE VIEW IF NOT EXISTS``.
    """
    statements = _iter_statements(load_schema_sql())
    table_stmts = [s for s in statements if s.upper().startswith("CREATE TABLE")]
    rest = [s for s in statements if s not in table_stmts]

    for stmt in table_stmts:
        conn.execute(stmt)

    missing = [col for col in CANONICAL_COLUMNS if col not in column_names(conn)]
    for col in missing:
        conn.execute(
            f"ALTER TABLE topic_metadata ADD COLUMN {col} {_ALTER_TYPES[col]}"
        )

    for view in MANAGED_VIEWS:
        conn.execute(f"DROP VIEW IF EXISTS {view}")
    for stmt in rest:
        conn.execute(stmt)

    conn.commit()


# ── Value normalisation ──────────────────────────────────────────────────
def split_list_value(value: Any) -> list[str]:
    """Normalise a frontmatter value into a plain ``list[str]``.

    Accepts: ``list`` (as parsed from YAML block/flow lists), JSON array
    string, or comma-separated scalar. Empty / missing → ``[]``.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            import json

            parsed = json.loads(text)
        except Exception:  # noqa: BLE001 - fall back to comma split
            parsed = text.strip("[]").split(",")
        return split_list_value(parsed)
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_modes(value: Any) -> list[str]:
    """Return lowercase, de-duplicated modes (order preserved)."""
    out: list[str] = []
    for mode in split_list_value(value):
        mode = mode.lower()
        if mode not in out:
            out.append(mode)
    return out


def normalize_phases(value: Any) -> list[str]:
    """Return the Dreamer 4D phases carried by a document, order preserved.

    Cross-phase documents keep every phase (wk03 = ``["Design", "Deliver"]``).
    Unknown values are dropped by the caller after validation warns on them;
    this function keeps only valid phases.
    """
    out: list[str] = []
    for phase in split_list_value(value):
        if phase in VALID_DREAMER_PHASES and phase not in out:
            out.append(phase)
    return out


def coerce_week(value: Any) -> Optional[int]:
    """Return the curriculum week ordinal as an int, else ``None``.

    ``week`` is authored as a YAML scalar (``week: 3``) and therefore
    arrives as the string ``"3"``; invalid / absent values become NULL
    rather than aborting the whole export.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def is_declared(meta: dict, key: str) -> bool:
    """True when the document's frontmatter declares a non-empty ``key``."""
    if key not in meta:
        return False
    value = meta[key]
    if isinstance(value, (list, tuple, set)):
        return any(str(v).strip() for v in value)
    return bool(str(value).strip())


def unknown_frontmatter_keys(meta: dict) -> list[str]:
    """Frontmatter keys that no canonical / extension column consumes."""
    return sorted(k for k in meta if k not in KNOWN_FRONTMATTER_KEYS)
