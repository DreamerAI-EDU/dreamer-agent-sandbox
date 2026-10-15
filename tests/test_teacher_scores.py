"""PR-2 T-7 — teacher weekly scoring input (PUT /api/teacher/scores).

Covers the step-1 backend checklist per design book v1.1 §4.4 / §8.3:
  * normal write: assessment_logs row with scored_by='teacher', age_band
    server-derived from the students table (never trusted from the client)
  * idempotent overwrite: re-scoring the same (student_id, week_no,
    skill_code) updates the existing row AND archives the old value into the
    append-only teacher_score_audit FIRST (old score + old evidence + masked
    student id + replaced_by)
  * revoke: score_0_3=null clears the live score (old value still archived)
  * boundary gate at the API layer: out-of-range score (-1 / 4), invalid
    week_no / skill_code / over-long evidence all 422 AND write nothing —
    the DB CHECK is the last line, not the first
  * cross-class / unowned-class scoring -> unified 403 + zero writes
  * same week, two different skill codes -> two coexisting rows
  * parent token -> 403 + zero writes
  * audit append-only: UPDATE / DELETE on teacher_score_audit blocked by DB
    triggers (same discipline as ws_chat_relay_audit)
  * constants: EVIDENCE_MAX_CHARS alignment with parent_report_agent
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

from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402
from auth.scores import EVIDENCE_MAX_CHARS  # noqa: E402
from agents.parent_report_agent import EVIDENCE_MAX_CHARS as PARENT_EVIDENCE_MAX_CHARS  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

# Fixed identities across the seeded world (same reachable set as W3-B)
P1 = "user-p1"          # parent of students A and B
P2 = "user-p2"          # parent of students D and E
T1 = "user-t1"          # owns class-0001 (students A, B confirmed)
T2 = "user-t2"          # owns class-0002 (student D confirmed)
SID_A = "aaaa1111aaaa2222"   # confirmed member of class-0001, band P4-P6
SID_B = "aaaa1111bbbb2222"   # confirmed member of class-0001, band P4-P6
SID_D = "dddd1111dddd2222"   # confirmed member of class-0002, band P4-P6
SID_E = "eeee1111eeee2222"   # parent P2; NOT in any confirmed class

AGENT_DDL = """
CREATE TABLE IF NOT EXISTS assessment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en', internal_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0, rubric_id TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '', agent_used TEXT NOT NULL DEFAULT 'assessment',
    cost_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_logs_student ON assessment_logs(student_id, created_at);
CREATE TABLE IF NOT EXISTS progress_snapshots (
    student_id TEXT NOT NULL, topic_id TEXT NOT NULL,
    mastery_pct REAL NOT NULL DEFAULT 0.0, attempt_count INTEGER NOT NULL DEFAULT 1,
    last_label TEXT NOT NULL DEFAULT '', streak INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL, PRIMARY KEY (student_id, topic_id));
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    student_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT '',
    lang_code TEXT NOT NULL DEFAULT '', age_band TEXT NOT NULL DEFAULT '',
    agent_list TEXT NOT NULL DEFAULT '[]', topic_ids TEXT NOT NULL DEFAULT '[]',
    cost_summary TEXT NOT NULL DEFAULT '{}', duration_seconds INTEGER,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS obs_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '', event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')));
