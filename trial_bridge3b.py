"""trial_bridge3b.py — parent 8-week course map, real-server round trip.

Boss work order 2026-09-12 (3b spec, Parent Dashboard 8 週地圖) + ruling #5
("mock-green ≠ real"): the map must be exercised for real — real HTTP over a
real socket, a real SQLite database, the real assessment writer, a real audit
sink — through the same endpoints the product uses:

    teacher register/login -> create class -> mount the ready-made 8-week course
    -> invite the parent (POST /api/invites) -> parent confirms from the token
    -> teacher confirms the binding -> (parent surface)
       GET /api/parent/curriculum?student_id=... -> advance weeks -> read again

Checks
  ----- positive path (spec: 8 cells / mastery / advance / completion) -----
  1  parent reads its own child: 200 active, Week 1 / 8, eight grid cells,
     authored titles verbatim, authored course title
  2  no data yet -> every week mastery_pct is null, NEVER 0% (neutral)
  3  the real assessment writer (AssessmentAgent.progress_track) lands a
     snapshot -> that week shows the raw 0..1 rolling value, others stay null
  4  a STORED 0.0 is real data and stays 0.0 (distinct from the null above)
  5  mastery is scoped per child: a sibling in the same class still sees null
  6  two advances -> the grid flips (completed / completed / active / locked)
     and the stored mastery survives the advance
  7  eight weeks done -> state=completed, week 8 completed; a 9th advance 409
  ----- guard rails (spec: parent guard / 403 / neutral / 401) -----
  8  anonymous -> 401
  9  teacher session -> 403 (+ WARNING), not a staff lens
 10  cross-family read -> 403 + WARNING, nothing read, nothing leaked
 11  no mounted course / no class -> 200 neutral (weeks [], never a 500)
 12  the wire payload carries no student id and no internal topic_id
 13  the four negative cases exist by name and are on the CI manifest
 14  the frontend renders the backend title verbatim, is null-safe, 3 languages
  ----- evidence -----
 15  audit sink isolation: <repo>/audit_log.jsonl untouched by the whole run

Workdir: %DREAMER_TRIAL_DIR% (defaults to a temp dir) — the trial never writes
into the repo working tree. Exit code 0 only when every check passes.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

WORKDIR = Path(
    os.environ.get("DREAMER_TRIAL_DIR") or tempfile.mkdtemp(prefix="bridge3b_trial_")
)
WORKDIR.mkdir(parents=True, exist_ok=True)
DB_PATH = WORKDIR / "trial_auth.db"
AUDIT_PATH = WORKDIR / "audit_log.jsonl"

# Point the real modules at the trial workdir BEFORE importing them: auth/db.py
# resolves DREAMER_DB_PATH per connect(), auth/consent.py reads its sink at
# import time, agents/assessment_agent.py resolves DB_PATH at import time.
# Nothing in this process may touch the repo's real DB / audit log.
os.environ["DREAMER_DB_PATH"] = str(DB_PATH)
os.environ["DREAMER_AUDIT_LOG_PATH"] = str(AUDIT_PATH)
os.environ.setdefault("PYTHONPATH", str(REPO_ROOT))

import httpx  # noqa: E402
from aiohttp import web  # noqa: E402

from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402
from auth import curriculum as curriculum_mod  # noqa: E402
from pipeline import topic_metadata_schema  # noqa: E402
from agents.assessment_agent import AssessmentAgent  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
COURSE_ID = "dreamer-curriculum"
MAP_URL = "/api/parent/curriculum"

# The authored, family-facing week titles — Bridge-1's topic_metadata is the
# only source of these strings; the frontend must never build one itself.
WEEK_TITLES = {
    1: "第 1 週：AI 係咩嚟嘅？",
    2: "第 2 週：同 AI 傾偈",
    3: "第 3 週：AI 點樣學嘢",
    4: "第 4 週：提示詞小技巧",
    5: "第 5 週：AI 幫我寫故事",
    6: "第 6 週：AI 畫畫",
    7: "第 7 週：AI 同我嘅生活",
    8: "第 8 週：我做嘅 AI 小專題",
}

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# Fixtures — real rows in the trial DB
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_schema() -> None:
    auth_db.ensure_schema()
    auth_db.apply_class_curriculum_migration()
    conn = _conn()
    try:
        topic_metadata_schema.ensure_schema(conn)
    finally:
        conn.close()


def _seed_course() -> None:
    """The ready-made 8-week course a teacher mounts (Bridge-1 SoT)."""
    conn = _conn()
    try:
        for week, title in WEEK_TITLES.items():
            conn.execute(
                "INSERT INTO topic_metadata (topic_id, subject, topic, "
                "modes_allowed, grade_level, week, dreamer_phase, kb_name, "
                "document_path, document_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"curriculum-wk{week:02d}",
                    "AI Literacy",
                    title,
                    '["contextual"]',
                    "P4-P6",
                    week,
                    '["Design"]',
                    COURSE_ID,
                    f"curriculum-wk{week:02d}.md",
                    f"hash-{week}",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _invite_token_for(student_id: str) -> str:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT token FROM invites WHERE student_id = ? "
            "AND used_at IS NULL ORDER BY rowid DESC LIMIT 1",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no pending invite row"
    return str(row["token"])


def _student_id_for_email(parent_email: str) -> str:
    """The invited child, read back from the invite row the API created."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT student_id FROM invites WHERE parent_email = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (parent_email,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no student for {parent_email}"
    return str(row["student_id"])


