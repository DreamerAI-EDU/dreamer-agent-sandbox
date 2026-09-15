"""W3-A — WS chat handshake gate tests (work instruction v1.0 §3/§5).

Negative gates (each rejects at the HTTP layer BEFORE upgrade, with a
WARNING audit trail):
    1. no session cookie                -> 401 (auth)
    2. expired session cookie           -> 401 (auth)
    3. teacher-role session             -> 403 (role; Q4 teacher-refusal)
    4. parent A opening parent B's
       student (full-id cross account)  -> 403 (ownership)
    5. student pending (teacher has not
       confirmed the class binding)     -> 403 (class_confirmed)
    6. chat consent withdrawn          -> 403 (consent)
       (W6 PR-C2: consent decoupled — the gate hangs off chat_consent;
       a media_consent withdrawal no longer stops AI chat)
Positive:
    7. confirmed student -> upgrade OK, frames relay bidirectionally to
       the (mock) DeepTutor upstream and close cleanly.

The upstream is conftest's mock_deeptutor_server, wired via a
monkeypatched _upstream_ws_url so no real DeepTutor is needed here.
"""

from __future__ import annotations

import json
import os
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
from auth import security as auth_security  # noqa: E402
from auth import students as students_mod  # noqa: E402
from auth import ws_chat as ws_chat_mod  # noqa: E402
from auth.api import build_app  # noqa: E402

MEDIA_VERSION = consent_mod.get_doc_config("media_consent")["current_version"]
CHAT_VERSION = consent_mod.get_doc_config("chat_consent")["current_version"]


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


def _audit_events(tmp_path):
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Fixtures & data builders (direct DB — same pattern as test_students.py)
# ---------------------------------------------------------------------------

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


@pytest_asyncio.fixture
async def mock_upstream(mock_deeptutor_server, monkeypatch):
    """Point ws_chat._upstream_ws_url at conftest's mock DeepTutor."""
    host, port, controller = mock_deeptutor_server
    controller.sequence = [
        {"type": "session", "session_id": "unified_test_001", "seq": 0},
        {"type": "stage", "stage": "thinking", "seq": 1,
         "session_id": "unified_test_001"},
        {"type": "content", "content": "你好！", "seq": 2,
         "session_id": "unified_test_001"},
        {"type": "result", "session_id": "unified_test_001",
         "cost_summary": {"total": 0.01}, "seq": 3},
    ]
    controller.auto_done = True
    monkeypatch.setattr(
        ws_chat_mod,
        "_upstream_ws_url",
        lambda: f"ws://{host}:{port}/api/v1/ws",
    )
    return controller


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


def _new_class(teacher_id: str) -> str:
    return classes_mod.create_class(teacher_id=teacher_id, name="Test Class")


def _new_student(parent_id: str, teacher_id: str) -> str:
    return students_mod.create_student(
        first_name="小明",
        age_band="P1-P3",
        lang_code="zh-hk",
        pin_hash=students_mod.hash_pin("1357"),
        parent_id=parent_id,
        teacher_id=teacher_id,
    )


def _link_student_class(class_id: str, student_id: str, status: str) -> None:
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            "INSERT INTO class_students (class_id, student_id, status,"
            " created_at) VALUES (?, ?, ?, ?)",
            (class_id, student_id, status, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _confirmed_trio():
    """Return (parent_session, student_id) with a fully approved student."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "confirmed")
    return _new_session(parent_id), student_id

def _confirmed_trio_full():
    """Return (parent_id, parent_session, student_id) fully approved."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "confirmed")
    return parent_id, _new_session(parent_id), student_id


# ---------------------------------------------------------------------------
# Negative gates — reject before upgrade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_session_rejected(client, tmp_path):
    """No auth_session cookie -> 401 (auth gate)."""
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect("/api/ws/chat?student=abcdef12")
    assert ei.value.status == 401


@pytest.mark.asyncio
async def test_expired_session_rejected(client, tmp_path):
    """Expired session cookie -> 401 (auth gate)."""
    parent_id = _new_user(role="parent")
    expired = _new_session(parent_id, expires_days=-1)
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            "/api/ws/chat?student=abcdef12",
            headers={"Cookie": f"auth_session={expired}"},
        )
    assert ei.value.status == 401


