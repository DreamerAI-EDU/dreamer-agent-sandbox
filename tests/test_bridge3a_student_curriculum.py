"""Bridge-3a — kid-facing "Week X / 8" badge (boss work order 2026-09-11).

Rulings under test (the five amendments on top of the spec skeleton):
  #1 ``unit_title`` is authored server-side (topic_metadata, the label_soften
     tradition) — the internal topic_id never crosses the wire and the frontend
     never translates one;
  #2 student guard: a parent only ever reads its OWN child (cross-class attempt
     -> unified 403); no class / no mounted course -> 200 with a neutral state,
     never a 500 on a child surface;
  #3 ``week_index`` = the ``week_no`` of the class's ONE active week; the full
     8 weeks done -> "8/8 · 完成" (the Bridge-2 ``course_completed`` state);
  #4 the negative set below is CI-red-line material (cross-child 403 / no-course
     neutral / anonymous 401 / unit_title is the kid-facing string);
  #5 exercised for real in the container trial (see the PR report).

This file is part of the CI manifest (phase2-tests) — see .github/workflows/ci.yml.
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
UNIT_URL = "/api/student/curriculum"


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    for sc in resp.headers.getall("Set-Cookie", []):
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no auth_session cookie")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _auth(token) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"auth_session={token}"}


def _audit_events(tmp_path) -> list[dict]:
    audit_file = tmp_path / "audit_log.jsonl"
    if not audit_file.exists():
        return []
    return [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _seed_curriculum(curriculum_id: str = CURRICULUM_ID, weeks=range(1, 9)):
    """Ready-made 8-week course straight into topic_metadata (Bridge-1 SoT)."""
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
                    f"curriculum-wk{week:02d}",
                    "AI Literacy",
                    f"Week {week} kid-facing unit",  # authored child-facing text
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


def _seed_student(*, parent_id, class_id=None, status="confirmed",
                  first_name="Mia") -> str:
    """Student row (+ optional class_students membership) for the kid surface."""
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
        if class_id is not None:
            conn.execute(
                "INSERT INTO class_students (class_id, student_id, status, "
                "created_at) VALUES (?, ?, ?, ?)",
                (class_id, student_id, status, _now_iso()),
            )
        conn.commit()
    finally:
        conn.close()
    return student_id


def _force_week(class_id: str, week_no: int, status: str) -> None:
    """Bypass the API on purpose — build illegal / half-migrated states."""
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
def teacher_invite():
    for code in ("invite-ok-001", "invite-ok-002"):
        auth_db.insert_teacher_invite(
            code=code, created_by="admin-cli", expires_at=_future_iso(days=7)
        )


async def _setup_teacher(client, email="teacher@test.local", invite="invite-ok-001"):
    await client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


async def _setup_parent(client, email="parent-a@test.local", role="parent"):
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password("test-pass-parent1"),
        role=role,
        email_verified=True,
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-pass-parent1"},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return user_id, _session_cookie(login)


async def _parent_child(client, email, *, class_id=None, status="confirmed"):
    """A logged-in parent plus one child (optionally in a class)."""
    user_id, token = await _setup_parent(client, email)
    student_id = _seed_student(parent_id=user_id, class_id=class_id, status=status)
    return user_id, token, student_id


async def _create_class(client, token, name="AI Class"):
    resp = await client.post(
        "/api/classes", json={"name": name}, headers=_auth(token)
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


async def _mount(client, token, class_id, curriculum_id=CURRICULUM_ID):
    resp = await client.post(
        f"/api/classes/{class_id}/curriculum",
        json={"curriculum_id": curriculum_id},
        headers=_auth(token),
    )
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _advance(client, token, class_id):
    return await client.post(
        f"/api/classes/{class_id}/advance-week", headers=_auth(token)
    )


async def _badge(client, token, identifier):
    return await client.get(
        f"{UNIT_URL}?student={identifier}", headers=_auth(token)
    )


async def _mounted_child_class(client, teacher_token, *, parent_email):
    """Teacher class + mounted course + one confirmed child of that parent."""
    _seed_curriculum()
    class_id = (await _create_class(client, teacher_token))["id"]
    await _mount(client, teacher_token, class_id)
    user_id, token, student_id = await _parent_child(
        client, parent_email, class_id=class_id
    )
    return class_id, token, student_id


# ---------------------------------------------------------------------------
# Positive path — Week X / 8, backend-stated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_badge_shows_active_week_one(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    resp = await _badge(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body == {
        "state": "active",
        "week_index": 1,
        "total_weeks": 8,
        "unit_title": "Week 1 kid-facing unit",
    }


@pytest.mark.asyncio
async def test_badge_follows_advance_week(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    assert (await _advance(client, teacher, class_id)).status == 200

    body = await (await _badge(client, parent_token, student_id)).json()
    assert body["state"] == "active"
    assert body["week_index"] == 2
    assert body["unit_title"] == "Week 2 kid-facing unit"


@pytest.mark.asyncio
async def test_badge_completed_after_eight_weeks(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    for _ in range(8):  # week 8 active -> the 8th advance completes the course
        assert (await _advance(client, teacher, class_id)).status == 200

    body = await (await _badge(client, parent_token, student_id)).json()
    assert body["state"] == "completed"
    assert body["week_index"] == 8  # badge reads "8/8 · 完成"
    assert body["total_weeks"] == 8
    assert body["unit_title"] == "Week 8 kid-facing unit"


@pytest.mark.asyncio
async def test_badge_payload_carries_no_internal_ids(client, teacher_invite):
    """Ruling #1: no topic_id, no student id, no raw internal metadata."""
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    resp = await _badge(client, parent_token, student_id[:8])
    raw = await resp.text()
    assert resp.status == 200
    assert "curriculum-wk" not in raw          # internal topic_id
    assert student_id not in raw               # full student id
    assert os.environ["DREAMER_DB_PATH"] not in raw
    assert (await resp.json())["unit_title"] != "curriculum-wk01"


