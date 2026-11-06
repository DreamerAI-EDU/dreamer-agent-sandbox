"""PR-6 S2 — bilingual report PDF renderer: 零新措辭 + 確定性 + T-9 golden.

验收对照（施工令 PR-6 §A1-4 / §S2 / 把關人通訊 2026-11-05 硬規矩）:

  * **零新措辭（程式化斷言證明）** — every chrome literal the renderer prints
    must appear character-for-character in a frozen asset:
    ``frontend/src/lib/parentReportCopy.ts`` (PARENT_REPORT_COPY, the PR-5
    wording declaration) or ``config/pr5_frozen_copy.json`` ``bandLabels``
    (§三 144-grid). Every descriptor sentence must appear verbatim in
    ``config/report_descriptors.json`` (the 144-cell table).
  * **冇機翻** — the zh side of every pair is the table's own zh-HK / zh-CN
    cell for the SAME band × level, never a translation of the en cell.
  * **PDF bytes 確定性** — two renders of the same input are byte-identical
    and hash to the pinned T-9 golden below.
  * **Free text stays single-language** — the narrative paragraph and the
    evidence lines are printed once, exactly as stored.
  * **Zero new wording on the web B2 surface** — the parent detail page holds
    no CJK string literal of its own: every Chinese word it prints comes from
    the frozen copy module or from the payload.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re

import pytest

from agents import report_pdf
from auth import report_descriptors as rd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY_TS = os.path.join(REPO_ROOT, "frontend", "src", "lib", "parentReportCopy.ts")
FROZEN_JSON = os.path.join(REPO_ROOT, "config", "pr5_frozen_copy.json")
DESCRIPTORS_JSON = os.path.join(REPO_ROOT, "config", "report_descriptors.json")
PARENT_DETAIL_TSX = os.path.join(
    REPO_ROOT, "frontend", "src", "pages", "parent", "ParentReportDetailPage.tsx"
)

#: T-9 golden — sha256 of the fixture below (see ``_golden_bytes``), one hash
#: per lang_code (three pairing cases, 施工令 §五-2). A change here means the
#: bytes changed; re-pinning is only allowed with a new 施工令, and the report
#: must carry the before/after hashes plus the reason.
GOLDEN_SHA256 = {
    "zh-hk": "be7633f2672464b607ceab6507c93a407d86363ac46bfa970603fd45804d15d7",
    "zh-cn": "8b1170951e7870240b41ab5e3d5516daf82face428c8523181953ba841d43dee",
    "en": "d14302f42270f263ec62dfc1dac69995b1e87d3c71a1b08fff7c403e018b2099",
}


#: Free text is single-language by rule (A1-2), so the fixture carries one
#: narrative per lang_code — exactly what a stored row holds.
_NARRATIVE = {
    "en": "Focused on fraction word problems; steady this week.",
    "zh-hk": "今週專注分數應用題，表現穩定。",
    "zh-cn": "本周专注分数应用题，表现稳定。",
}
_EVIDENCE = {
    "en": "Answered three questions correctly",
    "zh-hk": "答對了三題",
    "zh-cn": "答对了三题",
}


def _fixture_view(lang_code: str = "zh-hk") -> dict:
    """Smallest realistic parent-safe projection: 4 scored dims, 1 topic."""
    scores = {"DREAM": 3, "DISCOVER": 2, "DESIGN": 1, "DELIVER": 0}
    return {
        "report_id": "rpt_0123456789abcdef0123456789abcdef",
        "version": 2,
        "student_id": "aaaa1111",
        "week_from": 3,
        "week_to": 4,
        "status": "approved",
        "lang_code": lang_code,
        "age_band": "P4-P6",
        "published_at": "2026-11-05T10:00:00Z",
        "descriptor_pairs": rd.descriptor_pairs(scores, "P4-P6", lang_code),
        "payload": {
            "content": _NARRATIVE[lang_code],
            "report": {
                "summary": {
                    "session_count": 3,
                    "total_duration_seconds": 5400,
                    "topics_touched": 1,
                },
                "topics": [
                    {
                        "topic_id": "topic-num-1",
                        "subject": "分數",
                        "mastery_pct": 0.667,
                        "last_label_parent": "達標",
                        "recent_evidence": [
                            {
                                "date": "2026-11-01",
                                "evidence_text": _EVIDENCE[lang_code],
                            }
                        ],
                    }
                ],
            },
        },
    }


def _golden_bytes(lang_code: str = "zh-hk") -> bytes:
    return report_pdf.render_report_pdf(_fixture_view(lang_code))


# ---------------------------------------------------------------------------
# 零新措辭 — chrome words trace back to a frozen asset
# ---------------------------------------------------------------------------


def test_every_chrome_literal_is_a_frozen_asset_string():
    """Each printed chrome word must exist verbatim in the PR-5 frozen copy."""
    ts = io.open(COPY_TS, encoding="utf-8").read()
    frozen = json.load(io.open(FROZEN_JSON, encoding="utf-8"))
    frozen_values = set()
    for band in frozen["bandLabels"].values():
        frozen_values.update(band.values())

    for key, langs in report_pdf._CHROME.items():
        for lang, text in langs.items():
            assert text in ts or text in frozen_values, (
                f"chrome[{key}][{lang}] = {text!r} is not a frozen §三 string"
            )

    for level, langs in report_pdf._LEVELS.items():
        for lang, text in langs.items():
            assert text in ts, (
                f"level[{level}][{lang}] = {text!r} is not in the frozen level table"
            )


def test_every_descriptor_sentence_comes_from_the_144_cell_table():
    rows = json.load(io.open(DESCRIPTORS_JSON, encoding="utf-8"))
    assert len(rows) == 144
    cells = {(r["dimension"], r["band"], r["lang"], r["level"]): r["text"] for r in rows}

    for lang_code in ("en", "zh-hk", "zh-cn"):
        pairs = rd.descriptor_pairs(
            {"DREAM": 3, "DISCOVER": 2, "DESIGN": 1, "DELIVER": 0}, "P4-P6", lang_code
        )
        _, zh_lang = rd.paired_langs(lang_code)
        for dim, pair in pairs.items():
            level = {"DREAM": 3, "DISCOVER": 2, "DESIGN": 1, "DELIVER": 0}[dim]
            assert pair["en"] == cells[(dim, "P4-P6", "en", level)]
            assert pair["zh"] == cells[(dim, "P4-P6", zh_lang, level)]


def test_paired_langs_follows_a1_1():
    assert rd.paired_langs("en") == ("en", "zh-hk")
    assert rd.paired_langs("zh-hk") == ("en", "zh-hk")
    assert rd.paired_langs("zh-cn") == ("en", "zh-cn")


def test_parent_detail_page_holds_no_chinese_literal_of_its_own():
    """B2 零新措辭: the page never spells a Chinese word itself.

    Comments are stripped first (they discuss the rule in Chinese), then every
    string literal is removed. What remains is JSX text — the words a parent
    actually reads off the page — and it must contain no CJK at all: those
    come from the frozen copy module or from the payload.
    """
    src = io.open(PARENT_DETAIL_TSX, encoding="utf-8").read()
    stripped = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    stripped = re.sub(r"`[^`]*`", "``", stripped)
    stripped = re.sub(r"'([^'\\\n]*)'", "''", stripped)
    stripped = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', stripped)

    cjk = re.compile(r"[\u3400-\u9fff]")
    offenders = [line.strip() for line in stripped.splitlines() if cjk.search(line)]
    assert not offenders, f"new Chinese wording on the parent surface: {offenders}"


# ---------------------------------------------------------------------------
# 確定性 + T-9 golden
# ---------------------------------------------------------------------------


def test_render_is_deterministic():
    first = _golden_bytes()
    second = _golden_bytes()
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


@pytest.mark.parametrize("lang_code", ["zh-hk", "zh-cn", "en"])
def test_golden_render_hash_matches_pin(lang_code):
    digest = hashlib.sha256(_golden_bytes(lang_code)).hexdigest()
    assert digest == GOLDEN_SHA256[lang_code], (
        "T-9 golden drift for %s: the PDF bytes changed. Only a new 施工令 may "
        "re-pin, and the report must list before/after hashes." % lang_code
    )


def test_three_lang_codes_render_three_documents():
    """zh-hk / zh-cn / en are three different files (pair + free text)."""
    hk, cn, en = _golden_bytes("zh-hk"), _golden_bytes("zh-cn"), _golden_bytes("en")
    assert len({hk, cn, en}) == 3


# ---------------------------------------------------------------------------
# Text extraction — the frozen words really are on the page
# ---------------------------------------------------------------------------


def _text(lang_code: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(_golden_bytes(lang_code)))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _flat(text: str) -> str:
    """Whitespace-insensitive view: reportlab wraps a long cell across lines."""
    return re.sub(r"\s+", " ", text).strip()


def test_extracted_text_carries_the_frozen_level_and_band_pairs():
    text = _text("zh-hk")
    assert "Exemplary 出色" in text          # T-9 关键冻结字串
    assert "Achieved 達標" in text
    assert "Not Yet 尚未開始" in text
    assert "Upper Primary (P4–P6)" in text   # §三 band 親切名（EN）
    assert "小學高年級組（P4–P6）" in text     # §三 band 親切名（繁）
    assert "4 Dimension Evaluation" in text
    # the duplicated-identical-pair bug: printed once, never stacked twice
    assert text.count("4 Dimension Evaluation") == 1


def test_extracted_text_carries_both_descriptor_cells():
    rows = json.load(io.open(DESCRIPTORS_JSON, encoding="utf-8"))
    cells = {(r["dimension"], r["band"], r["lang"], r["level"]): r["text"] for r in rows}
    scores = {"DREAM": 3, "DISCOVER": 2, "DESIGN": 1, "DELIVER": 0}
    text = _flat(_text("zh-hk"))
    for dim, level in scores.items():
        en_cell = _flat(cells[(dim, "P4-P6", "en", level)])
        zh_cell = _flat(cells[(dim, "P4-P6", "zh-hk", level)])
        assert en_cell in text, f"{dim} EN cell missing"
        assert zh_cell in text, f"{dim} 繁 cell missing"


def test_free_text_is_printed_once_in_its_own_language():
    """A1-2: no machine translation — the zh report never carries the EN body."""
    hk = _text("zh-hk")
    assert _NARRATIVE["zh-hk"] in hk
    assert _NARRATIVE["en"] not in hk
    assert _EVIDENCE["zh-hk"] in hk
    en = _text("en")
    assert _NARRATIVE["en"] in en
    assert _NARRATIVE["zh-hk"] not in en


def test_zh_cn_report_uses_simplified_cells_not_hant():
    cn = _text("zh-cn")
    assert "小學高年級組（P4–P6）" not in cn
    assert "小学高年级组（P4–P6）" in cn
    assert "出色" in cn


def test_parent_page_collapses_an_identical_pair_and_mirrors_the_server_filename():
    """Two rendering rules that keep the web B2 surface honest.

    1. A frozen pair whose EN and zh cells are literally the same string (the
       `dimensions` chrome key) must print once — otherwise the page stacks the
       same line twice, which reads as a bug. Collapsing is a rendering rule,
       not new wording: nothing is translated or invented.
    2. The downloaded file name mirrors the server's `content-disposition`
       (`dreamer-report-<report id[:8]>`), so the parent sees exactly one name
       for the artifact the endpoint produced.
    """
    src = open(PARENT_DETAIL_TSX, encoding="utf-8").read()
    assert "zh !== en" in src, "Bi() must guard against stacking an identical pair twice"
    assert "dreamer-report-" in src, "download name must mirror the server content-disposition"
    assert "anchor.download = `${reportId}.pdf`" not in src, (
        "the raw report id as filename contradicts the endpoint's own file name"
    )
