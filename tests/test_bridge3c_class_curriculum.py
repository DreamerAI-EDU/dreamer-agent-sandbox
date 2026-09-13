"""Bridge-3c — the class-lens course read (boss work order 2026-09-12).

Spec under test (GET /api/classes/{id}/curriculum), the read behind the
teacher console's 進度 card:

  * payload ``{class_id, course_title, state, current_week, total_weeks: 8,
    mastery_scope: "class", weeks[{week_no, topic_id, title, status,
    mastery_pct}]}``;
  * ``state`` / ``current_week`` come from the SAME ``_resolve_week_state``
    resolver as the kid badge (3a) and the parent map (3b) — one source of
    truth for "which week is it", so the three surfaces cannot disagree;
  * ``title`` authored server-side (#1 tradition) — the console renders it
    verbatim and never translates it (``topic_id`` rides along for
    teaching-side identification only, and no student id ever crosses);
  * mastery rule: the week's CLASS AVERAGE over confirmed members; a week
    with no data reports ``null``, NEVER 0%; a stored 0.0 is real data;
  * guard: teacher/admin + own class only -> anonymous 401, non-staff 403,
    another teacher's class 403 + WARNING audit (no payload leak);
  * no mounted course -> neutral 200 ``state=none`` (empty grid), never 500.

The negative set below is CI-red-line material (registered in the ci.yml
pytest manifest, red line #9).

NOTE (flagged to the boss, 2026-09-12): this READ lens admits teacher AND
admin (matching ``handle_curriculum_catalog``), while the bridge-2 write
guards (mount / advance-week) are still teacher-only. The brief says
"teacher/admin only" for all four controls, so the asymmetry is surfaced
rather than silently rewritten — say the word and the write guards get the
same admin allowance.
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
ASSESSMENT_MIGRATION = os.path.join(REPO_ROOT, "migrations", "phase3_assessment.sql")


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
                    f"Week {week} kid-facing unit",  # authored, console-rendered
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


def _seed_assessment_schema() -> None:
    """Real phase-3 assessment schema (progress_snapshots for the mastery lens)."""
    with open(ASSESSMENT_MIGRATION, encoding="utf-8") as fh:
        ddl = fh.read()
    conn = _conn()
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def _seed_snapshot(student_id: str, topic_id: str, mastery_pct: float) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO progress_snapshots (student_id, topic_id, mastery_pct, "
            "attempt_count, last_label, streak, updated_at) "
            "VALUES (?, ?, ?, 1, 'achieved', 1, ?)",
            (student_id, topic_id, mastery_pct, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_student(*, parent_id, class_id, status="confirmed", first_name="Mia") -> str:
    """Student row + class membership (status drives the mastery average)."""
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
        conn.execute(
            "INSERT INTO class_students (class_id, student_id, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            (class_id, student_id, status, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return student_id


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
    for code in ("invite-ok-001", "invite-ok-002", "invite-ok-003"):
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


async def _setup_user(client, email, role, password="test-pass-parent1"):
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


async def _create_class(client, token, name="AI Class"):
    resp = await client.post(
        "/api/classes", json={"name": name}, headers=_auth(token)
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["class"]


async def _mount(client, token, class_id, curriculum_id=CURRICULUM_ID):
    return await client.post(
        f"/api/classes/{class_id}/curriculum",
        json={"curriculum_id": curriculum_id},
        headers=_auth(token),
    )


async def _advance(client, token, class_id):
    return await client.post(
        f"/api/classes/{class_id}/advance-week", headers=_auth(token)
    )


async def _read(client, token, class_id):
    return await client.get(
        f"/api/classes/{class_id}/curriculum", headers=_auth(token)
    )


async def _mounted_class(client, teacher_token):
    """Teacher + one class with the 8-week course mounted."""
    _seed_curriculum()
    cls = await _create_class(client, teacher_token)
    resp = await _mount(client, teacher_token, cls["id"])
    assert resp.status == 201, await resp.text()
    return cls


# ---------------------------------------------------------------------------
# Positive path — the teacher's own view of the 8-week course
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_class_curriculum_neutral_before_mount(client, teacher_invite):
    """Nothing mounted yet -> neutral 200 with an EMPTY grid, never an error."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    cls = await _create_class(client, teacher)

    resp = await _read(client, teacher, cls["id"])
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body == {
        "class_id": cls["id"],
        "course_title": "",
        "state": "none",
        "current_week": None,
        "total_weeks": 8,
        "mastery_scope": "class",
        "weeks": [],
    }


@pytest.mark.asyncio
async def test_class_curriculum_shows_the_eight_week_grid(client, teacher_invite):
    """Week 1 active, 2..8 locked, authored titles, no invented mastery."""
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)

    resp = await _read(client, teacher, cls["id"])
    assert resp.status == 200, await resp.text()
    body = await resp.json()

    assert body["state"] == "active"
    assert body["current_week"] == 1
    assert body["total_weeks"] == 8
    assert body["mastery_scope"] == "class"
    assert body["course_title"] == "AI Literacy"
    assert [w["week_no"] for w in body["weeks"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [w["status"] for w in body["weeks"]] == ["active"] + ["locked"] * 7
    assert [w["title"] for w in body["weeks"]][:2] == [
        "Week 1 kid-facing unit",
        "Week 2 kid-facing unit",
    ]
    # Nobody in the class has data -> every week is null, never 0.
    assert [w["mastery_pct"] for w in body["weeks"]] == [None] * 8


@pytest.mark.asyncio
async def test_class_curriculum_follows_advance_week(client, teacher_invite):
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)

    assert (await _advance(client, teacher, cls["id"])).status == 200

    body = await (await _read(client, teacher, cls["id"])).json()
    assert body["state"] == "active"
    assert body["current_week"] == 2
    assert [w["status"] for w in body["weeks"]][:3] == [
        "completed",
        "active",
        "locked",
    ]


@pytest.mark.asyncio
async def test_class_curriculum_completed_after_eight_weeks(client, teacher_invite):
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)
    for _ in range(8):  # week 8 active -> the 8th advance completes the course
        assert (await _advance(client, teacher, cls["id"])).status == 200

    body = await (await _read(client, teacher, cls["id"])).json()
    assert body["state"] == "completed"
    assert body["current_week"] == 8
    assert [w["status"] for w in body["weeks"]] == ["completed"] * 8


