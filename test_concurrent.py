"""test_concurrent.py — 10 concurrent WS sessions against real DeepTutor container.

Gate item #3 (10 concurrent) + #4 (pool observable via logs).
Each session sends one short message and collects latency + cost.
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

# ── importlib bootleg (avoid agents/__init__ heavy dep chain) ──
import importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_agents_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
_agents_pkg = type(sys)("agents")
_agents_pkg.__path__ = [_agents_path]
sys.modules["agents"] = _agents_pkg

for mod, fname in [
    ("agents.config_loader", "config_loader.py"),
    ("agents.deeptutor_ws", "deeptutor_ws.py"),
]:
    spec = importlib.util.spec_from_file_location(
        mod, os.path.join(_agents_path, fname), submodule_search_locations=[_agents_path]
    )
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "agents"
    sys.modules[mod] = m
    spec.loader.exec_module(m)

DeepTutorWSClient = sys.modules["agents.deeptutor_ws"].DeepTutorWSClient

WS_URL = "ws://127.0.0.1:8001/api/v1/ws"
BASE_URL = "http://127.0.0.1:8001"

# ── pool monitoring ─────────────────────────────────────────────
pool_active = 0
pool_queue: list = []


@dataclass
class SessionResult:
    idx: int
    turn_id: str
    content: str
    latency_s: float
    cost_usd: float
    tokens: int
    error: str = ""


async def session_worker(idx: int, message: str) -> SessionResult:
    """One session: connect → query → close. Logs pool metrics."""
    global pool_active, pool_queue
    t0 = time.monotonic()

    # ── enter pool ──
    pool_queue.append(idx)
    pool_active += 1
    pool_queue.pop(0)
    print(f"[pool] session #{idx} entering — active={pool_active}, queued={len(pool_queue)}")

    client = DeepTutorWSClient(ws_url=WS_URL)
    client.liveness_url = f"{BASE_URL}/"
    client.readiness_url = f"{BASE_URL}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query(f"s-conc-{idx}", message, timeout=20)

        latency = time.monotonic() - t0
        cost = result.cost_summary.get("total_cost_usd", 0) if result.cost_summary else 0
        tokens = result.cost_summary.get("total_tokens", 0) if result.cost_summary else 0

        print(f"[pool] session #{idx} done — latency={latency:.2f}s, cost=${cost:.6f}, tokens={tokens}")

        return SessionResult(
            idx=idx,
            turn_id=result.turn_id or "",
            content=result.content[:120],
            latency_s=latency,
            cost_usd=cost,
            tokens=tokens,
        )
    except Exception as e:
        latency = time.monotonic() - t0
        print(f"[pool] session #{idx} FAILED — latency={latency:.2f}s, error={e}")
        return SessionResult(idx=idx, turn_id="", content="", latency_s=latency, cost_usd=0, tokens=0, error=str(e))
    finally:
        await client.close()
        pool_active -= 1
        print(f"[pool] session #{idx} leaving — active={pool_active}, queued={len(pool_queue)}")


async def main():
    CONCURRENT = 10
    MESSAGE = "What is 2+2?"

    print(f"=== DeepTutor Concurrent Stress Test ===")
    print(f"  sessions: {CONCURRENT}")
    print(f"  message:  {MESSAGE!r}")
    print(f"  endpoint: {WS_URL}")
    print()

    t_start = time.monotonic()

    tasks = [session_worker(i, MESSAGE) for i in range(1, CONCURRENT + 1)]
    results: list[SessionResult] = list(await asyncio.gather(*tasks))

    wall_time = time.monotonic() - t_start
    errors = [r for r in results if r.error]
    ok = [r for r in results if not r.error]

    # ── report ──────────────────────────────────────────────────
    print()
    print(f"{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Total wall time:       {wall_time:.2f}s")
    print(f"  Sessions succeeded:    {len(ok)}/{CONCURRENT}")
    print(f"  Sessions failed:       {len(errors)}/{CONCURRENT}")
    print()

    if ok:
        latencies = [r.latency_s for r in ok]
        costs = [r.cost_usd for r in ok]
        tokens_list = [r.tokens for r in ok]

        print(f"  Latency (s): min={min(latencies):.2f}  max={max(latencies):.2f}  avg={sum(latencies)/len(latencies):.2f}")
        print(f"  Cost ($):    min=${min(costs):.6f}  max=${max(costs):.6f}  total=${sum(costs):.6f}")
        print(f"  Tokens:      min={min(tokens_list)}  max={max(tokens_list)}  total={sum(tokens_list)}")
        print()

        print(f"  Per-session detail:")
        print(f"  {'#':>3}  {'latency':>8}  {'cost':>12}  {'tokens':>8}  {'turn_id'}")
        for r in sorted(ok, key=lambda x: x.idx):
            print(f"  {r.idx:>3}  {r.latency_s:>7.2f}s  ${r.cost_usd:>10.6f}  {r.tokens:>8}  {r.turn_id}")

    if errors:
        print()
        print(f"  FAILURES:")
        for r in errors:
            print(f"  #{r.idx}: {r.error}")

    print()
    if len(ok) == CONCURRENT:
        print("  ✅ GATE: 10/10 concurrent sessions passed")
    else:
        print(f"  ❌ GATE: {len(errors)} failures")

    print(f"{'='*60}")

    return 0 if len(ok) == CONCURRENT else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
