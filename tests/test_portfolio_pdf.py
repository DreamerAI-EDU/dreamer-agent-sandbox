"""W4 PR-C tests — portfolio PDF renderer (docs/phase6-portfolio-pdf-spec.md §6).

Covers the five §6 acceptance gates plus the Step-4 red-line scans:

  * Gate A — parseable A4 PDF pages (pypdf opens it, page size = A4).
  * Gate B — populated portfolio renders all five §3 sections
    (cover / summary / highlights / growth notes / footer).
  * Gate C — PDPO text-scan (spec §6.3): the extracted text never contains
    seeded student-id values / masked prefixes / raw internal_label values /
    "confidence" / school / full name — even when such keys are deliberately
    smuggled into the render payload (allowlist defense, R1/R4).
  * Gate D — empty portfolio: cover + summary only, no error, no blank
    pages, no Highlights / Growth-notes section headers.
  * Gate E — pagination boundaries: 6 / 7 / 12 / 13 items keep <= 6 item
    titles per page (P4-P6 & S1-S3), and P1-P3 variants keep <= 4 per page.
    Also: exact-6 "one full page" behaviour and cross-page continuity.

The renderer must stay CJK-safe: a zh-hk title / kid label must round-trip
through pypdf text extraction (the container has no system CJK font — the
bundled assets/fonts/NotoSansSC-Regular.ttf is what makes this pass).
"""

from __future__ import annotations

import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from agents.portfolio_pdf import render_portfolio_pdf  # noqa: E402

# Identifiers mirroring the seeded world of test_portfolio_api.py — these
# must NEVER survive into PDF text (PDPO §4 / spec §6.3).
SID_A = "aaaa1111aaaa2222"
SID_A_PREFIX = SID_A[:8]
SID_D = "dddd1111dddd2222"
INTERNAL_LABELS = ["not_yet", "developing", "achieved", "exemplary"]
RUBRIC_ID = "rub-internal-001"
FULL_NAME = "阿明 Chan Tai Man"
SCHOOL = "Dreamer Primary School"

FONT_PATH = os.path.join(REPO_ROOT, "assets", "fonts", "NotoSansSC-Regular.ttf")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _card(i: int, poisoned: bool = False) -> dict:
    card = {
        "display_name": "阿明",
        "item_id": f"pf-smoke-{i:03d}",
        "title": f"項目-{i:03d}",
        "artifact_summary": (
            f"呢個係第 {i:03d} 個作品嘅描述，小朋友完成咗任務並展示成果。"
            "用嚟測試中文字體同分頁邊界。"
        ),
        "competencies_4d": ["deliver", "communicate"],
        "kid_label": "勁！做得好",
        "brand": "Dreamer AI",
        "generated_at": "2026-09-01T08:00:00Z",
        "growth_note": "今次比上次更進步！",
    }
    if poisoned:
        # Malicious extra keys — the renderer must ignore everything that is
        # not on its render allowlist (R1: internal fields never rendered).
        card["student_id"] = SID_A
        card["full_name"] = FULL_NAME
        card["school"] = SCHOOL
        card["internal_label"] = "achieved"
        card["confidence"] = 0.95
        card["rubric_id"] = RUBRIC_ID
        card["score"] = 87
    return card


def _render(count: int, age_band: str = "P4-P6", empty: bool = False,
            poisoned: bool = False) -> bytes:
    cards = [] if empty else [_card(i, poisoned=poisoned) for i in range(1, count + 1)]
    return render_portfolio_pdf(
        cards,
        display_name="阿明",
        generated_at="2026-09-01T08:00:00Z",
        lang_code="zh-hk",
        age_band=age_band,
    )


def _extract(pdf: bytes) -> list[str]:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf))
    return [page.extract_text() or "" for page in reader.pages]


def _pages(pdf: bytes):
    from io import BytesIO

    from pypdf import PdfReader

    return PdfReader(BytesIO(pdf)).pages


# ---------------------------------------------------------------------------
# Gate A — parseable A4 PDF
# ---------------------------------------------------------------------------


def test_gate_a_pdf_is_a4_and_parseable():
    pdf = _render(2)
    pages = _pages(pdf)
    assert len(pages) >= 1
    w = float(pages[0].mediabox.width)
    h = float(pages[0].mediabox.height)
    assert abs(w - 595.27) < 1.5 and abs(h - 841.89) < 1.5


def test_font_file_bundled():
    """CJK font must live in the repo so the container can render it."""
    assert os.path.isfile(FONT_PATH)
    assert os.path.getsize(FONT_PATH) > 1_000_000


# ---------------------------------------------------------------------------
# Gate B — all five sections present for a populated portfolio
# ---------------------------------------------------------------------------


