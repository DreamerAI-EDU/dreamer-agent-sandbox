"""PR-3 T-3 / T-7 — report persistence, state machine, TOCTOU hard gate.

验收对照（design book v1.1 §3.2 / §4.1 / §4.2 / §4.4 / §8.3）:

  T-7 状态机非法迁移 → 409（approved→approve、rejected→approve、
      approved→reject、pending→pending 全部拒绝，且 DB 零改动）
  T-7 one-pending 撞闸 → 409 ＋ 现有草稿链接（draft_url / report_id / status）
  T-7 supersede 链：同一区间新版本 approved → 旧版本 superseded，两行都在
      （永不 DELETE）
  T-3 band 真值贯穿：students.age_band → generate → parent_reports.age_band
      → GET /api/parent/reports（H-2 修复后的端到端证据）
  T-3 TOCTOU 并发双写：第二次 INSERT 由 DB 唯一索引拒绝（不靠应用层把关）
  T-3 硬闸镜像：migrations/phase8i canonical 与 auth/db.py 镜像逐字一致

家长端只读 GET /api/parent/reports:
  * 仅 status='approved' 可见（pending / rejected / superseded 一律不可达）
  * ownership gate（非本人子女 → 403，未知 report_id → 404）
  * student_id 出站前 8 位 mask，payload 不含 last_label_internal
  * 出站投影不含 teacher_edits / review / cost_summary

DB 级硬闸:
  * DELETE parent_reports → 触发器 ABORT
  * teacher_edits 重写 / 缩短 → 触发器 ABORT（append-only）
"""

from __future__ import annotations

import asyncio
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
from auth import report_store  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

P1 = "user-p1"          # parent of students A and B
P2 = "user-p2"          # parent of students D and E
T1 = "user-t1"          # owns class-0001 (students A, B confirmed)
T2 = "user-t2"          # owns class-0002 (student D confirmed)
SID_A = "aaaa1111aaaa2222"   # confirmed member of class-0001, band P4-P6
SID_B = "aaaa1111bbbb2222"   # confirmed member of class-0001, band P4-P6
SID_D = "dddd1111dddd2222"   # confirmed member of class-0002, band P4-P6
SID_E = "eeee1111eeee2222"   # parent P2; NOT in any confirmed class, band P2-P3

MASK_A = SID_A[:8]
TOPIC = "topic-num-1"

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
    sid = "ses-p3-" + uuid.uuid4().hex[:8]
    auth_db.create_session(session_id=sid, user_id=user_id, expires_at=_future_iso())
    return {"Cookie": f"auth_session={sid}", **HEADERS}


