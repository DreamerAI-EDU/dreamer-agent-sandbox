"""
Session Manager for DeepTutor WS clients (Phase 2.2 — Day 10 gate).

Manages a pool of DeepTutorWSClient instances.
One session = one WS connection + one client (pool cap 50).
Client → Server session_id mapping recorded for debug/tracing.

Design rationale (per trial_ws round-trip discovery):
- Server assigns its own session_id (unified_xxx), doesn't echo client's
- `session` event carries the server-assigned ID; captured on first arrival
- Single-connection-per-session eliminates cross-session dispatch complexity
- Documented in docs/phase2-websocket.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from .deeptutor_ws import (
    DeepTutorNotConnectedError,
    DeepTutorWSClient,
    POOL_MAX_SIZE,
    WS_PATH,
    QueryResult,
    WSEvent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PoolExhaustedError
# ---------------------------------------------------------------------------


class PoolExhaustedError(Exception):
    """Raised when the session pool is at capacity."""


# ---------------------------------------------------------------------------
# SessionInfo
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """Metadata for one active session.

    client_id:  caller-chosen ephemeral ID (e.g. ``ephemeral_student_uuid``)
    server_id:  server-assigned ID from first ``session`` event (e.g. ``unified_xxx``)
    created_at: monotonic timestamp of session creation
    client:     the DeepTutorWSClient instance bound to this session
    """

    client_id: str
    server_id: str = ""
    created_at: float = 0.0
    client: DeepTutorWSClient | None = None


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Pool manager for DeepTutor WS connections.

    Design:
    - One session = one DeepTutorWSClient (one WS connection)
    - Pool cap: 50 concurrent sessions (matches POOL_MAX_SIZE)
    - client_id → server_id mapping from first ``session`` event
    - Per-session query() delegates to the bound client
    - Per-session listen() callback captures server_id via dispatcher

    Usage::

        mgr = SessionManager(host="127.0.0.1", port=8001, pool_size=50)
        await mgr.create_session("alice")
        result = await mgr.query("alice", "What is 2+2?")
        print(mgr.sessions["alice"].server_id)  # e.g. "unified_abc123"
        await mgr.end_session("alice")
        await mgr.shutdown()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8001,
        pool_size: int = POOL_MAX_SIZE,
    ) -> None:
        self._host = host
        self._port = port
        self._pool_size = min(pool_size, POOL_MAX_SIZE)
        self._sessions: dict[str, SessionInfo] = {}
        self._server_ids: dict[str, str] = {}  # ephemeral capture during query
        self._lock = asyncio.Lock()

    @property
    def sessions(self) -> dict[str, SessionInfo]:
        """Read-only view of active sessions."""
        return self._sessions

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def pool_size(self) -> int:
        return self._pool_size

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def create_session(self, client_id: str) -> SessionInfo:
        """Create a new session bound to a dedicated WS connection.

        Returns the existing session if *client_id* is already active.

        Raises:
            PoolExhaustedError: Pool at capacity (50 sessions).
            DeepTutorNotConnectedError: WS connect / health check failed.
        """
        async with self._lock:
            # Reuse existing session
            if client_id in self._sessions:
                return self._sessions[client_id]

            # Enforce pool cap
            if len(self._sessions) >= self._pool_size:
                raise PoolExhaustedError(
                    f"Session pool full ({self._pool_size}/{self._pool_size}). "
                    f"End an existing session before creating a new one."
                )

            # Create a dedicated client for this session
            client = DeepTutorWSClient(
                ws_url=f"ws://{self._host}:{self._port}{WS_PATH}",
            )
            client.liveness_url = f"http://{self._host}:{self._port}/"
            client.readiness_url = (
                f"http://{self._host}:{self._port}/api/v1/knowledge/health"
            )

            ok = await client.connect()
            if not ok:
                await client.close()
                raise DeepTutorNotConnectedError(
                    f"Failed to connect session '{client_id}' to "
                    f"ws://{self._host}:{self._port}{WS_PATH}"
                )

            info = SessionInfo(
                client_id=client_id,
                created_at=time.monotonic(),
                client=client,
            )

            # Register a listen handler to capture server_id from the
            # first ``session`` event the server sends back.
            # Per dispatcher architecture, this runs in parallel with
            # query() and captures the server_id regardless of who
            # initiated the first turn.
            capture: dict[str, str] = {}

            async def _capture_server_id(event: WSEvent) -> None:
                if event.type == "session" and event.session_id and not capture:
                    capture["id"] = event.session_id
                    info.server_id = event.session_id
                    logger.debug(
                        "Session %s → server_id %s", client_id, event.session_id
                    )

            client.listen(_capture_server_id)

            self._sessions[client_id] = info
            logger.info(
                "Session created: %s (active=%d/%d)",
                client_id,
                len(self._sessions),
                self._pool_size,
            )
            return info

    async def query(
        self,
        client_id: str,
        content: str,
        *,
        capability: str = "chat",
        config: dict[str, Any] | None = None,
        tools: list[str] | None = None,
        timeout: float = 30.0,
    ) -> QueryResult:
        """Send a message on the session's connection and collect the response.

        Delegates to the session's ``DeepTutorWSClient.query()``.
        The ``session`` event (with server-assigned ID) is captured
        by the listen handler registered during ``create_session()``.

        Raises:
            KeyError: No session found for *client_id*.
            DeepTutorNotConnectedError: Session's client is disconnected.
        """
        session = self._sessions.get(client_id)
        if session is None:
            raise KeyError(f"No session found for client_id='{client_id}'")
        if session.client is None:
            raise DeepTutorNotConnectedError(
                f"Session '{client_id}' has no active client"
            )

        return await session.client.query(
            client_id,
            content,
            capability=capability,
            config=config,
            tools=tools,
            timeout=timeout,
        )

    async def end_session(self, client_id: str) -> None:
        """End a session and close its WS connection.

        Safe to call on nonexistent sessions (no-op).
        """
        async with self._lock:
            session = self._sessions.pop(client_id, None)
            if session is None:
                return

            if session.client:
                await session.client.close()

            logger.info(
                "Session ended: %s (server_id=%s, active=%d/%d)",
                client_id,
                session.server_id or "(not captured)",
                len(self._sessions),
                self._pool_size,
            )

    async def shutdown(self) -> None:
        """End all sessions and release all connections."""
        async with self._lock:
            client_ids = list(self._sessions.keys())

        for client_id in client_ids:
            await self.end_session(client_id)

        logger.info("SessionManager shut down (0 active)")
