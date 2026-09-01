"""W2 PR#1 — DB schema + auth core tests (14 cases, per PR brief §5).

Each case is a separate test. No real passwords anywhere: all fixtures use
`test-pass-xxx` format (guard test 13 enforces this repo-wide).
"""

from __future__ import annotations

import datetime
import os
import re
import sqlite3
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import db as auth_db  # noqa: E402
from auth import email as auth_email  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _past_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    """Extract auth_session token from a login response.

    TestClient runs over plain http, where aiohttp's cookie jar refuses to
    send Secure cookies back — so tests carry the session explicitly via a
    Cookie header (same as a browser would over https).
    """
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


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB per test (DREAMER_DB_PATH isolated)."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
def fresh_invite():
    auth_db.insert_teacher_invite(
        code="invite-ok-001",
        created_by="admin-cli",
        expires_at=_future_iso(days=7),
    )


# ---------------------------------------------------------------------------
# 1-4. Register + password hashing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_success_creates_user_and_marks_invite_used(
    client, fresh_invite
):
    resp = await _register_teacher(client)
    assert resp.status == 201
    body = await resp.json()
    assert body["user"]["email"] == "teacher@test.local"
    assert body["user"]["role"] == "teacher"
    assert body["user"]["email_verified"] is False

    user = auth_db.get_user_by_email("teacher@test.local")
    assert user is not None
    assert user["role"] == "teacher"

    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        invite = conn.execute(
            "SELECT * FROM teacher_invites WHERE code = 'invite-ok-001'"
        ).fetchone()
    finally:
        conn.close()
    assert invite is not None
    assert invite[3] == user["id"]  # used_by
    assert invite[4] is not None    # used_at


@pytest.mark.asyncio
async def test_register_rejects_used_or_expired_invite(client):
    auth_db.insert_teacher_invite(
        code="invite-used-001", created_by="admin-cli",
        expires_at=_future_iso(days=7),
    )
    auth_db.insert_teacher_invite(
        code="invite-expired-001", created_by="admin-cli",
        expires_at=_past_iso(),
    )
    # Mark one as used.
    auth_db.mark_invite_used("invite-used-001", "user-existing")

    resp_used = await _register_teacher(
        client, invite="invite-used-001", email="used@test.local"
    )
    assert resp_used.status == 400

    resp_expired = await _register_teacher(
        client, invite="invite-expired-001", email="expired@test.local"
    )
    assert resp_expired.status == 400

    assert auth_db.get_user_by_email("used@test.local") is None
    assert auth_db.get_user_by_email("expired@test.local") is None


@pytest.mark.asyncio
async def test_register_duplicate_email_unified_response(client, fresh_invite):
    resp1 = await _register_teacher(client)
    assert resp1.status == 201

    auth_db.insert_teacher_invite(
        code="invite-ok-002", created_by="admin-cli",
        expires_at=_future_iso(days=7),
    )
    resp2 = await _register_teacher(
        client, email="teacher@test.local", invite="invite-ok-002"
    )
    assert resp2.status == 400
    body = await resp2.json()
    # Unified wording must not reveal the email already exists.
    assert body == {"error": "請求無效"}


@pytest.mark.asyncio
async def test_password_stored_as_argon2id(client, fresh_invite):
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")
    assert user is not None
    assert user["password_hash"].startswith("$argon2id$")
    assert "test-pass-teacher1" not in user["password_hash"]


# ---------------------------------------------------------------------------
# 5-8. Login, cookie flags, lockout, counter reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success_sets_cookie_with_all_three_flags(
    client, fresh_invite
):
    await _register_teacher(client)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert resp.status == 200

    set_cookies = resp.headers.getall("Set-Cookie", [])
    auth_cookie = next(
        (sc for sc in set_cookies if sc.startswith("auth_session=")), None
    )
    assert auth_cookie is not None, f"no auth_session cookie in {set_cookies}"
    assert "HttpOnly" in auth_cookie
    assert "Secure" in auth_cookie
    assert "SameSite=Lax" in auth_cookie