def _rows(db_path: str, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _report_rows(db_path: str, student_id: str = None) -> list[sqlite3.Row]:
    if student_id is None:
        return _rows(db_path, "SELECT * FROM parent_reports ORDER BY id")
    return _rows(
        db_path,
        "SELECT * FROM parent_reports WHERE student_id = ? ORDER BY id",
        (student_id,),
    )


def _payload_of(row: sqlite3.Row) -> dict:
    return json.loads(row["payload"])


def _edits_of(row: sqlite3.Row) -> list:
    return json.loads(row["teacher_edits"])


def _assert_no_internal_labels(node) -> None:
    """Recursive: the P-series internal label must never reach a client."""
    if isinstance(node, dict):
        assert "last_label_internal" not in node
        for value in node.values():
            _assert_no_internal_labels(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_internal_labels(item)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
async def world(client, tmp_path, monkeypatch):
    """Fresh DB seeded with users / students / classes / confirmed roster."""
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
            password_hash="test-pass-p3-001",
            role=role,
            email_verified=True,
        )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for sid, parent, fname, band, lang in (
        (SID_A, P1, "阿明", "P4-P6", "zh-hk"),
        (SID_B, P1, "小晴", "P4-P6", "zh-hk"),
        (SID_D, P2, "家豪", "P4-P6", "zh-hk"),
        (SID_E, P2, "新手兒", "P2-P3", "en"),
    ):
        cur.execute(
            "INSERT INTO students (id,parent_id,teacher_id,first_name,age_band,"
            "lang_code,pin_hash,pin_lock_until,failed_pin_count,created_at) "
            "VALUES (?,?,NULL,?,?,?,'x',NULL,0,?)",
            (sid, parent, fname, band, lang, _ago_iso(days=90)),
        )
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
    for cid, sid in (("class-0001", SID_A), ("class-0001", SID_B),
                     ("class-0002", SID_D)):
        cur.execute(
            "INSERT INTO class_students (class_id,student_id,status,created_at) "
            "VALUES (?,?,'confirmed',?)",
            (cid, sid, _ago_iso(days=60)),
        )
    # One topic of history per student so the envelope is not the empty variant.
    for sid, internal in ((SID_A, "P4.DREAM.1"), (SID_B, "P4.DISCOVER.2"),
                          (SID_D, "P4.DESIGN.1")):
        cur.execute(
            "INSERT INTO assessment_logs (student_id,session_id,topic_id,mode,"
            "lang_code,internal_label,confidence,rubric_id,evidence_text,"
            "agent_used,cost_tokens,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, "sess-1", TOPIC, "DIRECT", "zh-hk", internal, 0.8,
             "rub-1", "答對了三題", "assessment", 120, _ago_iso(days=3)),
        )
        cur.execute(
            "INSERT INTO progress_snapshots (student_id,topic_id,mastery_pct,"
            "attempt_count,last_label,streak,updated_at) VALUES (?,?,?,?,?,?,?)",
            (sid, TOPIC, 66.7, 3, internal, 2, _ago_iso(days=2)),
        )
        cur.execute(
            "INSERT INTO session_logs (session_id,student_id,mode,lang_code,"
            "age_band,agent_list,topic_ids,cost_summary,duration_seconds,"
            "created_at) VALUES (?,?, 'DIRECT','zh-hk','P4-P6','[]',?, '{}',600,?)",
            ("sess-1", sid, json.dumps([TOPIC]), _ago_iso(days=3)),
        )
    conn.commit()
    conn.close()
    return {"db_path": db_path}


async def _generate(client, user_id: str, *, student_id: str = SID_A,
                    class_id: str = "class-0001", **extra):
    body = {"student_id": student_id, "class_id": class_id}
    body.update(extra)
    return await client.post(
        "/api/teacher/reports/generate", json=body, headers=_cookie_header(user_id)
    )


async def _decide(client, user_id: str, report_id: str, action: str, **body):
    return await client.post(
        f"/api/teacher/reports/{report_id}/{action}",
        json=body,
        headers=_cookie_header(user_id),
    )


# ---------------------------------------------------------------------------
# T-7.1 generate — draft into pending_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t7_generate_drafts_pending_report(client, world):
    resp = await _generate(client, T1)
    assert resp.status == 201, await resp.text()
    data = await resp.json()
    assert data["ok"] is True
    assert data["status"] == "pending_review"
    assert data["version"] == 1
    assert data["student_id"] == SID_A
    assert data["class_id"] == "class-0001"
    # H-2: the stored band is the student's REAL band, never None
    assert data["age_band"] == "P4-P6"
    assert data["published_at"] == ""
    assert data["draft_url"] == f"/teacher/reports/{data['report_id']}"
    assert data["teacher_edits_count"] == 0

    rows = _report_rows(world["db_path"], SID_A)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending_review"
    assert rows[0]["age_band"] == "P4-P6"
    assert rows[0]["approved_at"] == ""
    assert rows[0]["published_at"] == ""
    # envelope persisted, internal labels already stripped at the DAO boundary
    payload = _payload_of(rows[0])
    assert payload["age_band"] == "P4-P6"
    assert payload["report"]["student_id"] == SID_A  # stored copy keeps the id
    _assert_no_internal_labels(payload)


@pytest.mark.asyncio
async def test_t7_generate_one_pending_gate_409_with_draft_link(client, world):
    first = await _generate(client, T1)
    assert first.status == 201
    draft = await first.json()

    second = await _generate(client, T1)
    assert second.status == 409, await second.text()
    body = await second.json()
    # 409 must carry the existing draft + its link (施工令: 409＋现有草稿链接)
    assert body["report_id"] == draft["report_id"]
    assert body["status"] == "pending_review"
    assert body["version"] == 1
    assert body["draft_url"] == f"/teacher/reports/{draft['report_id']}"

    rows = _report_rows(world["db_path"], SID_A)
    assert len(rows) == 1
    assert rows[0]["report_id"] == draft["report_id"]


