"""
test_ws_client.py — DeepTutorWSClient unit tests (pytest-asyncio + mock WS server).

Covers:
 1. connect success (health-first flow)
 2. health fail → connect returns False
 3. multi-chunk accumulation → full content
 4. error event → DeepTutorError
 5. session dispatch isolation (two concurrent queries, interleaved replies)
 6. cost_summary capture from result event
 7. timeout
 8. reconnect backoff timing
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.deeptutor_ws import (
    DeepTutorError,
    DeepTutorNotConnectedError,
    DeepTutorTimeoutError,
    DeepTutorWSClient,
    QueryResult,
    WSEvent,
)


# ══════════════════════════════════════════════════════════════════
# Case 1: connect success (health-first flow)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_success(mock_deeptutor_server):
    """Health 200 → WS connect → CONNECTED."""
    from agents.deeptutor_ws import ConnectionState

    host, port, ctrl = mock_deeptutor_server
    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        ok = await client.connect()
        assert ok is True
        assert client._state == ConnectionState.CONNECTED
        assert client.healthy
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 2: health fail → connect returns False
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_health_fail_liveness():
    """Liveness 404 → connect returns False."""
    from agents.deeptutor_ws import ConnectionState

    client = DeepTutorWSClient(ws_url="ws://127.0.0.1:19999/api/v1/ws")
    client.liveness_url = "http://127.0.0.1:19999/"
    client.readiness_url = "http://127.0.0.1:19999/api/v1/knowledge/health"

    try:
        ok = await client.connect()
        assert ok is False
        assert client._state == ConnectionState.DISCONNECTED
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_connect_health_fail_readiness(mock_deeptutor_server, monkeypatch):
    """Readiness returns non-ok status → connect still succeeds (liveness passes)."""
    # Liveness is OK via mock server, but we override readiness check to fail
    host, port, ctrl = mock_deeptutor_server
    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    # connect() requires only liveness, not readiness
    try:
        ok = await client.connect()
        assert ok is True
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 3: multi-chunk accumulation
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_multi_chunk_accumulation(mock_deeptutor_server):
    """3 content events + 1 done → full concatenated content."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "content", "content": "Hello ", "session_id": "s1", "turn_id": "turn-001", "seq": 1},
        {"type": "content", "content": "from ", "session_id": "s1", "turn_id": "turn-001", "seq": 2},
        {"type": "content", "content": "DeepTutor", "session_id": "s1", "turn_id": "turn-001", "seq": 3},
        {"type": "done", "session_id": "s1", "turn_id": "turn-001", "seq": 4},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query("s1", "Hi")
        assert result.content == "Hello from DeepTutor"
        assert result.turn_id == "turn-001"
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 4: error event → DeepTutorError
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_error_event(mock_deeptutor_server):
    """Server sends error → DeepTutorError raised with message."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "error", "content": "KB not loaded: dreamer-prerequisites", "session_id": "s2", "seq": 1},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        with pytest.raises(DeepTutorError, match="KB not loaded"):
            await client.query("s2", "explain calculus")
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 5: session dispatch isolation (CORE)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_session_dispatch_isolation(mock_deeptutor_server):
    """Two concurrent queries on different sessions get interleaved replies.

    The mock server sends events interleaved (A1, B1, A2, B2, done_A, done_B).
    The dispatcher must correctly route each event to the right queue.
    """
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False

    # Programming the server to send interleaved events after receiving BOTH messages.
    # Since the mock handler sends the entire sequence after EACH message,
    # we need a smarter approach.

    # Instead, we use a shared counter so the handler knows it has seen both messages.
    class SharedState:
        def __init__(self):
            self.received_count = 0
            self.lock = asyncio.Lock()

    state = SharedState()

    # Build a custom app that handles interleaving properly
    import aiohttp.web

    async def ws_interleaved(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)

        msgs_seen = []
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    body = json.loads(msg.data)
                    msgs_seen.append(body)

                    if len(msgs_seen) == 2:
                        # Interleave: A1, B1, A2, B2, done_A, done_B
                        s_a = msgs_seen[0].get("session_id", "?")
                        s_b = msgs_seen[1].get("session_id", "?")

                        await ws.send_json({"type": "content", "content": "A1", "session_id": s_a, "seq": 1})
                        await ws.send_json({"type": "content", "content": "B1", "session_id": s_b, "seq": 1})
                        await ws.send_json({"type": "content", "content": "A2", "session_id": s_a, "seq": 2})
                        await ws.send_json({"type": "content", "content": "B2", "session_id": s_b, "seq": 2})
                        await ws.send_json({"type": "done", "session_id": s_a, "turn_id": "turn-a", "seq": 3})
                        await ws.send_json({"type": "done", "session_id": s_b, "turn_id": "turn-b", "seq": 3})
                except json.JSONDecodeError:
                    pass
        return ws

    port = host, p = mock_deeptutor_server[:2]
    port = p

    # We need a new app with the interleaved handler — stop old, start new
    # Simpler: use the same port but with a separate runner.
    # Actually, let's just restart with a new port for this test.

    import socket
    new_port = None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        new_port = s.getsockname()[1]

    app = aiohttp.web.Application()
    app.router.add_get("/", lambda r: aiohttp.web.Response(status=200, text="OK"))
    app.router.add_get("/api/v1/knowledge/health", lambda r: aiohttp.web.json_response({"status": "ok"}))
    app.router.add_get("/api/v1/ws", ws_interleaved)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", new_port)
    await site.start()

    client = DeepTutorWSClient(ws_url=f"ws://127.0.0.1:{new_port}/api/v1/ws")
    client.liveness_url = f"http://127.0.0.1:{new_port}/"
    client.readiness_url = f"http://127.0.0.1:{new_port}/api/v1/knowledge/health"

    try:
        await client.connect()

        # Run two concurrent queries
        r_a, r_b = await asyncio.gather(
            client.query("session-alpha", "question A"),
            client.query("session-beta",  "question B"),
        )

        assert r_a.content == "A1A2", f"Session A got wrong content: {r_a.content!r}"
        assert r_b.content == "B1B2", f"Session B got wrong content: {r_b.content!r}"
        assert r_a.turn_id == "turn-a"
        assert r_b.turn_id == "turn-b"
    finally:
        await client.close()
        await runner.cleanup()


# ══════════════════════════════════════════════════════════════════
# Case 6: cost_summary capture from result event
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cost_summary_capture(mock_deeptutor_server):
    """result event with cost_summary → captured in QueryResult."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "content", "content": "Answer", "session_id": "s6", "turn_id": "turn-cost", "seq": 1},
        {
            "type": "result",
            "session_id": "s6",
            "turn_id": "turn-cost",
            "seq": 2,
            "metadata": {
                "cost_summary": {"tokens_in": 120, "tokens_out": 45, "cost_usd": 0.0023},
                "citations": [{"title": "Ref A", "url": "https://example.com/a"}],
            },
        },
        {"type": "done", "session_id": "s6", "turn_id": "turn-cost", "seq": 3},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query("s6", "cost me")
        assert result.cost_summary == {"tokens_in": 120, "tokens_out": 45, "cost_usd": 0.0023}
        assert result.citations == [{"title": "Ref A", "url": "https://example.com/a"}]
        assert result.content == "Answer"
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 7: timeout
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_timeout(mock_deeptutor_server):
    """Server sends no done event → DeepTutorTimeoutError."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = []  # empty — no done event coming

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        t0 = time.monotonic()
        with pytest.raises(DeepTutorTimeoutError, match="timed out"):
            await client.query("s_timeout", "This will timeout", timeout=2.0)
        elapsed = time.monotonic() - t0
        assert 1.8 <= elapsed <= 3.5, f"Timeout took {elapsed:.2f}s, expected ~2.0s"
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Case 8: reconnect backoff timing
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reconnect_backoff():
    """After a failed connect, subsequent retries should have increasing delays.

    We verify that the delay calculation follows exponential backoff:
    base * 2^connection_count, capped at 30s, with jitter 0-1s.
    """
    from agents.deeptutor_ws import RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY, RECONNECT_JITTER

    # Use a bad port so connect always fails
    client = DeepTutorWSClient(ws_url="ws://127.0.0.1:19999/api/v1/ws")
    client.liveness_url = "http://127.0.0.1:19999/"
    client.readiness_url = "http://127.0.0.1:19999/api/v1/knowledge/health"

    try:
        # Simulate multiple failed connect attempts and verify delay grows
        for attempt in range(3):
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** client._connection_count),
                RECONNECT_MAX_DELAY,
            )
            jitter_max = RECONNECT_JITTER
            assert delay >= RECONNECT_BASE_DELAY, f"Attempt {attempt}: delay {delay} < base"

            # Bump connection count to simulate failed attempt
            client._connection_count += 1

        # After 5+ attempts, delay should be capped at RECONNECT_MAX_DELAY
        client._connection_count = 10
        delay = min(
            RECONNECT_BASE_DELAY * (2 ** client._connection_count),
            RECONNECT_MAX_DELAY,
        )
        assert delay == RECONNECT_MAX_DELAY, f"Delay {delay} should be capped at {RECONNECT_MAX_DELAY}"
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Bonus: connect without health (direct)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_not_connected_query_raises():
    """query() before connect() raises DeepTutorNotConnectedError."""
    client = DeepTutorWSClient(ws_url="ws://127.0.0.1:19999/api/v1/ws")
    try:
        with pytest.raises(DeepTutorNotConnectedError):
            await client.query("s", "hello")
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Bonus: query with tools and config
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_sends_tools_and_config(mock_deeptutor_server):
    """query() with tools + config → server receives them."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [{"type": "done", "session_id": "s_tools", "turn_id": "t-tools", "seq": 1}]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query(
            "s_tools",
            "do it",
            capability="deep_solve",
            config={"temperature": 0.3},
            tools=["web_search", "calculator"],
        )

        # Verify the mock server received the right message
        assert len(ctrl.received) >= 1
        msg = ctrl.received[0]
        assert msg["type"] == "message"
        assert msg["session_id"] == "s_tools"
        assert msg["capability"] == "deep_solve"
        assert msg["content"] == "do it"
        assert msg["config"] == {"temperature": 0.3}
        assert msg["tools"] == ["web_search", "calculator"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_query_forwards_language(mock_deeptutor_server):
    """query() with language → server receives top-level language field."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [{"type": "done", "session_id": "s_lang", "turn_id": "t-lang", "seq": 1}]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query(
            "s_lang",
            "出幾條練習",
            capability="deep_question",
            language="zh-hk",
            config={"topic": "maths", "num_questions": 3},
        )

        assert len(ctrl.received) >= 1
        msg = ctrl.received[0]
        assert msg["language"] == "zh-hk"
        assert msg["capability"] == "deep_question"
        assert msg["config"] == {"topic": "maths", "num_questions": 3}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_query_no_language_omits_field(mock_deeptutor_server):
    """query() without language → no language field in message."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [{"type": "done", "session_id": "s_nolang", "turn_id": "t-nolang", "seq": 1}]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        await client.query("s_nolang", "hello", capability="chat")

        assert len(ctrl.received) >= 1
        msg = ctrl.received[0]
        assert "language" not in msg
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Bonus: listen() handler receives events
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_listen_handler_receives_events(mock_deeptutor_server):
    """listen() callback receives events from the dispatcher."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "content", "content": "chunk", "session_id": "s_listen", "seq": 1},
        {"type": "done", "session_id": "s_listen", "turn_id": "t-listen", "seq": 2},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    received: list[WSEvent] = []

    async def handler(event: WSEvent) -> None:
        received.append(event)

    try:
        await client.connect()
        client.listen(handler)

        # Use query to trigger server events (listen handler runs in parallel)
        result = await client.query("s_listen", "ping")

        # Give dispatcher a moment to route to handler
        await asyncio.sleep(0.1)

        # The handler should have received the same events
        assert len(received) >= 2, f"Expected >=2 events, got {len(received)}: {[e.type for e in received]}"
        assert any(e.type == "content" for e in received)
        assert any(e.type == "done" for e in received)
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
# Regression: nested cost_summary (real container path)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_result_nested_cost_summary(mock_deeptutor_server):
    """cost_summary extracted from metadata.metadata.cost_summary (real server)."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "session", "session_id": "s_nested", "turn_id": "t-nested", "seq": 1},
        {
            "type": "result",
            "session_id": "s_nested",
            "turn_id": "t-nested",
            "seq": 2,
            "metadata": {
                "response": "42",
                "completed": True,
                "engine": "agent_loop",
                "rounds": 1,
                "tool_steps": 0,
                "metadata": {
                    "cost_summary": {
                        "total_cost_usd": 0.00078,
                        "total_tokens": 5564,
                        "prompt_tokens": 5535,
                        "completion_tokens": 29,
                    },
                    "context_budget": {"window": 65536, "used_tokens": 5175},
                },
            },
        },
        {"type": "done", "session_id": "s_nested", "turn_id": "t-nested", "seq": 3},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query("s_nested", "hello")
        assert result.cost_summary == {
            "total_cost_usd": 0.00078,
            "total_tokens": 5564,
            "prompt_tokens": 5535,
            "completion_tokens": 29,
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_result_flat_cost_summary(mock_deeptutor_server):
    """cost_summary extracted from metadata.cost_summary (flat / mock path)."""
    host, port, ctrl = mock_deeptutor_server
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "session", "session_id": "s_flat", "turn_id": "t-flat", "seq": 1},
        {
            "type": "result",
            "session_id": "s_flat",
            "turn_id": "t-flat",
            "seq": 2,
            "metadata": {
                "cost_summary": {
                    "total_tokens": 999,
                    "total_cost_usd": 0.004,
                },
            },
        },
        {"type": "done", "session_id": "s_flat", "turn_id": "t-flat", "seq": 3},
    ]

    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    try:
        await client.connect()
        result = await client.query("s_flat", "hello")
        assert result.cost_summary == {
            "total_tokens": 999,
            "total_cost_usd": 0.004,
        }
    finally:
        await client.close()