@pytest.mark.asyncio
async def test_teacher_session_rejected(client, tmp_path):
    """Teacher-role session -> 403 (role gate; Q4)."""
    teacher_id = _new_user(role="teacher")
    session = _new_session(teacher_id)
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            "/api/ws/chat?student=abcdef12",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403
    assert any(
        e["event"] == "ws_chat_rejected" for e in _audit_events(tmp_path)
    )


@pytest.mark.asyncio
async def test_cross_account_student_rejected(client, tmp_path):
    """Parent A's session opening parent B's student -> 403 (ownership)."""
    _, student_id = _confirmed_trio()
    other_parent = _new_user(role="parent")
    session = _new_session(other_parent)

    # Full id straight through resolve; ownership check must reject.
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403

    # Masked prefix of a foreign student resolves to nothing (same 403).
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei2:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei2.value.status == 403
    assert any(
        e["event"] == "ws_chat_rejected" for e in _audit_events(tmp_path)
    )


@pytest.mark.asyncio
async def test_pending_student_rejected(client, tmp_path):
    """Class binding pending (no confirmed class) -> 403 (class gate)."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "pending")
    session = _new_session(parent_id)

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_required_unsigned_chat_consent_rejected(client, tmp_path, monkeypatch):
    """Default-deny flip (required: true): unsigned student -> 403.

    PR-D: when chat_consent is required, the gate needs a current-version
    agreed row -- no row at all must refuse (not only explicit withdrawal).
    Simulated by monkeypatching get_doc_config to flip required while the
    real config yaml still says required: false (safe by default).
    """
    parent_id, session, student_id = _confirmed_trio_full()
    _orig_get_doc = consent_mod.get_doc_config

    def _flip_required(doc_type):
        cfg = _orig_get_doc(doc_type)
        return {**cfg, "required": True} if doc_type == "chat_consent" else cfg

    monkeypatch.setattr(consent_mod, "get_doc_config", _flip_required)
    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403


@pytest.mark.asyncio
async def test_required_agreed_chat_consent_allowed(
    client, mock_upstream, monkeypatch
):
    """Default-deny flip: an agreed current-version row still opens chat.

    Guards against the flip regressing students who already signed.
    """
    parent_id, session, student_id = _confirmed_trio_full()
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="agreed",
        student_id=student_id,
        ip=None,
        user_agent=None,
    )
    _orig_get_doc = consent_mod.get_doc_config

    def _flip_required(doc_type):
        cfg = _orig_get_doc(doc_type)
        return {**cfg, "required": True} if doc_type == "chat_consent" else cfg

    monkeypatch.setattr(consent_mod, "get_doc_config", _flip_required)
    await _assert_upgrade_ok(client, mock_upstream, session, student_id)


@pytest.mark.asyncio
async def test_withdrawn_chat_consent_rejected(client, tmp_path):
    """Latest chat_consent row withdrawn -> 403 (consent gate)."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "confirmed")
    session = _new_session(parent_id)

    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="agreed",
        student_id=student_id,
    )
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="withdrawn",
        student_id=student_id,
    )

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403
    assert any(
        e["event"] == "ws_chat_rejected" for e in _audit_events(tmp_path)
    )


