#!/usr/bin/env python3
"""
Phase 1 — KB Export Script
Exports DeepTutor knowledge base documents to Hermes-compatible format,
extracting YAML frontmatter and populating the SQLite metadata index.

Usage:
    python phase1_kb_export.py --kb-root ./knowledge_bases --db ./metadata.db

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


# =============================================================================
# Dreamer 4D phase validation (teaching mainline — must be one of these four)
# =============================================================================
VALID_DREAMER_PHASES = {"Dream", "Discover", "Design", "Deliver"}

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

VALID_MODES = {"contextual", "direct", "hybrid"}


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

    # dreamer_phase validation (PRIMARY AXIS)
    phase = meta.get("dreamer_phase", "")
    if phase and phase not in VALID_DREAMER_PHASES:
        warnings.append(
            f"[{filepath}] Invalid dreamer_phase '{phase}'. "
            f"Must be one of: {', '.join(sorted(VALID_DREAMER_PHASES))}"
        )

    # ib_atl_skills validation (cross-reference only)
    atl = meta.get("ib_atl_skills", [])
    if isinstance(atl, list):
        unknown = set(atl) - KNOWN_IB_ATL_SKILLS
        if unknown:
            warnings.append(
                f"[{filepath}] Unknown ib_atl_skills: {unknown}. "
                f"Known values: {', '.join(sorted(KNOWN_IB_ATL_SKILLS))}"
            )

    # modes_allowed validation
    modes_raw = meta.get("modes_allowed", "")
    if modes_raw:
        if isinstance(modes_raw, str) and modes_raw.startswith("["):
            try:
                modes = json.loads(modes_raw)
            except json.JSONDecodeError:
                modes = [m.strip() for m in modes_raw.strip("[]").split(",")]
        elif isinstance(modes_raw, list):
            modes = modes_raw
        else:
            modes = [m.strip() for m in modes_raw.split(",")]
        invalid = set(modes) - VALID_MODES
        if invalid:
            warnings.append(
                f"[{filepath}] Invalid modes: {invalid}. "
                f"Must be subset of: {', '.join(sorted(VALID_MODES))}"
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
    """Initialize the SQLite metadata database with schema."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    schema_path = Path(__file__).parent / "phase1_sqlite_schema.sql"
    if schema_path.exists():
        schema_sql = schema_path.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
    else:
        print(f"Warning: schema file not found at {schema_path}", file=sys.stderr)

    conn.commit()
    return conn


def upsert_topic_metadata(conn: sqlite3.Connection, meta: dict, body_hash: str,
                          doc_path: str):
    """Insert or update a topic metadata row."""
    # Serialize list fields to JSON strings
    def to_json(val):
        if isinstance(val, list):
            return json.dumps(val, ensure_ascii=False)
        if isinstance(val, str) and val.startswith("["):
            return val
        return json.dumps([], ensure_ascii=False)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO topic_metadata (
            topic_id, subject, topic, ai_literacy_context,
            modes_allowed, grade_level, prerequisites, linked_projects,
            dreamer_phase, ib_atl_skills, ethical_ai_tags,
            kb_name, document_path, document_hash, domain_agent_owner,
            exported_at, last_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id) DO UPDATE SET
            subject = excluded.subject,
            topic = excluded.topic,
            ai_literacy_context = excluded.ai_literacy_context,
            modes_allowed = excluded.modes_allowed,
            grade_level = excluded.grade_level,
            prerequisites = excluded.prerequisites,
            linked_projects = excluded.linked_projects,
            dreamer_phase = excluded.dreamer_phase,
            ib_atl_skills = excluded.ib_atl_skills,
            ethical_ai_tags = excluded.ethical_ai_tags,
            kb_name = excluded.kb_name,
            document_path = excluded.document_path,
            document_hash = excluded.document_hash,
            domain_agent_owner = excluded.domain_agent_owner,
            last_modified = excluded.last_modified
    """, (
        meta.get("topic_id", ""),
        meta.get("subject", ""),
        meta.get("topic", ""),
        meta.get("ai_literacy_context", ""),
        to_json(meta.get("modes_allowed", [])),
        meta.get("grade_level", ""),
        to_json(meta.get("prerequisites", [])),
        to_json(meta.get("linked_projects", [])),
        meta.get("dreamer_phase", ""),
        to_json(meta.get("ib_atl_skills", [])),
        to_json(meta.get("ethical_ai_tags", [])),
        meta.get("kb_name", ""),
        doc_path,
        body_hash,
        meta.get("domain_agent_owner", ""),
        now,
        now,
    ))


# =============================================================================
# Main Export Pipeline
# =============================================================================
def export_kb(kb_root: str, db_path: str, output_dir: Optional[str] = None,
              dry_run: bool = False):
    """Main export pipeline: walk KB directories, parse, validate, index."""

    kb_root = Path(kb_root)
    if not kb_root.is_dir():
        print(f"Error: KB root not found: {kb_root}", file=sys.stderr)
        sys.exit(1)

    conn = init_sqlite_db(db_path) if not dry_run else None

    total = 0
    warnings = []
    errors = []

    for md_file in sorted(kb_root.rglob("*.md")):
        total += 1
        rel_path = str(md_file.relative_to(kb_root))

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"[{rel_path}] Read error: {e}")
            continue

        content = strip_aigc_watermark(content)

        meta = parse_frontmatter(content)
        if not meta:
            warnings.append(f"[{rel_path}] No YAML frontmatter found. Skipping index.")
            continue

        # Validate
        file_warnings = validate_frontmatter(meta, rel_path)
        warnings.extend(file_warnings)

        body = extract_body(content)
        body_hash = compute_hash(content)

        # Optionally write to output directory
        if output_dir:
            out_path = Path(output_dir) / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(body, encoding="utf-8")

        # Index into SQLite
        if conn and not dry_run:
            upsert_topic_metadata(conn, meta, body_hash, rel_path)

    # Summary
    if conn:
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM topic_metadata").fetchone()[0]
        conn.close()
        print(f"\nExport complete.")
        print(f"  Documents scanned : {total}")
        print(f"  Indexed to SQLite  : {count}")
    else:
        print(f"\nDry run complete. {total} documents scanned.")

    if warnings:
        print(f"\n  Warnings: {len(warnings)}")
        for w in warnings:
            print(f"    {w}")

    if errors:
        print(f"\n  Errors: {len(errors)}")
        for e in errors:
            print(f"    {e}")

    return 0 if not errors else 1


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Phase 1: Export DeepTutor KBs to Hermes format + SQLite index"
    )
    parser.add_argument("--kb-root", required=True,
                        help="Root directory of DeepTutor knowledge bases")
    parser.add_argument("--db", default="./metadata.db",
                        help="SQLite database path (default: ./metadata.db)")
    parser.add_argument("--output-dir", default=None,
                        help="Optional: export cleaned KBs to this directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate only; do not write to DB or disk")
    args = parser.parse_args()

    sys.exit(export_kb(
        kb_root=args.kb_root,
        db_path=args.db,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    ))
