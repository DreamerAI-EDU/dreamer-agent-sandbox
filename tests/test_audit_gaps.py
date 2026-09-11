"""W6 audit-gap PR — handler-level audit rows for state-changing endpoints.

Covers the gaps found in auth/api.py: register, verify-email, create-class and
create-student each append exactly one INFO row to the JSONL audit channel on
success, and append nothing on a rejected path.

No real passwords anywhere: fixtures use the repo-wide `test-pass-xxx` form.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import security as auth_security  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

TEACHER_EMAIL = "teacher-audit@test.local"
TEACHER_PASSWORD = "test-pass-teacher1"
PARENT_EMAIL = "parent-audit@test.local"
PARENT_PASSWORD = "test-pass-parent1"


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    """Extract auth_session token from a login response (see test_auth)."""
    set_cookies = resp.headers.getall("Set-Cookie", [])
    for sc in set_cookies:
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no auth_session cookie in {set_cookies}")


async def _register_teacher(client, *, email=TEACHER_EMAIL,
                            password=TEACHER_PASSWORD, invite="invite-ok-001"):
    return await client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": password},
        headers=HEADERS,
    )


async def _login(client, *, email, password):
    return await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )


async def _teacher_session(client):
    reg = await _register_teacher(client)
    assert reg.status == 201, await reg.text()
    login = await _login(client, email=TEACHER_EMAIL, password=TEACHER_PASSWORD)
    assert login.status == 200, await login.text()
    return _session_cookie(login)


def _create_parent_user():
    """Create a parent user directly in DB (role=parent, verified)."""
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=PARENT_EMAIL,
        password_hash=auth_security.hash_password(PARENT_PASSWORD),
        role="parent",
        email_verified=True,
    )
    return user_id


async def _parent_session(client):
    _create_parent_user()
    login = await _login(client, email=PARENT_EMAIL, password=PARENT_PASSWORD)
    assert login.status == 200, await login.text()
    return _session_cookie(login)


def _audit_path() -> Path:
    return Path(consent_mod.AUDIT_LOG_PATH)


def _audit_rows(*, event: str | None = None) -> list[dict]:
    path = _audit_path()
    if not path.exists():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if event is None:
        return rows
    return [r for r in rows if r.get("event") == event]


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
    auth_db.insert_teacher_invite(
        code="invite-ok-001",
        created_by="admin-cli",
        expires_at=_future_iso(days=7),
    )


# ---------------------------------------------------------------------------
# 1. register → one INFO user_registered row, no credentials in the channel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_appends_user_registered_audit(client, fresh_invite):
    resp = await _register_teacher(client)
    assert resp.status == 201, await resp.text()
    user_id = (await resp.json())["user"]["id"]

    rows = _audit_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["level"] == "INFO"
    assert row["event"] == "user_registered"
    assert row["user_id"] == user_id
    assert row["target_id"] is None
    assert row["timestamp"]

    # The audit channel never carries credentials or the raw email.
    raw = _audit_path().read_text(encoding="utf-8")
    assert TEACHER_PASSWORD not in raw
    assert TEACHER_EMAIL not in raw


# ---------------------------------------------------------------------------
# 2. rejected register → zero writes to the audit channel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_register_appends_nothing(client):
    resp = await _register_teacher(client, invite="invite-bad-000")
    assert resp.status == 400, await resp.text()
    assert _audit_rows() == []


# ---------------------------------------------------------------------------
# 3. create class → one INFO class_created row carrying the new class id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_class_appends_class_created_audit(client, fresh_invite):
    token = await _teacher_session(client)

    resp = await client.post(
        "/api/classes",
        json={"name": "Audit 示範班"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    class_id = body["class"]["id"]

    registered = _audit_rows(event="user_registered")
    assert len(registered) == 1
    rows = _audit_rows(event="class_created")
    assert len(rows) == 1
    assert rows[0]["level"] == "INFO"
    assert rows[0]["user_id"] == registered[0]["user_id"]
    assert rows[0]["target_id"] == class_id


# ---------------------------------------------------------------------------
# 4. non-teacher create class (403) → no class_created row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_class_forbidden_appends_no_audit(client):
    token = await _parent_session(client)

    resp = await client.post(
        "/api/classes",
        json={"name": "Nope"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 403, await resp.text()
    assert _audit_rows(event="class_created") == []


# ---------------------------------------------------------------------------
# 5. create student → one INFO student_created row with the full student id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_student_appends_student_created_audit(client, tmp_path):
    parent_id = _create_parent_user()
    login = await _login(client, email=PARENT_EMAIL, password=PARENT_PASSWORD)
    assert login.status == 200, await login.text()
    token = _session_cookie(login)

    resp = await client.post(
        "/api/students",
        json={
            "first_name": "Audit Child",
            "age_band": "P1-P3",
            "lang_code": "zh-hk",
            "pin": "1234",
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    masked_id = (await resp.json())["student"]["id"]

    conn = sqlite3.connect(str(tmp_path / "auth_test.db"))
    try:
        full_id = conn.execute(
            "SELECT id FROM students WHERE parent_id = ?", (parent_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    rows = _audit_rows(event="student_created")
    assert len(rows) == 1
    assert rows[0]["level"] == "INFO"
    assert rows[0]["user_id"] == parent_id
    assert rows[0]["target_id"] == full_id
    assert full_id.startswith(masked_id)


# ---------------------------------------------------------------------------
# 6. verify email → one email_verified row; a replayed token writes nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_email_appends_single_audit_row(client, fresh_invite):
    await _register_teacher(client)
    user = auth_db.get_user_by_email(TEACHER_EMAIL)
    assert user["email_verify_token"]

    resp = await client.post(
        "/api/auth/verify-email",
        json={"token": user["email_verify_token"]},
        headers=HEADERS,
    )
    assert resp.status == 200, await resp.text()

    rows = _audit_rows(event="email_verified")
    assert len(rows) == 1
    assert rows[0]["level"] == "INFO"
    assert rows[0]["user_id"] == user["id"]

    # Single-use token: the replay path is a 400 and must not log again.
    replay = await client.post(
        "/api/auth/verify-email",
        json={"token": user["email_verify_token"]},
        headers=HEADERS,
    )
    assert replay.status == 400, await replay.text()
    assert len(_audit_rows(event="email_verified")) == 1
