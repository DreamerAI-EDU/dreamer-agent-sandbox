"""W3-B API tests — Parent Report + Teacher progress lens (shared data layer).

Covers the step-1 backend checklist per W3-B brief §5/R5:
  * role gates (parent/teacher) + unified 403 discipline
  * masked vs full student ids (parent mask, teacher console full id)
  * ambiguous mask -> 400; invalid period -> 400
  * zero-activity student still returns 200 canonical report
  * P-series red line: internal_label / confidence / rubric_id never leave
    the server on ANY surface (parent or teacher)
  * consent indicator three states: agreed / unsigned / withdrawn
  * teacher class rollup shape + average; cross-teacher -> unified 403
  * R5.8 same-source parity: teacher detail report == parent report body
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

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

# Fixed identities across the seeded world
P1 = "user-p1"          # parent of students A and B
P2 = "user-p2"          # parent of students D and E
T1 = "user-t1"          # owns class-0001 (students A, B confirmed)
T2 = "user-t2"          # owns class-0002 (student D confirmed)
SID_A = "aaaa1111aaaa2222"   # parent P1; agreed media consent; real activity
SID_B = "aaaa1111bbbb2222"   # parent P1; NO consent rows; no activity
SID_D = "dddd1111dddd2222"   # parent P2; withdrawn media consent
SID_E = "eeee1111eeee2222"   # parent P2; brand-new, zero activity

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
    sid = "ses-w3b-" + uuid.uuid4().hex[:8]
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
    """Fresh DB seeded with users/students/classes + real agent activity."""
    # security-warning audit channel must never write the repo's tracked log
    monkeypatch.setattr("auth.consent.AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    db_path = auth_db._db_path()
    auth_db.ensure_schema()
    auth_db.apply_class_meta_migration()
    for uid, role in ((P1, "parent"), (P2, "parent"), (T1, "teacher"), (T2, "teacher")):
        auth_db.create_user(
            user_id=uid,
            email=f"{uid}@test.local",
            password_hash="test-pass-w3b-001",
            role=role,
            email_verified=True,
        )

    conn = sqlite3.connect(db_path)
    conn.executescript(AGENT_DDL)
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
    # class membership (confirmed)
    for cid, sid in (("class-0001", SID_A), ("class-0001", SID_B),
                     ("class-0002", SID_D)):
        cur.execute(
            "INSERT INTO class_students (class_id,student_id,status,created_at) "
            "VALUES (?,?,'confirmed',?)",
            (cid, sid, _ago_iso(days=60)),
        )
    # consent rows (student-bound, no account NULL rows in the seed)
    cur.execute(
        "INSERT INTO consent_log (user_id,doc_type,doc_version,action,student_id,"
        "created_at) VALUES (?, 'media_consent','2026-01','agreed',?,?)",
        (P1, SID_A, _ago_iso(days=30)),
    )
    cur.execute(
        "INSERT INTO consent_log (user_id,doc_type,doc_version,action,student_id,"
        "created_at) VALUES (?, 'media_consent','2026-01','withdrawn',?,?)",
        (P2, SID_D, _ago_iso(days=20)),
    )
    # activity for student A: 3 assessments + 6 sessions + snapshot
    for i, (label, days) in enumerate(
        [("not_yet", 20), ("developing", 12), ("achieved", 2)]
    ):
        cur.execute(
            "INSERT INTO assessment_logs (student_id,session_id,topic_id,mode,"
            "lang_code,internal_label,confidence,rubric_id,evidence_text,agent_used,"
            "cost_tokens,created_at) VALUES (?,?,'maths-multiplication-01','DIRECT',"
            "'zh-hk',?,0.9,'rub','','auto',0,?)",
            (SID_A, f"ses-{i}", label, _ago_iso(days=days)),
        )
    for d in range(6):
        cur.execute(
            "INSERT INTO session_logs (session_id,student_id,mode,lang_code,"
            "age_band,agent_list,topic_ids,cost_summary,duration_seconds,created_at) "
            "VALUES (?,?,'guide','zh-hk','P4-P6','[]','[\"maths-multiplication-01\"]',"
            "'{}',900,?)",
            (f"ses-s{d}", SID_A, _ago_iso(days=d * 3)),
        )
    cur.execute(
        "INSERT INTO progress_snapshots (student_id,topic_id,mastery_pct,"
        "attempt_count,last_label,streak,updated_at) VALUES "
        "(?,'maths-multiplication-01',66.7,3,'achieved',2,?)",
        (SID_A, _ago_iso(days=2)),
    )
    conn.commit()
    conn.close()
    return {"db_path": db_path}


# ---------------------------------------------------------------------------
# Parent report endpoint — success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_report_full_envelope_for_own_student(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A, "period": "cycle"},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200
    body = await resp.json()
    # canonical envelope shape (probe-verified against ParentReportAgent)
    for key in ("content", "mode", "lang_code", "age_band", "kid_label",
                "citations", "cost_summary", "report"):
        assert key in body, f"missing envelope key {key}"
    report = body["report"]
    assert report["student_id"] == SID_A[:8], "parent side must mask id"
    assert report["variant"] == "standard"
    assert report["summary"]["session_count"] >= 1
    topics = report["topics"]
    assert topics, "expected topics with seeded activity"
    assert topics[0]["mastery_pct"] == 66.7
    assert topics[0]["attempt_count"] == 3
    assert topics[0]["streak"] == 2
    assert topics[0]["last_label_parent"]  # softened parent label non-empty


@pytest.mark.asyncio
async def test_parent_report_masked_id_identifier(world, client):
    # SID_D's 8-char prefix is unique inside P2's reachable set
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_D[:8]},
        headers=_cookie_header(P2),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["report"]["student_id"] == SID_D[:8]


@pytest.mark.asyncio
async def test_parent_report_full_id_never_leaks_on_parent_surface(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_D[:8]},
        headers=_cookie_header(P2),
    )
    blob = json.dumps(await resp.json(), ensure_ascii=False)
    assert SID_D not in blob, "full student id leaked to parent surface"


@pytest.mark.asyncio
async def test_parent_report_period_variants_all_supported(world, client):
    for period in ("cycle", "weekly", "journey"):
        resp = await client.get(
            "/api/parent/report",
            params={"student_id": SID_A, "period": period},
            headers=_cookie_header(P1),
        )
        assert resp.status == 200, period
        body = await resp.json()
        assert body["report"]["period"]["type"] == period


# ---------------------------------------------------------------------------
# Parent report endpoint — authz / rejection paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_report_foreign_student_forbidden(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_D},
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_parent_report_unknown_student_forbidden(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": "zzzz9999zzzz9999"},
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_parent_report_ambiguous_mask_bad_request(world, client):
    # SID_A and SID_B share the same 8-char prefix for parent P1
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A[:8]},
        headers=_cookie_header(P1),
    )
    assert resp.status == 400, "ambiguous mask must be rejected (never pick one)"
    assert "ambiguous" not in json.dumps(await resp.json())


@pytest.mark.asyncio
async def test_parent_report_requires_role_parent(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A},
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_parent_report_requires_session(world, client):
    resp = await client.get(
        "/api/parent/report", params={"student_id": SID_A}
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_parent_report_invalid_period_bad_request(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A, "period": "daily"},
        headers=_cookie_header(P1),
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_parent_report_zero_activity_student_still_200(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_E},
        headers=_cookie_header(P2),
    )
    assert resp.status == 200
    body = await resp.json()
    summary = body["report"]["summary"]
    assert summary["session_count"] == 0
    assert body["report"]["student_id"] == SID_E[:8]


# ---------------------------------------------------------------------------
# P-series red line — no internal fields on any W3-B surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_report_never_leaks_internal_fields(world, client):
    resp = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A, "period": "journey"},
        headers=_cookie_header(P1),
    )
    blob = json.dumps(await resp.json(), ensure_ascii=False)
    for leaked in ("internal_label", "last_label_internal", "confidence",
                   "rubric_id"):
        assert f'"{leaked}"' not in blob, f"parent surface leaked {leaked}"


@pytest.mark.asyncio
async def test_teacher_class_progress_never_leaks_internal_fields(world, client):
    resp = await client.get(
        "/api/teacher/classes/class-0001/progress",
        headers=_cookie_header(T1),
    )
    blob = json.dumps(await resp.json(), ensure_ascii=False)
    for leaked in ("internal_label", "last_label_internal", "confidence",
                   "rubric_id", "evidence_text"):
        assert f'"{leaked}"' not in blob, f"teacher class surface leaked {leaked}"


@pytest.mark.asyncio
async def test_teacher_student_progress_never_leaks_internal_fields(world, client):
    resp = await client.get(
        "/api/teacher/student/" + SID_A + "/progress",
        headers=_cookie_header(T1),
    )
    blob = json.dumps(await resp.json(), ensure_ascii=False)
    for leaked in ("internal_label", "last_label_internal", "confidence",
                   "rubric_id"):
        assert f'"{leaked}"' not in blob, f"teacher drill surface leaked {leaked}"


# ---------------------------------------------------------------------------
# Teacher lens — class rollups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_class_progress_rollup_owned_class(world, client):
    resp = await client.get(
        "/api/teacher/classes/class-0001/progress",
        headers=_cookie_header(T1),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["class"]["id"] == "class-0001"
    assert body["class"]["name"] == "週六 P4 班"
    assert body["stats"]["student_count"] == 2
    assert body["stats"]["average_mastery_pct"] == 66.7
    rows = {r["student_id"]: r for r in body["students"]}
    assert set(rows) == {SID_A, SID_B}
    # full ids on the trusted teacher console
    assert SID_A in rows and SID_B in rows
    # B24: display_name comes from first_name only
    assert rows[SID_A]["display_name"] == "阿明"
    assert rows[SID_B]["display_name"] == "小晴"
    # consent indicator three states on class rows
    assert rows[SID_A]["media_consent"] == "agreed"
    assert rows[SID_B]["media_consent"] == "unsigned"
    # student A row carries real activity; B is empty
    assert rows[SID_A]["mastery_pct"] == 66.7
    assert rows[SID_A]["last_label_kid"]
    assert rows[SID_B]["mastery_pct"] is None
    assert rows[SID_B]["last_label_kid"] == ""
    assert rows[SID_B]["last_activity_at"] is None


@pytest.mark.asyncio
async def test_teacher_class_progress_withdrawn_consent_row(world, client):
    resp = await client.get(
        "/api/teacher/classes/class-0002/progress",
        headers=_cookie_header(T2),
    )
    assert resp.status == 200
    body = await resp.json()
    rows = {r["student_id"]: r for r in body["students"]}
    assert rows[SID_D]["media_consent"] == "withdrawn"
    assert body["stats"]["student_count"] == 1
    assert body["stats"]["average_mastery_pct"] is None  # no snapshots at all


@pytest.mark.asyncio
async def test_teacher_class_progress_cross_teacher_forbidden(world, client):
    # T1 attempting T2's class -> unified 403 (WARNING logged in handler)
    resp = await client.get(
        "/api/teacher/classes/class-0002/progress",
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_class_progress_unknown_class_forbidden(world, client):
    resp = await client.get(
        "/api/teacher/classes/class-nope/progress",
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_class_progress_parent_role_forbidden(world, client):
    resp = await client.get(
        "/api/teacher/classes/class-0001/progress",
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_class_progress_requires_session(world, client):
    resp = await client.get("/api/teacher/classes/class-0001/progress")
    assert resp.status == 401


# ---------------------------------------------------------------------------
# Teacher lens — student drill-down
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_student_progress_taught_student(world, client):
    resp = await client.get(
        "/api/teacher/student/" + SID_A + "/progress",
        params={"period": "cycle"},
        headers=_cookie_header(T1),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["student"]["student_id"] == SID_A  # full id on trusted console
    assert body["student"]["display_name"] == "阿明"  # B24 first_name only
    assert body["student"]["media_consent"] == "agreed"
    report = body["report"]["report"]  # envelope -> canonical parent report
    assert report["student_id"] == SID_A  # teacher surface keeps full id
    assert report["summary"]["session_count"] >= 1
    hist = body["assessment_history"]
    assert len(hist) == 3  # 3 seeded assessments, newest first
    assert hist[0]["date"] == _ago_iso(days=2)[:10]
    assert hist[0]["label_parent"]  # softened parent-facing label
    for row in hist:
        assert set(row) == {"date", "topic_id", "subject", "mode", "label_parent"}
        assert row["subject"] == "maths"
        assert row["mode"] == "DIRECT"


@pytest.mark.asyncio
async def test_teacher_student_progress_untaught_forbidden(world, client):
    # T1 does not teach SID_D (owned by T2's class)
    resp = await client.get(
        "/api/teacher/student/" + SID_D + "/progress",
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_student_progress_unknown_forbidden(world, client):
    resp = await client.get(
        "/api/teacher/student/zzzz9999zzzz9999/progress",
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_student_progress_parent_role_forbidden(world, client):
    resp = await client.get(
        "/api/teacher/student/" + SID_A + "/progress",
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_student_progress_invalid_period_bad_request(world, client):
    resp = await client.get(
        "/api/teacher/student/" + SID_A + "/progress",
        params={"period": "yearly"},
        headers=_cookie_header(T1),
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_teacher_student_progress_withdrawn_consent(world, client):
    resp = await client.get(
        "/api/teacher/student/" + SID_D + "/progress",
        headers=_cookie_header(T2),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["student"]["media_consent"] == "withdrawn"


# ---------------------------------------------------------------------------
# R5.8 same-source parity — teacher drill report == parent report body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_and_parent_report_same_source_parity(world, client):
    """Both lenses must render byte-identical canonical content for the same
    student/period, differing only in the embedded student_id (full vs mask).
    """
    teacher = await client.get(
        "/api/teacher/student/" + SID_A + "/progress",
        params={"period": "journey"},
        headers=_cookie_header(T1),
    )
    parent = await client.get(
        "/api/parent/report",
        params={"student_id": SID_A, "period": "journey"},
        headers=_cookie_header(P1),
    )
    tbody = (await teacher.json())["report"]
    pbody = await parent.json()

    def _normalise(payload: dict) -> dict:
        payload = json.loads(json.dumps(payload))
        inner = payload.get("report") or {}
        if isinstance(inner.get("student_id"), str):
            inner["student_id"] = inner["student_id"][:8]
        return payload

    assert _normalise(tbody) == _normalise(pbody), "W3-B surfaces drifted from shared data layer"
