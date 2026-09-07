"""Dreamer AI Phase 6 (W4 PR-C) — Portfolio PDF renderer.

Pure renderer built on reportlab. It consumes whitelist **share_card
payloads** ONLY (R3/R4; docs/phase6-portfolio-pdf-spec.md §5) — this module
has no DB import and no student-identity input; the only way in is the
``share_cards`` sequence plus cover display_name / generated_at.

PDPO red line (§4): rendered text never contains student_id / full name /
school / raw internal_label values / scores / confidence. The renderer only
extracts the keys in ``PDF_RENDER_ALLOWLIST``; anything else in a payload
(including a hypothetical student_id) is ignored, never rendered.

Sections (§3):
  1. Cover  — brand + display_name + generated_at (first-name only, B24)
  2. Summary — kid-facing intro line (local kid-safe template per language;
     template text mirrors agents.portfolio_agent portfolio narrative, so
     no LLM / tone layer is needed at render time)
  3. Highlights — one block per portfolio item: title, kid_label,
     artifact_summary, competencies_4d badges
  4. Growth notes — per item: kid-facing growth wording. growth_note is NOT
     part of the R3 share_card API contract, so the API contract stays
     frozen; the PDF handler attaches each item's kid-safe growth_note to
     the render payload (never internal fields) and the renderer may show it
     here. If a payload has no growth_note, the item's kid_label is used as
     the growth line so the section is never empty for a populated
     portfolio (spec §6 acceptance #2).
  5. Footer — on every page: brand + date + "Made with Dreamer AI"

Layout (§5): A4 portrait; CJK font bundled in-repo
(assets/fonts/NotoSansSC-Regular.ttf — required in the container where no
system CJK font exists); max 6 items per page (P1-P3: larger type, 4 per
page); brand color #00023D from the Dreamer AI design kit.
"""

from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

# ---------------------------------------------------------------------------
# Fonts — bundled CJK font (must exist in repo & container)
# ---------------------------------------------------------------------------

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "fonts",
)
_FONT_PATH = os.path.join(_FONT_DIR, "NotoSansSC-Regular.ttf")
_FONT_NAME = "NotoSansSC"

# ---------------------------------------------------------------------------
# Design kit & layout constants
# ---------------------------------------------------------------------------

BRAND_HEX = "#00023D"          # Dreamer AI brand ink
ACCENT_HEX = "#2E5AAC"         # calm blue for section headers / badges
MUTED_HEX = "#5A6270"          # secondary text
RULE_HEX = "#C9CFDA"

A4_PORTRAIT = A4
PAGE_MARGIN = 16 * 2.835  # ~16mm in points
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN

# spec §5: max 6 items/page; P1-P3 larger type, fewer per page.
ITEMS_PER_PAGE = {"P1-P3": 4, "P4-P6": 6, "S1-S3": 6}
DEFAULT_PER_PAGE = 6

# Anything a PDF renderer may put on the page. This is the R3 whitelist plus
# the kid-safe growth_note extension for the PDF surface (R1: internal
# fields can never be added here).
PDF_RENDER_ALLOWLIST = frozenset(
    {
        "display_name",
        "item_id",  # accepted for idempotent de-dupe only; never rendered
        "title",
        "artifact_summary",
        "competencies_4d",
        "kid_label",
        "growth_note",
        "brand",
        "generated_at",
    }
)
_RENDER_TEXT_KEYS = frozenset(
    {
        "display_name",
        "title",
        "artifact_summary",
        "kid_label",
        "growth_note",
        "brand",
        "generated_at",
    }
)

_MAX_ARTIFACT_CHARS = 160  # keep a 6-item page within one A4 page

# Kid-safe summary intro lines (mirror agents/portfolio_agent narrative).
_SUMMARY_INTRO = {
    "has_items": {
        "en": "This portfolio celebrates the projects you have completed — "
              "look at everything you have made!",
        "zh-hk": "呢本作品集記錄咗你完成嘅項目——睇吓你做到嘅嘢！",
        "zh-cn": "这本作品集记录了你完成的项目——看看你做到的事情！",
    },
    "empty": {
        "en": "Keep exploring new projects — your portfolio is growing!",
        "zh-hk": "繼續探索新項目，作品集就會慢慢豐富起嚟！",
        "zh-cn": "继续探索新项目，作品集就会慢慢丰富起来！",
    },
}

