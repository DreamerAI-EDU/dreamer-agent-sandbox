"""PR-D-b1 / PR-D-b4 PR-1 — relay-side clarification-card contract (§A.5).

The backend half of the clarification card: the relay must bridge the engine's
card to the child, park the turn on the child's answer, resume that turn on the
*same* turn, and close the wait with its own error code — never as an idle
engine.

Covered here (acceptance #1–#6 of §6.2, the D-b1 subset):
    1. `tool_call` reaches the child as the frontend contract (id mapped in,
       option ids minted) and is audited once
    2. a turn parked on a card survives the idle watchdog
    3. the pick rides the open turn, translated into `submit_user_reply`;
       a non-pending pick is dropped
    4. the clarify budget closes the wait with ERR_CLARIFY_TIMEOUT, not idle
    5. replay carries the card *and* the pick (R5 β)
    6. every audit row stays mask-only (紅線 8)

PR-D-b4 PR-1 closes F-b4-6 on top of that (design v0.2.1 §A.2 F2 / §4.1):
    T-01   the id is mapped out of `metadata`, never minted
    T-01b  the engine gets `submit_user_reply` + `turn_id`, never `tool_result`
    T-02   the provider id wins over the trace id
    T-03   no id anywhere → forwarded as-is, nothing minted
    T-13   option ids are minted `opt_1…opt_N` and the labels stay in sync
    T-14   the pick comes back as *labels* (plus free text), never as ids
    T-15   an unmapped option id is dropped, audited, never guessed at
    T-12   the enriched card is still `tool_call`, so it still replays
    G-01   nothing this relay does ever names one of the 4 residual rows

PR-D-b4 PR-2 closes B4-2 on top of that (design v0.2 §5.1/§5.4, gate D-3 甲):
    T-11   an upstream `tool_result` is intercepted relay-side and audited;
           the child never sees it
    T-10   the engine keeps emitting its own `tool_result` (N-2) — the relay
           is the one that classifies it; the child still gets only the card
    T-12   `content` / `tool_call` / `result` still ride the open turn and
           still replay; the replay key set is untouched (gate condition)

PR-D-b4 PR-3 closes B4-3 on top of that (design v0.2 §6.1/§6.4, gate §3i):
    T-04   the clarify budget expiring on a parked turn cancels that turn
           upstream, by id, and still closes the wait as a clarify kill
    T-04b  that cancel rides the connection already open — it goes out before
           the relay drops its socket, and nothing re-dials for it
    T-04c  an idle kill is not a cancel (the engine's own turn stays its own)
    T-07   the reap cancels only a turn the engine is *holding*: all three
           teardown callers share the one gate, a streaming turn sends nothing
    T-07b  no live socket → no cancel, and above all no fresh dial for one
    G-02   the trigger is not a janitor: cancels name only turns this
           connection opened, no session sweep, no turn-status write

PR-D-b4 PR-4 closes B4-4 on top of that (design v0.2 §7, gate §3j) — the last
relay PR. The clarify timeout is self-healing within one connection: the turn
the relay cancelled is remembered, so the `session_busy` that meets the child's
next question is recognised as that leftover rather than as a second tab.
    T-08   after the cancel, the same student's next turn on the same
           connection is not busy-locked: the cancel is re-sent for the id
           this connection opened, `busy_after_cancel` is audited, and the
           child gets the retryable copy
    T-09   a busy with nothing of ours pending is still true concurrency: the
           P4 non-retryable semantics are not weakened (no re-cancel, no
           `busy_after_cancel` row, the original copy)
    G-01   the retried ids are a subset of this connection's own cancel set,
           and that set never contains one of the 4 residual rows
    G-02   the self-heal is a retry of our own cancel, not a janitor: no
           session sweep, no turn-status write, no residual row named

The upstream is the same scripted stand-in the P3/P4 suites use, wired into
`ws_chat._upstream_ws_url`, so no real DeepTutor is needed.
"""

from __future__ import annotations

import asyncio
import collections
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
_CALL_ID = "call-xyz-001"  # the trace-side id: only the T-01 fallback
_TURN_ID = "turn-clarify-001"

#: the four `running` rows the D3 window left behind (D3_window_report §7).
#: 紅線 1 — no PR of this series may reap them, so no test may either: G-01
#: asserts the relay never so much as *names* one of them (G-02, which adds
#: the cancel/status half of that guard, ships with PR-3/PR-4).
_RESIDUAL_RUNNING_TURN_IDS = (
    "turn_1789805286986_8ceb544b05",
    "turn_1789823910953_50c861e378",
    "turn_1789827929607_6e48b23116",
    "turn_1790249010368_9ab1fd387c",
)


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


def _card_frame(
    *,
    tool_call_id: str | None = _TCID,
    call_id: str | None = _CALL_ID,
    options: list | None = None,
    allow_free_text: bool | None = True,
    multi_select: bool = False,
) -> dict:
    """The clarification card in the engine's *real* shape (design §4.6, read
    off the deployed image): the call id rides in `metadata` (never at the top
    level, B4-1), the question and its options ride in `args.questions[0]`, and
    an option carries no id at all — those are minted relay-side for the
    frontend contract (T-13)."""
    meta: dict = {
        "args": {
            "questions": [
                {
                    "id": "q-1",
                    "prompt": "你想問邊樣？",
                    "allow_free_text": allow_free_text,
                    "multi_select": multi_select,
                    "options": (
                        options
                        if options is not None
                        else [{"label": "數學"}, {"label": "科學"}]
                    ),
                }
            ]
        }
    }
    if tool_call_id is not None:
        meta["tool_call_id"] = tool_call_id
    if call_id is not None:
        meta["call_id"] = call_id
    return {
        "type": "tool_call",
        "session_id": _SID,
        "turn_id": _TURN_ID,
        "metadata": meta,
    }


def _pick_frame(option_ids: list | None = None, free_text: str = "") -> dict:
    """The pick as the frontend actually sends it (`chatWs.ts:65` /
    `ChatPage.tsx:253`): the option ids it was handed, plus whatever the child
    typed in the free-text box."""
    return {
        "type": "tool_result",
        "tool_call_id": _TCID,
        "session_id": _SID,
        "result": {
            "selected": ["opt_1"] if option_ids is None else list(option_ids),
            "free_text": free_text,
        },
    }


async def _start_turn(ws) -> None:
    await ws.send_json(
        {"type": "message", "capability": "chat", "message": "我想學數學"}
    )


