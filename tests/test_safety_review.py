"""W2 PR#4 — safety review API + step-up auth tests (15 cases, brief §4).

Covers: teacher list pointer-only inbox (own class students, newest first),
`raw_input` never appears in the list body, role guards (parent 403 /
anonymous 401), step-up gate on detail (not stepped up / expired /
wrong password counting into the existing failed_logins machinery),
safety_detail_viewed audit trail, cross-teacher detail+review blocked with
a security WARNING and no DB mutation, review marking, unknown-id unified
403, ?reviewed=false filter, the new sessions.stepped_up_until column, and
the admin path (DB-seeded role=admin bypasses the class filter but still
must step up and still writes the audit line).

Discipline (brief §6): fixture raw_input is a fake sentence only
("test-distress-sentence") — no realistic student distress wording, not
even in test data. No real passwords: `test-pass-*` / `test-pin-*`.
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
from auth import security as auth_security  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

CONFIRM_PASSWORD = "test-pass-parent1"
FAKE_RAW_INPUT = "test-distress-sentence"

# Mirrors auth/safety.py (and migrations/phase2.5_safety_events.sql) so the
# test DB can bootstrap the table without a migration runner.
_SAFETY_DDL = """\
CREATE TABLE IF NOT EXISTS safety_events (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    matched_rule TEXT,
    age_band TEXT,
    lang_code TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


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


def _register_teacher(client, *, email="teacher@test.local",
                      password="test-pass-teacher1", invite="invite-ok-001"):
    return client.post(
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


def _db_path():
    return os.environ["DREAMER_DB_PATH"]


def _conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SAFETY_DDL)
    conn.commit()
    return conn


def _user_row(user_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def _invite_row(token):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM invites WHERE token = ?", (token,)
        ).fetchone()
    finally:
        conn.close()


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


def _session_row(token):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (token,)
        ).fetchone()
    finally:
        conn.close()


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
    # Two teacher invite codes so a second teacher can be registered for
    # cross-teacher scenarios.
    for code in ("invite-ok-001", "invite-ok-002"):
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
    pin=None,
):
    payload = {
        "class_id": class_id,
        "parent_email": parent_email,
        "first_name": first_name,
        "age_band": age_band,
        "lang_code": lang_code,
    }
    if pin is not None:
        payload["pin"] = pin
    resp = await client.post(
        "/api/invites",
        json=payload,
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _confirm(client, token, *, privacy=True, media=False,
                   password=CONFIRM_PASSWORD):
    """Parent 1-click confirm — deliberately NO CSRF header (email link)."""
    payload = {"password": password}
    if privacy is not None:
        payload["privacy_policy"] = privacy
    if media:
        payload["media_consent"] = True
    return await client.post(f"/api/invites/{token}/confirm", json=payload)


async def _make_teacher_with_student(
    client,
    *,
    teacher_email="teacher@test.local",
    teacher_password="test-pass-teacher1",
    invite="invite-ok-001",
    parent_email="parent-x@test.local",
    first_name="小明",
    class_name="Math Class",
):
    """Full happy path: register teacher -> class -> invite -> parent
    confirm -> teacher confirm binding. Returns (token, class_id,
    student_id)."""
    token = await _setup_logged_in_user(
        client, email=teacher_email, password=teacher_password, invite=invite
    )
    cls = await _create_class_via_api(client, token, name=class_name)
    await _create_invite(
        client, token, cls["id"],
        parent_email=parent_email, first_name=first_name, pin="1357",
    )
    invite_token = _latest_invite_token()
    confirm = await _confirm(client, invite_token)
    assert confirm.status == 201, await confirm.text()

    student_id = _invite_row(invite_token)["student_id"]
    bind = await client.post(
        f"/api/classes/{cls['id']}/confirm",
        json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert bind.status == 200, await bind.text()
    return token, cls["id"], student_id


def _insert_event(
    student_id,
    *,
    event_id=None,
    event_type="distress_signal",
    severity="high",
    reviewed=False,
    created_at=None,
):
    conn = _conn()
    try:
        eid = event_id or f"evt-test-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO safety_events "
            "(id, student_id, event_type, severity, raw_input, reviewed,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid, student_id, event_type, severity, FAKE_RAW_INPUT,
                1 if reviewed else 0,
                created_at or _future_iso(),
            ),
        )
        conn.commit()
        return eid
    finally:
        conn.close()


def _event_row(event_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM safety_events WHERE id = ?", (event_id,)
        ).fetchone()
    finally:
        conn.close()


