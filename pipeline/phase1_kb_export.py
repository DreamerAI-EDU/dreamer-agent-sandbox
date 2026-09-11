#!/usr/bin/env python3
"""
Phase 1 — KB Export Script
Exports DeepTutor knowledge base documents to Hermes-compatible format,
extracting YAML frontmatter and populating the SQLite metadata index.

Usage:
    python -m pipeline.phase1_kb_export --kb-root ./knowledge_bases
    python -m pipeline.phase1_kb_export --kb-root ./knowledge_bases --db dreamer.db

Bridge-1 (2026-09) changes
-------------------------
1. ``dreamer_phase`` is normalised to a LIST (a cross-phase doc such as wk03
   which carries ``[Design, Deliver]`` keeps BOTH phases) and is validated
   with a set check instead of ``phase not in {..}`` — the old code raised
   ``TypeError: unhashable type: 'list'`` on any multi-phase document.
2. The output schema is the canonical 12-field shape owned by
   ``pipeline/topic_metadata_schema.py`` (same DDL the Curriculum Navigator
   uses) — no half-aligned private copy. ``domain_agent_owner`` is gone
   (phantom field, B21 spec §5).
3. ``--db`` defaults to the real Hermes DB (``$DREAMER_DB_PATH`` or the
   repo-root ``dreamer.db``), not the orphan ``./metadata.db``.
4. ``week`` (frontmatter) is carried into the new ``week`` column and is
   the progress unit of decision 4. A frontmatter key a document does NOT
   declare no longer erases the DB value (see ``upsert_topic_metadata``):
   the seeded maths / computing prerequisite chains share topic_ids with KB
   documents (``maths-fractions-01``) and would otherwise be nulled out by
   the first sync.

Architecture:
    DeepTutor KB (Markdown + YAML frontmatter)
        → parse frontmatter
        → validate dreamer_phase & ib_atl_skills
        → write to Hermes KB directory
        → index into SQLite topic_metadata
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _load_schema_module():
    """Import the canonical schema module (package or script context)."""
    try:
        from pipeline import topic_metadata_schema as mod  # type: ignore
    except ImportError:  # executed as a bare script
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import topic_metadata_schema as mod  # type: ignore
    return mod


_SCHEMA = _load_schema_module()

# =============================================================================
# Dreamer 4D phase validation (teaching mainline — must be one of these four)
# =============================================================================
VALID_DREAMER_PHASES = set(_SCHEMA.VALID_DREAMER_PHASES)

# IB ATL skills (cross-reference only — internal; school alignment conversation)
# These are NOT the pedagogical spine; dreamer_phase is.
KNOWN_IB_ATL_SKILLS = {
    "thinking-inquiry", "thinking-critical", "thinking-creative",
    "thinking-transfer", "thinking-reflection",
    "research-information-literacy", "research-media-literacy",
    "communication-exchange", "communication-representation",
    "social-collaboration", "self-management-organization",
    "self-management-affective", "self-management-reflection",
}

VALID_MODES = set(_SCHEMA.VALID_MODES)

# Phantom field(s) that must never be written back (B21 spec §5).
FORBIDDEN_FIELDS = set(_SCHEMA.FORBIDDEN_COLUMNS)

# Re-exported helpers so callers (seed_kb.py) can reuse them.
split_list_value = _SCHEMA.split_list_value
normalize_phases = _SCHEMA.normalize_phases
normalize_modes = _SCHEMA.normalize_modes
resolve_db_path = _SCHEMA.resolve_db_path
ensure_schema = _SCHEMA.ensure_schema


# =============================================================================
# AIGC Watermark Stripper
# =============================================================================
AIGC_BLOCK_RE = re.compile(r'^---\s*\nAIGC:.*?\n---\s*\n', re.DOTALL)
AIGC_FOOTER_RE = re.compile(r'\n\*?（内容由AI生成，仅供参考）\*?\s*$')


def strip_aigc_watermark(content: str) -> str:
    """Strip AIGC watermark frontmatter block and footer from Markdown content.

    Handles both forms:
      - Leading ``--- AIGC: ... ---`` block injected by some write tools
      - Trailing ``（内容由AI生成，仅供参考）`` footer line

    Returns clean content ready for YAML frontmatter parsing.
    """
    content = AIGC_BLOCK_RE.sub('', content, count=1)
    content = AIGC_FOOTER_RE.sub('', content, count=1)
    return content


# =============================================================================
# YAML Frontmatter Parser
# =============================================================================
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def strip_inline_comment(value: str) -> str:
    """Strip YAML inline # comment from a value, keeping quoted # intact."""
    idx = value.find("#")
    if idx >= 0:
        return value[:idx].rstrip()
    return value


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from a Markdown document.
    Uses a minimal YAML parser for the subset of fields we need.
    Handles inline # comments in scalar values.
    """
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}

    raw = match.group(1)
    meta = {}

    # Simple line-by-line parser for flat keys and list items
    current_key = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under current key
        if stripped.startswith("- "):
            value = stripped[2:].strip().strip('"').strip("'")
            value = strip_inline_comment(value)
            if current_key is not None:
                if current_key not in meta:
                    meta[current_key] = []
                meta[current_key].append(value)
            continue

        # Key: value
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            value = strip_inline_comment(value)
            if value == "":
                current_key = key
                continue
            current_key = key
            meta[key] = value

    return meta


def validate_frontmatter(meta: dict, filepath: str) -> list[str]:
    """Validate frontmatter against Dreamer 4D requirements.
    Returns list of warnings (empty = all good).
    """
    warnings = []

    # Required fields
    required = ["topic_id", "subject", "topic", "dreamer_phase",
                 "modes_allowed", "grade_level", "kb_name"]
    for field in required:
        if field not in meta:
            warnings.append(f"[{filepath}] Missing required field: '{field}'")

    # Phantom field guard (B21 spec §5)
    phantom = sorted(set(meta) & FORBIDDEN_FIELDS)
    if phantom:
        warnings.append(
            f"[{filepath}] Phantom field(s) {phantom} present — not part of the "
            f"canonical schema; ignored (B21 spec §5)"
        )

    # dreamer_phase validation (PRIMARY AXIS)
    # A document may legitimately span phases (wk03 = [Design, Deliver]):
    # normalise to a list first, then set-check — never hash the raw value.
    phases = split_list_value(meta.get("dreamer_phase"))
    invalid_phases = [p for p in phases if p not in VALID_DREAMER_PHASES]
    if invalid_phases:
        warnings.append(
            f"[{filepath}] Invalid dreamer_phase {invalid_phases}. "
            f"Must be one of: {', '.join(sorted(VALID_DREAMER_PHASES))}"
        )

    # ib_atl_skills validation (cross-reference only)
    unknown = set(split_list_value(meta.get("ib_atl_skills"))) - KNOWN_IB_ATL_SKILLS
    if unknown:
        warnings.append(
            f"[{filepath}] Unknown ib_atl_skills: {sorted(unknown)}. "
            f"Known values: {', '.join(sorted(KNOWN_IB_ATL_SKILLS))}"
        )

    # modes_allowed validation
    invalid_modes = set(normalize_modes(meta.get("modes_allowed"))) - VALID_MODES
    if invalid_modes:
        warnings.append(
            f"[{filepath}] Invalid modes: {sorted(invalid_modes)}. "
            f"Must be subset of: {', '.join(sorted(VALID_MODES))}"
        )

    # Unmapped frontmatter keys: no column consumes them → they would be
    # dropped silently. Report (never guess): extend the canonical schema
    # in pipeline/topic_metadata_schema.py if the key matters.
    unmapped = _SCHEMA.unknown_frontmatter_keys(meta)
    if unmapped:
        warnings.append(
            f"[{filepath}] Frontmatter key(s) {unmapped} are not consumed by "
            f"any topic_metadata column — dropped (extend the canonical "
            f"schema if they must be indexed)"
        )

    return warnings


def extract_body(content: str) -> str:
    """Remove YAML frontmatter and return the document body."""
    match = FRONTMATTER_RE.match(content)
    if match:
        return content[match.end():]
    return content


def compute_hash(content: str) -> str:
    """SHA256 hash of document content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# =============================================================================
