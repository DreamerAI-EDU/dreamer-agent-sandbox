"""Test label_soften — 36 kid-facing combos + parent-facing + mastery + streaks."""

import pytest
from agents.kid_safe.label_soften import (
    soften_label,
    get_mastery_pct,
    get_parent_report_sections,
    is_streak_improvement,
    INTERNAL_LABELS,
    ALL_AGE_BANDS,
    ALL_LANG_CODES,
    LABEL_COMBOS,
)


class TestLabelSoftenKidFacing:
    """36 combos: 4 labels × 3 age bands × 3 languages."""

    @pytest.mark.parametrize("label", INTERNAL_LABELS)
    @pytest.mark.parametrize("band", ALL_AGE_BANDS)
    @pytest.mark.parametrize("lang", ALL_LANG_CODES)
    def test_all_36_combos_non_empty(self, label, band, lang):
        result = soften_label(label, band, lang, audience="kid_facing")
        assert result, f"Empty result for {label}/{band}/{lang}/kid_facing"
        assert isinstance(result, str)
        assert len(result) > 1, f"Result too short for {label}/{band}/{lang}"

    def test_not_yet_mapping(self):
        assert soften_label("not_yet", "P1-P3", "en") == "Getting Started"
        assert soften_label("not_yet", "P4-P6", "en") == "Keep Going!"
        assert soften_label("not_yet", "S1-S3", "en") == "Not Yet"

    def test_developing_mapping(self):
        assert soften_label("developing", "P1-P3", "en") == "Making Progress"
        assert soften_label("developing", "P4-P6", "en") == "Almost There!"
        assert soften_label("developing", "S1-S3", "en") == "Developing"

    def test_achieved_mapping(self):
        assert soften_label("achieved", "P1-P3", "en") == "You've Got It!"
        assert soften_label("achieved", "P4-P6", "en") == "Well Done!"
        assert soften_label("achieved", "S1-S3", "en") == "Achieved"

    def test_exemplary_mapping(self):
        assert soften_label("exemplary", "P1-P3", "en") == "Amazing Work!"
        assert soften_label("exemplary", "P4-P6", "en") == "Excellent!"
        assert soften_label("exemplary", "S1-S3", "en") == "Exemplary"

    def test_no_internal_label_leaked(self):
        """Kid-facing output must never contain raw internal labels."""
        for label in INTERNAL_LABELS:
            for band in ALL_AGE_BANDS:
                for lang in ALL_LANG_CODES:
                    result = soften_label(label, band, lang, audience="kid_facing")
                    # internal labels use underscores — check they don't appear
                    for internal in INTERNAL_LABELS:
                        assert internal not in result, (
                            f"Internal label '{internal}' leaked in {label}/{band}/{lang}: '{result}'"
                        )


class TestLabelSoftenParentFacing:
    """Parent-facing labels are flat (no age band dimension)."""

    @pytest.mark.parametrize("lang", ALL_LANG_CODES)
    def test_not_yet_parent(self, lang):
        result = soften_label("not_yet", "P1-P3", lang, audience="parent_facing")
        assert result  # Non-empty parent-facing mapping
        assert "not_yet" not in result.lower()

    @pytest.mark.parametrize("lang", ALL_LANG_CODES)
    def test_achieved_parent(self, lang):
        result = soften_label("achieved", "P1-P3", lang, audience="parent_facing")
        assert result


class TestLabelSoftenFallbacks:
    """Edge cases and fallback behaviour."""

    def test_unknown_label_passthrough(self):
        result = soften_label("super_exemplary", "P1-P3", "en")
        assert result == "super_exemplary"

    def test_unknown_audience_passthrough(self):
        result = soften_label("achieved", "P1-P3", "en", audience="teacher_facing")
        assert result == "achieved"

    def test_unknown_lang_falls_back_to_en(self):
        """Unknown language should give the EN version for that band."""
        result = soften_label("achieved", "P4-P6", "fr")
        assert result == "Well Done!"  # EN for P4-P6

    def test_empty_label(self):
        result = soften_label("", "P1-P3", "en")
        assert result == ""  # passthrough


class TestMasteryPct:
    """Mastery percentage mapping from config."""

    def test_not_yet(self):
        assert get_mastery_pct("not_yet") == 0.25

    def test_developing(self):
        assert get_mastery_pct("developing") == 0.50

    def test_achieved(self):
        assert get_mastery_pct("achieved") == 0.75

    def test_exemplary(self):
        assert get_mastery_pct("exemplary") == 1.00

    def test_unknown(self):
        assert get_mastery_pct("nonexistent") == 0.0

    def test_type_is_float(self):
        for label in INTERNAL_LABELS:
            assert isinstance(get_mastery_pct(label), float)


class TestParentReportSections:
    """Parent report section headers in all 3 languages."""

    def test_english_has_all_keys(self):
        sections = get_parent_report_sections("en")
        expected_keys = [
            "summary", "progress", "strengths",
            "development", "recommendations",
            "session_count", "time_spent",
        ]
        for key in expected_keys:
            assert key in sections, f"Missing key '{key}' in EN sections"
            assert sections[key], f"Empty section for '{key}'"

    def test_cantonese_has_all_keys(self):
        sections = get_parent_report_sections("zh-hk")
        assert len(sections) >= 7
        for val in sections.values():
            assert val  # non-empty

    def test_mandarin_has_all_keys(self):
        sections = get_parent_report_sections("zh-cn")
        assert len(sections) >= 7
        for val in sections.values():
            assert val

    def test_unknown_language_falls_back_to_en(self):
        sections = get_parent_report_sections("fr")
        assert "summary" in sections


class TestStreakImprovement:
    """Streak rules from config."""

    def test_not_yet_to_developing_is_improvement(self):
        assert is_streak_improvement("not_yet", "developing") is True

    def test_developing_to_achieved_is_improvement(self):
        assert is_streak_improvement("developing", "achieved") is True

    def test_achieved_to_exemplary_is_improvement(self):
        assert is_streak_improvement("achieved", "exemplary") is True

    def test_same_label_is_not_improvement(self):
        assert is_streak_improvement("developing", "developing") is False

    def test_regression_is_not_improvement(self):
        assert is_streak_improvement("achieved", "not_yet") is False

    def test_unknown_label(self):
        assert is_streak_improvement("blah", "exemplary") is False
        assert is_streak_improvement("not_yet", "blah") is False


class TestLabelCombos:
    """Verify 36-combo constant."""

    def test_label_combos_constant(self):
        assert LABEL_COMBOS == 36
