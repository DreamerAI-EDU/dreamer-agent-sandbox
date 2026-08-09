"""
trial_routing.py — Phase 4 Day 21: execute() end-to-end trial.

Four cases using real container + real LLM (DeepTutor running required).

Case 1: computing-game-design-01 + exam query  → DIRECT + quiz + kb filter
Case 2: "我想整個遊戲" + topic                 → CONTEXTUAL + WS + kid_safe_wrap
Case 3: "用AI幫我溫書"                        → HYBRID + agent_list has curriculum+assessment
Case 4: "project mode, I want to revise for exam" → CONTEXTUAL (override wins)

Pre-req: DeepTutor container running on localhost:8001.
Fallback: container unreachable → stub mode (outputs ok_stub / ws_error).
"""

import asyncio
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.hermes_scheduler import execute, _ensure_session_logs_table
from agents.registry import SubagentRegistry
from agents.subagents import register_all


# ── Fixture: registry ──────────────────────────────────

_registry = None


def get_registry():
    global _registry
    if _registry is None:
        _registry = SubagentRegistry()
        register_all(_registry)
    return _registry


# ── Helpers ────────────────────────────────────────────

def check_session_logs(session_id: str) -> dict | None:
    """Return session_logs row for given session_id."""
    db_path = os.environ.get(
        "DREAMER_DB_PATH",
        os.path.join(os.path.dirname(__file__), "dreamer.db"),
    )
    db_path = os.path.abspath(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM session_logs WHERE session_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchall()
        return dict(rows[0]) if rows else None
    finally:
        conn.close()


def print_result(label: str, result: dict, session_id: str):
    """Pretty-print a trial case result."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(f"  mode:       {result.get('mode')}")
    print(f"  lang_code:  {result.get('lang_code')}")
    print(f"  age_band:   {result.get('age_band')}")
    print(f"  kid_label:  {result.get('kid_label')}")

    content = result.get("content", "")
    if len(content) > 200:
        content = content[:200] + "..."
    print(f"  content:    {content}")

    citations = result.get("citations", [])
    print(f"  citations:  {len(citations)} items")

    cost = result.get("cost_summary", {})
    print(f"  cost:       {json.dumps(cost, ensure_ascii=False, default=str)}")

    # Session log check
    log = check_session_logs(session_id)
    if log:
        print(f"  session_log: mode={log['mode']}, "
              f"agents={log['agent_list']}, "
              f"topics={log['topic_ids']}")


# ── Case runners ────────────────────────────────────────

async def run_case_1():
    """Case 1: DIRECT + quiz_gen + kb_list filtered.

    Topic: computing-game-design-01
    Query: 「我要考試溫習整遊戲嘅課題」
    Expected: DIRECT mode, quiz_gen questions, kb_list excludes
              dreamer-psd / dreamer-life_skills.
    """
    session_id = f"trial_c1_{int(time.time())}"
    reg = get_registry()

    result = await execute(
        "我要做練習題準備測驗",
        student_id="trial_stu_c1",
        age_band="P4-P6",
        topic_id="computing-game-design-01",
        registry=reg,
        session_id=session_id,
    )
    print_result("Case 1 — DIRECT + quiz_gen + kb filter", result, session_id)

    # Verify kb_list filter via PlanContext
    from agents.hermes_scheduler import build_plan
    plan = build_plan(
        "我要做練習題準備測驗", "trial_stu_c1", "P4-P6",
        topic_id="computing-game-design-01",
        registry=reg,
    )
    assert plan.mode == "DIRECT", f"Expected DIRECT, got {plan.mode}"
    # kb_list filter only applies in DIRECT mode
    assert "dreamer-psd" not in plan.kb_list, (
        f"dreamer-psd should be filtered from kb_list, got: {plan.kb_list}"
    )
    assert "dreamer-life_skills" not in plan.kb_list, (
        f"dreamer-life_skills should be filtered from kb_list, got: {plan.kb_list}"
    )
    print(f"  ✓ kb_list verified: {plan.kb_list}")

    return result


async def run_case_2():
    """Case 2: CONTEXTUAL + WS DeepTutor + kid_safe_wrap.

    Topic: computing-game-design-01
    Query: 「我想整個遊戲」
    Expected: CONTEXTUAL mode, WS chat response, kid_safe_wrap applied.
    """
    session_id = f"trial_c2_{int(time.time())}"
    reg = get_registry()

    result = await execute(
        "我想整個遊戲",
        student_id="trial_stu_c2",
        age_band="S1-S3",
        topic_id="computing-game-design-01",
        registry=reg,
        session_id=session_id,
    )
    print_result("Case 2 — CONTEXTUAL + WS + kid_safe_wrap", result, session_id)

    from agents.hermes_scheduler import build_plan
    plan = build_plan(
        "我想整個遊戲", "trial_stu_c2", "S1-S3",
        topic_id="computing-game-design-01",
        registry=reg,
    )
    assert plan.mode == "CONTEXTUAL", f"Expected CONTEXTUAL, got {plan.mode}"
    print(f"  ✓ mode verified: {plan.mode}")

    return result


async def run_case_3():
    """Case 3: HYBRID + agent_list has curriculum + assessment.

    Query: 「用AI幫我溫書」
    Expected: HYBRID mode, agent_list includes curriculum + assessment.
    """
    session_id = f"trial_c3_{int(time.time())}"
    reg = get_registry()

    result = await execute(
        "用AI幫我溫書",
        student_id="trial_stu_c3",
        age_band="P4-P6",
        topic_id="computing-game-design-01",
        registry=reg,
        session_id=session_id,
    )
    print_result("Case 3 — HYBRID + agent_list", result, session_id)

    from agents.hermes_scheduler import build_plan
    plan = build_plan(
        "用AI幫我溫書", "trial_stu_c3", "P4-P6",
        topic_id="computing-game-design-01",
        registry=reg,
    )
    assert plan.mode == "HYBRID", f"Expected HYBRID, got {plan.mode}"
    assert "curriculum" in plan.agent_list, (
        f"curriculum should be in agent_list, got: {plan.agent_list}"
    )
    assert "assessment" in plan.agent_list, (
        f"assessment should be in agent_list, got: {plan.agent_list}"
    )
    print(f"  ✓ mode={plan.mode}, agents={plan.agent_list}")

    return result


async def run_case_4():
    """Case 4: "project mode" override → CONTEXTUAL.

    Query: "project mode, I want to revise for exam"
    Expected: CONTEXTUAL (override keyword wins over exam keyword).
    """
    session_id = f"trial_c4_{int(time.time())}"
    reg = get_registry()

    result = await execute(
        "project mode, I want to revise for exam",
        student_id="trial_stu_c4",
        age_band="S1-S3",
        registry=reg,
        session_id=session_id,
    )
    print_result("Case 4 — CONTEXTUAL override", result, session_id)

    from agents.hermes_scheduler import build_plan
    plan = build_plan(
        "project mode, I want to revise for exam", "trial_stu_c4", "S1-S3",
        registry=reg,
    )
    assert plan.mode == "CONTEXTUAL", (
        f"Expected CONTEXTUAL (override), got {plan.mode}"
    )
    print(f"  ✓ override mode={plan.mode}, lang={plan.lang_code}")

    return result


# ── Main ────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("Phase 4 Day 21 — Trial Routing (4 cases)")
    print("=" * 60)

    results = {}

    # Case 1
    try:
        results["c1"] = await run_case_1()
    except Exception as e:
        print(f"\n  Case 1 FAILED: {e}")

    # Case 2
    try:
        results["c2"] = await run_case_2()
    except Exception as e:
        print(f"\n  Case 2 FAILED: {e}")

    # Case 3
    try:
        results["c3"] = await run_case_3()
    except Exception as e:
        print(f"\n  Case 3 FAILED: {e}")

    # Case 4
    try:
        results["c4"] = await run_case_4()
    except Exception as e:
        print(f"\n  Case 4 FAILED: {e}")

    # Summary
    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}")
    for case, r in results.items():
        mode = r.get("mode", "?")
        kid = r.get("kid_label", "?")
        cost = r.get("cost_summary", {})
        cost_short = {k: v for k, v in cost.items()
                      if k in ("agent", "status", "elapsed_ms", "ws_fallback", "questions_count")}
        print(f"  {case}: mode={mode}, kid_label={kid}, cost={cost_short}")


if __name__ == "__main__":
    asyncio.run(main())
