"""Issue #59 — POST /api/auth/resend-verification.

An expired / lost verification link (VERIFY_HOURS = 24h) used to leave the
account with no self-service way back in. This endpoint rotates the token and
mails a fresh link; the old link dies immediately.

Cases:
1. happy path — token rotated, new link verifies, old link rejected;
2. expired-link recovery — the actual issue #59 scenario;
3. anti-enumeration — unknown email / already-verified are uniform 200 no-ops
   (no mail, no audit row);
4. audit row written exactly once on a real resend, event=verification_resent,
   no token literal in the log;
5. rate limits — 20/email/hour + 20/IP/hour, counted before the lookup;
6. session fallback — `{}` body with a live session uses the account email;
7. CSRF guard applies (custom header required).

No real passwords anywhere: fixtures use the `test-pass-xxx` format.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import security  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
RESEND_URL = "/api/auth/resend-verification"
VERIFY_URL = "/api/auth/verify-email"


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _past_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")


def _register_teacher(client, *, email="teacher@test.local",
                      password="test-pass-teacher1", invite="invite-ok-001"):
    return client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": password},
        headers=HEADERS,
    )


def _session_cookie(resp) -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no auth_session cookie in response")


def _audit_rows(tmp_path) -> list[dict]:
    path = tmp_path / "audit_log.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB + isolated audit sink per test."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    monkeypatch.setattr(
        consent_mod, "AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl")
    )
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


@pytest_asyncio.fixture(autouse=True)
def _clean_limiters():
    """Module-level limiter singletons outlive a test — reset around each one."""
    security.resend_email_limiter.reset("teacher@test.local")
    security.resend_ip_limiter.reset("127.0.0.1")
    yield
    security.resend_email_limiter.reset("teacher@test.local")
    security.resend_ip_limiter.reset("127.0.0.1")


async def _register_and_capture_token(client, email="teacher@test.local") -> str:
    """Register (verification mail mocked) and return the emailed token."""
    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        resp = await _register_teacher(client, email=email)
    assert resp.status == 201
    return mock_send.call_args.kwargs["token"]


def _db_token(db_path: str) -> tuple[str | None, str | None]:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT email_verify_token, email_verify_expires_at FROM users"
        ).fetchone()
    finally:
        conn.close()
    return row


# ---------------------------------------------------------------------------
# 1. Happy path — token rotated, new link works, old link dies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_rotates_token_and_old_link_dies(client, fresh_invite):
    email = "resend-ok@test.local"
    old_token = await _register_and_capture_token(client, email=email)

    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        resp = await client.post(RESEND_URL, json={"email": email}, headers=HEADERS)

    assert resp.status == 200
    assert await resp.json() == {"ok": True}
    assert mock_send.call_count == 1
    new_token = mock_send.call_args.kwargs["token"]
    assert mock_send.call_args.kwargs["to_addr"] == email
    assert new_token != old_token

    # DB holds exactly the new token, with a fresh 24h expiry.
    stored, expires_at = _db_token(os.environ["DREAMER_DB_PATH"])
    assert stored == new_token
    assert expires_at > _future_iso(hours=23)

    # Old link is dead the moment the token rotates.
    stale = await client.post(
        VERIFY_URL, json={"token": old_token}, headers=HEADERS
    )
    assert stale.status == 400, "rotated-away token must be rejected"

    # New link verifies the account.
    fresh = await client.post(
        VERIFY_URL, json={"token": new_token}, headers=HEADERS
    )
    assert fresh.status == 200
    assert (await fresh.json())["user"]["email_verified"] is True


@pytest.mark.asyncio
async def test_resend_recovers_from_expired_link(client, fresh_invite):
    """The issue #59 scenario: link already expired → resend gets you back in."""
    email = "resend-expired@test.local"
    await _register_and_capture_token(client, email=email)
    user = auth_db.get_user_by_email(email)

    # Age the pending token past its window.
    auth_db.set_email_verify_token(user["id"], "expired-token-0001", _past_iso())
    expired = await client.post(
        VERIFY_URL, json={"token": "expired-token-0001"}, headers=HEADERS
    )
    assert expired.status == 400

    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        resp = await client.post(RESEND_URL, json={"email": email}, headers=HEADERS)
    assert resp.status == 200

    ok = await client.post(
        VERIFY_URL,
        json={"token": mock_send.call_args.kwargs["token"]},
        headers=HEADERS,
    )
    assert ok.status == 200


# ---------------------------------------------------------------------------
# 2. Anti-enumeration: unknown / already-verified are uniform 200 no-ops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_unknown_email_uniform_response_no_mail_no_audit(
    client, tmp_path
):
    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        with patch("auth.api.dummy_verify"):
            resp = await client.post(
                RESEND_URL, json={"email": "nobody@test.local"}, headers=HEADERS
            )

    assert resp.status == 200
    assert await resp.json() == {"ok": True}
    mock_send.assert_not_called()
    assert _audit_rows(tmp_path) == []