async def _step_up(client, token, *, password="test-pass-teacher1"):
    return await client.post(
        "/api/auth/step-up",
        json={"password": password},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )


async def _list_events(client, token, *, reviewed=None):
    url = "/api/teacher/safety-events"
    if reviewed is not None:
        url += f"?reviewed={reviewed}"
    return await client.get(
        url, headers={"Cookie": f"auth_session={token}"}
    )


async def _detail(client, token, event_id):
    return await client.get(
        f"/api/teacher/safety-events/{event_id}",
        headers={"Cookie": f"auth_session={token}"},
    )


async def _review(client, token, event_id):
    return await client.post(
        f"/api/teacher/safety-events/{event_id}/review",
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )


# ---------------------------------------------------------------------------
# 1. Teacher list — own class students only, newest first
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_own_class_events_newest_first(client, fresh_invite):
    t1_token, _, stu1 = await _make_teacher_with_student(
        client, teacher_email="teacher@test.local",
        parent_email="parent-x@test.local",
    )
    _, _, stu2 = await _make_teacher_with_student(
        client, teacher_email="teacher2@test.local",
        teacher_password="test-pass-teacher2",
        invite="invite-ok-002",
        parent_email="parent-y@test.local",
        first_name="小美",
        class_name="English Class",
    )
    old_evt = _insert_event(
        stu1, created_at=_future_iso(minutes=-30)
    )
    _insert_event(stu2, created_at=_future_iso(minutes=-20))
    new_evt = _insert_event(
        stu1, created_at=_future_iso(minutes=-10)
    )

    resp = await _list_events(client, t1_token)
    assert resp.status == 200, await resp.text()
    events = (await resp.json())["events"]

    assert [e["event_id"] for e in events] == [new_evt, old_evt]
    assert all(e["student_first_name"] == "小明" for e in events)
    assert all(e["event_type"] == "distress_signal" for e in events)
    assert all(e["severity"] == "high" for e in events)
    assert all(e["reviewed"] is False for e in events)


# ---------------------------------------------------------------------------
# 2. List response never contains raw_input (string-level grep)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_response_has_no_raw_input_key(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    _insert_event(stu)

    resp = await _list_events(client, token)
    assert resp.status == 200, await resp.text()
    body = await resp.text()
    assert "raw_input" not in body
    assert FAKE_RAW_INPUT not in body


# ---------------------------------------------------------------------------
# 3. Parent role -> 403 on all three endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parent_forbidden_on_all_endpoints(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    _, email, pw = _create_parent_user()
    p_token = await _login_parent(client, email, pw)

    lst = await _list_events(client, p_token)
    assert lst.status == 403

    det = await _detail(client, p_token, evt)
    assert det.status == 403

    rev = await _review(client, p_token, evt)
    assert rev.status == 403


# ---------------------------------------------------------------------------
# 4. Anonymous -> 401 on all three endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anonymous_unauthorized(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    lst = await client.get("/api/teacher/safety-events")
    assert lst.status == 401

    det = await client.get(f"/api/teacher/safety-events/{evt}")
    assert det.status == 401

    rev = await client.post(
        f"/api/teacher/safety-events/{evt}/review", headers=HEADERS
    )
    assert rev.status == 401


# ---------------------------------------------------------------------------
# 5. Detail without step-up -> 403 + unified wording, raw_input absent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_requires_step_up(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    resp = await _detail(client, token, evt)
    assert resp.status == 403
    assert "需要重新驗證密碼" == (await resp.json())["error"]
    body = await resp.text()
    assert "raw_input" not in body
    assert FAKE_RAW_INPUT not in body


# ---------------------------------------------------------------------------
# 6. Step-up ok -> detail shows raw_input + audit trail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_up_then_detail_shows_raw_input_and_audit(
    client, fresh_invite, tmp_path
):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    step = await _step_up(client, token)
    assert step.status == 200, await step.text()
    assert (await step.json())["ok"] is True

    resp = await _detail(client, token, evt)
    assert resp.status == 200, await resp.text()
    event = (await resp.json())["event"]
    assert event["raw_input"] == FAKE_RAW_INPUT
    assert event["student_first_name"] == "小明"
    # Masked student id (PR#3 convention) — no full id in the response.
    assert event["student_id"] == stu[:8]
    assert stu not in json.dumps(event)

    audits = _audit_events(tmp_path)
    viewed = [
        a for a in audits
        if a["event"] == "safety_detail_viewed" and a["event_id"] == evt
    ]
    assert len(viewed) == 1
    assert viewed[0]["user_id"] == auth_db.get_user_by_email(
        "teacher@test.local"
    )["id"]


