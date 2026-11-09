"""PR-7 S1 — 4D 純度契約（test-only；唔改任何 production 碼）。

三支測試釘死 `auth/report_store.py:333-337` 嘅 `scored_by = 'teacher'` filter：
4D 維度分數（`build_dimension_scores` → `scores` / `dimension_descriptors`）
只認教師打分，AI（`scored_by='auto'`）行永遠唔可以頂替、補位或者偽造成
「Not Yet」。呢個 filter 早於 PR-3 已存在，本檔只係把既有契約寫成可執行斷言，
防止後人以「4D 純度」為名順手改窄／改寬。

B 案（A 案）口徑 — 唔准照令字面擴大適用範圍：
    本令鎖嘅只係 **4D 分數**。`topics` / `recent_evidence` / `baseline` 三欄
    維持 **AI 素材位**（`parent_report_agent._build_topics` /
    `_query_assessment_logs` / `_build_baseline` 一律唔加 `scored_by` filter）。
    呢三欄本來就係 AI 教學紀錄嘅投影，加 filter 會令報告退化——mastery 全 0、
    evidence 空、baseline None——屬回歸，唔係加固。

對照施工令《施工令_PR7_S1-S3精確落點_2026-11-09.md》S1 T1/T2/T3。
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
from auth import report_descriptors as rd  # noqa: E402
from auth import report_store  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

P1 = "user-p1"          # parent of SID_A
T1 = "user-t1"          # owns class-0001
SID_A = "aaaa1111aaaa2222"   # confirmed member of class-0001, band P4-P6 / zh-hk
CLASS_A = "class-0001"
TOPIC = "topic-num-1"

DIMS = ("DREAM", "DISCOVER", "DESIGN", "DELIVER")

# Same harness DDL as tests/test_report_state_machine.py (the agent-side tables
# are not owned by auth/db.py on a fresh DB).
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
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _cookie_header(user_id: str) -> dict:
    sid = "ses-pr7-" + uuid.uuid4().hex[:8]
    auth_db.create_session(session_id=sid, user_id=user_id, expires_at=_future_iso())
    return {"Cookie": f"auth_session={sid}", **HEADERS}


def _rows(db_path: str, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _seed_auto_row(
    db_path: str,
    *,
    student_id: str = SID_A,
    week_no: int,
    skill_code: str,
    score_0_3: int,
) -> int:
    """Insert an engine-side (``scored_by='auto'``) assessment row; returns its id.

    Written by hand on purpose: the teacher-score HTTP endpoint can only ever
    produce ``scored_by='teacher'`` rows, and the whole point of these tests is
    what happens when auto rows exist *next to* teacher rows.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO assessment_logs (student_id,session_id,topic_id,mode,"
            "lang_code,internal_label,confidence,rubric_id,evidence_text,"
            "agent_used,cost_tokens,created_at,week_no,skill_code,score_0_3,"
            "scored_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'auto')",
            (
                student_id, "sess-auto", TOPIC, "DIRECT", "zh-hk",
                f"P4.{skill_code}.1", 0.7, "rub-auto", "AI 自動評估",
                "assessment", 90, _ago_iso(days=1), week_no, skill_code, score_0_3,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
async def world(client, tmp_path, monkeypatch):
    """Fresh DB seeded with one parent / one teacher / one confirmed student."""
    monkeypatch.setattr("auth.consent.AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    db_path = auth_db._db_path()
    auth_db.ensure_schema()
    conn = sqlite3.connect(db_path)
    conn.executescript(AGENT_DDL)
    conn.commit()
    conn.close()
    auth_db.apply_class_meta_migration()
    auth_db.apply_phase8_parent_reports_migration()

    for uid, role in ((P1, "parent"), (T1, "teacher")):
        auth_db.create_user(
            user_id=uid,
            email=f"{uid}@test.local",
            password_hash="test-pass-pr7-001",
            role=role,
            email_verified=True,
        )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO students (id,parent_id,teacher_id,first_name,age_band,"
        "lang_code,pin_hash,pin_lock_until,failed_pin_count,created_at) "
        "VALUES (?,?,NULL,?,?,?,'x',NULL,0,?)",
        (SID_A, P1, "阿明", "P4-P6", "zh-hk", _ago_iso(days=90)),
    )
    cur.execute(
        "INSERT INTO classes (id,teacher_id,name,join_code,class_type,grade_band,"
        "is_one_on_one,created_at) VALUES (?,?,'週六 P4 班','PR7C0DE','monthly',"
        "'P4-P6',0,?)",
        (CLASS_A, T1, _ago_iso(days=80)),
    )
    cur.execute(
        "INSERT INTO class_students (class_id,student_id,status,created_at) "
        "VALUES (?,?,'confirmed',?)",
        (CLASS_A, SID_A, _ago_iso(days=60)),
    )
    # One topic of history so the report envelope is not the empty variant.
    cur.execute(
        "INSERT INTO assessment_logs (student_id,session_id,topic_id,mode,"
        "lang_code,internal_label,confidence,rubric_id,evidence_text,"
        "agent_used,cost_tokens,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (SID_A, "sess-1", TOPIC, "DIRECT", "zh-hk", "P4.DREAM.1", 0.8,
         "rub-1", "答對了三題", "assessment", 120, _ago_iso(days=3)),
    )
    cur.execute(
        "INSERT INTO progress_snapshots (student_id,topic_id,mastery_pct,"
        "attempt_count,last_label,streak,updated_at) VALUES (?,?,?,?,?,?,?)",
        (SID_A, TOPIC, 66.7, 3, "P4.DREAM.1", 2, _ago_iso(days=2)),
    )
    cur.execute(
        "INSERT INTO session_logs (session_id,student_id,mode,lang_code,"
        "age_band,agent_list,topic_ids,cost_summary,duration_seconds,"
        "created_at) VALUES (?,?,'DIRECT','zh-hk','P4-P6','[]',?,'{}',600,?)",
        ("sess-1", SID_A, json.dumps([TOPIC]), _ago_iso(days=3)),
    )
    conn.commit()
    conn.close()
    return {"db_path": db_path}


async def _score(client, *, week_no: int, skill_code: str, score_0_3: int):
    """Seed one teacher score through the PR-2 endpoint (no hand-written SQL)."""
    return await client.put(
        "/api/teacher/scores",
        json={
            "student_id": SID_A,
            "class_id": CLASS_A,
            "week_no": week_no,
            "skill_code": skill_code,
            "score_0_3": score_0_3,
            "evidence_text": "PR-7 純度",
        },
        headers=_cookie_header(T1),
    )


# ---------------------------------------------------------------------------
# T1 — 混行只認 teacher：較新嘅 auto 行搶唔走教師值
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr7_t1_newer_auto_row_never_overrides_teacher_score(client, world):
    """A *newer* auto row for the same (student, skill) must be ignored.

    Seeding order is deliberate: teacher row first (week 3), auto row second
    (week 5) so the auto row wins on **both** ordering keys of
    ``ORDER BY week_no DESC, id DESC LIMIT 1``. If the ``scored_by='teacher'``
    filter were ever dropped, this test reads 0 instead of 2.
    """
    resp = await _score(client, week_no=3, skill_code="DREAM", score_0_3=2)
    assert resp.status in (200, 201), await resp.text()
    auto_id = _seed_auto_row(
        world["db_path"], week_no=5, skill_code="DREAM", score_0_3=0
    )

    teacher_rows = _rows(
        world["db_path"],
        "SELECT * FROM assessment_logs WHERE student_id = ? AND skill_code = 'DREAM'"
        " AND scored_by = 'teacher'",
        (SID_A,),
    )
    auto_rows = _rows(
        world["db_path"],
        "SELECT * FROM assessment_logs WHERE student_id = ? AND skill_code = 'DREAM'"
        " AND scored_by = 'auto'",
        (SID_A,),
    )
    assert len(teacher_rows) == 1 and len(auto_rows) == 1
    assert teacher_rows[0]["score_0_3"] == 2
    assert auto_rows[0]["score_0_3"] == 0
    # premise: the auto row is the fresher one by both week and id
    assert auto_rows[0]["week_no"] > teacher_rows[0]["week_no"]
    assert auto_id > teacher_rows[0]["id"]

    scores = report_store.build_dimension_scores(SID_A, 1, 8)
    assert scores["DREAM"] == 2, "the newer auto row must not override the teacher"
    assert scores["DREAM"] != 0
    # the other three dimensions have no teacher row at all -> null, never 0
    assert scores["DISCOVER"] is None
    assert scores["DESIGN"] is None
    assert scores["DELIVER"] is None


# ---------------------------------------------------------------------------
# T2 — 純 AI 維度 = null，唔准偽造 Not Yet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr7_t2_auto_only_dimension_stays_null_and_gets_no_pitch(client, world):
    """Three teacher-graded dims + one auto-only dim (DELIVER).

    DELIVER must come out ``None`` and must get **no** descriptor: an auto score
    is not a teacher judgement, and a 0 would be pitched as the book's Level 0
    "Not Yet" opening — a fabricated verdict about the child.
    """
    for code, value in (("DREAM", 0), ("DISCOVER", 2), ("DESIGN", 3)):
        resp = await _score(client, week_no=3, skill_code=code, score_0_3=value)
        assert resp.status in (200, 201), await resp.text()
    _seed_auto_row(world["db_path"], week_no=4, skill_code="DELIVER", score_0_3=0)

    scores = report_store.build_dimension_scores(SID_A, 1, 8)
    assert scores["DREAM"] == 0, "0 from the teacher is a real score and must survive"
    assert scores["DISCOVER"] == 2
    assert scores["DESIGN"] == 3
    assert scores["DELIVER"] is None, "an auto-only dimension is missing, not 0"

    envelope = {"report": {"student_id": SID_A}}
    picked = rd.attach_dimension_descriptors(
        envelope, scores=scores, age_band="P4-P6", lang_code="zh-hk"
    )
    assert set(picked) == {"DREAM", "DISCOVER", "DESIGN"}
    assert "DELIVER" not in picked
    assert envelope["report"]["dimension_descriptors"] == picked

    # a real teacher 0 does get the Level 0 sentence — that is the contrast
    assert picked["DREAM"] == rd.descriptor("DREAM", 0, "P4-P6", "zh-hk")
    assert picked["DREAM"].startswith("尚未——")

    # ...but the auto-only dimension never borrows that sentence
    blob = json.dumps(envelope["report"], ensure_ascii=False)
    for level in range(4):
        assert rd.descriptor("DELIVER", level, "P4-P6", "zh-hk") not in blob
    assert rd.descriptor("DELIVER", 0, "P4-P6", "zh-hk") not in blob


# ---------------------------------------------------------------------------
# T3 — 全 AI 四維：唔爆，報告流程照走
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr7_t3_all_auto_dimensions_do_not_raise(client, world):
    """All four dims auto-only: build → attach → generate → approve, no raise.

    An all-ungraded report is a legitimate state (a fresh student), so the chain
    must degrade to "no 4D block" instead of blowing up or inventing scores.
    """
    for week_no, code, value in (
        (2, "DREAM", 0), (3, "DISCOVER", 1), (4, "DESIGN", 2), (5, "DELIVER", 3),
    ):
        _seed_auto_row(
            world["db_path"], week_no=week_no, skill_code=code, score_0_3=value
        )

    scores = report_store.build_dimension_scores(SID_A, 1, 8)
    assert scores == {dim: None for dim in DIMS}

    envelope = {"report": {"student_id": SID_A}}
    picked = rd.attach_dimension_descriptors(
        envelope, scores=scores, age_band="P4-P6", lang_code="zh-hk"
    )
    assert picked == {}
    assert envelope["report"]["dimension_descriptors"] == {}

    resp = await client.post(
        "/api/teacher/reports/generate",
        json={"student_id": SID_A, "class_id": CLASS_A},
        headers=_cookie_header(T1),
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    assert body["payload"]["report"]["dimension_descriptors"] == {}
    assert body["scores"] == {dim: None for dim in DIMS}

    report_id = body["report_id"]
    approve = await client.post(
        f"/api/teacher/reports/{report_id}/approve",
        json={},
        headers=_cookie_header(T1),
    )
    assert approve.status == 200, await approve.text()

    detail = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id={report_id}",
        headers=_cookie_header(P1),
    )
    assert detail.status == 200, await detail.text()
    served = (await detail.json())["report"]
    assert served["payload"]["report"]["dimension_descriptors"] == {}

    # B 案口徑：AI 素材位唔受影響——topics / recent_evidence / baseline 照舊
    # （呢三欄嘅來源係 auto 行；若後人喺 _build_topics / _build_baseline 加
    #  scored_by='teacher' filter，以下三條會一齊塌：mastery 0、evidence 空。）
    report = served["payload"]["report"]
    topics = report.get("topics") or []
    assert topics, "AI-sourced topics must not be filtered away"
    assert topics[0]["mastery_pct"] == 66.7, "mastery must not collapse to 0"
    assert topics[0]["recent_evidence"], "AI-sourced evidence must survive"
    assert "baseline" in report
