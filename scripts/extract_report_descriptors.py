#!/usr/bin/env python3
"""PR-4 — extract the 144 descriptor rows from design book v1.1 §5 (programmatic).

唯一内容来源（signed edition, read-only）：
  《家长评估报告 — 设计书 v1.1 签批版》(2026-10-15)
      §5.1 English / §5.2 zh-HK（繁體・香港）/ §5.3 zh-CN（简体・内地）
      三张维度表（Dream / Discover / Design / Deliver × Level 0-3 × band 3 列）。
  §5.4 Learner Profile 译名表起即停：该节及之后的内容属内部材料，不落家长档。

输出：
  <repo>/config/report_descriptors.json — 144 条 {dimension, level, band, lang, text}

不做任何手打：每个 ``text`` 都是 markdown 表格 cell 的逐字字符串；``verify()``
重新读取设计书做双向逐 cell 对碰（book -> JSON 与 JSON -> book），键集与值必须
全部一致，任何一格漂移即 raise（防静默错配）。

用法::

    python scripts/extract_report_descriptors.py --check --book <path>   # 双向校验，不写文件
    python scripts/extract_report_descriptors.py --book <path>           # 抽取 + 校验 + 写 JSON

设计书路径**必须显式给出**：``--book <path>`` 或环境变量 ``REPORT_DESIGN_BOOK``。
本脚本刻意不设默认值：2026-10-15 的签批版副本在同一日内被改写过（DISCOVER Level 0
九格措辞由「照单全收」系改成「尚未評核」系），脚本不替任何副本背书 —— 跑之前请自行
确认手头这份是不是老板签批的那一版。
设计书为历史 dated 文件，本脚本**只读**，永不改写。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

# 设计书路径只从 --book / 环境变量取，没有默认值（见 module docstring 的说明）
ENV_BOOK = "REPORT_DESIGN_BOOK"
REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "config" / "report_descriptors.json"

LANGS = ("en", "zh-hk", "zh-cn")
SECTION_HEAD = {
    "en": "### 5.1 English",
    "zh-hk": "### 5.2 zh-HK（繁體・香港）",
    "zh-cn": "### 5.3 zh-CN（简体・内地）",
}
SECTION_54 = "### 5.4 "  # 内部译名表（§5.4）— 不落家长档，仅作 §5.3 的区块结束界
BANDS = ("P1-P3", "P4-P6", "S1-S3")
DIMENSION_HEAD = re.compile(r"^\*\*(Dream|Discover|Design|Deliver)（")
LEVEL_CELL = re.compile(r"^[0-3]$")


def extract(book: Path) -> list[dict]:
    lines = book.read_text(encoding="utf-8").splitlines()
    starts, ends = {}, {}
    for lang, head in SECTION_HEAD.items():
        hit = [i for i, ln in enumerate(lines) if ln.strip() == head]
        assert len(hit) == 1, f"section heading not unique: {head}"
        starts[lang] = hit[0]
    stop_54 = [i for i, ln in enumerate(lines) if ln.strip().startswith(SECTION_54)]
    assert len(stop_54) == 1, "§5.4 heading not unique"
    for pos, lang in enumerate(LANGS):
        ends[lang] = (
            starts[LANGS[pos + 1]] if pos + 1 < len(LANGS) else stop_54[0]
        )

    entries: list[dict] = []
    for lang in LANGS:
        dimension = None
        for raw in lines[starts[lang] + 1 : ends[lang]]:
            line = raw.strip()
            head = DIMENSION_HEAD.match(line)
            if head:
                dimension = head.group(1).upper()
                continue
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[0] == "Level":                     # table header row
                assert cells[1:] == list(BANDS), f"bad header: {line}"
                continue
            if not LEVEL_CELL.match(cells[0]):          # |---|---| separator
                continue
            assert dimension is not None, f"row outside a dimension block: {line}"
            assert len(cells) == 4, f"expected 4 cells: {line}"
            level = int(cells[0])
            for band, text in zip(BANDS, cells[1:]):
                assert text, f"empty cell: {lang} {dimension} {level} {band}"
                assert "|" not in text, f"unescaped pipe: {line}"
                entries.append(
                    {
                        "dimension": dimension,
                        "level": level,
                        "band": band,
                        "lang": lang,
                        "text": text,
                    }
                )
    return entries


def verify(entries: list[dict], book: Path, json_path: Path) -> str:
    """Bidirectional cell-by-cell collision check -> evidence text."""
    book_cells = {}
    for e in entries:
        key = (e["lang"], e["dimension"], e["level"], e["band"])
        assert key not in book_cells, f"duplicate key from book: {key}"
        book_cells[key] = e["text"]

    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(written, list) and len(written) == 144, "JSON must be 144 rows"
    json_cells, order = {}, []
    for row in written:
        assert set(row) == {"dimension", "level", "band", "lang", "text"}, row
        key = (row["lang"], row["dimension"], row["level"], row["band"])
        assert key not in json_cells, f"duplicate key in JSON: {key}"
        json_cells[key] = row["text"]
        order.append(key)

    assert set(book_cells) == set(json_cells), "key sets differ"
    mismatch = [k for k in book_cells if book_cells[k] != json_cells[k]]
    assert not mismatch, f"{len(mismatch)} cells differ: {mismatch[:3]}"

    out = []
    out.append("PR-4 descriptor 逐 cell 对碰（design book v1.1 §5.1-5.3 vs config/report_descriptors.json）")
    out.append(f"source : {book}")
    out.append(f"json   : {json_path}")
    out.append("")
    out.append("每行格式: idx | lang | dimension | level | band | verdict | cell 全文")
    out.append("-" * 100)
    for i, key in enumerate(order, 1):
        lang, dim, level, band = key
        verdict = "MATCH" if book_cells[key] == json_cells[key] else "DIFF"
        out.append(
            f"{i:03d} | {lang:5s} | {dim:8s} | L{level} | {band} | {verdict} | "
            f"{book_cells[key]}"
        )
    out.append("-" * 100)
    out.append("cells promised : 144")
    out.append(f"cells compared : {len(order)}")
    out.append(f"cells matched  : {sum(1 for k in order if book_cells[k] == json_cells[k])}/144")
    diff = list(
        difflib.unified_diff(
            [book_cells[k] for k in order],
            [json_cells[k] for k in order],
            fromfile="design-book-cell",
            tofile="json-text",
            lineterm="",
        )
    )
    out.append(f"unified_diff hunks: {len(diff)}  (0 == byte-for-byte identical)")
    if diff:
        out.extend(diff[:40])
    out.append("")
    return "\n".join(out)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="抽取设计书 v1.1 §5.1-5.3 的 144 条 descriptor，并做双向逐 cell 对碰"
    )
    ap.add_argument("--book", default=None, help="设计书 markdown 路径（必填；或用 REPORT_DESIGN_BOOK）")
    ap.add_argument("--json", default=None, help="JSON 输出路径（默认 config/report_descriptors.json）")
    ap.add_argument("--check", action="store_true", help="只做双向校验，不写 JSON")
    ap.add_argument("--evidence", default=None, help="把逐 cell 对碰 raw 写到该路径（默认仅 stdout）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    book_arg = args.book or os.environ.get(ENV_BOOK)
    if not book_arg:
        print(
            "ERROR: design book path required.\n"
            f"  pass --book <path> or set {ENV_BOOK}.\n"
            "  No implicit default: the 2026-10-15 签批版 copy was edited in place\n"
            "  (DISCOVER L0 x9 wording) after it was produced, so this script refuses\n"
            "  to assume which copy is the signed one.",
            file=sys.stderr,
        )
        return 2
    book = Path(book_arg)
    json_path = Path(args.json) if args.json else OUT

    assert book.is_file(), f"design book not found: {book}"
    entries = extract(book)
    assert len(entries) == 144, f"extracted {len(entries)} rows, expected 144"

    if not args.check:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    evidence = verify(entries, book, json_path)
    if args.evidence:
        Path(args.evidence).write_text(evidence, encoding="utf-8")
    print(f"source book : {book}")
    print(f"json        : {json_path}{' (unchanged, --check)' if args.check else ''}")
    for line in evidence.splitlines():
        if line.startswith(("cells ", "unified_diff")):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