# ---------------------------------------------------------------------------
# 7. Step-up wrong password -> unified wording + failed_logins counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_up_wrong_password_counts_failed_logins(
    client, fresh_invite
):
    token, _, stu = await _make_teacher_with_student(client)
    _insert_event(stu)

    resp = await _step_up(client, token, password="test-pass-wrong")
    assert resp.status == 401
    assert "email 或密碼不正確" == (await resp.json())["error"]

    user = auth_db.get_user_by_email("teacher@test.local")
    assert _user_row(user["id"])["failed_logins"] == 1


# ---------------------------------------------------------------------------
# 8. Step-up expired (11 min later) -> detail rejected again
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_up_expired_after_11_minutes(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    step = await _step_up(client, token)
    assert step.status == 200
    assert _session_row(token)["stepped_up_until"] is not None

    # Simulate the clock moving 11 minutes past the step-up window: the
    # server-side session marker falls below "now" and the next request
    # must be rejected (the check reads the session fresh per request).
    expired = _future_iso(minutes=-11)
    conn = _conn()
    try:
        conn.execute(
            "UPDATE sessions SET stepped_up_until = ? WHERE id = ?",
            (expired, token),
        )
        conn.commit()
    finally:
        conn.close()

    resp = await _detail(client, token, evt)
    assert resp.status == 403
    assert "需要重新驗證密碼" == (await resp.json())["error"]
    assert "raw_input" not in await resp.text()


# ---------------------------------------------------------------------------
# 9. Cross-teacher detail -> 403 + security WARNING, raw_input absent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_teacher_detail_blocked(client, fresh_invite, tmp_path):
    t1_token, _, _ = await _make_teacher_with_student(
        client, teacher_email="teacher@test.local",
        parent_email="parent-x@test.local",
    )
    _, _, stu2 = await _make_teacher_with_student(
        client, teacher_email="teacher2@test.local",
        teacher_password="test-pass-teacher2",
        invite="invite-ok-002",
        parent_email="parent-y@test.local",
        first_name="小美",
        class_name="English Class",
    )
    other_evt = _insert_event(stu2)

    # t1 must still step up (gate runs before ownership check).
    step = await _step_up(client, t1_token)
    assert step.status == 200

    resp = await _detail(client, t1_token, other_evt)
    assert resp.status == 403
    body = await resp.text()
    assert "raw_input" not in body
    assert FAKE_RAW_INPUT not in body

    audits = _audit_events(tmp_path)
    warnings = [
        a for a in audits
        if a["level"] == "WARNING"
        and a["event"] == "safety_detail_cross_access"
        and a["target_id"] == other_evt
    ]
    assert len(warnings) == 1
    assert warnings[0]["user_id"] == auth_db.get_user_by_email(
        "teacher@test.local"
    )["id"]


# ---------------------------------------------------------------------------
# 10. Cross-teacher review -> 403 + WARNING; DB three columns untouched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_teacher_review_blocked_no_db_change(
    client, fresh_invite, tmp_path
):
    t1_token, _, _ = await _make_teacher_with_student(
        client, teacher_email="teacher@test.local",
        parent_email="parent-x@test.local",
    )
    _, _, stu2 = await _make_teacher_with_student(
        client, teacher_email="teacher2@test.local",
        teacher_password="test-pass-teacher2",
        invite="invite-ok-002",
        parent_email="parent-y@test.local",
        first_name="小美",
        class_name="English Class",
    )
    other_evt = _insert_event(stu2)

    before = _event_row(other_evt)

    resp = await _review(client, t1_token, other_evt)
    assert resp.status == 403

    after = _event_row(other_evt)
    assert after["reviewed"] == before["reviewed"]
    assert after["reviewed_by"] == before["reviewed_by"]
    assert after["reviewed_at"] == before["reviewed_at"]

    audits = _audit_events(tmp_path)
    warnings = [
        a for a in audits
        if a["level"] == "WARNING"
        and a["event"] == "safety_review_cross_access"
        and a["target_id"] == other_evt
    ]
    assert len(warnings) == 1
    assert warnings[0]["user_id"] == auth_db.get_user_by_email(
        "teacher@test.local"
    )["id"]


