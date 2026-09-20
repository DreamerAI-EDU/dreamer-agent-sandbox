"""PR-D watermark guard tests (PR #89) - write-channel AIGC injection.

Covers the marker vocabulary reuse (``scripts/seed_kb.AIGC_MARKERS`` stays the
SoT), the repo-wide structural check, and the sensitivity of both scans, so the
guard cannot silently rot into a no-op after the PR #88 incident.
"""
from __future__ import annotations

import scripts.check_aigc_watermark as guard
import scripts.seed_kb as seed


def test_marker_vocabulary_is_reused_from_seed_kb():
    """The guard must not re-declare the markers - seed_kb.py stays the SoT."""
    for marker in seed.AIGC_MARKERS:
        assert marker in guard.MARKERS


def test_repo_prompt_and_kb_content_is_clean():
    findings = guard.find_violations()
    assert findings == {}, f"AIGC watermark in tracked content: {findings}"


def test_scan_scope_covers_content_and_excludes_tooling():
    assert guard.is_content_file("deeptutor/personas/dibi-p1-p3/PERSONA.md")
    assert guard.is_content_file("deeptutor/prompt_overrides/zh/chat_agent.yaml")
    assert guard.is_content_file("knowledge_bases/dreamer-core-kb/core-ai-what-is-01.md")
    assert not guard.is_content_file("scripts/seed_kb.py")


def test_vocabulary_scan_flags_injected_metadata(tmp_path):
    polluted = tmp_path / "PERSONA.md"
    polluted.write_text(
        "---\nAIGC:\n    ContentProducer: 001191440300708461136T1XGW3\n"
        "    ReservedCode1: YWJjZGVm\n---\nname: x\n---\nbody\n",
        encoding="utf-8",
    )
    hits = guard.scan_file(polluted, vocabulary=True)
    assert any("ContentProducer" in h for h in hits)
    assert any("AIGC:" in h for h in hits)


def test_structural_scan_flags_frontmatter_replacement_and_tail(tmp_path):
    polluted = tmp_path / "PERSONA.md"
    polluted.write_text(
        "---\nAIGC:\n    Label: \"1\"\n---\n\n"
        "You are talking with a young child.\n"
        "*（内容由AI生成，仅供参考）*\n",
        encoding="utf-8",
    )
    hits = guard.scan_file(polluted, vocabulary=False)
    assert any("head" in h for h in hits)
    assert any("disclaimer" in h for h in hits)


def test_clean_persona_is_not_flagged(tmp_path):
    clean = tmp_path / "PERSONA.md"
    clean.write_text(
        "---\nname: dibi-p1-p3\ndescription: Dibi voice for Primary 1-3\n---\n"
        "You are talking with a young child in Primary 1-3.\n",
        encoding="utf-8",
    )
    assert guard.scan_file(clean, vocabulary=True) == []