# ---------------------------------------------------------------------------
# #1 — tool_call reaches the child as the frontend contract, audited once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db1_tool_call_reaches_the_child_as_the_frontend_contract(
    client, p3_upstream
):
    """Acceptance #1 / PR-1 (T-01, T-02, T-13): the card the child gets is the
    frontend contract — the engine's call id mapped to the top level, its option
    ids minted `opt_1…opt_N` — and it leaves one audit row naming the id and the
    level it was read from. The turn stays open."""
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
    out = events[1]
    # mapped, never minted: the id is the engine's own, lifted out of metadata
    assert out["tool_call_id"] == _TCID
    assert out["status"] == "awaiting_input"
    # the contract the card renderer needs — `normalizeClarifyOptions` drops
    # every option without an id, so the relay mints them (F-b4-6(b)/(c))
    assert out["tool_args"] == {
        "question": "你想問邊樣？",
        "options": [
            {"id": "opt_1", "label": "數學", "description": None},
            {"id": "opt_2", "label": "科學", "description": None},
        ],
        "allow_free_text": True,
        "multi_select": False,
    }
    # the card does not end the turn: no turn_end yet, and no kill of any kind
    assert _audit(event="turn_end") == []
    assert _audit(event="watchdog_kill") == []
    assert _audit(event="clarify_timeout") == []
    await ws.close()

    calls = _audit(event="tool_call")
    assert len(calls) == 1
    assert calls[0]["student_mask"] == student_id[:8]
    assert calls[0]["session_id"] == _SID
    assert (
        calls[0]["detail"]
        == f"tool_call_id={_TCID} id_source=metadata.tool_call_id"
    )
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
    """Acceptance #3 / PR-1 (T-01b, T-14): the pick is answered on the *same*
    turn (one turn_start in the ledger) and the engine's answer still reaches
    the child — but what travels upstream is the translated resume frame, never
    the child's `tool_result`, and the pick is audited once."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
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

    # the engine saw the translated pick, on the same connection, after the card
    sent = [f["frame"] for f in p3_upstream.frames]
    assert [f["type"] for f in sent] == ["message", "submit_user_reply"]
    assert sent[1]["turn_id"] == _TURN_ID
    assert sent[1]["answers"] == [{"questionId": "q-1", "text": "數學"}]
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
    neither replayed nor re-sent upstream. The card it gets back is the
    enriched one (PR-1), so a refresh still renders options."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
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
    assert replay[0]["tool_call_id"] == _TCID
    assert [o["id"] for o in replay[0]["tool_args"]["options"]] == [
        "opt_1",
        "opt_2",
    ]
    assert replay[1]["content"] == "好嘅，我哋由數學開始。"
    assert replay[2]["metadata"] == {"status": "ok"}
    # the pick is a client→engine frame: the child side has no consumer for it
    assert all(e["type"] != "tool_result" for e in replay)
    await ws.close()

    # the replay is local: the engine never saw the subscribe, and the pick
    # travelled upstream exactly once — as the translated resume frame
    sent = [f["frame"]["type"] for f in p3_upstream.frames]
    assert sent == ["message", "submit_user_reply"]


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
        elif frame.get("type") == "submit_user_reply":
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


# ---------------------------------------------------------------------------
# PR-1 (design v0.2.1 §4.1/§4.4) — the id map, the option mint, the pick
# translation. Every case is a scripted-upstream contract test: no engine, no
# raw-frame capture (C-b4-4).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pr1_t01_id_is_mapped_from_call_id_when_trace_id_is_absent(
    client, p3_upstream
):
    """T-01 (§8.4): `metadata.tool_call_id` empty, `metadata.call_id` set → the
    contract frame carries that value, mapped and never minted, and the audit
    says which level it came from. The value only feeds rendering + the pending
    association; the resume itself rides `turn_id`."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = _card_frame(tool_call_id=None, call_id=_CALL_ID)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(card)

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert events[1]["tool_call_id"] == _CALL_ID
    await ws.close()

    row = _audit(event="tool_call")[0]
    assert row["detail"] == f"tool_call_id={_CALL_ID} id_source=metadata.call_id"


@pytest.mark.asyncio
async def test_pr1_t02_the_provider_id_wins_over_the_trace_id(
    client, p3_upstream
):
    """T-02 (§8.4): both ids present → `metadata.tool_call_id` is the one the
    engine matches its pick against, so it wins over `metadata.call_id`."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(_card_frame())  # both ids on the card

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert events[1]["tool_call_id"] == _TCID
    assert events[1]["tool_call_id"] != _CALL_ID
    await ws.close()

    row = _audit(event="tool_call")[0]
    assert (
        row["detail"] == f"tool_call_id={_TCID} id_source=metadata.tool_call_id"
    )


@pytest.mark.asyncio
async def test_pr1_t03_no_id_anywhere_is_forwarded_untouched(
    client, p3_upstream
):
    """T-03 (§8.4): no id at any level → the frame goes out exactly as the
    engine sent it (nothing minted, no `tool_args` invented), the ledger records
    `id_source=missing`, and no empty id is parked on the turn."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = _card_frame(tool_call_id=None, call_id=None)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(card)

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert events[1] == card

    # nothing was parked, so a pick cannot match anything: it never travels
    await ws.send_json(_pick_frame())
    await _assert_quiet(ws, timeout=0.4)
    await ws.close()

    row = _audit(event="tool_call")[0]
    assert row["detail"] == "tool_call_id= id_source=missing"
    assert [f["frame"]["type"] for f in p3_upstream.frames] == ["message"]
    assert _audit(event="tool_result") == []


@pytest.mark.asyncio
async def test_pr1_t01b_engine_gets_a_resume_never_a_tool_result(
    client, p3_upstream
):
    """T-01b (§8.4, N-1): the pick is translated into the engine's own resume
    frame — `submit_user_reply` keyed by `turn_id` and the question id — and the
    child's raw `tool_result` is never forwarded (U-3: the resume does not ride
    the call id)."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame())
    await _collect(ws, 2)
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert [f["type"] for f in sent] == ["message", "submit_user_reply"]
    assert "tool_result" not in [f["type"] for f in sent]
    assert sent[1]["turn_id"] == _TURN_ID
    assert sent[1]["answers"][0]["questionId"] == "q-1"
    # the resume is turn-keyed: it carries no call id of its own
    assert "tool_call_id" not in sent[1]


@pytest.mark.asyncio
async def test_pr1_t13_option_ids_are_minted_positionally(
    client, p3_upstream
):
    """T-13 (§8.4, F-b4-6(b)/(c)): the engine's options carry no id at all, so
    the relay mints `opt_1…opt_N` in place order for the frontend contract,
    keeps every label, and copies `allow_free_text` / `multi_select` through.
    The id→label sync itself is observed end-to-end in T-14."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = _card_frame(
        options=[
            {"label": "數學"},
            {"label": "科學", "description": "STEM"},
            {"label": "   "},  # blank labels are not options
        ],
        allow_free_text=False,
        multi_select=True,
    )

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(card)

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    out = events[1]
    await ws.close()

    assert out["tool_args"] == {
        "question": "你想問邊樣？",
        "options": [
            {"id": "opt_1", "label": "數學", "description": None},
            {"id": "opt_2", "label": "科學", "description": "STEM"},
        ],
        "allow_free_text": False,
        "multi_select": True,
    }
    assert out["status"] == "awaiting_input"


