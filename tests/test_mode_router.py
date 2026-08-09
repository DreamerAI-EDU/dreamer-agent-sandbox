"""
Dreamer AI Phase 4 — Mode Router tests (Day 19)
"""

import pytest

from agents.mode_router import ModeRouter, Mode, _has_cjk, _count_script_indicators


# ── Fixture ─────────────────────────────────────────────

@pytest.fixture
def router():
    return ModeRouter()


# ── Language Detection ──────────────────────────────────

class TestLanguageDetection:
    """detect_language() → en / zh-hk / zh-cn"""

    @pytest.mark.parametrize("text,expected", [
        ("hello world", "en"),
        ("I want to revise for my exam", "en"),
        ("project mode, help me study", "en"),
        ("AI tutor please", "en"),
    ])
    def test_detect_en(self, router, text, expected):
        assert router.detect_language(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("我想溫書", "zh-hk"),
        ("幫我溫習準備測驗", "zh-hk"),
        ("整遊戲", "zh-hk"),
        ("用AI幫我溫書", "zh-hk"),
        ("點樣用AI做功課", "zh-hk"),
    ])
    def test_detect_zh_hk(self, router, text, expected):
        assert router.detect_language(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("我想复习准备考试", "zh-cn"),
        ("做游戏设计项目", "zh-cn"),
        ("用AI帮我复习", "zh-cn"),
    ])
    def test_detect_zh_cn(self, router, text, expected):
        assert router.detect_language(text) == expected

    def test_detect_empty_defaults_zh_hk(self, router):
        assert router.detect_language("") == "zh-hk"
        assert router.detect_language("   ") == "zh-hk"

    def test_detect_pure_numbers_en(self, router):
        assert router.detect_language("123 456") == "en"

    def test_detect_pure_emoji_en(self, router):
        assert router.detect_language("😀🎉👍") == "en"


# ── Explicit Override ───────────────────────────────────

class TestOverride:
    """check_override() → Mode | None"""

    def test_override_direct_en(self, router):
        assert router.check_override("exam mode", "en") == Mode.DIRECT
        assert router.check_override("test mode please", "en") == Mode.DIRECT

    def test_override_direct_zh_hk(self, router):
        assert router.check_override("測驗模式", "zh-hk") == Mode.DIRECT
        assert router.check_override("用考試模式", "zh-hk") == Mode.DIRECT

    def test_override_direct_zh_cn(self, router):
        assert router.check_override("测验模式", "zh-cn") == Mode.DIRECT

    def test_override_contextual_en(self, router):
        assert router.check_override("project mode", "en") == Mode.CONTEXTUAL
        assert router.check_override("creative mode", "en") == Mode.CONTEXTUAL

    def test_override_contextual_zh_hk(self, router):
        assert router.check_override("項目模式", "zh-hk") == Mode.CONTEXTUAL

    def test_override_contextual_zh_cn(self, router):
        assert router.check_override("项目模式", "zh-cn") == Mode.CONTEXTUAL

    def test_no_override_normal_text(self, router):
        assert router.check_override("hello world", "en") is None
        assert router.check_override("我想溫書", "zh-hk") is None


# ── Mode Match ──────────────────────────────────────────

class TestModeMatch:
    """match_mode() → Mode enum"""

    # zh-hk DIRECT
    @pytest.mark.parametrize("text", [
        "我想溫書準備測驗",
        "幫我溫習考試範圍",
        "做功課要交啦",
        "教我數學",
    ])
    def test_match_direct_zh_hk(self, router, text):
        assert router.match_mode(text, "zh-hk") == Mode.DIRECT

    # zh-hk CONTEXTUAL
    @pytest.mark.parametrize("text", [
        "我想整一個遊戲",
        "我想設計一個app",
        "探索AI可以點樣幫手",
        "試下做個動畫",
    ])
    def test_match_contextual_zh_hk(self, router, text):
        assert router.match_mode(text, "zh-hk") == Mode.CONTEXTUAL

    # zh-hk HYBRID
    @pytest.mark.parametrize("text", [
        "用AI幫我溫書",
        "AI做功課",
        "AI補習數學",
        "AI教我英文",
    ])
    def test_match_hybrid_zh_hk(self, router, text):
        assert router.match_mode(text, "zh-hk") == Mode.HYBRID

    # en DIRECT
    @pytest.mark.parametrize("text", [
        "help me study for the exam",
        "I have a test tomorrow",
        "can you teach me math",
        "practice questions for revision",
    ])
    def test_match_direct_en(self, router, text):
        assert router.match_mode(text, "en") == Mode.DIRECT

    # en CONTEXTUAL
    @pytest.mark.parametrize("text", [
        "I want to make a game",
        "build a project with AI",
        "explore how AI works",
        "write a story about dragons",
    ])
    def test_match_contextual_en(self, router, text):
        assert router.match_mode(text, "en") == Mode.CONTEXTUAL

    # en HYBRID
    @pytest.mark.parametrize("text", [
        "use AI to revise my homework",
        "can AI help me with studying",
        "AI tutor for math",
        "use AI for homework",
    ])
    def test_match_hybrid_en(self, router, text):
        assert router.match_mode(text, "en") == Mode.HYBRID

    # zh-cn DIRECT
    @pytest.mark.parametrize("text", [
        "我想复习准备考试",
        "帮我做练习题",
    ])
    def test_match_direct_zh_cn(self, router, text):
        assert router.match_mode(text, "zh-cn") == Mode.DIRECT

    # zh-cn CONTEXTUAL
    @pytest.mark.parametrize("text", [
        "我想设计一个游戏",
        "探索AI可以做什么",
    ])
    def test_match_contextual_zh_cn(self, router, text):
        assert router.match_mode(text, "zh-cn") == Mode.CONTEXTUAL

    # zh-cn HYBRID
    @pytest.mark.parametrize("text", [
        "用AI帮我复习",
        "AI辅导数学",
    ])
    def test_match_hybrid_zh_cn(self, router, text):
        assert router.match_mode(text, "zh-cn") == Mode.HYBRID

    def test_fallback_contextual_no_hits(self, router):
        assert router.match_mode("hello world", "en") == Mode.CONTEXTUAL
        assert router.match_mode("今日天氣好好", "zh-hk") == Mode.CONTEXTUAL


