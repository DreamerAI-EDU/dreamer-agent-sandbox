"""Bridge-3b — parent-facing 8-week course map (boss work order 2026-09-12).

Spec under test (GET /api/parent/curriculum):
  * payload ``{course_title, current_week, total_weeks: 8, state,
    weeks[{week_no, title, status, mastery_pct}]}``;
  * ``title`` authored server-side (#1 tradition) — the internal ``topic_id``
    never crosses the wire and the parent grid never translates;
  * mastery rule: a week with no data reports ``null``, NEVER 0% (neutral, no
    invented progress); a stored 0.0 is real data and stays 0.0;
  * guard: parent role + own child only -> cross-family 403 + WARNING audit
    (no payload leak); no class / no mounted course -> 200 ``state=none``;
    anonymous -> 401; teacher/admin -> 403 (staff lens is not the parent lens);
  * completion: all 8 weeks done -> ``state=completed``, week 8 ``completed``.

The negative set below is CI-red-line material (registered in the ci.yml
pytest manifest, red line #9).

NOTE (flagged to the boss, 2026-09-12): mastery is read from
``progress_snapshots`` — the per-topic rolling aggregate — only. Deriving a
fallback from ``assessment_logs`` would need the label -> pct mapping that
lives in ``agents.kid_safe.label_soften``, and ``auth/`` deliberately imports
nothing from ``agents/`` (layering). The boss's "progress_snapshots /
assessment_logs" wording is therefore honoured through the canonical snapshot
side; say the word and the log-side aggregation becomes a follow-up ruling.
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
MAP_URL = "/api/parent/curriculum"
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
                    f"Week {week} kid-facing unit",  # authored family-facing text
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


def _seed_student(*, parent_id, class_id=None, status="confirmed",
                  first_name="Mia") -> str:
    """Student row (+ optional class_students membership) for the parent lens."""
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


async def _map(client, token, identifier, param="student_id"):
    return await client.get(
        f"{MAP_URL}?{param}={identifier}", headers=_auth(token)
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
# Positive path — the 8-week grid, backend-stated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_map_shows_the_eight_week_grid(client, teacher_invite):
    """Week 1 active, 2..8 locked, authored titles, no invented mastery."""
    teacher = await _setup_teacher(client)
    _, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    resp = await _map(client, parent_token, student_id[:8])
    assert resp.status == 200, await resp.text()
    body = await resp.json()

    assert body["state"] == "active"
    assert body["current_week"] == 1
    assert body["total_weeks"] == 8
    assert body["course_title"] == "AI Literacy"
    assert [w["week_no"] for w in body["weeks"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [w["status"] for w in body["weeks"]] == (
        ["active"] + ["locked"] * 7
    )
    assert [w["title"] for w in body["weeks"]][:2] == [
        "Week 1 kid-facing unit",
        "Week 2 kid-facing unit",
    ]
    # No snapshot anywhere -> every week is null, never 0.
    assert [w["mastery_pct"] for w in body["weeks"]] == [None] * 8


@pytest.mark.asyncio
async def test_map_mastery_null_vs_stored_zero(client, teacher_invite):
    """A week with data reports the raw 0..1 value; a stored 0.0 is real data."""
    teacher = await _setup_teacher(client)
    _, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    _seed_assessment_schema()
    _seed_snapshot(student_id, "curriculum-wk01", 0.75)
    _seed_snapshot(student_id, "curriculum-wk02", 0.0)

    body = await (await _map(client, parent_token, student_id)).json()
    mastery = {w["week_no"]: w["mastery_pct"] for w in body["weeks"]}
    assert mastery[1] == 0.75          # raw rolling value (frontend does ×100)
    assert mastery[2] == 0.0           # real zero, reported as zero
    assert mastery[3] is None          # no data -> null, NEVER 0


@pytest.mark.asyncio
async def test_map_follows_advance_week(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    assert (await _advance(client, teacher, class_id)).status == 200

    body = await (await _map(client, parent_token, student_id)).json()
    assert body["state"] == "active"
    assert body["current_week"] == 2
    assert [w["status"] for w in body["weeks"]][:3] == [
        "completed",
        "active",
        "locked",
    ]


@pytest.mark.asyncio
async def test_map_completed_after_eight_weeks(client, teacher_invite):
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    for _ in range(8):  # week 8 active -> the 8th advance completes the course
        assert (await _advance(client, teacher, class_id)).status == 200

    body = await (await _map(client, parent_token, student_id)).json()
    assert body["state"] == "completed"
    assert body["current_week"] == 8
    assert [w["status"] for w in body["weeks"]] == ["completed"] * 8


@pytest.mark.asyncio
async def test_map_accepts_the_student_alias(client, teacher_invite):
    """The console may reuse either the parent convention or the kid helper."""
    teacher = await _setup_teacher(client)
    _, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    by_id = await _map(client, parent_token, student_id, param="student_id")
    by_alias = await _map(client, parent_token, student_id, param="student")
    assert by_id.status == by_alias.status == 200
    assert await by_id.json() == await by_alias.json()


@pytest.mark.asyncio
async def test_map_payload_carries_no_internal_ids(client, teacher_invite):
    """No topic_id, no student id, no raw metadata on the wire."""
    teacher = await _setup_teacher(client)
    _, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    resp = await _map(client, parent_token, student_id[:8])
    raw = await resp.text()
    assert resp.status == 200
    assert "curriculum-wk" not in raw          # internal topic_id
    assert student_id not in raw               # full student id
    assert os.environ["DREAMER_DB_PATH"] not in raw
    assert "topic_id" not in raw


# ---------------------------------------------------------------------------
# Negative set — the CI red lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_map_anonymous_is_401(client):
    resp = await client.get(
        f"{MAP_URL}?student_id={uuid.uuid4().hex[:8]}", headers=HEADERS
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_map_requires_a_student_param(client, teacher_invite):
    _, parent_token, _ = await _parent_child(client, "parent-a@test.local")

    resp = await client.get(MAP_URL, headers=_auth(parent_token))
    assert resp.status == 400


@pytest.mark.asyncio
async def test_map_teacher_and_admin_are_denied(client, teacher_invite, tmp_path):
    """The parent map is not a staff lens — teacher/admin get a unified 403."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    class_id = (await _create_class(client, teacher))["id"]
    await _mount(client, teacher, class_id)
    _, parent_token, student_id = await _parent_child(
        client, "parent-a@test.local", class_id=class_id
    )

    teacher_resp = await _map(client, teacher, student_id[:8])
    assert teacher_resp.status == 403

    _, admin_token = await _setup_parent(client, "admin@test.local", role="admin")
    admin_resp = await _map(client, admin_token, student_id[:8])
    assert admin_resp.status == 403
    assert await admin_resp.json() == await teacher_resp.json()  # no oracle

    # the legitimate parent still works — the denial is role-scoped, not global
    assert (await _map(client, parent_token, student_id[:8])).status == 200

    events = [e["event"] for e in _audit_events(tmp_path)]
    assert events.count("curriculum_parent_role_denied") == 2


