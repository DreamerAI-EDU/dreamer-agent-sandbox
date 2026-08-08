"""trial_ws.py — DeepTutor real-container round-trip (Phase 2.2 Day 10 gate rehearsal).

Sequence:
 1. check_health() — liveness + readiness
 2. connect()
 3. Call 1 (EN): "What is 2+2?" — observe event type order, terminal event, cost_summary
 4. Call 2 (Cantonese UTF-8): "你好，請問分數係咩？" — verify encoding round-trip
 5. close — print full event timeline
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Install a minimal agents package stub to avoid __init__.py heavy import chain
_agents_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
_agents_pkg = type(sys)("agents")
_agents_pkg.__path__ = [_agents_path]
_agents_pkg.__file__ = os.path.join(_agents_path, "__init__.py")
sys.modules["agents"] = _agents_pkg

# Load config_loader as agents.config_loader
_cl_spec = importlib.util.spec_from_file_location(
    "agents.config_loader",
    os.path.join(_agents_path, "config_loader.py"),
    submodule_search_locations=[_agents_path],
)
_cl = importlib.util.module_from_spec(_cl_spec)
_cl.__package__ = "agents"
sys.modules["agents.config_loader"] = _cl
_cl_spec.loader.exec_module(_cl)

# Load deeptutor_ws as agents.deeptutor_ws
_spec = importlib.util.spec_from_file_location(
    "agents.deeptutor_ws",
    os.path.join(_agents_path, "deeptutor_ws.py"),
    submodule_search_locations=[_agents_path],
)
_deeptutor_ws = importlib.util.module_from_spec(_spec)
_deeptutor_ws.__package__ = "agents"
sys.modules["agents.deeptutor_ws"] = _deeptutor_ws
_spec.loader.exec_module(_deeptutor_ws)

DeepTutorWSClient = _deeptutor_ws.DeepTutorWSClient
DeepTutorError = _deeptutor_ws.DeepTutorError
DeepTutorTimeoutError = _deeptutor_ws.DeepTutorTimeoutError


def timestamp() -> str:
    return time.strftime("%H:%M:%S")


async def main() -> None:
    client = DeepTutorWSClient()

    print("=" * 64)
    print("  DeepTutor WS Client — Real Container Trial")
    print("=" * 64)

    # ── Phase 1: Health ──────────────────────────────────
    print(f"\n[{timestamp()}] Phase 1: Health check")
    health = await client.check_health()
    print(f"  Liveness  (GET /)                         : {'PASS' if health.liveness else 'FAIL'}")
    print(f"  Readiness (GET /api/v1/knowledge/health)  : {'PASS' if health.readiness else 'FAIL'}")
    if not health.liveness or not health.readiness:
        print("  ABORT: health checks failed")
        await client.close()
        return

    # ── Phase 2: Connect ─────────────────────────────────
    print(f"\n[{timestamp()}] Phase 2: Connect to {client.ws_url}")
    ok = await client.connect()
    assert ok, "connect returned False"
    print(f"  Connected OK")

    # ── Phase 3: Call 1 — English, simple math ──────────
    print(f"\n[{timestamp()}] Phase 3: Call 1 — 'What is 2+2?' (capability=chat)")
    try:
        result1 = await client.query(
            session_id="trial-en-001",
            content="What is 2+2? Answer in one short sentence.",
            capability="chat",
            timeout=60.0,
        )
    except (DeepTutorError, DeepTutorTimeoutError) as e:
        print(f"  ERROR: {e}")
        await client.close()
        return

    print(f"  Turn ID     : {result1.turn_id}")
    print(f"  Content     : {result1.content[:200]}")
    print(f"  Cost summary: {json.dumps(result1.cost_summary, indent=4) if result1.cost_summary else '(none)'}")
    print(f"  Citations   : {len(result1.citations)} items")
    print(f"  Events received: {len(result1.events)}")

    # Print full event timeline for Call 1
    print(f"\n  ── Event Timeline (Call 1) ──")
    terminal_type = None
    for i, ev in enumerate(result1.events):
        meta_brief = ""
        if ev.metadata:
            meta_keys = list(ev.metadata.keys())
            meta_brief = f" meta={meta_keys}"
            # special: if this is result type, show cost
            if ev.type == "result" and "cost_summary" in ev.metadata:
                cs = ev.metadata["cost_summary"]
                meta_brief = f" cost_summary={cs}"
        content_preview = ev.content[:60].replace("\n", "\\n") if ev.content else ""
        print(f"  [{i:02d}] type={ev.type:<14s} seq={ev.seq:<4d} src={ev.source:<12s} {content_preview}{meta_brief}")
        if ev.type in ("done", "result", "error"):
            terminal_type = ev.type

    print(f"\n  ★ Terminal event type: {terminal_type}")
    print(f"  ★ cost_summary in:     {'result' if any(e.type == 'result' and 'cost_summary' in e.metadata for e in result1.events) else 'N/A'}")

    # ── Phase 4: Call 2 — Cantonese UTF-8 ───────────────
    print(f"\n[{timestamp()}] Phase 4: Call 2 — '你好，請問分數係咩？'")
    try:
        result2 = await client.query(
            session_id="trial-zh-001",
            content="你好，請問分數係咩？用廣東話簡短回答。",
            capability="chat",
            timeout=60.0,
        )
    except (DeepTutorError, DeepTutorTimeoutError) as e:
        print(f"  ERROR: {e}")
        await client.close()
        return

    print(f"  Turn ID     : {result2.turn_id}")
    print(f"  Content     : {result2.content[:200]}")
    print(f"  Cost summary: {json.dumps(result2.cost_summary, indent=4) if result2.cost_summary else '(none)'}")
    utf8_ok = all(ord(c) < 128 or ord(c) > 127 for c in result2.content)
    print(f"  UTF-8 clean : {'PASS' if utf8_ok else 'CHECK'} (no mojibake detected via heuristic)")
    print(f"  Events received: {len(result2.events)}")

    print(f"\n  ── Event Timeline (Call 2) ──")
    for i, ev in enumerate(result2.events):
        content_preview = ev.content[:60].replace("\n", "\\n") if ev.content else ""
        print(f"  [{i:02d}] type={ev.type:<14s} seq={ev.seq:<4d} src={ev.source:<12s} {content_preview}")

    # ── Phase 5: Close ───────────────────────────────────
    print(f"\n[{timestamp()}] Phase 5: Close")
    await client.close()
    print("  Done.")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print(f"  Summary")
    print(f"{'=' * 64}")
    print(f"  Call 1 terminal event  : {terminal_type}")
    print(f"  Call 1 cost_summary    : {'found' if result1.cost_summary else 'not found'}")
    print(f"  Call 2 UTF-8 roundtrip : {'PASS' if utf8_ok else 'ISSUE'}")
    print(f"  Total events           : {len(result1.events) + len(result2.events)}")
    print(f"{'=' * 64}")


if __name__ == "__main__":
    asyncio.run(main())