@pytest.mark.asyncio
async def test_class_curriculum_mastery_is_the_class_average(client, teacher_invite):
    """Mean over CONFIRMED members; pending never counts; 0.0 is real data."""
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)
    _, parent_a = await _setup_user(client, "parent-a@test.local", "parent")
    _, parent_b = await _setup_user(client, "parent-b@test.local", "parent")
    mia = _seed_student(parent_id=parent_a, class_id=cls["id"])
    ben = _seed_student(parent_id=parent_b, class_id=cls["id"], first_name="Ben")
    pending = _seed_student(
        parent_id=parent_b, class_id=cls["id"], status="pending", first_name="Cher"
    )
    _seed_assessment_schema()
    _seed_snapshot(mia, "curriculum-wk01", 0.5)
    _seed_snapshot(ben, "curriculum-wk01", 1.0)          # mean -> 0.75
    _seed_snapshot(mia, "curriculum-wk02", 0.0)          # real zero survives
    _seed_snapshot(pending, "curriculum-wk03", 0.0)      # pending must not count

    body = await (await _read(client, teacher, cls["id"])).json()
    mastery = {w["week_no"]: w["mastery_pct"] for w in body["weeks"]}
    assert mastery[1] == 0.75
    assert mastery[2] == 0.0
    assert mastery[3] is None   # only a pending member had data -> null, NOT 0
    assert mastery[4] is None   # no data anywhere -> null, NEVER 0


@pytest.mark.asyncio
async def test_class_curriculum_payload_carries_no_student_ids(client, teacher_invite):
    """The console sees week metadata only — never a student identifier."""
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)
    _, parent_a = await _setup_user(client, "parent-a@test.local", "parent")
    mia = _seed_student(parent_id=parent_a, class_id=cls["id"])

    resp = await _read(client, teacher, cls["id"])
    raw = await resp.text()
    assert resp.status == 200
    assert mia not in raw                      # no student id
    assert parent_a not in raw                 # no parent id
    assert os.environ["DREAMER_DB_PATH"] not in raw
    assert "student" not in raw.lower()


# ---------------------------------------------------------------------------
# Negative set — the CI red lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_class_curriculum_anonymous_is_401(client, teacher_invite):
    teacher = await _setup_teacher(client)
    cls = await _create_class(client, teacher)

    resp = await client.get(
        f"/api/classes/{cls['id']}/curriculum", headers=HEADERS
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_class_curriculum_non_staff_is_403(client, teacher_invite):
    """A parent session (or any non-staff role) never reads the console lens."""
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)
    _, parent_token = await _setup_user(client, "parent-a@test.local", "parent")

    resp = await _read(client, parent_token, cls["id"])
    assert resp.status == 403
    leaked = await resp.text()
    assert "AI Literacy" not in leaked and "Week 1" not in leaked

    # the owner teacher still works — the denial is role-scoped, not global
    assert (await _read(client, teacher, cls["id"])).status == 200


@pytest.mark.asyncio
async def test_class_curriculum_cross_teacher_is_403_and_warns(
    client, teacher_invite, tmp_path
):
    """One teacher never reads another teacher's class, known id or not."""
    owner = await _setup_teacher(client, "owner@test.local", "invite-ok-001")
    other = await _setup_teacher(client, "other@test.local", "invite-ok-002")
    cls = await _mounted_class(client, owner)

    known = await _read(client, other, cls["id"])
    unknown = await _read(client, other, uuid.uuid4().hex)
    assert known.status == unknown.status == 403
    assert await known.json() == await unknown.json()  # no oracle
    leaked = await known.text()
    assert "AI Literacy" not in leaked and "Week 1" not in leaked

    warnings = [
        e
        for e in _audit_events(tmp_path)
        if e["event"] == "curriculum_cross_teacher"
    ]
    assert len(warnings) == 2
    assert all(e["level"] == "WARNING" for e in warnings)
    assert all("AI Literacy" not in json.dumps(e) for e in warnings)


@pytest.mark.asyncio
async def test_class_curriculum_degrades_on_non_linear_rows(client, teacher_invite):
    """A half-migrated / gap state hides the grid instead of lying about it."""
    teacher = await _setup_teacher(client)
    cls = await _mounted_class(client, teacher)
    conn = _conn()
    try:
        conn.execute(
            "UPDATE class_curriculum SET status = 'locked' "
            "WHERE class_id = ? AND week_no = 1",
            (cls["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    body = await (await _read(client, teacher, cls["id"])).json()
    assert body["state"] == "none"
    assert body["weeks"] == []
    assert body["current_week"] is None
