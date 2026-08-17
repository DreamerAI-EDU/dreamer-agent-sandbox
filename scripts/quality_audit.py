#!/usr/bin/env python3
"""
Dreamer AI Phase 5 Day 23 — Quality Audit Script

Runs 12-case audit matrix against execute() and applies five
rule-based checks. Outputs two reports:
  - output/audit_report_<YYYYMMDD>.md  (human-readable)
  - output/audit_report_<YYYYMMDD>.json (machine-readable)

Usage:
  python scripts/quality_audit.py --stub    # validate audit logic (no LLM cost)
  python scripts/quality_audit.py           # real run against DeepTutor
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.hermes_scheduler import execute
from agents.subagents import register_all
from agents.registry import SubagentRegistry


# ═══════════════════════════════════════════════════════════
# CONFIG — edit here to tune audit parameters
# ═══════════════════════════════════════════════════════════

# Topic IDs from seed_topic_metadata.py
T1 = "computing-scratch-basics-01"
T2 = "maths-multiplication-02"
T3 = "computing-game-design-01"

# Default max tokens cap (env DREAMER_MAX_TOKENS overrides)
MAX_TOKENS = int(os.environ.get("DREAMER_MAX_TOKENS", "8192"))

# Per-case timeout (seconds) — real execute() can take 80-120s via WS
CASE_TIMEOUT_S = int(os.environ.get("AUDIT_CASE_TIMEOUT", "150"))

# Label blacklist — these internal labels must not leak into content
LABEL_BLACKLIST = [
    "not_yet", "internal_label", "exemplary",
    "achieved", "developing", "not yet",
]

# Sentence length thresholds (age-band dependent)
EN_WORD_LIMIT = 10    # avg words per sentence for P1-P3
CJK_CHAR_LIMIT = 15   # avg CJK chars per sentence for P1-P3

# 12-case audit matrix
CASES: List[Dict[str, Any]] = [
    {
        "n": 1, "age_band": "P1-P3", "lang": "zh-hk",
        "expected_mode": "DIRECT", "topic_id": T1,
        "query": "我想溫書，可唔可以出幾條練習俾我？",
    },
    {
        "n": 2, "age_band": "P1-P3", "lang": "en",
        "expected_mode": "CONTEXTUAL", "topic_id": None,
        "query": "I want to make a game with AI",
    },
    {
        "n": 3, "age_band": "P1-P3", "lang": "zh-cn",
        "expected_mode": "HYBRID", "topic_id": T1,
        "query": "用AI复习数学",
    },
    {
        "n": 4, "age_band": "P1-P3", "lang": "zh-cn",
        "expected_mode": "DIRECT", "topic_id": T2,
        "query": "明天要考试，帮我练习",
    },
    {
        "n": 5, "age_band": "P4-P6", "lang": "en",
        "expected_mode": "DIRECT", "topic_id": T2,
        "query": "Can you quiz me for my exam?",
    },
    {
        "n": 6, "age_band": "P4-P6", "lang": "zh-hk",
        "expected_mode": "CONTEXTUAL", "topic_id": None,
        "query": "我想整一個AI作品，可以點開始？",
    },
    {
        "n": 7, "age_band": "P4-P6", "lang": "zh-cn",
        "expected_mode": "CONTEXTUAL", "topic_id": None,
        "query": "我想做一个AI小项目",
    },
    {
        "n": 8, "age_band": "P4-P6", "lang": "en",
        "expected_mode": "HYBRID", "topic_id": T3,
        "query": "Can AI help me study for my test?",
    },
    {
        "n": 9, "age_band": "S1-S3", "lang": "zh-hk",
        "expected_mode": "HYBRID", "topic_id": T3,
        "query": "AI幫我溫書得唔得？",
    },
    {
        "n": 10, "age_band": "S1-S3", "lang": "en",
        "expected_mode": "CONTEXTUAL", "topic_id": None,
        "query": "How does AI work? I want to build a project",
    },
    {
        "n": 11, "age_band": "S1-S3", "lang": "zh-cn",
        "expected_mode": "DIRECT", "topic_id": T1,
        "query": "帮我练习代数，我要考试了",
    },
    {
        "n": 12, "age_band": "S1-S3", "lang": "zh-hk",
        "expected_mode": "HYBRID", "topic_id": T2,
        "query": "用AI幫我做功課",
    },
]

# ── Stub responses (used when --stub is active) ──────────

STUB_QUIZ_RESPONSE = {
    "agent": "assessment",
    "capability": "quiz_gen",
    "status": "ok_stub",
    "questions": [
        {
            "id": "q1",
            "question": "What is 3 × 4? Show your working.",
            "type": "short_answer",
            "grade_level": 1,
        },
        {
            "id": "q2",
            "question": "If you have 12 apples and share them equally among 3 friends, how many does each get?",
            "type": "short_answer",
            "grade_level": 1,
        },
        {
            "id": "q3",
            "question": "Draw a rectangle and divide it into 4 equal parts.",
            "type": "short_answer",
            "grade_level": 1,
        },
    ],
    "topic": "",
    "grade_level": 1,
    "rubric_id": "",
    "cost_tokens": 150,
}

STUB_WS_ERROR_RESPONSE = {
    "content": "Sorry, I couldn't connect right now. Please try again in a moment!",
    "kid_label": "ws_error",
    "citations": [],
    "cost_summary": {"ws_fallback": "stub", "error": "Connection refused (stub)"},
}


# ═══════════════════════════════════════════════════════════
# Audit helpers
# ═══════════════════════════════════════════════════════════

def _default_registry():
    reg = SubagentRegistry()
    register_all(reg)
    return reg


# ── Rule-based checks ────────────────────────────────────

def _cjk_ratio(text: str) -> float:
    """Proportion of CJK characters among alphabetic-like characters."""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    total = cjk + sum(1 for c in text if c.isalpha())
    return cjk / total if total > 0 else 0.0


def check_language_consistency(result: dict, case: dict) -> tuple:
    """Check #1: language consistency.

    lang=zh-* → CJK ratio ≥ 30%; lang=en → CJK < 5%.
    zh-hk cases also flagged for human review (simplified vs traditional).
    """
    lang = case["lang"]
    content = result.get("content", "")
    ratio = _cjk_ratio(content)
    if lang.startswith("zh"):
        passed = ratio >= 0.30
        detail = f"CJK ratio={ratio:.2f}" + (" (< 30%)" if not passed else "")
        if lang == "zh-hk":
            detail += " [human review: simplified vs traditional]"
    else:
        passed = ratio < 0.05
        detail = f"CJK ratio={ratio:.2f}" + (" (≥ 5%)" if not passed else "")
    return passed, detail


def check_label_leak(result: dict, case: dict) -> tuple:
    """Check #2: label leakage — internal labels must not appear in content."""
    content = result.get("content", "")
    content_lower = content.lower()
    leaked = []
    for lbl in LABEL_BLACKLIST:
        # case-insensitive word boundary match
        pattern = re.compile(r"\b" + re.escape(lbl) + r"\b", re.IGNORECASE)
        if pattern.search(content_lower):
            leaked.append(lbl)
    if leaked:
        return False, f"Leaked labels: {', '.join(leaked)}"
    return True, "No leaked labels"


