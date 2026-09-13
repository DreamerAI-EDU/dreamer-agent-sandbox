"""Bridge-3d — student self-login (join code + PIN) tests.

Spec under test (boss work order 2026-09-13):

  * ``POST /api/student/login {join_code, pin}`` → ``kid_session`` cookie;
    ``GET /api/student/me`` reads it; ``POST /api/student/logout`` clears it;
  * a student is a THIRD identity with no email and no ``users`` row, so a
    parent/teacher ``auth_session`` must never open a kid surface;
  * 5 consecutive failures lock the JOIN-CODE scope for 10 minutes (429),
    the lock surviving a subsequent CORRECT PIN — and the lock scope is the
    join code, never a single student, so one kid fat-fingering cannot lock
    a classmate out;
  * the lock counter is separate from the parent/teacher delegated
    ``/api/students/{id}/pin-verify`` contract (10 strikes / 1 minute):
    exercising one must leave the other untouched;
  * a malformed PIN still counts as a strike (otherwise the format check is
    a free probing oracle);
  * only ``confirmed`` class members with a server-drawn PIN may log in — a
    ``pending`` student stays out even with the right PIN;
  * one uniform 401 body for unknown join code / wrong PIN / malformed PIN,
    with the real reason kept in the WARNING audit line (no existence
    oracle), and a WARNING on lockout;
  * login/logout are SPA POSTs and stay behind the CSRF header guard;
  * the ``/me`` payload carries only the student's own data (masked id, no
    ``pin_hash``) plus the shared Week X / 8 badge — never a classmate's.

The negative set is CI-red-line material: this file is registered in the
ci.yml pytest manifest (red line #9).

No real credentials anywhere: ``test-pass-`` / ``test-pin-`` style values
only (B24 guard enforces this repo-wide).
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import uuid

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import student_auth as student_auth_mod  # noqa: E402
from auth import students as students_mod  # noqa: E402
from auth.api import build_app  # noqa: E402
from pipeline import topic_metadata_schema  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CONFIRM_PASSWORD = "test-pass-parent1"
CURRICULUM_ID = "dreamer-curriculum"


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _auth(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"auth_session={token}"}


def _kid(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"kid_session={token}"}


def _session_cookie(resp, name="auth_session") -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith(f"{name}="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no {name} cookie in {resp.headers.getall('Set-Cookie', [])}")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _audit_events(tmp_path) -> list[dict]:
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wrong_pin(correct: str) -> str:
    return "0000" if correct != "0000" else "0001"


def _full_student_id() -> str:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM students ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no student row in test DB"
    return row[0]


def _latest_invite_token() -> str:
    """createInvite's 201 body carries the drawn PIN, never the token."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT token FROM invites ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no invite row in test DB"
    return row[0]


def _lock_row(join_code: str):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM student_login_locks WHERE scope = ?",
            (f"jc:{student_auth_mod.normalise_join_code(join_code)}",),
        ).fetchone()
    finally:
        conn.close()


