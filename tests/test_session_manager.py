"""
test_session_manager.py — SessionManager unit tests (pytest-asyncio + mock WS servers).

Covers:
 1. create_session — basic creation, SessionInfo fields populated
 2. pool cap — PoolExhaustedError at 50 sessions
 3. query delegation — session_manager.query() returns QueryResult
 4. server_id capture — session event → SessionInfo.server_id
 5. concurrent sessions — two sessions, isolated clients+queues
 6. end_session — frees pool slot, client closed
 7. shutdown — all sessions closed, pool empty
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time

import aiohttp
import aiohttp.web
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.deeptutor_ws import (
    DeepTutorError,
    DeepTutorNotConnectedError,
    DeepTutorTimeoutError,
    QueryResult,
)
from agents.session_manager import (
    PoolExhaustedError,
    SessionInfo,
    SessionManager,
)


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockController:
    """Controls a mock WS server with per-connection response sequences."""

    def __init__(self) -> None:
        self.sequence: list[dict] = []       # events to send per message
        self.received: list[dict] = []       # all messages received
        self.auto_done: bool = True
        self.delay_ms: float = 0

    async def ws_handler(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        msg_count = 0
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    self.received.append(json.loads(msg.data))
                except json.JSONDecodeError:
                    pass
                msg_count += 1
                for event in self.sequence:
                    await ws.send_json(event)
                    if self.delay_ms:
                        await asyncio.sleep(self.delay_ms / 1000)
                if self.auto_done:
                    await ws.send_json({
                        "type": "done",
                        "turn_id": "turn-test-001",
                        "session_id": "auto",
                        "seq": 999,
                    })
        return ws


async def _start_mock(host: str, port: int, ctrl: MockController) -> aiohttp.web.AppRunner:
    """Start a mock DeepTutor server at host:port, return runner."""
    app = aiohttp.web.Application()
    app.router.add_get("/", lambda r: aiohttp.web.Response(status=200, text="OK"))
    app.router.add_get("/api/v1/knowledge/health", lambda r: aiohttp.web.json_response({"status": "ok"}))
    app.router.add_get("/api/v1/ws", ctrl.ws_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()
    return runner


# ══════════════════════════════════════════════════════════════════
# Fixture: mock server + session_manager
# ══════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def mock_env() -> tuple[int, MockController, aiohttp.web.AppRunner]:
    """Start a mock DeepTutor server and return (port, controller, runner)."""
    port = _free_port()
    ctrl = MockController()
    runner = await _start_mock("127.0.0.1", port, ctrl)
    yield port, ctrl, runner
    await runner.cleanup()


# ══════════════════════════════════════════════════════════════════
# Case 1: create_session — basic creation
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_session_basic(mock_env):
    """create_session creates a SessionInfo with client attached."""
    port, ctrl, _ = mock_env
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    try:
        info = await mgr.create_session("alice")
        assert isinstance(info, SessionInfo)
        assert info.client_id == "alice"
        assert info.client is not None
        assert info.created_at > 0
        assert info.server_id == ""        # not set until session event
        assert mgr.active_count == 1
        assert "alice" in mgr.sessions
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Case 2: pool cap — PoolExhaustedError
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_session_pool_exhausted(mock_env):
    """Creating N+1 sessions with pool_size=N raises PoolExhaustedError."""
    port, ctrl, _ = mock_env
    POOL = 3
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=POOL)

    try:
        # Fill the pool
        for i in range(POOL):
            await mgr.create_session(f"user-{i}")
        assert mgr.active_count == POOL

        # Next one should fail
        with pytest.raises(PoolExhaustedError, match="pool full"):
            await mgr.create_session("overflow")
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Case 3: query delegation
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_delegation(mock_env):
    """session_manager.query() delegates to the session's client and returns QueryResult."""
    port, ctrl, _ = mock_env
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "content", "content": "Hello World", "session_id": "bob", "turn_id": "turn-bob", "seq": 1},
        {"type": "done", "session_id": "bob", "turn_id": "turn-bob", "seq": 2},
    ]

    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    try:
        await mgr.create_session("bob")
        result = await mgr.query("bob", "test message")
        assert isinstance(result, QueryResult)
        assert result.content == "Hello World"
        assert result.turn_id == "turn-bob"
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Case 4: server_id capture from session event
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_server_id_capture(mock_env):
    """Session event with session_id → SessionInfo.server_id populated."""
    port, ctrl, _ = mock_env
    ctrl.auto_done = False
    ctrl.sequence = [
        {"type": "session", "session_id": "unified-alpha-42", "seq": 0},
        {"type": "content", "content": "ok", "session_id": "unified-alpha-42", "turn_id": "t-alpha", "seq": 1},
        {"type": "done", "session_id": "unified-alpha-42", "turn_id": "t-alpha", "seq": 2},
    ]

    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    try:
        await mgr.create_session("alpha")
        # Trigger a query so the server sends its sequence (including session event)
        result = await mgr.query("alpha", "ping")

        # Give the listen handler a moment to fire (runs in same event loop)
        await asyncio.sleep(0.05)

        info = mgr.sessions["alpha"]
        assert info.server_id == "unified-alpha-42", (
            f"Expected server_id='unified-alpha-42', got '{info.server_id}'"
        )
        assert result.content == "ok"
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Case 5: concurrent sessions — isolated clients + queues
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_concurrent_sessions_isolation():
    """Two sessions with separate clients get correct content each.

    Uses two mock servers on different ports — each session gets its own
    DeepTutorWSClient connecting to its own server, exercising the pool design.
    """
    port_a = _free_port()
    port_b = _free_port()

    ctrl_a = MockController()
    ctrl_a.auto_done = False
    ctrl_a.sequence = [
        {"type": "content", "content": "A-response", "session_id": "charlie", "turn_id": "t-charlie", "seq": 1},
        {"type": "done", "session_id": "charlie", "turn_id": "t-charlie", "seq": 2},
    ]

    ctrl_b = MockController()
    ctrl_b.auto_done = False
    ctrl_b.sequence = [
        {"type": "content", "content": "B-response", "session_id": "dana", "turn_id": "t-dana", "seq": 1},
        {"type": "done", "session_id": "dana", "turn_id": "t-dana", "seq": 2},
    ]

    runner_a = await _start_mock("127.0.0.1", port_a, ctrl_a)
    runner_b = await _start_mock("127.0.0.1", port_b, ctrl_b)

    mgr_a = SessionManager(host="127.0.0.1", port=port_a, pool_size=5)
    mgr_b = SessionManager(host="127.0.0.1", port=port_b, pool_size=5)

    try:
        await mgr_a.create_session("charlie")
        await mgr_b.create_session("dana")

        # Run concurrently
        r_a, r_b = await asyncio.gather(
            mgr_a.query("charlie", "question A"),
            mgr_b.query("dana", "question B"),
        )

        assert r_a.content == "A-response", f"Charlie got: {r_a.content!r}"
        assert r_b.content == "B-response", f"Dana got: {r_b.content!r}"
        assert r_a.turn_id == "t-charlie"
        assert r_b.turn_id == "t-dana"
    finally:
        await mgr_a.shutdown()
        await mgr_b.shutdown()
        await runner_a.cleanup()
        await runner_b.cleanup()