def _week_topic_ids(class_id: str) -> dict[int, str]:
    """The class's mounted ``topic_id`` per week — the bridge's own rows."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT week_no, topic_id FROM class_curriculum "
            "WHERE class_id = ? ORDER BY week_no ASC",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()
    return {int(r["week_no"]): str(r["topic_id"]) for r in rows}


def _seed_child_of(
    parent_id: str,
    *,
    class_id: str | None,
    first_name: str,
    status: str = "pending",
) -> str:
    """A child the invite flow cannot produce: no class, or a raw class row.

    Same shape the unit tests use — these are states, not user journeys.
    """
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


def _audit_events() -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    return [
        json.loads(line)
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Real HTTP helpers
# ---------------------------------------------------------------------------

def _client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def _absorb_session(client: httpx.AsyncClient, resp: httpx.Response) -> None:
    """Carry the session cookie the way a browser does.

    The cookie is ``Secure``; the trial speaks plain HTTP on loopback, where a
    cookie jar would withhold it, so the header is set explicitly. Production
    (Caddy + TLS) behaves exactly like this header.
    """
    for raw in resp.headers.get_list("set-cookie"):
        if raw.startswith("auth_session="):
            client.headers["Cookie"] = raw.split(";", 1)[0]
            return
    raise AssertionError("no auth_session cookie on the response")


async def _register_teacher(client: httpx.AsyncClient, email: str, invite: str) -> None:
    resp = await client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": "test-pass-teacher1"},
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), await _text(resp)


async def _login(client: httpx.AsyncClient, email: str, password: str) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=HEADERS
    )
    assert resp.status_code == 200, await _text(resp)
    _absorb_session(client, resp)


async def _confirm_parent(client: httpx.AsyncClient, token: str) -> None:
    resp = await client.post(
        f"/api/invites/{token}/confirm",
        json={
            "password": "test-pass-parent1",
            "privacy_policy": True,
            "chat_consent": True,
            "media_consent": False,
        },
    )
    assert resp.status_code == 201, await _text(resp)
    _absorb_session(client, resp)


async def _text(resp: httpx.Response) -> str:
    return f"{resp.status_code} {resp.text[:300]}"


async def _map(
    client: httpx.AsyncClient, identifier: str
) -> tuple[int, dict, str]:
    resp = await client.get(
        f"{MAP_URL}?student_id={identifier}", headers=HEADERS
    )
    try:
        body = resp.json()
    except Exception:  # pragma: no cover — non-JSON error body
        body = {}
    return resp.status_code, body, resp.text


def _statuses(body: dict) -> list[str]:
    return [str(w["status"]) for w in body.get("weeks", [])]


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 68)
    print("  Bridge-3b — parent 8-week course map · real-server trial")
    print("=" * 68)
    print(f"  workdir : {WORKDIR}")
    print(f"  db      : {DB_PATH}")
    print(f"  audit   : {AUDIT_PATH}")

    repo_audit = REPO_ROOT / "audit_log.jsonl"
    repo_audit_before = repo_audit.exists()

    # The trial owns its workdir — start from an empty DB and sink each run.
    for stale in (DB_PATH, AUDIT_PATH):
        if stale.exists():
            stale.unlink()

    _seed_schema()
    _seed_course()
    auth_db.insert_teacher_invite(
        code="trial-invite-001", created_by="trial", expires_at=_future_iso(days=1)
    )

    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    print(f"  server  : {base_url}\n")

    teacher = _client(base_url)
    parent = _client(base_url)
    parent_b = _client(base_url)
    teacher_b = _client(base_url)
    anon = _client(base_url)

    try:
        # ── Real journey: teacher creates the class and the invite ──────────
        await _register_teacher(teacher, "trial-teacher@dreamer.local", "trial-invite-001")
        await _login(teacher, "trial-teacher@dreamer.local", "test-pass-teacher1")

        resp = await teacher.post("/api/classes", json={"name": "Trial P4 AI"}, headers=HEADERS)
        assert resp.status_code == 201, await _text(resp)
        class_id = resp.json()["class"]["id"]
        print(f"  class   : {class_id}")

        resp = await teacher.post(
            f"/api/classes/{class_id}/curriculum",
            json={"curriculum_id": COURSE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 201, await _text(resp)
        mounted = resp.json()
        print(f"  mounted : week 1..{mounted.get('week_count')} of {COURSE_ID}\n")
        topic_ids = _week_topic_ids(class_id)

        resp = await teacher.post(
            "/api/invites",
            json={
                "first_name": "Mia",
                "age_band": "P4-P6",
                "lang_code": "zh-hk",
                "parent_email": "trial-parent-a@dreamer.local",
                "class_id": class_id,
                "pin": "2468",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 201, await _text(resp)

        kid_id = _student_id_for_email("trial-parent-a@dreamer.local")
        token = _invite_token_for(kid_id)
        public = await anon.get(f"/api/invites/{token}")
        assert public.status_code == 200, await _text(public)

        await _confirm_parent(parent, token)
        me = await parent.get("/api/auth/me")
        assert me.status_code == 200 and (me.json())["user"]["role"] == "parent", (
            await _text(me)
        )
        parent_uid = (me.json())["user"]["id"]

        # Teacher approves the binding from the console — the real journey: the
        # child only becomes a confirmed class member after this step, and only
        # then does the map resolve to an active week.
        pending = await teacher.get(f"/api/classes/{class_id}/pending", headers=HEADERS)
        assert pending.status_code == 200, await _text(pending)
        assert any(
            p["student_id"] == kid_id for p in pending.json()["pending"]
        ), await _text(pending)
        resp = await teacher.post(
            f"/api/classes/{class_id}/confirm",
            json={"student_id": kid_id},
            headers=HEADERS,
        )
        assert resp.status_code == 200, await _text(resp)

        # ── 1. Week 1 / 8, eight cells, authored strings verbatim ───────────
        code, body, raw = await _map(parent, kid_id[:8])
        titles_ok = [w["title"] for w in body.get("weeks", [])] == [
            WEEK_TITLES[n] for n in range(1, 9)
        ]
        check(
            "1. parent -> own child: 200 active, Week 1 / 8, 8 authored cells",
            code == 200
            and body.get("state") == "active"
            and body.get("current_week") == 1
            and body.get("total_weeks") == 8
            and len(body.get("weeks", [])) == 8
            and _statuses(body)[0] == "active"
            and set(_statuses(body)[1:]) == {"locked"}
            and titles_ok
            and body.get("course_title") == "AI Literacy",
            f"{code} | course_title={body.get('course_title')!r} | titles_verbatim={titles_ok}",
        )

        # ── 2. no data yet -> null, never 0% ────────────────────────────────
        neutral_ok = all(w["mastery_pct"] is None for w in body["weeks"])
        check(
            "2. no data yet -> every week mastery_pct is null (never 0%)",
            neutral_ok,
            "mastery=" + json.dumps([w["mastery_pct"] for w in body["weeks"]]),
        )

        # ── 5. mastery is scoped per child (sibling in the same class) ──────
        sibling_id = _seed_child_of(
            parent_uid, class_id=class_id, first_name="Ann", status="confirmed"
        )
        code_sib, sib_body, _ = await _map(parent, sibling_id)
        check(
            "5. mastery is scoped per child: the sibling's map is still all null",
            code_sib == 200
            and sib_body.get("state") == "active"
            and len(sib_body.get("weeks", [])) == 8
            and all(w["mastery_pct"] is None for w in sib_body["weeks"]),
            "sibling mastery=" + json.dumps([w["mastery_pct"] for w in sib_body.get("weeks", [])]),
        )

        # ── 3. the real assessment writer lands a snapshot ──────────────────
        agent = AssessmentAgent()
        write = await agent.progress_track(
            {
                "student_id": kid_id,
                "session_id": "trial-session-1",
                "topic_id": topic_ids[2],
                "mode": "DIRECT",
                "lang_code": "zh-hk",
                "internal_label": "achieved",
                "confidence": 0.9,
                "rubric_id": "trial-rubric",
                "evidence_text": "trial: real assessment write",
                "agent_used": "assessment",
                "cost_tokens": 0,
                "age_band": "P4-P6",
            }
        )
        code_w, body_w, _ = await _map(parent, kid_id[:8])
        check(
            "3. real writer (progress_track) -> that week shows the raw 0..1 value",
            write.get("status") == "ok"
            and write.get("snapshot_id") != ""
            and code_w == 200
            and body_w["weeks"][1]["mastery_pct"] == 0.75
            and all(w["mastery_pct"] is None for i, w in enumerate(body_w["weeks"]) if i != 1),
            f"write={write.get('status')} snapshot={write.get('snapshot_id')} "
            f"week2={body_w['weeks'][1]['mastery_pct']}",
        )

        # ── 4. a STORED 0.0 is real data (distinct from null) ───────────────
        await agent.progress_track(
            {
                "student_id": kid_id,
                "session_id": "trial-session-2",
                "topic_id": topic_ids[3],
                "mode": "DIRECT",
                "lang_code": "zh-hk",
                "internal_label": "ungraded",  # unknown label -> real 0.0
                "confidence": 0.9,
                "rubric_id": "trial-rubric",
                "evidence_text": "trial: scored zero",
                "agent_used": "assessment",
                "cost_tokens": 0,
                "age_band": "P4-P6",
            }
        )
        code_z, body_z, _ = await _map(parent, kid_id[:8])
        check(
            "4. stored 0.0 stays 0.0 while the untouched week stays null",
            body_z["weeks"][2]["mastery_pct"] == 0.0
            and body_z["weeks"][3]["mastery_pct"] is None,
            f"week3={body_z['weeks'][2]['mastery_pct']} week4={body_z['weeks'][3]['mastery_pct']}",
        )

        # ── 6. two advances -> the grid flips, mastery survives ────────────
        for _ in range(2):
            resp = await teacher.post(
                f"/api/classes/{class_id}/advance-week", headers=HEADERS
            )
            assert resp.status_code == 200, await _text(resp)
        code_a, body_a, _ = await _map(parent, kid_id[:8])
        check(
            "6. two advances -> 2 completed / 1 active / 5 locked, mastery kept",
            code_a == 200
            and body_a["current_week"] == 3
            and _statuses(body_a) == ["completed", "completed", "active"] + ["locked"] * 5
            and body_a["weeks"][1]["mastery_pct"] == 0.75
            and body_a["weeks"][2]["mastery_pct"] == 0.0,
            f"current_week={body_a['current_week']} statuses={_statuses(body_a)}",
        )

        # ── 11. neutral states -> 200, never 500 ───────────────────────────
        empty_resp = await teacher.post(
            "/api/classes", json={"name": "No course yet"}, headers=HEADERS
        )
        empty_class = empty_resp.json()["class"]["id"]
        pending_kid = _seed_child_of(
            parent_uid, class_id=empty_class, first_name="Joe"
        )
        noclass_kid = _seed_child_of(parent_uid, class_id=None, first_name="Eve")
        for label, sid in (("no mounted course", pending_kid), ("no class", noclass_kid)):
            code_n, body_n, _ = await _map(parent, sid)
            check(
                f"11. child with {label} -> 200 neutral (empty grid, no 500)",
                code_n == 200
                and body_n["state"] == "none"
                and body_n["weeks"] == []
                and body_n["current_week"] is None
                and body_n["total_weeks"] == 8,
                json.dumps(body_n, ensure_ascii=False),
            )

        # ── 12. wire payload hygiene ────────────────────────────────────────
        _, _, raw_now = await _map(parent, kid_id[:8])
        check(
            "12. payload carries no student id and no internal topic_id",
            kid_id not in raw_now
            and "curriculum-wk" not in raw_now
            and "topic_id" not in raw_now
            and "progress_snapshots" not in raw_now,
            raw_now[:180],
        )

        # ── 8. anonymous -> 401 ────────────────────────────────────────────
        code_anon, _, raw_anon = await _map(anon, kid_id[:8])
        check(
            "8. anonymous -> 401 (no session, no read)",
            code_anon == 401,
            raw_anon[:120],
        )

        # ── 9. teacher session -> 403 + WARNING ────────────────────────────
        code_t, _, raw_t = await _map(teacher, kid_id[:8])
        role_warned = any(
            e.get("event") == "curriculum_parent_role_denied"
            and e.get("level") == "WARNING"
            for e in _audit_events()
        )
        check(
            "9. teacher session -> 403 + WARNING (parent map is not a staff lens)",
            code_t == 403 and role_warned,
            f"{raw_t[:90]} | warning_logged={role_warned}",
        )

        # ── 10. cross-family -> 403 + WARNING, nothing leaked ──────────────
        auth_db.insert_teacher_invite(
            code="trial-invite-002", created_by="trial", expires_at=_future_iso(days=1)
        )
        await _register_teacher(teacher_b, "trial-teacher-b@dreamer.local", "trial-invite-002")
        await _login(teacher_b, "trial-teacher-b@dreamer.local", "test-pass-teacher1")
        resp = await teacher_b.post(
            "/api/classes", json={"name": "Other class"}, headers=HEADERS
        )
        other_class = resp.json()["class"]["id"]
        resp = await teacher_b.post(
            "/api/invites",
            json={
                "first_name": "Sam",
                "age_band": "P4-P6",
                "lang_code": "zh-hk",
                "parent_email": "trial-parent-b@dreamer.local",
                "class_id": other_class,
                "pin": "1357",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 201, await _text(resp)
        other_kid = _student_id_for_email("trial-parent-b@dreamer.local")
        other_token = _invite_token_for(other_kid)
        await _confirm_parent(parent_b, other_token)

        code_x, _, raw_x = await _map(parent, other_kid)
        cross_warned = any(
            e.get("event") == "curriculum_parent_cross_access"
            and e.get("level") == "WARNING"
            for e in _audit_events()
        )
        check(
            "10. cross-family read -> 403, no leak, WARNING logged",
            code_x == 403
            and cross_warned
            and other_kid not in raw_x
            and WEEK_TITLES[1] not in raw_x,
            f"{raw_x[:90]} | warning_logged={cross_warned}",
        )

        # ── 13. the four negative cases are CI red lines ──────────────────
        test_src = (
            REPO_ROOT / "tests" / "test_bridge3b_parent_curriculum.py"
        ).read_text(encoding="utf-8")
        ci_src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        required = ["cross", "neutral", "anonymous", "mastery"]
        check(
            "13. negative cases on the CI manifest (cross / neutral / anon / mastery)",
            "test_bridge3b_parent_curriculum.py" in ci_src
            and all(k in test_src for k in required),
            "ci.yml phase2-tests + four named cases",
        )

        # ── 7. eight weeks done -> completed, then 409 ────────────────────
        for _ in range(6):  # 2 advances already done -> the 8th completes it
            resp = await teacher.post(
                f"/api/classes/{class_id}/advance-week", headers=HEADERS
            )
            assert resp.status_code == 200, await _text(resp)
        code_d, done, raw_d = await _map(parent, kid_id[:8])
        over = await teacher.post(
            f"/api/classes/{class_id}/advance-week", headers=HEADERS
        )
        check(
            "7. course completed -> state=completed, week 8 completed; 9th advance 409",
            code_d == 200
            and done["state"] == "completed"
            and done["current_week"] == 8
            and done["total_weeks"] == 8
            and set(_statuses(done)) == {"completed"}
            and done["weeks"][1]["mastery_pct"] == 0.75
            and over.status_code == 409,
            f"{json.dumps(done, ensure_ascii=False)[:160]} | advance={await _text(over)}",
        )

        # ── 14. frontend renders the backend string verbatim ───────────────
        weekmap = (
            REPO_ROOT / "frontend" / "src" / "components" / "parent" / "WeekMap.tsx"
        ).read_text(encoding="utf-8")
        dash = (REPO_ROOT / "frontend" / "src" / "pages" / "ParentDashboard.tsx").read_text(
            encoding="utf-8"
        )
        i18n_src = (REPO_ROOT / "frontend" / "src" / "lib" / "i18n.tsx").read_text(
            encoding="utf-8"
        )
        types_src = (REPO_ROOT / "frontend" / "src" / "lib" / "types.ts").read_text(
            encoding="utf-8"
        )
        api_src = (REPO_ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(
            encoding="utf-8"
        )
        # Comments explain that topic_id never reaches the frontend — only real
        # code lines are checked for the forbidden identifier.
        map_code = "\n".join(
            line for line in weekmap.splitlines() if not line.strip().startswith("//")
        )
        check(
            "14. frontend: server title verbatim, null-safe, 3 languages, wired",
            all(k in i18n_src for k in ("en:", "hk:", "cn:"))
            and i18n_src.count("weekMapNoData") == 4  # interface + 3 languages
            and "selectedWeek.title" in map_code
            and "selectedWeek.mastery_pct === null" in map_code
            and "<MasteryBar" in map_code
            and "topic_id" not in map_code
            and "ParentCurriculumResponse" in types_src
            and "/api/parent/curriculum" in api_src
            and "WeekMap" in dash,
            "grid colours 3-state; the frame is localized, the week string is backend-owned",
        )

        # ── 15. audit sink isolation ───────────────────────────────────────
        sink_before = len(_audit_events())
        await parent.get(f"{MAP_URL}?student_id={kid_id[:8]}", headers=HEADERS)
        sink_after = len(_audit_events())
        repo_audit_after = REPO_ROOT / "audit_log.jsonl"
        check(
            "15. audit sink isolation: repo audit_log.jsonl untouched; a plain "
            "parent read writes nothing to the sink",
            repo_audit_after.exists() == repo_audit_before
            and sink_after == sink_before,
            f"trial sink events={sink_after} (no new line on read); "
            f"repo file exists={repo_audit_after.exists()}",
        )
    finally:
        for c in (teacher, teacher_b, parent, parent_b, anon):
            await c.aclose()
        await runner.cleanup()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    failed = [name for name, ok, _ in CHECKS if not ok]
    print("\n" + "=" * 68)
    print(f"  {passed}/{len(CHECKS)} checks passed")
    if failed:
        print("  FAILED: " + "; ".join(failed))
    print("=" * 68)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