@pytest.mark.asyncio
async def test_t7_generate_gates_cross_teacher_and_non_roster(client, world):
    # another teacher's class -> 403, zero rows
    cross = await _generate(client, T2)
    assert cross.status == 403, await cross.text()
    # a student with no confirmed class membership -> 403, zero rows
    roster = await _generate(client, T2, student_id=SID_E, class_id="class-0002")
    assert roster.status == 403, await roster.text()
    # unknown class id -> 403 (ownership gate, not 404 information leak)
    ghost = await _generate(client, T1, class_id="class-9999")
    assert ghost.status == 403, await ghost.text()
    assert _report_rows(world["db_path"]) == []


@pytest.mark.asyncio
async def test_t7_generate_validates_shape_and_role(client, world):
    parent = await _generate(client, P1)
    assert parent.status == 403, await parent.text()

    missing = await client.post(
        "/api/teacher/reports/generate",
        json={"student_id": SID_A},
        headers=_cookie_header(T1),
    )
    assert missing.status == 422, await missing.text()

    for window in (
        {"week_from": 0, "week_to": 8},
        {"week_from": 1, "week_to": 9},
        {"week_from": 5, "week_to": 4},
        {"week_from": "1", "week_to": 8},
    ):
        bad = await _generate(client, T1, **window)
        assert bad.status == 422, await bad.text()
    assert _report_rows(world["db_path"]) == []


# ---------------------------------------------------------------------------
# T-7.2 list with status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t7_list_status_filter_and_counts(client, world):
    a = await (await _generate(client, T1, student_id=SID_A)).json()
    b = await (await _generate(client, T1, student_id=SID_B)).json()
    approved = await _decide(client, T1, a["report_id"], "approve")
    assert approved.status == 200

    resp = await client.get(
        "/api/teacher/reports", headers=_cookie_header(T1)
    )
    assert resp.status == 200
    body = await resp.json()
    assert {r["report_id"] for r in body["reports"]} == {
        a["report_id"], b["report_id"]
    }
    assert body["count"] == 2
    assert body["counts"]["approved"] == 1
    assert body["counts"]["pending_review"] == 1
    assert body["counts"]["rejected"] == 0

    pending = await client.get(
        "/api/teacher/reports?status=pending_review", headers=_cookie_header(T1)
    )
    pending_body = await pending.json()
    assert [r["report_id"] for r in pending_body["reports"]] == [b["report_id"]]

    approved_only = await client.get(
        "/api/teacher/reports?status=approved", headers=_cookie_header(T1)
    )
    approved_body = await approved_only.json()
    assert [r["report_id"] for r in approved_body["reports"]] == [a["report_id"]]

    # T2 owns none of these rows; a foreign filter returns nothing
    foreign = await client.get("/api/teacher/reports", headers=_cookie_header(T2))
    assert (await foreign.json())["count"] == 0

    # unknown status -> 422
    bogus = await client.get(
        "/api/teacher/reports?status=draft", headers=_cookie_header(T1)
    )
    assert bogus.status == 422, await bogus.text()

    # parent token -> 403
    forbidden = await client.get(
        "/api/teacher/reports", headers=_cookie_header(P1)
    )
    assert forbidden.status == 403


# ---------------------------------------------------------------------------
# T-7.3 PUT — teacher edits, pending_review only, append-only audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t7_put_edits_pending_only_and_appends_audit(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]

    first = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [
            {"field": "report.summary", "before": "舊摘要", "after": "新摘要"},
            {"field": "report.roadmap", "before": "A", "after": "B"},
        ]},
        headers=_cookie_header(T1),
    )
    assert first.status == 200, await first.text()
    body = await first.json()
    assert body["status"] == "pending_review"
    assert body["teacher_edits_count"] == 2

    second = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "report.summary", "after": "再修正"}]},
        headers=_cookie_header(T1),
    )
    assert second.status == 200
    assert (await second.json())["teacher_edits_count"] == 3

    row = _report_rows(world["db_path"], SID_A)[0]
    edits = _edits_of(row)
    assert len(edits) == 3
    assert edits[0] == {
        "field": "report.summary",
        "before": "舊摘要",
        "after": "新摘要",
        "by": T1,
        "at": edits[0]["at"],
    }
    assert edits[2]["field"] == "report.summary"
    assert edits[2]["after"] == "再修正"
    # the first two entries survived verbatim (append, never rewrite)
    assert edits[1]["after"] == "B"

    # approved rows are frozen: no further edits
    assert (await _decide(client, T1, rid, "approve")).status == 200
    frozen = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "report.summary", "after": "偷偷改"}]},
        headers=_cookie_header(T1),
    )
    assert frozen.status == 409, await frozen.text()
    assert len(_edits_of(_report_rows(world["db_path"], SID_A)[0])) == 3


