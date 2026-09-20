#!/usr/bin/env python3
"""PR-D watermark guard - the agent write channel must not leak AIGC metadata.

Incident (2026-09-20, PR #88): every file produced by the agent write channel
came back with an auto-injected AIGC block prepended and an
"（内容由AI生成，仅供参考）" line appended. In a persona file the block
*replaced* the file's own front matter, so:

  * the persona loader parsed the wrong block and lost ``name`` / ``description``;
  * the disclaimer line would have shipped inside the student prompt;
  * ``ContentProducer`` / ``ProduceID`` are platform provenance fingerprints
    that must not enter git history.

The marker vocabulary is not re-declared here: it is imported from
``scripts/seed_kb.py`` (``AIGC_MARKERS``), the same SoT whose
``validate_frontmatter`` already hard-FAILs KB documents at seed time. This
guard extends that rule to the files that ship into the engine / student
prompt, plus a structural check for the injected block itself.

Scope note: the vocabulary scan is deliberately limited to content files. The
markers legitimately appear in scripts/seed_kb.py, pipeline/phase1_kb_export.py
and their tests, so a repo-wide vocabulary scan would be pure noise.

Read-only. Exit 0 = clean, 1 = findings.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.seed_kb import AIGC_MARKERS  # noqa: E402  SoT: ("ContentProducer", "内容由AI")

# The rest of the injected block, kept beside the imported SoT so the whole
# platform fingerprint is caught, not only the two seed-time markers.
BLOCK_MARKERS = ("AIGC:", "ReservedCode", "ContentPropagator", "PropagateID")
MARKERS = tuple(dict.fromkeys(AIGC_MARKERS + BLOCK_MARKERS))

# Content that ends up in the engine prompt or in the student's context.
SCAN_GLOBS = (
    "deeptutor/personas/**/*.md",
    "deeptutor/prompt_overrides/**/*.yaml",
    "knowledge_bases/**/*.md",
    "kb/**/*.md",
)

# Structural signature of the injection: block at the head, disclaimer at the tail.
HEAD_BLOCK_RE = re.compile(r"\A---[ \t]*\r?\nAIGC:")
TAIL_DISCLAIMER_RE = re.compile(r"\n[^\n]*(?:内容由AI生成|仅供参考)[^\n]*[ \t]*\r?\n?\Z")
# Extensions treated as text by the structural head check.
TEXT_SUFFIXES = frozenset({
    ".md", ".markdown", ".yaml", ".yml", ".json", ".txt", ".py", ".ts", ".tsx",
    ".js", ".jsx", ".css", ".html", ".toml", ".sql",
})


def tracked_files() -> list[str]:
    """All git-tracked paths, POSIX-style."""
    r = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True)
    return [p.decode("utf-8", "replace").replace("\\", "/") for p in r.stdout.split(b"\0") if p]


def is_content_file(rel: str) -> bool:
    """True when the path is prompt / KB content that ships to the engine."""
    return any(fnmatch.fnmatch(rel, pattern) for pattern in SCAN_GLOBS)


def scan_text(text: str) -> list[str]:
    """Vocabulary markers present anywhere in the file body."""
    return [m for m in MARKERS if m in text]


def scan_structural(text: str) -> list[str]:
    """The injection itself: AIGC block at the head, disclaimer at the tail."""
    hits: list[str] = []
    if HEAD_BLOCK_RE.search(text):
        hits.append("injected AIGC block at file head (shadows the real front matter)")
    if TAIL_DISCLAIMER_RE.search(text):
        hits.append("trailing AI-generated disclaimer line")
    return hits


def scan_file(path: Path, vocabulary: bool = False) -> list[str]:
    """Reasons this file fails the guard (empty list = clean)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = scan_structural(text)
    if vocabulary:
        hits += [f"AIGC marker {m!r}" for m in scan_text(text)]
    return hits


def find_violations() -> dict[str, list[str]]:
    """{path: reasons} for every tracked file carrying the watermark."""
    findings: dict[str, list[str]] = {}
    for rel in tracked_files():
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        reasons = scan_file(REPO / rel, vocabulary=is_content_file(rel))
        if reasons:
            findings[rel] = reasons
    return findings


def main() -> int:
    tracked = tracked_files()
    content = [rel for rel in tracked if is_content_file(rel)]
    findings = find_violations()
    print(f"tracked files scanned      : {len(tracked)}")
    print(f"prompt / KB content scanned: {len(content)}")
    print(f"marker vocabulary          : {', '.join(MARKERS)}")
    if findings:
        print("")
        print("[RED] AIGC watermark found in tracked content:")
        for rel, reasons in sorted(findings.items()):
            print(f"  - {rel}")
            for reason in reasons:
                print(f"      {reason}")
        print("")
        print(f"FAIL: {len(findings)} file(s) carry the write-channel watermark.")
        return 1
    print("")
    print(f"PASS: clean, {len(content)}/{len(content)} content files free of AIGC watermark.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
