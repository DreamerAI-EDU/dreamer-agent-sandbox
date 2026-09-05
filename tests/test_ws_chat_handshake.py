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
    6. media consent withdrawn          -> 403 (consent)
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
async def test_withdrawn_media_consent_rejected(client, tmp_path):
    """Latest media_consent row withdrawn -> 403 (consent gate)."""
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


# ---------------------------------------------------------------------------
# Positive — confirmed student relays to (mock) DeepTutor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmed_student_upgrades_and_relays(client, mock_upstream):
    """Full happy path: gate passes, relay echoes the mock sequence."""
    session, student_id = _confirmed_trio()

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
