"""
Dreamer AI Phase 2.3 — Label Soften

Maps Dreamer internal assessment labels to kid-facing and parent-facing labels.
Uses config/dreamer_progress_levels.json (Phase 0 config, v3).
Coverage: 4 labels × 3 age bands × 3 languages = 36 kid-facing combos.

Internal labels (input) → kid_facing (output by age_band + lang_code):
  not_yet    → Getting Started / Keep Going! / Not Yet
  developing → Making Progress / Almost There! / Developing
  achieved   → You've Got It! / Well Done! / Achieved
  exemplary  → Amazing Work! / Excellent! / Exemplary
"""

import json
import os
from typing import Dict, Optional

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "dreamer_progress_levels.json"
)

# ── Lazy-load the config ────────────────────────────────

_config: Optional[Dict] = None


def _load_config() -> Dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = json.load(f)
    return _config


# ── Public API ──────────────────────────────────────────


def soften_label(
    internal_label: str,
    age_band: str,
    lang_code: str,
    audience: str = "kid_facing",
) -> str:
    """Convert an internal label to a kid/parent-facing string.

    Args:
        internal_label: One of "not_yet", "developing", "achieved", "exemplary".
        age_band: One of "P1-P3", "P4-P6", "S1-S3".
        lang_code: One of "en", "zh-hk", "zh-cn".
        audience: "kid_facing" (default) or "parent_facing".

    Returns:
        The softened label string. Falls back through: exact match
        → EN in same band → first band for that label → raw internal_label.
    """
    cfg = _load_config()
    mapping = cfg.get("label_mapping", {}).get(internal_label)
    if mapping is None:
        return internal_label  # Unknown label → pass through unchanged

    audience_map = mapping.get(audience)
    if audience_map is None:
        return internal_label

    # Try: exact age_band → lang_code
    if isinstance(audience_map, dict) and age_band in audience_map:
        band_map = audience_map[age_band]
        if isinstance(band_map, dict) and lang_code in band_map:
            return band_map[lang_code]
        # Fallback: EN within same band
        if isinstance(band_map, dict) and "en" in band_map:
            return band_map["en"]

    # Try: flat lang_code (parent_facing has flat structure)
    if isinstance(audience_map, dict) and lang_code in audience_map:
        return audience_map[lang_code]
    if isinstance(audience_map, dict) and "en" in audience_map:
        return audience_map["en"]

    return internal_label


def get_mastery_pct(internal_label: str) -> float:
    """Convert an internal label to an approximate mastery percentage.

    Uses config's mastery_pct_from_label mapping.
    Falls back to 0.0 for unknown labels.
    """
    cfg = _load_config()
    pct_map = cfg.get("mastery_pct_from_label", {})
    return float(pct_map.get(internal_label, 0.0))


def get_parent_report_sections(lang_code: str) -> Dict[str, str]:
    """Return parent report section headers for the given language.

    Returns a dict with keys: summary, progress, strengths, development,
    recommendations, session_count, time_spent.
    """
    cfg = _load_config()
    sections = cfg.get("parent_report_sections", {})
    lang_sections = sections.get(lang_code, sections.get("en", {}))
    return dict(lang_sections)


def is_streak_improvement(prev_label: str, curr_label: str) -> bool:
    """Check if curr_label is an improvement over prev_label per streak_rules.

    Uses config's improvement_chain list of [from, to] pairs.
    """
    cfg = _load_config()
    rules = cfg.get("streak_rules", {})
    chain = rules.get("improvement_chain", [])
    return [prev_label, curr_label] in chain


# ── Convenience constants for test iteration ────────────

INTERNAL_LABELS = ["not_yet", "developing", "achieved", "exemplary"]
ALL_AGE_BANDS = ["P1-P3", "P4-P6", "S1-S3"]
ALL_LANG_CODES = ["en", "zh-hk", "zh-cn"]

LABEL_COMBOS = len(INTERNAL_LABELS) * len(ALL_AGE_BANDS) * len(ALL_LANG_CODES)  # 36
