"""Bridge-2 — class ↔ curriculum mounting tests (boss work order 2026-09-11).

Rulings under test:
  #2 a class follows exactly ONE 8-week curriculum; weeks advance linearly and
     skipping is impossible — enforced in the DB / DAO, not the frontend;
  #3 a teacher mounts a ready-made course (body = curriculum_id only), never a
     hand-picked topic list;
  #4 "Week X/8" is the progress unit, so every advance moves exactly one week.

The negative cases are the red-line set demanded by the work order:
repeat mount -> 409, advance without mount -> 409, skipping a week -> 409,
unknown curriculum -> 404, catalog without a role -> 401/403.
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
from pipeline import topic_metadata_schema  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CURRICULUM_ID = "dreamer-curriculum"
OTHER_CURRICULUM_ID = "another-curriculum"


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no auth_session cookie")


def _db_path() -> str:
    return os.environ["DREAMER_DB_PATH"]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _audit_events(tmp_path):
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _seed_curriculum(curriculum_id=CURRICULUM_ID, weeks=range(1, 9),
                     subject="AI Literacy"):
    """Write a ready-made curriculum straight into topic_metadata (Bridge-1 SoT)."""
    conn = _conn()
    try:
        topic_metadata_schema.ensure_schema(conn)
        for week in weeks:
            conn.execute(
                "INSERT INTO topic_metadata (topic_id, subject, topic, "
                "modes_allowed, grade_level, week, dreamer_phase, kb_name, "
                "document_path, document_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{curriculum_id}-wk{week:02d}",
                    subject,
                    f"Week {week} — {subject}",
                    '["contextual"]',
                    "P4-P6",
                    week,
                    '["Design"]',
                    curriculum_id,
                    f"curriculum-wk{week:02d}.md",
                    f"hash-{week}",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _curriculum_rows(class_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT topic_id, week_no, status, activated_at FROM class_curriculum "
            "WHERE class_id = ? ORDER BY week_no ASC",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()


def _class_row(class_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
    finally:
        conn.close()


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
    for code in ("invite-ok-001", "invite-ok-002"):
        auth_db.insert_teacher_invite(
            code=code, created_by="admin-cli", expires_at=_future_iso(days=7)
        )


async def _setup_teacher(client, email="teacher@test.local", invite="invite-ok-001"):
    await client.post(
        "/api/auth/register",
        json={
            "invite_code": invite,
            "email": email,
            "password": "test-pass-teacher1",
        },
        headers=HEADERS,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


async def _setup_parent(client, email="parent-a@test.local"):
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password("test-pass-parent1"),
        role="parent",
        email_verified=True,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-parent1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


async def _create_class(client, token, name="Math Class"):
    resp = await client.post(
        "/api/classes",
        json={"name": name},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


def _auth(token):
    return {**HEADERS, "Cookie": f"auth_session={token}"}


async def _mount(client, token, class_id, curriculum_id=CURRICULUM_ID, **extra):
    body = {"curriculum_id": curriculum_id, **extra}
    return await client.post(
        f"/api/classes/{class_id}/curriculum", json=body, headers=_auth(token)
    )


async def _advance(client, token, class_id):
    return await client.post(
        f"/api/classes/{class_id}/advance-week", headers=_auth(token)
    )


def _force_status(class_id, week_no, status):
    """Bypass the API on purpose — used to build illegal states for the DAO."""
    conn = _conn()
    try:
        conn.execute(
            "UPDATE class_curriculum SET status = ? "
            "WHERE class_id = ? AND week_no = ?",
            (status, class_id, week_no),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Catalog (GET /api/curriculum/catalog)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_catalog_lists_complete_curricula(client, fresh_invite):
    token = await _setup_teacher(client)
    _seed_curriculum()
    _seed_curriculum(OTHER_CURRICULUM_ID, subject="Robotics")

    resp = await client.get("/api/curriculum/catalog", headers=_auth(token))
    assert resp.status == 200, await resp.text()
    catalog = (await resp.json())["curricula"]

    ids = [c["curriculum_id"] for c in catalog]
    assert ids == [OTHER_CURRICULUM_ID, CURRICULUM_ID]  # ordered by kb_name
    assert all(c["week_count"] == 8 and c["ready"] for c in catalog)
    assert [w["week_no"] for w in catalog[1]["weeks"]] == list(range(1, 9))


@pytest.mark.asyncio
async def test_catalog_hides_incomplete_curriculum(client, fresh_invite):
    token = await _setup_teacher(client)
    _seed_curriculum(weeks=range(1, 6))  # only 5 authored weeks

    resp = await client.get("/api/curriculum/catalog", headers=_auth(token))
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["curricula"] == []


@pytest.mark.asyncio
async def test_catalog_requires_role(client, fresh_invite):
    _seed_curriculum()

    anon = await client.get("/api/curriculum/catalog")
    assert anon.status == 401

    parent_token = await _setup_parent(client)
    parent = await client.get(
        "/api/curriculum/catalog", headers=_auth(parent_token)
    )
    assert parent.status == 403

    teacher_token = await _setup_teacher(client)
    teacher = await client.get(
        "/api/curriculum/catalog", headers=_auth(teacher_token)
    )
    assert teacher.status == 200


# ---------------------------------------------------------------------------
# Mount (POST /api/classes/{id}/curriculum)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mount_expands_eight_weeks_week1_active(client, fresh_invite, tmp_path):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()

    resp = await _mount(client, token, cls["id"])
    assert resp.status == 201, await resp.text()
    body = await resp.json()

    assert body["week_count"] == 8
    assert [w["week_no"] for w in body["weeks"]] == list(range(1, 9))
    assert [w["status"] for w in body["weeks"]] == ["active"] + ["locked"] * 7
    assert body["weeks"][0]["activated_at"] is not None
    assert all(w["activated_at"] is None for w in body["weeks"][1:])
    assert [w["topic_id"] for w in body["weeks"]] == [
        f"{CURRICULUM_ID}-wk{w:02d}" for w in range(1, 9)
    ]

    rows = _curriculum_rows(cls["id"])
    assert len(rows) == 8
    assert _class_row(cls["id"])["curriculum_id"] == CURRICULUM_ID

    events = [e["event"] for e in _audit_events(tmp_path)]
    assert "curriculum_mounted" in events


@pytest.mark.asyncio
async def test_mount_unknown_curriculum_returns_404(client, fresh_invite):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()

    resp = await _mount(client, token, cls["id"], curriculum_id="no-such-course")
    assert resp.status == 404, await resp.text()
    assert _curriculum_rows(cls["id"]) == []


@pytest.mark.asyncio
async def test_mount_incomplete_curriculum_returns_409(client, fresh_invite):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum(weeks=range(1, 7))

    resp = await _mount(client, token, cls["id"])
    assert resp.status == 409, await resp.text()
    assert _curriculum_rows(cls["id"]) == []


@pytest.mark.asyncio
async def test_repeat_mount_returns_409(client, fresh_invite):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()
    _seed_curriculum(OTHER_CURRICULUM_ID, subject="Robotics")

    first = await _mount(client, token, cls["id"])
    assert first.status == 201, await first.text()

    again = await _mount(client, token, cls["id"])
    assert again.status == 409, await again.text()

    other = await _mount(client, token, cls["id"], OTHER_CURRICULUM_ID)
    assert other.status == 409, await other.text()

    rows = _curriculum_rows(cls["id"])
    assert len(rows) == 8  # the original mount is untouched
    assert rows[0]["topic_id"] == f"{CURRICULUM_ID}-wk01"


@pytest.mark.asyncio
async def test_mount_rejects_topic_picking(client, fresh_invite):
    """Ruling #3: one curriculum_id, no free composition of topics."""
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()

    resp = await _mount(
        client, token, cls["id"], topic_ids=["t1", "t2"], week_no=3
    )
    assert resp.status == 400, await resp.text()
    assert _curriculum_rows(cls["id"]) == []