@pytest.mark.asyncio
async def test_both_withdrawn_rejected(client, tmp_path):
    """Media withdrawn AND chat withdrawn -> 403 (chat gate decides)."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "confirmed")
    session = _new_session(parent_id)

    for doc_type, version in (
        ("media_consent", MEDIA_VERSION),
        ("chat_consent", CHAT_VERSION),
    ):
        consent_mod.insert_consent_row(
            user_id=parent_id,
            doc_type=doc_type,
            doc_version=version,
            action="agreed",
            student_id=student_id,
        )
        consent_mod.insert_consent_row(
            user_id=parent_id,
            doc_type=doc_type,
            doc_version=version,
            action="withdrawn",
            student_id=student_id,
        )

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403


@pytest.mark.asyncio
async def test_chat_withdrawn_media_agreed_rejected(client, tmp_path):
    """Chat withdrawn while media agreed -> 403 (withdraw chat stops chat)."""
    parent_id = _new_user(role="parent")
    teacher_id = _new_user(role="teacher")
    class_id = _new_class(teacher_id)
    student_id = _new_student(parent_id, teacher_id)
    _link_student_class(class_id, student_id, "confirmed")
    session = _new_session(parent_id)

    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="media_consent",
        doc_version=MEDIA_VERSION,
        action="agreed",
        student_id=student_id,
    )
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="agreed",
        student_id=student_id,
    )
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="withdrawn",
        student_id=student_id,
    )

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403


# ---------------------------------------------------------------------------
# Decoupled positive — media state must never stop chat (W6 PR-C2 core)
# ---------------------------------------------------------------------------

async def _assert_upgrade_ok(client, mock_upstream, session, student_id):
    """Handshake passes and frames relay through the mock DeepTutor."""
    ws = await client.ws_connect(
        f"/api/ws/chat?student={student_id[:8]}",
        headers={"Cookie": f"auth_session={session}"},
    )
    assert ws is not None

    await ws.send_json(
        {"type": "message", "capability": "chat", "message": "你好"}
    )

    events = []
    for _ in range(5):  # 4 programmed events + auto_done
        msg = await ws.receive()
        assert msg.type == aiohttp.WSMsgType.TEXT, msg
        events.append(json.loads(msg.data))
    assert [e["type"] for e in events] == [
        "session", "stage", "content", "result", "done",
    ]
    assert events[0]["session_id"] == "unified_test_001"

    await ws.close()
    assert mock_upstream.received
    assert mock_upstream.received[0]["message"] == "你好"


@pytest.mark.asyncio
async def test_media_withdrawn_chat_unsigned_denied(client, tmp_path):
    """Media withdrawn + chat unsigned -> 403 by default-deny (PR-D).

    Decoupling survives: the refusal is caused by the UNSIGNED chat
    consent (required:true now), NOT by the media withdrawal. With a chat
    agreed row the same media-withdrawn student opens (see the next test).
    """
    session, student_id = _confirmed_trio()
    parent_id = auth_db.get_session_user(session)["id"]

    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="media_consent",
        doc_version=MEDIA_VERSION,
        action="agreed",
        student_id=student_id,
    )
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="media_consent",
        doc_version=MEDIA_VERSION,
        action="withdrawn",
        student_id=student_id,
    )

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403
    assert any(
        e["event"] == "ws_chat_rejected" for e in _audit_events(tmp_path)
    )


@pytest.mark.asyncio
async def test_media_agreed_chat_unsigned_denied(client, tmp_path):
    """Media agreed, chat unsigned -> 403 (PR-D default-deny).

    Since the registry flip, a missing chat_consent row is NOT treated as
    'not withdrawn, proceed'; it is treated as 'not agreed, deny'. This is
    the enforcement the registration UI (required checkbox) pairs with.
    """
    session, student_id = _confirmed_trio()
    parent_id = auth_db.get_session_user(session)["id"]

    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="media_consent",
        doc_version=MEDIA_VERSION,
        action="agreed",
        student_id=student_id,
    )

    with pytest.raises(aiohttp.WSServerHandshakeError) as ei:
        await client.ws_connect(
            f"/api/ws/chat?student={student_id[:8]}",
            headers={"Cookie": f"auth_session={session}"},
        )
    assert ei.value.status == 403
    assert any(
        e["event"] == "ws_chat_rejected" for e in _audit_events(tmp_path)
    )


@pytest.mark.asyncio
async def test_media_withdrawn_chat_agreed_opens(client, mock_upstream):
    """Media withdrawn but chat agreed -> chat opens (flags independent)."""
    session, student_id = _confirmed_trio()
    parent_id = auth_db.get_session_user(session)["id"]

    for doc_type, version, action in (
        ("media_consent", MEDIA_VERSION, "agreed"),
        ("media_consent", MEDIA_VERSION, "withdrawn"),
        ("chat_consent", CHAT_VERSION, "agreed"),
    ):
        consent_mod.insert_consent_row(
            user_id=parent_id,
            doc_type=doc_type,
            doc_version=version,
            action=action,
            student_id=student_id,
        )

    await _assert_upgrade_ok(client, mock_upstream, session, student_id)


# ---------------------------------------------------------------------------
# Positive — confirmed student relays to (mock) DeepTutor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmed_student_upgrades_and_relays(client, mock_upstream):
    """Full happy path: gate passes, relay echoes the mock sequence.

    PR-D default-deny: a brand-new student needs a current chat_consent
    agreed row (the registration required checkbox writes it) before the
    handshake proceeds; media rows are irrelevant to this gate.
    """
    session, student_id = _confirmed_trio()
    parent_id = auth_db.get_session_user(session)["id"]
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="chat_consent",
        doc_version=CHAT_VERSION,
        action="agreed",
        student_id=student_id,
    )

    await _assert_upgrade_ok(client, mock_upstream, session, student_id)


# ---------------------------------------------------------------------------
# P3 — relay resilience (pre-content retry / idle watchdog / audit)
# ---------------------------------------------------------------------------
#
# The upstream stand-in here is scripted per *message*, not per connection, so
# a test can answer the first attempt with a 429 and the re-sent attempt with a
# normal turn — and can tell a same-socket retry apart from a re-dial via
# ``conn``. Budgets/idle windows are shortened through the relay's env knobs so
# the suite stays fast; the shipped defaults are asserted separately.

import asyncio  # noqa: E402
import socket  # noqa: E402

from auth import relay_audit as relay_audit_mod  # noqa: E402

_RELAY_BACKOFF_ENV = "WS_CHAT_RETRY_BACKOFF"
_IDLE_WATCHDOG_ENV = "WS_CHAT_IDLE_WATCHDOG_SECONDS"
_MIGRATION_SQL = os.path.join(
    REPO_ROOT, "migrations", "phase8f_ws_chat_relay_audit.sql"
)


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


def _audit(*, event: str | None = None) -> list[sqlite3.Row]:
    rows = relay_audit_mod.rows()
    return [r for r in rows if event is None or r["event"] == event]


@pytest.mark.asyncio
async def test_p3_pre_content_429_is_retried_and_invisible(
    client, p3_upstream, monkeypatch
):
    """Condition 1 (pre-content half): a 429 before any text is re-sent.

    The child must see the recovered answer and never the 429; the retry reuses
    the open socket and re-sends the byte-identical turn frame (P2 persona
    included), and the attempt is audited with its cause.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        if idx == 0:
            await ws.send_json(
                {
                    "type": "error",
                    "error_code": "rate_limited",
                    "content": "429 Too Many Requests",
                }
            )
            return
        await ws.send_json({"type": "session", "session_id": "unified_p3_001"})
        await ws.send_json(
            {
                "type": "content",
                "content": "你好！",
                "session_id": "unified_p3_001",
            }
        )
        await ws.send_json(
            {
                "type": "done",
                "turn_id": "turn-p3-001",
                "session_id": "unified_p3_001",
            }
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 3)
    assert [e["type"] for e in events] == ["session", "content", "done"]
    assert all("429" not in json.dumps(e) for e in events)

    await ws.close()
    assert p3_upstream.connections == 1  # retry reused the open socket
    assert len(p3_upstream.frames) == 2  # one turn frame, re-sent exactly once
    assert p3_upstream.frames[0]["raw"] == p3_upstream.frames[1]["raw"]
    assert json.loads(p3_upstream.frames[0]["raw"])["persona"] == "dibi-p1-p3"

    assert len(_audit(event="turn_start")) == 1
    retries = _audit(event="turn_retry")
    assert [r["attempt"] for r in retries] == [1]
    assert retries[0]["upstream_error"] == "rate_limited"
    end = _audit(event="turn_end")[0]
    assert end["final_status"] == "completed"
    assert end["upstream_error"] is None
    assert end["session_id"] == "unified_p3_001"
    assert end["turn_id"] == "turn-p3-001"
    assert _audit(event="midstream_error") == []