# ── Full Route ──────────────────────────────────────────

class TestRoute:
    """route() → (Mode, lang_code)"""

    def test_route_direct_zh_hk(self, router):
        mode, lang = router.route("我想溫書準備測驗")
        assert mode == Mode.DIRECT
        assert lang == "zh-hk"

    def test_route_contextual_en(self, router):
        mode, lang = router.route("I want to make a game")
        assert mode == Mode.CONTEXTUAL
        assert lang == "en"

    def test_route_hybrid_mixed(self, router):
        """中英夾雜 input → HYBRID"""
        mode, lang = router.route("用AI幫我溫書")
        assert mode == Mode.HYBRID
        assert lang == "zh-hk"

    def test_route_override_wins_over_keyword(self, router):
        """Override 「測驗模式」wins even with contextual keywords present"""
        mode, lang = router.route("測驗模式，我想整遊戲")
        assert mode == Mode.DIRECT
        assert lang == "zh-hk"

    def test_route_override_en_wins_over_keyword(self, router):
        mode, lang = router.route("project mode, I want to revise for exam")
        assert mode == Mode.CONTEXTUAL
        assert lang == "en"

    def test_route_fallback_empty_string(self, router):
        mode, lang = router.route("")
        assert mode == Mode.CONTEXTUAL
        assert lang == "zh-hk"

    def test_route_fallback_pure_emoji(self, router):
        mode, lang = router.route("🎉👍😀")
        assert mode == Mode.CONTEXTUAL
        # Pure emoji → no CJK → detect as 'en', fallback still CONTEXTUAL

    def test_route_fallback_pure_numbers(self, router):
        mode, lang = router.route("12345")
        assert mode == Mode.CONTEXTUAL
        assert lang == "en"

    def test_route_both_direct_contextual_hybrid(self, router):
        """Text with both direct + contextual keywords → HYBRID"""
        mode, lang = router.route("help me study and build a project")
        assert mode == Mode.HYBRID


# ── Edge Cases ──────────────────────────────────────────

class TestEdgeCases:
    """Boundary / edge case tests"""

    def test_en_word_boundary_no_false_positive(self, router):
        """'latest news' should NOT match DIRECT ('test' as substring)"""
        mode, lang = router.route("latest news about AI")
        assert mode != Mode.DIRECT
        # "AI" alone is a hybrid keyword → HYBRID or fallback CONTEXTUAL
        assert mode in (Mode.CONTEXTUAL, Mode.HYBRID)

    def test_en_word_boundary_test(self, router):
        """'test' as standalone word should match DIRECT"""
        mode, _ = router.route("I have a test next week")
        assert mode == Mode.DIRECT

    def test_no_exception_on_null_bytes(self, router):
        """Should handle unusual input without throwing"""
        mode, lang = router.route("\x00")
        assert mode == Mode.CONTEXTUAL

    def test_no_exception_on_very_long_text(self, router):
        long_text = "測驗 " * 1000
        mode, lang = router.route(long_text)
        assert mode == Mode.DIRECT
        assert lang == "zh-hk"

    def test_config_loads_once(self, router):
        """Config should be cached after first access"""
        config1 = router.config
        config2 = router.config
        assert config1 is config2


# ── Helpers ─────────────────────────────────────────────

