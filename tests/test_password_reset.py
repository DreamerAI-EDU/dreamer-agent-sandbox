"""W4 PR-D — forgot-password / reset-password tests (B-新2).

Covers the five boss points from the PR-D kickoff:
1. token three-iron-rule (DB holds only SHA-256 hash, plaintext only in the
   emailed link; single-use; new-request-wastes-old);
2. anti-enumeration (registered vs unknown email return identical responses);
3. reset side effects (all sessions revoked — old cookie → /api/auth/me 401);
4. phase8b migration creates password_reset_tokens on a fresh DB (lesson #39);
5. rate-limit values from the boss ruling (3/email/hr, 30/IP/hr).

No real passwords anywhere: all fixtures use the `test-pass-xxx` format.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import sqlite3
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402
from auth import security  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

DB_FILE_NAME = "auth_test.db"


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


async def _login(client, email="teacher@test.local", password="test-pass-teacher1"):
    return await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )


def _raw_from_link(link: str) -> str:
    assert "?token=" in link, f"reset link missing token: {link}"
    return link.split("?token=", 1)[1]


def _reset_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM password_reset_tokens ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB per test (DREAMER_DB_PATH isolated)."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / DB_FILE_NAME))
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
# 1. Token three-iron-rule: DB stores only the SHA-256 hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forgot_stores_only_hash_plaintext_only_in_link(
    client, fresh_invite, tmp_path
):
    """DB row must hold sha256(raw); the raw token appears only in the email link."""
    await _register_teacher(client, email="fr-hash@test.local")
    with patch("auth.api.send_reset_email", return_value=True) as mock_send:
        resp = await client.post(
            "/api/auth/forgot-password",
            json={"email": "fr-hash@test.local"},
            headers=HEADERS,
        )
    assert resp.status == 200
    assert await resp.json() == {"ok": True}

    link = mock_send.call_args.kwargs["link"]
    raw = _raw_from_link(link)
    expected_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    rows = _reset_rows(str(tmp_path / DB_FILE_NAME))
    assert len(rows) == 1
    assert rows[0]["token_hash"] == expected_hash
    assert rows[0]["user_id"] is not None
    assert rows[0]["expires_at"] > _future_iso(minutes=59)

    # Plaintext token must not appear anywhere in the row (any column).
    blob = " ".join(str(v) for v in rows[0])
    assert raw not in blob, "plaintext reset token leaked into the DB row"

    # And it IS present in the email link (the one permitted location).
    assert raw in link


# ---------------------------------------------------------------------------
# 2. Anti-enumeration: registered vs unknown email respond identically
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forgot_unknown_email_matches_registered_response(
    client, fresh_invite
):
    await _register_teacher(client, email="fr-ae@test.local")
    with patch("auth.api.send_reset_email", return_value=True):
        known = await client.post(
            "/api/auth/forgot-password",
            json={"email": "fr-ae@test.local"},
            headers=HEADERS,
        )
        unknown = await client.post(
            "/api/auth/forgot-password",
            json={"email": "no-such-user-xyz@test.local"},
            headers=HEADERS,
        )
    assert known.status == 200
    assert unknown.status == 200
    assert await known.json() == await unknown.json() == {"ok": True}


# ---------------------------------------------------------------------------
# 3. New request supersedes older pending tokens (single valid link)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forgot_new_request_supersedes_old_token(
    client, fresh_invite, tmp_path
):
    await _register_teacher(client, email="fr-sup@test.local")
    with patch("auth.api.send_reset_email", return_value=True) as mock_send:
        for _ in range(2):
            await client.post(
                "/api/auth/forgot-password",
                json={"email": "fr-sup@test.local"},
                headers=HEADERS,
            )
    raws = [_raw_from_link(call.kwargs["link"]) for call in mock_send.call_args_list]
    old_raw, new_raw = raws[0], raws[1]

    rows = _reset_rows(str(tmp_path / DB_FILE_NAME))
    pending = [r for r in rows if r["used_at"] is None]
    assert len(pending) == 1, "expected exactly one pending (unused) token"
    assert pending[0]["token_hash"] == hashlib.sha256(
        new_raw.encode("utf-8")
    ).hexdigest()

    # Old link is already dead; the new one works.
    old_resp = await client.post(
        "/api/auth/reset-password",
        json={"token": old_raw, "password": "test-pass-new1"},
        headers=HEADERS,
    )
    assert old_resp.status == 400
    new_resp = await client.post(
        "/api/auth/reset-password",
        json={"token": new_raw, "password": "test-pass-new1"},
        headers=HEADERS,
    )
    assert new_resp.status == 200


# ---------------------------------------------------------------------------
# 4. Boss ruling rate limits: 3/email/hour, 30/IP/hour
# ---------------------------------------------------------------------------

def test_rate_limit_constants_match_boss_ruling():
    assert security.forgot_email_limiter._max == 3
    assert security.forgot_ip_limiter._max == 30
    assert security.forgot_email_limiter._window == 3600
    assert security.forgot_ip_limiter._window == 3600


@pytest.mark.asyncio
async def test_forgot_email_rate_limit_3_per_hour(client):
    email = "rate-email@test.local"
    security.forgot_email_limiter.reset(email)
    security.forgot_ip_limiter.reset("127.0.0.1")
    # Unknown email is enough to exercise limiting; skip Argon2 burns.
    with patch("auth.api.dummy_verify"):
        for _ in range(3):
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": email},
                headers=HEADERS,
            )
            assert resp.status == 200, "first 3 requests within the hour"
        blocked = await client.post(
            "/api/auth/forgot-password",
            json={"email": email},
            headers=HEADERS,
        )
    assert blocked.status == 429


# ---------------------------------------------------------------------------
# 5. Reset success: password updated + ALL sessions revoked (old cookie 401)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_success_revokes_all_sessions_and_new_password_works(
    client, fresh_invite
):
    await _register_teacher(client, email="fr-rs@test.local")
    login1 = await _login(client, email="fr-rs@test.local")
    login2 = await _login(client, email="fr-rs@test.local")
    token1, token2 = _session_cookie(login1), _session_cookie(login2)
    assert login1.status == login2.status == 200

    for tok in (token1, token2):
        me = await client.get(
            "/api/auth/me", headers={"Cookie": f"auth_session={tok}"}
        )
        assert me.status == 200

    with patch("auth.api.send_reset_email", return_value=True) as mock_send:
        await client.post(
            "/api/auth/forgot-password",
            json={"email": "fr-rs@test.local"},
            headers=HEADERS,
        )
    raw = _raw_from_link(mock_send.call_args.kwargs["link"])

    reset = await client.post(
        "/api/auth/reset-password",
        json={"token": raw, "password": "test-pass-new1"},
        headers=HEADERS,
    )
    assert reset.status == 200
    assert await reset.json() == {"ok": True}

    # Old cookies are dead on every device — the boss point #3 proof.
    for tok in (token1, token2):
        me_old = await client.get(
            "/api/auth/me", headers={"Cookie": f"auth_session={tok}"}
        )
        assert me_old.status == 401, "old session must be revoked after reset"

    # New password logs in; old password is dead.
    new_login = await _login(client, email="fr-rs@test.local", password="test-pass-new1")
    assert new_login.status == 200
    old_login = await _login(client, email="fr-rs@test.local")
    assert old_login.status == 401


@pytest.mark.asyncio
async def test_reset_token_single_use_no_replay(client, fresh_invite):
    await _register_teacher(client, email="fr-replay@test.local")
    with patch("auth.api.send_reset_email", return_value=True) as mock_send:
        await client.post(
            "/api/auth/forgot-password",
            json={"email": "fr-replay@test.local"},
            headers=HEADERS,
        )
    raw = _raw_from_link(mock_send.call_args.kwargs["link"])

    first = await client.post(
        "/api/auth/reset-password",
        json={"token": raw, "password": "test-pass-new1"},
        headers=HEADERS,
    )
    assert first.status == 200

    replay = await client.post(
        "/api/auth/reset-password",
        json={"token": raw, "password": "test-pass-new2"},
        headers=HEADERS,
    )
    assert replay.status == 400, "used token must be rejected on replay"


# ---------------------------------------------------------------------------
# 6. Expired / malformed tokens and payloads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_expired_token_rejected(client, fresh_invite):
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")
    raw = "expired-reset-token-0001"
    auth_db.insert_password_reset_token(
        user_id=user["id"],
        token_hash=security.hash_reset_token(raw),
        expires_at=_past_iso(),
    )
    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": raw, "password": "test-pass-new1"},
        headers=HEADERS,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_reset_missing_or_weak_payload_rejected(client):
    cases = [
        {},
        {"token": "abc"},
        {"password": "test-pass-new1"},
        {"token": "abc", "password": "short"},
    ]
    for body in cases:
        resp = await client.post(
            "/api/auth/reset-password", json=body, headers=HEADERS
        )
        assert resp.status == 400, f"expected 400 for {body!r}"


# ---------------------------------------------------------------------------
# 7. CSRF guard (custom header) applies to both new endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forgot_and_reset_require_csrf_header(client):
    forgot = await client.post(
        "/api/auth/forgot-password", json={"email": "x@test.local"}
    )
    assert forgot.status == 403
    reset = await client.post(
        "/api/auth/reset-password", json={"token": "x", "password": "test-pass-x"}
    )
    assert reset.status == 403


# ---------------------------------------------------------------------------
# 8. Lesson #39: phase8b migration creates the table on a fresh DB
# ---------------------------------------------------------------------------

def test_phase8b_migration_creates_table_on_fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "migration.db")
    monkeypatch.setenv("DREAMER_DB_PATH", db_path)
    migration = os.path.join(
        REPO_ROOT, "migrations", "phase8b_password_reset.sql"
    )
    with open(migration, encoding="utf-8") as fh:
        sql = fh.read()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql)          # fresh DB → migration runs clean
        conn.executescript(sql)          # idempotent on re-run
        cur = conn.execute("PRAGMA table_info(password_reset_tokens)")
        cols = {row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    assert {"token_hash", "user_id", "expires_at", "used_at", "created_at"} <= cols

    # ensure_schema() also carries the table (fresh-DB runtime path).
    auth_db.ensure_schema()
    conn2 = sqlite3.connect(db_path)
    try:
        cur2 = conn2.execute("PRAGMA table_info(password_reset_tokens)")
        assert len(cur2.fetchall()) == 5
    finally:
        conn2.close()