def check_structure(result: dict, case: dict) -> tuple:
    """Check #3: structure completeness — all 7 keys present + mode/lang_code/age_band match."""
    required_keys = [
        "content", "mode", "lang_code", "age_band",
        "kid_label", "citations", "cost_summary",
    ]
    missing = [k for k in required_keys if k not in result]
    if missing:
        return False, f"Missing keys: {', '.join(missing)}"

    mismatches = []
    actual_mode = result.get("mode", "")
    expected_start = case["expected_mode"]
    # Mode label may include suffix like DIRECT_clarifying / HYBRID_clarifying
    if not actual_mode.startswith(expected_start):
        mismatches.append(f"mode={actual_mode} (expected ^={expected_start})")
    if result.get("lang_code") != case["lang"]:
        mismatches.append(
            f"lang_code={result.get('lang_code')} (expected {case['lang']})"
        )
    if result.get("age_band") != case["age_band"]:
        mismatches.append(
            f"age_band={result.get('age_band')} (expected {case['age_band']})"
        )

    if mismatches:
        return False, "; ".join(mismatches)
    return True, "All 7 keys present, fields match"


def _split_sentences_en(text: str) -> List[str]:
    """Split English text into sentences."""
    return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]


def _split_sentences_zh(text: str) -> List[str]:
    """Split Chinese text into sentences."""
    return [s.strip() for s in re.split(r"[。！？]+", text) if s.strip()]