@pytest.mark.asyncio
async def test_map_cross_family_is_403_and_warns(client, teacher_invite, tmp_path):
    """One family never reads another family's map (same class, mask or full)."""
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

    mask_resp = await _map(client, token_a, child_b[:8])
    full_resp = await _map(client, token_a, child_b)
    assert mask_resp.status == full_resp.status == 403
    assert await mask_resp.json() == await full_resp.json()  # no oracle
    leaked = await mask_resp.text()
    assert "AI Literacy" not in leaked and "Week 1" not in leaked

    # own child still fine
    assert (await _map(client, token_a, child_a[:8])).status == 200

    warnings = [
        e
        for e in _audit_events(tmp_path)
        if e["event"] == "curriculum_parent_cross_access"
    ]
    assert len(warnings) == 2
    assert all(e["level"] == "WARNING" for e in warnings)
    # The attempt itself is the evidence (same convention as the kid badge):
    # mask + full id as tried, and no course payload smuggled into the trail.
    assert [e["target_id"] for e in warnings] == [child_b[:8], child_b]
    assert all("AI Literacy" not in json.dumps(e) for e in warnings)
    assert all("Week 1" not in json.dumps(e) for e in warnings)


@pytest.mark.asyncio
async def test_map_neutral_when_child_has_no_class(client, teacher_invite):
    """No class at all -> 200 state=none, empty grid, never a 500."""
    _, parent_token, student_id = await _parent_child(client, "parent-a@test.local")

    resp = await _map(client, parent_token, student_id)
    assert resp.status == 200
    body = await resp.json()
    assert body == {
        "course_title": "",
        "current_week": None,
        "total_weeks": 8,
        "state": "none",
        "weeks": [],
    }


@pytest.mark.asyncio
async def test_map_neutral_when_class_has_no_mounted_course(client, teacher_invite):
    """Class exists but nothing is mounted yet -> same neutral shape."""
    teacher = await _setup_teacher(client)
    _seed_curriculum()
    class_id = (await _create_class(client, teacher))["id"]  # no mount
    _, parent_token, student_id = await _parent_child(
        client, "parent-a@test.local", class_id=class_id
    )

    body = await (await _map(client, parent_token, student_id)).json()
    assert body["state"] == "none"
    assert body["weeks"] == []
    assert body["current_week"] is None


@pytest.mark.asyncio
async def test_map_neutral_when_membership_is_still_pending(client, teacher_invite):
    """A pending invite is not a membership: the grid stays empty."""
    teacher = await _setup_teacher(client)
    class_id, _, _ = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    _, token_b, pending_child = await _parent_child(
        client, "parent-b@test.local", class_id=class_id, status="pending"
    )

    body = await (await _map(client, token_b, pending_child)).json()
    assert body["state"] == "none"
    assert body["weeks"] == []


@pytest.mark.asyncio
async def test_map_survives_missing_topic_metadata(client, teacher_invite):
    """Bridge-1 data absent -> titles degrade to "", statuses/frames intact."""
    teacher = await _setup_teacher(client)
    _, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )

    conn = _conn()
    try:
        conn.execute("DELETE FROM topic_metadata")
        conn.commit()
    finally:
        conn.close()

    resp = await _map(client, parent_token, student_id)
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["state"] == "active"
    assert body["course_title"] == ""
    assert [w["title"] for w in body["weeks"]] == [""] * 8
    assert [w["status"] for w in body["weeks"]][0] == "active"


@pytest.mark.asyncio
async def test_map_degrades_on_non_linear_rows(client, teacher_invite):
    """A half-migrated / gap state hides the grid instead of lying about it."""
    teacher = await _setup_teacher(client)
    class_id, parent_token, student_id = await _mounted_child_class(
        client, teacher, parent_email="parent-a@test.local"
    )
    conn = _conn()
    try:
        conn.execute(
            "UPDATE class_curriculum SET status = 'locked' "
            "WHERE class_id = ? AND week_no = 1",
            (class_id,),
        )
        conn.commit()
    finally:
        conn.close()

    body = await (await _map(client, parent_token, student_id)).json()
    assert body["state"] == "none"
    assert body["weeks"] == []
