"""
DeepTutor WebSocket Client (Phase 2.2 — Day 10 gate).

Connects to DeepTutor backend via the unified WS endpoint at /api/v1/ws.

Protocol (verified against container source):
- Client → Server: {"type":"message","session_id":"...","capability":"chat","content":"..."}
- Server → Client: StreamEvent (content/done/result/error/thinking/tool_call/...)

Architecture:
  Single connection → one receive loop (dispatcher) → per-session asyncio.Queue
  + optional message handler for listen() consumers.

Pool: 50 connections max.
Health: GET / (liveness), GET /api/v1/knowledge/health (readiness).
Reconnect: exponential backoff, max 30s, jitter 0-1s.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import aiohttp

from . import config_loader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WS_HOST_DEFAULT = "127.0.0.1"
WS_PORT_DEFAULT = 8001
WS_PATH = "/api/v1/ws"                     # verified: unified_ws.router @ /api/v1
HEALTH_LIVENESS_PATH = "/"                 # GET / → 200 = alive
HEALTH_READINESS_PATH = "/api/v1/knowledge/health"  # status=ok → ready
POOL_MAX_SIZE = 50

RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
RECONNECT_JITTER = 1.0

QUERY_TIMEOUT = 30.0                       # total accumulation timeout


# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"


@dataclass
class HealthStatus:
    liveness: bool = False
    readiness: bool = False
    checked_at: float = 0.0


@dataclass
class WSEvent:
    """Incoming stream event from DeepTutor server.

    Mirrors StreamEvent.to_dict() from core/stream.py:
    type: content / done / result / error / thinking / tool_call / tool_result / ...
    """
    type: str = ""
    source: str = ""
    stage: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    seq: int = 0
    timestamp: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WSEvent:
        return cls(
            type=data.get("type", ""),
            source=data.get("source", ""),
            stage=data.get("stage", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}) or {},
            session_id=data.get("session_id", ""),
            turn_id=data.get("turn_id", ""),
            seq=data.get("seq", 0),
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class QueryResult:
    """Aggregated result from a query() call."""
    content: str = ""                       # accumulated text chunks
    turn_id: str = ""
    cost_summary: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    events: list[WSEvent] = field(default_factory=list)  # all raw events


class DeepTutorError(Exception):
    """Raised when server returns an error event."""


class DeepTutorTimeoutError(Exception):
    """Raised when query accumulation times out."""


class DeepTutorNotConnectedError(Exception):
    """Raised when trying to use a disconnected client."""


# ---------------------------------------------------------------------------
# DeepTutorWSClient
# ---------------------------------------------------------------------------

class DeepTutorWSClient:
    """WebSocket client for DeepTutor backend (Hermes WS gateway).

    Single-connection dispatcher architecture:
    - _receive_loop() is the sole reader — routes events to per-session queues
      and the optional message handler.
    - query() registers a queue, sends a message, and collects streaming events.
    - listen() registers the message handler for continuous consumption.
    """

    def __init__(
        self,
        ws_url: str | None = None,
        pool_size: int = POOL_MAX_SIZE,
        message_handler: Callable[[WSEvent], Any] | None = None,
    ) -> None:
        cfg = config_loader.get("deeptutor_ws", {})
        host = cfg.get("host", WS_HOST_DEFAULT)
        port = cfg.get("port", WS_PORT_DEFAULT)
        self.ws_url = ws_url or f"ws://{host}:{port}{WS_PATH}"
        self.liveness_url = f"http://{host}:{port}{HEALTH_LIVENESS_PATH}"
        self.readiness_url = f"http://{host}:{port}{HEALTH_READINESS_PATH}"
        self.pool_size = min(pool_size, POOL_MAX_SIZE)

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._state = ConnectionState.DISCONNECTED
        self._reconnect_delay = RECONNECT_BASE_DELAY
        self._connection_count = 0
        self._health = HealthStatus()

        # Dispatcher plumbing
        self._pending_queues: dict[str, asyncio.Queue[WSEvent]] = {}       # session_id → Queue
        self._message_handler = message_handler or self._default_handler
        self._dispatcher_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def check_health(self) -> HealthStatus:
        """Run liveness + readiness checks."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        liveness = False
        readiness = False

        try:
            async with self._session.get(self.liveness_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                liveness = resp.status == 200
        except Exception:
            logger.warning("Liveness check failed (%s)", self.liveness_url)

        try:
            async with self._session.get(self.readiness_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    readiness = body.get("status") == "ok"
        except Exception:
            logger.warning("Readiness check failed (%s)", self.readiness_url)

        self._health = HealthStatus(
            liveness=liveness,
            readiness=readiness,
            checked_at=time.monotonic(),
        )
        return self._health

    @property
    def healthy(self) -> bool:
        return self._health.liveness and self._health.readiness

    @property
    def is_connected(self) -> bool:
        """True if WS is currently connected and dispatcher is running."""
        return self._state == ConnectionState.CONNECTED

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to DeepTutor WS and start dispatcher. Returns True on success."""
        if self._state == ConnectionState.CONNECTED:
            return True

        health = await self.check_health()
        if not health.liveness:
            logger.error("Liveness check failed, aborting connect")
            return False

        self._state = ConnectionState.CONNECTING
        if self._session is None:
            self._session = aiohttp.ClientSession()

        try:
            self._ws = await self._session.ws_connect(
                self.ws_url,
                timeout=aiohttp.ClientTimeout(total=10),
            )
            self._state = ConnectionState.CONNECTED
            self._reconnect_delay = RECONNECT_BASE_DELAY
            self._connection_count += 1
            logger.info("WS connected to %s (count=%d)", self.ws_url, self._connection_count)

            # Start dispatcher
            self._dispatcher_task = asyncio.create_task(self._receive_loop())
            return True
        except Exception as exc:
            logger.error("WS connect failed: %s", exc)
            self._state = ConnectionState.DISCONNECTED
            return False

    async def disconnect(self) -> None:
        """Graceful disconnect — stop dispatcher, close WS."""
        self._state = ConnectionState.CLOSING

        # Drain pending queues with error
        for q in self._pending_queues.values():
            await q.put(WSEvent(type="error", content="Connection closed"))
        self._pending_queues.clear()

        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._state = ConnectionState.DISCONNECTED
        logger.info("WS disconnected")

    async def close(self) -> None:
        """Full shutdown — disconnect WS and close HTTP session."""
        await self.disconnect()
        if self._session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Reconnect loop
    # ------------------------------------------------------------------

    async def _reconnect_loop(self) -> None:
        """Exponential-backoff reconnect."""
        while self._state == ConnectionState.DISCONNECTED:
            delay = min(self._reconnect_delay * (2 ** self._connection_count), RECONNECT_MAX_DELAY)
            jitter = random.uniform(0, RECONNECT_JITTER)
            wait = delay + jitter
            logger.debug("Reconnecting in %.1fs", wait)
            await asyncio.sleep(wait)

            if await self.connect():
                return

    # ------------------------------------------------------------------
    # Dispatcher (single receive loop)
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Single reader: receive ALL WS messages and dispatch.

        Routes each event to:
        1. The pending queue registered for its session_id (if any)
        2. The message handler (if set)
        """
        assert self._ws is not None

        try:
            async for raw in self._ws:
                if raw.type != aiohttp.WSMsgType.TEXT:
                    if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue

                try:
                    data = json.loads(raw.data)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from WS: %.100s", raw.data)
                    continue

                event = WSEvent.from_dict(data)

                # Route to pending query: match by session_id first, then turn_id.
                # Also register turn_id → queue aliasing so events that only carry
                # turn_id (e.g. late done/results) still reach the right consumer.
                queue = self._pending_queues.get(event.session_id) or self._pending_queues.get(event.turn_id)

                # Server assigns its own session_id (e.g. "unified_xxx") which differs
                # from the client-chosen session_id. As a fallback: when no queue
                # matches and there is exactly one pending queue, route to it.
                # This correctly handles the "server-assigned ID" case while
                # preserving isolation for multi-session scenarios.
                if queue is None and len(self._pending_queues) == 1:
                    queue = next(iter(self._pending_queues.values()))

                if queue is not None:
                    await queue.put(event)
                    # alias: when we first see an event with a new session_id/turn_id,
                    # register it so future events for the same session are routed directly.
                    if event.session_id and event.session_id not in self._pending_queues:
                        self._pending_queues[event.session_id] = queue
                    if event.turn_id and event.turn_id not in self._pending_queues:
                        self._pending_queues[event.turn_id] = queue

                # Route to message handler
                try:
                    await self._message_handler(event)
                except Exception:
                    logger.exception("Message handler error for event type=%s", event.type)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Receive loop error: %s", exc)
        finally:
            self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def _send_raw(self, data: dict[str, Any]) -> bool:
        """Send a JSON dict to the WS. Internal use only."""
        if self._state != ConnectionState.CONNECTED or self._ws is None:
            raise DeepTutorNotConnectedError("WS not connected")
        try:
            payload = json.dumps(data, ensure_ascii=False)
            await self._ws.send_str(payload)
            return True
        except Exception as exc:
            logger.error("WS send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # query() — streaming accumulation with single-dispatcher routing
    # ------------------------------------------------------------------

    async def query(
        self,
        session_id: str,
        content: str,
        *,
        capability: str = "chat",
        config: dict[str, Any] | None = None,
        tools: list[str] | None = None,
        timeout: float = QUERY_TIMEOUT,
    ) -> QueryResult:
        """Send a message and collect the full streaming response.

        Sends {"type":"message", "session_id":..., "capability":..., "content":...}
        then accumulates all ``content`` events until ``done`` or ``error``.

        Args:
            session_id: Unique session identifier.
            content: User message text.
            capability: Capability to invoke (default: "chat").
            config: Optional capability-specific config dict.
            tools: Optional tool whitelist for this turn.
            timeout: Total accumulation timeout in seconds.

        Returns:
            QueryResult with accumulated content, cost_summary, and citations.

        Raises:
            DeepTutorError: Server returned an error event.
            DeepTutorTimeoutError: No ``done`` event within timeout.
            DeepTutorNotConnectedError: Client is not connected.
        """
        if self._state != ConnectionState.CONNECTED:
            raise DeepTutorNotConnectedError("Cannot query: WS not connected")

        # Register a queue for this session
        queue: asyncio.Queue[WSEvent] = asyncio.Queue()
        self._pending_queues[session_id] = queue

        try:
            # Send the message (server expects raw dict, not wrapped)
            msg = {
                "type": "message",
                "session_id": session_id,
                "capability": capability,
                "content": content,
            }
            if config:
                msg["config"] = config
            if tools is not None:
                msg["tools"] = tools

            if not await self._send_raw(msg):
                raise DeepTutorNotConnectedError("WS send failed")

            # Accumulate streaming events
            chunks: list[str] = []
            all_events: list[WSEvent] = []
            cost_summary: dict[str, Any] = {}
            citations: list[dict[str, Any]] = []
            result_meta: dict[str, Any] = {}
            turn_id = ""

            async def _accumulate() -> QueryResult:
                nonlocal cost_summary, citations, result_meta, turn_id

                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        raise DeepTutorTimeoutError(
                            f"Query timed out after {timeout:.1f}s "
                            f"(received {len(chunks)} chunks, {len(all_events)} events)"
                        )

                    all_events.append(event)
                    event_type = event.type

                    # Capture turn_id from any event that carries it
                    if event.turn_id and not turn_id:
                        turn_id = event.turn_id

                    if event_type == "content":
                        chunks.append(event.content)
                    elif event_type == "result":
                        result_meta = event.metadata
                        # Real container nests cost_summary under metadata.metadata
                        # (e.g. {"metadata":{"cost_summary":{...}}}).
                        # Mock server sends it flat for convenience.
                        inner = event.metadata.get("metadata", {}) or {}
                        cost_summary = (
                            event.metadata.get("cost_summary")
                            or inner.get("cost_summary", {})
                        )
                        citations = (
                            event.metadata.get("citations")
                            or inner.get("citations", [])
                        )
                        turn_id = event.turn_id or turn_id
                    elif event_type == "done":
                        turn_id = turn_id or event.turn_id
                        return QueryResult(
                            content="".join(chunks),
                            turn_id=turn_id,
                            cost_summary=cost_summary,
                            citations=citations,
                            events=all_events,
                        )
                    elif event_type == "error":
                        raise DeepTutorError(event.content)
                    # Other types (thinking, tool_call, tool_result, stage_start,
                    # stage_end, progress, sources, session, session_meta,
                    # wait_for_input) are collected but don't affect the result loop.
                    # wait_for_input would need special handling for interactive
                    # turns — tracked but not implemented in this MR.

                # unreachable

            return await _accumulate()

        finally:
            # Remove the original registration and any aliases that point to this queue
            for key in list(self._pending_queues.keys()):
                if self._pending_queues[key] is queue:
                    del self._pending_queues[key]

    # ------------------------------------------------------------------
    # listen() — continuous stream via message handler
    # ------------------------------------------------------------------

    def listen(self, callback: Callable[[WSEvent], Any]) -> None:
        """Register a callback for all incoming WS events.

        Unlike query(), this does NOT consume events from the stream —
        it simply sets the handler that is called by the dispatcher for
        every event. Safe to use concurrently with query().

        To stop listening, call listen_stop().
        """
        self._message_handler = callback

    def listen_stop(self) -> None:
        """Remove the listen callback, reverting to default handler."""
        self._message_handler = self._default_handler

    async def _default_handler(self, event: WSEvent) -> None:
        logger.debug("WS event: type=%s session=%s turn=%s seq=%d",
                     event.type, event.session_id, event.turn_id, event.seq)

    # ------------------------------------------------------------------
    # Convenience: health-first connect
    # ------------------------------------------------------------------

    async def wait_until_ready(self, max_retries: int = 10, interval: float = 2.0) -> bool:
        """Poll health until both liveness and readiness pass, then connect."""
        for _ in range(max_retries):
            health = await self.check_health()
            if health.liveness and health.readiness:
                return await self.connect()
            await asyncio.sleep(interval)
        logger.error("wait_until_ready exhausted (%d retries)", max_retries)
        return False
