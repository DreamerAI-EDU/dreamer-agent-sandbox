"""Test Phase 2.3 wiring in HermesScheduler.

Covers: inject_kb_query, kid_safe_wrap, kid_safe_error.
"""

import pytest
from agents.hermes_scheduler import HermesScheduler
from agents.kid_safe.session_wrap import SessionState


@pytest.fixture
def scheduler():
    return HermesScheduler()


class TestInjectKbQuery:
    """Ethical AI KB injection into student queries."""

    def test_injects_kb_prefix(self, scheduler):
        result = scheduler.inject_kb_query("How to add fractions?", "P4-P6")
        assert "[dreamer-ethical-ai]" in result
        assert "[student-query]" in result
        assert "How to add fractions?" in result
        assert "[/student-query]" in result

    def test_injects_without_age_band(self, scheduler):
        result = scheduler.inject_kb_query("Hello")
        assert "[dreamer-ethical-ai]" in result
        assert "[student-query]" in result
        assert "age-band" not in result

    def test_cantonese_query(self, scheduler):
        result = scheduler.inject_kb_query("點樣計數？", "P1-P3")
        assert "點樣計數？" in result


class TestKidSafeWrap:
    """Response pipeline: DeepTutor → KidSafe → student."""

    def test_wraps_response(self, scheduler):
        result = scheduler.kid_safe_wrap(
            "That is wrong.", "P4-P6", "en",
        )
        assert "wrong" not in result.lower()
        assert len(result) > 0

    def test_wraps_with_session(self, scheduler):
        session = SessionState(lang_code="en")
        result = scheduler.kid_safe_wrap(
            "Hello", "P4-P6", "en", session=session,
        )
        assert session.turns == 1
        assert "Hello" in result

    def test_session_wrap_at_turn_7(self, scheduler):
        session = SessionState(lang_code="en")
        # Simulate 6 prior turns
        for _ in range(6):
            session.increment()
        session.add_topic("Math", "achieved")

        result = scheduler.kid_safe_wrap(
            "Good work", "P4-P6", "en", session=session,
        )
        assert session.turns == 7
        assert "That's all" in result  # wrap message appended

    def test_s1_s3_passthrough(self, scheduler):
        text = "Detailed academic response with advanced reasoning."
        result = scheduler.kid_safe_wrap(text, "S1-S3", "en")
        assert result == text

    def test_s1_s3_strips_anxiety(self, scheduler):
        result = scheduler.kid_safe_wrap(
            "You'll fail the exam. Here is the solution.",
            "S1-S3", "en",
        )
        assert "fail the exam" not in result.lower()
        assert "solution" in result.lower()

    def test_cantonese(self, scheduler):
        result = scheduler.kid_safe_wrap(
            "你答錯咗", "P4-P6", "zh-hk",
        )
        assert len(result) > 0

    def test_mandarin(self, scheduler):
        result = scheduler.kid_safe_wrap(
            "你错了", "P1-P3", "zh-cn",
        )
        assert len(result) > 0


class TestKidSafeError:
    """Error path: bypasses middleware, uses templates."""

    def test_returns_friendly_message(self, scheduler):
        result = scheduler.kid_safe_error(
            "Internal 500 error", "server_error", "P1-P3", "en",
        )
        assert isinstance(result, str)
        assert len(result) > 10
        # Raw error should NOT leak to student
        assert "Internal 500" not in result

    def test_different_age_different_message(self, scheduler):
        r1 = scheduler.kid_safe_error("error", "server_error", "P1-P3", "en")
        r2 = scheduler.kid_safe_error("error", "server_error", "S1-S3", "en")
        assert r1 != r2

    @pytest.mark.parametrize("age_band", ["P1-P3", "P4-P6", "S1-S3"])
    @pytest.mark.parametrize("lang_code", ["en", "zh-hk", "zh-cn"])
    def test_all_combinations(self, scheduler, age_band, lang_code):
        result = scheduler.kid_safe_error("err", "ws_error", age_band, lang_code)
        assert isinstance(result, str)
        assert len(result) > 5
