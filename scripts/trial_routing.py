"""
Dreamer AI Phase 5 — trial_routing.py
Trigger all obs_events types and verify GROUP BY distribution.

Usage: python scripts/trial_routing.py

Prerequisites: dreamer.db accessible (no container needed — uses mocks)
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import json
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, patch
from agents.hermes_scheduler import (
    execute,
    PlanContext,
    HermesScheduler,
    _direct_clarifying_response,
)


async def run_trials():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = os.path.join(repo_root, "dreamer.db")

    # ── Fixture: ensure tables exist ──
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS obs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT '',
            lang_code TEXT NOT NULL DEFAULT '',
            age_band TEXT NOT NULL DEFAULT '',
            agent_list TEXT NOT NULL DEFAULT '[]',
            topic_ids TEXT NOT NULL DEFAULT '[]',
            raw_input TEXT NOT NULL DEFAULT '',
            response_type TEXT NOT NULL DEFAULT '',
            cost_summary TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

    # ── Clean slate ──
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM obs_events")
    conn.execute("DELETE FROM session_logs")
    conn.commit()
    conn.close()

    fake_assessment = {"type": "quiz", "content": "mock assessment", "sources": []}

    # ── Trial 1-4: DIRECT routing + cost (4x) ──
    plan_direct = PlanContext(
        mode="DIRECT", lang_code="zh-hk", age_band="S1-S3",
        agent_list=["assessment"], kb_list=["ethical-ai"],
        prereq_gaps=[], matched_keyword="測驗",
    )
    with patch("agents.hermes_scheduler.build_plan", return_value=plan_direct):
        with patch(
            "agents.hermes_scheduler.HermesScheduler.kid_safe_input", return_value=None
        ):
            with patch("agents.hermes_scheduler._call_assessment", return_value=fake_assessment):
                for i in range(4):
                    await execute(
                        f"我想溫書準備測驗 #{i}",
                        f"std_dir_{i}",
                        "S1-S3",
                        session_id=f"ses_dir_{i}",
                        topic_id="math_p1",
                    )

    # ── Trial 5-6: CONTEXTUAL → WS event ──
    plan_ctx = PlanContext(
        mode="CONTEXTUAL", lang_code="zh-hk", age_band="S1-S3",
        agent_list=["deeptutor"], kb_list=["ethical-ai"],
        prereq_gaps=[], matched_keyword=None,
    )
    fake_ws_result = {"reply": "hello from ws", "sources": []}
    with patch("agents.hermes_scheduler.build_plan", return_value=plan_ctx):
        with patch(
            "agents.hermes_scheduler.HermesScheduler.kid_safe_input", return_value=None
        ):
            with patch(
                "agents.hermes_scheduler._run_contextual",
                new=AsyncMock(return_value=fake_ws_result),
            ):
                for i in range(2):
                    await execute(
                        f"hello good morning #{i}",
                        f"std_ws_{i}",
                        "S1-S3",
                        session_id=f"ses_ws_{i}",
                    )

    # ── Trial 7: DIRECT clarifying (empty agent_list → clarifying path) ──
    plan_clarify = PlanContext(
        mode="DIRECT", lang_code="zh-hk", age_band="S1-S3",
        agent_list=[], kb_list=["ethical-ai"],
        prereq_gaps=[], matched_keyword=None,
    )
    with patch("agents.hermes_scheduler.build_plan", return_value=plan_clarify):
        with patch(
            "agents.hermes_scheduler.HermesScheduler.kid_safe_input", return_value=None
        ):
            await execute(
                "我想問下點樣學好數學",
                "std_clarify",
                "S1-S3",
                session_id="ses_clarify",
            )

    # ── Trial 8: safety event ──
    plan_safety = PlanContext(
        mode="DIRECT", lang_code="zh-hk", age_band="S1-S3",
        agent_list=["assessment"], kb_list=["ethical-ai"],
        prereq_gaps=[], matched_keyword="福利",
    )
    mock_block = {
        "response_message": "安全護欄攔截",
        "event": {"id": "safety_ev_001", "event_type": "welfare_block"},
    }
    with patch("agents.hermes_scheduler.build_plan", return_value=plan_safety):
        with patch(
            "agents.hermes_scheduler.HermesScheduler.kid_safe_input",
            return_value=mock_block,
        ):
            await execute(
                "我要領錢",
                "std_safety",
                "S1-S3",
                session_id="ses_safety",
            )

    # ── Print results ──
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT event_type, event_data FROM obs_events ORDER BY id"
    ).fetchall()

    print("=== ALL obs_events rows ===")
    for et, ed in rows:
        data = json.loads(ed)
        print(f"  {et}: {json.dumps(data, ensure_ascii=False)}")

    print("\n=== GROUP BY distribution ===")
    dist = conn.execute(
        "SELECT event_type, COUNT(*) as cnt FROM obs_events "
        "GROUP BY event_type ORDER BY cnt DESC"
    ).fetchall()
    for et, cnt in dist:
        print(f"  {et}: {cnt}")

    event_types = {et for et, _ in rows}
    expected = {"routing", "cost", "ws", "clarifying", "safety"}
    missing = expected - event_types
    if missing:
        print(f"\n⚠️  MISSING event types: {missing}")
    else:
        print(f"\n✅ All 5 expected event types present (routing/cost/ws/clarifying/safety)")

    conn.close()


if __name__ == "__main__":
    asyncio.run(run_trials())