# SQLite Index Operations
# =============================================================================
def init_sqlite_db(db_path: str):
    """Initialize the SQLite metadata database with the canonical schema.

    Bridge-1: delegates to ``topic_metadata_schema.ensure_schema`` so the
    export and the Curriculum Navigator can never drift apart again.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    ensure_schema(conn)

    conn.commit()
    return conn


def _to_json_list(value) -> str:
    """Serialise a list-valued frontmatter field to a JSON array string."""
    return json.dumps(split_list_value(value), ensure_ascii=False)


def _existing_row(conn: sqlite3.Connection, topic_id: str) -> dict:
    """Return the current row for ``topic_id`` as a dict (empty if absent)."""
    cur = conn.execute(
        "SELECT * FROM topic_metadata WHERE topic_id = ?", (topic_id,)
    )
    row = cur.fetchone()
    if row is None:
        return {}
    return {desc[0]: value for desc, value in zip(cur.description, row)}


def upsert_topic_metadata(conn: sqlite3.Connection, meta: dict, body_hash: str,
                          doc_path: str) -> list:
    """Insert or update a topic metadata row (canonical 12-field shape).

    Bridge-1 preserve rule: a frontmatter key the document does NOT declare
    never erases the value already in the DB. ``topic_metadata`` has more
    than one writer — the temporary ``scripts/seed_topic_metadata.py``
    sample rows carry the maths / computing prerequisite chains — and a
    blind ``excluded.*`` overwrite dropped those edges as soon as a KB
    document shared the topic_id (``maths-fractions-01``). Declared keys
    always win over the stored value.

    Returns the list of column names whose DB value was preserved.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    topic_id = meta.get("topic_id", "")

    values = {
        "topic_id": topic_id,
        "subject": meta.get("subject", ""),
        "topic": meta.get("topic", ""),
        "ai_literacy_context": meta.get("ai_literacy_context", ""),
        "modes_allowed": _to_json_list(meta.get("modes_allowed", [])),
        "grade_level": meta.get("grade_level", ""),
        "week": _SCHEMA.coerce_week(meta.get("week")),
        "prerequisites": _to_json_list(meta.get("prerequisites", [])),
        "linked_projects": _to_json_list(meta.get("linked_projects", [])),
        "dreamer_phase": json.dumps(
            normalize_phases(meta.get("dreamer_phase")), ensure_ascii=False
        ),
        "ib_atl_skills": _to_json_list(meta.get("ib_atl_skills", [])),
        "ethical_ai_tags": _to_json_list(meta.get("ethical_ai_tags", [])),
        "kb_name": meta.get("kb_name", ""),
        "document_path": doc_path,
        "document_hash": body_hash,
        "exported_at": now,
        "last_modified": now,
    }

    existing = _existing_row(conn, topic_id)
    preserved: list = []
    for col in _SCHEMA.PRESERVE_IF_ABSENT:
        if _SCHEMA.is_declared(meta, col):
            continue
        old_value = existing.get(col)
        if old_value in (None, "", "[]"):
            continue
        values[col] = old_value
        preserved.append(col)

    cols = list(values)
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(
        f"{col} = excluded.{col}" for col in cols if col != "topic_id"
    )
    conn.execute(
        f"INSERT INTO topic_metadata ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(topic_id) DO UPDATE SET {updates}",
        tuple(values[col] for col in cols),
    )
    return preserved