@pytest.mark.asyncio
async def test_p3_midstream_429_is_not_retried_and_never_silent(
    client, p3_upstream, monkeypatch
):
    """Conditions 1 + 3: text already streamed -> no re-send, no dead end.

    The half answer stays on screen and a localized busy line closes the turn,
    so the child is never left hanging; the mid-stream failure is audited with
    the `content_already_streamed` reason instead of the success path only.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": "unified_p3_002"})
        await ws.send_json(
            {
                "type": "content",
                "content": "你好，我",
                "session_id": "unified_p3_002",
            }
        )
        await ws.send_json(
            {
                "type": "error",
                "error_code": "upstream_error",
                "content": "429 Too Many Requests: rate limit exceeded",
                "session_id": "unified_p3_002",
            }
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 3)
    assert [e["type"] for e in events] == ["session", "content", "error"]
    assert events[1]["content"] == "你好，我"  # the half answer is kept
    busy = events[2]
    assert busy["error_code"] == "upstream_rate_limited"
    assert busy["content"] == ws_chat_mod._GRACEFUL_BUSY_COPY["zh-hk"]
    assert "429" not in json.dumps(busy)  # raw provider text never reaches the kid

    await _assert_quiet(ws)  # no hidden retry after text is on screen
    await ws.close()
    assert len(p3_upstream.frames) == 1

    assert _audit(event="turn_retry") == []
    mid = _audit(event="midstream_error")[0]
    assert mid["upstream_error"] == "rate_limited"
    assert mid["detail"] == "content_already_streamed"
    assert mid["session_id"] == "unified_p3_002"
    assert _audit(event="turn_end")[0]["final_status"] == "failed"


@pytest.mark.asyncio
async def test_p3_non_rate_limit_error_is_not_retried_and_never_silent(
    client, p3_upstream, monkeypatch
):
    """Review Q: only `rate_limited` may spend retry budget.

    A 500-style upstream error is not a rate limit, so the turn frame is never
    re-sent and no retry delay is burned; the turn still closes with localized
    copy instead of a dead end, and no raw provider wording reaches the child.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        await ws.send_json(
            {
                "type": "error",
                "error_code": "Internal Server Error",
                "content": "500 Internal Server Error: upstream provider died",
                "session_id": "unified_p3_500",
            }
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 1)
    assert events[0]["type"] == "error"
    assert events[0]["error_code"] == "upstream_error"
    assert events[0]["content"] == ws_chat_mod._UPSTREAM_UNAVAILABLE_COPY
    assert "500" not in json.dumps(events)  # raw text never reaches the kid
    await _assert_quiet(ws)  # and nothing trails the stop message
    await ws.close()

    assert len(p3_upstream.frames) == 1  # never re-sent: budget untouched
    assert _audit(event="turn_retry") == []
    mid = _audit(event="midstream_error")[0]
    assert mid["upstream_error"] == "upstream_error"
    assert mid["detail"] == "non_retryable_error_frame provider=internal_server_error"
    assert mid["attempt"] is None
    end = _audit(event="turn_end")[0]
    assert end["final_status"] == "failed"
    assert end["upstream_error"] == "upstream_error"


