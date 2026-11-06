"""PR-6 S2 — parent report PDF renderer (bilingual, stacked, deterministic).

Scope (施工令 PR-6 §A1-4 / §S2):

* **Input is the parent-safe projection**, never a raw DB row. The caller
  passes the same dict ``auth.api._parent_report_view`` hands to the web
  client (masked student id, ``_scrub_parent_keys`` applied) plus the paired
  descriptors computed from the stored 0-3 scores. A renderer that can only
  see scrubbed data cannot leak an internal slot into a file that leaves the
  server (PDPO red line, same discipline as ``agents/portfolio_pdf.py``).
* **Stacked bilingual layout**: every label and every descriptor prints the
  English line first and the Chinese line under it (A1-4). The pair is
  ``(en, zh)`` where ``zh`` is zh-HK for ``lang_code`` in
  ``{"en", "zh-hk"}`` and zh-CN for ``"zh-cn"`` (A1-1).
* **Free text stays single-language**: the narrative paragraph and each
  topic's ``last_label_parent`` / evidence text are printed verbatim in the
  stored language. Nothing here translates, rewrites or machine-translates a
  sentence — 零新措辭 / 冇機翻.
* **Deterministic bytes**: reportlab stamps ``/CreationDate``,
  ``/ModDate`` and a random ``/ID`` into every document it writes, which
  would make a golden hash impossible. ``_normalise_bytes`` rewrites those
  tokens in place with fixed values so two renders of the same input are
  byte-identical (T-9 golden render).
* **Every human-readable word comes from a frozen asset**:

  - ``PARENT_REPORT_COPY`` (frontend/src/lib/parentReportCopy.ts) — chrome
    words approved in the PR-5 wording declaration;
  - ``config/pr5_frozen_copy.json`` ``bandLabels`` — frozen §三 band grid;
  - ``config/report_descriptors.json`` — the 144-cell descriptor table.

  ``tests/test_pr6_report_pdf.py`` walks ``_CHROME`` and asserts every
  literal appears verbatim in those assets, so a new word cannot slip in
  (程式化斷言證明).

Boundaries: pure function, no DB import, no file IO, no state transition.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from io import BytesIO
from typing import Any, Dict, List, Mapping, Optional, Tuple

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from auth import report_descriptors as rd

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Same bundled CJK font as the portfolio PDF (repo + image requirement).
_FONT_PATH = os.path.join(_REPO_ROOT, "assets", "fonts", "NotoSansSC-Regular.ttf")
_FONT_NAME = "NotoSansSC"
_FROZEN_COPY_PATH = os.path.join(_REPO_ROOT, "config", "pr5_frozen_copy.json")

BRAND_HEX = "#00023D"
MUTED_HEX = "#5A6270"
RULE_HEX = "#C9CFDA"

PAGE_MARGIN = 16 * 2.835  # ~16mm in points

#: Fixed metadata so the produced file hashes the same on every machine and
#: every run (T-9). Not a date anyone reads — the visible date comes from the
#: report row (``published_at``).
_FIXED_PDF_DATE = "D:20260101000000Z"
_FIXED_PRODUCER = "Dreamer AI report renderer"

# ---------------------------------------------------------------------------
# Frozen copy — mirrors frontend/src/lib/parentReportCopy.ts PARENT_REPORT_COPY
# ---------------------------------------------------------------------------
#
# Only the keys this renderer prints are mirrored; values are character-for-
# character the frozen words. The anchor test walks this table and refuses any
# literal that does not appear verbatim in the TS source.

_CHROME: Dict[str, Dict[str, str]] = {
    "title": {"en": "Weekly reports", "zh-hk": "每週報告", "zh-cn": "每周报告"},
    "weekRange": {"en": "Weeks", "zh-hk": "週次", "zh-cn": "周次"},
    "published": {"en": "Published", "zh-hk": "發佈日期", "zh-cn": "发布日期"},
    "band": {"en": "Stage", "zh-hk": "階段", "zh-cn": "阶段"},
    "version": {"en": "Version", "zh-hk": "版本", "zh-cn": "版本"},
    "summary": {"en": "At a glance", "zh-hk": "學習概覽", "zh-cn": "学习概览"},
    "sessions": {"en": "Learning sessions", "zh-hk": "學習節數", "zh-cn": "学习节数"},
    "topics": {"en": "Topics covered", "zh-hk": "涵蓋主題", "zh-cn": "涵盖主题"},
    "minutes": {"en": "Minutes", "zh-hk": "分鐘", "zh-cn": "分钟"},
    "narrative": {"en": "What we saw", "zh-hk": "我哋觀察到", "zh-cn": "我们观察到"},
    "dimensions": {
        "en": "4 Dimension Evaluation",
        "zh-hk": "4 Dimension Evaluation",
        "zh-cn": "4 Dimension Evaluation",
    },
    "topicsTitle": {"en": "Topic detail", "zh-hk": "主題詳情", "zh-cn": "主题详情"},
    "mastery": {"en": "Mastery", "zh-hk": "掌握度", "zh-cn": "掌握度"},
    "evidence": {"en": "Evidence", "zh-hk": "學習證據", "zh-cn": "学习证据"},
}

#: 0–3 → frozen level name, en + zh (parentReportCopy.ts LEVEL_LABEL). Printed
#: as a pair so the T-9 text-extraction assertion can look for `Exemplary 出色`.
_LEVELS: Dict[int, Dict[str, str]] = {
    3: {"en": "Exemplary", "zh-hk": "出色", "zh-cn": "出色"},
    2: {"en": "Achieved", "zh-hk": "達標", "zh-cn": "达标"},
    1: {"en": "Developing", "zh-hk": "進展中", "zh-cn": "进展中"},
    0: {"en": "Not Yet", "zh-hk": "尚未開始", "zh-cn": "尚未开始"},
}


def level_pair(level: int, zh_lang: str) -> str:
    """`Exemplary 出色` — EN first, the zh cell under the same dash-free line.

    Unknown level → empty string (never an invented word).
    """
    row = _LEVELS.get(level)
    if not row:
        return ""
    return "%s %s" % (row["en"], row.get(zh_lang, row["zh-hk"]))


#: 4D dimension names — the Dreamer words are identical in every language
#: (design book §4.2), so they print once.
_DIMENSION_NAMES: Dict[str, str] = {
    "DREAM": "Dream",
    "DISCOVER": "Discover",
    "DESIGN": "Design",
    "DELIVER": "Deliver",
}

#: Brand mark inherited from agents/portfolio_pdf.py — not new wording.
_BRAND = "Dreamer AI"

#: Language tokens in one place. The stack is always English-first (A1-4), so
#: ``_TOP_LANG`` is fixed; the bottom slot is the Chinese variant that pairs
#: with the stored ``lang_code`` (zh-HK for zh-hk/en, zh-CN for zh-cn — A1-1).
_TOP_LANG = "en"
_ZH_HK = "zh-hk"
_ZH_CN = "zh-cn"


def chrome(key: str, lang: str) -> str:
    """Frozen chrome word for ``key`` in ``lang`` (unknown lang → EN)."""
    row = _CHROME[key]
    return row.get(lang, row["en"])


def paired_langs(lang_code: str) -> Tuple[str, str]:
    """(top, bottom) language pair for a stored ``lang_code`` (施工令 A1-1).

    zh-HK → 繁 + EN ; zh-CN → 簡 + EN ; en → EN + 繁. The print order is always
    English on top, so the tuple is ``("en", zh_variant)`` regardless of the
    stored language: index 0 prints first, index 1 underneath.
    """
    if lang_code == _ZH_CN:
        return (_TOP_LANG, _ZH_CN)
    return (_TOP_LANG, _ZH_HK)


_FROZEN_COPY: Optional[dict] = None


def frozen_copy() -> dict:
    """``config/pr5_frozen_copy.json`` (read-only frozen asset)."""
    global _FROZEN_COPY
    if _FROZEN_COPY is None:
        with open(_FROZEN_COPY_PATH, "r", encoding="utf-8") as fh:
            _FROZEN_COPY = json.load(fh)
    return _FROZEN_COPY


def reset_cache() -> None:
    """Drop the cached frozen asset (tests / reloads only)."""
    global _FROZEN_COPY
    _FROZEN_COPY = None


def band_label(band: Optional[str], lang: str) -> str:
    """Frozen §三 band friendly name — the raw band code is never printed."""
    labels = frozen_copy().get("bandLabels") or {}
    cell = labels.get(band or "") or labels.get("P1-P3") or {}
    return str(cell.get(lang) or cell.get("en") or "")


# ---------------------------------------------------------------------------
# reportlab setup
# ---------------------------------------------------------------------------


def _ensure_font() -> None:
    """Register the bundled CJK TTF once per process."""
    if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    if not os.path.exists(_FONT_PATH):
        raise RuntimeError(
            "CJK font not found: %s — bundle assets/fonts/NotoSansSC-Regular.ttf "
            "in the repo and the image (PR-6 PDF requirement)" % _FONT_PATH
        )
    pdfmetrics.registerFont(TTFont(_FONT_NAME, _FONT_PATH))


def _style(name: str, **kw) -> ParagraphStyle:
    base = {
        "fontName": _FONT_NAME,
        "fontSize": 10,
        "leading": 14,
        "textColor": colors.HexColor(BRAND_HEX),
        "wordWrap": "CJK",
        "allowWidows": 0,
        "allowOrphans": 0,
    }
    base.update(kw)
    return ParagraphStyle(name, **base)


_TITLE = _style("r-title", fontSize=19, leading=26, spaceAfter=2)
_TITLE_ZH = _style(
    "r-title-zh", fontSize=14, leading=20, textColor=colors.HexColor(MUTED_HEX), spaceAfter=4
)
_SECTION = _style("r-section", fontSize=13, leading=18, spaceBefore=10, spaceAfter=2)
_SECTION_ZH = _style(
    "r-section-zh", fontSize=10.5, leading=15, textColor=colors.HexColor(MUTED_HEX), spaceAfter=4
)
_BODY = _style("r-body", fontSize=10, leading=15)
_BODY_ZH = _style("r-body-zh", fontSize=10, leading=15, textColor=colors.HexColor(MUTED_HEX))
_META = _style("r-meta", fontSize=9, leading=13, textColor=colors.HexColor(MUTED_HEX))
_DIM_NAME = _style("r-dim-name", fontSize=11, leading=15)
_TOPIC = _style("r-topic", fontSize=10, leading=14, spaceBefore=4)


def _clean(value: Any) -> str:
    """Flatten a scalar to safe text — never a raw list/dict repr."""
    if value is None or isinstance(value, (list, tuple, dict, bool)):
        return ""
    return " ".join(str(value).split())


def _date_text(value: Any) -> str:
    """``published_at`` → ``YYYY-MM-DD`` (same slice the web view prints)."""
    return _clean(value)[:10]


def _num(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# Determinism — fixed info dictionary + trailer id (T-9)
# ---------------------------------------------------------------------------


def _normalise_bytes(raw: bytes) -> bytes:
    """Rewrite the volatile tokens of a reportlab PDF in place (T-9).

    reportlab writes ``/CreationDate``, ``/ModDate`` and a document ``/ID``
    derived from the wall clock. Bytes are only rewritten when the token
    length is unchanged, so the xref offsets stay valid and the document
    structure is never re-serialised (no re-flow, no re-compress).
    """
    out = raw

    # 1. Info-dictionary dates → fixed literal of identical length.
    for field in (b"/CreationDate", b"/ModDate"):
        index = out.find(field)
        if index < 0:
            continue
        start = out.find(b"(", index) + 1
        end = out.find(b")", start)
        if start <= 0 or end < 0:
            continue
        current = out[start:end]
        replacement = _FIXED_PDF_DATE.encode("ascii")
        if len(replacement) < len(current):
            replacement = replacement.ljust(len(current), b"0")
        out = out[:start] + replacement[: len(current)] + out[end:]

    # 2. Trailer /ID [<hex> <hex>] → digest of the (now stable) body.
    id_match = re.search(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]", out)
    if id_match is not None:
        first_width = len(id_match.group(1))
        second_width = len(id_match.group(2))
        digest = hashlib.sha256(out).hexdigest().upper()
        first = (digest * 4)[:first_width]
        second = (digest * 4)[:second_width]
        out = (
            out[: id_match.start()]
            + b"/ID [<"
            + first.encode("ascii")
            + b"><"
            + second.encode("ascii")
            + b">]"
            + out[id_match.end():]
        )
    return out


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------


def dimension_rows(view: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Paired descriptor rows in the frozen ``DIMENSIONS`` order.

    ``descriptor_pairs`` comes from ``auth.report_descriptors.descriptor_pairs``
    (stored scores → the two cells of the same 144-table row). A dimension the
    teacher never graded has no entry and prints no row — never a bogus
    "Not Yet" (design book §3.2).
    """
    pairs = view.get("descriptor_pairs")
    if not isinstance(pairs, Mapping):
        return []
    rows: List[Dict[str, str]] = []
    for code in rd.DIMENSIONS:
        entry = pairs.get(code)
        if not isinstance(entry, Mapping):
            continue
        en_text = _clean(entry.get("en"))
        zh_text = _clean(entry.get("zh"))
        if not en_text and not zh_text:
            continue
        level = entry.get("level")
        if isinstance(level, bool) or not isinstance(level, int):
            level = None
        rows.append(
            {
                "code": code,
                "name": _DIMENSION_NAMES.get(code, code),
                "level": level,
                "en": en_text,
                "zh": zh_text,
            }
        )
    return rows