"""


def _future_iso(days: int = 7) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")


def _ago_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _cookie_header(user_id: str) -> dict:
    sid = "ses-t7-" + uuid.uuid4().hex[:8]
    auth_db.create_session(session_id=sid, user_id=user_id, expires_at=_future_iso())
    return {"Cookie": f"auth_session={sid}", **HEADERS}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
async def world(client, tmp_path, monkeypatch):
    """Fresh DB seeded with users/students/classes + PR-1 schema columns."""
    # security-warning audit channel must never write the repo's tracked log
    monkeypatch.setattr("auth.consent.AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    db_path = auth_db._db_path()
    auth_db.ensure_schema()
    conn = sqlite3.connect(db_path)
    conn.executescript(AGENT_DDL)
    conn.commit()
    conn.close()
    auth_db.apply_class_meta_migration()
    auth_db.apply_phase8_parent_reports_migration()
    for uid, role in ((P1, "parent"), (P2, "parent"), (T1, "teacher"), (T2, "teacher")):
        auth_db.create_user(
            user_id=uid,
            email=f"{uid}@test.local",
            password_hash="test-pass-t7-001",
            role=role,
            email_verified=True,
        )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # students
    students = [
        (SID_A, P1, "阿明", "P4-P6", "zh-hk"),
        (SID_B, P1, "小晴", "P4-P6", "zh-hk"),
        (SID_D, P2, "家豪", "P4-P6", "zh-hk"),
        (SID_E, P2, "新手兒", "P2-P3", "en"),
    ]
    for sid, parent, fname, band, lang in students:
        cur.execute(
            "INSERT INTO students (id,parent_id,teacher_id,first_name,age_band,"
            "lang_code,pin_hash,pin_lock_until,failed_pin_count,created_at) "
            "VALUES (?,?,NULL,?,?,?,'x',NULL,0,?)",
            (sid, parent, fname, band, lang, _ago_iso(days=90)),
        )
    # classes
    cur.execute(
        "INSERT INTO classes (id,teacher_id,name,join_code,class_type,grade_band,"
        "is_one_on_one,created_at) VALUES ('class-0001',?, '週六 P4 班','ABC123XY',"
        "'monthly','P4-P6',0,?)",
        (T1, _ago_iso(days=80)),
    )
    cur.execute(
        "INSERT INTO classes (id,teacher_id,name,join_code,class_type,grade_band,"
        "is_one_on_one,created_at) VALUES ('class-0002',?, '週二 P4 班','DEF456UV',"
        "'monthly','P4-P6',0,?)",
        (T2, _ago_iso(days=70)),
    )
    # class membership (confirmed) — SID_E has NO confirmed class on purpose
    for cid, sid in (("class-0001", SID_A), ("class-0001", SID_B),
                     ("class-0002", SID_D)):
        cur.execute(
            "INSERT INTO class_students (class_id,student_id,status,created_at) "
            "VALUES (?,?,'confirmed',?)",
            (cid, sid, _ago_iso(days=60)),
        )
    conn.commit()
    conn.close()
    return {"db_path": db_path}


async def _put_score(client, user_id: str, body: dict):
    return await client.put(
        "/api/teacher/scores", json=body, headers=_cookie_header(user_id)
    )


def _live_rows(db_path: str, student_id: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM assessment_logs WHERE student_id = ? AND scored_by = 'teacher'"
            " ORDER BY id",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()


def _audit_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM teacher_score_audit ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T-7.1 normal write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_insert_writes_row_with_server_age_band(world, client):
    resp = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 3,
         "skill_code": "DREAM", "score_0_3": 3,
         "evidence_text": "課堂主動舉手回答"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "inserted"
    assert body["student_id"] == SID_A[:8], "response must carry only the mask"
    assert json.dumps(body) and SID_A not in json.dumps(body)

    rows = _live_rows(world["db_path"], SID_A)
    assert len(rows) == 1
    row = rows[0]
    assert row["scored_by"] == "teacher"
    assert row["week_no"] == 3
    assert row["skill_code"] == "DREAM"
    assert row["score_0_3"] == 3
    assert row["evidence_text"] == "課堂主動舉手回答"
    # age_band is server-derived from students, never trusted from client
    assert row["age_band"] == "P4-P6"
    assert row["internal_label"] == "teacher_score"
    assert _audit_rows(world["db_path"]) == []


# ---------------------------------------------------------------------------
# T-7.2 idempotent overwrite -> old value archived first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_overwrite_archives_old_value_then_updates(world, client):
    first = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 4,
         "skill_code": "DISCOVER", "score_0_3": 2, "evidence_text": "初版評分"},
    )
    assert first.status == 200
    first_body = await first.json()
    assert first_body["status"] == "inserted"

    second = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 4,
         "skill_code": "DISCOVER", "score_0_3": 1, "evidence_text": "覆寫評分"},
    )
    assert second.status == 200
    second_body = await second.json()
    assert second_body["status"] == "updated"
    assert second_body["assessment_log_id"] == first_body["assessment_log_id"], \
        "overwrite must update the SAME row, not insert a second one"

    rows = _live_rows(world["db_path"], SID_A)
    assert len(rows) == 1
    assert rows[0]["score_0_3"] == 1
    assert rows[0]["evidence_text"] == "覆寫評分"

    audits = _audit_rows(world["db_path"])
    assert len(audits) == 1
    a = audits[0]
    assert a["old_score"] == 2, "old value must reach the audit BEFORE overwrite"
    assert a["old_evidence"] == "初版評分"
    assert a["week_no"] == 4
    assert a["skill_code"] == "DISCOVER"
    assert a["assessment_id"] == rows[0]["id"]
    assert a["replaced_by"] == T1
    # red-line 8: audit rows carry only the 8-char mask, never the full id
    assert a["student_mask"] == SID_A[:8]
    assert SID_A not in a["student_mask"]


@pytest.mark.asyncio
async def test_teacher_score_identical_resubmission_is_noop(world, client):
    body = {"student_id": SID_A, "class_id": "class-0001", "week_no": 2,
            "skill_code": "DESIGN", "score_0_3": 2, "evidence_text": "同值重交"}
    r1 = await _put_score(client, T1, body)
    assert r1.status == 200
    r2 = await _put_score(client, T1, body)
    assert r2.status == 200
    assert (await r2.json())["status"] == "unchanged"
    assert len(_live_rows(world["db_path"], SID_A)) == 1
    assert _audit_rows(world["db_path"]) == [], \
        "identical re-submission must not mint an audit row"


# ---------------------------------------------------------------------------
# T-7.3 revoke via score_0_3=null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_revoke_null_clears_score_and_archives(world, client):
    r1 = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 5,
         "skill_code": "DELIVER", "score_0_3": 2, "evidence_text": "先畀分"},
    )
    assert r1.status == 200

    r2 = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 5,
         "skill_code": "DELIVER", "score_0_3": None, "evidence_text": ""},
    )
    assert r2.status == 200
    assert (await r2.json())["status"] == "updated"

    rows = _live_rows(world["db_path"], SID_A)
    assert len(rows) == 1
    assert rows[0]["score_0_3"] is None, "null revoke must clear the live score"
    audits = _audit_rows(world["db_path"])
    assert len(audits) == 1
    assert audits[0]["old_score"] == 2


# ---------------------------------------------------------------------------
# T-7.4 boundary gate at the API layer — 422 AND zero DB writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_out_of_range_422_and_zero_write(world, client):
    for bad in (-1, 4):
        resp = await _put_score(
            client, T1,
            {"student_id": SID_A, "class_id": "class-0001", "week_no": 1,
             "skill_code": "DREAM", "score_0_3": bad},
        )
        assert resp.status == 422, f"score {bad} must be 422, got {resp.status}"
    assert _live_rows(world["db_path"], SID_A) == []
    assert _audit_rows(world["db_path"]) == []


@pytest.mark.asyncio
async def test_teacher_score_invalid_boundaries_422_and_zero_write(world, client):
    valid = {"student_id": SID_A, "class_id": "class-0001", "week_no": 1,
             "skill_code": "DREAM", "score_0_3": 2}
    cases = [
        {**valid, "week_no": 0},
        {**valid, "week_no": 9},
        {**valid, "week_no": 1.5},
        {**valid, "skill_code": "HACK"},
        {**valid, "score_0_3": "2"},                 # non-int
        {**valid, "evidence_text": "字" * 201},      # over EVIDENCE_MAX_CHARS
        {"class_id": "class-0001", "week_no": 1, "skill_code": "DREAM", "score_0_3": 2},  # no student_id
        {"student_id": SID_A, "week_no": 1, "skill_code": "DREAM", "score_0_3": 2},       # no class_id
    ]
    for body in cases:
        resp = await _put_score(client, T1, body)
        assert resp.status == 422, f"{body} must be 422, got {resp.status}"
    assert _live_rows(world["db_path"], SID_A) == []
    assert _audit_rows(world["db_path"]) == []


@pytest.mark.asyncio
async def test_teacher_score_put_requires_csrf_header(world, client):
    # PUT joins the POST-style custom-header CSRF scheme (auth/api.py csrf_guard)
    sid = "ses-t7-csrf-" + uuid.uuid4().hex[:8]
    auth_db.create_session(session_id=sid, user_id=T1, expires_at=_future_iso())
    resp = await client.put(
        "/api/teacher/scores",
        json={"student_id": SID_A, "class_id": "class-0001", "week_no": 1,
              "skill_code": "DREAM", "score_0_3": 2},
        headers={"Cookie": f"auth_session={sid}"},   # no X-Requested-With
    )
    assert resp.status == 403
    assert _live_rows(world["db_path"], SID_A) == []


# ---------------------------------------------------------------------------
# T-7.5 cross-class / unowned class -> unified 403 + zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_cross_class_403_and_zero_write(world, client):
    # T1 tries to score SID_D (T2's class-0002 student) via T1's class-0001
    resp = await _put_score(
        client, T1,
        {"student_id": SID_D, "class_id": "class-0001", "week_no": 1,
         "skill_code": "DREAM", "score_0_3": 2},
    )
    assert resp.status == 403
    # T1 tries to score via a class it does not own (class-0002)
    resp2 = await _put_score(
        client, T1,
        {"student_id": SID_D, "class_id": "class-0002", "week_no": 1,
         "skill_code": "DREAM", "score_0_3": 2},
    )
    assert resp2.status == 403
    # SID_E has no confirmed class at all
    resp3 = await _put_score(
        client, T2,
        {"student_id": SID_E, "class_id": "class-0002", "week_no": 1,
         "skill_code": "DREAM", "score_0_3": 2},
    )
    assert resp3.status == 403
    assert _live_rows(world["db_path"], SID_D) == []
    assert _live_rows(world["db_path"], SID_E) == []
    assert _audit_rows(world["db_path"]) == []


# ---------------------------------------------------------------------------
# T-7.6 same week, two different skill codes coexist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_same_week_two_skills_coexist(world, client):
    r1 = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 6,
         "skill_code": "DREAM", "score_0_3": 2},
    )
    r2 = await _put_score(
        client, T1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 6,
         "skill_code": "DESIGN", "score_0_3": 1},
    )
    assert r1.status == 200 and r2.status == 200
    rows = _live_rows(world["db_path"], SID_A)
    assert len(rows) == 2
    assert {r["skill_code"] for r in rows} == {"DREAM", "DESIGN"}
    assert all(r["week_no"] == 6 for r in rows)
    assert len({r["id"] for r in rows}) == 2, "two distinct rows, not one merged"


# ---------------------------------------------------------------------------
# T-7.7 role gate — parent token -> 403 + zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_parent_token_403_and_zero_write(world, client):
    resp = await _put_score(
        client, P1,
        {"student_id": SID_A, "class_id": "class-0001", "week_no": 1,
         "skill_code": "DREAM", "score_0_3": 2},
    )
    assert resp.status == 403
    assert _live_rows(world["db_path"], SID_A) == []
    assert _audit_rows(world["db_path"]) == []


@pytest.mark.asyncio
async def test_teacher_score_unauthenticated_401(world, client):
    resp = await _put_score(client, "user-ghost",
                            {"student_id": SID_A, "class_id": "class-0001",
                             "week_no": 1, "skill_code": "DREAM", "score_0_3": 2})
    assert resp.status == 401
    assert _live_rows(world["db_path"], SID_A) == []


# ---------------------------------------------------------------------------
# T-7.8 audit append-only + constants alignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_score_audit_append_only(world):
    db_path = world["db_path"]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO teacher_score_audit (student_mask, week_no, skill_code,"
            " old_score, old_evidence, assessment_id, replaced_by, replaced_at)"
            " VALUES ('mask1234', 1, 'DREAM', 2, 'old', 9, 'user-t1', '2026-10-15T00:00:00Z')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE teacher_score_audit SET old_score = 3"
            )
            conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "DELETE FROM teacher_score_audit WHERE id = 1"
            )
            conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM teacher_score_audit").fetchone()[0]
        assert count == 1, "trigger must keep the archive append-only"
    finally:
        conn.close()


def test_teacher_score_evidence_max_chars_alignment():
    assert EVIDENCE_MAX_CHARS == 200
    assert EVIDENCE_MAX_CHARS == PARENT_EVIDENCE_MAX_CHARS, \
        "auth.scores and parent_report_agent must agree on the 200-char cap"