@pytest.mark.asyncio
async def test_p3_failed_turn_tail_never_reaches_the_child(
    client, p3_upstream, monkeypatch
):
    """Condition 1: after the graceful stop, that turn's leftovers stay hidden.

    The upstream keeps talking for a turn that has already failed — a progress
    frame, a second raw 429, a late ``done``. None of it may reach the child:
    the raw provider text is never shown, and the closed turn is not re-opened
    behind the message. The child's next question still works.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        sid = f"unified_p3_tail_{idx}"
        await ws.send_json({"type": "session", "session_id": sid})
        if idx == 0:
            await ws.send_json(
                {"type": "content", "content": "你好，我", "session_id": sid}
            )
            await ws.send_json(
                {
                    "type": "error",
                    "error_code": "upstream_error",
                    "content": "429 Too Many Requests: rate limit exceeded",
                    "session_id": sid,
                }
            )
            # the failed turn is not done with us: its tail follows
            await ws.send_json(
                {"type": "progress", "content": "階段", "session_id": sid}
            )
            await ws.send_json(
                {
                    "type": "error",
                    "error_code": "upstream_error",
                    "content": "429 Too Many Requests",
                    "session_id": sid,
                }
            )
            await ws.send_json(
                {"type": "done", "turn_id": "turn-tail", "session_id": sid}
            )
            return
        await ws.send_json(
            {"type": "content", "content": "第二答", "session_id": sid}
        )
        await ws.send_json(
            {"type": "done", "turn_id": "turn-tail-2", "session_id": sid}
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})
    events = await _collect(ws, 3)
    assert [e["type"] for e in events] == ["session", "content", "error"]
    assert events[2]["content"] == ws_chat_mod._GRACEFUL_BUSY_COPY["zh-hk"]

    await _assert_quiet(ws)  # the tail (second 429, late done) stays hidden

    await ws.send_json(
        {"type": "message", "capability": "chat", "message": "再問一次"}
    )
    again = await _collect(ws, 3)
    assert [e["type"] for e in again] == ["session", "content", "done"]
    assert again[1]["content"] == "第二答"
    assert "429" not in json.dumps(events + again)
    await ws.close()

    assert len(p3_upstream.frames) == 2  # the failed turn was never re-sent
    assert _audit(event="turn_retry") == []
    assert _audit(event="midstream_error")[0]["detail"] == (
        "content_already_streamed"
    )
    # newest first: the child's second question ended normally
    assert [r["final_status"] for r in _audit(event="turn_end")] == [
        "completed",
        "failed",
    ]


@pytest.mark.asyncio
async def test_p3_exhausted_retry_budget_falls_back_to_graceful_message(
    client, p3_upstream, monkeypatch
):
    """Retry budget spent while still pre-content -> graceful stop, not silence.

    Every attempt is audited with its ordinal so the trail shows the full
    escalation (condition 3) rather than only the final outcome.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        await ws.send_json(
            {"type": "error", "error_code": "rate_limited", "content": "429"}
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 1)
    assert events[0]["type"] == "error"
    assert events[0]["content"] == ws_chat_mod._GRACEFUL_BUSY_COPY["zh-hk"]
    assert events[0]["error_code"] == "upstream_rate_limited"

    await ws.close()
    assert len(p3_upstream.frames) == 3  # original + the two configured retries
    # rows() reads newest-first, so compare the attempt set, not the order
    assert sorted(r["attempt"] for r in _audit(event="turn_retry")) == [1, 2]
    mid = _audit(event="midstream_error")[0]
    assert mid["detail"] == "retry_budget_exhausted"
    assert mid["attempt"] == 2


