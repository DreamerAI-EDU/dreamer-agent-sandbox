"""Test session_wrap — 7-turn wrap messages with topics in 3 languages."""

import pytest
from agents.kid_safe.session_wrap import (
    SessionState,
    TopicSummary,
    generate_wrap,
    is_wrap_turn,
    SESSION_WRAP_TURN,
    EN, ZH_HK, ZH_CN,
)


class TestIsWrapTurn:
    """Wrap trigger logic."""

    def test_below_threshold(self):
        assert is_wrap_turn(0) is False
        assert is_wrap_turn(1) is False
        assert is_wrap_turn(6) is False

    def test_at_threshold(self):
        assert is_wrap_turn(7) is True

    def test_above_threshold(self):
        assert is_wrap_turn(8) is True
        assert is_wrap_turn(50) is True

    def test_turn_count_constant(self):
        assert SESSION_WRAP_TURN == 7


class TestSessionState:
    """Session state tracking."""

    def test_initial_state(self):
        s = SessionState()
        assert s.turns == 0
        assert s.topics == []
        assert s.lang_code == EN
        assert s.should_wrap() is False

    def test_increment(self):
        s = SessionState()
        for _ in range(7):
            s.increment()
        assert s.turns == 7
        assert s.should_wrap() is True

    def test_add_topic(self):
        s = SessionState()
        s.add_topic("Fractions", "developing")
        assert len(s.topics) == 1
        assert s.topics[0].topic == "Fractions"
        assert s.topics[0].label_key == "developing"

    def test_should_wrap_at_turn_7(self):
        s = SessionState()
        for _ in range(7):
            s.increment()
        assert s.should_wrap() is True


class TestGenerateWrap:
    """Wrap message generation."""

    def test_english_basic(self):
        s = SessionState(lang_code=EN, turns=7)
        s.add_topic("Math", "achieved")
        result = generate_wrap(s)
        assert "That's all" in result
        assert "Math" in result
        assert "Keep exploring" in result

    def test_english_no_topics(self):
        s = SessionState(lang_code=EN, turns=7)
        result = generate_wrap(s)
        assert "That's all" in result
        assert "great chat today" in result

    def test_cantonese_basic(self):
        s = SessionState(lang_code=ZH_HK, turns=7)
        s.add_topic("數學", "achieved")
        result = generate_wrap(s)
        assert "學習環節" in result
        assert "數學" in result
        assert "下次再見" in result

    def test_cantonese_no_topics(self):
        s = SessionState(lang_code=ZH_HK, turns=7)
        result = generate_wrap(s)
        assert "傾得好開心" in result

    def test_mandarin_basic(self):
        s = SessionState(lang_code=ZH_CN, turns=7)
        s.add_topic("数学", "developing")
        result = generate_wrap(s)
        assert "学习环节" in result
        assert "数学" in result
        assert "下次再见" in result

    def test_mandarin_no_topics(self):
        s = SessionState(lang_code=ZH_CN, turns=7)
        result = generate_wrap(s)
        assert "聊得很开心" in result

    def test_unknown_language_falls_back_to_en(self):
        s = SessionState(lang_code="fr", turns=7)
        result = generate_wrap(s)
        assert "That's all" in result

    def test_override_language(self):
        s = SessionState(lang_code=EN, turns=7)
        result = generate_wrap(s, lang_code=ZH_HK)
        assert "學習環節" in result

    def test_multiple_topics(self):
        s = SessionState(lang_code=EN, turns=7)
        s.add_topic("Fractions", "developing")
        s.add_topic("AI Ethics", "achieved")
        s.add_topic("Python Loops", "not_yet")
        result = generate_wrap(s)
        assert "Fractions" in result
        assert "AI Ethics" in result
        assert "Python Loops" in result
        # Should not repeat header/footer per topic
        assert result.count("That's all") == 1
        assert result.count("Keep exploring") == 1

    def test_non_wrap_turn_still_generates(self):
        """generate_wrap works regardless of turn count (caller decides when)."""
        s = SessionState(lang_code=EN, turns=3)
        result = generate_wrap(s)
        assert "That's all" in result  # Still generates

    def test_result_is_non_empty_string(self):
        for lang in [EN, ZH_HK, ZH_CN]:
            s = SessionState(lang_code=lang, turns=7)
            s.add_topic("Test", "achieved")
            result = generate_wrap(s)
            assert isinstance(result, str)
            assert len(result) > 20
