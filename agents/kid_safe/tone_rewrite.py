"""
Dreamer AI Phase 2.3 — Tone Rewrite

Rule-based tone adjustment for kid-safe output.
Zero LLM — all rules driven by config/kid_safe_tone_rules.json.

Pipeline:
  1. Strip sarcasm patterns
  2. Strip grade-anxiety patterns
  3. Keyword replacement (negative → positive framing)
  4. Word count trim (per age band limit)
  5. Encouragement prefix (every N turns)

Age band rules:
  P1-P3: ≤10 words, encouragement every 2 turns, no sarcasm
  P4-P6: ≤15 words, positive framing, avoid "wrong"
  S1-S3: full sentences, constructive critique, no grade anxiety
  (S1-S3 has no word limit or encouragement — raw adult-level output preserved)
"""

import json
import os
import random
import re
from typing import Dict, List, Optional, Tuple

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "kid_safe_tone_rules.json"
)

# ── Lazy-load config ───────────────────────────────────

_config: Optional[Dict] = None


def _load_config() -> Dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = json.load(f)
    return _config


# ── Public API ─────────────────────────────────────────


def rewrite_tone(
    text: str,
    age_band: str,
    lang_code: str,
    turn_count: int = 0,
) -> str:
    """Apply kid-safe tone rules to a response text.

    Args:
        text: Raw DeepTutor response text.
        age_band: "P1-P3", "P4-P6", or "S1-S3".
        lang_code: "en", "zh-hk", or "zh-cn".
        turn_count: Current session turn number (0-indexed).
                    Used for encouragement insertion cadence.

    Returns:
        Tone-adjusted text string.
    """
    cfg = _load_config()
    band_cfg = cfg.get("age_bands", {}).get(age_band, {})

    result = text

    # S1-S3: only grade-anxiety stripping, no other modifications
    if age_band == "S1-S3":
        result = _strip_grade_anxiety(result, lang_code, cfg)
        return result

    # Full pipeline for P1-P6
    result = _strip_sarcasm(result, lang_code, cfg)
    result = _strip_grade_anxiety(result, lang_code, cfg)
    result = _replace_keywords(result, lang_code, cfg)
    result = _trim_words(result, band_cfg.get("max_words", 0))
    result = _insert_encouragement(result, age_band, lang_code, turn_count, cfg)

    return result


# ── Internal pipeline steps ────────────────────────────


def _strip_sarcasm(text: str, lang_code: str, cfg: Dict) -> str:
    """Remove known sarcasm patterns from text."""
    patterns = cfg.get("sarcasm_patterns", {}).get(lang_code, [])
    for phrase in patterns:
        # Case-insensitive for EN, exact for CJK
        if lang_code == "en":
            text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
        else:
            text = text.replace(phrase, "")
    # Collapse multiple spaces from removals
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def _strip_grade_anxiety(text: str, lang_code: str, cfg: Dict) -> str:
    """Remove grade-anxiety-inducing phrases."""
    patterns = cfg.get("grade_anxiety_patterns", {}).get(lang_code, [])
    for phrase in patterns:
        if lang_code == "en":
            text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
        else:
            text = text.replace(phrase, "")
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def _replace_keywords(text: str, lang_code: str, cfg: Dict) -> str:
    """Replace negative keywords with positive framing."""
    replacements = cfg.get("keyword_replacements", {}).get(lang_code, {})
    if not replacements:
        return text

    # Sort by length descending to replace longer phrases first
    # (e.g., "you don't know" before "don't")
    sorted_keys = sorted(replacements.keys(), key=len, reverse=True)

    for word in sorted_keys:
        replacement = replacements[word]
        if lang_code == "en":
            # Word-boundary replacement for English
            text = re.sub(
                r"\b" + re.escape(word) + r"\b",
                replacement,
                text,
                flags=re.IGNORECASE,
            )
        else:
            # Direct substring for CJK
            text = text.replace(word, replacement)

    return text


def _trim_words(text: str, max_words: int) -> str:
    """Trim text to max_words. If 0, pass through unchanged."""
    if max_words <= 0:
        return text

    words = text.split()
    if len(words) <= max_words:
        return text

    # Truncate and add ellipsis-style ending
    trimmed = " ".join(words[:max_words])
    if not trimmed.rstrip().endswith((".", "!", "?", "~", "…", "。")):
        trimmed += "…"
    return trimmed


def _insert_encouragement(
    text: str,
    age_band: str,
    lang_code: str,
    turn_count: int,
    cfg: Dict,
) -> str:
    """Insert encouragement prefix on cadence turns."""
    band_cfg = cfg.get("age_bands", {}).get(age_band, {})
    interval = band_cfg.get("encouragement_interval", 0)
    if interval <= 0:
        return text

    # Only insert on interval-boundary turns (1-indexed: turn_count 0 = first turn)
    if (turn_count + 1) % interval != 0:
        return text

    pool = band_cfg.get("encouragement_pool", {}).get(lang_code, [])
    if not pool:
        return text

    encouragement = random.choice(pool)
    if lang_code in ("zh-hk", "zh-cn"):
        # CJK: no space separator needed
        return f"{encouragement}{text}"
    else:
        return f"{encouragement} {text}"


# ── Convenience ────────────────────────────────────────

ALL_AGE_BANDS = ["P1-P3", "P4-P6", "S1-S3"]
ALL_LANG_CODES = ["en", "zh-hk", "zh-cn"]