class TestHelpers:
    def test_has_cjk_true(self):
        assert _has_cjk("測驗") is True
        assert _has_cjk("hello 你好 world") is True

    def test_has_cjk_false(self):
        assert _has_cjk("hello world") is False
        assert _has_cjk("12345") is False

    def test_count_script_indicators_traditional(self, router):
        si = router.config.get("script_indicators", {})
        simp, trad = _count_script_indicators(
            "我想溫書準備測驗",
            set(si.get("zh-cn", [])),
            set(si.get("zh-hk", [])),
        )
        assert trad > simp

    def test_count_script_indicators_simplified(self, router):
        si = router.config.get("script_indicators", {})
        simp, trad = _count_script_indicators(
            "我想复习准备测验",
            set(si.get("zh-cn", [])),
            set(si.get("zh-hk", [])),
        )
        assert simp > trad


# ── Script Indicator (Check 5) ──────────────────────────

class TestScriptIndicator:
    """Script indicator tie-break for neutral / mixed sentences"""

    def test_neutral_simplified_zh_cn(self, router):
        """'今天天气很好' has '气' → zh-cn, not zh-hk"""
        assert router.detect_language("今天天气很好") == "zh-cn"

    def test_truly_neutral_defaults_zh_hk(self, router):
        """'我愛你' no indicator in either set → default zh-hk"""
        assert router.detect_language("我愛你") == "zh-hk"

    def test_mixed_script_scoring(self, router):
        """'我今日去學校温习' has trad + simp → scoring decides"""
        lang = router.detect_language("我今日去學校温习")
        # 校 = both, 學 = trad, 温 = simp, 习 = simp
        # trad count: '學' → 1; simp count: '温' '习' → 2 → zh-cn wins
        assert lang == "zh-cn"


# ── Config Injection (Check 6.1) ────────────────────────

class TestConfigInjection:
    """Unit tests with injected fake config (isolation)"""

    def test_fake_config_determines_route(self, tmp_path):
        import json
        fake = {
            "mode_keywords": {
                "direct": {"en": ["quiz"]},
                "contextual": {"en": []},
                "hybrid": {"en": []},
            },
            "explicit_mode_overrides": {
                "direct": {"en": []},
                "contextual": {"en": []},
            },
            "languages": {"en": {}, "zh-hk": {}, "zh-cn": {}},
            "script_indicators": {"zh-cn": [], "zh-hk": []},
        }
        cfg = tmp_path / "fake_config.json"
        cfg.write_text(json.dumps(fake), encoding="utf-8")

        from agents.mode_router import ModeRouter as MR
        r = MR(config_path=str(cfg))
        mode, lang = r.route("quiz me please")
        assert mode == Mode.DIRECT
        assert lang == "en"

    def test_fake_config_no_keywords_fallback(self, tmp_path):
        import json
        fake = {
            "mode_keywords": {
                "direct": {"en": []},
                "contextual": {"en": []},
                "hybrid": {"en": []},
            },
            "explicit_mode_overrides": {
                "direct": {"en": []},
                "contextual": {"en": []},
            },
            "languages": {"en": {}, "zh-hk": {}, "zh-cn": {}},
            "script_indicators": {"zh-cn": [], "zh-hk": []},
        }
        cfg = tmp_path / "fake_empty.json"
        cfg.write_text(json.dumps(fake), encoding="utf-8")

        from agents.mode_router import ModeRouter as MR
        r = MR(config_path=str(cfg))
        mode, lang = r.route("hello world")
        assert mode == Mode.CONTEXTUAL  # fallback


# ── Config Integrity (Check 6.2) ────────────────────────

class TestConfigIntegrity:
    """Structural validation of real cantonese_keyword_config.json"""

    def test_top_level_keys_present(self, router):
        c = router.config
        for key in ("mode_keywords", "explicit_mode_overrides",
                     "languages", "script_indicators"):
            assert key in c, f"Missing top-level key: {key}"

    def test_mode_keywords_three_langs_nonempty(self, router):
        mk = router.config["mode_keywords"]
        for mode_cat in ("direct", "contextual", "hybrid"):
            for lang in ("en", "zh-hk", "zh-cn"):
                kw = mk[mode_cat][lang]
                assert isinstance(kw, list), \
                    f"{mode_cat}.{lang} not a list"
                assert len(kw) > 0, \
                    f"{mode_cat}.{lang} is empty"

    def test_explicit_overrides_three_langs_nonempty(self, router):
        ov = router.config["explicit_mode_overrides"]
        for mode_cat in ("direct", "contextual"):
            for lang in ("en", "zh-hk", "zh-cn"):
                kw = ov[mode_cat][lang]
                assert isinstance(kw, list), \
                    f"override {mode_cat}.{lang} not a list"
                assert len(kw) > 0, \
                    f"override {mode_cat}.{lang} is empty"

    def test_script_indicators_both_langs_nonempty(self, router):
        si = router.config["script_indicators"]
        for lang in ("zh-cn", "zh-hk"):
            assert lang in si, f"Missing script_indicators.{lang}"
            assert len(si[lang]) > 0, \
                f"script_indicators.{lang} is empty"

    def test_languages_three_keys(self, router):
        langs = router.config["languages"]
        for lang in ("en", "zh-hk", "zh-cn"):
            assert lang in langs, f"Missing languages.{lang}"