# ---------------------------------------------------------------------------
# 11. Review ok -> three columns written, list state flips
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_review_marks_event(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    resp = await _review(client, token, evt)
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["reviewed"] is True

    row = _event_row(evt)
    assert row["reviewed"] == 1
    assert row["reviewed_by"] == auth_db.get_user_by_email(
        "teacher@test.local"
    )["id"]
    assert row["reviewed_at"] is not None

    # List default shows it as reviewed.
    lst = await _list_events(client, token)
    events = (await lst.json())["events"]
    assert events[0]["reviewed"] is True


# ---------------------------------------------------------------------------
# 12. Review unknown event -> unified 403, no existence leak
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_review_unknown_event_unified_403(client, fresh_invite):
    token, _, _ = await _make_teacher_with_student(client)

    resp = await _review(client, token, "evt-nonexistent-000000")
    assert resp.status == 403
    assert "無權操作" == (await resp.json())["error"]


# ---------------------------------------------------------------------------
# 13. ?reviewed=false filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewed_false_filter(client, fresh_invite):
    token, _, stu = await _make_teacher_with_student(client)
    _insert_event(stu, reviewed=True, created_at=_future_iso(minutes=-5))
    unreviewed = _insert_event(stu, created_at=_future_iso(minutes=-1))

    resp = await _list_events(client, token, reviewed="false")
    assert resp.status == 200, await resp.text()
    events = (await resp.json())["events"]
    assert [e["event_id"] for e in events] == [unreviewed]
    assert events[0]["reviewed"] is False


# ---------------------------------------------------------------------------
# 14. sessions.stepped_up_until migration column present
# ---------------------------------------------------------------------------

def test_sessions_has_stepped_up_column(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "pairing.db"))
    auth_db.ensure_schema()

    conn = sqlite3.connect(str(tmp_path / "pairing.db"))
    try:
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
    finally:
        conn.close()
    assert "stepped_up_until" in cols


# ---------------------------------------------------------------------------
# 15. Admin path — bypasses class filter, still steps up, still audits
# ---------------------------------------------------------------------------

def _create_admin_user(email="admin@test.local",
                       password="test-pass-admin1"):
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password(password),
        role="admin",
        email_verified=True,
    )
    return user_id, email, password


@pytest.mark.asyncio
async def test_admin_path(client, fresh_invite, tmp_path):
    # Two teachers each with one student and one event.
    _, _, stu1 = await _make_teacher_with_student(
        client, teacher_email="teacher@test.local",
        parent_email="parent-x@test.local",
    )
    _, _, stu2 = await _make_teacher_with_student(
        client, teacher_email="teacher2@test.local",
        teacher_password="test-pass-teacher2",
        invite="invite-ok-002",
        parent_email="parent-y@test.local",
        first_name="小美",
        class_name="English Class",
    )
    evt1 = _insert_event(stu1, created_at=_future_iso(minutes=-5))
    evt2 = _insert_event(stu2, created_at=_future_iso(minutes=-2))

    _, admin_email, admin_pw = _create_admin_user()
    a_token = await _login_parent(client, admin_email, admin_pw)

    # Admin list sees events from BOTH teachers (bypasses class filter).
    lst = await _list_events(client, a_token)
    assert lst.status == 200, await lst.text()
    events = (await lst.json())["events"]
    assert {e["event_id"] for e in events} == {evt1, evt2}
    assert "raw_input" not in await lst.text()

    # Admin without step-up is still rejected.
    det_no_step = await _detail(client, a_token, evt2)
    assert det_no_step.status == 403
    assert "需要重新驗證密碼" == (await det_no_step.json())["error"]

    # Admin step-up -> detail ok, raw_input visible, audit written.
    step = await _step_up(client, a_token, password="test-pass-admin1")
    assert step.status == 200, await step.text()

    det = await _detail(client, a_token, evt2)
    assert det.status == 200, await det.text()
    assert (await det.json())["event"]["raw_input"] == FAKE_RAW_INPUT

    audits = _audit_events(tmp_path)
    viewed = [
        a for a in audits
        if a["event"] == "safety_detail_viewed" and a["event_id"] == evt2
    ]
    assert len(viewed) == 1
    assert viewed[0]["user_id"] == auth_db.get_user_by_email(
        "admin@test.local"
    )["id"]

    # Admin access is NOT cross-access: no WARNING lines.
    cross = [
        a for a in audits
        if a["level"] == "WARNING"
        and a["event"] in ("safety_detail_cross_access",
                           "safety_review_cross_access")
    ]
    assert cross == []


# ---------------------------------------------------------------------------
# (12-step guard) No real-looking student distress wording anywhere in the
# test file — enforced by the FAKE_RAW_INPUT discipline above.
# ---------------------------------------------------------------------------