def check_sentence_length(result: dict, case: dict) -> tuple:
    """Check #4: sentence length (P1-P3 only).
    en: avg ≤ 10 words; zh: avg ≤ 15 CJK chars.
    """
    if not case["age_band"].startswith("P1"):
        return True, "N/A (not P1-P3)"

    content = result.get("content", "")
    lang = case["lang"]
    if lang == "en":
        sentences = _split_sentences_en(content)
        if not sentences:
            return True, "No sentences to measure"
        avg = sum(len(s.split()) for s in sentences) / len(sentences)
        passed = avg <= EN_WORD_LIMIT
        detail = f"avg words/sentence={avg:.1f}" + (
            f" (>{EN_WORD_LIMIT})" if not passed else ""
        )
    else:
        sentences = _split_sentences_zh(content)
        if not sentences:
            return True, "No sentences to measure"
        avg = sum(
            sum(1 for c in s if "\u4e00" <= c <= "\u9fff") for s in sentences
        ) / len(sentences)
        passed = avg <= CJK_CHAR_LIMIT
        detail = f"avg CJK chars/sentence={avg:.1f}" + (
            f" (>{CJK_CHAR_LIMIT})" if not passed else ""
        )
    return passed, detail


def check_cost(result: dict, case: dict) -> tuple:
    """Check #5: cost_summary tokens ≤ MAX_TOKENS."""
    cost = result.get("cost_summary", {})
    tokens = (
        cost.get("tokens")
        or cost.get("total_tokens")
        or cost.get("cost_tokens")
        or cost.get("usage_total_tokens")
    )
    if tokens is None:
        # Stub responses may not include tokens — pass
        return True, "No token field (stub/non-LLM response)"
    passed = int(tokens) <= MAX_TOKENS
    detail = f"tokens={tokens}" + (
        f" (>{MAX_TOKENS})" if not passed else ""
    )
    return passed, detail


CHECKS = [
    ("language_consistency", check_language_consistency),
    ("label_leak", check_label_leak),
    ("structure", check_structure),
    ("sentence_length", check_sentence_length),
    ("cost", check_cost),
]


# ── Case runner ──────────────────────────────────────────

