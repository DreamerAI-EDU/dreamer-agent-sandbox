"""PR-5 frozen-copy extractor — machine-extract 施工令 §三 + design book §6.

The PR-5 brief (施工令 PR-5, 2026-10-20) freezes two blocks of wording that a
parent console is allowed to show, plus the teacher-only crosswalk:

  * §三  the 3 (band) x 3 (language) friendly-name grid, the level names and
         the parent-facing banned-term list              -> 施工令
  * §6   the nine crosswalk rows, its heading / purpose / column heads and the
         standard answer, verbatim                        -> design book v1.1

``config/pr5_frozen_copy.json`` is the machine copy of exactly that. It is
regenerated ONLY by this script, from the two signed originals, with a hard
sha256 gate on both files — a hand-edited or re-wrapped source can never slip a
"similar but not identical" sentence into the parent console.

Usage::

    python scripts/extract_pr5_frozen_copy.py \
        --brief  "…/施工令_PR5_教師台UI+家長端視圖_2026-10-20.md" \
        --book   "…/家长评估报告_设计书_v1_2026-10-15 (1).md" \
        --out    config/pr5_frozen_copy.json

Exit code 1 on any hash mismatch, missing section or unexpected table shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Signed-original digests (KIMI archive copies). Overriding these means the
#: extracted text is no longer the signed text — refuse, don't warn.
BRIEF_SHA256 = "C7BBF6EEA478C3C13647E24AF5F4D442FF231C047F26A2AB094A44B9F6F736D5"
BOOK_SHA256 = "753A691FF158977521DBA3218025A17BBF2388905EE867C63DFD04BE17737429"

BANDS = ("P1-P3", "P4-P6", "S1-S3")
LANGS = ("en", "zh-hk", "zh-cn")

#: §三 banned terms, in brief order. Kept here as the fallback shape check —
#: the values written to JSON are read back out of the brief itself.
EXPECTED_FORBIDDEN = (
    "IB",
    "ATL",
    "Inquirer",
    "Learner Profile",
    "Proficient",
    "Excellent",
    "kid_label",
    "citations",
    "cost",
    "P1-P3",
    "P4-P6",
    "S1-S3",
)


class ExtractError(RuntimeError):
    """The source does not contain the signed wording — stop, don't guess."""


