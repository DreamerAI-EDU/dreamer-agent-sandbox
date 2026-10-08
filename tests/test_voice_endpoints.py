"""c1-13b Phase 1 — voice input endpoints (P1-P3 trial).

Spec under test (boss 實施令 2026-10-04):

  * everyone is decided SERVER-SIDE: ``GET /api/voice/config`` is the only
    authority on whether a mic button may exist (flag → band → signed
    ``voice_consent`` row → daily meter → monthly meter);
  * no consent row ⇒ the kid does not even see a button (200 + enabled=false,
    never a 401/403 that leaks *why*);
  * ``POST /api/voice/transcribe`` re-checks the same gate, sizes the clip
    before spending, refuses an unmeasurable clip rather than guessing, and
    charges the meters with the real length;
  * the transcript travels to the browser and nowhere else — not the audit
    log, not the DB;
  * a closed meter (daily or monthly) stops voice with no code change.

No real credentials: ``test-pass-`` / ``test-pin-`` style values only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct

import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import api as api_mod  # noqa: E402
from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import voice_quota  # noqa: E402
from auth import voice_stt  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CONFIRM_PASSWORD = "test-pass-parent1"
BAND = "P1-P3"
TRANSCRIPT = "tell me why the sky is blue"


def _future_iso(**delta: int) -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp, name="auth_session") -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith(f"{name}="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no {name} cookie")


def _kid(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"kid_session={token}"}


def _auth(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"auth_session={token}"}


def _wav(seconds: float, *, sample_rate: int = 16000) -> bytes:
    """A real PCM WAV of exactly `seconds`."""
    frames = int(sample_rate * seconds)
    payload = b"\x00\x00" * frames
    block_align = 2
    byte_rate = sample_rate * block_align
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, byte_rate, block_align, 16)
    body = (
        b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(payload)) + payload
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def _clip_form(payload: bytes, *, declared_ms: int | None = None, lang: str = "en",
               filename: str = "clip") -> FormData:
    """Exactly what the browser sends: one multipart file part + two fields."""
    form = FormData()
    form.add_field("audio", payload, filename=filename, content_type="audio/webm")
    if declared_ms is not None:
        form.add_field("duration_ms", str(declared_ms))
    form.add_field("lang", lang)
    return form


def _full_student_id() -> str:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        row = conn.execute("SELECT id FROM students ORDER BY rowid DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None, "no student in test DB"
    return row[0]


def _latest_invite_token() -> str:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        row = conn.execute("SELECT token FROM invites ORDER BY rowid DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None, "no invite row in test DB"
    return row[0]


def _audit_lines(tmp_path) -> list[dict]:
    path = consent_mod.AUDIT_LOG_PATH
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    monkeypatch.setattr(
        consent_mod, "AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl")
    )
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
def teacher_invite():
    for code in ("invite-ok-001", "invite-ok-002"):
        auth_db.insert_teacher_invite(
            code=code, created_by="admin-cli", expires_at=_future_iso(days=7)
        )


async def _setup_teacher(client):
    await client.post(
        "/api/auth/register",
        json={
            "invite_code": "invite-ok-001",
            "email": "teacher@test.local",
            "password": "test-pass-teacher1",
        },
        headers=HEADERS,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


async def _kid_session(client, *, band: str = BAND) -> str:
    """A confirmed, self-login-capable kid in the requested age band."""
    teacher = await _setup_teacher(client)
    cls = (await (await client.post(
        "/api/classes", json={"name": "AI Class"}, headers=_auth(teacher)
    )).json())["class"]
    invite = await (await client.post(
        "/api/invites",
        json={
            "class_id": cls["id"],
            "parent_email": "parent-kid@test.local",
            "first_name": "小明",
            "age_band": band,
            "lang_code": "zh-hk",
        },
        headers=_auth(teacher),
    )).json()
    student_id = _full_student_id()
    await client.post(
        f"/api/invites/{_latest_invite_token()}/confirm",
        json={"password": CONFIRM_PASSWORD, "privacy_policy": True, "chat_consent": True},
    )
    await client.post(
        f"/api/classes/{cls['id']}/confirm",
        json={"student_id": student_id},
        headers=_auth(teacher),
    )
    login = await client.post(
        "/api/student/login",
        json={"join_code": cls["join_code"], "pin": invite["pin"]},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login, "kid_session")


def _mark_consent(student_id: str, *, action: str = "agreed") -> None:
    """What scripts/mark_voice_consent.py does, without the CLI."""
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        parent_id = conn.execute(
            "SELECT parent_id FROM students WHERE id = ?", (student_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    cfg = consent_mod.get_doc_config("voice_consent")
    assert cfg is not None
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="voice_consent",
        doc_version=cfg["current_version"],
        action=action,
        ip="operator-script",
        user_agent="tests",
        student_id=student_id,
    )


class _StubStt:
    """Stands in for the provider call; records what it was handed."""

    def __init__(self, text: str = TRANSCRIPT):
        self.text = text
        self.calls: list[dict] = []

    async def __call__(self, audio, *, content_type, lang_hint=None, client=None):
        self.calls.append(
            {"bytes": len(audio), "content_type": content_type, "lang": lang_hint}
        )
        return voice_stt.SttResult(text=self.text, provider="azure", latency_ms=42)


@pytest.fixture
def stub_stt(monkeypatch):
    stub = _StubStt()
    monkeypatch.setattr(voice_stt, "transcribe", stub)
    return stub


def _enable_flag(monkeypatch):
    monkeypatch.setenv("VOICE_P1P3_ENABLED", "1")


# ---------------------------------------------------------------------------
# 1. The gate: mic invisible unless everything lines up
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_means_no_button_even_with_signed_consent(
    client, teacher_invite, tmp_path
):
    kid = await _kid_session(client)
    _mark_consent(_full_student_id())
    resp = await client.get("/api/voice/config", headers=_kid(kid))
    assert resp.status == 200
    assert await resp.json() == {"enabled": False}


@pytest.mark.asyncio
async def test_no_consent_row_means_no_button(client, teacher_invite, monkeypatch):
    """實施令 §3: 冇 consent 記錄 = 睇都睇唔到 mic 掣."""
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    resp = await client.get("/api/voice/config", headers=_kid(kid))
    assert resp.status == 200
    body = await resp.json()
    assert body == {"enabled": False}
    assert "reason" not in body  # never leaks why to the browser


@pytest.mark.asyncio
async def test_signed_consent_opens_the_button_with_segment_cap(
    client, teacher_invite, monkeypatch
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    _mark_consent(_full_student_id())
    body = await (await client.get("/api/voice/config", headers=_kid(kid))).json()
    assert body["enabled"] is True
    assert body["max_seconds"] == 60
    assert body["daily_remaining_seconds"] == 900
    assert body["max_upload_bytes"] == 2097152


@pytest.mark.asyncio
async def test_band_outside_allowed_set_means_no_button(
    client, teacher_invite, monkeypatch
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client, band="P4-P6")
    _mark_consent(_full_student_id())
    body = await (await client.get("/api/voice/config", headers=_kid(kid))).json()
    assert body == {"enabled": False}


@pytest.mark.asyncio
async def test_withdrawn_consent_closes_the_button_again(
    client, teacher_invite, monkeypatch
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    student_id = _full_student_id()
    _mark_consent(student_id)
    assert (await (await client.get("/api/voice/config", headers=_kid(kid))).json())[
        "enabled"
    ] is True
    _mark_consent(student_id, action="withdrawn")
    assert (await (await client.get("/api/voice/config", headers=_kid(kid))).json())[
        "enabled"
    ] is False


@pytest.mark.asyncio
async def test_config_requires_a_kid_session(client, teacher_invite, monkeypatch):
    _enable_flag(monkeypatch)
    assert (await client.get("/api/voice/config")).status == 401


# ---------------------------------------------------------------------------
# 2. Transcribe: same gate, sized before spending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_requires_a_kid_session(client, teacher_invite, monkeypatch):
    _enable_flag(monkeypatch)
    resp = await client.post(
        "/api/voice/transcribe",
        data={"duration_ms": "1000"},
        headers=HEADERS,
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_transcribe_is_csrf_guarded(client, teacher_invite, monkeypatch):
    """Kid POSTs carry the session cookie, so the custom header is required."""
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    resp = await client.post(
        "/api/voice/transcribe",
        data={"duration_ms": "1000"},
        headers={"Cookie": f"kid_session={kid}"},
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_transcribe_refused_when_gate_closed(
    client, teacher_invite, monkeypatch, stub_stt
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(3), declared_ms=3000),
        headers=_kid(kid),
    )
    assert resp.status == 403
    assert (await resp.json())["error"] == "語音輸入未開放"
    assert stub_stt.calls == []  # nothing spent upstream
    assert voice_quota.month_meter()["seconds"] == 0


@pytest.mark.asyncio
async def test_too_long_clip_refused_before_spending(
    client, teacher_invite, monkeypatch, stub_stt
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    _mark_consent(_full_student_id())
    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(70), declared_ms=70000),
        headers=_kid(kid),
    )
    assert resp.status == 400
    assert stub_stt.calls == []
    assert voice_quota.student_daily_seconds(_full_student_id()) == 0


@pytest.mark.asyncio
async def test_unmeasurable_clip_refused_rather_than_guessed(
    client, teacher_invite, monkeypatch, stub_stt
):
    """No WAV header and no declared length ⇒ refuse (can't price it)."""
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    _mark_consent(_full_student_id())
    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(b"\x1aE\xdf\xa3not-a-wav"),
        headers=_kid(kid),
    )
    assert resp.status == 400
    assert stub_stt.calls == []