# ---------------------------------------------------------------------------
# Negative set — the CI red lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_badge_anonymous_is_401(client):
    resp = await client.get(f"{UNIT_URL}?student={uuid.uuid4().hex[:8]}", headers=HEADERS)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_badge_requires_student_param(client, teacher_invite):
    _, parent_token, _ = await _parent_child(client, "parent-a@test.local")

    resp = await client.get(UNIT_URL, headers=_auth(parent_token))
    assert resp.status == 400


@pytest.mark.asyncio
async def test_badge_teacher_and_admin_are_denied(client, teacher_invite, tmp_path):
    """The kid badge is not a staff lens — teacher/admin get a unified 403."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    class_id = (await _create_class(client, teacher))["id"]
    await _mount(client, teacher, class_id)
    _, parent_token, student_id = await _parent_child(
        client, "parent-a@test.local", class_id=class_id
    )

    teacher_resp = await _badge(client, teacher, student_id[:8])
    assert teacher_resp.status == 403

    _, admin_token = await _setup_parent(client, "admin@test.local", role="admin")
    admin_resp = await _badge(client, admin_token, student_id[:8])
    assert admin_resp.status == 403
    assert await admin_resp.json() == await teacher_resp.json()  # no oracle

    # the legitimate parent still works — the denial is role-scoped, not global
    assert (await _badge(client, parent_token, student_id[:8])).status == 200

    events = [e["event"] for e in _audit_events(tmp_path)]
    assert events.count("curriculum_student_role_denied") == 2


@pytest.mark.asyncio
async def test_badge_cross_child_is_403(client, teacher_invite, tmp_path):
    """Ruling #2: a parent never reads another parent's child (same class)."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    class_id = (await _create_class(client, teacher))["id"]
    await _mount(client, teacher, class_id)

    _, token_a, child_a = await _parent_child(
        client, "parent-a@test.local", class_id=class_id
    )
    _, _, child_b = await _parent_child(
        client, "parent-b@test.local", class_id=class_id
    )

    # 8-char mask and full id are both refused, with the same body
    mask_resp = await _badge(client, token_a, child_b[:8])
    full_resp = await _badge(client, token_a, child_b)
    assert mask_resp.status == 403
    assert full_resp.status == 403
    assert await mask_resp.json() == await full_resp.json()

    # cross-CLASS as well (another teacher's class, child not confirmed in A's)
    _, token_c, child_c = await _parent_child(client, "parent-c@test.local")
    assert (await _badge(client, token_c, child_c[:8])).status == 200  # own, no class
    assert (await _badge(client, token_a, child_c[:8])).status == 403

    assert (await _badge(client, token_a, child_a[:8])).status == 200

    events = [e["event"] for e in _audit_events(tmp_path)]
    assert events.count("curriculum_student_cross_access") == 3