@pytest.mark.asyncio
async def test_p3_upstream_close_before_content_reconnects_and_retries(
    client, p3_upstream, monkeypatch
):
    """A dropped socket before any text is a retry, not a lost turn."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_RELAY_BACKOFF_ENV, "0.05,0.05")

    async def script(ws, conn, idx):
        if conn == 1:
            await ws.close()  # upstream dies mid-turn, nothing streamed yet
            return
        await ws.send_json(
            {"type": "content", "content": "答案", "session_id": "unified_p3_003"}
        )
        await ws.send_json(
            {
                "type": "done",
                "turn_id": "turn-p3-003",
                "session_id": "unified_p3_003",
            }
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["content", "done"]

    await ws.close()
    assert p3_upstream.connections == 2  # re-dialled, then replayed the turn
    assert p3_upstream.frames[0]["raw"] == p3_upstream.frames[1]["raw"]
    retry = _audit(event="turn_retry")[0]
    assert retry["upstream_error"] == "upstream_closed"
    assert _audit(event="turn_end")[0]["final_status"] == "completed"


@pytest.mark.asyncio
async def test_p3_watchdog_kills_a_silent_turn(
    client, p3_upstream, monkeypatch
):
    """Condition 2 (kill half): a turn with an idle upstream is reaped.

    The child gets the localized stop message and the audit row carries the
    `idle_timeout` cause instead of a silently abandoned turn.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "0.4")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": "unified_p3_wd"})
        # then silence: the turn never completes

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 2)
    assert [e["type"] for e in events] == ["session", "error"]
    assert events[1]["error_code"] == "upstream_idle_timeout"
    assert events[1]["content"] == ws_chat_mod._UPSTREAM_UNAVAILABLE_COPY
    await ws.close()

    kill = await _wait_for(lambda: bool(_audit(event="watchdog_kill")))
    assert kill
    assert _audit(event="watchdog_kill")[0]["upstream_error"] == "idle_timeout"
    end = _audit(event="turn_end")[0]
    assert end["final_status"] == "failed"
    assert end["upstream_error"] == "idle_timeout"