# =============================================================================
# Main Export Pipeline
# =============================================================================
def export_kb(kb_root: str, db_path: Optional[str] = None,
              output_dir: Optional[str] = None, dry_run: bool = False,
              kb_names: Optional[list] = None, prune_stale: bool = False):
    """Main export pipeline: walk KB directories, parse, validate, index.

    Returns a report dict:
        scanned / indexed / skipped_no_frontmatter / stored_paths
        warnings / errors / per_kb / pruned / db_path

    Raises ValueError if ``kb_root`` does not exist (the CLI maps it to exit 1).
    """
    kb_root = Path(kb_root)
    if not kb_root.is_dir():
        raise ValueError(f"KB root not found: {kb_root}")

    db_path = resolve_db_path(db_path)
    selected = set(kb_names) if kb_names else None

    report = {
        "scanned": 0,
        "indexed": 0,
        "skipped_no_frontmatter": 0,
        "stored_paths": set(),
        "warnings": [],
        "errors": [],
        "per_kb": {},
        "preserved": [],
        "pruned": [],
        "db_path": str(db_path),
    }

    conn = None if dry_run else init_sqlite_db(str(db_path))

    try:
        for md_file in sorted(kb_root.rglob("*.md")):
            rel_path = md_file.relative_to(kb_root)
            # document_path is stored POSIX-style: the same string must resolve
            # on a Windows dev box and inside the Linux container.
            doc_path = rel_path.as_posix()
            dir_kb_name = rel_path.parts[0] if len(rel_path.parts) > 1 else ""

            if selected is not None and dir_kb_name not in selected:
                continue

            report["scanned"] += 1

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                report["errors"].append(f"[{doc_path}] Read error: {e}")
                continue

            content = strip_aigc_watermark(content)

            meta = parse_frontmatter(content)
            if not meta:
                report["warnings"].append(
                    f"[{doc_path}] No YAML frontmatter found. Skipping index."
                )
                report["skipped_no_frontmatter"] += 1
                continue

            report["warnings"].extend(validate_frontmatter(meta, doc_path))

            body = extract_body(content)
            body_hash = compute_hash(content)

            if output_dir and not dry_run:
                out_path = Path(output_dir) / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(body, encoding="utf-8")

            if dry_run:
                continue

            # PK must never be empty — an empty topic_id would silently merge
            # every malformed document into one row.
            if not meta.get("topic_id"):
                report["errors"].append(
                    f"[{doc_path}] Missing topic_id — NOT indexed"
                )
                continue

            fm_kb_name = meta.get("kb_name") or ""
            if fm_kb_name and dir_kb_name and fm_kb_name != dir_kb_name:
                report["warnings"].append(
                    f"[{doc_path}] kb_name '{fm_kb_name}' != directory "
                    f"'{dir_kb_name}' — keeping frontmatter value"
                )
            preserved = upsert_topic_metadata(conn, meta, body_hash, doc_path)
            if preserved:
                report["preserved"].append(
                    f"{meta.get('topic_id')}: kept {'/'.join(preserved)} "
                    f"(frontmatter does not declare them)"
                )

            report["indexed"] += 1
            report["stored_paths"].add(doc_path)
            bucket = report["per_kb"].setdefault(
                fm_kb_name or dir_kb_name, {"docs": 0, "phases": {}}
            )
            bucket["docs"] += 1
            for phase in normalize_phases(meta.get("dreamer_phase")):
                bucket["phases"][phase] = bucket["phases"].get(phase, 0) + 1

        if conn is not None and prune_stale:
            for topic_id, old_path in conn.execute(
                "SELECT topic_id, document_path FROM topic_metadata"
            ).fetchall():
                if old_path not in report["stored_paths"]:
                    conn.execute(
                        "DELETE FROM topic_metadata WHERE topic_id = ?", (topic_id,)
                    )
                    report["pruned"].append(old_path)

        if conn is not None:
            conn.commit()
            report["row_count"] = conn.execute(
                "SELECT COUNT(*) FROM topic_metadata"
            ).fetchone()[0]
    finally:
        if conn is not None:
            conn.close()

    return report