@pytest.mark.asyncio
async def test_clip_within_tolerance_is_accepted(
    client, teacher_invite, monkeypatch, stub_stt
):
    """Stop is racy by a few hundred ms — a 61 s clip is not a 70 s clip."""
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    _mark_consent(_full_student_id())
    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(61), declared_ms=61000),
        headers=_kid(kid),
    )
    assert resp.status == 200


# ---------------------------------------------------------------------------
# 3. Success path: meters charged, transcript nowhere but the browser
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_returns_text_and_charges_the_meters(
    client, teacher_invite, monkeypatch, stub_stt, tmp_path
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    student_id = _full_student_id()
    _mark_consent(student_id)

    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(3), declared_ms=3000),
        headers=_kid(kid),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["text"] == TRANSCRIPT
    assert body["seconds_used"] == 3
    assert body["daily_remaining_seconds"] == 897
    assert stub_stt.calls[0]["bytes"] == len(_wav(3))
    assert stub_stt.calls[0]["lang"] == "en"

    assert voice_quota.student_daily_seconds(student_id) == 3
    assert voice_quota.month_meter()["seconds"] == 3

    # Privacy: the transcript never reaches the audit log (or any log) …
    for line in _audit_lines(tmp_path):
        assert TRANSCRIPT not in json.dumps(line, ensure_ascii=False)
    # … the audit line records a masked student, never the full id …
    usage = [ln for ln in _audit_lines(tmp_path) if ln.get("event") == "voice_usage"]
    assert len(usage) == 1
    assert usage[0]["seconds"] == 3
    assert usage[0]["student"] == voice_quota.mask_student_id(student_id)
    assert student_id[8:] not in json.dumps(usage)
    # … and the audio itself is not left on disk anywhere near the DB.
    for root, _dirs, files in os.walk(tmp_path):
        for name in files:
            with open(os.path.join(root, name), "rb") as fh:
                assert b"RIFF" not in fh.read()