@pytest.mark.asyncio
async def test_p3_watchdog_is_idle_based_not_absolute(
    client, p3_upstream, monkeypatch
):
    """Condition 2 (survive half): a long but *live* turn is never killed.

    Six progress frames spaced well inside the idle window keep the turn alive
    for more than twice the window; an absolute deadline would have killed it.
    """
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setenv(_IDLE_WATCHDOG_ENV, "0.4")

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": "unified_p3_long"})
        for i in range(6):  # ~0.9s of work, i.e. > 2x the 0.4s idle window
            await asyncio.sleep(0.15)
            await ws.send_json(
                {
                    "type": "progress",
                    "content": f"階段 {i}",
                    "session_id": "unified_p3_long",
                }
            )
        await ws.send_json(
            {"type": "content", "content": "答案", "session_id": "unified_p3_long"}
        )
        await ws.send_json(
            {
                "type": "done",
                "turn_id": "turn-p3-long",
                "session_id": "unified_p3_long",
            }
        )

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})

    events = await _collect(ws, 9, timeout=8.0)
    assert [e["type"] for e in events] == [
        "session",
        "progress",
        "progress",
        "progress",
        "progress",
        "progress",
        "progress",
        "content",
        "done",
    ]
    await ws.close()
    assert _audit(event="watchdog_kill") == []
    assert _audit(event="turn_end")[0]["final_status"] == "completed"