# ══════════════════════════════════════════════════════════════════
# Case 6: end_session frees pool slot
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_end_session_releases_slot(mock_env):
    """end_session removes session and allows a new one."""
    port, ctrl, _ = mock_env
    POOL = 2
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=POOL)

    try:
        await mgr.create_session("one")
        await mgr.create_session("two")
        assert mgr.active_count == 2

        await mgr.end_session("one")
        assert mgr.active_count == 1
        assert "one" not in mgr.sessions
        assert "two" in mgr.sessions

        # Should succeed now that one slot is free
        await mgr.create_session("three")
        assert mgr.active_count == 2
        assert "three" in mgr.sessions
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Case 7: shutdown
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shutdown_cleanup(mock_env):
    """shutdown() closes all sessions, pool empty."""
    port, ctrl, _ = mock_env
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    for name in ("p1", "p2", "p3"):
        await mgr.create_session(name)
    assert mgr.active_count == 3

    await mgr.shutdown()
    assert mgr.active_count == 0
    assert len(mgr.sessions) == 0


# ══════════════════════════════════════════════════════════════════
# Bonus: end_session on nonexistent session (no-op)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_end_nonexistent_session_noop(mock_env):
    """end_session on missing client_id is a safe no-op."""
    port, ctrl, _ = mock_env
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    try:
        await mgr.create_session("only")
        await mgr.end_session("nobody")     # should not raise
        assert mgr.active_count == 1
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Bonus: create_session with same client_id returns existing
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_session_idempotent(mock_env):
    """create_session with same client_id returns the existing session."""
    port, ctrl, _ = mock_env
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    try:
        s1 = await mgr.create_session("reuse")
        s2 = await mgr.create_session("reuse")
        assert s1 is s2
        assert mgr.active_count == 1      # still one session
    finally:
        await mgr.shutdown()


# ══════════════════════════════════════════════════════════════════
# Bonus: query on unknown session raises KeyError
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_query_unknown_session_raises(mock_env):
    """query() on nonexistent client_id raises KeyError."""
    port, ctrl, _ = mock_env
    mgr = SessionManager(host="127.0.0.1", port=port, pool_size=5)

    with pytest.raises(KeyError, match="No session found"):
        await mgr.query("ghost", "hello")


# ══════════════════════════════════════════════════════════════════
# Bonus: pool_size property
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pool_size_capped():
    """pool_size > POOL_MAX_SIZE is capped."""
    mgr = SessionManager(host="127.0.0.1", port=8001, pool_size=999)
    assert mgr.pool_size == 50   # POOL_MAX_SIZE
    await mgr.shutdown()