@pytest.mark.asyncio
async def test_mount_requires_teacher_and_ownership(client, fresh_invite):
    owner = await _setup_teacher(client)
    other = await _setup_teacher(client, email="teacher2@test.local",
                                 invite="invite-ok-002")
    cls = await _create_class(client, owner)
    _seed_curriculum()

    parent_token = await _setup_parent(client)
    parent = await _mount(client, parent_token, cls["id"])
    assert parent.status == 403

    foreign = await _mount(client, other, cls["id"])
    assert foreign.status == 403
    assert _curriculum_rows(cls["id"]) == []

    anon = await client.post(
        f"/api/classes/{cls['id']}/curriculum",
        json={"curriculum_id": CURRICULUM_ID},
        headers=HEADERS,
    )
    assert anon.status == 401


# ---------------------------------------------------------------------------
# Advance (POST /api/classes/{id}/advance-week)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_advance_moves_exactly_one_week(client, fresh_invite, tmp_path):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()
    await _mount(client, token, cls["id"])

    resp = await _advance(client, token, cls["id"])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["completed_week"] == 1
    assert body["active_week"] == 2
    assert body["course_completed"] is False

    statuses = {w["week_no"]: w["status"] for w in body["weeks"]}
    assert statuses[1] == "completed"
    assert statuses[2] == "active"
    assert all(statuses[w] == "locked" for w in range(3, 9))
    assert body["weeks"][1]["activated_at"] is not None

    advanced = [e for e in _audit_events(tmp_path)
                if e["event"] == "curriculum_week_advanced"]
    assert len(advanced) == 1
    assert advanced[0]["week_no"] == 1 and advanced[0]["active_week"] == 2