_SECTION_TITLES = {
    "highlights": {
        "en": "Highlights",
        "zh-hk": "作品亮點",
        "zh-cn": "作品亮点",
    },
    "growth": {
        "en": "Growth Notes",
        "zh-hk": "成長點滴",
        "zh-cn": "成长点滴",
    },
}

_SUMMARY_TITLE = {
    "en": "About this portfolio",
    "zh-hk": "關於呢本作品集",
    "zh-cn": "关于这本作品集",
}

_PORTFOLIO_TITLE = {
    "en": "Portfolio",
    "zh-hk": "作品集",
    "zh-cn": "作品集",
}

_FOOTER_MADE = {
    "en": "Made with Dreamer AI",
    "zh-hk": "Made with Dreamer AI",
    "zh-cn": "Made with Dreamer AI",
}

_GROWTH_PREFIX = {
    "en": "Growth: ",
    "zh-hk": "成長：",
    "zh-cn": "成长：",
}

_BADGE_JOIN = "    "

# ---------------------------------------------------------------------------
# reportlab styles
# ---------------------------------------------------------------------------

_font_registered = False


def _ensure_font() -> None:
    global _font_registered
    if _font_registered:
        return
    if not os.path.exists(_FONT_PATH):
        raise RuntimeError(
            "CJK font not found: %s — bundle assets/fonts/NotoSansSC-Regular.ttf "
            "in the repo and image (W4 PR-C font requirement)" % _FONT_PATH
        )
    pdfmetrics.registerFont(TTFont(_FONT_NAME, _FONT_PATH))
    _font_registered = True


def _style(name: str, **kw) -> ParagraphStyle:
    base = {
        "fontName": _FONT_NAME,
        "fontSize": 10.5,
        "leading": 15,
        "textColor": colors.HexColor(BRAND_HEX),
        "wordWrap": "CJK",
        "allowWidows": 0,
        "allowOrphans": 0,
    }
    base.update(kw)
    return ParagraphStyle(name, **base)


_COVER_BRAND = _style("cover-brand", fontSize=11, leading=15, textColor=colors.HexColor(ACCENT_HEX))
_COVER_NAME = _style("cover-name", fontSize=27, leading=34, textColor=colors.HexColor(BRAND_HEX))
_COVER_SUB = _style("cover-sub", fontSize=10, leading=14, textColor=colors.HexColor(MUTED_HEX))
_SECTION_H = _style("section-h", fontSize=14, leading=20, textColor=colors.HexColor(BRAND_HEX),
                    spaceBefore=6, spaceAfter=4)
_ITEM_TITLE = _style("item-title", fontSize=12.5, leading=17, textColor=colors.HexColor(BRAND_HEX))
_ITEM_KID = _style("item-kid", fontSize=10, leading=14, textColor=colors.HexColor(ACCENT_HEX),
                   spaceBefore=1, spaceAfter=1)
_ITEM_BODY = _style("item-body", fontSize=9.5, leading=14, textColor=colors.HexColor(MUTED_HEX),
                    spaceBefore=2, spaceAfter=2)
_ITEM_BADGE = _style("item-badge", fontSize=8.5, leading=12, textColor=colors.HexColor(ACCENT_HEX),
                     spaceAfter=2)
_GROWTH_ROW = _style("growth-row", fontSize=9.5, leading=14, textColor=colors.HexColor(BRAND_HEX),
                     leftIndent=2, spaceAfter=1)
_SUMMARY_BODY = _style("summary-body", fontSize=10.5, leading=16, textColor=colors.HexColor(BRAND_HEX),
                       spaceBefore=2)


