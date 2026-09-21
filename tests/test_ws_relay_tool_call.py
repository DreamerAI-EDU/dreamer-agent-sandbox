"""PR-D-b1 — relay-side clarification-card contract (design v0.2.1 §A.5).

The backend half of the clarification card: the relay must treat `tool_call`
as a contract frame it forwards verbatim, park the turn on the child's answer,
forward that answer on the *same* turn, and close the wait with its own error
code — never as an idle engine.

Covered here (acceptance #1–#6 of §6.2, the D-b1 subset):
    1. `tool_call` is forwarded unchanged and audited once
    2. a turn parked on a card survives the idle watchdog
    3. `tool_result` rides the open turn; a non-pending pick is dropped
    4. the clarify budget closes the wait with ERR_CLARIFY_TIMEOUT, not idle
    5. replay carries the card *and* the pick (R5 β)
    6. every audit row stays mask-only (紅線 8)

The upstream is the same scripted stand-in the P3/P4 suites use, wired into
`ws_chat._upstream_ws_url`, so no real DeepTutor is needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import uuid

import aiohttp
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import classes as classes_mod  # noqa: E402
from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import relay_audit as relay_audit_mod  # noqa: E402
from auth import security as auth_security  # noqa: E402
from auth import students as students_mod  # noqa: E402
from auth import ws_chat as ws_chat_mod  # noqa: E402
from auth.api import build_app  # noqa: E402

CHAT_VERSION = consent_mod.get_doc_config("chat_consent")["current_version"]

_IDLE_WATCHDOG_ENV = "WS_CHAT_IDLE_WATCHDOG_SECONDS"
_CLARIFY_WAIT_ENV = "WS_CHAT_CLARIFY_WAIT_SECONDS"

#: engine-owned ids used across the cases (the relay never invents these)
_SID = "engine-clarify-001"
_TCID = "tc-abc-001"
_TURN_ID = "turn-clarify-001"


# ---------------------------------------------------------------------------
# Fixtures & builders (same pattern as test_ws_chat_handshake.py)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _future_iso(**delta: int) -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _db_path() -> str:
    return os.environ["DREAMER_DB_PATH"]


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB + isolated audit log per test."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    monkeypatch.setattr(
        consent_mod, "AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl")
    )
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _noop_message(ws, conn: int, idx: int) -> None:  # pragma: no cover
    return None


class _ScriptedUpstream:
    """A DeepTutor WS stand-in whose reply depends on the incoming message."""

    def __init__(self) -> None:
        self.connections = 0
        self.disconnects = 0
        self.frames: list[dict] = []  # {"conn", "raw", "frame"} in arrival order
        self.on_message = _noop_message


@pytest_asyncio.fixture
async def p3_upstream(monkeypatch):
    """Scriptable upstream wired into ws_chat._upstream_ws_url."""
    controller = _ScriptedUpstream()
    port = _port()

    async def ws_handler(request):
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        controller.connections += 1
        conn = controller.connections
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                controller.frames.append(
                    {"conn": conn, "raw": msg.data, "frame": json.loads(msg.data)}
                )
                await controller.on_message(ws, conn, len(controller.frames) - 1)
        except (aiohttp.ClientConnectionError, ConnectionResetError):
            pass
        finally:
            controller.disconnects += 1
        return ws

    app = aiohttp.web.Application()
    app.router.add_get("/api/v1/ws", ws_handler)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    monkeypatch.setattr(
        ws_chat_mod, "_upstream_ws_url", lambda: f"ws://127.0.0.1:{port}/api/v1/ws"
    )
    yield controller
    await runner.cleanup()


def _new_user(*, role: str = "parent") -> str:
    uid = str(uuid.uuid4())
    auth_db.create_user(
        user_id=uid,
        email=f"{uid[:12]}@test.local",
        password_hash=auth_security.hash_password("test-pass-0001"),
        role=role,
        email_verified=True,
    )
    return uid


def _new_session(user_id: str, *, expires_days: int = 1) -> str:
    sid = str(uuid.uuid4())
    auth_db.create_session(
        session_id=sid,
        user_id=user_id,
        expires_at=_future_iso(days=expires_days),
    )
    return sid


def _confirmed_trio():
    """Return (parent_session, student_id) with a fully approved student."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = classes_mod.create_class(teacher_id=teacher_id, name="Test Class")
    student_id = students_mod.create_student(
        first_name="小明",
        age_band="P1-P3",
        lang_code="zh-hk",
        pin_hash=students_mod.hash_pin("1357"),
        parent_id=parent_id,
        teacher_id=teacher_id,
    )
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            "INSERT INTO class_students (class_id, student_id, status,"
            " created_at) VALUES (?, ?, ?, ?)",
            (class_id, student_id, "confirmed", _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return _new_session(parent_id), student_id


async def _agree_chat(session: str, student_id: str) -> None:
    consent_mod.insert_consent_row(
        user_id=auth_db.get_session_user(session)["id"],
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="agreed",
        student_id=student_id,
    )


async def _open_chat(client, session: str, student_id: str):
    return await client.ws_connect(
        f"/api/ws/chat?student={student_id[:8]}",
        headers={"Cookie": f"auth_session={session}"},
    )


async def _collect(ws, count: int, *, timeout: float = 5.0) -> list[dict]:
    events = []
    for _ in range(count):
        msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
        assert msg.type == aiohttp.WSMsgType.TEXT, msg
        events.append(json.loads(msg.data))
    return events


async def _assert_quiet(ws, *, timeout: float = 0.6) -> None:
    """Assert nothing arrives — i.e. no hidden retry / no stray frame."""
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ws.receive(), timeout=timeout)