@pytest.mark.asyncio
async def test_pr1_t13_legacy_flat_args_still_flatten(client, p3_upstream):
    """T-13 (§8.4) safety net: the older flat `ask_user` payload — no `questions`
    list, no question id — still mints its option ids. With no question id to
    key on, the resume rides the plain `text` field instead of `answers`."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = {
        "type": "tool_call",
        "session_id": _SID,
        "turn_id": _TURN_ID,
        "metadata": {
            "tool_call_id": _TCID,
            "args": {
                "question": "你想問邊樣？",
                "options": [{"label": "數學"}, {"label": "科學"}],
            },
        },
    }

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(card)
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert [o["id"] for o in events[1]["tool_args"]["options"]] == [
        "opt_1",
        "opt_2",
    ]
    assert events[1]["tool_args"]["question"] == "你想問邊樣？"

    await ws.send_json(_pick_frame(["opt_2"]))
    await _collect(ws, 1)
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert sent[1]["type"] == "submit_user_reply"
    assert sent[1]["text"] == "科學"
    assert "answers" not in sent[1]


@pytest.mark.parametrize(
    "question_level,args_level,expected",
    [
        (False, None, False),  # the engine's per-question value is authoritative
        (True, False, True),  # ... and it beats a stray args-level value (W-b4-1)
        (None, False, False),  # legacy flat payload: the args level still counts
        (None, None, True),  # neither → the engine's own default
    ],
)
@pytest.mark.asyncio
async def test_pr1_w_b4_1_allow_free_text_follows_the_question_level(
    client, p3_upstream, question_level, args_level, expected
):
    """W-b4-1 (§4.2 B, corrected against the engine): `ask_user` keeps
    `allow_free_text` on the *question* (`tools/ask_user.py`), so that level
    wins; the payload root is only the legacy fallback, and `True` is the
    engine's default when neither is set."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    card = _card_frame(allow_free_text=question_level)
    if question_level is None:
        card["metadata"]["args"]["questions"][0].pop("allow_free_text")
    if args_level is not None:
        card["metadata"]["args"]["allow_free_text"] = args_level

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(card)

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    await ws.close()

    assert events[1]["tool_args"]["allow_free_text"] is expected


@pytest.mark.asyncio
async def test_pr1_t14_pick_is_translated_to_labels_plus_free_text(
    client, p3_upstream
):
    """T-14 (§8.4, F-b4-6(d)): the child answers `opt_2` — an id the engine has
    never seen — so the relay maps it back to the label and folds in whatever
    was typed, before resuming the turn."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame(["opt_2"], free_text="想學多啲"))
    tail = await _collect(ws, 2)
    assert [e["type"] for e in tail] == ["content", "done"]
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert sent[1]["type"] == "submit_user_reply"
    assert sent[1]["answers"] == [
        {"questionId": "q-1", "text": "科學、想學多啲"}
    ]
    # the engine gets the label it knows, never the relay's private id
    assert "opt_2" not in sent[1]["answers"][0]["text"]
    assert _audit(event=relay_audit_mod.EVENT_UNMAPPED_PICK) == []


@pytest.mark.asyncio
async def test_pr1_t15_unknown_pick_id_is_dropped_and_audited(
    client, p3_upstream
):
    """T-15 (§8.4, F-b4-6(d)): an id the relay never minted is dropped, the
    payload stays legal (the turn still resumes) and the ledger records the
    unmapped pick."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame(["opt_9", "opt_1"]))
    await _collect(ws, 1)
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert sent[1]["type"] == "submit_user_reply"
    # the known id still lands; only the stranger is dropped
    assert sent[1]["answers"] == [{"questionId": "q-1", "text": "數學"}]

    assert relay_audit_mod.EVENT_UNMAPPED_PICK == "unmapped_pick"
    rows = _audit(event=relay_audit_mod.EVENT_UNMAPPED_PICK)
    assert len(rows) == 1
    assert rows[0]["detail"] == "ids=opt_9"
    assert rows[0]["student_mask"] == student_id[:8]


@pytest.mark.asyncio
async def test_pr1_t15b_empty_pick_still_sends_a_legal_reply(
    client, p3_upstream
):
    """T-15 (§8.4) second half: an empty `selected` is not an error — the turn
    resumes with an empty answer and nothing is logged as unmapped."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await ws.send_json(_pick_frame([]))
    await _collect(ws, 1)
    await ws.close()

    sent = [f["frame"] for f in p3_upstream.frames]
    assert sent[1]["type"] == "submit_user_reply"
    assert sent[1]["answers"] == [{"questionId": "q-1", "text": ""}]
    assert _audit(event=relay_audit_mod.EVENT_UNMAPPED_PICK) == []


@pytest.mark.asyncio
async def test_pr1_t12_enriched_card_stays_replayable(client, p3_upstream):
    """T-12 (§4.4): enrichment rewrites the card before it is forwarded — the id
    lifted to the top level, the option ids minted — but the frame is still a
    `tool_call`, so it still belongs to the replay set and a refresh after the
    turn still renders the card (options and all) without dialling the engine.
    The replay key sets themselves are untouched by PR-1."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    live = (await _collect(ws, 2))[1]
    # enriched, yet still the one frame type the replay cache keys off
    assert live["type"] == "tool_call"
    assert live["type"] in ws_chat_mod._REPLAYABLE_FRAME_TYPES
    assert live["tool_call_id"] == _TCID

    await ws.send_json(_pick_frame())
    await _collect(ws, 2)

    # the completed turn replays the *enriched* card, not the engine's raw one
    await ws.send_json({"type": "subscribe_session", "session_id": _SID})
    replayed = (await _collect(ws, 3))[0]
    assert replayed["type"] == "tool_call"
    assert replayed["tool_call_id"] == _TCID
    assert replayed["status"] == "awaiting_input"
    assert [o["id"] for o in replayed["tool_args"]["options"]] == [
        "opt_1",
        "opt_2",
    ]
    await ws.close()

    # the replay is local: one dial, and the engine only ever saw the turn and
    # the translated resume — never a second `message`, never a `tool_result`
    assert p3_upstream.connections == 1
    assert [f["frame"]["type"] for f in p3_upstream.frames] == [
        "message",
        "submit_user_reply",
    ]
    # the gate's added condition: PR-1 changes no replay key set
    assert ws_chat_mod._REPLAYABLE_FRAME_TYPES == (
        "content",
        "tool_call",
        "result",
    )
    assert "tool_result" not in ws_chat_mod._REPLAYABLE_FRAME_TYPES
    assert ws_chat_mod._INTERACTIVE_FRAME_TYPES == ("tool_call",)