def _clean(value: Any) -> str:
    """Flatten a render value to safe single-line-ish text (never raw list/dict)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return ""
    text = str(value).strip()
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text


def _fmt_date(iso_text: str, lang_code: str) -> str:
    iso_text = (iso_text or "").strip()
    if not iso_text:
        return ""
    try:
        dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except ValueError:
        return iso_text
    if lang_code.startswith("zh"):
        # Manual formatting: strftime may fail on CJK literal under a
        # non-UTF-8 locale (e.g. Windows cp936) — keep it explicit.
        return f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"
    return f"{dt.day:02d} {dt.strftime('%b')} {dt.year}"


def _truncate(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _extract(card: Dict[str, Any]) -> Dict[str, str]:
    """Pull only allowlisted text fields out of a payload.

    Non-text keys (competencies_4d) are handled separately. Any unknown key
    is deliberately dropped — defense in depth for the PDPO red line even if
    a caller accidentally passes internal fields.
    """
    out: Dict[str, str] = {}
    for key in _RENDER_TEXT_KEYS:
        out[key] = _clean(card.get(key))
    comps = card.get("competencies_4d")
    if isinstance(comps, list):
        comps = [_clean(c) for c in comps if _clean(c)]
    elif isinstance(comps, str):
        comps = [_clean(c) for c in comps.split(",") if _clean(c)]
    else:
        comps = []
    out["competencies_4d"] = comps  # type: ignore[assignment]
    return out


def _footer(canvas, doc, generated_date: str, lang_code: str) -> None:
    """Page footer: brand + date + Made-with line (spec §3 section 5)."""
    _ensure_font()
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor(RULE_HEX))
    canvas.setLineWidth(0.6)
    y = PAGE_MARGIN - 8
    canvas.line(PAGE_MARGIN, y, A4[0] - PAGE_MARGIN, y)
    canvas.setFont(_FONT_NAME, 7.8)
    canvas.setFillColor(colors.HexColor(MUTED_HEX))
    made = _FOOTER_MADE.get(lang_code, _FOOTER_MADE["en"])
    left = f"Dreamer AI  ·  {made}"
    canvas.drawString(PAGE_MARGIN, y - 12, left)
    right = generated_date or ""
    if right:
        canvas.drawRightString(A4[0] - PAGE_MARGIN, y - 12, right)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Public renderer — pure, DB-free
# ---------------------------------------------------------------------------


def render_portfolio_pdf(
    share_cards: Sequence[Dict[str, Any]],
    display_name: str,
    generated_at: str,
    lang_code: str = "zh-hk",
    age_band: str = "P4-P6",
) -> bytes:
    """Render an A4 portrait portfolio PDF from whitelist share_card payloads.

    Args:
        share_cards: per-item payloads (R3 whitelist fields; the PDF surface
            additionally accepts kid-safe ``growth_note``). May be empty.
        display_name: first-name-only cover name (B24).
        generated_at: ISO timestamp for cover/footer.
        lang_code: "en" | "zh-hk" | "zh-cn".
        age_band: "P1-P3" | "P4-P6" | "S1-S3" (controls type size / per-page
            item count).

    Returns:
        PDF bytes.
    """
    _ensure_font()

    display_name = _clean(display_name) or "Dreamer Explorer"
    generated_at = _clean(generated_at)
    date_text = _fmt_date(generated_at, lang_code)
    per_page = ITEMS_PER_PAGE.get(age_band, DEFAULT_PER_PAGE)

    cards = [_extract(c) for c in share_cards]
    has_items = bool(cards)

    # ---- styles tuned per age band (P1-P3: larger type) -----------------
    if age_band == "P1-P3":
        cover_name = _style("cover-name-p", fontSize=30, leading=38,
                            textColor=colors.HexColor(BRAND_HEX))
        section_h = _style("section-h-p", fontSize=15, leading=21,
                           textColor=colors.HexColor(BRAND_HEX), spaceBefore=6, spaceAfter=4)
        item_title = _style("item-title-p", fontSize=14, leading=19,
                            textColor=colors.HexColor(BRAND_HEX))
        item_kid = _style("item-kid-p", fontSize=11, leading=15,
                          textColor=colors.HexColor(ACCENT_HEX), spaceBefore=1, spaceAfter=1)
        item_body = _style("item-body-p", fontSize=11, leading=16,
                           textColor=colors.HexColor(MUTED_HEX), spaceBefore=2, spaceAfter=2)
        item_badge = _style("item-badge-p", fontSize=10, leading=14,
                            textColor=colors.HexColor(ACCENT_HEX), spaceAfter=2)
        growth_row = _style("growth-row-p", fontSize=11, leading=16,
                            textColor=colors.HexColor(BRAND_HEX), leftIndent=2, spaceAfter=1)
        summary_body = _style("summary-body-p", fontSize=12, leading=18,
                              textColor=colors.HexColor(BRAND_HEX), spaceBefore=2)
    else:
        cover_name = _COVER_NAME
        section_h = _SECTION_H
        item_title = _ITEM_TITLE
        item_kid = _ITEM_KID
        item_body = _ITEM_BODY
        item_badge = _ITEM_BADGE
        growth_row = _GROWTH_ROW
        summary_body = _SUMMARY_BODY

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4_PORTRAIT,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN + 22,
        title=f"{display_name} — Dreamer AI Portfolio",
        author="Dreamer AI",
    )

    story: list = []

    # ---- 1. Cover + 2. Summary (first page) -----------------------------
    brand_line = "Dreamer AI"
    story.append(Paragraph(brand_line, _COVER_BRAND))
    story.append(Spacer(1, 2))
    story.append(Paragraph(_PORTFOLIO_TITLE.get(lang_code, _PORTFOLIO_TITLE["en"]), cover_name))
    story.append(Paragraph(display_name, _style("cover-sub-name", fontSize=13, leading=18,
                                                textColor=colors.HexColor(MUTED_HEX))))
    if date_text:
        story.append(Paragraph(date_text, _COVER_SUB))
    story.append(Spacer(1, 10))

    intro_key = "has_items" if has_items else "empty"
    intro = _SUMMARY_INTRO[intro_key].get(lang_code, _SUMMARY_INTRO[intro_key]["en"])
    if has_items:
        story.append(Paragraph(_SUMMARY_TITLE.get(lang_code, _SUMMARY_TITLE["en"]), section_h))
        story.append(Paragraph(intro, summary_body))
        story.append(Spacer(1, 6))

    # ---- 3. Highlights + 4. Growth notes ---------------------------------
    if has_items:
        first_block_done = False

        def page_items_chunks(items: Sequence[Dict[str, str]]):
            for i in range(0, len(items), per_page):
                yield items[i : i + per_page]

        for chunk in page_items_chunks(cards):
            block: list = []
            if not first_block_done:
                block.append(Paragraph(
                    _SECTION_TITLES["highlights"].get(lang_code, "Highlights"), section_h))
                first_block_done = True
            for card in chunk:
                title = _clean(card.get("title")) or "Untitled piece"
                kid = _clean(card.get("kid_label"))
                body = _truncate(card.get("artifact_summary", ""), _MAX_ARTIFACT_CHARS)
                comps = card.get("competencies_4d") or []
                card_flow: list = [Paragraph(title, item_title)]
                if kid:
                    card_flow.append(Paragraph(kid, item_kid))
                if body:
                    card_flow.append(Paragraph(body, item_body))
                if comps:
                    badge_text = _BADGE_JOIN.join("◆ " + _clean(c) for c in comps)
                    card_flow.append(Paragraph(badge_text, item_badge))
                card_flow.append(Spacer(1, 4))
                block.append(KeepTogether(card_flow))
            story.extend(block)
            story.append(PageBreak())

        # Growth notes — one kid-facing line per item (never internal)
        growth_title = _SECTION_TITLES["growth"].get(lang_code, "Growth Notes")
        story.append(Paragraph(growth_title, section_h))
        prefix = _GROWTH_PREFIX.get(lang_code, _GROWTH_PREFIX["en"])
        growth_rows: list = []
        for card in cards:
            kid = _clean(card.get("kid_label"))
            growth = _clean(card.get("growth_note")) or kid
            line = growth if not kid else growth
            if not line:
                line = _clean(card.get("title")) or "—"
            row = Paragraph(f"{prefix}{line}", growth_row)
            growth_rows.append(row)
        for row in growth_rows:
            story.append(KeepTogether(row))
    else:
        # Empty portfolio: cover + summary only (spec §6 acceptance #4)
        story.append(Paragraph(intro, summary_body))

    def _footer_cb(canvas, doc_):
        _footer(canvas, doc_, date_text, lang_code)

    doc.build(story, onFirstPage=_footer_cb, onLaterPages=_footer_cb)
    return buf.getvalue()
