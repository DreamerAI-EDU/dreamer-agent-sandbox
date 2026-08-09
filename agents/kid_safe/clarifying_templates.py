"""
Dreamer AI Phase 4 Day 21 — Kid-Safe Clarifying Templates

Used when DIRECT mode is triggered but no topic_id is provided.
Student is prompted to choose a subject instead of wasting tokens on routing.

Template selection: by (age_band, lang_code).
Same pattern as error_templates.py.
"""

from typing import Dict

# ── Age band constants ──────────────────────────────────

P1_P3 = "P1-P3"
P4_P6 = "P4-P6"
S1_S3 = "S1-S3"

# ── Language code constants ─────────────────────────────

EN = "en"
ZH_HK = "zh-hk"
ZH_CN = "zh-cn"

# ── Student-facing clarifying templates ─────────────────

CLARIFYING_TEMPLATES: Dict[str, Dict[str, str]] = {
    P1_P3: {
        EN: "Which subject are you revising? 🙂",
        ZH_HK: "你想溫邊科呀？",
        ZH_CN: "你想复习哪科呀？",
    },
    P4_P6: {
        EN: "Which subject are you revising today?",
        ZH_HK: "你想溫邊科呀？",
        ZH_CN: "你想复习哪科呀？",
    },
    S1_S3: {
        EN: "Which subject would you like to revise?",
        ZH_HK: "你想溫邊科呀？",
        ZH_CN: "你想复习哪科呀？",
    },
}

# ── Generic fallback ───────────────────────────────────

FALLBACK_TEMPLATES: Dict[str, str] = {
    EN: "Which subject are you revising?",
    ZH_HK: "你想溫邊科呀？",
    ZH_CN: "你想复习哪科呀？",
}


def get_clarifying_message(age_band: str, lang_code: str) -> str:
    """Get the clarifying template for the given age_band and lang_code.

    Args:
        age_band: "P1-P3", "P4-P6", or "S1-S3".
        lang_code: "en", "zh-hk", or "zh-cn".

    Returns:
        Student-facing clarifying message.
    """
    band = CLARIFYING_TEMPLATES.get(age_band)
    if band:
        return band.get(lang_code, FALLBACK_TEMPLATES.get(lang_code, FALLBACK_TEMPLATES[EN]))
    return FALLBACK_TEMPLATES.get(lang_code, FALLBACK_TEMPLATES[EN])