@pytest.mark.asyncio
async def test_pr1_g01_no_residual_turn_is_ever_touched(
    client, p3_upstream, monkeypatch
):
    """G-01 (§4.4, 紅線 1): the four `running` rows D3 left behind are not this
    PR's business. Every DB statement the relay runs during a full card→pick→
    resume cycle is recorded, and neither those statements, nor the frames it
    sends upstream, nor its ledger may name one of them — and PR-1 carries no
    cancel frame and no turn-status write at all — and PR-3, which does give the
    relay a cancel path, may still only ever name this connection's own turn."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    statements: list[str] = []
    real_connect = auth_db.connect

    def recording_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(auth_db, "connect", recording_connect)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    # a mapped pick plus a stranger: both the happy and the drop path run here
    await ws.send_json(_pick_frame(["opt_1", "opt_9"]))
    await _collect(ws, 1)
    await ws.close()

    assert statements, "the recorder captured no DB traffic at all"
    for rid in _RESIDUAL_RUNNING_TURN_IDS:
        assert not any(rid in sql for sql in statements), rid
        assert rid not in json.dumps(
            [f["frame"] for f in p3_upstream.frames], ensure_ascii=False
        ), rid
        assert rid not in json.dumps(_audit(), ensure_ascii=False), rid

    # PR-3 gives the relay a cancel path (B4-3) — what stays forbidden is
    # naming a turn that is not this connection's own. The four residual rows
    # are still off limits, and nothing here writes a turn status.
    cancels = [
        f["frame"]
        for f in p3_upstream.frames
        if f["frame"]["type"] == "cancel_turn"
    ]
    assert all(c["turn_id"] == _TURN_ID for c in cancels)
    assert not set(c["turn_id"] for c in cancels) & set(_RESIDUAL_RUNNING_TURN_IDS)
    assert not any("turn_status" in sql.lower() for sql in statements)


# ---------------------------------------------------------------------------
# PR-2 (design v0.2 §5.1/§5.4) — the engine's non-contract frame is classified
# relay-side: intercepted, audited, never forwarded. Same scripted-upstream
# shape as the PR-1 block (C-b4-4: no engine, no raw-frame capture).
# ---------------------------------------------------------------------------

def _engine_tool_result_frame(
    *, trace_kind: str | None = "tool_result", tool_call_id: str | None = _TCID
) -> dict:
    """The engine's own `tool_result` emit (`tool_dispatch.py:547-554`) in the
    shape N-2 read off the deployed image: a trace / panel frame that, for
    `ask_user`, also carries the engine UI's card payload. It is *not* in the
    Dreamer frontend contract — the card the child must see travels on the
    `tool_call` frame instead."""
    meta: dict = {"tool_metadata": {"ask_user": {"intro": "你想問邊樣？"}}}
    if trace_kind is not None:
        meta["trace_kind"] = trace_kind
    if tool_call_id is not None:
        meta["tool_call_id"] = tool_call_id
    return {
        "type": "tool_result",
        "session_id": _SID,
        "turn_id": _TURN_ID,
        "metadata": meta,
    }


@pytest.mark.asyncio
async def test_pr2_t11_upstream_tool_result_is_intercepted_not_forwarded(
    client, p3_upstream
):
    """T-11 (§5.4): an upstream `tool_result` no longer falls through to the
    child. The relay consumes it, writes exactly one `non_contract_frame` row
    naming the frame and its trace kind, and the child's screen stays exactly
    the contract frames — the frame is never re-routed anywhere else either."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_engine_tool_result_frame())
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 3)
    assert [e["type"] for e in events] == ["session", "content", "done"]
    await ws.close()

    rows = _audit(event="non_contract_frame")
    assert len(rows) == 1
    assert rows[0]["detail"] == "frame=tool_result trace_kind=tool_result"
    assert rows[0]["session_id"] == _SID
    assert rows[0]["turn_id"] == _TURN_ID
    # 紅線 8: the new event writes the 8-char mask like every other row
    assert rows[0]["student_mask"] == student_id[:8]
    assert student_id not in json.dumps(dict(rows[0]), ensure_ascii=False)
    # the interception is a classification, not a re-route: the engine saw
    # nothing beyond the turn itself
    assert [f["frame"]["type"] for f in p3_upstream.frames] == ["message"]