@pytest.mark.asyncio
async def test_login_wrong_password_5_times_then_locked(client, fresh_invite):
    await _register_teacher(client)

    for _ in range(5):
        resp = await client.post(
            "/api/auth/login",
            json={"email": "teacher@test.local", "password": "test-pass-wrong"},
            headers=HEADERS,
        )
        assert resp.status == 401

    # 5th failure triggers lock_until.
    user = auth_db.get_user_by_email("teacher@test.local")
    assert user is not None
    assert user["lock_until"] is not None
    assert user["lock_until"] > _past_iso()

    # 6th attempt (even correct password) is rejected.
    resp6 = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert resp6.status == 429


@pytest.mark.asyncio
async def test_locked_account_rejects_correct_password(client, fresh_invite):
    await _register_teacher(client)
    auth_db.set_user_lock(
        auth_db.get_user_by_email("teacher@test.local")["id"],
        _future_iso(minutes=15),
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert resp.status == 429


@pytest.mark.asyncio
async def test_login_success_resets_failed_logins(client, fresh_invite):
    await _register_teacher(client)

    # Two failures first.
    for _ in range(2):
        await client.post(
            "/api/auth/login",
            json={"email": "teacher@test.local", "password": "test-pass-wrong"},
            headers=HEADERS,
        )
    user = auth_db.get_user_by_email("teacher@test.local")
    assert int(user["failed_logins"]) == 2

    # Correct login resets the counter.
    resp = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert resp.status == 200
    user = auth_db.get_user_by_email("teacher@test.local")
    assert int(user["failed_logins"]) == 0
    assert user["lock_until"] is None


# ---------------------------------------------------------------------------
# 9-10. Session lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logout_then_me_returns_401(client, fresh_invite):
    await _register_teacher(client)
    login = await client.post(
        "/api/auth/login",
        json={"email": "teacher@test.local", "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200
    token = _session_cookie(login)

    me = await client.get(
        "/api/auth/me", headers={"Cookie": f"auth_session={token}"}
    )
    assert me.status == 200

    logout = await client.post(
        "/api/auth/logout",
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert logout.status == 200

    # Session row deleted server-side; cookie header is now useless.
    me2 = await client.get(
        "/api/auth/me", headers={"Cookie": f"auth_session={token}"}
    )
    assert me2.status == 401


@pytest.mark.asyncio
async def test_expired_session_returns_401(client, fresh_invite):
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    # Insert an already-expired session row directly.
    auth_db.create_session(
        session_id="expired-session-token",
        user_id=user["id"],
        expires_at=_past_iso(),
    )

    me = await client.get(
        "/api/auth/me",
        headers={"Cookie": "auth_session=expired-session-token"},
    )
    assert me.status == 401


# ---------------------------------------------------------------------------
# 11. Email verification token single-use
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_verify_token_single_use(client, fresh_invite):
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")
    token = user["email_verify_token"]
    assert token is not None

    resp1 = await client.post(
        "/api/auth/verify-email",
        json={"token": token},
        headers=HEADERS,
    )
    assert resp1.status == 200
    body = await resp1.json()
    assert body["user"]["email_verified"] is True

    user_after = auth_db.get_user_by_email("teacher@test.local")
    assert int(user_after["email_verified"]) == 1
    assert user_after["email_verify_token"] is None

    resp2 = await client.post(
        "/api/auth/verify-email",
        json={"token": token},
        headers=HEADERS,
    )
    assert resp2.status == 400


# ---------------------------------------------------------------------------
# 12. CSRF custom-header guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_csrf_missing_header_post_rejected(client):
    # No X-Requested-With on a POST → 403, regardless of body validity.
    resp = await client.post(
        "/api/auth/register",
        json={"invite_code": "x", "email": "a@b.local", "password": "test-pass-x"},
    )
    assert resp.status == 403

    resp_login = await client.post(
        "/api/auth/login",
        json={"email": "a@b.local", "password": "test-pass-x"},
    )
    assert resp_login.status == 403


# ---------------------------------------------------------------------------
# 13. Plaintext-password grep guard (test-pass-xxx fixtures only)
# ---------------------------------------------------------------------------

def _repo_py_files():
    for root, dirs, files in os.walk(REPO_ROOT):
        parts = root.split(os.sep)
        if any(
            seg in {".venv", "node_modules", "__pycache__", ".git", "temp", "output"}
            for seg in parts
        ):
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_no_plaintext_passwords_in_repo():
    """No hardcoded plaintext password assignment anywhere in repo .py files.

    Allowed exception: fixture passwords following `test-pass-` prefix.
    """
    bad = []
    pattern = re.compile(
        r"""["'](?:password|passwd|pwd)["']\s*[=:]\s*["'][^"']{6,}["']"""
    )
    for path in _repo_py_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in pattern.finditer(text):
            literal = m.group(0)
            if "test-pass-" in literal:
                continue
            bad.append((os.path.relpath(path, REPO_ROOT), literal))
    assert not bad, f"plaintext password literals found: {bad}"


def test_auth_fixture_passwords_use_test_pass_prefix():
    """tests/test_auth.py password literals must follow test-pass-xxx."""
    path = os.path.join(REPO_ROOT, "tests", "test_auth.py")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for m in re.finditer(r"""["'](?:password)["']\s*[=:]\s*["'][^"']{6,}["']""", text):
        literal = m.group(0)
        assert "test-pass-" in literal, f"non-fixture password literal: {literal}"


# ---------------------------------------------------------------------------
# 14. Migration schema pairing — PRAGMA per table vs migrations/phase8_auth.sql
# ---------------------------------------------------------------------------

EXPECTED_SCHEMA = {
    "users": [
        ("id", "TEXT"), ("email", "TEXT"), ("password_hash", "TEXT"),
        ("role", "TEXT"), ("email_verified", "BOOLEAN"),
        ("email_verify_token", "TEXT"), ("email_verify_expires_at", "TEXT"),
        ("failed_logins", "INT"), ("lock_until", "TEXT"),
        ("created_at", "TEXT"),
    ],
    "sessions": [
        ("id", "TEXT"), ("user_id", "TEXT"), ("expires_at", "TEXT"),
        ("created_ip", "TEXT"), ("created_at", "TEXT"),
        ("stepped_up_until", "TEXT"),
    ],
    "teacher_invites": [
        ("code", "TEXT"), ("created_by", "TEXT"), ("expires_at", "TEXT"),
        ("used_by", "TEXT"), ("used_at", "TEXT"),
    ],
    "students": [
        ("id", "TEXT"), ("parent_id", "TEXT"), ("teacher_id", "TEXT"),
        ("first_name", "TEXT"), ("age_band", "TEXT"), ("lang_code", "TEXT"),
        ("pin_hash", "TEXT"), ("pin_lock_until", "TEXT"),
        ("failed_pin_count", "INT"), ("created_at", "TEXT"),
    ],
    "classes": [
        ("id", "TEXT"), ("teacher_id", "TEXT"), ("name", "TEXT"),
        ("join_code", "TEXT"), ("created_at", "TEXT"),
    ],
    "class_students": [
        ("class_id", "TEXT"), ("student_id", "TEXT"), ("status", "TEXT"),
        ("created_at", "TEXT"),
    ],
    "invites": [
        ("token", "TEXT"), ("parent_email", "TEXT"), ("student_id", "TEXT"),
        ("class_id", "TEXT"), ("expires_at", "TEXT"), ("used_at", "TEXT"),
        ("superseded_by", "TEXT"), ("created_by", "TEXT"),
        ("created_at", "TEXT"),
    ],
    "consent_log": [
        ("id", "TEXT"), ("user_id", "TEXT"), ("student_id", "TEXT"),
        ("doc_type", "TEXT"), ("doc_version", "TEXT"), ("action", "TEXT"),
        ("ip", "TEXT"), ("user_agent", "TEXT"), ("created_at", "TEXT"),
    ],
}


def test_migration_schema_pairing(tmp_path, monkeypatch):
    """After ensure_schema(), every W2 table's PRAGMA must match the SQL file.

    Same style as the safety_events 13-column pairing test
    (tests/test_input_guard.py::test_safety_events_schema_13_columns).
    """
    db_path = str(tmp_path / "pairing.db")
    monkeypatch.setenv("DREAMER_DB_PATH", db_path)
    auth_db.ensure_schema()

    conn = sqlite3.connect(db_path)
    try:
        for table, expected in EXPECTED_SCHEMA.items():
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = [(row[1], row[2]) for row in cur.fetchall()]
            assert len(cols) == len(expected), (
                f"{table} column count mismatch: got {len(cols)}, "
                f"expected {len(expected)}"
            )
            for (actual_name, actual_type), (exp_name, exp_type) in zip(cols, expected):
                assert actual_name.lower() == exp_name.lower(), (
                    f"{table} column mismatch: got '{actual_name}', "
                    f"expected '{exp_name}'"
                )
                assert actual_type.upper() == exp_type.upper(), (
                    f"{table} column type mismatch for '{exp_name}': "
                    f"got '{actual_type}', expected '{exp_type}'"
                )
    finally:
        conn.close()


def test_students_table_has_no_b24_forbidden_columns(tmp_path, monkeypatch):
    """B24 hard gate: students must NOT carry full_name/last_name/school/dob."""
    db_path = str(tmp_path / "b24.db")
    monkeypatch.setenv("DREAMER_DB_PATH", db_path)
    auth_db.ensure_schema()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA table_info(students)")
        cols = [row[1].lower() for row in cur.fetchall()]
    finally:
        conn.close()

    forbidden = {"full_name", "last_name", "school", "dob", "date_of_birth"}
    hits = forbidden & set(cols)
    assert not hits, f"B24 forbidden columns present in students: {hits}"


# ---------------------------------------------------------------------------
# PR#33 — SMTP login user: SAFETY_SMTP_USER with SAFETY_EMAIL_FROM fallback
# ---------------------------------------------------------------------------

def test_email_smtp_login_uses_smtp_user_when_set(monkeypatch):
    """SAFETY_SMTP_USER set → SMTP login uses it; From header keeps EMAIL_FROM."""
    monkeypatch.setenv("SAFETY_SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("SAFETY_SMTP_USER", "login-user@example.com")
    monkeypatch.setenv("SAFETY_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("SAFETY_SMTP_PORT", "465")  # force SMTP_SSL path for mock

    with patch("auth.email.smtplib.SMTP_SSL") as mock_smtp:
        instance = mock_smtp.return_value.__enter__.return_value
        result = auth_email.send_email(
            to_addr="to@example.com", subject="Subject", body="Body"
        )
        assert result is True
        instance.login.assert_called_once_with(
            "login-user@example.com", "test-app-password"
        )
        sent = instance.send_message.call_args[0][0]
        assert sent["From"] == "from@example.com"


def test_email_smtp_login_falls_back_to_email_from(monkeypatch):
    """SAFETY_SMTP_USER unset → SMTP login falls back to EMAIL_FROM (backward compat)."""
    monkeypatch.setenv("SAFETY_SMTP_PASSWORD", "test-app-password")
    monkeypatch.delenv("SAFETY_SMTP_USER", raising=False)
    monkeypatch.setenv("SAFETY_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("SAFETY_SMTP_PORT", "465")  # force SMTP_SSL path for mock

    with patch("auth.email.smtplib.SMTP_SSL") as mock_smtp:
        instance = mock_smtp.return_value.__enter__.return_value
        result = auth_email.send_email(
            to_addr="to@example.com", subject="Subject", body="Body"
        )
        assert result is True
        instance.login.assert_called_once_with(
            "from@example.com", "test-app-password"
        )
        sent = instance.send_message.call_args[0][0]
        assert sent["From"] == "from@example.com"
