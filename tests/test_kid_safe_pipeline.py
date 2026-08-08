"""Test KidSafePipeline — normal and error paths."""

import pytest
from agents.kid_safe import KidSafePipeline
from agents.kid_safe.session_wrap import SessionState


@pytest.fixture
def pipeline():
    return KidSafePipeline()


class TestProcessResponse:
    """Normal response path: ToneRewrite → (optional Wrap)."""

    def test_basic_pipeline_en(self, pipeline):
        result = pipeline.process_response(
            "That is wrong.", "P4-P6", "en",
        )
        assert "wrong" not in result.lower()
        assert len(result) > 0

    def test_basic_pipeline_zh_hk(self, pipeline):
        result = pipeline.process_response(
            "你答錯咗", "P4-P6", "zh-hk",
        )
        assert len(result) > 0

    def test_basic_pipeline_zh_cn(self, pipeline):
        result = pipeline.process_response(
            "你错了", "P4-P6", "zh-cn",
        )
        assert len(result) > 0

    def test_s1_s3_passthrough_neutral(self, pipeline):
        text = "This is a detailed, complex academic response."
        result = pipeline.process_response(text, "S1-S3", "en")
        assert result == text

    def test_s1_s3_strips_anxiety(self, pipeline):
        result = pipeline.process_response(
            "You'll fail the exam. Here is the solution.",
            "S1-S3", "en",
        )
        assert "fail the exam" not in result.lower()
        assert "solution" in result.lower()

    def test_no_session_no_wrap(self, pipeline):
        """Without session, no wrap is appended even at turn 7+."""
        result = pipeline.process_response(
            "Good job", "P1-P3", "en",
        )
        assert "That's all" not in result

    def test_session_tracks_turns(self, pipeline):
        session = SessionState(lang_code="en")
        assert session.turns == 0

        pipeline.process_response("Turn 1", "P4-P6", "en", session=session)
        assert session.turns == 1

    def test_session_triggers_wrap_at_turn_7(self, pipeline):
        session = SessionState(lang_code="en")
        # Simulate 6 prior turns
        for _ in range(6):
            session.increment()
        assert session.turns == 6
        assert session.should_wrap() is False

        # 7th turn triggers wrap
        session.add_topic("Math", "achieved")
        result = pipeline.process_response(
            "Good work", "P4-P6", "en", session=session,
        )
        assert session.turns == 7
        assert session.should_wrap() is True
        assert "That's all" in result

    def test_wrap_not_triggered_before_7(self, pipeline):
        session = SessionState(lang_code="en")
        result = pipeline.process_response(
            "Hello", "P4-P6", "en", session=session,
        )
        assert "That's all" not in result
        assert session.turns == 1


class TestProcessError:
    """Error path: bypasses all middleware, uses error templates."""

    @pytest.mark.parametrize("age_band", ["P1-P3", "P4-P6", "S1-S3"])
    @pytest.mark.parametrize("lang_code", ["en", "zh-hk", "zh-cn"])
    def test_all_combinations_return_string(self, pipeline, age_band, lang_code):
        """Error path should return a non-empty string for all combinations."""
        result = pipeline.process_error(
            "Internal error 500", "server_error", age_band, lang_code,
        )
        assert isinstance(result, str)
        assert len(result) > 10

    def test_error_bypasses_tone_rewrite(self, pipeline):
        """Error path does NOT apply keyword replacement — raw 'wrong' should not appear in student-facing message."""
        result = pipeline.process_error(
            "Something went wrong", "server_error", "P1-P3", "en",
        )
        # The friendly template should not contain the raw error text
        assert "Something went wrong" not in result

    def test_error_bypasses_word_trim(self, pipeline):
        """Error message should not be trimmed to age-band word limits."""
        result = pipeline.process_error(
            "x" * 200, "server_error", "P1-P3", "en",
        )
        # P1-P3 has 10-word limit in normal path; error should be full
        assert len(result.split()) > 5

    def test_error_template_differs_by_age(self, pipeline):
        r_p1 = pipeline.process_error("err", "server_error", "P1-P3", "en")
        r_s1 = pipeline.process_error("err", "server_error", "S1-S3", "en")
        # Different age bands should produce different messages
        assert r_p1 != r_s1

    def test_error_template_differs_by_language(self, pipeline):
        r_en = pipeline.process_error("err", "server_error", "P4-P6", "en")
        r_hk = pipeline.process_error("err", "server_error", "P4-P6", "zh-hk")
        assert r_en != r_hk