@pytest.mark.asyncio
async def test_pr2_t10_engine_keeps_emitting_the_relay_classifies(
    client, p3_upstream
):
    """T-10 (§8.3, revised; N-2): the engine is *not* asked to stop emitting its
    `tool_result` trace frame — it keeps emitting it through the whole
    `ask_user` cycle, and the relay is what classifies it. The child sees the
    card and never the trace frame, and the two directions stay separable in
    the ledger: the engine's frame is a `non_contract_frame` row, the child's
    own pick is still a `tool_result` row."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
            # the engine's own emit, right behind the card it duplicates
            await ws.send_json(_engine_tool_result_frame())
        elif frame.get("type") == "submit_user_reply":
            await ws.send_json(
                {"type": "content", "content": "好嘅。", "session_id": _SID}
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    live = await _collect(ws, 2)
    assert [e["type"] for e in live] == ["session", "tool_call"]
    assert live[1]["tool_call_id"] == _TCID
    # the engine's frame arrived between the card and the pick: the child
    # waited for its own answer and got none of it
    await _assert_quiet(ws, timeout=0.4)

    await ws.send_json(_pick_frame())
    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["content", "done"]
    await ws.close()

    non_contract = _audit(event="non_contract_frame")
    assert len(non_contract) == 1
    assert non_contract[0]["detail"] == "frame=tool_result trace_kind=tool_result"
    picks = _audit(event="tool_result")
    assert len(picks) == 1
    assert picks[0]["detail"] == f"tool_call_id={_TCID}"
    # the cycle still runs end to end on the engine's own resume channel
    assert [f["frame"]["type"] for f in p3_upstream.frames] == [
        "message",
        "submit_user_reply",
    ]
    assert _audit(event="turn_end")[-1]["final_status"] == "completed"


@pytest.mark.asyncio
async def test_pr2_t12_contract_frames_still_ride_the_open_turn(
    client, p3_upstream
):
    """T-12 (§5.4, gate condition): the interception is scoped to `tool_result`
    only. `content` / `tool_call` / `result` still reach the child unchanged and
    still replay after the turn, the replay key set is untouched, and no
    contract frame leaves a `non_contract_frame` row."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(
                {"type": "content", "content": "第一步。", "session_id": _SID}
            )
            await ws.send_json(_card_frame())
            await ws.send_json(
                {
                    "type": "result",
                    "session_id": _SID,
                    "turn_id": _TURN_ID,
                    "content": "完成。",
                }
            )
            await ws.send_json(
                {"type": "done", "turn_id": _TURN_ID, "session_id": _SID}
            )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    live = await _collect(ws, 5)
    assert [e["type"] for e in live] == [
        "session",
        "content",
        "tool_call",
        "result",
        "done",
    ]
    assert live[2]["tool_call_id"] == _TCID

    # all three contract frames were cached, so the completed turn replays
    await ws.send_json({"type": "subscribe_session", "session_id": _SID})
    replayed = await _collect(ws, 4)
    assert [e["type"] for e in replayed] == [
        "content",
        "tool_call",
        "result",
        "done",
    ]
    await ws.close()

    # the gate's added condition: PR-2 changes no replay key set
    assert ws_chat_mod._REPLAYABLE_FRAME_TYPES == (
        "content",
        "tool_call",
        "result",
    )
    assert "tool_result" not in ws_chat_mod._REPLAYABLE_FRAME_TYPES
    # no false positive: nothing contract-shaped was classified as non-contract
    assert _audit(event="non_contract_frame") == []


# ---------------------------------------------------------------------------
# PR-3 (design v0.2 §6.1/§6.4, F-b4-7) — the relay asks the engine to finish a
# turn the engine is *holding*: the clarify budget and the teardown reap both
# cancel on the connection that is already open, the idle branch and a merely
# streaming reap both stay silent, and no cancel ever names a turn this
# connection did not open. Same scripted upstream as the rest of the file
# (C-b4-4: no engine, no raw-frame capture).
# ---------------------------------------------------------------------------

def _cancel_frames(controller: _ScriptedUpstream) -> list[dict]:
    return [
        f["frame"]
        for f in controller.frames
        if f["frame"].get("type") == "cancel_turn"
    ]


async def _wait_for_cancel(controller: _ScriptedUpstream) -> list[dict]:
    """Wait for the cancel to land, then return it.

    `_send_upstream` writes the frame and returns; the scripted upstream only
    reads it on a later loop turn. Every assertion about a cancel that was sent
    while a connection was being torn down (client close, watchdog kill) has to
    wait for it rather than race the scheduler.
    """
    await _wait_for(lambda: bool(_cancel_frames(controller)))
    return _cancel_frames(controller)


class _ScriptedSocket:
    """The bit of `aiohttp.ClientWebSocketResponse` `_send_upstream` touches."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send_str(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


class _RelaySeam:
    """A `self` just rich enough to call the PR-3 seams directly.

    The third teardown caller (`relay_teardown`, from `run()`) cannot be
    reached with a live socket in a scripted run: by the time `run()` reaps,
    `_socket_lost` / `_midstream_error` have already cleared `_upstream`
    (ws_chat.py:1781-1806). The shared gate is asserted here instead — the real
    `_reap_turn` / `_send_upstream_cancel`, over a scripted socket, with the
    dial counted exactly where `_ensure_upstream` would dial
    (ws_chat.py:770-783).
    """

    _reap_turn = ws_chat_mod._ChatRelay._reap_turn
    _finish_turn = ws_chat_mod._ChatRelay._finish_turn
    _send_upstream = ws_chat_mod._ChatRelay._send_upstream

    student_mask = "seam0001"

    def __init__(self, upstream, turn=None) -> None:
        self._upstream = upstream
        self._turn = turn
        self.dials = 0
        # PR-4: the two relay-level fields `_send_upstream_cancel` now touches
        # when its frame goes out. Same values the real `_ChatRelay` starts
        # with, so the seam keeps exercising the real helper.
        self.self_cancelled_turn_ids: set = set()
        self._self_cancelled_order = collections.deque()

    async def _send_upstream_cancel(self, turn) -> None:
        # looked up at call time, not at import time: on the pre-PR-3 tree the
        # method does not exist, and this has to surface as a failing test
        # rather than as a collection error that hides every other test
        await ws_chat_mod._ChatRelay._send_upstream_cancel(self, turn)

    def _remember_self_cancelled(self, turn_id: str) -> None:
        # same reason as the cancel seam above: PR-4 added this call inside
        # `_send_upstream_cancel`, so it must not be resolved at import time
        ws_chat_mod._ChatRelay._remember_self_cancelled(self, turn_id)

    async def _ensure_upstream(self) -> bool:
        if self._upstream is not None and not self._upstream.closed:
            return True
        self.dials += 1  # a real `_ensure_upstream` would dial here
        return False

    def _arm_recycle(self) -> None:  # not this seam's subject
        return None


def _seam_turn(*, parked: bool) -> object:
    turn = ws_chat_mod._TurnInFlight("{}", "zh-hk", "seam0001")
    turn.session_id = _SID
    turn.turn_id = _TURN_ID
    turn.awaiting_tool_result = parked
    return turn


@pytest.mark.asyncio
async def test_pr3_t04_clarify_timeout_cancels_the_held_turn(
    client, p3_upstream, monkeypatch
):
    """T-04 (§6.4): the clarify budget expires while the turn is parked — the
    relay tells the engine to finish that turn. Without it the engine row keeps
    `running` with a live task, which is what refuses the same student's next
    turn with `session_busy`."""
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

    # the engine was told to finish the turn it is holding, by id
    assert [c["turn_id"] for c in await _wait_for_cancel(p3_upstream)] == [_TURN_ID]
    rows = _audit(event="cancel_sent")
    assert len(rows) == 1
    assert rows[0]["turn_id"] == _TURN_ID
    assert rows[0]["detail"] == "ok=True"
    # and the local close-out is still the clarify kill, not an idle one
    assert _audit(event="clarify_timeout")[0]["upstream_error"] == "clarify_timeout"
    assert _audit(event="watchdog_kill") == []
    end = _audit(event="turn_end")[0]
    assert end["final_status"] == "failed"
    assert end["upstream_error"] == "clarify_timeout"


@pytest.mark.asyncio
async def test_pr3_t04b_the_cancel_rides_the_original_connection(
    client, p3_upstream, monkeypatch
):
    """T-04b (§6.4, F-b4-7(c)): the cancel goes out *before* the relay drops its
    own socket, so it travels on the connection the engine already bound the
    turn to and nothing re-dials for it. (Had it been sent after
    `self._upstream = None`, the helper's guard would have returned and no
    frame would exist at all — the frame on connection #1 *is* the ordering
    proof.) It is also the last thing the engine hears from this relay."""
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
    await _collect(ws, 3, timeout=6.0)
    await ws.close()

    await _wait_for_cancel(p3_upstream)
    assert [f["conn"] for f in p3_upstream.frames
            if f["frame"]["type"] == "cancel_turn"] == [1]
    assert p3_upstream.connections == 1  # never a fresh dial for a cancel
    assert p3_upstream.frames[-1]["frame"]["type"] == "cancel_turn"


@pytest.mark.asyncio
async def test_pr3_t04c_the_idle_kill_cancels_nothing(
    client, p3_upstream, monkeypatch
):
    """T-04c (§6.4, F-b4-7(b)): an idle kill is not a cancel. The engine went
    quiet on a turn of its own — the relay has no business ending that turn, and
    must not reach for the cancel path it now owns."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "0.4")
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "30")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        # then silence: not parked, so this is the idle watchdog's call

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2, timeout=6.0)
    assert [e["type"] for e in events] == ["session", "error"]
    await ws.close()

    assert len(_audit(event="watchdog_kill")) == 1
    assert _audit(event="clarify_timeout") == []
    await asyncio.sleep(0.2)  # let any stray frame land before asserting none
    assert _cancel_frames(p3_upstream) == []
    assert _audit(event="cancel_sent") == []