@pytest.mark.asyncio
async def test_t7_put_ownership_and_shape_gates(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]

    foreign = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "report.summary", "after": "x"}]},
        headers=_cookie_header(T2),
    )
    assert foreign.status == 403, await foreign.text()

    parent = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": []},
        headers=_cookie_header(P1),
    )
    assert parent.status == 403, await parent.text()

    unknown = await client.put(
        "/api/teacher/reports/rpt_nope",
        json={"edits": []},
        headers=_cookie_header(T1),
    )
    assert unknown.status == 404, await unknown.text()

    bad_shape = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": ["not-a-dict"]},
        headers=_cookie_header(T1),
    )
    assert bad_shape.status == 422, await bad_shape.text()

    blank_field = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "  ", "after": "x"}]},
        headers=_cookie_header(T1),
    )
    assert blank_field.status == 422, await blank_field.text()
    assert _edits_of(_report_rows(world["db_path"], SID_A)[0]) == []


# ---------------------------------------------------------------------------
# T-7.4 approve / reject — state machine + illegal transitions 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t7_approve_publishes_and_sets_published_at(client, world):
    draft = await (await _generate(client, T1)).json()
    resp = await _decide(client, T1, draft["report_id"], "approve", note="睇過，可以出街")
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["status"] == "approved"
    assert body["approved_at"]
    assert body["published_at"] == body["approved_at"]
    assert body["review"]["decision"] == "approve"
    assert body["review"]["decided_by"] == T1
    assert body["review"]["note"] == "睇過，可以出街"

    row = _report_rows(world["db_path"], SID_A)[0]
    assert row["status"] == "approved"
    assert row["published_at"] == row["approved_at"] != ""


@pytest.mark.asyncio
async def test_t7_illegal_transitions_409(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]
    assert (await _decide(client, T1, rid, "approve")).status == 200

    # approved -> approve (again) and approved -> reject are both illegal
    again = await _decide(client, T1, rid, "approve")
    assert again.status == 409, await again.text()
    rejected_late = await _decide(client, T1, rid, "reject")
    assert rejected_late.status == 409, await rejected_late.text()

    # rejected -> approve is illegal too
    other = await (await _generate(client, T1, student_id=SID_B)).json()
    assert (await _decide(client, T1, other["report_id"], "reject")).status == 200
    resurrect = await _decide(client, T1, other["report_id"], "approve")
    assert resurrect.status == 409, await resurrect.text()

    rows = {r["report_id"]: r for r in _report_rows(world["db_path"])}
    assert rows[rid]["status"] == "approved"
    assert rows[other["report_id"]]["status"] == "rejected"
    assert rows[other["report_id"]]["published_at"] == ""
    # the rejected draft is kept, never deleted, and its edit log is intact
    assert rows[other["report_id"]]["version"] == 1


@pytest.mark.asyncio
async def test_t7_reject_releases_gate_and_keeps_history(client, world):
    first = await (await _generate(client, T1)).json()
    assert (await _decide(client, T1, first["report_id"], "reject")).status == 200

    # the one-pending gate is free again -> a fresh draft is accepted
    second = await _generate(client, T1)
    assert second.status == 201, await second.text()
    second_body = await second.json()
    assert second_body["version"] == 2

    rows = _report_rows(world["db_path"], SID_A)
    assert [r["status"] for r in rows] == ["rejected", "pending_review"]
    assert [r["version"] for r in rows] == [1, 2]


