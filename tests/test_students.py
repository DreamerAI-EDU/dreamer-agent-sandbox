"""W2 PR#3 — students + PIN tests (8 cases, brief §6 #5-12).

Covers: parent creating a student row (B24 forbidden-column scan),
age_band/lang_code enum validation, Argon2id PIN hashing, correct/wrong
PIN verification with failure counting, 10-strike 1-minute lockout,
pin-reset immediate use + unlock, cross-parent/cross-teacher pin-verify
rejection with security log, and GET /api/students per-parent filtering.

API responses only ever carry the masked (8-char prefix) student id; the
PIN endpoints are keyed by the full server-side id, so tests resolve the
full id from the test DB before calling them.

No real passwords anywhere: all fixtures use `test-pass-` / `test-pin-`
style values (B24 guard enforces this repo-wide).
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

# B24: columns that must never appear on a student record.
FORBIDDEN_COLUMNS = {
    "last_name", "school", "dob", "date_of_birth", "full_name", "address",
    "phone", "email", "photo", "national_id", "hkid",
}

EXPECTED_COLUMNS = {
    "id", "parent_id", "teacher_id", "first_name", "age_band", "lang_code",
    "pin_hash", "pin_lock_until", "failed_pin_count", "created_at",
}


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


async def _setup_logged_in_user(client):
    await _register_teacher(client)
    login = await _login(client)
    assert login.status == 200
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


def _student_columns():
    conn = sqlite3.connect(_db_path())
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(students)")}
    finally:
        conn.close()
    return cols


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
    auth_db.insert_teacher_invite(
        code="invite-ok-001",
        created_by="admin-cli",
        expires_at=_future_iso(days=7),
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


async def _create_class_via_api(client, token, *, name="Test Class"):
    resp = await client.post(
        "/api/classes",
        json={"name": name},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


# ---------------------------------------------------------------------------
# 5. Parent creates a student → row complete, B24 forbidden-column scan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parent_creates_student_row_complete_and_b24_clean(
    client, fresh_invite
):
    parent_id, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)

    resp = await client.post(
        "/api/students",
        json={
            "first_name": "小明",
            "age_band": "P1-P3",
            "lang_code": "zh-hk",
            "pin": "2468",
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    student = body["student"]

    full_id = _full_student_id(mask=student["id"])
    assert student["id"] == full_id[:8]     # masked prefix, not the full id

    row = _student_row(full_id)
    assert row is not None
    assert row[1] == parent_id          # parent_id bound directly
    assert row[2] is None               # no teacher
    assert row[3] == "小明"
    assert row[4] == "P1-P3"
    assert row[5] == "zh-hk"
    assert row[7] is None               # pin_lock_until
    assert row[8] == 0                  # failed_pin_count
    assert row[9] is not None           # created_at

    # Response must not echo the PIN or expose the full student id.
    assert "pin" not in body
    assert "pin_hash" not in body
    assert len(student["id"]) == 8

    # B24 scan: students table carries no forbidden column.
    cols = _student_columns()
    assert cols == EXPECTED_COLUMNS
    assert not (cols & FORBIDDEN_COLUMNS)


# ---------------------------------------------------------------------------
# 6. Bad age_band / lang_code / missing first_name → rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_student_rejects_bad_enums_and_blank_name(
    client, fresh_invite
):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    base = {
        "first_name": "小明",
        "age_band": "P1-P3",
        "lang_code": "zh-hk",
        "pin": "2468",
    }

    for mutate in (
        {"age_band": "P2"},              # not in enum
        {"age_band": "P1-P3-P4"},        # garbage
        {"lang_code": "fr"},             # not in enum
        {"lang_code": "zh"},             # too generic
        {"first_name": ""},              # blank name
        {"pin": "12"},                   # not 4 digits
        {"pin": "abcd"},                 # not digits
    ):
        payload = dict(base, **mutate)
        resp = await client.post(
            "/api/students",
            json=payload,
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 400, f"payload {payload!r} must be rejected"

    # Nothing was inserted.
    conn = sqlite3.connect(_db_path())
    try:
        count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# 7. pin_hash is Argon2id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_hash_is_argon2id(client, fresh_invite):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)

    resp = await client.post(
        "/api/students",
        json={
            "first_name": "小明",
            "age_band": "P1-P3",
            "lang_code": "zh-hk",
            "pin": "1357",
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201

    body = await resp.json()
    full_id = _full_student_id(mask=body["student"]["id"])
    row = _student_row(full_id)
    assert row[6].startswith("$argon2id$")
    assert "1357" not in row[6]  # never stored in plaintext


# ---------------------------------------------------------------------------
# 8. Correct PIN passes; wrong PIN increments failure count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_verify_correct_passes_wrong_counts(client, fresh_invite):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")

    # Wrong PIN → 401, failure count increments.
    wrong = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "9999"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert wrong.status == 401
    assert _student_row(student_id)[8] == 1

    # Correct PIN → 200, failure count cleared.
    ok = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert ok.status == 200, await ok.text()
    assert _student_row(student_id)[8] == 0


# ---------------------------------------------------------------------------
# 9. 10 consecutive failures → 1-minute lockout; correct PIN also rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_lockout_after_10_failures_blocks_even_correct_pin(
    client, fresh_invite
):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")
    url = f"/api/students/{student_id}/pin-verify"

    for attempt in range(10):
        resp = await client.post(
            url, json={"pin": "9999"},
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 401, f"failure {attempt + 1} must be 401"

    row = _student_row(student_id)
    assert row[7] is not None        # pin_lock_until set
    assert row[8] == 0               # counter reset after lock

    # Locked: even the correct PIN is rejected with 429.
    locked = await client.post(
        url, json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert locked.status == 429


# ---------------------------------------------------------------------------
# 10. pin-reset → immediate use + unlock (clears pin_lock_until)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_reset_immediate_use_and_unlock(client, fresh_invite,
                                                  tmp_path):
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")
    url = f"/api/students/{student_id}/pin-verify"

    # Lock the student first (10 wrong attempts).
    for _ in range(10):
        await client.post(
            url, json={"pin": "9999"},
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
    assert _student_row(student_id)[7] is not None

    # Reset to a new PIN → 200.
    reset = await client.post(
        f"/api/students/{student_id}/pin-reset",
        json={"pin": "2468"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert reset.status == 200, await reset.text()

    row = _student_row(student_id)
    assert row[7] is None           # unlocked
    assert row[8] == 0
    assert row[6].startswith("$argon2id$")

    # New PIN works immediately; old PIN no longer works.
    new_ok = await client.post(
        url, json={"pin": "2468"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert new_ok.status == 200
    old = await client.post(
        url, json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert old.status == 401

    # Audit log carries the PIN reset event.
    events = _audit_events(tmp_path)
    assert any(e["event"] == "pin_reset" for e in events)


# ---------------------------------------------------------------------------
# 11. Cross-parent / cross-teacher pin-verify → rejected + security log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_verify_cross_parent_and_cross_teacher_rejected(
    client, fresh_invite, tmp_path
):
    parent_a, email_a, pw_a = _create_parent_user("parent-a@test.local")
    token_a = await _login_parent(client, email_a, pw_a)
    student_id = await _create_student_via_api(client, token_a)

    # Another parent cannot verify someone else's student.
    _, email_b, pw_b = _create_parent_user("parent-b@test.local")
    token_b = await _login_parent(client, email_b, pw_b)
    cross_parent = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token_b}"},
    )
    assert cross_parent.status == 403

    # A teacher who does not teach the student cannot verify either.
    teacher_token = await _setup_logged_in_user(client)
    cross_teacher = await client.post(
        f"/api/students/{student_id}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={teacher_token}"},
    )
    assert cross_teacher.status == 403

    # Both attempts landed a security-log entry (WARNING, both ids).
    events = _audit_events(tmp_path)
    pin_events = [e for e in events if e["event"] == "pin_verify_cross_access"]
    assert len(pin_events) == 2
    for e in pin_events:
        assert e["level"] == "WARNING"
        assert e["target_id"] == student_id


# ---------------------------------------------------------------------------
# 12. GET /api/students filters per parent — cannot see others' students
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_students_filtered_per_parent(client, fresh_invite):
    parent_a, email_a, pw_a = _create_parent_user("parent-a@test.local")
    token_a = await _login_parent(client, email_a, pw_a)
    student_a = await _create_student_via_api(client, token_a)

    _, email_b, pw_b = _create_parent_user("parent-b@test.local")
    token_b = await _login_parent(client, email_b, pw_b)
    student_b = await _create_student_via_api(client, token_b)

    # Parent A sees only their own student (masked id).
    resp_a = await client.get(
        "/api/students", headers={"Cookie": f"auth_session={token_a}"}
    )
    assert resp_a.status == 200
    ids_a = [s["id"] for s in (await resp_a.json())["students"]]
    assert student_a[:8] in ids_a
    assert student_b[:8] not in ids_a

    # Parent B sees only theirs.
    resp_b = await client.get(
        "/api/students", headers={"Cookie": f"auth_session={token_b}"}
    )
    assert resp_b.status == 200
    ids_b = [s["id"] for s in (await resp_b.json())["students"]]
    assert student_b[:8] in ids_b
    assert student_a[:8] not in ids_b


# ---------------------------------------------------------------------------
# 13. W2 PR#5 — pin-verify / pin-reset accept the 8-char mask prefix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_verify_mask_prefix_unique_match(client, fresh_invite):
    """A unique 8-char mask prefix resolves to the student and verifies."""
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    student_id = await _create_student_via_api(client, token, pin="1357")

    mask = student_id[:8]
    ok = await client.post(
        f"/api/students/{mask}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert ok.status == 200, await ok.text()

    # The same prefix also works for pin-reset.
    reset = await client.post(
        f"/api/students/{mask}/pin-reset",
        json={"pin": "2468"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert reset.status == 200, await reset.text()
    row = _student_row(student_id)
    assert row[6].startswith("$argon2id$")


@pytest.mark.asyncio
async def test_pin_verify_mask_prefix_no_match_403(client, fresh_invite):
    """A prefix matching no reachable student → 403 with the unified wording."""
    _, email, pw = _create_parent_user()
    token = await _login_parent(client, email, pw)
    await _create_student_via_api(client, token, pin="1357")

    no_match = await client.post(
        "/api/students/00000000/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert no_match.status == 403
    assert (await no_match.json())["error"] == "無權操作"

    # Full id unknown keeps the same 403 (no id-existence oracle).
    unknown = await client.post(
        f"/api/students/{uuid.uuid4()}/pin-verify",
        json={"pin": "1357"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert unknown.status == 403
    assert (await unknown.json())["error"] == "無權操作"
