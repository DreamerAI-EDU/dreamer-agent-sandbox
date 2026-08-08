"""Test error_templates — 9 templates (3 age bands × 3 languages)."""

import pytest
from agents.kid_safe.error_templates import (
    ERROR_TEMPLATES,
    FALLBACK_TEMPLATES,
    ALL_AGE_BANDS,
    ALL_LANG_CODES,
    TEMPLATE_COUNT,
    get_error_message,
    label_error,
    P1_P3, P4_P6, S1_S3,
    EN, ZH_HK, ZH_CN,
)


class TestErrorTemplatesCatalogue:
    """Verify the static template dictionary is complete."""

    def test_all_nine_templates_present(self):
        """3 age bands × 3 languages = 9 templates."""
        assert len(ERROR_TEMPLATES) == 3
        for band in ALL_AGE_BANDS:
            assert band in ERROR_TEMPLATES, f"Missing age band: {band}"
            assert len(ERROR_TEMPLATES[band]) == 3, (
                f"{band} should have 3 languages, got {len(ERROR_TEMPLATES[band])}"
            )
            for lang in ALL_LANG_CODES:
                assert lang in ERROR_TEMPLATES[band], (
                    f"Missing {lang} in {band}"
                )

    def test_no_empty_templates(self):
        """No template string should be empty."""
        for band in ALL_AGE_BANDS:
            for lang in ALL_LANG_CODES:
                msg = ERROR_TEMPLATES[band][lang]
                assert msg, f"Empty template for {band}/{lang}"
                assert isinstance(msg, str)

    def test_fallbacks_all_languages(self):
        """Fallback templates cover all three languages."""
        for lang in ALL_LANG_CODES:
            assert lang in FALLBACK_TEMPLATES, f"Missing fallback for {lang}"
            assert FALLBACK_TEMPLATES[lang], f"Empty fallback for {lang}"

    def test_template_count_constant(self):
        assert TEMPLATE_COUNT == 9


class TestGetErrorMessage:
    """Test get_error_message() dispatch."""

    @pytest.mark.parametrize("band,lang", [
        (P1_P3, EN), (P1_P3, ZH_HK), (P1_P3, ZH_CN),
        (P4_P6, EN), (P4_P6, ZH_HK), (P4_P6, ZH_CN),
        (S1_S3, EN), (S1_S3, ZH_HK), (S1_S3, ZH_CN),
    ])
    def test_returns_correct_template(self, band, lang):
        msg = get_error_message(band, lang)
        expected = ERROR_TEMPLATES[band][lang]
        assert msg == expected

    def test_unknown_age_band_returns_fallback(self):
        msg = get_error_message("X-Y", EN)
        assert msg == FALLBACK_TEMPLATES[EN]

    def test_unknown_language_returns_english_in_band(self):
        """If language missing but age band valid → fall back to EN within band."""
        msg = get_error_message(P1_P3, "fr")
        assert msg == ERROR_TEMPLATES[P1_P3][EN]

    def test_unknown_both_returns_fallback_en(self):
        msg = get_error_message("X-Y", "fr")
        assert msg == FALLBACK_TEMPLATES[EN]

    def test_raw_error_not_surfaced(self):
        """The raw error string passed in must never appear in output."""
        raw = "500 Internal Server Error: connection reset"
        for band in ALL_AGE_BANDS:
            for lang in ALL_LANG_CODES:
                msg = get_error_message(band, lang, raw_error=raw)
                assert "500" not in msg
                assert "Internal Server Error" not in msg
                assert "connection reset" not in msg

    def test_template_never_blank(self):
        """Even with empty raw_error, result is non-empty."""
        for band in ALL_AGE_BANDS:
            for lang in ALL_LANG_CODES:
                assert get_error_message(band, lang, raw_error="") != ""


class TestLabelError:
    """Test error type → human-readable label mapping."""

    def test_known_types(self):
        assert label_error("ws_error") == "WebSocket connection error"
        assert label_error("timeout") == "DeepTutor request timeout"
        assert label_error("server_error") == "DeepTutor server error (5xx)"
        assert label_error("empty_response") == "DeepTutor returned empty response"
        assert label_error("unknown") == "Unknown error"

    def test_unknown_type_passthrough(self):
        assert label_error("some_new_error") == "some_new_error"