@pytest.mark.asyncio
async def test_t7_supersede_chain_keeps_history(client, world):
    v1 = await (await _generate(client, T1)).json()
    assert (await _decide(client, T1, v1["report_id"], "approve")).status == 200
    v2 = await (await _generate(client, T1)).json()
    assert v2["version"] == 2
    assert (await _decide(client, T1, v2["report_id"], "approve")).status == 200

    rows = {r["report_id"]: r for r in _report_rows(world["db_path"], SID_A)}
    assert len(rows) == 2  # 永不 DELETE
    assert rows[v1["report_id"]]["status"] == "superseded"
    assert rows[v2["report_id"]]["status"] == "approved"
    # the superseded row keeps its own publication stamp (history, not erased)
    assert rows[v1["report_id"]]["published_at"] != ""

    # superseded rows are not parent-visible and cannot be re-approved
    parent_list = await client.get(
        f"/api/parent/reports?student_id={SID_A}", headers=_cookie_header(P1)
    )
    listed = (await parent_list.json())["reports"]
    assert [r["report_id"] for r in listed] == [v2["report_id"]]


# ---------------------------------------------------------------------------
# T-3/T-7.5 parent read-only surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t7_parent_reports_approved_only(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]

    # pending -> invisible (empty list, detail 404)
    pending_list = await client.get(
        f"/api/parent/reports?student_id={SID_A}", headers=_cookie_header(P1)
    )
    assert pending_list.status == 200
    assert (await pending_list.json())["count"] == 0
    pending_detail = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id={rid}",
        headers=_cookie_header(P1),
    )
    assert pending_detail.status == 404, await pending_detail.text()

    assert (await _decide(client, T1, rid, "approve")).status == 200

    listed = await client.get(
        f"/api/parent/reports?student_id={SID_A}", headers=_cookie_header(P1)
    )
    body = await listed.json()
    assert body["count"] == 1
    summary = body["reports"][0]
    assert summary["report_id"] == rid
    assert summary["status"] == "approved"
    assert summary["student_id"] == MASK_A
    assert summary["age_band"] == "P4-P6"
    # list view is a summary: no report body, no internal audit fields
    assert "payload" not in summary
    for leaked in ("teacher_edits", "review", "cost_summary", "generated_by"):
        assert leaked not in summary

    detail = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id={rid}",
        headers=_cookie_header(P1),
    )
    assert detail.status == 200
    detail_body = (await detail.json())["report"]
    assert detail_body["student_id"] == MASK_A
    assert detail_body["age_band"] == "P4-P6"
    assert detail_body["payload"]["report"]["student_id"] == MASK_A
    _assert_no_internal_labels(detail_body)
    assert SID_A not in json.dumps(detail_body)

    # rejected rows stay invisible as well
    other = await (await _generate(client, T1, student_id=SID_B)).json()
    assert (await _decide(client, T1, other["report_id"], "reject")).status == 200
    b_list = await client.get(
        f"/api/parent/reports?student_id={SID_B}", headers=_cookie_header(P1)
    )
    assert (await b_list.json())["count"] == 0


@pytest.mark.asyncio
async def test_t7_parent_reports_ownership_gate(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]
    assert (await _decide(client, T1, rid, "approve")).status == 200

    # another parent asking for student A's report -> unified 403
    foreign = await client.get(
        f"/api/parent/reports?student_id={SID_A}", headers=_cookie_header(P2)
    )
    assert foreign.status == 403, await foreign.text()
    foreign_detail = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id={rid}",
        headers=_cookie_header(P2),
    )
    assert foreign_detail.status == 403

    # teacher token on the parent surface -> 403
    teacher = await client.get(
        f"/api/parent/reports?student_id={SID_A}", headers=_cookie_header(T1)
    )
    assert teacher.status == 403

    # no student_id -> 400; unknown student -> 403
    empty = await client.get("/api/parent/reports", headers=_cookie_header(P1))
    assert empty.status == 400, await empty.text()
    ghost = await client.get(
        "/api/parent/reports?student_id=zzzz9999zzzz9999", headers=_cookie_header(P1)
    )
    assert ghost.status == 403

    # 8-char masks that collide across siblings are refused as ambiguous (400)
    ambiguous = await client.get(
        f"/api/parent/reports?student_id={MASK_A}", headers=_cookie_header(P1)
    )
    assert ambiguous.status == 400, await ambiguous.text()

    # an unknown report_id for an owned student -> 404 (no id probing)
    missing = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id=rpt_ghost",
        headers=_cookie_header(P1),
    )
    assert missing.status == 404, await missing.text()


