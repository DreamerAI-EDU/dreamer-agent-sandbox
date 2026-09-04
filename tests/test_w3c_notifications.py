"""W3-C notifications + teacher pending console + register→verify→login chain.

Spec: phase7-W3 開波 spec v1.3 §3 (W3-C). Covers:
 - 通知-1: parent confirm → class-owner teacher email (recipient follows the
   class owner, never hardcoded); fail-silent — SMTP failure never blocks
   the confirm flow — and every attempt leaves an audit row
 - 通知-2: teacher confirm → parent email (formal parent-facing tone, no
   action link)
 - GET /api/classes/{id}/pending: teacher console (full student ids on the
   trusted teacher surface), role gates (anon 401 / parent 403) + ownership
   gate (cross-teacher 403 with WARNING)
 - §3.1 acceptance chain at API level: register (teacher invite code) →
   verify email → login → GET /api/classes (empty state on a fresh teacher)
 - W3-C class metadata (boss ruling 2026-09-04): create accepts class_type /
   grade_band / is_one_on_one; list returns them; invalid enum values 400;
   apply_class_meta_migration is idempotent and preserves existing rows

No real emails: auth.email.send_email is mocked in every test that needs
it. No real passwords: test-pass- prefix only (B24 guard).
"""

from __future__ import annotations

import datetime
import json
import os
import uuid

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import security as auth_security  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CONFIRM_PASSWORD = "test-pass-parent1"


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    set_cookies = resp.headers.getall("Set-Cookie", [])
    for sc in set_cookies:
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no auth_session cookie in {set_cookies}")


async def _register_teacher(client, *, email="teacher@test.local",
                            password="test-pass-teacher1", invite="invite-ok-001"):
    return await client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": password},
        headers=HEADERS,
    )


async def _login(client, *, email="teacher@test.local",
                 password="test-pass-teacher1"):
    return await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )


async def _setup_logged_in_user(client, *, email="teacher@test.local",
                                password="test-pass-teacher1",
                                invite="invite-ok-001"):
    await _register_teacher(client, email=email, password=password, invite=invite)
    login = await _login(client, email=email, password=password)
    assert login.status == 200, await login.text()
    return _session_cookie(login)


def _create_parent_user(email="parent-a@test.local",
                        password="test-pass-parent1"):
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password(password),
        role="parent",
        email_verified=True,
    )
    return user_id, email, password


async def _login_parent(client, email, password):
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


def _conn():
    import sqlite3

    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _latest_invite_token():
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT token FROM invites ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no invites row in test DB"
    return row[0]


def _audit_events(tmp_path):
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
def fresh_invite():
    for code in ("invite-ok-001", "invite-ok-002", "invite-ok-003"):
        auth_db.insert_teacher_invite(
            code=code,
            created_by="admin-cli",
            expires_at=_future_iso(days=7),
        )