async def _wait_for(predicate, *, timeout: float = 3.0) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def _audit(*, event: str | None = None) -> list[dict]:
    rows = relay_audit_mod.rows()
    return [r for r in rows if event is None or r["event"] == event]


def _card_frame() -> dict:
    """The clarification card as the engine would send it (opaque to the relay)."""
    return {
        "type": "tool_call",
        "tool_call_id": _TCID,
        "session_id": _SID,
        "prompt": "你想問邊樣？",
        "options": [
            {"id": "opt-1", "label": "數學"},
            {"id": "opt-2", "label": "科學"},
        ],
    }


def _pick_frame() -> dict:
    return {
        "type": "tool_result",
        "tool_call_id": _TCID,
        "session_id": _SID,
        "option_id": "opt-1",
    }


async def _start_turn(ws) -> None:
    await ws.send_json(
        {"type": "message", "capability": "chat", "message": "我想學數學"}
    )


# ---------------------------------------------------------------------------
# #1 — tool_call is forwarded verbatim and audited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_tool_call_is_forwarded_verbatim_and_audited(
    client, p3_upstream
):
    """Acceptance #1: the card reaches the child byte-for-byte and leaves one
    audit row naming the engine's tool_call_id. The turn stays open."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = _card_frame()

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(card)

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)

    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "tool_call"]
    # verbatim: the relay is not allowed to reshape the contract frame
    assert events[1] == card
    # the card does not end the turn: no turn_end yet, and no kill of any kind
    assert _audit(event="turn_end") == []
    assert _audit(event="watchdog_kill") == []
    assert _audit(event="clarify_timeout") == []
    await ws.close()

    calls = _audit(event="tool_call")
    assert len(calls) == 1
    assert calls[0]["student_mask"] == student_id[:8]
    assert calls[0]["session_id"] == _SID
    assert calls[0]["detail"] == f"tool_call_id={_TCID}"
    # the child left mid-wait: the turn is reaped as a client close, not killed
    assert await _wait_for(lambda: bool(_audit(event="turn_end")))
    assert _audit(event="turn_end")[0]["detail"] == "client_closed"


# ---------------------------------------------------------------------------
# #2 — a parked turn survives the idle watchdog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_parked_turn_survives_the_idle_watchdog(
    client, p3_upstream, monkeypatch
):
    """Acceptance #2: the idle window is 0.4s here, the child takes ~1s to
    answer — and nothing is killed, because a card being read is not a silent
    engine. An absolute/idle timer would have reaped this turn."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "0.4")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(_card_frame())
        # then silence: the engine is waiting on the child, not dead

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)

    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "tool_call"]

    # > 2x the idle window with the turn parked: still nothing from the relay
    await _assert_quiet(ws, timeout=1.0)
    await ws.close()

    assert _audit(event="watchdog_kill") == []
    assert _audit(event="clarify_timeout") == []
    # the turn was still open when the child left, so it was reaped, not killed
    assert await _wait_for(lambda: bool(_audit(event="turn_end")))
    assert _audit(event="turn_end")[0]["detail"] == "client_closed"