@pytest.mark.asyncio
async def test_pr3_t07a_client_closed_cancels_the_held_turn(
    client, p3_upstream
):
    """T-07 ① (`client_closed`): the child leaves while its turn is parked on a
    card — the engine is still holding that turn, so the reap asks it to finish
    on the socket that is already open."""
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
    await ws.close()

    assert await _wait_for(lambda: bool(_audit(event="turn_end")))
    end = _audit(event="turn_end")[0]
    assert end["detail"] == "client_closed"
    assert end["final_status"] == "aborted"

    # a frame written as the relay is tearing down is only picked up by the
    # scripted upstream on a later loop turn: wait for it, don't race it
    assert [c["turn_id"] for c in await _wait_for_cancel(p3_upstream)] == [_TURN_ID]
    assert p3_upstream.connections == 1
    rows = _audit(event="cancel_sent")
    assert len(rows) == 1
    assert rows[0]["detail"] == "ok=True"


@pytest.mark.asyncio
async def test_pr3_t07a_superseded_turn_is_cancelled_before_the_new_one(
    client, p3_upstream
):
    """T-07 ① (`superseded_by_new_turn`): the child opens a new turn while the
    old one is still parked. The parked turn is cancelled upstream *first*, and
    only then does the new turn's frame go out — the engine is never left
    holding two turns for one student."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        frame = p3_upstream.frames[idx]["frame"]
        if frame.get("type") == "message":
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await _start_turn(ws)  # the child talks again without answering the card

    assert await _wait_for(lambda: len(_audit(event="turn_start")) == 2)
    await _wait_for(lambda: len(p3_upstream.frames) >= 3)
    sent = [f["frame"] for f in p3_upstream.frames]
    assert [f["type"] for f in sent] == ["message", "cancel_turn", "message"]
    assert sent[1]["turn_id"] == _TURN_ID
    assert p3_upstream.connections == 1

    ends = _audit(event="turn_end")
    assert [e["detail"] for e in ends] == ["superseded_by_new_turn"]
    assert ends[0]["final_status"] == "aborted"
    assert _audit(event="cancel_sent")[0]["turn_id"] == _TURN_ID
    await ws.close()


@pytest.mark.asyncio
async def test_pr3_t07_reverse_a_streaming_teardown_cancels_nothing(
    client, p3_upstream
):
    """T-07 ② (§6.4, F-b4-7(a)): a turn that is merely streaming has not lost
    its engine task — the answer is still being produced and the child can come
    back to the same connection for it. The reap still closes the relay's own
    turn, and sends nothing upstream."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(
            {"type": "content", "content": "第一步。", "session_id": _SID}
        )
        # then silence: mid-answer, not parked on a card

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "content"]
    await ws.close()

    assert await _wait_for(lambda: bool(_audit(event="turn_end")))
    end = _audit(event="turn_end")[0]
    assert end["detail"] == "client_closed"
    assert end["final_status"] == "aborted"
    await asyncio.sleep(0.2)  # let any stray frame land before asserting none
    assert _cancel_frames(p3_upstream) == []
    assert _audit(event="cancel_sent") == []


@pytest.mark.asyncio
async def test_pr3_t07a_teardown_reap_shares_the_gate(client):
    """T-07 ① (third caller, `relay_teardown`): the gate lives in `_reap_turn`,
    so all three callers go through it. Asserted at the seam — see `_RelaySeam`
    for why this one cannot be scripted with a live socket."""
    socket = _ScriptedSocket()
    seam = _RelaySeam(upstream=socket, turn=_seam_turn(parked=True))

    assert await seam._reap_turn(
        "relay_teardown", relay_audit_mod.ERR_UPSTREAM_CLOSED
    ) is True

    assert socket.sent == [{"type": "cancel_turn", "turn_id": _TURN_ID}]
    rows = _audit(event="cancel_sent")
    assert len(rows) == 1
    assert rows[0]["turn_id"] == _TURN_ID
    assert rows[0]["detail"] == "ok=True"
    end = _audit(event="turn_end")[0]
    assert end["detail"] == "relay_teardown"
    assert end["final_status"] == "aborted"


@pytest.mark.asyncio
async def test_pr3_t07b_a_cancel_never_dials_a_fresh_connection(client):
    """T-07b (§6.4, F-b4-7(c)): with no live socket the helper returns — it must
    not re-dial to deliver a cancel. A cancel on a fresh connection is bound to
    no engine-side turn, so the engine would not honour it; the dial counter
    proves the guard is on the dial, not just on the frame."""
    socket = _ScriptedSocket()
    seam = _RelaySeam(upstream=socket, turn=_seam_turn(parked=True))
    seam._upstream = None  # the socket this turn lived on is already gone

    auth_db.ensure_schema()  # this seam test never touches the relay's DB
    await seam._send_upstream_cancel(seam._turn)

    assert seam.dials == 0
    assert socket.sent == []
    assert _audit(event="cancel_sent") == []