async def _create_class_via_api(client, token, *, name="Math Class"):
    resp = await client.post(
        "/api/classes",
        json={"name": name},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


async def _create_invite(
    client, token, class_id, *,
    parent_email="parent-x@test.local",
    first_name="小明",
    age_band="P1-P3",
    lang_code="zh-hk",
):
    resp = await client.post(
        "/api/invites",
        json={
            "class_id": class_id,
            "parent_email": parent_email,
            "first_name": first_name,
            "age_band": age_band,
            "lang_code": lang_code,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _confirm(client, token, *, password=CONFIRM_PASSWORD):
    """Parent 1-click confirm — deliberately NO CSRF header (email link)."""
    return await client.post(
        f"/api/invites/{token}/confirm",
        json={"password": password, "privacy_policy": True},
    )


def _capture_email(monkeypatch):
    sent = []

    def fake_send_email(*, to_addr, subject, body):
        sent.append({"to_addr": to_addr, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("auth.email.send_email", fake_send_email)
    return sent


# ---------------------------------------------------------------------------
# 通知-1: parent confirm → class-owner teacher email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify1_teacher_emailed_after_parent_confirm(
    client, fresh_invite, monkeypatch, tmp_path
):
    sent = _capture_email(monkeypatch)
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token, name="Math Class")
    await _create_invite(client, token, cls["id"], parent_email="p1@test.local")
    tok = _latest_invite_token()

    # Register fires a verification email; invite a second; 通知-1 a third.
    assert (await _confirm(client, tok)).status == 201
    assert len(sent) == 3
    notices = [m for m in sent if "Parent confirmed" in m["subject"]]
    assert len(notices) == 1
    notice = notices[0]
    assert notice["to_addr"] == "teacher@test.local"  # class owner, not p1
    assert "Parent confirmed" in notice["subject"]
    assert "/teacher" in notice["body"]
    assert "Math Class" in notice["body"]
    assert "小明 (P1-P3)" in notice["body"]

    events = _audit_events(tmp_path)
    notify = [e for e in events if e["event"] == "notify_teacher_pending"]
    assert len(notify) == 1
    assert notify[0]["ok"] is True
    assert notify[0]["teacher_id"] is not None
    assert notify[0]["class_id"] == cls["id"]


@pytest.mark.asyncio
async def test_notify1_recipient_follows_class_owner(
    client, fresh_invite, monkeypatch
):
    """Two teachers each with a class: each notice goes to its own owner."""
    sent = _capture_email(monkeypatch)

    # Teacher two (second invite code) creates the class that gets confirmed.
    t2 = await _setup_logged_in_user(
        client, email="teacher-two@test.local", invite="invite-ok-002"
    )
    cls2 = await _create_class_via_api(client, t2, name="T2 Class")
    await _create_invite(client, t2, cls2["id"], parent_email="p2@test.local")
    tok2 = _latest_invite_token()
    assert (await _confirm(client, tok2)).status == 201

    notices = [m for m in sent if "Parent confirmed" in m["subject"]]
    assert len(notices) == 1
    assert notices[0]["to_addr"] == "teacher-two@test.local"
    assert "teacher@test.local" not in notices[0]["to_addr"]
    assert "T2 Class" in notices[0]["body"]


@pytest.mark.asyncio
async def test_notify1_fail_silent_does_not_block_confirm(
    client, fresh_invite, monkeypatch, tmp_path
):
    def failing_email(*, to_addr, subject, body):
        return False  # SMTP unavailable — must not break the confirm flow

    monkeypatch.setattr("auth.email.send_email", failing_email)

    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"], parent_email="p1@test.local")
    tok = _latest_invite_token()

    resp = await _confirm(client, tok)
    assert resp.status == 201  # confirm itself succeeds

    events = _audit_events(tmp_path)
    notify = [e for e in events if e["event"] == "notify_teacher_pending"]
    assert len(notify) == 1
    assert notify[0]["ok"] is False
    assert notify[0]["level"] == "WARNING"


# ---------------------------------------------------------------------------
# 通知-2: teacher confirm → parent email (formal, no link)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify2_parent_emailed_after_teacher_confirm(
    client, fresh_invite, monkeypatch, tmp_path
):
    sent = _capture_email(monkeypatch)
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token, name="Math Class")
    await _create_invite(client, token, cls["id"], parent_email="p1@test.local")
    tok = _latest_invite_token()
    student_id = None
    conn = _conn()
    try:
        student_id = conn.execute(
            "SELECT student_id FROM invites WHERE token = ?", (tok,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert (await _confirm(client, tok)).status == 201

    # Teacher confirms the pending binding → 通知-2 to the parent.
    confirm = await client.post(
        f"/api/classes/{cls['id']}/confirm",
        json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert confirm.status == 200

    parent_notices = [m for m in sent if "Teacher confirmed" in m["subject"]]
    assert len(parent_notices) == 1
    assert parent_notices[0]["to_addr"] == "p1@test.local"
    assert "Math Class" in parent_notices[0]["body"]
    assert "小明 (P1-P3)" in parent_notices[0]["body"]
    # Parent-facing formal tone: no action link is embedded.
    assert "http" not in parent_notices[0]["body"]

    events = _audit_events(tmp_path)
    notify = [e for e in events if e["event"] == "notify_parent_confirmed"]
    assert len(notify) == 1
    assert notify[0]["ok"] is True
    assert notify[0]["parent_user_id"] is not None


# ---------------------------------------------------------------------------
# GET /api/classes/{id}/pending — teacher console
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_class_pending_lists_only_pending_students(
    client, fresh_invite, monkeypatch, tmp_path
):
    _capture_email(monkeypatch)
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)

    # Student A: stays pending.
    await _create_invite(client, token, cls["id"], parent_email="a@test.local")
    tok_a = _latest_invite_token()
    assert (await _confirm(client, tok_a)).status == 201
    conn = _conn()
    try:
        s_a = conn.execute(
            "SELECT student_id FROM invites WHERE token = ?", (tok_a,)
        ).fetchone()[0]
    finally:
        conn.close()

    # Student B: confirmed by the teacher, must not appear as pending.
    await _create_invite(
        client, token, cls["id"], parent_email="b@test.local", first_name="小英"
    )
    tok_b = _latest_invite_token()
    assert (await _confirm(client, tok_b)).status == 201
    conn = _conn()
    try:
        s_b = conn.execute(
            "SELECT student_id FROM invites WHERE token = ?", (tok_b,)
        ).fetchone()[0]
    finally:
        conn.close()
    resp = await client.post(
        f"/api/classes/{cls['id']}/confirm",
        json={"student_id": s_b},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 200

    pending_resp = await client.get(
        f"/api/classes/{cls['id']}/pending",
        headers={"Cookie": f"auth_session={token}"},
    )
    assert pending_resp.status == 200
    body = await pending_resp.json()
    assert body["class_id"] == cls["id"]
    assert len(body["pending"]) == 1
    row = body["pending"][0]
    # Trusted teacher surface: full student id, not the 8-char mask.
    assert row["student_id"] == s_a
    assert row["student_id"] != s_b
    assert row["first_name"] == "小明"
    assert row["age_band"] == "P1-P3"
    assert row["lang_code"] == "zh-hk"
    assert row["parent_email"] == "a@test.local"


@pytest.mark.asyncio
async def test_class_pending_role_and_owner_guards(
    client, fresh_invite, monkeypatch
):
    _capture_email(monkeypatch)
    t1 = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, t1)

    # Anonymous → 401.
    anon = await client.get(f"/api/classes/{cls['id']}/pending")
    assert anon.status == 401

    # Parent → 403.
    _, p_email, p_pw = _create_parent_user()
    p_token = await _login_parent(client, p_email, p_pw)
    parent = await client.get(
        f"/api/classes/{cls['id']}/pending",
        headers={"Cookie": f"auth_session={p_token}"},
    )
    assert parent.status == 403

    # Cross-teacher → 403 (unified wording, DAO ownership check).
    t2 = await _setup_logged_in_user(
        client, email="teacher-two@test.local", invite="invite-ok-002"
    )
    foreign = await client.get(
        f"/api/classes/{cls['id']}/pending",
        headers={"Cookie": f"auth_session={t2}"},
    )
    assert foreign.status == 403
    assert (await foreign.json())["error"] == "無權操作"


# ---------------------------------------------------------------------------
# §3.1 acceptance chain (API leg): register → verify → login → /teacher data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_teacher_register_verify_login_landing_chain(
    client, fresh_invite, monkeypatch, tmp_path
):
    """API-equivalent of the §3.1 chain. The real-browser /teacher leg is
    the E2E check; here the empty-state list proves the landing data works
    for a fresh teacher account."""
    _capture_email(monkeypatch)

    reg = await _register_teacher(
        client,
        email="teacher-new@test.local",
        password="test-pass-teacher3",
        invite="invite-ok-003",
    )
    assert reg.status == 201, await reg.text()

    user = auth_db.get_user_by_email("teacher-new@test.local")
    assert int(user["email_verified"]) == 0
    verify_token = user["email_verify_token"]
    assert verify_token is not None

    ver = await client.post(
        "/api/auth/verify-email",
        json={"token": verify_token},
        headers=HEADERS,
    )
    assert ver.status == 200
    assert (await ver.json())["user"]["email_verified"] is True

    login = await _login(
        client, email="teacher-new@test.local", password="test-pass-teacher3"
    )
    assert login.status == 200
    t_token = _session_cookie(login)

    landing = await client.get(
        "/api/classes", headers={"Cookie": f"auth_session={t_token}"}
    )
    assert landing.status == 200
    assert (await landing.json())["classes"] == []  # empty state


async def test_class_meta_create_and_list_return_new_fields(client, fresh_invite):
    """POST /api/classes accepts W3-C fields; GET /api/classes echoes them."""
    token = await _setup_logged_in_user(
        client,
        email="teacher-meta@test.local",
        password="test-pass-tm1",
        invite="invite-ok-001",
    )
    resp = await client.post(
        "/api/classes",
        json={
            "name": "K1 Phonics",
            "class_type": "workshop",
            "grade_band": "P1-P3",
            "is_one_on_one": True,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    created = (await resp.json())["class"]
    assert created["class_type"] == "workshop"
    assert created["grade_band"] == "P1-P3"
    assert created["is_one_on_one"] == 1

    listing = await client.get(
        "/api/classes", headers={"Cookie": f"auth_session={token}"}
    )
    assert listing.status == 200
    payload = await listing.json()
    assert len(payload["classes"]) == 1
    c = payload["classes"][0]
    assert c["class_type"] == "workshop"
    assert c["grade_band"] == "P1-P3"
    assert c["is_one_on_one"] == 1


async def test_class_meta_defaults_when_omitted(client, fresh_invite):
    """Old clients that send only a name keep working: monthly / NULL / 0."""
    token = await _setup_logged_in_user(
        client,
        email="teacher-meta2@test.local",
        password="test-pass-teacher-meta2",
        invite="invite-ok-002",
    )
    cls = await _create_class_via_api(client, token, name="Default Class")
    assert cls["class_type"] == "monthly"
    assert cls["grade_band"] is None
    assert cls["is_one_on_one"] == 0


async def test_class_meta_rejects_invalid_enum_values(client, fresh_invite):
    token = await _setup_logged_in_user(
        client,
        email="teacher-meta3@test.local",
        password="test-pass-teacher-meta3",
        invite="invite-ok-003",
    )
    for body in (
        {"name": "X", "class_type": "trial"},
        {"name": "X", "grade_band": "S4-S6"},
        {"name": "X", "class_type": "workshop", "grade_band": "primary"},
    ):
        resp = await client.post(
            "/api/classes",
            json=body,
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 400, (body, await resp.text())


async def test_class_list_role_gate_parent_403(client, fresh_invite):
    """Spec §3.1 boundary 4: GET /api/classes is teacher-only — parent gets 403."""
    token = await _setup_logged_in_user(
        client,
        email="teacher-meta4@test.local",
        password="test-pass-teacher-meta4",
        invite="invite-ok-003",
    )
    await _create_class_via_api(client, token, name="Gate Class")

    _, p_email, p_pw = _create_parent_user()
    p_token = await _login_parent(client, p_email, p_pw)
    resp = await client.get(
        "/api/classes",
        headers={"Cookie": f"auth_session={p_token}"},
    )
    assert resp.status == 403
    assert (await resp.json())["error"] == "無權操作"


def test_class_meta_migration_idempotent(tmp_path, monkeypatch):
    """apply_class_meta_migration adds columns once on an old-schema DB,
    backfills existing rows via DEFAULT, and is safe to re-run."""
    import sqlite3

    db_path = tmp_path / "migrate_test.db"
    monkeypatch.setenv("DREAMER_DB_PATH", str(db_path))
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE classes (
                id            TEXT PRIMARY KEY,
                teacher_id    TEXT NOT NULL,
                name          TEXT NOT NULL,
                join_code     TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
            INSERT INTO classes (id, teacher_id, name, join_code, created_at)
            VALUES ('c-old', 't-1', 'TEST-Old', 'ABC123', '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()

    auth_db.apply_class_meta_migration()

    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(classes)")}
        assert {"class_type", "grade_band", "is_one_on_one"} <= cols
        row = conn.execute(
            "SELECT class_type, grade_band, is_one_on_one FROM classes WHERE id='c-old'"
        ).fetchone()
        assert tuple(row) == ("monthly", None, 0)
    finally:
        conn.close()

    auth_db.apply_class_meta_migration()  # second run: no-op, no error