@pytest.mark.asyncio
async def test_advance_without_mount_returns_409(client, fresh_invite):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)

    resp = await _advance(client, token, cls["id"])
    assert resp.status == 409, await resp.text()


@pytest.mark.asyncio
async def test_advance_rejects_gap(client, fresh_invite):
    """Two open weeks are illegal; so is a hole in the completed run."""
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()
    await _mount(client, token, cls["id"])

    _force_status(cls["id"], 1, "completed")
    _force_status(cls["id"], 3, "active")  # week 2 still locked -> hole

    resp = await _advance(client, token, cls["id"])
    assert resp.status == 409, await resp.text()


@pytest.mark.asyncio
async def test_advance_after_week8_returns_409(client, fresh_invite):
    token = await _setup_teacher(client)
    cls = await _create_class(client, token)
    _seed_curriculum()
    await _mount(client, token, cls["id"])

    for _ in range(7):  # week 1 -> active week 8
        resp = await _advance(client, token, cls["id"])
        assert resp.status == 200, await resp.text()

    last = await _advance(client, token, cls["id"])
    assert last.status == 200, await last.text()
    body = await last.json()
    assert body["completed_week"] == 8
    assert body["active_week"] is None
    assert body["course_completed"] is True
    assert all(w["status"] == "completed" for w in body["weeks"])

    beyond = await _advance(client, token, cls["id"])
    assert beyond.status == 409, await beyond.text()


@pytest.mark.asyncio
async def test_advance_requires_role_and_ownership(client, fresh_invite):
    owner = await _setup_teacher(client)
    other = await _setup_teacher(client, email="teacher2@test.local",
                                 invite="invite-ok-002")
    cls = await _create_class(client, owner)
    _seed_curriculum()
    await _mount(client, owner, cls["id"])

    parent_token = await _setup_parent(client)
    assert (await _advance(client, parent_token, cls["id"])).status == 403
    assert (await _advance(client, other, cls["id"])).status == 403

    statuses = {r["week_no"]: r["status"] for r in _curriculum_rows(cls["id"])}
    assert statuses[1] == "active"


# ---------------------------------------------------------------------------
# DB-level guards (decision 2 must not depend on the frontend)
# ---------------------------------------------------------------------------

def test_db_guard_rejects_two_active_weeks(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "guard.db"))
    auth_db.ensure_schema()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO classes (id, teacher_id, name, join_code, class_type, "
            "grade_band, is_one_on_one, created_at) "
            "VALUES ('c1', 't1', 'C', 'CODE1', 'monthly', 'P1-P3', 0, 'now')"
        )
        topic_metadata_schema.ensure_schema(conn)
        conn.execute(
            "INSERT INTO class_curriculum (class_id, topic_id, week_no, status, "
            "created_at) VALUES ('c1', 'x', 1, 'active', 'now')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO class_curriculum (class_id, topic_id, week_no, "
                "status, created_at) VALUES ('c1', 'y', 2, 'active', 'now')"
            )
            conn.commit()
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE class_curriculum SET status = 'outside' WHERE week_no = 1"
            )
            conn.commit()
    finally:
        conn.close()


def test_bridge2_migration_is_idempotent(tmp_path, monkeypatch):
    """Lesson #39: a pre-Bridge-2 DB must migrate cleanly, twice."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "legacy.db"))
    conn = _conn()
    try:
        conn.execute(
            "CREATE TABLE classes (id TEXT PRIMARY KEY, teacher_id TEXT, "
            "name TEXT, join_code TEXT, class_type TEXT, grade_band TEXT, "
            "is_one_on_one INTEGER, created_at TEXT)"
        )
        conn.commit()
    finally:
        conn.close()

    auth_db.apply_class_curriculum_migration()
    auth_db.apply_class_curriculum_migration()
    auth_db.ensure_schema()

    conn = _conn()
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(classes)")}
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    finally:
        conn.close()

    assert "curriculum_id" in cols
    assert "class_curriculum" in tables
    assert "idx_class_curriculum_one_active" in indexes
