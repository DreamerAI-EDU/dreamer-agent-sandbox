"""
Dreamer AI Phase 4 — Mode Router (Day 19)
Deterministic keyword-based mode routing engine.
Zero LLM dependency. All keywords externalized to config JSON.

Usage:
    router = ModeRouter()
    mode, lang = router.route("我想溫書準備測驗")
    # → (Mode.DIRECT, "zh-hk")
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Mode(Enum):
    DIRECT = "DIRECT"
    CONTEXTUAL = "CONTEXTUAL"
    HYBRID = "HYBRID"


# ── CJK detection ───────────────────────────────────────

_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0x2E80, 0x2EFF),   # CJK Radicals Supplement
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
]


def _has_cjk(text: str) -> bool:
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in _CJK_RANGES)
        for ch in text
    )


# ── Script detection ────────────────────────────────────

# Script indicators are externalized to config/cantonese_keyword_config.json
# (script_indicators key). Functions below accept character sets as parameters
# to support config injection in tests.


def _count_script_indicators(
    text: str, simp_set: set, trad_set: set
) -> Tuple[int, int]:
    simp = sum(1 for ch in text if ch in simp_set)
    trad = sum(1 for ch in text if ch in trad_set)
    return simp, trad


# ── Keyword matching helpers ────────────────────────────

def _match_en_keywords(text: str, keywords: List[str]) -> bool:
    """Case-insensitive word-boundary match for English keywords."""
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        # Multi-word phrase: substring match
        if " " in kw_lower:
            if kw_lower in text_lower:
                return True
        else:
            # Single word: word boundary match
            pattern = re.compile(rf"(?<![a-zA-Z]){re.escape(kw_lower)}(?![a-zA-Z])")
            if pattern.search(text_lower):
                return True
    return False


def _match_zh_keywords(text: str, keywords: List[str]) -> bool:
    """Substring match for Chinese keywords (no word boundaries)."""
    for kw in keywords:
        if kw in text:
            return True
    return False


def _match_keywords(
    text: str, keywords: List[str], lang: str
) -> bool:
    """Dispatch keyword matching based on language script."""
    if lang == "en":
        return _match_en_keywords(text, keywords)
    return _match_zh_keywords(text, keywords)


# ── ModeRouter ─────────────────────────────────────────

class ModeRouter:
    """Deterministic mode router using keyword config.

    Config path is injectable for testing. Lazy-loaded and cached.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or self._default_config_path()
        self._config: Optional[dict] = None
        self._last_matched_keyword: Optional[str] = None

    @staticmethod
    def _default_config_path() -> str:
        return os.path.join(
            os.path.dirname(__file__), "..", "config",
            "cantonese_keyword_config.json",
        )

    @property
    def config(self) -> dict:
        if self._config is None:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        return self._config

    # ── Language Detection ──────────────────────────

    def detect_language(self, text: str) -> str:
        """Detect primary language of text.

        Returns:
            'en'  — pure Latin / no CJK characters
            'zh-hk' — traditional Chinese or ambiguous (HK primary market default)
            'zh-cn' — simplified Chinese (when clearly indicated)
        """
        if not text or not text.strip():
            return "zh-hk"  # default for empty

        if not _has_cjk(text):
            return "en"

        # Has CJK — distinguish zh-hk vs zh-cn
        languages = self.config.get("languages", {})
        mode_kw = self.config.get("mode_keywords", {})

        # Count keyword hits per zh variant
        zh_hk_hits = 0
        zh_cn_hits = 0
        for mode_cat in mode_kw.values():
            zh_hk_hits += sum(
                1 for kw in mode_cat.get("zh-hk", []) if kw in text
            )
            zh_cn_hits += sum(
                1 for kw in mode_cat.get("zh-cn", []) if kw in text
            )

        # Count script indicators (externalized to config)
        script_ind = self.config.get("script_indicators", {})
        simp_set = set(script_ind.get("zh-cn", []))
        trad_set = set(script_ind.get("zh-hk", []))
        simp, trad = _count_script_indicators(text, simp_set, trad_set)

        # Decision logic
        zh_cn_score = zh_cn_hits * 2 + simp
        zh_hk_score = zh_hk_hits * 2 + trad

        if zh_cn_score > zh_hk_score:
            return "zh-cn"
        return "zh-hk"  # default: HK primary market

    # ── Explicit Override ───────────────────────────

    def check_override(self, text: str, lang: str) -> Optional[Mode]:
        """Check for explicit mode override phrases.

        Override keywords take highest priority per Plan §2 Routing Rules.
        「測驗模式」with contextual keywords → still DIRECT (override wins).

        Returns:
            Mode if an override is matched, None otherwise.
        """
        overrides = self.config.get("explicit_mode_overrides", {})

        # Check direct overrides
        direct_kw = overrides.get("direct", {}).get(lang, [])
        if _match_keywords(text, direct_kw, lang):
            return Mode.DIRECT

        # Check contextual overrides
        contextual_kw = overrides.get("contextual", {}).get(lang, [])
        if _match_keywords(text, contextual_kw, lang):
            return Mode.CONTEXTUAL

        return None

    # ── Keyword Mode Match ──────────────────────────

    def match_mode(self, text: str, lang: str) -> Mode:
        """Match keywords against text to determine mode.

        Priority (Plan §2.2):
          1. Both DIRECT + CONTEXTUAL keywords hit → HYBRID
          2. HYBRID keyword hit → HYBRID
          3. Only DIRECT → DIRECT
          4. Only CONTEXTUAL → CONTEXTUAL
          5. Zero hits → CONTEXTUAL (fallback)

        For CJK text (zh-*), English keywords are also checked
        (HK students commonly mix languages).
        """
        mode_kw = self.config.get("mode_keywords", {})

        # Collect keyword hits
        direct_kw = mode_kw.get("direct", {}).get(lang, [])
        contextual_kw = mode_kw.get("contextual", {}).get(lang, [])
        hybrid_kw = mode_kw.get("hybrid", {}).get(lang, [])

        # For zh-* languages, also check English keywords (mixed input)
        if lang.startswith("zh"):
            direct_kw = direct_kw + mode_kw.get("direct", {}).get("en", [])
            contextual_kw = contextual_kw + mode_kw.get("contextual", {}).get("en", [])
            hybrid_kw = hybrid_kw + mode_kw.get("hybrid", {}).get("en", [])

        direct_hit = _match_keywords(text, direct_kw, lang) or (
            lang.startswith("zh") and _match_en_keywords(
                text, mode_kw.get("direct", {}).get("en", [])
            )
        )
        contextual_hit = _match_keywords(text, contextual_kw, lang) or (
            lang.startswith("zh") and _match_en_keywords(
                text, mode_kw.get("contextual", {}).get("en", [])
            )
        )
        hybrid_hit = _match_keywords(text, hybrid_kw, lang) or (
            lang.startswith("zh") and _match_en_keywords(
                text, mode_kw.get("hybrid", {}).get("en", [])
            )
        )

        # Priority-based resolution
        if direct_hit and contextual_hit:
            return Mode.HYBRID
        if hybrid_hit:
            return Mode.HYBRID
        if direct_hit:
            return Mode.DIRECT
        if contextual_hit:
            return Mode.CONTEXTUAL

        return Mode.CONTEXTUAL  # fallback

    def route_with_trace(
        self,
        text: str,
        *,
        student_id: str = "",
        session_id: str = "",
    ) -> Tuple[Mode, str]:
        """Route with observability trace — stores matched keyword in instance state.

        Pure function: no DB side-effects. The caller (execute()) is
        responsible for emitting the routing event, not this router.
        Per Phase 5 red-line: route() behaviour is zero-change.

        Returns:
            (mode, lang_code) — identical to route().
        """
        self._last_matched_keyword = None
        mode_val, lang_code = self.route(text)

        # Extract the first matched keyword (without storing raw text)
        if text and text.strip():
            mode_kw = self.config.get("mode_keywords", {})
            all_kws: List[str] = []
            for cat in ("direct", "contextual", "hybrid"):
                for lc in (lang_code, "en"):
                    all_kws.extend(mode_kw.get(cat, {}).get(lc, []))
            for kw in all_kws:
                if kw.lower() in text.lower():
                    self._last_matched_keyword = kw
                    break

        return mode_val, lang_code


    # ── Full Route ───────────────────────────────────

    def route(self, text: str) -> Tuple[Mode, str]:
        """Full routing pipeline.

        1. Detect language
        2. Check explicit override (highest priority)
        3. Match keywords
        4. Return (mode, lang_code)

        Returns:
            Tuple of (Mode enum, language code string).
        """
        if not text or not text.strip():
            return Mode.CONTEXTUAL, "zh-hk"

        lang = self.detect_language(text)

        # Explicit override wins everything
        override = self.check_override(text, lang)
        if override is not None:
            # For override, also check en overrides if CJK text
            if lang.startswith("zh") and override is None:
                override = self.check_override(text, "en")
            return override, lang

        # For CJK text, also try en override keywords
        if lang.startswith("zh"):
            en_override = self.check_override(text, "en")
            if en_override is not None:
                return en_override, lang

        mode = self.match_mode(text, lang)
        return mode, lang
