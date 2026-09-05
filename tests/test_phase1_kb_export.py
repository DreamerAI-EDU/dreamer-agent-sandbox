"""Phase 7 watermark line — guard tests for phase1_kb_export.strip_aigc_watermark.

IMPORTANT (assumption disclosure): fixture formats below are SYNTHETIC —
they encode the format the stripper regex was written against, but have
NOT been calibrated against a real watermarked export sample (no genuine
(1).md / ContentProducer original exists in the repo as of 2026-09-05).
These tests guard the stripper against regression only; they do NOT
verify that real-world watermark format is fully covered. The true
defence line remains seed_kb.py --check AIGC hard FAIL (validate_frontmatter).
"""

from __future__ import annotations

import textwrap

import pipeline.phase1_kb_export as export


def _sample(watermarked: bool = True) -> str:
    """Synthetic export sample: real frontmatter + body, optionally with the
    assumed AIGC watermark head block and footer."""
    aigc_head = (
        "---\n"
        "AIGC:\n"
        "    ContentProducer: text-export-tool\n"
        "    Generated: 2026-09-01\n"
        "---\n"
    ) if watermarked else ""
    footer = "（内容由AI生成，仅供参考）\n" if watermarked else ""
    return aigc_head + textwrap.dedent("""\
        ---
        topic_id: maths-fractions-01
        subject: Mathematics
        topic: "Fractions Basics"
        dreamer_phase: Dream
        modes_allowed:
          - contextual
        grade_level: P4-P6
        kb_name: dreamer-maths-ai
        ---
        # Body
        Students explore fractions.
        """) + footer


def test_strip_removes_aigc_head_block_and_footer() -> None:
    content = _sample(watermarked=True)
    cleaned = export.strip_aigc_watermark(content)
    assert "ContentProducer" not in cleaned
    assert "AIGC:" not in cleaned
    assert "内容由AI" not in cleaned
    # Real frontmatter + body survive untouched.
    assert "topic_id: maths-fractions-01" in cleaned
    assert "# Body" in cleaned
    assert cleaned.startswith("---\n")
    assert cleaned.rstrip().endswith("Students explore fractions.")


def test_strip_removes_footer_when_no_head_block() -> None:
    content = _sample(watermarked=False) + "（内容由AI生成，仅供参考）\n"
    cleaned = export.strip_aigc_watermark(content)
    assert "内容由AI" not in cleaned
    assert cleaned.rstrip().endswith("Students explore fractions.")


def test_strip_leaves_clean_content_untouched() -> None:
    content = _sample(watermarked=False)
    cleaned = export.strip_aigc_watermark(content)
    assert cleaned == content
