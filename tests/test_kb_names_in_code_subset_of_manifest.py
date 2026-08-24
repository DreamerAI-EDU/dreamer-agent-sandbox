"""Phase 7 B21 — CI guard: KB names in code ⊆ manifest KB names.

Spec docs/phase7-B21-kb-seed-規格.md §1 (命名裁決: 代碼就 manifest):
  Scans all agents/*.py for dreamer-* strings and asserts every KB-looking
  name is present in kb/manifest.yaml. Prevents §12 legacy slugs
  (dreamer-maths, dreamer-rubrics, dreamer-psd, ...) from creeping back.

Non-KB uses are explicitly excluded:
  - dreamer-agent-sandbox (repo name, codex_cli.py)
  - dreamer-ai           (brand/product name, otel_exporter.py)
  - dreamer-sandboxes-   (sandbox naming prefix, sandbox_manager.py)
"""

from __future__ import annotations

import re
from pathlib import Path

import scripts.seed_kb as seed

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
MANIFEST_PATH = REPO_ROOT / "kb" / "manifest.yaml"

# Non-KB prefixes that legitimately appear in code (excluded from the check)
NON_KB_PREFIXES = ("dreamer-agent-sandbox", "dreamer-ai", "dreamer-sandboxes-")

_DREAMER_RE = re.compile(r"dreamer-[a-z0-9_\-]+")


def _manifest_kb_names() -> set[str]:
    manifest = seed.load_manifest(MANIFEST_PATH)
    return {kb["name"] for kb in manifest["knowledge_bases"]}


def _code_dreamer_names() -> set[str]:
    names: set[str] = set()
    for path in sorted(AGENTS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in _DREAMER_RE.finditer(text):
            name = m.group(0)
            if name.startswith(NON_KB_PREFIXES):
                continue
            names.add(name)
    return names


def test_kb_names_in_code_subset_of_manifest():
    kb_names = _manifest_kb_names()
    code_names = _code_dreamer_names()

    assert code_names, (
        "no dreamer-* KB references found in agents/ — "
        "regex may be broken or directory empty"
    )
    unknown = sorted(code_names - kb_names)
    assert not unknown, (
        "agents/*.py references KB names not in kb/manifest.yaml: "
        f"{unknown}. Update code to manifest names (spec §1) or extend manifest."
    )