def test_gate_b_five_sections_present():
    pdf = _render(2)
    text = "\n".join(_extract(pdf))
    for probe in (
        "作品集",            # cover
        "阿明",              # cover name (first-name only)
        "關於呢本作品集",     # summary header
        "作品亮點",           # highlights
        "項目-001",           # item title
        "成長點滴",           # growth notes
        "成長：",             # growth row prefix
        "Dreamer AI",        # footer / brand
    ):
        assert probe in text, f"missing §3 section probe: {probe}"


def test_gate_b_cjk_roundtrip():
    """zh-hk strings must survive pypdf text extraction (container-safe font)."""
    pdf = _render(1)
    text = "\n".join(_extract(pdf))
    assert "項目-001" in text
    assert "勁！做得好" in text
    assert "今次比上次更進步！" in text
    assert "2026年09月01日" in text


# ---------------------------------------------------------------------------
# Gate C — PDPO text-scan (spec §6.3 red-line gate)
# ---------------------------------------------------------------------------


def _scan_blacklist(pdf: bytes) -> list[str]:
    text = "\n".join(_extract(pdf))
    hits = []
    probes = [
        SID_A, SID_A_PREFIX, SID_D, SID_D[:8],
        FULL_NAME, SCHOOL, RUBRIC_ID, "confidence",
    ] + INTERNAL_LABELS
    for p in probes:
        if p.lower() in text.lower():
            hits.append(p)
    return hits


@pytest.mark.parametrize("count", [1, 6, 13])
def test_gate_c_pdpo_scan_clean(count):
    # Poisoned payloads carry student ids / full name / internal fields —
    # the renderer must drop them all (allowlist defense in depth).
    pdf = _render(count, poisoned=True)
    hits = _scan_blacklist(pdf)
    assert hits == [], f"PDPO blacklist leak: {hits}"


# ---------------------------------------------------------------------------
# Gate D — empty portfolio: cover + summary only
# ---------------------------------------------------------------------------


def test_gate_d_empty_portfolio_cover_summary_only():
    pdf = _render(0, empty=True)
    pages = _pages(pdf)
    assert len(pages) == 1, "empty portfolio must render a single page"
    text = pages[0].extract_text() or ""
    assert "繼續探索新項目" in text          # kid-safe empty summary
    assert "作品集" in text                 # cover
    assert "作品亮點" not in text           # no highlights section
    assert "成長點滴" not in text           # no growth-notes section
    assert "項目-" not in text              # no phantom items


# ---------------------------------------------------------------------------
# Gate E — pagination boundaries (spec §6 acceptance #5)
# ---------------------------------------------------------------------------


def _titles_per_page(pdf: bytes) -> list[int]:
    return [len(re.findall(r"項目-\d{3}", page)) for page in _extract(pdf)]


@pytest.mark.parametrize(
    "count,band,per_page,expect_pages_min",
    [
        (6, "P4-P6", 6, 2),    # one full items page (+ growth page)
        (7, "P4-P6", 6, 2),    # spill into a second items page
        (12, "P4-P6", 6, 3),   # two full items pages
        (13, "P4-P6", 6, 3),   # second page spills
        (6, "P1-P3", 4, 2),    # younger band: larger type, fewer per page
        (7, "P1-P3", 4, 2),
        (12, "P1-P3", 4, 3),
        (13, "P1-P3", 4, 4),
    ],
)
def test_gate_e_pagination_boundaries(count, band, per_page, expect_pages_min):
    pdf = _render(count, age_band=band)
    per = _titles_per_page(pdf)
    assert sum(per) == count, f"all item titles must appear exactly once: {per}"
    assert max(per) <= per_page, f"a page holds more than {per_page} items: {per}"
    assert len(per) >= expect_pages_min, f"unexpectedly few pages: {per}"


def test_gate_e_exact_full_page_boundary_6():
    """6 items at P4-P6: exactly one full items page, no spill."""
    pdf = _render(6, age_band="P4-P6")
    per = _titles_per_page(pdf)
    # The full 6-item chunk sits on the first page (cover+summary lead it);
    # the growth-notes page that follows must repeat no item titles.
    assert per[0] == 6
    assert sum(per) == 6
    assert len(per) == 2


def test_gate_e_order_preserved_across_pages():
    """Item order must be preserved across page breaks (ascending)."""
    pdf = _render(13, age_band="P4-P6")
    all_titles: list[int] = []
    for page in _extract(pdf):
        all_titles += [int(m) for m in re.findall(r"項目-(\d{3})", page)]
    assert all_titles == sorted(all_titles)
    assert all_titles == list(range(1, 14))