def format_report(report: dict, dry_run: bool = False) -> str:
    """Human-readable export summary (kept stable for seed_kb.py)."""
    lines = []
    if dry_run:
        lines.append(f"\nDry run complete. {report['scanned']} documents scanned.")
    else:
        lines.append("\nExport complete.")
        lines.append(f"  Documents scanned : {report['scanned']}")
        lines.append(f"  Indexed to SQLite  : {report['indexed']}")
        lines.append(f"  rows in topic_metadata : {report.get('row_count', 0)}")
        lines.append(f"  DB : {report['db_path']}")

    if report["per_kb"]:
        lines.append("  Per KB:")
        for kb, info in sorted(report["per_kb"].items()):
            phases = ", ".join(
                f"{p}={n}" for p, n in sorted(info["phases"].items())
            ) or "no phase"
            lines.append(f"    {kb}: {info['docs']} doc(s) [{phases}]")

    if report.get("preserved"):
        lines.append(
            f"  DB values preserved (key absent from frontmatter): "
            f"{len(report['preserved'])}"
        )
        for p in report["preserved"]:
            lines.append(f"    - {p}")

    if report.get("pruned"):
        lines.append(f"  Pruned stale rows: {len(report['pruned'])}")
        for p in report["pruned"]:
            lines.append(f"    - {p}")

    if report["warnings"]:
        lines.append(f"\n  Warnings: {len(report['warnings'])}")
        for w in report["warnings"]:
            lines.append(f"    {w}")

    if report["errors"]:
        lines.append(f"\n  Errors: {len(report['errors'])}")
        for e in report["errors"]:
            lines.append(f"    {e}")

    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1: Export DeepTutor KBs to Hermes format + SQLite index"
    )
    parser.add_argument("--kb-root", required=True,
                        help="Root directory of DeepTutor knowledge bases")
    parser.add_argument("--db", default=None,
                        help="SQLite database path (default: $DREAMER_DB_PATH "
                             "or repo-root dreamer.db)")
    parser.add_argument("--output-dir", default=None,
                        help="Optional: export cleaned KBs to this directory")
    parser.add_argument("--kb", action="append", default=None,
                        help="Only export this KB (repeatable)")
    parser.add_argument("--prune-stale", action="store_true",
                        help="Delete rows whose document_path no longer exists "
                             "in the KB root (destructive: confirm with operator)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate only; do not write to DB or disk")
    args = parser.parse_args(argv)

    try:
        report = export_kb(
            kb_root=args.kb_root,
            db_path=args.db,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            kb_names=args.kb,
            prune_stale=args.prune_stale,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(format_report(report, dry_run=args.dry_run))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