@pytest.mark.asyncio
async def test_badge_neutral_when_student_has_no_class(client, teacher_invite):
    """Ruling #2: no class -> 200 neutral (badge hidden), never 500."""
    _, parent_token, student_id = await _parent_child(client, "parent-a@test.local")

    resp = await _badge(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    assert await resp.json() == {
        "state": "none",
        "week_index": None,
        "total_weeks": 8,
        "unit_title": "",
    }


@pytest.mark.asyncio
async def test_badge_neutral_when_class_has_no_curriculum(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id = (await _create_class(client, teacher))["id"]  # unmounted
    _, parent_token, student_id = await _parent_child(
        client, "parent-a@test.local", class_id=class_id
    )

    resp = await _badge(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["state"] == "none"
    assert body["week_index"] is None


@pytest.mark.asyncio
async def test_badge_pending_membership_is_neutral(client, teacher_invite):
    """A pending invite is not a class: the kid badge stays neutral."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    class_id = (await _create_class(client, teacher))["id"]
    await _mount(client, teacher, class_id)
    _, parent_token, student_id = await _parent_child(
        client, "parent-a@test.local", class_id=class_id, status="pending"
    )

    body = await (await _badge(client, parent_token, student_id[:8])).json()
    assert body["state"] == "none"
    assert body["week_index"] is None


@pytest.mark.asyncio
async def test_badge_neutral_on_non_linear_rows(client, teacher_invite):
    """A gap degrades to neutral instead of a wrong number.

    Two simultaneously ``active`` weeks are impossible (Bridge-2 partial unique
    index), so the achievable illegal states are the gap shapes below.
    """
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    # gap, nothing open: week 1 completed while 2..8 stay locked
    _force_week(class_id, 1, "completed")
    body = await (await _badge(client, parent_token, student_id[:8])).json()
    assert body["state"] == "none"
    assert body["week_index"] is None

    # gap before the open week: 1 completed, 8 active, 2..7 still locked
    _force_week(class_id, 8, "locked")
    _force_week(class_id, 8, "active")
    body = await (await _badge(client, parent_token, student_id[:8])).json()
    assert body["state"] == "none"
    assert body["week_index"] is None

    # and the healthy shape recovers the badge
    _force_week(class_id, 8, "locked")
    _force_week(class_id, 2, "active")
    body = await (await _badge(client, parent_token, student_id[:8])).json()
    assert body["state"] == "active"
    assert body["week_index"] == 2


@pytest.mark.asyncio
async def test_badge_partial_mount_is_neutral(client, teacher_invite):
    """Half-written curriculum rows (not 1..8) hide the badge, no 500."""
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    conn = _conn()
    try:
        conn.execute(
            "DELETE FROM class_curriculum WHERE class_id = ? AND week_no > 5",
            (class_id,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = await _badge(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["state"] == "none"


@pytest.mark.asyncio
async def test_badge_survives_missing_topic_metadata(client, teacher_invite):
    """Title lookup failures degrade to "" — the week counter still shows."""
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    conn = _conn()
    try:
        conn.execute("DELETE FROM topic_metadata")
        conn.commit()
    finally:
        conn.close()

    resp = await _badge(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["state"] == "active"
    assert body["week_index"] == 1
    assert body["unit_title"] == ""


@pytest.mark.asyncio
async def test_badge_picks_the_class_with_a_mounted_course(client, teacher_invite):
    """Several confirmed classes: the mounted one wins over the bare one."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    bare_class = (await _create_class(client, teacher, name="Bare"))["id"]
    mounted_class = (await _create_class(client, teacher, name="Mounted"))["id"]
    await _mount(client, teacher, mounted_class)

    user_id, parent_token = await _setup_parent(client, "parent-a@test.local")
    student_id = _seed_student(parent_id=user_id, class_id=bare_class)
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO class_students (class_id, student_id, status, created_at) "
            "VALUES (?, ?, 'confirmed', ?)",
            (mounted_class, student_id, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    body = await (await _badge(client, parent_token, student_id[:8])).json()
    assert body["state"] == "active"
    assert body["week_index"] == 1
    assert body["unit_title"] == "Week 1 kid-facing unit"