@pytest.mark.asyncio
async def test_resend_already_verified_is_noop(client, fresh_invite, tmp_path):
    email = "resend-verified@test.local"
    token = await _register_and_capture_token(client, email=email)
    verified = await client.post(VERIFY_URL, json={"token": token}, headers=HEADERS)
    assert verified.status == 200
    audit_before = len(_audit_rows(tmp_path))

    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        with patch("auth.api.dummy_verify"):
            resp = await client.post(
                RESEND_URL, json={"email": email}, headers=HEADERS
            )

    assert resp.status == 200
    assert await resp.json() == {"ok": True}
    # Verified account must not be mailed again.
    mock_send.assert_not_called()
    assert len(_audit_rows(tmp_path)) == audit_before


# ---------------------------------------------------------------------------
# 3. Audit row on a real resend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_writes_single_audit_row_without_token(client, fresh_invite, tmp_path):
    email = "resend-audit@test.local"
    await _register_and_capture_token(client, email=email)

    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        await client.post(RESEND_URL, json={"email": email}, headers=HEADERS)
    token = mock_send.call_args.kwargs["token"]

    rows = [r for r in _audit_rows(tmp_path) if r["event"] == "verification_resent"]
    assert len(rows) == 1
    assert rows[0]["level"] == "INFO"
    assert rows[0]["user_id"] == auth_db.get_user_by_email(email)["id"]
    # The token never lands in the audit log (plaintext or otherwise).
    raw_log = (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8")
    assert token not in raw_log


# ---------------------------------------------------------------------------
# 4. Rate limits — 20/email/hour + 20/IP/hour, counted before the lookup
# ---------------------------------------------------------------------------

def test_resend_limiter_constants_match_issue_59():
    assert security.resend_email_limiter._max == 20
    assert security.resend_ip_limiter._max == 20
    assert security.resend_email_limiter._window == 3600
    assert security.resend_ip_limiter._window == 3600


@pytest.mark.asyncio
async def test_resend_email_limit_20_per_hour(client, monkeypatch):
    # Permissive IP limiter so only the per-email counter can trip.
    monkeypatch.setattr(
        "auth.api.resend_ip_limiter", security.SlidingWindowLimiter(10_000, 3600)
    )
    email = "resend-ratelimit@test.local"
    security.resend_email_limiter.reset(email)

    with patch("auth.api.dummy_verify"):
        for _ in range(20):
            resp = await client.post(RESEND_URL, json={"email": email}, headers=HEADERS)
            assert resp.status == 200, "first 20 hits within the hour"
        blocked = await client.post(
            RESEND_URL, json={"email": email}, headers=HEADERS
        )
        # A different email from the same IP is still served — limit is per-email.
        other = await client.post(
            RESEND_URL, json={"email": "resend-other@test.local"}, headers=HEADERS
        )

    assert blocked.status == 429
    assert other.status == 200


@pytest.mark.asyncio
async def test_resend_ip_limit_20_per_hour(client, monkeypatch):
    # Permissive email limiter so only the per-IP counter can trip.
    monkeypatch.setattr(
        "auth.api.resend_email_limiter", security.SlidingWindowLimiter(10_000, 3600)
    )
    security.resend_ip_limiter.reset("127.0.0.1")

    with patch("auth.api.dummy_verify"):
        for i in range(20):
            resp = await client.post(
                RESEND_URL, json={"email": f"resend-ip-{i}@test.local"}, headers=HEADERS
            )
            assert resp.status == 200, "first 20 hits from this IP"
        blocked = await client.post(
            RESEND_URL, json={"email": "resend-ip-21@test.local"}, headers=HEADERS
        )

    assert blocked.status == 429


# ---------------------------------------------------------------------------
# 5. Session fallback + CSRF guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resend_without_email_falls_back_to_session(client, fresh_invite):
    email = "resend-session@test.local"
    await _register_and_capture_token(client, email=email)
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200
    cookie = _session_cookie(login)

    with patch("auth.api.send_verification_email", return_value=True) as mock_send:
        resp = await client.post(
            RESEND_URL,
            json={},
            headers={**HEADERS, "Cookie": f"auth_session={cookie}"},
        )

    assert resp.status == 200
    assert mock_send.call_count == 1
    assert mock_send.call_args.kwargs["to_addr"] == email


@pytest.mark.asyncio
async def test_resend_without_email_and_without_session_rejected(client):
    resp = await client.post(RESEND_URL, json={}, headers=HEADERS)
    assert resp.status == 400


@pytest.mark.asyncio
async def test_resend_malformed_body_rejected(client):
    resp = await client.post(
        RESEND_URL,
        data="not json",
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_resend_requires_csrf_header(client):
    resp = await client.post(RESEND_URL, json={"email": "x@test.local"})
    assert resp.status == 403
