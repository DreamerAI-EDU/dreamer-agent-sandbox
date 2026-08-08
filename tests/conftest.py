"""Shared fixtures for Phase 2 tests."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from typing import Any, Callable

import aiohttp
import aiohttp.web
import pytest
import pytest_asyncio


# ── Free port helper ──────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Mock WS handler control ───────────────────────────

class MockWSController:
    """Controls the behaviour of the mock WebSocket server."""

    def __init__(self) -> None:
        self.sequence: list[dict[str, Any]] = []          # events to send, in order
        self.received: list[dict[str, Any]] = []          # messages received from client
        self.auto_done: bool = True                        # append {"type":"done"} after sequence
        self.close_after: int = -1                         # close after N messages (-1 = never)
        self.delay_ms: float = 0                           # delay between each send

    async def handler(self, ws: aiohttp.web.WebSocketResponse) -> None:
        """WS handler: receive messages then send the programmed sequence."""
        msg_count = 0
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    self.received.append(json.loads(msg.data))
                except json.JSONDecodeError:
                    pass
                msg_count += 1

                # Send sequence for each incoming message
                for event in self.sequence:
                    await ws.send_json(event)
                    if self.delay_ms:
                        await asyncio.sleep(self.delay_ms / 1000)

                if self.auto_done:
                    await ws.send_json({"type": "done", "turn_id": "turn-test-001", "session_id": "auto", "seq": 999})

                if 0 < self.close_after <= msg_count:
                    await ws.close()
                    return


# ── Mock aiohttp server fixture ───────────────────────

@pytest_asyncio.fixture
async def mock_deeptutor_server() -> AsyncGenerator[
    tuple[str, int, MockWSController], None
]:
    """Spin up an aiohttp server that mocks DeepTutor HTTP + WS.

    Returns (host, port, controller).
    """
    controller = MockWSController()
    port = _free_port()
    host = "127.0.0.1"

    async def health_liveness(request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.Response(status=200, text="OK")

    async def health_readiness(request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.json_response({"status": "ok"})

    async def ws_handler(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        await controller.handler(ws)
        return ws

    app = aiohttp.web.Application()
    app.router.add_get("/", health_liveness)
    app.router.add_get("/api/v1/knowledge/health", health_readiness)
    app.router.add_get("/api/v1/ws", ws_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()

    yield host, port, controller

    await runner.cleanup()


# ── Client fixture ────────────────────────────────────

@pytest_asyncio.fixture
async def ws_client(mock_deeptutor_server) -> AsyncGenerator[Any, None]:
    """Create a DeepTutorWSClient connected to the mock server.

    Late import so sys.path is already patched by the test module.
    """
    from agents.deeptutor_ws import DeepTutorWSClient

    host, port, _ = mock_deeptutor_server
    client = DeepTutorWSClient(ws_url=f"ws://{host}:{port}/api/v1/ws")
    # Override health URLs to match mock server
    client.liveness_url = f"http://{host}:{port}/"
    client.readiness_url = f"http://{host}:{port}/api/v1/knowledge/health"

    yield client

    await client.close()
