"""PR-4 descriptor content + loader (design book v1.1 §5 / §8.3).

The 144 parent-facing descriptor sentences (4 dimensions × 4 levels × 3 bands ×
3 languages) live in ``config/report_descriptors.json``, machine-extracted from
the signed design book §5.1-5.3. This module is the only reader:

* ``load_descriptors`` refuses to hand back a partial table — the full
  dimension × level × band × lang cross product must be present, every cell
  non-empty and every Level 0 cell must open with the frozen
  ``Not yet — …`` / ``尚未——…`` prefix. A single missing row raises
  :class:`DescriptorError`, so report generation refuses to start rather than
  silently mismatch a family's language/band (T-4 缺一即生成失败).
* ``descriptor(dimension, level, band, lang)`` is the single lookup used when a
  report is drafted.
* ``attach_dimension_descriptors`` maps the teacher's 0-3 scores onto those
  sentences and writes them into the report payload, one entry per dimension
  that actually carries a score. ``score_0_3 IS NULL`` (never graded) yields no
  descriptor at all — a missing score must never be rendered as a "Not Yet"
  judgement (§3.2).

Frozen vocabulary: the level names (Exemplary/Achieved/Developing/Not Yet and
the zh-HK / zh-CN pairs) are code constants below — they are deliberately NOT
stored in the JSON, and §5.4 translation table / chapter 6 crosswalk terms
(IB, ATL, Inquirer, Learner Profile) must never reach a parent-facing file.

Boundaries: pure content module — no DB access, no masking, no state machine.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping, Optional

# ---------------------------------------------------------------------------
# Frozen vocabulary / table shape
# ---------------------------------------------------------------------------

DIMENSIONS: tuple[str, ...] = ("DREAM", "DISCOVER", "DESIGN", "DELIVER")
BANDS: tuple[str, ...] = ("P1-P3", "P4-P6", "S1-S3")
LANGS: tuple[str, ...] = ("en", "zh-hk", "zh-cn")
LEVELS: tuple[int, ...] = (0, 1, 2, 3)

#: Level names, frozen here on purpose — never serialized into the JSON
#: (design book §5: 「等级名（冻结）」).
LEVEL_NAMES: dict[str, tuple[str, str, str, str]] = {
    "en": ("Not Yet", "Developing", "Achieved", "Exemplary"),
    "zh-hk": ("尚未開始", "進展中", "達標", "出色"),
    "zh-cn": ("尚未开始", "进展中", "达标", "出色"),
}

#: Level 0 opening, frozen across dimensions and languages (§5 v1.1 格式规约).
LEVEL0_PREFIX: dict[str, str] = {
    "en": "Not yet — ",
    "zh-hk": "尚未——",
    "zh-cn": "尚未——",
}

#: Retired / internal-only wording that must never appear in a parent-facing
#: descriptor (H-1 retired names + §5.4 / chapter 6 internal vocabulary).
FORBIDDEN_TERMS: tuple[str, ...] = (
    "IB",
    "ATL",
    "Inquirer",
    "Learner Profile",
    "Proficient",
    "Excellent",
    "未達標",
    "不及格",
)

ENTRY_KEYS = frozenset({"dimension", "level", "band", "lang", "text"})

EXPECTED_ROWS = len(DIMENSIONS) * len(LEVELS) * len(BANDS) * len(LANGS)  # 144

CONFIG_RELATIVE_PATH = os.path.join("config", "report_descriptors.json")

_TABLE: Optional[dict[tuple[str, int, str, str], str]] = None


class DescriptorError(RuntimeError):
    """The descriptor table is unusable — report generation must not start."""


# ---------------------------------------------------------------------------
# Load + hard assertions
# ---------------------------------------------------------------------------


def config_path(path: Optional[str] = None) -> str:
    """Path of the descriptor JSON (repo-relative unless ``path`` is given)."""
    if path:
        return path
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, CONFIG_RELATIVE_PATH)


def _read_rows(path: str) -> list[Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as exc:
        raise DescriptorError(f"descriptor table missing: {path}") from exc
    except (OSError, ValueError) as exc:
        raise DescriptorError(f"descriptor table unreadable: {path} ({exc})") from exc
    if not isinstance(raw, list):
        raise DescriptorError(f"descriptor table must be a JSON array: {path}")
    return raw


def _check_forbidden(text: str, where: str, terms: Iterable[str]) -> None:
    for term in terms:
        if term in text:
            raise DescriptorError(
                f"forbidden term {term!r} in parent-facing descriptor at {where}"
            )


def load_descriptors(path: Optional[str] = None) -> dict[tuple[str, int, str, str], str]:
    """Load and fully validate the 144-cell table.

    Raises :class:`DescriptorError` on any gap, duplicate, out-of-domain value,
    Level 0 prefix drift or forbidden vocabulary — never returns a partial map.
    """
    src = config_path(path)
    rows = _read_rows(src)

    table: dict[tuple[str, int, str, str], str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DescriptorError(f"row {index}: expected an object, got {type(row).__name__}")
        keys = set(row)
        if keys != ENTRY_KEYS:
            raise DescriptorError(
                f"row {index}: expected keys {sorted(ENTRY_KEYS)}, got {sorted(keys)}"
            )
        dimension, level, band, lang, text = (
            row["dimension"],
            row["level"],
            row["band"],
            row["lang"],
            row["text"],
        )
        where = f"row {index} ({lang}/{dimension}/L{level}/{band})"
        if dimension not in DIMENSIONS:
            raise DescriptorError(f"{where}: unknown dimension {dimension!r}")
        if band not in BANDS:
            raise DescriptorError(f"{where}: unknown band {band!r}")
        if lang not in LANGS:
            raise DescriptorError(f"{where}: unknown lang {lang!r}")
        if isinstance(level, bool) or not isinstance(level, int) or level not in LEVELS:
            raise DescriptorError(f"{where}: level must be an int in 0-3, got {level!r}")
        if not isinstance(text, str) or not text or text != text.strip():
            raise DescriptorError(f"{where}: text must be a non-empty trimmed string")
        if level == 0 and not text.startswith(LEVEL0_PREFIX[lang]):
            raise DescriptorError(
                f"{where}: level 0 must open with {LEVEL0_PREFIX[lang]!r}, got {text!r}"
            )
        _check_forbidden(text, where, FORBIDDEN_TERMS)
        key = (dimension, level, band, lang)
        if key in table:
            raise DescriptorError(f"{where}: duplicate cell")
        table[key] = text

    missing = [
        (dim, level, band, lang)
        for dim in DIMENSIONS
        for level in LEVELS
        for band in BANDS
        for lang in LANGS
        if (dim, level, band, lang) not in table
    ]
    if missing or len(table) != EXPECTED_ROWS:
        raise DescriptorError(
            f"descriptor table incomplete: {len(table)}/{EXPECTED_ROWS} cells, "
            f"missing {missing[:5]}"
            + (" …" if len(missing) > 5 else "")
        )
    return table


def descriptors() -> dict[tuple[str, int, str, str], str]:
    """Process-cached table (validated once, on first use)."""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_descriptors()
    return _TABLE


def reset_cache() -> None:
    """Drop the cache (tests that swap in a broken table)."""
    global _TABLE
    _TABLE = None


def descriptor(dimension: str, level: int, band: str, lang: str) -> str:
    """The one sentence for (dimension, level, band, lang)."""
    key = (dimension, level, band, lang)
    table = descriptors()
    try:
        return table[key]
    except KeyError as exc:
        raise DescriptorError(f"no descriptor for {key}") from exc


# ---------------------------------------------------------------------------
# Report-payload integration
# ---------------------------------------------------------------------------


def descriptors_for_scores(
    scores: Mapping[str, Optional[int]], age_band: str, lang_code: str
) -> dict[str, str]:
    """Score map → descriptor sentences, keyed by dimension.

    ``build_dimension_scores`` returns ``None`` for a dimension the teacher has
    not graded in the window; those dimensions get **no** descriptor (they are
    not a 0 and must never be pitched as "Not Yet"). ``0`` is a real score and
    does produce the Level 0 sentence.
    """
    if age_band not in BANDS:
        raise DescriptorError(f"unknown band {age_band!r} — cannot pick a descriptor")
    if lang_code not in LANGS:
        raise DescriptorError(f"unknown lang {lang_code!r} — cannot pick a descriptor")
    out: dict[str, str] = {}
    for dimension in DIMENSIONS:
        score = scores.get(dimension)
        if score is None:
            continue
        if isinstance(score, bool) or not isinstance(score, int) or score not in LEVELS:
            raise DescriptorError(
                f"score for {dimension} must be an int in 0-3 or None, got {score!r}"
            )
        out[dimension] = descriptor(dimension, score, age_band, lang_code)
    return out


def paired_langs(lang_code: str) -> tuple[str, str]:
    """(top, bottom) pair for the PR-6 bilingual surface (施工令 A1-1).

    ``zh-hk`` → 繁 + EN ; ``zh-cn`` → 簡 + EN ; ``en`` → EN + 繁. The print
    order is always English on top, so the tuple is ``("en", zh_variant)``:
    index 0 is the upper line, index 1 the lower one.
    """
    if lang_code == "zh-cn":
        return ("en", "zh-cn")
    return ("en", "zh-hk")


def descriptor_pairs(
    scores: Mapping[str, Optional[int]], age_band: str, lang_code: str
) -> dict[str, dict[str, Any]]:
    """Score map → **both** language cells per dimension (PR-6 S1).

    The stored payload keeps the single-language ``dimension_descriptors``
    (PR-4 contract, untouched). The bilingual surface needs the other
    language too, and the pair must come from the SAME 144-cell table cell,
    so it is derived here from the stored scores + band rather than retyped:

        {"DREAM": {"level": 2, "en": "<en cell>", "zh": "<zh-Hant|zh-Hans cell>"}}

    ``level`` rides along so the PDF can print the frozen level pair
    (``Achieved 達標``) next to the dimension name without re-deriving it.

    An ungraded dimension (``None``) yields no entry — never a "Not Yet".
    A band outside the frozen closed set yields ``{}`` (legacy rows keep the
    pre-PR-4 report; nothing is written for a band it does not own).
    """
    if age_band not in BANDS:
        return {}
    _, zh_lang = paired_langs(lang_code)
    out: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        score = scores.get(dimension)
        if score is None:
            continue
        if isinstance(score, bool) or not isinstance(score, int) or score not in LEVELS:
            raise DescriptorError(
                f"score for {dimension} must be an int in 0-3 or None, got {score!r}"
            )
        out[dimension] = {
            "level": score,
            "en": descriptor(dimension, score, age_band, "en"),
            "zh": descriptor(dimension, score, age_band, zh_lang),
        }
    return out


def attach_dimension_descriptors(
    envelope: dict[str, Any],
    *,
    scores: Mapping[str, Optional[int]],
    age_band: str,
    lang_code: str,
) -> dict[str, str]:
    """Write ``report.dimension_descriptors`` into a draft payload.

    Called on the generation chain right after ``build_dimension_scores`` with
    the same band / lang_code the ``parent_reports`` row stores, so the stored
    sentences and the stored band can never disagree. Returns the mapping that
    was written (empty when nothing was graded).
    """
    picked = descriptors_for_scores(scores, age_band, lang_code)
    report = envelope.get("report")
    if not isinstance(report, dict):
        raise DescriptorError("report envelope has no 'report' object to attach to")
    report["dimension_descriptors"] = picked
    return picked