# ---------------------------------------------------------------------------
# #3 — the pick rides the open turn; a stranger's pick is dropped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_tool_result_rides_the_open_turn(client, p3_upstream):
    """Acceptance #3: the pick is forwarded upstream on the *same* turn (one
    turn_start in the ledger), the engine's answer still reaches the child,
    and the pick is audited once."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "tool_result":
            await ws.send_json(
                {"type": "content", "content": "好嘅，我哋由數學開始。",
                 "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "tool_call"]

    await ws.send_json(_pick_frame())
    tail = await _collect(ws, 2)
    assert [e["type"] for e in tail] == ["content", "done"]
    assert tail[0]["content"] == "好嘅，我哋由數學開始。"
    await ws.close()

    # the engine saw the pick, on the same connection, after the card
    sent = [f["frame"] for f in p3_upstream.frames]
    assert [f["type"] for f in sent] == ["message", "tool_result"]
    assert sent[1]["tool_call_id"] == _TCID
    assert p3_upstream.connections == 1

    results = _audit(event="tool_result")
    assert len(results) == 1
    assert results[0]["detail"] == f"tool_call_id={_TCID}"
    # a pick is not a new turn: exactly one turn was ever opened
    assert len(_audit(event="turn_start")) == 1
    assert _audit(event="turn_end")[0]["final_status"] == "completed"


@pytest.mark.asyncio
async def test_db1_non_pending_tool_result_is_dropped_silently(
    client, p3_upstream
):
    """Acceptance #3 (negative half): a pick this relay is not waiting on —
    stale replay, forged id, pick after the wait was killed — never reaches
    the engine, opens no turn and leaves no audit row."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(_card_frame())

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "tool_call"]

    stale = dict(_pick_frame(), tool_call_id="tc-somebody-elses")
    await ws.send_json(stale)
    await _assert_quiet(ws, timeout=0.5)
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert [f["type"] for f in sent] == ["message"]
    assert _audit(event="tool_result") == []
    assert len(_audit(event="turn_start")) == 1


# ---------------------------------------------------------------------------
# #4 — the clarify budget closes the wait with its own code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_clarify_timeout_is_not_an_idle_kill(
    client, p3_upstream, monkeypatch
):
    """Acceptance #4: when the budget expires the child gets
    ERR_CLARIFY_TIMEOUT (so the card can fall to its timeout state and the
    clarify banner show), and the ledger records clarify_timeout — never
    idle_timeout, which would blame a silent engine that never went silent."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "0.4")
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "30")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(_card_frame())

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)

    events = await _collect(ws, 3, timeout=6.0)
    assert [e["type"] for e in events] == ["session", "tool_call", "error"]
    assert events[2]["error_code"] == "ERR_CLARIFY_TIMEOUT"
    await ws.close()

    kills = _audit(event="clarify_timeout")
    assert len(kills) == 1
    assert kills[0]["upstream_error"] == "clarify_timeout"
    assert kills[0]["detail"] == "clarify_wait>0.4s"
    # the idle watchdog must not claim this kill
    assert _audit(event="watchdog_kill") == []
    end = _audit(event="turn_end")[0]
    assert end["final_status"] == "failed"
    assert end["upstream_error"] == "clarify_timeout"


# ---------------------------------------------------------------------------
# #5 — replay carries the card and the engine's terminal result frame (R5 β)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_replay_carries_card_and_result(client, p3_upstream):
    """Acceptance #5 / R5 β (7a): a child that refreshes after the turn gets
    the card, the answer text and the engine's terminal `result` frame back
    from relay memory, in arrival order — no engine dial, and the pick is
    neither replayed nor re-sent upstream."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "tool_result":
            await ws.send_json(
                {"type": "content", "content": "好嘅，我哋由數學開始。",
                 "session_id": _SID}
            )
            await ws.send_json(
                {"type": "result", "session_id": _SID, "turn_id": _TURN_ID,
                 "seq": 3, "metadata": {"status": "ok"}}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame())
    await _collect(ws, 3)

    await ws.send_json({"type": "subscribe_session", "session_id": _SID})
    replay = await _collect(ws, 4)
    assert [e["type"] for e in replay] == [
        "tool_call",
        "content",
        "result",
        "done",
    ]
    assert replay[0] == _card_frame()
    assert replay[1]["content"] == "好嘅，我哋由數學開始。"
    assert replay[2]["metadata"] == {"status": "ok"}
    # the pick is a client→engine frame: the child side has no consumer for it
    assert all(e["type"] != "tool_result" for e in replay)
    await ws.close()

    # the replay is local: the engine never saw the subscribe, and the pick
    # travelled upstream exactly once
    sent = [f["frame"]["type"] for f in p3_upstream.frames]
    assert sent == ["message", "tool_result"]


# ---------------------------------------------------------------------------
# #6 — 紅線 8: mask only, never the student id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_audit_rows_stay_mask_only(client, p3_upstream, monkeypatch):
    """Acceptance #6 (紅線 8): the new events write the 8-char mask like every
    other row — the full student id never appears anywhere in the ledger."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "0.4")

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "tool_result":
            await ws.send_json(_card_frame())  # a second card, then silence

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame())
    # second card opens a fresh wait, which then times out
    events = await _collect(ws, 2, timeout=6.0)
    assert [e["type"] for e in events] == ["tool_call", "error"]
    assert events[1]["error_code"] == "ERR_CLARIFY_TIMEOUT"
    await ws.close()

    rows = _audit()
    assert {r["event"] for r in rows} >= {
        "turn_start",
        "tool_call",
        "tool_result",
        "clarify_timeout",
        "turn_end",
    }
    for row in rows:
        assert row["student_mask"] == student_id[:8]
        assert len(row["student_mask"]) == 8
        # no field anywhere may carry the full id
        assert student_id not in json.dumps(dict(row), ensure_ascii=False)