async def run_case(
    case: dict,
    registry: SubagentRegistry,
    stub: bool = False,
) -> Dict[str, Any]:
    """Run a single audit case and collect result + raw response."""
    start = time.perf_counter()
    raw_result: Optional[Dict] = None
    error: Optional[str] = None

    try:
        row = await asyncio.wait_for(
            execute(
                case["query"],
                f"audit_stu_{case['n']:02d}",
                case["age_band"],
                topic_id=case.get("topic_id"),
                registry=registry,
            ),
            timeout=CASE_TIMEOUT_S,
        )
        raw_result = row
    except asyncio.TimeoutError:
        error = f"Timeout after {CASE_TIMEOUT_S}s"
        raw_result = {
            "content": "",
            "mode": "TIMEOUT",
            "lang_code": case["lang"],
            "age_band": case["age_band"],
            "kid_label": "timeout",
            "citations": [],
            "cost_summary": {"timeout": True},
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raw_result = {
            "content": "",
            "mode": "ERROR",
            "lang_code": case["lang"],
            "age_band": case["age_band"],
            "kid_label": "error",
            "citations": [],
            "cost_summary": {"error": str(exc)},
        }

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Run all checks
    checks = {}
    for ck_name, ck_fn in CHECKS:
        try:
            passed, detail = ck_fn(raw_result, case)
        except Exception as exc:
            passed, detail = False, f"check_raised: {exc}"
        checks[ck_name] = {"passed": passed, "detail": detail}

    # llm_path check: in real mode, stub fallback is a hard fail
    if not stub:
        status = (raw_result.get("cost_summary") or {}).get("status", "")
        is_stub = status == "ok_stub"
        checks["llm_path"] = {
            "passed": not is_stub,
            "detail": (
                "Silent stub fallback — real LLM NOT used"
                if is_stub
                else "Real LLM path confirmed"
            ),
        }

    return {
        "case": case,
        "result": raw_result,
        "checks": checks,
        "elapsed_ms": round(elapsed_ms, 1),
        "error": error,
    }


# ── Report generation ────────────────────────────────────

def generate_reports(
    results: List[Dict],
    stub: bool,
) -> tuple:
    """Generate .md and .json reports. Returns (md_path, json_path)."""
    today = datetime.date.today().strftime("%Y%m%d")
    output_dir = os.path.join(
        os.path.dirname(__file__), "..", "output",
    )
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.abspath(
        os.path.join(output_dir, f"audit_report_{today}.md")
    )
    json_path = os.path.abspath(
        os.path.join(output_dir, f"audit_report_{today}.json")
    )

    # Compute summary stats
    total = len(results)
    all_pass = sum(
        1 for r in results
        if all(c["passed"] for c in r["checks"].values())
    )
    # Gather check names from first result (includes conditional llm_path)
    check_names = list(results[0]["checks"].keys()) if results else [n for n, _ in CHECKS]
    per_check = {}
    for ck_name in check_names:
        per_check[ck_name] = sum(
            1 for r in results if r["checks"][ck_name]["passed"]
        )

    # ── .md report ──
    md_lines = [
        f"# Quality Audit Report — {today}",
        "",
        f"**Mode:** {'STUB (no LLM cost)' if stub else 'REAL (live DeepTutor)'}",
        f"**Timestamp:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total cases:** {total}",
        f"**All checks passed:** {all_pass}/{total}",
        "",
        "## Per-Check Pass Rate",
        "",
        "| Check | Passed | Rate |",
        "|-------|--------|------|",
    ]
    for ck_name, cnt in per_check.items():
        rate = f"{cnt/total*100:.0f}%"
        md_lines.append(f"| {ck_name} | {cnt}/{total} | {rate} |")

    md_lines.extend([
        "",
        "## Case-by-Case Results",
        "",
    ])

    for r in results:
        c = r["case"]
        pass_count = sum(1 for v in r["checks"].values() if v["passed"])
        fail_count = len(r["checks"]) - pass_count
        status_icon = "✅" if fail_count == 0 else "❌"

        md_lines.append(f"### Case {c['n']} — {status_icon} {pass_count}/{len(r['checks'])} checks passed")
        md_lines.append(f"**Query:** {c['query']}")
        md_lines.append(
            f"**Expected:** {c['expected_mode']} | "
            f"{c['lang']} | {c['age_band']} "
            f"{'| topic=' + c['topic_id'] if c.get('topic_id') else ''}"
        )
        actual = r["result"]
        md_lines.append(
            f"**Actual:** `{actual.get('mode','?')}` | "
            f"`{actual.get('lang_code','?')}` | "
            f"`{actual.get('age_band','?')}` | "
            f"label=`{actual.get('kid_label','?')}` | "
            f"{r['elapsed_ms']:.0f}ms"
        )
        if r.get("error"):
            md_lines.append(f"**Error:** {r['error']}")

        md_lines.append("")
        md_lines.append("| Check | Pass | Detail |")
        md_lines.append("|-------|------|--------|")
        for ck_name, ck in r["checks"].items():
            icon = "✅" if ck["passed"] else "❌"
            md_lines.append(f"| {ck_name} | {icon} | {ck['detail']} |")
        md_lines.append("")

        # Show response excerpt (first 200 chars)
        content = actual.get("content", "")
        excerpt = content[:200] + ("…" if len(content) > 200 else "")
        md_lines.append(f"**Response excerpt:** _{excerpt}_")
        md_lines.append("")

    # ── Save .md ──
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md_lines))

    # ── .json report ──
    json_data = {
        "date": today,
        "stub": stub,
        "timestamp": datetime.datetime.now().isoformat(),
        "total_cases": total,
        "all_pass": all_pass,
        "checks_summary": {k: {"passed": v, "rate": f"{v/total*100:.0f}%"}
                            for k, v in per_check.items()},
        "cases": [],
    }
    for r in results:
        entry = {
            "n": r["case"]["n"],
            "query": r["case"]["query"],
            "expected_mode": r["case"]["expected_mode"],
            "expected_lang": r["case"]["lang"],
            "expected_age_band": r["case"]["age_band"],
            "topic_id": r["case"].get("topic_id"),
            "elapsed_ms": r["elapsed_ms"],
            "error": r.get("error"),
            "result": r["result"],
            "checks": r["checks"],
        }
        json_data["cases"].append(entry)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(json_data, fh, indent=2, ensure_ascii=False, default=str)

    return md_path, json_path