def render_report_pdf(view: Mapping[str, Any]) -> bytes:
    """Render one approved report to A4 PDF bytes (deterministic).

    ``view`` is the parent-safe projection: the ``auth.api._parent_report_view``
    dict plus ``descriptor_pairs``. Unknown keys are ignored on purpose.
    """
    _ensure_font()

    lang_code = _clean(view.get("lang_code")) or "en"
    top_lang, bottom_lang = paired_langs(lang_code)
    payload = view.get("payload") if isinstance(view.get("payload"), Mapping) else {}
    inner = payload.get("report") if isinstance(payload.get("report"), Mapping) else {}
    summary = inner.get("summary") if isinstance(inner.get("summary"), Mapping) else {}
    topics = inner.get("topics") if isinstance(inner.get("topics"), list) else []

    # Deterministic document identity: report key lives in the fixed info
    # dictionary instead of a clock-derived UUID.
    report_key = "%s|v%s|%s" % (
        _clean(view.get("report_id")),
        _clean(view.get("version")),
        _clean(view.get("published_at")),
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title="%s %s-%s"
        % (
            chrome("title", "en"),
            _num(view.get("week_from")),
            _num(view.get("week_to")),
        ),
        author=_BRAND,
        subject=report_key,
        creator=_FIXED_PRODUCER,
        producer=_FIXED_PRODUCER,
    )

    story: list = []

    # ---- header: title pair + frozen meta pairs --------------------------
    story.append(Paragraph(_BRAND, _META))
    story.append(Paragraph(chrome("title", top_lang), _TITLE))
    story.append(Paragraph(chrome("title", bottom_lang), _TITLE_ZH))

    weeks_top = "%s %s–%s" % (
        chrome("weekRange", top_lang),
        _num(view.get("week_from")),
        _num(view.get("week_to")),
    )
    weeks_bottom = "%s %s–%s" % (
        chrome("weekRange", bottom_lang),
        _num(view.get("week_from")),
        _num(view.get("week_to")),
    )
    meta_pairs = [
        (weeks_top, weeks_bottom),
        (
            "%s %s" % (chrome("band", top_lang), band_label(_clean(view.get("age_band")), top_lang)),
            "%s %s"
            % (chrome("band", bottom_lang), band_label(_clean(view.get("age_band")), bottom_lang)),
        ),
        (
            "%s v%s" % (chrome("version", top_lang), _num(view.get("version"))),
            "%s v%s" % (chrome("version", bottom_lang), _num(view.get("version"))),
        ),
        (
            "%s %s" % (chrome("published", top_lang), _date_text(view.get("published_at"))),
            "%s %s" % (chrome("published", bottom_lang), _date_text(view.get("published_at"))),
        ),
    ]
    for top, bottom in meta_pairs:
        story.append(Paragraph(top, _META))
        story.append(Paragraph(bottom, _META))
    story.append(Spacer(1, 6))

    # ---- narrative (free text: verbatim, never translated) ---------------
    content = _clean(payload.get("content"))
    if content:
        story.append(Paragraph(chrome("narrative", top_lang), _SECTION))
        story.append(Paragraph(chrome("narrative", bottom_lang), _SECTION_ZH))
        story.append(Paragraph(content, _BODY))
        story.append(Spacer(1, 4))

    # ---- at a glance -----------------------------------------------------
    story.append(Paragraph(chrome("summary", top_lang), _SECTION))
    story.append(Paragraph(chrome("summary", bottom_lang), _SECTION_ZH))
    # total_duration_seconds is the stored truth; null means "no data" and is
    # printed as a dash, never as a fabricated 0 (design book §3.2 discipline).
    seconds = summary.get("total_duration_seconds")
    minutes = "—"
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        minutes = str(int(seconds // 60))
    glance = [
        ("sessions", _num(summary.get("session_count"))),
        ("topics", _num(summary.get("topics_touched"))),
        ("minutes", minutes),
    ]
    for key, value in glance:
        story.append(Paragraph("%s  %s" % (chrome(key, top_lang), value), _BODY))
        story.append(Paragraph("%s  %s" % (chrome(key, bottom_lang), value), _BODY_ZH))

    # ---- 4D descriptors, stacked pairs ----------------------------------
    rows = dimension_rows(view)
    if rows:
        story.append(Paragraph(chrome("dimensions", top_lang), _SECTION))
        # `dimensions` is the one chrome key whose zh value is the same EN
        # word (frozen as such in parentReportCopy.ts) — print it once rather
        # than stacking the identical line twice.
        if chrome("dimensions", bottom_lang) != chrome("dimensions", top_lang):
            story.append(Paragraph(chrome("dimensions", bottom_lang), _SECTION_ZH))
        for row in rows:
            block: list = [Paragraph(row["name"], _DIM_NAME)]
            if row["level"] is not None:
                pair = level_pair(row["level"], bottom_lang)
                if pair:
                    block.append(Paragraph(pair, _META))
            if row["en"]:
                block.append(Paragraph(row["en"], _BODY))
            if row["zh"]:
                block.append(Paragraph(row["zh"], _BODY_ZH))
            block.append(Spacer(1, 3))
            story.append(KeepTogether(block))

    # ---- topic detail ----------------------------------------------------
    printed_topics = [t for t in topics if isinstance(t, Mapping)]
    if printed_topics:
        story.append(Paragraph(chrome("topicsTitle", top_lang), _SECTION))
        story.append(Paragraph(chrome("topicsTitle", bottom_lang), _SECTION_ZH))
        for topic in printed_topics:
            block = [Paragraph(_clean(topic.get("subject")) or "—", _TOPIC)]
            mastery = topic.get("mastery_pct")
            if isinstance(mastery, (int, float)) and not isinstance(mastery, bool):
                pct = int(round(float(mastery) * 100))
                block.append(Paragraph("%s  %d / 100" % (chrome("mastery", top_lang), pct), _META))
                block.append(
                    Paragraph("%s  %d / 100" % (chrome("mastery", bottom_lang), pct), _META)
                )
            label = _clean(topic.get("last_label_parent"))
            if label:
                block.append(Paragraph(label, _BODY))
            evidence = topic.get("recent_evidence")
            if isinstance(evidence, list):
                lines = []
                for item in evidence:
                    if not isinstance(item, Mapping):
                        continue
                    text = _clean(item.get("evidence_text"))
                    if not text:
                        continue
                    date = _clean(item.get("date"))
                    lines.append("%s %s" % (date, text) if date else text)
                if lines:
                    block.append(Paragraph(chrome("evidence", top_lang), _META))
                    block.append(Paragraph(chrome("evidence", bottom_lang), _META))
                    for line in lines:
                        block.append(Paragraph(line, _BODY_ZH))
            block.append(Spacer(1, 4))
            story.append(KeepTogether(block))

    published = _date_text(view.get("published_at"))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(RULE_HEX))
        canvas.setLineWidth(0.6)
        y = PAGE_MARGIN - 10
        canvas.line(PAGE_MARGIN, y, A4[0] - PAGE_MARGIN, y)
        canvas.setFont(_FONT_NAME, 7.5)
        canvas.setFillColor(colors.HexColor(MUTED_HEX))
        canvas.drawString(PAGE_MARGIN, y - 11, _BRAND)
        canvas.drawRightString(A4[0] - PAGE_MARGIN, y - 11, published)
        canvas.restoreState()

    previous_invariant = rl_config.invariant
    rl_config.invariant = 1
    try:
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    finally:
        rl_config.invariant = previous_invariant

    return _normalise_bytes(buf.getvalue())


def page_count(data: bytes) -> int:
    """Page count from the produced bytes (used by the render tests)."""
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def pdf_sha256(data: bytes) -> str:
    """Content hash stored in ``parent_reports.pdf_sha256``."""
    return hashlib.sha256(data).hexdigest()
