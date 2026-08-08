"""Test ethical_ai_kb — KB prefix injection for every query."""

import pytest
from agents.kid_safe.ethical_ai_kb import (
    build_kb_prefix,
    inject_kb,
    ETHICAL_AI_KB_PREFIX,
)


class TestBuildKbPrefix:
    """Core KB prefix builder."""

    def test_no_age_band_returns_core_only(self):
        result = build_kb_prefix()
        assert "[dreamer-ethical-ai]" in result
        assert "age-band" not in result
        assert "Never generate harmful" in result

    def test_with_p1_p3(self):
        result = build_kb_prefix("P1-P3")
        assert "[dreamer-ethical-ai]" in result
        assert "[age-band: P1-P3" in result
        assert "playful elements" in result

    def test_with_p4_p6(self):
        result = build_kb_prefix("P4-P6")
        assert "[dreamer-ethical-ai]" in result
        assert "[age-band: P4-P6" in result
        assert "critical thinking" in result

    def test_with_s1_s3(self):
        result = build_kb_prefix("S1-S3")
        assert "[dreamer-ethical-ai]" in result
        assert "[age-band: S1-S3" in result
        assert "public exam thinking" in result

    def test_unknown_age_band_falls_back_to_core(self):
        result = build_kb_prefix("unknown-band")
        assert "[dreamer-ethical-ai]" in result
        assert "age-band" not in result

    def test_all_bands_have_unique_guidelines(self):
        """Each age band should add something distinct."""
        r_p1 = build_kb_prefix("P1-P3")
        r_p4 = build_kb_prefix("P4-P6")
        r_s1 = build_kb_prefix("S1-S3")
        # All should differ from each other
        assert r_p1 != r_p4
        assert r_p4 != r_s1
        assert r_p1 != r_s1

    def test_core_principles_present_in_all(self):
        """Core ethical principles must appear in every prefix."""
        core_principles = [
            "growth mindset",
            "avoid comparisons",
            "personal identifiable information",
            "trusted adult",
            "positive framing",
            "Hong Kong trilingual",
        ]
        for age_band in ["P1-P3", "P4-P6", "S1-S3", None]:
            result = build_kb_prefix(age_band)
            for principle in core_principles:
                assert principle.lower() in result.lower(), f"'{principle}' missing in age_band={age_band}"


class TestInjectKb:
    """Inject KB into student queries."""

    def test_basic_injection(self):
        result = inject_kb("How do I add fractions?", "P4-P6")
        assert "[dreamer-ethical-ai]" in result
        assert "[student-query]" in result
        assert "How do I add fractions?" in result
        assert "[/student-query]" in result

    def test_injection_ordering(self):
        """KB prefix must come before student query."""
        result = inject_kb("Test query", "P1-P3")
        kb_pos = result.index("[dreamer-ethical-ai]")
        query_pos = result.index("[student-query]")
        assert kb_pos < query_pos

    def test_no_age_band_injection(self):
        result = inject_kb("Hello", None)
        assert "[dreamer-ethical-ai]" in result
        assert "[student-query]" in result
        assert "age-band" not in result

    def test_cantonese_query_preserved(self):
        result = inject_kb("點樣計分數加法？", "P4-P6")
        assert "點樣計分數加法？" in result

    def test_mandarin_query_preserved(self):
        result = inject_kb("怎么算分数加法？", "P1-P3")
        assert "怎么算分数加法？" in result