# ---------------------------------------------------------------------------
# T-3 band true value — generate -> store -> parent surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t3_band_true_value_threads_generate_to_parent(client, world):
    """H-2 end-to-end: the band stored and served is the students.age_band."""
    drafts = {}
    for sid, band in ((SID_A, "P4-P6"), (SID_B, "P4-P6")):
        resp = await _generate(client, T1, student_id=sid)
        assert resp.status == 201, await resp.text()
        drafts[sid] = await resp.json()
        assert drafts[sid]["age_band"] == band
    assert (await _decide(client, T1, drafts[SID_A]["report_id"], "approve")).status == 200

    # DB column carries the real band (never None / never "")
    row = _report_rows(world["db_path"], SID_A)[0]
    assert row["age_band"] == "P4-P6"
    assert _payload_of(row)["age_band"] == "P4-P6"

    # and it survives to the parent-facing projection
    detail = await client.get(
        f"/api/parent/reports?student_id={SID_A}&report_id={drafts[SID_A]['report_id']}",
        headers=_cookie_header(P1),
    )
    assert detail.status == 200
    body = (await detail.json())["report"]
    assert body["age_band"] == "P4-P6"
    assert body["payload"]["age_band"] == "P4-P6"

    # the DB value really is derived from students.age_band (single source)
    assert _rows(
        world["db_path"],
        "SELECT age_band FROM students WHERE id = ?",
        (SID_A,),
    )[0]["age_band"] == body["age_band"]


@pytest.mark.asyncio
async def test_t3_band_true_value_for_lower_band_student(client, world):
    """A P2-P3 student must not be described with a P4-P6 band."""
    conn = sqlite3.connect(world["db_path"])
    conn.execute(
        "INSERT INTO class_students (class_id,student_id,status,created_at) "
        "VALUES ('class-0002',?,'confirmed',?)",
        (SID_E, _ago_iso(days=30)),
    )
    conn.commit()
    conn.close()

    draft = await _generate(client, T2, student_id=SID_E, class_id="class-0002")
    assert draft.status == 201, await draft.text()
    body = await draft.json()
    assert body["age_band"] == "P2-P3"
    assert (await _decide(client, T2, body["report_id"], "approve")).status == 200

    detail = await client.get(
        f"/api/parent/reports?student_id={SID_E}&report_id={body['report_id']}",
        headers=_cookie_header(P2),
    )
    assert detail.status == 200
    served = (await detail.json())["report"]
    assert served["age_band"] == "P2-P3"
    assert served["payload"]["age_band"] == "P2-P3"


# ---------------------------------------------------------------------------
# T-3 DB-level hard gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t3_report_rows_no_delete_and_edits_append_only(client, world):
    draft = await (await _generate(client, T1)).json()
    rid = draft["report_id"]
    await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "report.summary", "after": "新摘要"}]},
        headers=_cookie_header(T1),
    )

    conn = sqlite3.connect(world["db_path"])
    try:
        # ① the report row itself can never be deleted
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM parent_reports WHERE report_id = ?", (rid,))
        # ② teacher_edits cannot be rewritten...
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE parent_reports SET teacher_edits = ? WHERE report_id = ?",
                (json.dumps([{"field": "fake"}]), rid),
            )
        # ...nor shrunk
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE parent_reports SET teacher_edits = '[]' WHERE report_id = ?",
                (rid,),
            )
    finally:
        conn.close()

    # an append through the supported channel still works and survives
    appended = await client.put(
        f"/api/teacher/reports/{rid}",
        json={"edits": [{"field": "report.roadmap", "after": "第二步"}]},
        headers=_cookie_header(T1),
    )
    assert appended.status == 200
    assert len(_edits_of(_report_rows(world["db_path"], SID_A)[0])) == 2