@pytest.mark.asyncio
async def test_stt_failure_charges_nothing_and_keeps_kid_wording(
    client, teacher_invite, monkeypatch, tmp_path
):
    _enable_flag(monkeypatch)
    kid = await _kid_session(client)
    student_id = _full_student_id()
    _mark_consent(student_id)

    async def boom(audio, *, content_type, lang_hint=None, client=None):
        raise voice_stt.SttError("azure_http_500")

    monkeypatch.setattr(voice_stt, "transcribe", boom)
    resp = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(3), declared_ms=3000),
        headers=_kid(kid),
    )
    assert resp.status == 502
    body = await resp.json()
    assert body["error"] == "語音辨識暫時用唔到，可以打字問我"
    assert "azure_http_500" not in json.dumps(body)  # operator code stays server-side
    assert voice_quota.student_daily_seconds(student_id) == 0
    assert voice_quota.month_meter()["seconds"] == 0


# ---------------------------------------------------------------------------
# 4. The meters actually stop voice (gate 2, no code change)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_meter_stops_voice(client, teacher_invite, monkeypatch, stub_stt):
    _enable_flag(monkeypatch)
    # Cap and budget shrunk together: a 10 s budget cannot host the default
    # 60 s segment, so the gate reads "closed" — the same shape as the real
    # 15 min/day and 3000 min/month ceilings, just fast to exercise.
    monkeypatch.setenv("VOICE_MAX_SEGMENT_SECONDS", "10")
    monkeypatch.setenv("VOICE_DAILY_STUDENT_SECONDS", "10")
    kid = await _kid_session(client)
    student_id = _full_student_id()
    _mark_consent(student_id)

    first = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(5), declared_ms=5000),
        headers=_kid(kid),
    )
    assert first.status == 200, await first.text()
    assert voice_quota.student_daily_seconds(student_id) == 5

    # Button gone (less than one segment left) …
    assert (await (await client.get("/api/voice/config", headers=_kid(kid))).json())[
        "enabled"
    ] is False
    # … and the POST refuses too (never trust the client to stop asking).
    second = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(3), declared_ms=3000),
        headers=_kid(kid),
    )
    assert second.status == 403
    assert len(stub_stt.calls) == 1


@pytest.mark.asyncio
async def test_monthly_budget_stops_voice(
    client, teacher_invite, monkeypatch, stub_stt
):
    """The $50/mo auto-stop: once the global meter is spent, voice is off."""
    _enable_flag(monkeypatch)
    monkeypatch.setenv("VOICE_MAX_SEGMENT_SECONDS", "10")
    monkeypatch.setenv("VOICE_MONTHLY_GLOBAL_SECONDS", "10")
    kid = await _kid_session(client)
    student_id = _full_student_id()
    _mark_consent(student_id)

    first = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(5), declared_ms=5000),
        headers=_kid(kid),
    )
    assert first.status == 200, await first.text()
    assert voice_quota.month_meter()["seconds"] == 5

    assert (await (await client.get("/api/voice/config", headers=_kid(kid))).json())[
        "enabled"
    ] is False
    second = await client.post(
        "/api/voice/transcribe",
        data=_clip_form(_wav(1), declared_ms=1000),
        headers=_kid(kid),
    )
    assert second.status == 403
    assert len(stub_stt.calls) == 1


# ---------------------------------------------------------------------------
# 5. Clip length parsing (the number the meters are charged with)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wav_seconds_parser():
    assert api_mod._wav_seconds(_wav(3)) == pytest.approx(3.0, abs=0.01)
    assert api_mod._wav_seconds(b"\x1aE\xdf\xa3webm-opus-payload") is None
    assert api_mod._wav_seconds(b"") is None