@pytest.mark.asyncio
async def test_pr3_g02_no_turn_state_is_ever_swept(
    client, p3_upstream, monkeypatch
):
    """G-02 (§6.4, 紅線 1): PR-3 adds a cancel *trigger*, not a janitor. The
    relay never scans a session for leftover turns and never writes a turn
    status itself — every cancel it sends names a turn this connection opened,
    and no statement it runs touches turn status. The four residual rows are
    untouched by construction."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "0.4")
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "30")

    statements: list[str] = []
    real_connect = auth_db.connect

    def recording_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(auth_db, "connect", recording_connect)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": _SID})
        await ws.send_json(_card_frame())

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 3, timeout=6.0)  # session, tool_call, clarify error
    await ws.close()

    # a cancel did go out on this run — and it named this connection's own turn
    cancels = await _wait_for_cancel(p3_upstream)
    assert [c["turn_id"] for c in cancels] == [_TURN_ID]
    assert _audit(event="cancel_sent")[0]["turn_id"] == _TURN_ID
    assert statements, "the recorder captured no DB traffic at all"
    for rid in _RESIDUAL_RUNNING_TURN_IDS:
        assert rid not in json.dumps(cancels, ensure_ascii=False), rid
        assert rid not in json.dumps(_audit(), ensure_ascii=False), rid
        assert not any(rid in sql for sql in statements), rid
    lowered = " ".join(statements).lower()
    assert "turn_status" not in lowered
    assert "update turns" not in lowered
    assert "delete from turns" not in lowered


# ---------------------------------------------------------------------------
# PR-4 / B4-4 — the busy that meets our *own* cancel is a leftover, not a tab
# ---------------------------------------------------------------------------

def _busy_frame() -> dict:
    """The engine's refusal, in the shape the deployed image emits it: an
    `error` frame whose wording is matched by `_is_busy_frame` (P4). Built per
    call so no test can hand a mutated frame to the next one."""
    return {
        "type": "error",
        "error_code": "upstream_error",
        "content": "Session already has an active turn",
        "session_id": _SID,
    }


def _relay_state_writes(statements: list[str]) -> list[str]:
    """Statements that touch relay/turn *state*.

    Three kinds of noise are dropped, all of them audit bookkeeping. The relay's
    own audit INSERT is the one write PR-4 is allowed to add. `BEGIN`/`COMMIT`
    are how every connection frames that insert — and `_finish_turn`'s audit row
    lands *after* the child has already been told, so leaving them in would race
    the snapshot below. `PRAGMA` is what `auth_db.connect()` issues on open
    (auditing opens its own connection, so one audit row costs one pragma). What
    is left is what a janitor would need: a read or write against a turn or
    session table.
    """
    out = []
    for statement in statements:
        low = statement.strip().lower()
        if "ws_chat_relay_audit" in low or low.startswith("pragma"):
            continue
        if low in ("begin", "commit", "rollback"):
            continue
        out.append(statement)
    return out


async def _supersede_then_busy(controller: _ScriptedUpstream) -> None:
    """Script the two-message run PR-4 exists for.

    First message: the engine parks the turn on a card (so the turn stays open
    and, on PR-3's path, gets a cancel). Second message: the child asks again
    without answering, which is the one window where the relay is still alive
    to hear what the engine says about the turn it just asked it to finish.
    """
    seen = 0

    async def script(ws, conn, idx):
        nonlocal seen
        if controller.frames[idx]["frame"].get("type") != "message":
            return
        seen += 1
        if seen == 1:
            await ws.send_json({"type": "session", "session_id": _SID})
            await ws.send_json(_card_frame())
        else:
            await ws.send_json(_busy_frame())

    controller.on_message = script


@pytest.mark.asyncio
async def test_pr4_t08_a_busy_after_our_own_cancel_is_retryable(
    client, p3_upstream, monkeypatch
):
    """T-08 (§7, gate §3j): after PR-3 sent the cancel, the `session_busy` that
    meets the child's next turn is that leftover — not a second tab. The relay
    re-sends the cancel for the id *this* connection opened (`cancel_turn` is
    idempotent, so it is safe whether the engine is still working on the first
    one or missed it), audits `busy_after_cancel`, and hands the child the
    retryable copy. The wire code stays `session_busy`: only the copy changes,
    so the frontend contract is untouched."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    # long budgets: the child supersedes the parked turn, the clarify wait must
    # not be the thing that ends it
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "30")
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "30")

    await _supersede_then_busy(p3_upstream)

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    assert [e["type"] for e in await _collect(ws, 2)] == ["session", "tool_call"]

    await _start_turn(ws)  # the child asks again, card still unanswered
    busy = (await _collect(ws, 1, timeout=6.0))[0]

    assert busy["type"] == "error"
    assert busy["error_code"] == "session_busy"  # wire vocabulary unchanged
    assert busy["content"] == ws_chat_mod._BUSY_RETRYABLE_COPY["zh-hk"]
    assert busy["content"] != ws_chat_mod._GRACEFUL_BUSY_COPY["zh-hk"]
    assert "active turn" not in json.dumps(busy)  # provider text never leaks

    # the self-heal rode the socket already open: cancel, new turn, re-cancel —
    # and both cancels name the turn this connection opened
    assert await _wait_for(lambda: len(_cancel_frames(p3_upstream)) == 2)
    assert [f["frame"]["type"] for f in p3_upstream.frames] == [
        "message",
        "cancel_turn",
        "message",
        "cancel_turn",
    ]
    assert [c["turn_id"] for c in _cancel_frames(p3_upstream)] == [
        _TURN_ID,
        _TURN_ID,
    ]
    assert p3_upstream.connections == 1  # never a fresh dial for the re-send

    row = _audit(event="busy_after_cancel")[0]
    assert row["detail"] == "retried=1"
    mid = _audit(event="midstream_error")[0]
    assert mid["upstream_error"] == "session_busy"
    assert mid["detail"] == "busy_after_cancel"
    # the re-send is accounted for by `busy_after_cancel`, not as a second
    # cancel of its own — and busy still spends no retry budget (P4)
    assert len(_audit(event="cancel_sent")) == 1
    assert _audit(event="turn_retry") == []
    await ws.close()


