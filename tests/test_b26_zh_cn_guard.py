"""B26 — zh-cn guard tests.

Guards against the frontend/backend language contract drifting apart again
(habit #15 pattern: any refactor touching a shared enum gets a regression test).

1. test_lang_code_frontend_contract_subset_of_hermes — frontend contract
   values (en / zh-hk / zh-cn) must be a subset of the Hermes enum.
2. test_zh_cn_audit_cases_present — every quality_audit case (en/zh-hk)
   must have a zh-cn mirror (12/12 coverage gate).
3. test_language_consistency_zh_cn_heuristic — simplified-Chinese heuristic:
   pure simplified passes, mixed traditional >2% fails, pure traditional fails,
   HK-style zh/en mixed text is NOT false-flagged.
4. test_kid_safe_zh_cn_copy_present — kid-safe tone config / error templates
   are trilingual (zh-cn included).
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# ── 1. Frontend contract ⊆ Hermes enum ────────────────────────────────

# Frontend contract hardcoded from W1 scaffold src/lib/mock.ts lang_code enum.
FRONTEND_LANG_CODES = ("en", "zh-hk", "zh-cn")

# Hermes enum source of truth: agents/ language constants / type annotations.
# Keep this list in sync with agents/kid_safe/*.py ALL_LANG_CODES.
HERMES_LANG_CODES = ("en", "zh-hk", "zh-cn")


def test_lang_code_frontend_contract_subset_of_hermes():
    missing = [lc for lc in FRONTEND_LANG_CODES if lc not in HERMES_LANG_CODES]
    assert not missing, (
        f"frontend contract {FRONTEND_LANG_CODES} has lang codes missing from "
        f"Hermes enum {HERMES_LANG_CODES}: {missing} — sync the backend enum "
        f"before shipping a frontend that sends unsupported values."
    )


def test_hermes_enum_contains_zh_cn_in_code():
    """Scan agents/ for lang-code enums; all must include zh-cn."""
    agents_dir = os.path.join(REPO_ROOT, "agents")
    hits = []
    for root, _dirs, files in os.walk(agents_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            # Look for literal tuple/list enums that mention zh-hk but not zh-cn
            for m in re.finditer(r"[(\[]\s*[\"']en[\"']\s*,\s*[\"']zh-hk[\"']\s*[)\]]", text):
                hits.append((path, m.group(0)))
    assert not hits, (
        f"found lang_code enums declaring en/zh-hk without zh-cn: {hits}"
    )


# ── 2. quality_audit zh-cn mirror coverage ─────────────────────────────

def _load_audit_cases():
    from scripts.quality_audit import CASES

    return list(CASES)


def test_zh_cn_audit_cases_present():
    """Every original audit case must have zh-cn coverage.

    Structure after B26: n=1..12 are the curated originals (en / zh-hk /
    zh-cn), n=13..24 are the zh-cn mirror block. Guard asserts:
    - total curated cases >= 24
    - zh-cn cases >= 12 (every original case type has a simplified mirror)
    - the mirror block n=13..24 is entirely zh-cn
    """
    cases = _load_audit_cases()
    langs = {c["n"]: c.get("lang") for c in cases}
    zh_cn_count = sum(1 for lc in langs.values() if lc == "zh-cn")

    assert len(cases) >= 24, (
        f"expected >=24 curated audit cases after B26 mirror, got {len(cases)}"
    )
    assert zh_cn_count >= 12, (
        f"zh-cn coverage too low: {zh_cn_count}/24 — every original case "
        f"needs a simplified mirror (12/12), not a representative subset."
    )
    mirror_ok = all(
        langs.get(n) == "zh-cn" for n in range(13, 25) if n in langs
    )
    assert mirror_ok, (
        f"mirror block n=13..24 must all be zh-cn, got "
        f"{ {n: langs.get(n) for n in range(13, 25) if n in langs} }"
    )


# ── 3. zh-cn traditional-character heuristic ───────────────────────────

def _zh_cn_check(content: str) -> tuple[bool, str]:
    """Re-import the check function to keep the test honest."""
    from scripts.quality_audit import check_language_consistency

    return check_language_consistency(
        {"content": content}, {"lang": "zh-cn"}
    )


def test_language_consistency_zh_cn_heuristic():
    # Pure simplified passes
    ok, _ = _zh_cn_check("今天我们学习数学，这个题目很简单，我们一起做练习。")
    assert ok is True

    # Mixed traditional > 2% fails (density threshold)
    bad, msg = _zh_cn_check("今天我们學數學，這個題目很簡單，我們一起做練習。")
    assert bad is False
    assert "traditional-glyph" in msg

    # Pure traditional fails
    bad2, _ = _zh_cn_check("我們今天學數學，這個題目很簡單，我們一起做練習。")
    assert bad2 is False

    # zh/en mixed text is not false-flagged (CJK ratio still >= 30%)
    ok3, _ = _zh_cn_check("今天我们学数学，一起做练习，let's practice together，很简单。")
    assert ok3 is True


def test_language_consistency_zh_cn_heuristic_whitelist():
    """Proper-noun whitelist (e.g. 台灣) must not trip the heuristic."""
    from scripts.quality_audit import check_language_consistency

    ok, _ = check_language_consistency(
        {"content": "今天我们学习台灣的地理知识，这个岛屿很漂亮。"},
        {"lang": "zh-cn"},
    )
    assert ok is True


# ── 4. Kid-Safe zh-cn copy present ────────────────────────────────────

def test_kid_safe_zh_cn_copy_present():
    """Kid-safe tone config / error templates must include zh-cn copy."""
    tone_cfg_path = os.path.join(REPO_ROOT, "config", "kid_safe_tone_rules.json")
    with open(tone_cfg_path, encoding="utf-8") as fh:
        tone_cfg = json.load(fh)

    for section in ("sarcasm_patterns", "grade_anxiety_patterns", "keyword_replacements"):
        langs = set(tone_cfg.get(section, {}).keys())
        assert "zh-cn" in langs, (
            f"kid_safe_tone_rules.json[{section}] missing zh-cn key (has {langs})"
        )

    from agents.kid_safe.error_templates import ERROR_TEMPLATES

    # ERROR_TEMPLATES is keyed by age band -> {lang: text}
    for band, langs in ERROR_TEMPLATES.items():
        assert "zh-cn" in langs, (
            f"error_templates[{band}] missing zh-cn key (has {sorted(langs)})"
        )

    from agents.kid_safe.session_wrap import _TEMPLATES

    assert "zh-cn" in _TEMPLATES, "session_wrap templates missing zh-cn key"
