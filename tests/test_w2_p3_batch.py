"""W2 P3 batch (v1.9 §5) — null pin_hash ride + four P3 items.

Covers (per work-order v1.0, §1 Item 0 / P3-1 / P3-2 / P3-3 / P3-4):
- Item 0: a confirmed student whose pin_hash is NULL gets the uniform
  "PIN 不正確" 401 (never a 500 from verify_pin(None)), does NOT touch the
  lockout counter (data anomaly != guessing failure) and leaves a
  server-side pin_verify_null_pinhash WARNING trail.
- P3-1: safety review writes a safety_event_reviewed INFO audit trail.
- P3-2: media withdraw requires a current-version agreed row covering the
  withdraw scope — otherwise uniform "未有可撤回嘅同意紀錄" 400, zero
  writes, zero fake WARNING rows. Double withdraw collapses into the same
  gate (covered in test_consent.py test 10); here we pin the fresh-withdraw
  and per-student-scope semantics.
- P3-3: lockout bookkeeping is keyed by the resolved full student id, so a
  masked-prefix {id} path can no longer burn attempts on a key that never
  locks the student (PR#34-style bypass).
- P3-4: confirm without privacy_policy returns the explicit "必須同意私隱
  政策先可以繼續" wording instead of the generic 請求無效.

Discipline (brief §6): fixture raw_input is a fake sentence only
("test-distress-sentence"); no real passwords — `test-pass-*` /
`test-pin-*`.
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
from auth import students as students_mod  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

CONFIRM_PASSWORD = "test-pass-parent1"
FAKE_RAW_INPUT = "test-distress-sentence"
MEDIA_VERSION = "v2026-08-26"

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


def _db_path() -> str:
    return os.environ["DREAMER_DB_PATH"]


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


def _conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SAFETY_DDL)
    conn.commit()
    return conn


def _full_student_id(*, mask=None):
    """Resolve the full server-side student id from the test DB.

    The API only exposes masked ids; PIN endpoints are keyed by the full
    id. When mask is given the newest student with that masked prefix is
    returned, otherwise the newest student row overall.
    """
    conn = sqlite3.connect(_db_path())
    try:
        if mask is None:
            row = conn.execute(
                "SELECT id FROM students ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM students WHERE id LIKE ? "
                "ORDER BY rowid DESC LIMIT 1",
                (mask + "%",),
            ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no student row in test DB"
    return row[0]


def _student_row(student_id):
    conn = sqlite3.connect(_db_path())
    try:
        cur = conn.execute(
            "SELECT id, parent_id, teacher_id, first_name, age_band, "
            "lang_code, pin_hash, pin_lock_until, failed_pin_count, "
            "created_at FROM students WHERE id = ?",
            (student_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return row


def _create_db_student(*, parent_id, first_name="Child",
                       age_band="P1-P3", lang_code="zh-hk", pin="1234"):
    return students_mod.create_student(
        parent_id=parent_id,
        first_name=first_name,
        age_band=age_band,
        lang_code=lang_code,
        pin_hash=students_mod.hash_pin(pin),
    )


async def _create_student_via_api(client, token, *, pin="1357"):
    resp = await client.post(
        "/api/students",
        json={
            "first_name": "小明",
            "age_band": "P1-P3",
            "lang_code": "zh-hk",
            "pin": pin,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    masked = body["student"]["id"]
    return _full_student_id(mask=masked)


def _consent_rows(*, user_id=None, doc_type=None, student_id=None):
    conn = sqlite3.connect(_db_path())
    try:
        sql = ("SELECT doc_type, doc_version, action, student_id "
               "FROM consent_log")
        clauses = []
        params = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if doc_type is not None:
            clauses.append("doc_type = ?")
            params.append(doc_type)
        if student_id is not None:
            clauses.append("student_id = ?")
            params.append(student_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return rows


def _audit_events(tmp_path):
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _invite_row(token):
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM invites WHERE token = ?", (token,)
        ).fetchone()
    finally:
        conn.close()


def _latest_invite_token():
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            "SELECT token FROM invites ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no invites row in test DB"
    return row[0]


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


async def _confirm_invite(client, token, *, privacy=None, media=False,
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
    confirm = await _confirm_invite(client, invite_token, privacy=True)
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


# ---------------------------------------------------------------------------
# Item 0. NULL pin_hash — uniform 401, no lockout touch, WARNING trail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_pin_hash_verify_returns_uniform_401_no_lockout_and_warns(
    client, fresh_invite, tmp_path
):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")

    # Corrupt the row: confirmed student ends up with NULL pin_hash.
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            "UPDATE students SET pin_hash = NULL WHERE id = ?", (student_id,)
        )
        conn.commit()
    finally:
        conn.close()
    assert _student_row(student_id)[6] is None

    # Correct PIN against a NULL hash → uniform wrong-PIN 401, never a 500.
    resp = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 401, await resp.text()
    assert (await resp.json())["error"] == "PIN 不正確"

    # Lockout counter untouched — this is not a guessing failure.
    row = _student_row(student_id)
    assert row[7] is None            # pin_lock_until
    assert row[8] == 0               # failed_pin_count

    # Server-side WARNING trail for the operator.
    warnings = [
        a for a in _audit_events(tmp_path)
        if a["level"] == "WARNING"
        and a["event"] == "pin_verify_null_pinhash"
    ]
    assert len(warnings) == 1
    assert warnings[0]["target_id"] == student_id


# ---------------------------------------------------------------------------
# P3-3. Lockout keyed by resolved full id — masked prefix cannot bypass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_lockout_keyed_by_full_id_when_masked_prefix_used(
    client, fresh_invite
):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")

    # Burn 10 wrong attempts through the masked 8-char prefix path. Before
    # P3-3 these were recorded against the mask key, so the real student id
    # kept a clean counter and a correct-PIN verify succeeded mid-lockout.
    mask = student_id[:8]
    mask_url = f"/api/students/{mask}/pin-verify"
    for attempt in range(10):
        resp = await client.post(
            mask_url, json={"pin": "9999"},
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 401, f"failure {attempt + 1} must be 401"

    row = _student_row(student_id)
    assert row[7] is not None        # pin_lock_until set on the full id
    assert row[8] == 0               # counter reset after lock

    # The full-id path is locked too: even the correct PIN gets 429. This is
    # the regression that catches the mask-key bypass.
    locked = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert locked.status == 429


# ---------------------------------------------------------------------------
# P3-2. Withdraw prior-agree gate — fresh withdraw without agreement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_withdraw_without_prior_agree_400_zero_rows_zero_audit(
    client, fresh_invite, tmp_path
):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    resp = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 400, await resp.text()
    assert (await resp.json())["error"] == "未有可撤回嘅同意紀錄"

    # Zero writes.
    rows = _consent_rows(user_id=user["id"], doc_type="media_consent")
    assert len(rows) == 0

    # Zero fake WARNING markers.
    markers = [
        a for a in _audit_events(tmp_path)
        if a["event"] == "media_takedown_pending"
    ]
    assert len(markers) == 0


# ---------------------------------------------------------------------------
# P3-2. Per-student withdraw scope — sibling agreement does not cover
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_withdraw_student_scope_requires_that_students_agree(
    client, fresh_invite, tmp_path
):
    parent_a, email, pw = _create_parent_user("parent-a@test.local")
    token = await _login_parent(client, email, pw)
    s1 = _create_db_student(parent_id=parent_a, pin="1111")
    s2 = _create_db_student(parent_id=parent_a, pin="2222")

    # S1 signs media_consent (per-student row).
    sign = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "media_consent",
            "doc_version": MEDIA_VERSION,
            "student_id": s1,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert sign.status == 201, await sign.text()

    # Withdrawing S2 while only S1 agreed → uniform 400, zero S2 writes.
    w_s2 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": s2},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w_s2.status == 400, await w_s2.text()
    assert (await w_s2.json())["error"] == "未有可撤回嘅同意紀錄"
    assert len(_consent_rows(student_id=s2)) == 0

    # S1 still withdrawable — its own agreement covers the scope.
    w_s1 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": s1},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w_s1.status == 200, await w_s1.text()

    # Exactly one takedown marker, for S1 only.
    markers = [
        a for a in _audit_events(tmp_path)
        if a["event"] == "media_takedown_pending"
    ]
    assert len(markers) == 1
    assert markers[0]["student_id"] == s1


# ---------------------------------------------------------------------------
# P3-1. Safety review leaves an audit trail (INFO, not just DB columns)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_event_review_writes_audit_trail(
    client, fresh_invite, tmp_path
):
    token, _, stu = await _make_teacher_with_student(client)
    evt = _insert_event(stu)

    resp = await client.post(
        f"/api/teacher/safety-events/{evt}/review",
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["reviewed"] is True

    teacher = auth_db.get_user_by_email("teacher@test.local")
    reviews = [
        a for a in _audit_events(tmp_path)
        if a["level"] == "INFO"
        and a["event"] == "safety_event_reviewed"
    ]
    assert len(reviews) == 1
    assert reviews[0]["user_id"] == teacher["id"]
    assert reviews[0]["event_id"] == evt
    assert reviews[0]["student_id"] == stu
    assert reviews[0]["reviewed_by"] == teacher["id"]


# ---------------------------------------------------------------------------
# P3-4. Confirm without privacy_policy — explicit wording, zero writes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_without_privacy_explicit_wording_no_writes(
    client, fresh_invite
):
    token = await _setup_logged_in_user(
        client, email="teacher@test.local", password="test-pass-teacher1"
    )
    cls = await _create_class_via_api(client, token, name="Math Class")
    parent_email = "parent-new@test.local"
    await _create_invite(
        client, token, cls["id"], parent_email=parent_email, pin="1357",
    )
    invite_token = _latest_invite_token()

    # privacy_policy omitted entirely → 400 with the explicit gate wording.
    resp = await _confirm_invite(client, invite_token, privacy=None)
    assert resp.status == 400, await resp.text()
    assert (await resp.json())["error"] == "必須同意私隱政策先可以繼續"

    # Zero writes: invite still unused, no parent account created.
    row = _invite_row(invite_token)
    assert row["used_at"] is None
    assert auth_db.get_user_by_email(parent_email) is None

    # Same gate wording when privacy is explicitly false.
    resp2 = await _confirm_invite(client, invite_token, privacy=False)
    assert resp2.status == 400
    assert (await resp2.json())["error"] == "必須同意私隱政策先可以繼續"