@pytest.mark.asyncio
async def test_t3_toctou_concurrent_double_write_rejected_by_db(client, world):
    """The PR-2 race widow is closed physically, not by application checks.

    Three layers of evidence:
      ① HTTP: two racing PUTs for the same key both answer without a 500 and
         exactly one live row survives.
      ② DB: the read-then-write window is replayed by hand on two SQLite
         connections — both read "no row", the first INSERT lands and the
         second is rejected by ``uq_assessment_teacher_score``. That rejection
         (not any Python check) is what makes the double-write impossible.
      ③ DAO: a lost race degrades into the documented overwrite semantics, and
         the replaced value lands in the append-only audit carrying only the
         8-char student mask (red line 8).
    """
    body = {
        "student_id": SID_A,
        "class_id": "class-0001",
        "week_no": 3,
        "skill_code": "DREAM",
        "score_0_3": 2,
        "evidence_text": "第一寫",
    }

    # ① HTTP level: two concurrent writes, neither may 500
    headers = {"X-Requested-With": "XMLHttpRequest"}
    resp_a, resp_b = await asyncio.gather(
        client.put("/api/teacher/scores", json=body, headers={**_cookie_header(T1)}),
        client.put("/api/teacher/scores", json=body, headers={**_cookie_header(T1)}),
    )
    assert resp_a.status in (200, 201), await resp_a.text()
    assert resp_b.status in (200, 201), await resp_b.text()

    key = (SID_A, 3, "DREAM")
    live = _rows(
        world["db_path"],
        "SELECT * FROM assessment_logs WHERE student_id = ? AND scored_by = 'teacher'"
        " AND week_no = 3 AND skill_code = 'DREAM'",
        (SID_A,),
    )
    assert len(live) == 1, "TOCTOU: two live teacher scores for one key"

    # ② DB level: replay the read-then-write window on two connections
    insert_sql = (
        "INSERT INTO assessment_logs (student_id, session_id, topic_id, mode,"
        " lang_code, internal_label, confidence, rubric_id, evidence_text,"
        " agent_used, cost_tokens, created_at, week_no, skill_code,"
        " score_0_3, scored_by) VALUES (?,'s','t','DIRECT','zh-hk','teacher_score',"
        "0.0,'',?,'teacher',0,?,?,?,?, 'teacher')"
    )
    conn1 = sqlite3.connect(world["db_path"])
    conn2 = sqlite3.connect(world["db_path"])
    try:
        # both writers pre-check and see "no row yet" for a brand-new key
        probe = "SELECT id FROM assessment_logs WHERE student_id=? AND week_no=? AND skill_code=? AND scored_by='teacher'"
        assert conn1.execute(probe, (SID_B, 4, "DELIVER")).fetchone() is None
        assert conn2.execute(probe, (SID_B, 4, "DELIVER")).fetchone() is None
        # writer 1 commits first ...
        conn1.execute(insert_sql, (SID_B, "race-1", _ago_iso(days=1), 4, "DELIVER", 2))
        conn1.commit()
        # ... writer 2's INSERT is physically rejected by the partial index
        with pytest.raises(sqlite3.IntegrityError):
            conn2.execute(
                insert_sql, (SID_B, "race-2", _ago_iso(days=1), 4, "DELIVER", 3)
            )
        # the pre-check premise itself is now false: the row exists
        assert conn2.execute(probe, (SID_B, 4, "DELIVER")).fetchone() is not None
        assert len(_rows(world["db_path"], probe, (SID_B, 4, "DELIVER"))) == 1
    finally:
        conn1.close()
        conn2.close()

    # ③ DAO level: the losing writer degrades to overwrite, old value audited
    overwrite = await client.put(
        "/api/teacher/scores",
        json={**body, "score_0_3": 3, "evidence_text": "第二寫"},
        headers={"X-Requested-With": "XMLHttpRequest", **_cookie_header(T1)},
    )
    assert overwrite.status == 200, await overwrite.text()
    assert (await overwrite.json())["status"] == "updated"

    still_one = _rows(
        world["db_path"],
        "SELECT * FROM assessment_logs WHERE student_id = ? AND scored_by='teacher'"
        " AND week_no = 3 AND skill_code = 'DREAM'",
        (SID_A,),
    )
    assert len(still_one) == 1
    assert still_one[0]["score_0_3"] == 3

    audit = _rows(world["db_path"], "SELECT * FROM teacher_score_audit ORDER BY id")
    assert len(audit) == 1
    assert audit[0]["student_mask"] == SID_A[:8]
    assert audit[0]["student_mask"] != SID_A  # red line 8: mask only
    assert audit[0]["old_score"] == 2
    assert audit[0]["assessment_id"] == still_one[0]["id"]
    assert key == (SID_A, 3, "DREAM")