@pytest.mark.asyncio
async def test_p3_client_disconnect_reaps_the_open_turn(
    client, p3_upstream
):
    """Zombie reap: closing the socket mid-turn leaves no open turn behind."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)

    async def script(ws, conn, idx):
        await ws.send_json({"type": "session", "session_id": "unified_p3_reap"})
        # never completes — the child walks away instead

    p3_upstream.on_message = script

    ws = await _open_chat(client, session, student_id)
    await ws.send_json({"type": "message", "capability": "chat", "message": "你好"})
    await _collect(ws, 1)
    await ws.close()

    reaped = await _wait_for(
        lambda: bool(
            [
                r
                for r in _audit(event="turn_end")
                if r["final_status"] == "aborted"
            ]
        )
    )
    assert reaped
    end = _audit(event="turn_end")[0]
    assert end["detail"] == "client_closed"
    assert end["session_id"] == "unified_p3_reap"


@pytest.mark.asyncio
async def test_p3_engine_unreachable_is_audited(client, monkeypatch):
    """Connect failure keeps its old client contract and gains an audit row."""
    session, student_id = _confirmed_trio()
    await _agree_chat(session, student_id)
    monkeypatch.setattr(
        ws_chat_mod,
        "_upstream_ws_url",
        lambda: f"ws://127.0.0.1:{_port()}/api/v1/ws",  # nobody listens here
    )

    ws = await _open_chat(client, session, student_id)
    events = await _collect(ws, 1)
    assert events[0]["type"] == "error"
    assert events[0]["error_code"] == "upstream_unavailable"
    assert events[0]["content"] == ws_chat_mod._UPSTREAM_UNAVAILABLE_COPY
    await ws.close()

    row = _audit(event="upstream_unavailable")[0]
    assert row["upstream_error"] == "connect_failed"
    assert row["student_mask"] == student_id[:8]


def test_p3_rate_limit_match_is_error_frames_only():
    """A content frame that merely mentions 429 is never a limit rejection."""
    assert ws_chat_mod._is_rate_limit_frame(
        '{"type":"error","content":"429 Too Many Requests"}'
    )
    assert ws_chat_mod._is_rate_limit_frame(
        '{"type":"error","error_code":"resource_exhausted","content":"busy"}'
    )
    assert not ws_chat_mod._is_rate_limit_frame(
        '{"type":"content","content":"答案係 429 蚊","session_id":"s1"}'
    )
    # a session id that happens to read like quota noise must not trip it either
    assert not ws_chat_mod._is_rate_limit_frame(
        '{"type":"session","session_id":"unified_quota_1"}'
    )


def test_p3_upstream_error_code_is_normalised_for_the_audit():
    """A provider error code is untrusted text: only a short token is stored.

    The audit table is append-only, so whatever lands in ``upstream_error``
    stays: keep a bounded, charset-limited token (or nothing), never prose.
    """
    assert ws_chat_mod._error_code_of({"error_code": "Internal Server Error"}) == (
        "internal_server_error"
    )
    assert ws_chat_mod._error_code_of({"code": "resource_exhausted"}) == (
        "resource_exhausted"
    )
    assert ws_chat_mod._error_code_of({"error_code": "x" * 200}) == "x" * 64
    assert ws_chat_mod._error_code_of({"content": "no code here"}) is None
    assert ws_chat_mod._error_code_of({"error_code": "   "}) is None
    assert ws_chat_mod._error_code_of({"error_code": 42}) is None


def _declared_columns(schema_sql: str, table: str) -> list[str]:
    """Column names declared by a CREATE TABLE in a migration file.

    Comments are stripped before the body is delimited: the DDL annotates most
    columns inline, and a stray bracket inside a comment would otherwise be
    mistaken for the end of the table body.
    """
    body = schema_sql.split(f"CREATE TABLE IF NOT EXISTS {table}", 1)[1]
    body = "\n".join(line.split("--", 1)[0] for line in body.splitlines())
    body = body.split("(", 1)[1].split(")", 1)[0]
    names = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith(
            ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK")
        ):
            continue
        names.append(line.split()[0])
    return names


def test_p3_audit_table_matches_migration_and_is_append_only(
    tmp_path, monkeypatch
):
    """Migration / ensure_schema pairing + append-only triggers (audit rule).

    The audit trail may only be appended to: the ledger is the evidence for
    every retry, mid-stream failure and watchdog kill, so UPDATE/DELETE are
    refused at the DB level, not merely by convention.
    """
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "p3_audit.db"))
    auth_db.ensure_schema()

    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        live = [
            r[1]
            for r in conn.execute("PRAGMA table_info(ws_chat_relay_audit)")
        ]
        schema_sql = open(_MIGRATION_SQL, encoding="utf-8").read()
        assert live == _declared_columns(schema_sql, "ws_chat_relay_audit")
        triggers = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
                " AND name LIKE 'ws_chat_relay_audit%'"
            )
        ]
        assert sorted(triggers) == [
            "ws_chat_relay_audit_no_delete",
            "ws_chat_relay_audit_no_update",
        ]
    finally:
        conn.close()

    relay_audit_mod.record(
        relay_audit_mod.EVENT_TURN_START, student_mask="abcdef12"
    )
    target = auth_db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            target.execute("UPDATE ws_chat_relay_audit SET detail='tampered'")
            target.commit()
        target.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            target.execute("DELETE FROM ws_chat_relay_audit")
            target.commit()
        target.rollback()
    finally:
        target.close()
    assert len(relay_audit_mod.rows()) == 1
