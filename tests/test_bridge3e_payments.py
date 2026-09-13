"""Bridge-3e — payment mark-paid (boss work order 2026-09-13, decision ②).

Surfaces under test:
  * POST /api/admin/payments/{student_id}/mark-paid     (admin only, note?)
  * POST /api/admin/payments/{student_id}/mark-pending  (the undo path)
  * GET  /api/admin/payments?status=pending|paid        (reconciliation list)
  * GET  /api/parent/curriculum gains ``payment_status`` ('pending' | 'paid')

Laws pinned here (the negative set is CI-red-line material, registered in the
ci.yml pytest manifest):
  * one row per student — a flip UPDATEs that row, it never inserts a second;
  * mark is idempotent: a repeat mark-paid is a normal 200, never a 500;
  * audit: one ``payment_marked`` line per mark (actor + masked student
    pointer + timestamp) and NEVER the amount — the operator's free-text note
    deliberately stays out of the trail;
  * anonymous 401 / non-admin 403 (parent AND teacher) / unknown student 404 /
    bad ``?status=`` 400 / a parent can never read another family's payment.
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
LIST_URL = "/api/admin/payments"
MAP_URL = "/api/parent/curriculum"


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _session_cookie(resp) -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no auth_session cookie")


def _auth(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"auth_session={token}"}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _payment_rows(student_id: str) -> list[dict]:
    """Raw payments rows for one student — the one-row law is asserted here."""
    conn = _conn()
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM payments WHERE student_id = ?", (student_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


def _audit_events(tmp_path, event="payment_marked") -> list[dict]:
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        entry
        for entry in (
            json.loads(line)
            for line in audit_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if entry.get("event") == event
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


async def _setup_session(client, email, *, role="parent", password="test-pass-3e-1"):
    """Create a user with an explicit role and log them in."""
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password(password),
        role=role,
        email_verified=True,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return user_id, _session_cookie(login)


def _seed_student(*, parent_id, first_name="Mia") -> str:
    auth_db.ensure_schema()
    student_id = str(uuid.uuid4())
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO students (id, parent_id, teacher_id, first_name, "
            "age_band, lang_code, pin_hash, pin_lock_until, failed_pin_count, "
            "created_at) VALUES (?, ?, NULL, ?, 'P4-P6', 'zh-hk', 'x', NULL, 0, ?)",
            (student_id, parent_id, first_name, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return student_id


async def _mark(client, student_id, kind="paid", *, token=None, note=None):
    headers = _auth(token) if token else HEADERS
    return await client.post(
        f"/api/admin/payments/{student_id}/mark-{kind}",
        json={} if note is None else {"note": note},
        headers=headers,
    )


async def _list(client, *, token=None, status=None):
    headers = _auth(token) if token else HEADERS
    url = LIST_URL if status is None else f"{LIST_URL}?status={status}"
    return await client.get(url, headers=headers)


async def _parent_payload(client, token, student_id):
    return await client.get(
        f"{MAP_URL}?student_id={student_id[:8]}", headers=_auth(token)
    )


# ---------------------------------------------------------------------------
# Negative set — CI red line
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_paid_rejects_anonymous_and_non_admin(client):
    """Anonymous -> 401; parent AND teacher -> 403; state stays pending."""
    _, parent_token = await _setup_session(client, "parent-a@test.local")
    _, teacher_token = await _setup_session(
        client, "teacher-a@test.local", role="teacher"
    )
    student_id = _seed_student(parent_id="parent-a-id")

    anon = await _mark(client, student_id)
    assert anon.status == 401, await anon.text()

    as_parent = await _mark(client, student_id, token=parent_token)
    assert as_parent.status == 403, await as_parent.text()

    as_teacher = await _mark(client, student_id, token=teacher_token)
    assert as_teacher.status == 403, await as_teacher.text()

    assert _payment_rows(student_id) == []


@pytest.mark.asyncio
async def test_mark_pending_rejects_non_admin(client):
    _, parent_token = await _setup_session(client, "parent-a@test.local")
    student_id = _seed_student(parent_id="parent-a-id")

    assert (await _mark(client, student_id, "pending")).status == 401
    denied = await _mark(client, student_id, "pending", token=parent_token)
    assert denied.status == 403, await denied.text()


@pytest.mark.asyncio
async def test_mark_paid_unknown_student_is_404(client):
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")

    resp = await _mark(client, str(uuid.uuid4()), token=admin_token)
    assert resp.status == 404, await resp.text()


@pytest.mark.asyncio
async def test_payment_list_rejects_anonymous_and_non_admin(client):
    _, parent_token = await _setup_session(client, "parent-a@test.local")

    assert (await _list(client)).status == 401
    assert (await _list(client, token=parent_token)).status == 403


@pytest.mark.asyncio
async def test_payment_list_rejects_unknown_status_filter(client):
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")

    resp = await _list(client, token=admin_token, status="refunded")
    assert resp.status == 400, await resp.text()


@pytest.mark.asyncio
async def test_parent_cannot_read_another_family_payment(client):
    """Cross-family read stays the unified 403 with no payload leak."""
    parent_a_id, _ = await _setup_session(client, "parent-a@test.local")
    _, parent_b = await _setup_session(client, "parent-b@test.local")
    child_a = _seed_student(parent_id=parent_a_id)

    resp = await _parent_payload(client, parent_b, child_a)
    assert resp.status == 403, await resp.text()


# ---------------------------------------------------------------------------
# The flip itself
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_paid_flips_parent_payload_and_audits(client, tmp_path):
    admin_id, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    parent_id, parent_token = await _setup_session(client, "parent-a@test.local")
    student_id = _seed_student(parent_id=parent_id)

    before = await _parent_payload(client, parent_token, student_id)
    assert before.status == 200, await before.text()
    assert (await before.json())["payment_status"] == "pending"

    resp = await _mark(client, student_id, token=admin_token, note="Sep tuition")
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["status"] == "paid"
    assert body["student_id"] == student_id[:8]
    assert body["note"] == "Sep tuition"

    after = await _parent_payload(client, parent_token, student_id)
    assert (await after.json())["payment_status"] == "paid"

    rows = _payment_rows(student_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "paid"
    assert rows[0]["marked_by"] == admin_id

    events = _audit_events(tmp_path)
    assert len(events) == 1
    assert events[0]["user_id"] == admin_id
    assert events[0]["target_id"] == student_id[:8]
    # The amount rule: the operator note never reaches the audit trail.
    raw = (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8")
    assert "Sep tuition" not in raw


@pytest.mark.asyncio
async def test_repeat_mark_paid_is_idempotent(client):
    """Second mark-paid is a normal 200 and still one row - never a 500."""
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    student_id = _seed_student(parent_id="parent-a-id")

    first = await _mark(client, student_id, token=admin_token)
    second = await _mark(client, student_id, token=admin_token)
    assert first.status == 200, await first.text()
    assert second.status == 200, await second.text()

    rows = _payment_rows(student_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "paid"


@pytest.mark.asyncio
async def test_mark_pending_restores_and_audits_twice(client, tmp_path):
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    parent_id, parent_token = await _setup_session(client, "parent-a@test.local")
    student_id = _seed_student(parent_id=parent_id)

    assert (await _mark(client, student_id, token=admin_token)).status == 200
    restore = await _mark(client, student_id, "pending", token=admin_token)
    assert restore.status == 200, await restore.text()
    assert (await restore.json())["status"] == "pending"

    payload = await _parent_payload(client, parent_token, student_id)
    assert (await payload.json())["payment_status"] == "pending"
    assert len(_payment_rows(student_id)) == 1
    assert len(_audit_events(tmp_path)) == 2


@pytest.mark.asyncio
async def test_mark_paid_without_body_is_allowed(client):
    """The note is optional: an empty POST body is a normal mark."""
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    student_id = _seed_student(parent_id="parent-a-id")

    resp = await client.post(
        f"{LIST_URL}/{student_id}/mark-paid", headers=_auth(admin_token)
    )
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["note"] is None


@pytest.mark.asyncio
async def test_overlong_note_is_rejected(client):
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    student_id = _seed_student(parent_id="parent-a-id")

    resp = await _mark(client, student_id, token=admin_token, note="x" * 501)
    assert resp.status == 400, await resp.text()
    assert _payment_rows(student_id) == []


# ---------------------------------------------------------------------------
# Reconciliation list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_splits_pending_and_paid(client):
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    paid_child = _seed_student(parent_id="parent-a-id", first_name="Mia")
    pending_child = _seed_student(parent_id="parent-b-id", first_name="Kai")

    assert (await _mark(client, paid_child, token=admin_token)).status == 200

    pending = await _list(client, token=admin_token, status="pending")
    assert pending.status == 200, await pending.text()
    pending_ids = [p["student_id"] for p in (await pending.json())["payments"]]
    assert pending_ids == [pending_child[:8]]

    paid = await _list(client, token=admin_token, status="paid")
    paid_ids = [p["student_id"] for p in (await paid.json())["payments"]]
    assert paid_ids == [paid_child[:8]]

    everyone = await _list(client, token=admin_token)
    assert len((await everyone.json())["payments"]) == 2


@pytest.mark.asyncio
async def test_list_masked_id_round_trips_into_mark(client):
    """The console only ever holds the mask; the mask must be markable."""
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    student_id = _seed_student(parent_id="parent-a-id")

    listing = await _list(client, token=admin_token, status="pending")
    masked = (await listing.json())["payments"][0]["student_id"]
    assert masked == student_id[:8]

    resp = await _mark(client, masked, token=admin_token)
    assert resp.status == 200, await resp.text()
    assert _payment_rows(student_id)[0]["status"] == "paid"


@pytest.mark.asyncio
async def test_list_never_leaks_marked_by(client):
    """The list carries the status, not the acting admin's user id."""
    _, admin_token = await _setup_session(client, "admin@test.local", role="admin")
    student_id = _seed_student(parent_id="parent-a-id")
    assert (await _mark(client, student_id, token=admin_token)).status == 200

    listing = await _list(client, token=admin_token)
    entry = (await listing.json())["payments"][0]
    assert set(entry) == {"student_id", "first_name", "status", "marked_at", "note"}