@pytest.mark.asyncio
async def test_t3_phase8i_canonical_matches_db_mirror(client, world):
    """phase8i 规范档与 db.py 镜像必须逐字一致（canonical == mirror）。"""
    path = os.path.join(REPO_ROOT, "migrations", "phase8i_pr3_report_state_machine.sql")
    with open(path, encoding="utf-8") as fh:
        canonical = fh.read()

    for needle in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_teacher_score",
        "ON assessment_logs(student_id, week_no, skill_code)",
        "WHERE scored_by = 'teacher'",
        "CREATE TRIGGER IF NOT EXISTS parent_reports_no_delete",
        "CREATE TRIGGER IF NOT EXISTS parent_reports_teacher_edits_append_only",
    ):
        assert needle in canonical, f"canonical is missing: {needle}"

    def _norm(text: str) -> str:
        """Compare SQL statements only: drop ``--`` comments and collapse ws."""
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(stripped)
        return " ".join(" ".join(lines).split()).replace(" ;", ";")

    mirror_ok = _norm(auth_db._PR3_TEACHER_SCORE_UNIQUE_DDL) in _norm(canonical)
    assert mirror_ok, "uq_assessment_teacher_score mirror drifted from canonical"
    guards_ok = _norm(auth_db._PR3_PARENT_REPORTS_GUARDS_DDL) in _norm(canonical)
    assert guards_ok, "parent_reports guard mirror drifted from canonical"
    assert "_PR3_TEACHER_SCORE_UNIQUE_DDL" in canonical
    assert "_PR3_PARENT_REPORTS_GUARDS_DDL" in canonical

    # the guard mirror is wired into _DDL (fresh DB) ...
    assert "parent_reports_no_delete" in auth_db._DDL
    assert "parent_reports_teacher_edits_append_only" in auth_db._DDL
    # ... while ① cannot be (auth/db.py does not own assessment_logs on a fresh
    # DB) — it must instead ride the post-migration 补钉 path.
    import inspect

    assert "uq_assessment_teacher_score" not in auth_db._DDL
    apply_src = inspect.getsource(auth_db.apply_phase8i_pr3_migration)
    assert "_PR3_TEACHER_SCORE_UNIQUE_DDL" in apply_src
    assert "assessment_logs" in apply_src
    assert callable(auth_db.apply_phase8i_pr3_migration)

    rows = _rows(
        world["db_path"],
        "SELECT name, sql FROM sqlite_master WHERE name IN"
        " ('uq_assessment_teacher_score', 'parent_reports_no_delete',"
        " 'parent_reports_teacher_edits_append_only')",
    )
    names = {r["name"] for r in rows}
    assert names == {
        "uq_assessment_teacher_score",
        "parent_reports_no_delete",
        "parent_reports_teacher_edits_append_only",
    }
    index_sql = next(r["sql"] for r in rows if r["name"] == "uq_assessment_teacher_score")
    assert "WHERE scored_by = 'teacher'" in index_sql


# ---------------------------------------------------------------------------
# state-machine constants (contract lock)
# ---------------------------------------------------------------------------


def test_t7_legal_transition_table_shape():
    assert report_store.LEGAL_TRANSITIONS == {
        "pending_review": ("approved", "rejected"),
        "approved": ("superseded",),
        "rejected": (),
        "superseded": (),
    }
    assert "pending_review" not in report_store.LEGAL_TRANSITIONS["rejected"]
    assert report_store.SCORE_DIMENSIONS == (
        "DREAM", "DISCOVER", "DESIGN", "DELIVER",
    )
    assert report_store.REPORT_STATUSES == (
        "pending_review", "approved", "rejected", "superseded",
    )