@pytest.mark.asyncio
async def test_pr4_t08b_only_a_delivered_cancel_is_remembered(client):
    """T-08, seam half: the ledger is written where the cancel is *delivered*,
    so it can only ever hold frames the engine actually received — a cancel the
    helper refused to dial (T-07b) leaves nothing to self-heal from. Registering
    is idempotent and the helper is the only writer."""
    socket = _ScriptedSocket()
    seam = _RelaySeam(upstream=socket, turn=_seam_turn(parked=True))

    auth_db.ensure_schema()  # this seam test never touches the relay's DB
    await seam._send_upstream_cancel(seam._turn)

    assert socket.sent == [{"type": "cancel_turn", "turn_id": _TURN_ID}]
    assert seam.self_cancelled_turn_ids == {_TURN_ID}
    assert list(seam._self_cancelled_order) == [_TURN_ID]
    assert _audit(event="cancel_sent")[0]["detail"] == "ok=True"

    await seam._send_upstream_cancel(seam._turn)  # idempotent, no duplicate
    assert list(seam._self_cancelled_order) == [_TURN_ID]
    assert len(_audit(event="cancel_sent")) == 2  # each delivered frame, once

    undelivered = _seam_turn(parked=True)
    undelivered.turn_id = "turn-never-delivered"
    seam._upstream = None  # the socket this turn lived on is already gone
    await seam._send_upstream_cancel(undelivered)

    assert "turn-never-delivered" not in seam.self_cancelled_turn_ids
    assert list(seam._self_cancelled_order) == [_TURN_ID]
    assert len(_audit(event="cancel_sent")) == 2  # a refused dial audits nothing


@pytest.mark.asyncio
async def test_pr4_t09_a_busy_with_nothing_pending_is_still_a_second_tab(
    client, p3_upstream, monkeypatch
):
    """T-09 (§7, P4 semantics kept): with nothing of ours in flight the engine's
    busy is what it always was — real concurrency. No re-cancel, no
    `busy_after_cancel` row, the original copy, and not one extra frame
    upstream: the ledger only ever widens what is *retryable*, never what is
    *cancellable*."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "30")
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "30")

    async def script(ws, conn, idx):
        await ws.send_json(_busy_frame())

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    busy = (await _collect(ws, 1, timeout=6.0))[0]

    assert busy["type"] == "error"
    assert busy["error_code"] == "session_busy"
    assert busy["content"] == ws_chat_mod._GRACEFUL_BUSY_COPY["zh-hk"]
    assert busy["content"] != ws_chat_mod._BUSY_RETRYABLE_COPY["zh-hk"]

    await asyncio.sleep(0.2)  # let any stray frame land before asserting none
    await ws.close()

    assert len(p3_upstream.frames) == 1  # exactly the turn frame, no re-send
    assert _cancel_frames(p3_upstream) == []
    assert _audit(event="cancel_sent") == []
    assert _audit(event="busy_after_cancel") == []
    mid = _audit(event="midstream_error")[0]
    assert mid["upstream_error"] == "session_busy"
    assert mid["detail"] == "session_busy_non_retryable"


@pytest.mark.asyncio
async def test_pr4_g01_the_ledger_is_ours_and_bounded(client):
    """G-01 (§7, 紅線 1): the retry set is this connection's own cancels and
    nothing else, bounded FIFO at the §7 cap. Eviction only ever forgets the
    *oldest* cancel — that can cost a self-heal for a turn nobody is waiting on
    any more, and can never widen what the relay is willing to cancel, because
    the set is only ever read to re-cancel ids already in it. The four residual
    `running` rows are not reachable through it."""
    seam = _RelaySeam(upstream=_ScriptedSocket(), turn=None)

    assert ws_chat_mod._SELF_CANCELLED_MAX == 16  # the §7 bound, pinned

    for i in range(20):
        seam._remember_self_cancelled(f"turn-{i:02d}")

    expected = {f"turn-{i:02d}" for i in range(4, 20)}
    assert len(seam.self_cancelled_turn_ids) == ws_chat_mod._SELF_CANCELLED_MAX
    assert len(seam._self_cancelled_order) == ws_chat_mod._SELF_CANCELLED_MAX
    assert seam.self_cancelled_turn_ids == expected
    assert list(seam._self_cancelled_order) == sorted(expected)
    assert "turn-00" not in seam.self_cancelled_turn_ids  # oldest evicted first

    seam._remember_self_cancelled("turn-19")  # already in: no reorder, no growth
    assert list(seam._self_cancelled_order) == sorted(expected)

    for rid in _RESIDUAL_RUNNING_TURN_IDS:
        assert rid not in seam.self_cancelled_turn_ids
        assert rid not in seam._self_cancelled_order


@pytest.mark.asyncio
async def test_pr4_g02_the_self_heal_is_not_a_janitor(
    client, p3_upstream, monkeypatch
):
    """G-02 (§7, 紅線 1): the self-heal re-sends a frame it already sent — it
    does not go looking for leftovers. The busy branch issues no statement of
    its own (its only write is the audit row), it names no residual row, and it
    writes no turn status: the ledger decides what is *retryable*, the engine
    still owns every state transition."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_CLARIFY_WAIT_ENV, "30")
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "30")

    statements: list[str] = []
    real_connect = auth_db.connect

    def recording_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(auth_db, "connect", recording_connect)

    await _supersede_then_busy(p3_upstream)

    ws = await _open_chat(client, session, student_id)
    await _start_turn(ws)
    await _collect(ws, 2)
    await _start_turn(ws)
    # the new turn's own DB work is done the moment its frame goes upstream, so
    # anything added from here on is the busy branch's doing
    assert await _wait_for(lambda: len(p3_upstream.frames) >= 3)
    before = len(_relay_state_writes(statements))

    busy = (await _collect(ws, 1, timeout=6.0))[0]
    assert busy["content"] == ws_chat_mod._BUSY_RETRYABLE_COPY["zh-hk"]
    assert await _wait_for(lambda: len(_cancel_frames(p3_upstream)) == 2)
    after = _relay_state_writes(statements)
    assert len(after) == before  # a frame, not a sweep
    await ws.close()

    assert statements, "the recorder captured no DB traffic at all"
    for rid in _RESIDUAL_RUNNING_TURN_IDS:
        assert rid not in json.dumps(
            _cancel_frames(p3_upstream), ensure_ascii=False
        ), rid
        assert rid not in json.dumps(_audit(), ensure_ascii=False), rid
        assert not any(rid in sql for sql in statements), rid
    lowered = " ".join(statements).lower()
    assert "turn_status" not in lowered
    assert "update turns" not in lowered
    assert "delete from turns" not in lowered
    assert "from turns" not in lowered  # not even a read sweep