def sha256_of(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest().upper()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _table_rows(block: str) -> list[list[str]]:
    """Split a markdown table block into cell lists (data rows only)."""
    rows: list[list[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def extract_band_grid(brief: str) -> dict[str, dict[str, str]]:
    anchor = "band 家长友好名"
    start = brief.find(anchor)
    if start < 0:
        raise ExtractError("§三 band friendly-name table not found in the brief")
    block = brief[start : brief.find("其余家长端文案", start)]
    rows = _table_rows(block)
    if not rows or rows[0][0] != "band":
        raise ExtractError(f"unexpected band table head: {rows[:1]}")
    grid: dict[str, dict[str, str]] = {}
    for cells in rows[1:]:
        if len(cells) != 4:
            raise ExtractError(f"band row must have 4 cells: {cells}")
        code = cells[0]
        if code not in BANDS:
            raise ExtractError(f"unexpected band code {code!r}")
        grid[code] = dict(zip(LANGS, cells[1:]))
    if tuple(grid) != BANDS:
        raise ExtractError(f"band grid incomplete or reordered: {tuple(grid)}")
    for code, cells in grid.items():
        for lang, text in cells.items():
            if not text:
                raise ExtractError(f"empty frozen cell {code}/{lang}")
        # The friendly name must not BE the raw code (B3: parents never see it).
        for lang, text in cells.items():
            if text.strip() == code:
                raise ExtractError(f"{code}/{lang} is the raw code, not a name")
    return grid


LEVEL_LINE = re.compile(r"等级名沿用冻结名（([^）]*)）")


def extract_level_names(brief: str) -> dict[str, list[str]]:
    match = LEVEL_LINE.search(brief)
    if not match:
        raise ExtractError("§三 frozen level-name line not found")
    groups = []
    for chunk in match.group(1).split("；"):
        names = [part.strip() for part in chunk.strip().split("／") if part.strip()]
        if len(names) != 4:
            raise ExtractError(f"level line group must hold 4 names: {chunk!r}")
        groups.append(names)
    if len(groups) != 3:
        raise ExtractError(f"level line must hold 3 languages: {groups}")
    return {lang: groups[i] for i, lang in enumerate(LANGS)}


FORBIDDEN_LINE = re.compile(r"家长端禁词表[^：]*：([^\n]*)")


def extract_forbidden_terms(brief: str) -> list[str]:
    match = FORBIDDEN_LINE.search(brief)
    if not match:
        raise ExtractError("§三 banned-term line not found")
    terms = re.findall(r"`([^`]+)`", match.group(1))
    if tuple(terms) != EXPECTED_FORBIDDEN:
        raise ExtractError(f"banned-term list drifted: {terms}")
    return terms


def extract_crosswalk(book: str) -> dict[str, Any]:
    heading_marker = "## 第 6 章"
    start = book.find(heading_marker)
    if start < 0:
        raise ExtractError("design book §6 heading not found")
    end = book.find("\n---", start)
    if end < 0:
        raise ExtractError("design book §6 has no closing rule (hard boundary)")
    block = book[start:end]
    lines = [line for line in block.splitlines() if line.strip()]
    if len(lines) < 5:
        raise ExtractError(f"§6 block too short: {lines}")

    heading = lines[0].strip()
    purpose = lines[1].strip()
    table = _table_rows("\n".join(lines[2:]))
    if not table:
        raise ExtractError("§6 crosswalk table not found")
    columns = table[0]
    if len(columns) != 3:
        raise ExtractError(f"§6 table must have 3 columns: {columns}")
    rows = []
    for cells in table[1:]:
        if len(cells) != 3:
            raise ExtractError(f"§6 row must have 3 cells: {cells}")
        rows.append(
            {
                "parentSees": cells[0],
                "internal": cells[1],
                "oralBridge": cells[2],
            }
        )
    if len(rows) != 9:
        raise ExtractError(f"§6 must hold exactly nine rows, got {len(rows)}")

    # The standard answer is the paragraph AFTER the table's last line (start
    # from the next line, not the byte after the cell — the rest of that row is
    # still table syntax).
    last_row_line = next(
        (
            index
            for index, line in enumerate(lines)
            if rows[-1]["oralBridge"] in line
        ),
        None,
    )
    if last_row_line is None:
        raise ExtractError("§6 last crosswalk row not locatable in the block")
    tail = [line.strip() for line in lines[last_row_line + 1 :] if line.strip()]
    standard_answer = tail[0] if tail else ""
    if not standard_answer.startswith("若家长直接问"):
        raise ExtractError(f"§6 standard answer not found: {standard_answer!r}")

    return {
        "sectionHeading": heading,
        "title": heading[len("## ") :] if heading.startswith("## ") else heading,
        "purpose": purpose,
        "columns": {
            "parentSees": columns[0],
            "internal": columns[1],
            "oralBridge": columns[2],
        },
        "rows": rows,
        "standardAnswer": standard_answer,
    }


def build(brief_path: str, book_path: str) -> dict[str, Any]:
    brief_sha = sha256_of(brief_path)
    book_sha = sha256_of(book_path)
    if brief_sha != BRIEF_SHA256:
        raise ExtractError(f"brief sha256 {brief_sha} != signed {BRIEF_SHA256}")
    if book_sha != BOOK_SHA256:
        raise ExtractError(f"book sha256 {book_sha} != signed {BOOK_SHA256}")

    brief = read_text(brief_path)
    book = read_text(book_path)
    return {
        "_note": (
            "PR-5 frozen copy — machine extraction of 施工令 §三 (band grid, level "
            "names, banned terms) and design book v1.1 §6 (teacher crosswalk). "
            "Regenerate with scripts/extract_pr5_frozen_copy.py; never hand-edit."
        ),
        "sources": {
            "brief": {
                "name": os.path.basename(brief_path),
                "sha256": brief_sha,
                "sections": ["三、冻结文案"],
            },
            "book": {
                "name": os.path.basename(book_path),
                "sha256": book_sha,
                "sections": ["第 6 章　老师 crosswalk 一页纸"],
            },
        },
        "bandLabels": extract_band_grid(brief),
        "levelNames": extract_level_names(brief),
        "forbiddenTerms": extract_forbidden_terms(brief),
        "crosswalk": extract_crosswalk(book),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True, help="施工令 PR-5 markdown")
    parser.add_argument("--book", required=True, help="design book v1.1 (signed copy)")
    parser.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "config", "pr5_frozen_copy.json"),
        help="output JSON path",
    )
    args = parser.parse_args(argv)

    try:
        payload = build(args.brief, args.book)
    except ExtractError as exc:
        print(f"EXTRACT FAILED: {exc}", file=sys.stderr)
        return 1

    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest().upper()
    print(f"wrote {args.out}")
    print(f"sha256 {digest}")
    print(
        "bands {n_band} x {n_lang} = {cells} cells; crosswalk rows {rows}; "
        "banned terms {terms}".format(
            n_band=len(payload["bandLabels"]),
            n_lang=len(LANGS),
            cells=len(payload["bandLabels"]) * len(LANGS),
            rows=len(payload["crosswalk"]["rows"]),
            terms=len(payload["forbiddenTerms"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
