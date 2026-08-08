"""
Dreamer AI Phase 2.3 — Kid-Safe Error Templates

9 templates: 3 age bands × 3 languages (en/zh-hk/zh-cn).
Errors bypass ToneRewrite/LabelSoften/SessionWrap — routed directly here.
Raw error logged internally, student-facing message returned.

Template selection: by (age_band, lang_code).
"""

from typing import Dict, Optional

# ── Age band constants ──────────────────────────────────

P1_P3 = "P1-P3"
P4_P6 = "P4-P6"
S1_S3 = "S1-S3"

# ── Language code constants ─────────────────────────────

EN = "en"
ZH_HK = "zh-hk"
ZH_CN = "zh-cn"

# ── Student-facing error templates ──────────────────────

ERROR_TEMPLATES: Dict[str, Dict[str, str]] = {
    P1_P3: {
        EN: "Oops, I couldn't figure that out — try asking again?",
        ZH_HK: "哎呀，我諗唔到答案，試下再問過？",
        ZH_CN: "哎呀，我没想出来答案，再问问看？",
    },
    P4_P6: {
        EN: "That was tricky — maybe try asking differently?",
        ZH_HK: "呢題有啲難，不如試下第二個問法？",
        ZH_CN: "这题有点难，换个问法试试？",
    },
    S1_S3: {
        EN: "I ran into trouble with that — try rephrasing?",
        ZH_HK: "暫時處理唔到呢個問題，試下換個角度再問？",
        ZH_CN: "暂时处理不了这个问题，换个角度再问？",
    },
}

# ── Generic fallback (per language, used when age_band unknown) ─

FALLBACK_TEMPLATES: Dict[str, str] = {
    EN: "Something went wrong — please try again later.",
    ZH_HK: "出現咗問題，請稍後再試。",
    ZH_CN: "出了问题，请稍后再试。",
}

# ── Internal error labels for logging ──────────────────

ERROR_LABELS: Dict[str, str] = {
    "ws_error": "WebSocket connection error",
    "timeout": "DeepTutor request timeout",
    "server_error": "DeepTutor server error (5xx)",
    "empty_response": "DeepTutor returned empty response",
    "unknown": "Unknown error",
}


def get_error_message(
    age_band: str,
    lang_code: str,
    raw_error: str = "",
) -> str:
    """Return the student-facing error message for the given age band and language.

    Args:
        age_band: One of "P1-P3", "P4-P6", "S1-S3".
        lang_code: One of "en", "zh-hk", "zh-cn".
        raw_error: The raw/internal error string (logged, never surfaced).

    Returns:
        Student-facing friendly error message string.
    """
    band_templates = ERROR_TEMPLATES.get(age_band)
    if band_templates is None:
        # Unknown age band → language-specific fallback
        return FALLBACK_TEMPLATES.get(lang_code, FALLBACK_TEMPLATES[EN])

    return band_templates.get(
        lang_code,
        band_templates.get(EN, FALLBACK_TEMPLATES[EN]),
    )


def label_error(error_type: str) -> str:
    """Map an internal error type string to a human-readable label for logging.

    Args:
        error_type: Raw error type key (e.g. 'ws_error', 'timeout').

    Returns:
        Human-readable error label, or the raw type if unknown.
    """
    return ERROR_LABELS.get(error_type, error_type)


# ── Convenience: all template keys for test iteration ──

ALL_AGE_BANDS = [P1_P3, P4_P6, S1_S3]
ALL_LANG_CODES = [EN, ZH_HK, ZH_CN]

TEMPLATE_COUNT = len(ALL_AGE_BANDS) * len(ALL_LANG_CODES)  # 9