# ── Stub patching ────────────────────────────────────────

def _apply_stubs():
    """Apply monkeypatches so execute() runs without real LLM/WS.
    Same mechanism as test_execute.py."""
    from unittest.mock import AsyncMock, patch

    # Patch AssessmentAgent.quiz_gen → stub
    async_stub_quiz = AsyncMock(return_value=dict(STUB_QUIZ_RESPONSE))

    # Patch DeepTutorWSClient.query → raise → forces stub error fallback
    async def _ws_fail(*args, **kwargs):
        raise ConnectionError("Connection refused (stub audit)")

    patches = [
        patch(
            "agents.assessment_agent.AssessmentAgent.quiz_gen",
            new=async_stub_quiz,
        ),
        patch(
            "agents.deeptutor_ws.DeepTutorWSClient.query",
            new=_ws_fail,
        ),
    ]
    for p in patches:
        p.start()
    return patches


# ── Main ─────────────────────────────────────────────────

async def main_async(stub: bool = False, start: int = 1, end: int = 12) -> None:
    range_desc = "" if (start == 1 and end == 12) else f" cases {start}-{end}"
    print(f"Quality Audit {'(STUB)' if stub else '(REAL)'}{range_desc} — starting...")
    start_total = time.perf_counter()

    patches = []
    if stub:
        patches = _apply_stubs()

    registry = _default_registry()
    results: List[Dict] = []

    # Filter cases by range (1-based inclusive)
    active_cases = [c for c in CASES if start <= c["n"] <= end]

    try:
        for case in active_cases:
            cid = f"{case['n']:02d}/12"
            print(
                f"  [{cid}] {case['expected_mode']:>10} | "
                f"{case['lang']:>5} | {case['age_band']:>5} | "
                f"{case['query'][:40]}…"
            )
            row = await run_case(case, registry, stub=stub)
            results.append(row)

            # Quick per-case summary
            passes = sum(1 for v in row["checks"].values() if v["passed"])
            fails = len(row["checks"]) - passes
            if fails > 0:
                failed_checks = [
                    k for k, v in row["checks"].items() if not v["passed"]
                ]
                print(f"       {passes}/{len(row['checks'])} passed — FAIL: {', '.join(failed_checks)}")
    finally:
        for p in patches:
            p.stop()

    total_elapsed = (time.perf_counter() - start_total) * 1000
    md_path, json_path = generate_reports(results, stub)

    # ── Final summary ──
    all_pass = sum(
        1 for r in results
        if all(c["passed"] for c in r["checks"].values())
    )
    print(f"\nDone in {total_elapsed/1000:.1f}s — {all_pass}/{len(results)} cases all-green")
    print(f"Report (.md):  {md_path}")
    print(f"Report (.json): {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Phase 5 Day 23 Quality Audit")
    parser.add_argument(
        "--stub", action="store_true",
        help="Run with stub responses (no LLM cost, validates audit logic)",
    )
    parser.add_argument(
        "--start", type=int, default=1,
        help="First case number to run (1-based, inclusive)",
    )
    parser.add_argument(
        "--end", type=int, default=12,
        help="Last case number to run (1-based, inclusive)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(stub=args.stub, start=args.start, end=args.end))


if __name__ == "__main__":
    main()
