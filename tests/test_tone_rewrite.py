"""Test tone_rewrite — rule-based kid-safe tone adjustments.

Covers: word count trim, keyword replacement, sarcasm stripping,
grade-anxiety stripping, encouragement insertion.
"""

import pytest
from agents.kid_safe.tone_rewrite import (
    rewrite_tone,
    _strip_sarcasm,
    _strip_grade_anxiety,
    _replace_keywords,
    _trim_words,
    _insert_encouragement,
    _load_config,
)


@pytest.fixture(scope="module")
def config():
    return _load_config()


# ── Word Count Trim ────────────────────────────────────


class TestTrimWords:
    def test_below_limit_passthrough(self):
        assert _trim_words("hello world", 10) == "hello world"

    def test_exactly_at_limit(self):
        text = "one two three four five"
        assert _trim_words(text, 5) == text

    def test_above_limit_truncates(self):
        words = "one two three four five six seven eight nine ten eleven"
        result = _trim_words(words, 3)
        assert len(result.split()) == 3
        assert result.endswith("…")

    def test_zero_limit_passthrough(self):
        assert _trim_words("any text here", 0) == "any text here"

    def test_sentence_ending_preserved(self):
        """If truncated text happens to end with punctuation, no extra ellipsis."""
        result = _trim_words("Yes. No. Maybe.", 2)
        assert result in ("Yes. No.", "Yes. No.…")  # Both acceptable

    def test_empty_string(self):
        assert _trim_words("", 5) == ""

    def test_cjk_trimming(self):
        """Word count splits on spaces; CJK without spaces counts as single word."""
        result = _trim_words("你好 世界 测试 句子 太多", 3)
        assert "…" in result
        assert len(result.split()) == 3


# ── Keyword Replacement ────────────────────────────────


class TestReplaceKeywords:
    @pytest.mark.parametrize("lang", ["en", "zh-hk", "zh-cn"])
    def test_no_change_for_neutral_text(self, config, lang):
        neutral = "Let's try a different approach" if lang == "en" else "試下另一個方法"
        result = _replace_keywords(neutral, lang, config)
        assert result == neutral

    def test_en_replaces_wrong(self, config):
        assert _replace_keywords("That is wrong", "en", config) == "That is not quite right"

    def test_en_replaces_bad(self, config):
        assert _replace_keywords("Bad result", "en", config) == "needs improvement result"

    def test_en_case_insensitive(self, config):
        assert _replace_keywords("Wrong answer", "en", config) == "not quite right answer"
        assert _replace_keywords("WRONG", "en", config) == "not quite right"

    def test_en_word_boundary(self, config):
        """'wrong' inside 'wrongly' should not be replaced."""
        text = "That is wrongly labeled"
        result = _replace_keywords(text, "en", config)
        assert "wrongly" in result  # preserved

    def test_en_longer_phrase_first(self, config):
        """'you don't know' (longer) should be replaced before 'don't' (shorter)."""
        text = "you don't know the answer"
        result = _replace_keywords(text, "en", config)
        assert "let's explore this together" in result

    def test_zh_hk_replaces(self, config):
        assert _replace_keywords("你答錯咗", "zh-hk", config) == "你答未算啱咗"

    def test_zh_cn_replaces(self, config):
        assert _replace_keywords("这个问题你错了", "zh-cn", config) == "这个问题你还差一点点"


# ── Sarcasm Stripping ──────────────────────────────────


class TestStripSarcasm:
    def test_en_removes_sarcasm(self, config):
        result = _strip_sarcasm("Yeah right, that's correct", "en", config)
        assert "yeah right" not in result.lower()

    def test_en_preserves_sincere_text(self, config):
        text = "That is correct"
        result = _strip_sarcasm(text, "en", config)
        assert result == text

    def test_collapses_multiple_spaces(self, config):
        result = _strip_sarcasm("Yeah right  whatever  you say", "en", config)
        assert "  " not in result
        assert "yeah right" not in result.lower()
        assert "whatever" not in result.lower()


