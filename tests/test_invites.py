"""W2 PR#3 — parent-invite + class-binding tests (11 cases, brief §6 #13-23).

Covers: class creation with confusion-safe join codes, role guards
(teacher-only), one-shot invite flow (students + class_students + invites
rows in a single transaction), invite payload validation + cross-teacher
rejection, parent 1-click confirm (single transaction, privacy mandatory,
media opt-in), single-use / expired / superseded tokens, resend
(supersedes old token, updates email, cross-teacher rejected), the
per-teacher daily invite cap, teacher confirm of a pending binding
(four conditions), and list-classes pending/confirmed counts.

The confirm endpoint is CSRF-exempt by design (opened from an email link),
so those requests intentionally carry no X-Requested-With header.

No real passwords anywhere: all fixtures use `test-pass-` / `test-pin-`
style values (B24 guard enforces this repo-wide).
"""

from __future__ import annotations

import datetime
import json
import os
import secrets
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

# 0/O/1/I/L removed from the join-code alphabet (confusion-safe).
JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CONFUSION_CHARS = set("0O1IL")

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


def _student_row(student_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
    finally:
        conn.close()


def _class_student_row(class_id, student_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM class_students WHERE class_id = ? AND student_id = ?",
            (class_id, student_id),
        ).fetchone()
    finally:
        conn.close()


def _consent_rows(user_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT doc_type, doc_version, action, student_id FROM consent_log "
            "WHERE user_id = ? ORDER BY rowid",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def _session_count(user_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
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


# ---------------------------------------------------------------------------
# 13. Teacher creates class → confusion-safe join code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_class_join_code_confusion_safe(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token, name="Math Class")

    assert len(cls["id"]) == 36
    assert len(cls["join_code"]) == 8
    assert all(ch in JOIN_CODE_ALPHABET for ch in cls["join_code"])
    assert not (set(cls["join_code"]) & CONFUSION_CHARS)


# ---------------------------------------------------------------------------
# 14. Classes role guards: anonymous 401, parent 403, teacher 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classes_role_guards(client, fresh_invite):
    # Anonymous → 401.
    anon = await client.post("/api/classes", json={"name": "X"}, headers=HEADERS)
    assert anon.status == 401

    # Parent → 403 for create and list.
    _, email, pw = _create_parent_user()
    p_token = await _login_parent(client, email, pw)
    parent_create = await client.post(
        "/api/classes", json={"name": "X"},
        headers={**HEADERS, "Cookie": f"auth_session={p_token}"},
    )
    assert parent_create.status == 403
    parent_list = await client.get(
        "/api/classes", headers={"Cookie": f"auth_session={p_token}"}
    )
    assert parent_list.status == 403

    # Teacher → empty list on a fresh DB.
    t_token = await _setup_logged_in_user(client)
    resp = await client.get(
        "/api/classes", headers={"Cookie": f"auth_session={t_token}"}
    )
    assert resp.status == 200
    assert (await resp.json())["classes"] == []


# ---------------------------------------------------------------------------
# 15. Invite flow writes students + class_students + invites atomically
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invite_flow_writes_all_rows(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    teacher = auth_db.get_user_by_email("teacher@test.local")

    body = await _create_invite(client, token, cls["id"], pin="1357")
    assert body["message"] == "邀請已發送"
    assert "pin" not in body          # supplied PIN is never echoed

    tok = _latest_invite_token()
    invite = _invite_row(tok)
    assert invite["parent_email"] == "parent-x@test.local"
    assert invite["class_id"] == cls["id"]
    assert invite["used_at"] is None
    assert invite["created_by"] == teacher["id"]

    # 72h expiry window.
    expires = datetime.datetime.fromisoformat(
        invite["expires_at"].replace("Z", "+00:00")
    )
    remaining_h = (
        expires - datetime.datetime.now(datetime.timezone.utc)
    ).total_seconds() / 3600
    assert 71.0 < remaining_h <= 72.5

    # students row: unbound (parent_id NULL), teacher-owned.
    student_id = invite["student_id"]
    student = _student_row(student_id)
    assert student["parent_id"] is None
    assert student["teacher_id"] == teacher["id"]
    assert student["first_name"] == "小明"
    assert student["age_band"] == "P1-P3"
    assert student["lang_code"] == "zh-hk"

    # class_students row: pending.
    cs = _class_student_row(cls["id"], student_id)
    assert cs is not None
    assert cs["status"] == "pending"


# ---------------------------------------------------------------------------
# 16. Invite validation + cross-teacher rejection (security log)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invite_validation_and_cross_teacher(
    client, fresh_invite, tmp_path
):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    base = {
        "class_id": cls["id"],
        "parent_email": "parent-x@test.local",
        "first_name": "小明",
        "age_band": "P1-P3",
        "lang_code": "zh-hk",
    }

    for mutate in (
        {"parent_email": "not-an-email"},   # no @
        {"parent_email": ""},               # blank
        {"parent_email": "a" * 300},        # >255
        {"age_band": "P2"},                 # bad enum
        {"lang_code": "fr"},                # bad enum
        {"first_name": ""},                 # blank name
        {"pin": "12"},                      # not 4 digits
    ):
        resp = await client.post(
            "/api/invites",
            json=dict(base, **mutate),
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 400, f"payload {mutate!r} must be rejected"

    # No invites were written by the bad payloads.
    conn = _conn()
    try:
        count = conn.execute("SELECT COUNT(*) FROM invites").fetchone()[0]
        count_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
    assert count_students == 0

    # A second teacher cannot invite into someone else's class.
    token2 = await _setup_logged_in_user(
        client, email="teacher2@test.local", invite="invite-ok-002"
    )
    cross = await client.post(
        "/api/invites",
        json=dict(base),
        headers={**HEADERS, "Cookie": f"auth_session={token2}"},
    )
    assert cross.status == 403

    events = _audit_events(tmp_path)
    assert any(e["event"] == "invite_cross_teacher" for e in events)


# ---------------------------------------------------------------------------
# 17. Confirm invite → parent user + consent + binding + session (atomic)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_invite_success_creates_parent_and_binding(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"])
    tok = _latest_invite_token()

    resp = await _confirm(client, tok, privacy=True, media=False)
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    parent_id = body["user"]["id"]
    assert body["user"]["email"] == "parent-x@test.local"
    assert _session_cookie(resp)          # session cookie issued

    parent = _user_row(parent_id)
    assert parent["role"] == "parent"
    assert parent["email_verified"] == 1

    student_id = _invite_row(tok)["student_id"]
    student = _student_row(student_id)
    assert student["parent_id"] == parent_id      # binding applied

    # consent_log: privacy agreed, linked to the student, current version.
    rows = _consent_rows(parent_id)
    assert len(rows) == 1
    assert rows[0][0] == "privacy_policy"
    assert rows[0][1] == "v2026-08-26"
    assert rows[0][2] == "agreed"
    assert rows[0][3] == student_id

    # invite marked used; class_students still pending until teacher confirm.
    assert _invite_row(tok)["used_at"] is not None
    assert _class_student_row(cls["id"], student_id)["status"] == "pending"

    # A session row was opened for the parent.
    assert _session_count(parent_id) == 1


# ---------------------------------------------------------------------------
# 18. Confirm rejects: missing privacy, second use, expired, superseded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_invite_rejects_bad_states(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)

    # Missing privacy_policy → 400, no rows written.
    await _create_invite(client, token, cls["id"], parent_email="p-nopp@test.local")
    tok_nopp = _latest_invite_token()
    r_nopp = await _confirm(client, tok_nopp, privacy=False)
    assert r_nopp.status == 400
    assert _invite_row(tok_nopp)["used_at"] is None

    # Second use of a consumed token → 400.
    await _create_invite(client, token, cls["id"], parent_email="p-once@test.local")
    tok_once = _latest_invite_token()
    assert (await _confirm(client, tok_once, privacy=True)).status == 201
    r_twice = await _confirm(client, tok_once, privacy=True)
    assert r_twice.status == 400

    # Expired token → 400.
    await _create_invite(client, token, cls["id"], parent_email="p-exp@test.local")
    tok_exp = _latest_invite_token()
    conn = _conn()
    try:
        conn.execute(
            "UPDATE invites SET expires_at = ? WHERE token = ?",
            ("2020-01-01T00:00:00Z", tok_exp),
        )
        conn.commit()
    finally:
        conn.close()
    r_exp = await _confirm(client, tok_exp, privacy=True)
    assert r_exp.status == 400

    # Superseded (old token after resend) → 400.
    await _create_invite(client, token, cls["id"], parent_email="p-old@test.local")
    tok_sup = _latest_invite_token()
    resend = await client.post(
        f"/api/invites/{tok_sup}/resend",
        json={"parent_email": None},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resend.status == 200
    r_sup = await _confirm(client, tok_sup, privacy=True)
    assert r_sup.status == 400


# ---------------------------------------------------------------------------
# 19. Confirm with media opt-in → media consent row also written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_invite_with_media_opt_in_writes_media_row(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"])
    tok = _latest_invite_token()

    resp = await _confirm(client, tok, privacy=True, media=True)
    assert resp.status == 201
    parent_id = (await resp.json())["user"]["id"]

    rows = _consent_rows(parent_id)
    assert len(rows) == 2
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("privacy_policy", "v2026-08-26", "agreed"),
        ("media_consent", "v2026-08-26", "agreed"),
    ]
    student_id = _invite_row(tok)["student_id"]
    assert all(r[3] == student_id for r in rows)


# ---------------------------------------------------------------------------
# 20. Resend supersedes old token; cross-teacher resend rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_invite_supersedes_and_guards_ownership(
    client, fresh_invite, tmp_path
):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"], parent_email="old@test.local")
    old_tok = _latest_invite_token()

    resp = await client.post(
        f"/api/invites/{old_tok}/resend",
        json={"parent_email": "new@test.local"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["message"] == "邀請已重發"

    old = _invite_row(old_tok)
    assert old["superseded_by"] is not None
    new_tok = old["superseded_by"]
    new = _invite_row(new_tok)
    assert new["parent_email"] == "new@test.local"   # email updated
    assert new["class_id"] == old["class_id"]
    assert new["student_id"] == old["student_id"]
    assert new["created_by"] == old["created_by"]
    assert new["used_at"] is None

    # Old token is dead after resend.
    r_old = await _confirm(client, old_tok, privacy=True)
    assert r_old.status == 400

    # Cross-teacher resend → 403 + security log.
    token2 = await _setup_logged_in_user(
        client, email="teacher2@test.local", invite="invite-ok-002"
    )
    r_cross = await client.post(
        f"/api/invites/{new_tok}/resend",
        json={"parent_email": None},
        headers={**HEADERS, "Cookie": f"auth_session={token2}"},
    )
    assert r_cross.status == 403

    events = _audit_events(tmp_path)
    assert any(e["event"] == "invite_resend_cross_teacher" for e in events)


# ---------------------------------------------------------------------------
# 21. Daily invite + resend cap → 429
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_invite_limit_blocks_create_and_resend(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    teacher = auth_db.get_user_by_email("teacher@test.local")

    # One real invite, then 19 bulk rows → teacher is at the daily cap of 20.
    await _create_invite(client, token, cls["id"], parent_email="real@test.local")
    real_tok = _latest_invite_token()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    conn = _conn()
    try:
        for i in range(19):
            conn.execute(
                "INSERT INTO invites (token, parent_email, student_id, class_id, "
                "expires_at, used_at, superseded_by, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                (
                    secrets.token_urlsafe(32),
                    f"bulk{i}@test.local",
                    "stu-bulk-" + str(i),
                    cls["id"],
                    now,
                    teacher["id"],
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # New invite → 429 with the daily-cap wording.
    r_create = await client.post(
        "/api/invites",
        json={
            "class_id": cls["id"],
            "parent_email": "over@test.local",
            "first_name": "小明",
            "age_band": "P1-P3",
            "lang_code": "zh-hk",
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert r_create.status == 429
    assert "今日邀請名額已用完" in (await r_create.json())["error"]

    # Resend also shares the cap → 429.
    r_resend = await client.post(
        f"/api/invites/{real_tok}/resend",
        json={"parent_email": None},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert r_resend.status == 429


# ---------------------------------------------------------------------------
# 22. Teacher confirm binding: pending → confirmed (four conditions)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_teacher_confirm_class_student_flow(client, fresh_invite,
                                                  tmp_path):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"])
    tok = _latest_invite_token()
    student_id = _invite_row(tok)["student_id"]
    url = f"/api/classes/{cls['id']}/confirm"

    # Condition: parent must be bound first → 400 (no_parent).
    r_unbound = await client.post(
        url, json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert r_unbound.status == 400

    # Parent confirms the invite → binding exists.
    assert (await _confirm(client, tok, privacy=True)).status == 201

    # Teacher confirms → 200 confirmed.
    r_ok = await client.post(
        url, json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert r_ok.status == 200, await r_ok.text()
    assert (await r_ok.json())["status"] == "confirmed"
    assert _class_student_row(cls["id"], student_id)["status"] == "confirmed"

    # Re-confirming an already-confirmed student → 400 (not_pending).
    r_again = await client.post(
        url, json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert r_again.status == 400

    # Cross-teacher confirm → 403 + security log.
    token2 = await _setup_logged_in_user(
        client, email="teacher2@test.local", invite="invite-ok-002"
    )
    r_cross = await client.post(
        url, json={"student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token2}"},
    )
    assert r_cross.status == 403

    events = _audit_events(tmp_path)
    assert any(e["event"] == "class_confirm_cross_teacher" for e in events)


# ---------------------------------------------------------------------------
# 23. List classes shows pending / confirmed counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_classes_pending_confirmed_counts(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls_a = await _create_class_via_api(client, token, name="Class A")
    cls_b = await _create_class_via_api(client, token, name="Class B")

    # Class A: one pending + one confirmed.
    await _create_invite(client, token, cls_a["id"], parent_email="p1@test.local")
    tok1 = _latest_invite_token()
    s1 = _invite_row(tok1)["student_id"]

    await _create_invite(client, token, cls_a["id"], parent_email="p2@test.local")
    tok2 = _latest_invite_token()
    s2 = _invite_row(tok2)["student_id"]
    assert (await _confirm(client, tok2, privacy=True)).status == 201
    confirm = await client.post(
        f"/api/classes/{cls_a['id']}/confirm",
        json={"student_id": s2},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert confirm.status == 200

    resp = await client.get(
        "/api/classes", headers={"Cookie": f"auth_session={token}"}
    )
    assert resp.status == 200
    classes = {c["id"]: c for c in (await resp.json())["classes"]}
    assert classes[cls_a["id"]]["pending_count"] == 1
    assert classes[cls_a["id"]]["confirmed_count"] == 1
    assert classes[cls_b["id"]]["pending_count"] == 0
    assert classes[cls_b["id"]]["confirmed_count"] == 0


# ---------------------------------------------------------------------------
# 13+. Invite email is sent (mocked SMTP) with a link containing the token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invite_email_sent_with_link_containing_token(
    client, fresh_invite, monkeypatch
):
    sent = []

    def fake_send_email(*, to_addr, subject, body):
        sent.append({"to_addr": to_addr, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("auth.email.send_email", fake_send_email)

    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(
        client, token, cls["id"], parent_email="mail@test.local"
    )
    tok = _latest_invite_token()

    assert len(sent) >= 1
    invite_mails = [m for m in sent if "家長邀請" in m["subject"]]
    assert len(invite_mails) == 1
    assert invite_mails[0]["to_addr"] == "mail@test.local"
    assert f"/invite/{tok}" in invite_mails[0]["body"]


# ---------------------------------------------------------------------------
# 17+. Totally fake token → unified "連結無效或已過期" wording
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_fake_token_unified_wording(client, fresh_invite):
    resp = await _confirm(client, "totally-fake-token-000", privacy=True)
    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "連結無效或已過期"


# ---------------------------------------------------------------------------
# 19+. Resend of an already-used invite is rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_used_invite_rejected(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"], parent_email="used@test.local")
    tok = _latest_invite_token()
    assert (await _confirm(client, tok, privacy=True)).status == 201

    resp = await client.post(
        f"/api/invites/{tok}/resend",
        json={"parent_email": None},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 400
    # The used invite is untouched.
    assert _invite_row(tok)["superseded_by"] is None


# ---------------------------------------------------------------------------
# 21+. pin-verify rejected while teacher has not confirmed the binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_verify_rejected_until_teacher_confirms(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)
    cls = await _create_class_via_api(client, token)
    await _create_invite(client, token, cls["id"], pin="1357")
    tok = _latest_invite_token()
    student_id = _invite_row(tok)["student_id"]

    # Parent confirms; teacher has NOT confirmed the binding yet.
    assert (await _confirm(client, tok, privacy=True)).status == 201
    parent_token = await _login_parent(
        client, "parent-x@test.local", CONFIRM_PASSWORD
    )

    resp = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={parent_token}"},
    )
    assert resp.status == 403
    body = await resp.json()
    assert body["error"] == "等待老師確認"