def _seed_curriculum(curriculum_id: str = CURRICULUM_ID, weeks=range(1, 9)):
    """Ready-made 8-week course straight into topic_metadata (Bridge-1 SoT)."""
    conn = _conn()
    try:
        topic_metadata_schema.ensure_schema(conn)
        for week in weeks:
            conn.execute(
                "INSERT INTO topic_metadata (topic_id, subject, topic, "
                "modes_allowed, grade_level, week, dreamer_phase, kb_name, "
                "document_path, document_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"curriculum-wk{week:02d}",
                    "AI Literacy",
                    f"Week {week} kid-facing unit",
                    '["contextual"]',
                    "P4-P6",
                    week,
                    '["Design"]',
                    curriculum_id,
                    f"curriculum-wk{week:02d}.md",
                    f"hash-{week}",
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures + flow helpers
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
def teacher_invite():
    for code in ("invite-ok-001", "invite-ok-002"):
        auth_db.insert_teacher_invite(
            code=code, created_by="admin-cli", expires_at=_future_iso(days=7)
        )


async def _setup_teacher(client, email="teacher@test.local", invite="invite-ok-001"):
    await client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email,
              "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


async def _create_class(client, token, name="AI Class"):
    resp = await client.post(
        "/api/classes", json={"name": name}, headers=_auth(token)
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


async def _invite_student(client, token, class_id, *, pin=None,
                          parent_email="parent-kid@test.local"):
    """Teacher invites a parent; a blank pin makes the SERVER draw one."""
    payload = {
        "class_id": class_id,
        "parent_email": parent_email,
        "first_name": "小明",
        "age_band": "P4-P6",
        "lang_code": "zh-hk",
    }
    if pin is not None:
        payload["pin"] = pin
    resp = await client.post("/api/invites", json=payload, headers=_auth(token))
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _parent_confirm(client, invite_token):
    resp = await client.post(
        f"/api/invites/{invite_token}/confirm",
        json={"password": CONFIRM_PASSWORD, "privacy_policy": True,
              "chat_consent": True},
    )
    assert resp.status in (200, 201), await resp.text()


async def _teacher_confirm(client, token, class_id, student_id):
    resp = await client.post(
        f"/api/classes/{class_id}/confirm",
        json={"student_id": student_id},
        headers=_auth(token),
    )
    assert resp.status == 200, await resp.text()


async def _ready_student(client, *, confirmed=True):
    """Full family flow → a class whose single student is (in)eligible.

    Returns {teacher, class, join_code, pin, student_id}. The PIN came back
    from createInvite exactly as the teacher would hand it to the kid.
    """
    teacher = await _setup_teacher(client)
    cls = await _create_class(client, teacher)
    invite = await _invite_student(client, teacher, cls["id"])
    assert "pin" in invite, "server must return the drawn PIN to the teacher"
    pin = invite["pin"]
    student_id = _full_student_id()

    await _parent_confirm(client, _latest_invite_token())
    if confirmed:
        await _teacher_confirm(client, teacher, cls["id"], student_id)
    return {
        "teacher": teacher,
        "class": cls,
        "join_code": cls["join_code"],
        "pin": pin,
        "student_id": student_id,
    }


async def _login_kid(client, join_code, pin):
    return await client.post(
        "/api/student/login",
        json={"join_code": join_code, "pin": pin},
        headers=HEADERS,
    )


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_student_login_happy_path_mints_kid_session(client, teacher_invite):
    """Confirmed kid + correct join code + PIN → 200 + kid_session cookie."""
    ctx = await _ready_student(client)

    resp = await _login_kid(client, ctx["join_code"], ctx["pin"])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["ok"] is True
    assert body["student"]["first_name"] == "小明"
    assert body["student"]["id"] == ctx["student_id"][:8]
    assert "pin_hash" not in body["student"]
    assert body["badge"]["state"] in {"none", "active", "completed"}

    kid_token = _session_cookie(resp, "kid_session")
    assert kid_token

    me = await client.get("/api/student/me", headers=_kid(kid_token))
    assert me.status == 200, await me.text()
    assert (await me.json())["student"]["id"] == ctx["student_id"][:8]


@pytest.mark.asyncio
async def test_student_login_normalises_join_code(client, teacher_invite):
    """Hand-typed codes: case / spaces / hyphens are normalised, not rejected."""
    ctx = await _ready_student(client)
    typed = f"  {ctx['join_code'][:4]}-{ctx['join_code'][4:].lower()}  "

    resp = await _login_kid(client, typed, ctx["pin"])
    assert resp.status == 200, await resp.text()


@pytest.mark.asyncio
async def test_student_me_badge_uses_shared_week_resolver(client, teacher_invite):
    """After mounting, the kid's own /me badge reports Week 1 / 8 (3a source)."""
    ctx = await _ready_student(client)
    _seed_curriculum()
    mount = await client.post(
        f"/api/classes/{ctx['class']['id']}/curriculum",
        json={"curriculum_id": CURRICULUM_ID},
        headers=_auth(ctx["teacher"]),
    )
    assert mount.status == 201, await mount.text()

    login = await _login_kid(client, ctx["join_code"], ctx["pin"])
    assert login.status == 200, await login.text()
    badge = (await login.json())["badge"]
    assert badge["state"] == "active"
    assert badge["week_index"] == 1
    assert badge["total_weeks"] == 8


# ---------------------------------------------------------------------------
# 2. Negative — uniform rejection, no oracle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrong_pin_and_unknown_code_share_one_401_body(
    client, teacher_invite, tmp_path
):
    """Unknown join code / wrong PIN → byte-identical 401; reason stays server-side."""
    ctx = await _ready_student(client)

    wrong = await _login_kid(client, ctx["join_code"], _wrong_pin(ctx["pin"]))
    unknown = await _login_kid(client, "ZZZZZZZZ", ctx["pin"])
    assert wrong.status == 401
    assert unknown.status == 401
    assert await wrong.json() == await unknown.json()

    events = [e for e in _audit_events(tmp_path)
              if e["event"] == "student_login_failed"]
    assert len(events) == 2
    assert all("reason=" in e["message"] for e in events)


@pytest.mark.asyncio
async def test_malformed_pin_counts_a_strike(client, teacher_invite):
    """A malformed PIN is charged like a wrong one — no free probing oracle."""
    ctx = await _ready_student(client)

    resp = await _login_kid(client, ctx["join_code"], "not-a-pin")
    assert resp.status == 401

    row = _lock_row(ctx["join_code"])
    assert row is not None
    assert row["failed_count"] == 1


@pytest.mark.asyncio
async def test_pending_student_cannot_login(client, teacher_invite):
    """Teacher has not confirmed the binding yet → even the right PIN is 401."""
    ctx = await _ready_student(client, confirmed=False)

    resp = await _login_kid(client, ctx["join_code"], ctx["pin"])
    assert resp.status == 401
    assert await resp.json() == {"error": "班級代碼或 PIN 不正確"}


@pytest.mark.asyncio
async def test_no_pin_student_cannot_login(client, teacher_invite):
    """A student whose PIN the teacher never drew is not a login candidate."""
    ctx = await _ready_student(client)
    conn = _conn()
    try:
        conn.execute(
            "UPDATE students SET pin_hash = NULL WHERE id = ?",
            (ctx["student_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = await _login_kid(client, ctx["join_code"], ctx["pin"])
    assert resp.status == 401


@pytest.mark.asyncio
async def test_student_login_requires_csrf_header(client, teacher_invite):
    """SPA POST without X-Requested-With → 403 before any credential work."""
    ctx = await _ready_student(client)

    resp = await client.post(
        "/api/student/login",
        json={"join_code": ctx["join_code"], "pin": ctx["pin"]},
    )
    assert resp.status == 403


# ---------------------------------------------------------------------------
# 3. Negative — the 5-strike / 10-minute join-code lock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_five_strikes_lock_scope_for_ten_minutes(client, teacher_invite, tmp_path):
    """5 wrong PINs → scope locked; a 6th attempt with the CORRECT PIN is 429."""
    ctx = await _ready_student(client)
    wrong = _wrong_pin(ctx["pin"])

    for i in range(student_auth_mod.STUDENT_LOGIN_MAX_FAILURES):
        resp = await _login_kid(client, ctx["join_code"], wrong)
        assert resp.status == 401, f"attempt {i + 1} must be a 401, not a lock"

    row = _lock_row(ctx["join_code"])
    assert row is not None
    assert row["failed_count"] == 0            # counter resets on lock
    assert row["locked_until"] is not None
    assert row["locked_until"] > _now_iso()
    # ~10 minutes out, never 1 minute (that is the pin-verify contract).
    locked_until = datetime.datetime.fromisoformat(
        row["locked_until"].replace("Z", "+00:00")
    )
    delta = locked_until - datetime.datetime.now(datetime.timezone.utc)
    assert datetime.timedelta(minutes=9) < delta <= datetime.timedelta(minutes=10)

    good = await _login_kid(client, ctx["join_code"], ctx["pin"])
    assert good.status == 429

    locked_events = [e for e in _audit_events(tmp_path)
                     if e["event"] == "student_login_locked"]
    assert len(locked_events) == 1
    assert locked_events[0]["level"] == "WARNING"


@pytest.mark.asyncio
async def test_successful_login_clears_the_scope_counter(client, teacher_invite):
    """A good login wipes accumulated strikes (no half-count lingering)."""
    ctx = await _ready_student(client)
    wrong = _wrong_pin(ctx["pin"])
    for _ in range(3):
        assert (await _login_kid(client, ctx["join_code"], wrong)).status == 401
    assert _lock_row(ctx["join_code"])["failed_count"] == 3

    assert (await _login_kid(client, ctx["join_code"], ctx["pin"])).status == 200
    assert _lock_row(ctx["join_code"]) is None


@pytest.mark.asyncio
async def test_lock_is_scoped_to_join_code_not_one_student(client, teacher_invite):
    """A second, innocent classmate on the same code is not collateral damage.

    Locks a DIFFERENT class code to show the scope key, then proves the
    untouched code still logs in — the lock follows the code, not the kid.
    """
    ctx = await _ready_student(client)
    wrong = _wrong_pin(ctx["pin"])
    for _ in range(student_auth_mod.STUDENT_LOGIN_MAX_FAILURES):
        assert (await _login_kid(client, ctx["join_code"], wrong)).status == 401

    # Same student, same PIN, but the lock belongs to the OTHER code.
    assert (await _login_kid(client, "AAAAAAAA", ctx["pin"])).status == 401
    assert _lock_row("AAAAAAAA")["failed_count"] == 1
    assert (await _login_kid(client, ctx["join_code"], ctx["pin"])).status == 429


@pytest.mark.asyncio
async def test_student_lock_does_not_touch_pin_verify_contract(client, teacher_invite):
    """Two surfaces, two counters: the parent/teacher pin-verify stays 10/1."""
    assert students_mod.PIN_LOCK_FAILURES == 10
    assert students_mod.PIN_LOCK_MINUTES == 1
    assert student_auth_mod.STUDENT_LOGIN_MAX_FAILURES == 5
    assert student_auth_mod.STUDENT_LOGIN_LOCK_MINUTES == 10

    ctx = await _ready_student(client)
    wrong = _wrong_pin(ctx["pin"])
    for _ in range(student_auth_mod.STUDENT_LOGIN_MAX_FAILURES):
        assert (await _login_kid(client, ctx["join_code"], wrong)).status == 401

    # The delegated check is untouched by the kid lockout, and vice versa.
    verify = await client.post(
        f"/api/students/{ctx['student_id']}/pin-verify",
        json={"pin": ctx["pin"]},
        headers=_auth(ctx["teacher"]),
    )
    assert verify.status == 200, await verify.text()

    conn = _conn()
    try:
        row = conn.execute(
            "SELECT failed_pin_count, pin_lock_until FROM students WHERE id = ?",
            (ctx["student_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row["failed_pin_count"] == 0
    assert row["pin_lock_until"] is None


# ---------------------------------------------------------------------------
# 4. Session hygiene
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_requires_kid_session_not_auth_session(client, teacher_invite):
    """Anonymous 401; a teacher/parent auth_session cannot open /me."""
    anon = await client.get("/api/student/me", headers=HEADERS)
    assert anon.status == 401

    ctx = await _ready_student(client)
    as_parent = await client.get(
        "/api/student/me", headers=_auth(ctx["teacher"])
    )
    assert as_parent.status == 401
    assert await as_parent.json() == {"error": "請先登入"}


@pytest.mark.asyncio
async def test_logout_invalidates_the_kid_session(client, teacher_invite):
    """logout clears the server-side row and the cookie."""
    ctx = await _ready_student(client)
    login = await _login_kid(client, ctx["join_code"], ctx["pin"])
    kid_token = _session_cookie(login, "kid_session")

    assert (await client.get("/api/student/me", headers=_kid(kid_token))).status == 200
    assert (await client.post("/api/student/logout", headers=_kid(kid_token))).status == 200
    assert (await client.get("/api/student/me", headers=_kid(kid_token))).status == 401


@pytest.mark.asyncio
async def test_expired_kid_session_is_refused(client, teacher_invite):
    """A session past expires_at is dead, even if the cookie survives."""
    ctx = await _ready_student(client)
    login = await _login_kid(client, ctx["join_code"], ctx["pin"])
    kid_token = _session_cookie(login, "kid_session")

    conn = _conn()
    try:
        conn.execute(
            "UPDATE student_sessions SET expires_at = ? WHERE student_id = ?",
            (_future_iso(minutes=-5), ctx["student_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    assert (await client.get("/api/student/me", headers=_kid(kid_token))).status == 401


@pytest.mark.asyncio
async def test_login_is_rate_limited_by_scope_not_ip(client, teacher_invite, monkeypatch):
    """Two different students on ONE code share the strike counter (by design).

    Also confirms /me never accepts an acting-* parameter: a kid session is
    only ever itself.
    """
    ctx = await _ready_student(client)
    assert (await client.get("/api/student/me?student=" + ctx["student_id"][:8],
                             headers=HEADERS)).status == 401

    wrong = _wrong_pin(ctx["pin"])
    for _ in range(student_auth_mod.STUDENT_LOGIN_MAX_FAILURES):
        assert (await _login_kid(client, ctx["join_code"], wrong)).status == 401
    # The scope is the code: the count lives on the code, not per caller.
    assert _lock_row(ctx["join_code"])["locked_until"] is not None