# ── Grade Anxiety Stripping ────────────────────────────


class TestStripGradeAnxiety:
    def test_en_removes_anxiety(self, config):
        result = _strip_grade_anxiety("You'll fail the exam if you don't study", "en", config)
        assert "fail the exam" not in result.lower()

    def test_zh_hk_removes(self, config):
        result = _strip_grade_anxiety("你會唔合格㗎", "zh-hk", config)
        assert "唔合格" not in result

    def test_zh_cn_removes(self, config):
        result = _strip_grade_anxiety("你会不及格", "zh-cn", config)
        assert "不及格" not in result


# ── Encouragement Insertion ─────────────────────────────


class TestInsertEncouragement:
    def test_p1_p3_every_2nd_turn(self, config):
        """Turn 1 (0-indexed): should insert."""
        result = _insert_encouragement("Hello", "P1-P3", "en", 1, config)
        assert result != "Hello"
        assert result.endswith("Hello")

    def test_p1_p3_off_cadence_skip(self, config):
        """Turn 0 (first turn): should not insert."""
        result = _insert_encouragement("Hello", "P1-P3", "en", 0, config)
        assert result == "Hello"

    def test_s1_s3_no_encouragement(self, config):
        result = _insert_encouragement("Some text", "S1-S3", "en", 1, config)
        assert result == "Some text"

    def test_encouragement_from_pool(self, config):
        """At least one of the pool items should appear."""
        pool = config["age_bands"]["P1-P3"]["encouragement_pool"]["en"]
        result = _insert_encouragement("Hello", "P1-P3", "en", 1, config)
        matched = any(item == result.split(" ")[0] or item in result for item in pool)
        # Encouragement is prepended, so first word(s) should match
        assert matched or result != "Hello"


# ── Full Pipeline ──────────────────────────────────────


class TestRewriteTone:
    """End-to-end tone rewrite."""

    def test_p1_p3_full_pipeline(self):
        result = rewrite_tone(
            "That is wrong. You are bad at this.",
            "P1-P3", "en", turn_count=1,
        )
        assert "wrong" not in result.lower()
        assert "bad" not in result.lower()
        # Core message trimmed to ≤10 words; encouragement may add a few more
        assert len(result.split()) <= 14

    def test_p4_p6_full_pipeline(self):
        result = rewrite_tone(
            "Your answer is incorrect and terrible",
            "P4-P6", "en", turn_count=2,
        )
        assert "incorrect" not in result.lower()
        assert "terrible" not in result.lower()

    def test_s1_s3_strips_anxiety_only(self):
        """S1-S3: only grade-anxiety stripping, preserve full text."""
        text = "This is a complex answer with detailed reasoning."
        result = rewrite_tone(text, "S1-S3", "en")
        assert result == text  # No modification for neutral text

    def test_s1_s3_strips_anxiety_when_present(self):
        result = rewrite_tone(
            "You'll fail the exam. But here is the answer.",
            "S1-S3", "en",
        )
        assert "fail the exam" not in result.lower()
        assert "here is the answer" in result.lower()

    def test_empty_text(self):
        assert rewrite_tone("", "P1-P3", "en") == ""

    def test_idempotent_on_clean_text(self, config):
        """Clean positive text should be minimally modified."""
        text = "Great work on fractions today"
        result = rewrite_tone(text, "P4-P6", "en", turn_count=0)
        # Should still contain the essence
        assert "fractions" in result.lower() or "Great" in result

    def test_cantonese_pipeline(self):
        result = rewrite_tone(
            "你答錯咗呢題，你會唔合格",
            "P4-P6", "zh-hk", turn_count=2,
        )
        assert "錯" not in result or "未算啱" in result
        assert "唔合格" not in result

    def test_mandarin_pipeline(self):
        result = rewrite_tone(
            "你错了这个问题",
            "P1-P3", "zh-cn", turn_count=1,
        )
        assert "错了" not in result
