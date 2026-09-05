"""W3-A — WS chat handshake gate + DeepTutor upstream relay (dreamer-api side).

Real WS chat replaces the frontend mock (W3-A work instruction v1.0 §4).
Every gate runs server-side BEFORE the connection upgrades; a failure
rejects at the HTTP layer (JSON + status) with a WARNING audit trail —
never an upgrade-then-kick, never a client-side-only decision.

Gate order (spec v1.4 §1.1, same state sources as pin-verify):
    1. auth      — auth_session cookie resolves to a live user
    2. role      — only `parent` may open a kid chat (Q4: a teacher or
                   admin session opening a chat as a student is refused;
                   teacher watch/join flows are out of W3-A scope)
    3. ownership — the student identifier belongs to this parent; the
                   query carries the 8-char masked prefix (full student
                   ids never leave the server — W2 PR#3 rule), resolved
                   inside the caller's reachable set
    4. class     — classes.student_class_confirmed() (the single shared
                   decision with pin-verify — never a second copy)
    5. consent   — the student's latest media_consent row is not
                   withdrawn (consent.student_media_consent_withdrawn)

On success the request upgrades and frames relay bidirectionally to the
DeepTutor unified endpoint (/api/v1/ws). One chat connection = one
upstream connection; server-assigned session ids are relayed untouched.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

from . import api as api_mod
from . import classes as classes_mod
from . import consent as consent_mod
from . import students as students_mod

logger = logging.getLogger("dreamer.auth.ws_chat")

_UPSTREAM_CONNECT_TIMEOUT = 30.0  # seconds for the upstream WS connect


def _read_upstream_config() -> dict:
    """DeepTutor unified WS endpoint config (config/ws_client.yaml).

    Mirrors agents/deeptutor_ws.py resolution (scheme://host:port+path)
    but reads the YAML directly so this auth package stays independent of
    the heavy `agents` package import graph. env override for tests.
    """
    override = os.environ.get("DEEPTUTOR_WS_URL")
    if override:
        return {"scheme": "ws", "host": "override", "port": 0, "path": "", "_url": override}
    try:
        import yaml

        cfg_path = (
            Path(__file__).resolve().parent.parent / "config" / "ws_client.yaml"
        )
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return dict(data.get("deeptutor_ws") or {})
    except (OSError, yaml.YAMLError):
        return {}


def _upstream_ws_url() -> str:
    """Resolve the upstream DeepTutor WS URL for this relay connection."""
    cfg = _read_upstream_config()
    url = cfg.get("_url")
    if url:
        return str(url)
    scheme = cfg.get("scheme", "ws")
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8001)
    path = cfg.get("path", "/api/v1/ws")
    return f"{scheme}://{host}:{port}{path}"


# ---------------------------------------------------------------------------
# Handshake helpers
# ---------------------------------------------------------------------------

def _reject(
    status: int,
    error_body: dict,
    *,
    gate: str,
    user_id: str,
    target_id: Optional[str] = None,
) -> web.Response:
    """HTTP-layer handshake rejection + WARNING audit trail.

    The gate name goes to the server-side audit only; the HTTP body keeps
    the unified wording used across the auth API so callers cannot learn
    which guard fired (no id-oracle / gate-oracle).
    """
    api_mod._log_security_warning(
        "ws_chat_rejected",
        user_id=user_id,
        target_id=target_id,
        detail=f"handshake gate={gate}",
    )
    return web.json_response(error_body, status=status)


async def _close_quietly(ws) -> None:
    try:
        await ws.close()
    except Exception:
        pass


async def _pump(src, dst) -> None:
    """Forward frames from src to dst until src closes or errors."""
    try:
        async for msg in src:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await dst.send_str(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await dst.send_bytes(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning(
                    "ws_chat relay source error: %s", src.exception()
                )
                break
            else:  # CLOSE / CLOSING / CLOSED
                break
    except (aiohttp.ClientConnectionError, ConnectionResetError):
        pass
    finally:
        await _close_quietly(dst)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def handle_ws_chat(request: web.Request) -> web.Response:
    """GET /api/ws/chat?student=<8-char-masked-prefix> — handshake, relay."""
    user = api_mod._session_user(request)
    if user is None:
        return _reject(
            401,
            api_mod._ERR_AUTH,
            gate="auth",
            user_id="anonymous",
            target_id=request.query.get("student") or None,
        )

    if user["role"] != "parent":
        return _reject(
            403,
            api_mod._ERR_FORBIDDEN,
            gate="role",
            user_id=user["id"],
            target_id=request.query.get("student") or None,
        )

    student_identifier = request.query.get("student", "")
    student, ambiguous = students_mod.resolve_student_identifier(
        student_identifier, user
    )
    if ambiguous:
        return _reject(
            400,
            api_mod._ERR_INVALID,
            gate="ambiguous",
            user_id=user["id"],
            target_id=student_identifier or None,
        )
    if student is None:
        return _reject(
            403,
            api_mod._ERR_FORBIDDEN,
            gate="ownership",
            user_id=user["id"],
            target_id=student_identifier or None,
        )
    if student["parent_id"] is None or student["parent_id"] != user["id"]:
        return _reject(
            403,
            api_mod._ERR_FORBIDDEN,
            gate="ownership",
            user_id=user["id"],
            target_id=student["id"],
        )

    if not classes_mod.student_class_confirmed(student["id"]):
        return _reject(
            403,
            {"error": "等待老師確認"},
            gate="class_confirmed",
            user_id=user["id"],
            target_id=student["id"],
        )

    if consent_mod.student_media_consent_withdrawn(
        user["id"], student["id"]
    ):
        return _reject(
            403,
            api_mod._ERR_FORBIDDEN,
            gate="media_consent_withdrawn",
            user_id=user["id"],
            target_id=student["id"],
        )

    # Handshake passed — upgrade and relay to DeepTutor.
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    upstream_url = _upstream_ws_url()
    try:
        async with aiohttp.ClientSession() as session:
            try:
                upstream = await session.ws_connect(
                    upstream_url,
                    heartbeat=30.0,
                    timeout=aiohttp.ClientWSTimeout(
                        ws_close=_UPSTREAM_CONNECT_TIMEOUT
                    ),
                )
            except Exception as exc:  # connect refused / timeout / DNS
                logger.warning(
                    "ws_chat upstream connect failed url=%s err=%s",
                    upstream_url, exc,
                )
                await ws.send_json(
                    {
                        "type": "error",
                        "error_code": "upstream_unavailable",
                        "content": "連線暫時不可用，請稍後再試",
                    }
                )
                await ws.close()
                return ws
            try:
                await asyncio.gather(
                    _pump(ws, upstream),
                    _pump(upstream, ws),
                )
            finally:
                await _close_quietly(upstream)
    finally:
        await _close_quietly(ws)
    return ws
