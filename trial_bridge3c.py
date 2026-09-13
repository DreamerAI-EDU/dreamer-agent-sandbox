"""trial_bridge3c.py — teacher console course flow, real-server round trip.

Boss work order 2026-09-12 (3c, 3-4 days, "the big one") + ruling #5
("mock-green != real"): the console controls must be exercised for real — real
HTTP over a real socket, a real SQLite database, the real assessment writer, a
real audit sink — through the same endpoints the product uses.

Scope of THIS trial (PR A: 開班 + 揀課 + 進度 read; the 邀請 control is PR B and
rides on the 3b-proven invite flow, exercised here only to build a real roster):

    teacher register/login -> 開班 POST /api/classes (name/class_type/grade_band)
    -> 揀課 GET /api/curriculum/catalog -> POST /api/classes/{id}/curriculum
    -> 邀請 the existing parent invite flow (reused, never rewritten)
    -> 進度 GET /api/classes/{id}/curriculum -> POST .../advance-week -> flip

Checks
  ----- the controls (spec: UI renders, server computes) -----
  1  開班: 201, the form's name/class_type/grade_band round-trip onto the class
  2  揀課: catalog lists only READY 1..8 courses and carries curriculum_id
  3  揀課: the client posts ONE value (curriculum_id) and the server expands
     the eight rows itself — no topic picking, no week maths client-side
  4  進度 before mounting: a neutral 200 empty grid, never a 500
  5  進度: Week 1 / 8 with eight cells, authored titles verbatim, server-owned
     statuses, mastery null everywhere (never an invented 0%)
  5b 邀請 stays the reused flow (invite -> PIN login), not a rewrite
  6  進度: the class average comes from the REAL writer over CONFIRMED members
     (0.5 + 1.0 -> 0.75); a pending member never counts; a stored 0.0 survives
  7  進度: 下一週 flips the grid (completed / active / locked) and the read
     follows; the week's class average survives the advance
  8  進度: eight weeks done -> state=completed, week 8 completed; 9th refused
  ----- guard rails (spec: the controls are teacher/admin only) -----
  9  anonymous -> 401 on catalog / mount / read / advance
 10  parent session -> 403 on all four, nothing leaked
 11  another teacher's class -> 403 + WARNING, and an unknown id answers with
     the SAME body (no existence oracle)
 12  payload hygiene: no student id, no parent id, no db path on the wire;
     topic_id rides along RAW (never translated) for teaching-side use
 13  the negative cases exist by name and are on the CI manifest
 14  frontend: the 3c keys exist in all three dictionaries, the flow posts
     only curriculum_id, the chip renders the SERVER state, no week maths
  ----- evidence -----
 15  audit sink isolation: <repo>/audit_log.jsonl untouched by the whole run;
     a plain console read writes no audit line

FLAGGED to the boss in the delivery report (not silently changed):
  * the console shell is pinned to English (copyEn, W3-C policy); the 3c keys
    are nevertheless registered in all three dictionaries, so language
    switching is free the day the console goes trilingual;
  * this read lens admits teacher AND admin (matching the catalog), while the
    bridge-2 WRITE guards (mount / advance-week) are still teacher-only.

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
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

WORKDIR = Path(
    os.environ.get("DREAMER_TRIAL_DIR") or tempfile.mkdtemp(prefix="bridge3c_trial_")
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
from pipeline import topic_metadata_schema  # noqa: E402
from agents.assessment_agent import AssessmentAgent  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
COURSE_ID = "dreamer-curriculum"
TOTAL_WEEKS = 8

# The authored, teacher-facing week titles — Bridge-1's topic_metadata is the
# only source of these strings; the console must never build or translate one.
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
    """The ready-made 8-week course, plus a half-authored one the catalog hides."""
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
        # ready=False (weeks 1..3 only) -> the catalog must hide it.
        for week in (1, 2, 3):
            conn.execute(
                "INSERT INTO topic_metadata (topic_id, subject, topic, "
                "modes_allowed, grade_level, week, dreamer_phase, kb_name, "
                "document_path, document_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"halfbaked-wk{week:02d}",
                    "Half Baked",
                    f"Half-baked week {week}",
                    '["contextual"]',
                    "P4-P6",
                    week,
                    '["Design"]',
                    "half-baked-course",
                    f"halfbaked-wk{week:02d}.md",
                    f"hash-h{week}",
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
    class_id: str,
    first_name: str,
    status: str,
) -> str:
    """A class member in a state the invite flow cannot produce directly."""
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


def _audit_events() -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    return [
        json.loads(line)
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _warned(event: str) -> bool:
    return any(
        e.get("event") == event and e.get("level") == "WARNING"
        for e in _audit_events()
    )


def _archive_previous_run() -> None:
    """Keep the previous run's evidence instead of destroying it.

    The trial owns its workdir; a re-run moves the old DB / sink aside under a
    timestamp rather than deleting anything, so a failing run stays auditable.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path in (DB_PATH, AUDIT_PATH):
        if path.exists():
            os.replace(str(path), f"{path}.prev-{stamp}")


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


async def _text(resp: httpx.Response) -> str:
    return f"{resp.status_code} {resp.text[:300]}"


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


async def _json_or_empty(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:  # pragma: no cover — non-JSON error body
        return {}


async def _read(client: httpx.AsyncClient, class_id: str) -> tuple[int, dict, str]:
    resp = await client.get(f"/api/classes/{class_id}/curriculum", headers=HEADERS)
    return resp.status_code, await _json_or_empty(resp), resp.text


async def _mount(client: httpx.AsyncClient, class_id: str, payload: dict):
    return await client.post(
        f"/api/classes/{class_id}/curriculum", json=payload, headers=HEADERS
    )


async def _advance(client: httpx.AsyncClient, class_id: str) -> httpx.Response:
    return await client.post(f"/api/classes/{class_id}/advance-week", headers=HEADERS)


def _statuses(body: dict) -> list[str]:
    return [str(w["status"]) for w in body.get("weeks", [])]


def _titles(body: dict) -> list[str]:
    return [str(w["title"]) for w in body.get("weeks", [])]


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 68)
    print("  Bridge-3c — teacher console course flow · real-server trial")
    print("=" * 68)
    print(f"  workdir : {WORKDIR}")
    print(f"  db      : {DB_PATH}")
    print(f"  audit   : {AUDIT_PATH}")

    repo_audit = REPO_ROOT / "audit_log.jsonl"
    repo_audit_before = repo_audit.exists()

    _archive_previous_run()

    _seed_schema()
    _seed_course()
    auth_db.insert_teacher_invite(
        code="trial-invite-001", created_by="trial", expires_at=_future_iso(days=1)
    )
    auth_db.insert_teacher_invite(
        code="trial-invite-002", created_by="trial", expires_at=_future_iso(days=1)
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
    teacher_b = _client(base_url)
    parent = _client(base_url)
    anon = _client(base_url)

    try:
        await _register_teacher(
            teacher, "trial-teacher@dreamer.local", "trial-invite-001"
        )
        await _login(teacher, "trial-teacher@dreamer.local", "test-pass-teacher1")

        # ── 1. 開班 — the form's three fields round-trip ────────────────────
        resp = await teacher.post(
            "/api/classes",
            json={"name": "Trial P4 AI", "class_type": "monthly", "grade_band": "P4-P6"},
            headers=HEADERS,
        )
        assert resp.status_code == 201, await _text(resp)
        cls = resp.json()["class"]
        class_id = cls["id"]
        print(f"  class   : {class_id}")
        check(
            "1. 開班: 201 and the form fields land on the class "
            "(name / class_type / grade_band)",
            cls.get("name") == "Trial P4 AI"
            and cls.get("class_type") == "monthly"
            and cls.get("grade_band") == "P4-P6",
            json.dumps(cls, ensure_ascii=False)[:200],
        )

        # ── 4. 進度 before mounting: neutral, never a 500 ──────────────────
        code_pre, pre, raw_pre = await _read(teacher, class_id)
        check(
            "4. 進度 before 揀課: neutral 200 with an EMPTY grid (never a 500)",
            code_pre == 200
            and pre.get("state") == "none"
            and pre.get("weeks") == []
            and pre.get("current_week") is None
            and pre.get("total_weeks") == TOTAL_WEEKS,
            raw_pre[:160],
        )

        # ── 2. 揀課 — the catalog the dropdown renders ─────────────────────
        resp = await teacher.get("/api/curriculum/catalog", headers=HEADERS)
        assert resp.status_code == 200, await _text(resp)
        catalog = resp.json()["curricula"]
        ids = [c["curriculum_id"] for c in catalog]
        check(
            "2. 揀課: catalog lists only READY 1..8 courses, each with curriculum_id",
            COURSE_ID in ids
            and "half-baked-course" not in ids
            and all(c["ready"] and c["week_count"] == TOTAL_WEEKS for c in catalog)
            and all(c.get("title") for c in catalog),
            f"ids={ids} | week_counts={[c['week_count'] for c in catalog]}",
        )

        # ── 3. mount: one value in, eight server-expanded rows out ─────────
        client_payload = {"curriculum_id": COURSE_ID}  # exactly what the UI posts
        resp = await _mount(teacher, class_id, client_payload)
        assert resp.status_code == 201, await _text(resp)
        mounted = resp.json()
        extra = await _mount(teacher, class_id, {**client_payload, "weeks": [1, 2, 3]})
        check(
            "3. 揀課: the client posts ONE value; the server expands the eight rows "
            "(and refuses free topic picking)",
            mounted.get("week_count") == TOTAL_WEEKS
            and len(_week_topic_ids(class_id)) == TOTAL_WEEKS
            and extra.status_code == 400,
            f"week_count={mounted.get('week_count')} | extra-key body -> "
            f"{await _text(extra)}",
        )
        topic_ids = _week_topic_ids(class_id)

        # ── 5. 進度 — Week 1 / 8 with authored strings verbatim ────────────
        code, body, raw = await _read(teacher, class_id)
        titles_verbatim = _titles(body) == [WEEK_TITLES[n] for n in range(1, 9)]
        check(
            "5. 進度: Week 1 / 8, eight cells, authored titles verbatim, "
            "server statuses, mastery null (never 0%)",
            code == 200
            and body.get("state") == "active"
            and body.get("current_week") == 1
            and body.get("total_weeks") == TOTAL_WEEKS
            and body.get("mastery_scope") == "class"
            and body.get("course_title") == "AI Literacy"
            and len(body.get("weeks", [])) == TOTAL_WEEKS
            and _statuses(body)[0] == "active"
            and set(_statuses(body)[1:]) == {"locked"}
            and titles_verbatim
            and all(w["mastery_pct"] is None for w in body["weeks"]),
            f"{code} | titles_verbatim={titles_verbatim}",
        )

        # ── Roster: the 邀請 control stays the 3b-proven flow ──────────────
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
        await _confirm_parent(parent, token)
        me = await parent.get("/api/auth/me")
        assert me.status_code == 200, await _text(me)
        parent_uid = me.json()["user"]["id"]
        resp = await teacher.post(
            f"/api/classes/{class_id}/confirm",
            json={"student_id": kid_id},
            headers=HEADERS,
        )
        assert resp.status_code == 200, await _text(resp)
        # The 邀請 leg stays the 3b flow, not a rewrite: parent confirm ->
        # teacher confirm -> the kid's PIN is checked on the parent session
        # (the same route the parent console calls), wrong PIN stays 401.
        pin_ok = await parent.post(
            f"/api/students/{kid_id[:8]}/pin-verify",
            json={"pin": "2468"},
            headers=HEADERS,
        )
        pin_bad = await parent.post(
            f"/api/students/{kid_id[:8]}/pin-verify",
            json={"pin": "0000"},
            headers=HEADERS,
        )
        check(
            "5b. 邀請 (reused 3b flow, not rewritten): invite -> parent confirm "
            "-> teacher confirm -> PIN verify 200, wrong PIN 401",
            pin_ok.status_code == 200
            and pin_ok.json().get("ok") is True
            and pin_bad.status_code == 401,
            f"verify={await _text(pin_ok)} wrong={await _text(pin_bad)}",
        )

        # ── 6. the class average, written by the real writer ──────────────
        agent = AssessmentAgent()

        async def _track(student_id: str, topic_id: str, label: str, tag: str) -> dict:
            return await agent.progress_track(
                {
                    "student_id": student_id,
                    "session_id": f"trial-3c-{tag}",
                    "topic_id": topic_id,
                    "mode": "DIRECT",
                    "lang_code": "zh-hk",
                    "internal_label": label,
                    "confidence": 0.9,
                    "rubric_id": "trial-rubric",
                    "evidence_text": f"trial: {tag}",
                    "agent_used": "assessment",
                    "cost_tokens": 0,
                    "age_band": "P4-P6",
                }
            )

        write_a = await _track(kid_id, topic_ids[1], "developing", "member-a")
        ben = _seed_child_of(
            parent_uid, class_id=class_id, first_name="Ben", status="confirmed"
        )
        write_b = await _track(ben, topic_ids[1], "exemplary", "member-b")
        cher = _seed_child_of(
            parent_uid, class_id=class_id, first_name="Cher", status="pending"
        )
        await _track(cher, topic_ids[2], "ungraded", "pending-zero")
        await _track(kid_id, topic_ids[3], "ungraded", "stored-zero")
        # The expected average is derived from the two rows the real writer
        # just stored — the trial asserts the class average IS the mean over
        # confirmed members, instead of hard-coding the rubric's label scores.
        with _conn() as conn:
            stored = {
                (r["student_id"], r["topic_id"]): r["mastery_pct"]
                for r in conn.execute(
                    "SELECT student_id, topic_id, mastery_pct FROM progress_snapshots"
                )
            }
        a_val = stored[(kid_id, topic_ids[1])]
        b_val = stored[(ben, topic_ids[1])]
        expected = round((a_val + b_val) / 2, 4)
        _, body_m, _ = await _read(teacher, class_id)
        mastery = {w["week_no"]: w["mastery_pct"] for w in body_m["weeks"]}
        check(
            "6. 進度: real writer over CONFIRMED members -> class average is the "
            "mean of their stored scores; pending never counts; a stored 0.0 "
            "stays 0.0; no data stays null",
            write_a.get("status") == "ok"
            and write_b.get("status") == "ok"
            and a_val != b_val
            and mastery[1] == expected
            and mastery[2] is None
            and mastery[3] == 0.0
            and mastery[4] is None,
            "mastery=" + json.dumps([mastery[n] for n in range(1, 9)])
            + f" | member_a={a_val} member_b={b_val} expected={expected}",
        )

        # ── 7. 下一週 flips the grid; the class average survives ──────────
        assert (await _advance(teacher, class_id)).status_code == 200
        _, body_adv, _ = await _read(teacher, class_id)
        check(
            "7. 下一週: the grid flips (completed / active / locked) and the "
            "week's class average survives the advance",
            body_adv.get("state") == "active"
            and body_adv.get("current_week") == 2
            and _statuses(body_adv)[:3] == ["completed", "active", "locked"]
            and body_adv["weeks"][0]["mastery_pct"] == expected,
            "statuses=" + json.dumps(_statuses(body_adv)[:3])
            + f" week1_mastery={body_adv['weeks'][0]['mastery_pct']}",
        )

        # ── 8. eight weeks -> completed; the 9th is refused ───────────────
        for _ in range(7):  # one advance already done -> week 8 completes it
            resp = await _advance(teacher, class_id)
            assert resp.status_code == 200, await _text(resp)
        _, body_done, raw_done = await _read(teacher, class_id)
        over = await _advance(teacher, class_id)
        check(
            "8. 進度: course completed -> state=completed, week 8 completed; "
            "9th advance refused",
            body_done.get("state") == "completed"
            and body_done.get("current_week") == TOTAL_WEEKS
            and set(_statuses(body_done)) == {"completed"}
            and over.status_code in (409, 400),
            f"{raw_done[:140]} | advance={await _text(over)}",
        )

        # ── 9/10/11. guard rails on all four endpoints ────────────────────
        anon_read = await anon.get(f"/api/classes/{class_id}/curriculum", headers=HEADERS)
        anon_catalog = await anon.get("/api/curriculum/catalog", headers=HEADERS)
        anon_mount = await _mount(anon, class_id, client_payload)
        anon_advance = await _advance(anon, class_id)
        check(
            "9. anonymous -> 401 on catalog / mount / read / advance",
            anon_read.status_code == 401
            and anon_catalog.status_code == 401
            and anon_mount.status_code == 401
            and anon_advance.status_code == 401,
            f"read={anon_read.status_code} catalog={anon_catalog.status_code} "
            f"mount={anon_mount.status_code} advance={anon_advance.status_code}",
        )

        p_read = await parent.get(f"/api/classes/{class_id}/curriculum", headers=HEADERS)
        p_catalog = await parent.get("/api/curriculum/catalog", headers=HEADERS)
        p_mount = await _mount(parent, class_id, client_payload)
        p_advance = await _advance(parent, class_id)
        p_raw = p_read.text
        check(
            "10. parent session -> 403 on all four controls, nothing leaked",
            p_read.status_code == 403
            and p_catalog.status_code == 403
            and p_mount.status_code == 403
            and p_advance.status_code == 403
            and WEEK_TITLES[1] not in p_raw
            and kid_id not in p_raw,
            f"read={p_read.status_code} catalog={p_catalog.status_code} "
            f"mount={p_mount.status_code} advance={p_advance.status_code}",
        )

        await _register_teacher(
            teacher_b, "trial-teacher-b@dreamer.local", "trial-invite-002"
        )
        await _login(teacher_b, "trial-teacher-b@dreamer.local", "test-pass-teacher1")
        x_read = await teacher_b.get(
            f"/api/classes/{class_id}/curriculum", headers=HEADERS
        )
        unknown = await teacher_b.get(
            f"/api/classes/{uuid.uuid4().hex}/curriculum", headers=HEADERS
        )
        x_advance = await _advance(teacher_b, class_id)
        cross_warned = _warned("curriculum_cross_teacher")
        check(
            "11. another teacher -> 403 + WARNING on read and advance; an unknown "
            "id answers with the SAME body (no existence oracle)",
            x_read.status_code == 403
            and x_advance.status_code == 403
            and unknown.status_code == 403
            and x_read.text == unknown.text
            and cross_warned,
            f"read={x_read.status_code} advance={x_advance.status_code} "
            f"unknown={unknown.status_code} warning={cross_warned}",
        )

        # ── 12. wire hygiene ──────────────────────────────────────────────
        _, _, raw_now = await _read(teacher, class_id)
        check(
            "12. payload hygiene: no student id, no parent id, no db path; "
            "topic_id rides along RAW for teaching-side use",
            kid_id not in raw_now
            and ben not in raw_now
            and parent_uid not in raw_now
            and str(DB_PATH) not in raw_now
            and "progress_snapshots" not in raw_now
            and topic_ids[1] in raw_now,
            raw_now[:150],
        )

        # ── 13. the negative cases are CI red lines ───────────────────────
        test_src = (
            REPO_ROOT / "tests" / "test_bridge3c_class_curriculum.py"
        ).read_text(encoding="utf-8")
        ci_src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        required = [
            "anonymous_is_401",
            "non_staff_is_403",
            "cross_teacher_is_403_and_warns",
            "mastery_is_the_class_average",
        ]
        check(
            "13. the negative cases exist by name and are on the CI manifest",
            "test_bridge3c_class_curriculum.py" in ci_src
            and all(k in test_src for k in required),
            "ci.yml phase2-tests + four named cases",
        )

        # ── 14. frontend: render-only, i18n, wired ────────────────────────
        def _src(*parts: str) -> str:
            return (REPO_ROOT.joinpath("frontend", "src", *parts)).read_text(
                encoding="utf-8"
            )

        i18n_src = _src("lib", "i18n.tsx")
        types_src = _src("lib", "types.ts")
        api_src = _src("lib", "api.ts")
        flow_src = _src("components", "teacher", "OpenClassFlow.tsx")
        list_src = _src("components", "teacher", "ClassListView.tsx")
        # Comments explain why the console computes nothing — only real code
        # lines are checked for forbidden week arithmetic.
        code_lines = "\n".join(
            line
            for line in (flow_src + "\n" + list_src).splitlines()
            if not line.strip().startswith(("//", "*", "/*"))
        )
        keys_three_dicts = all(
            i18n_src.count(key) == 4  # interface + en + hk + cn
            for key in (
                "newClassBtn",
                "courseChipNone",
                "mountTitle",
                "courseProgressNextWeek",
                "closeBtn",
            )
        )
        check(
            "14. frontend: the 3c keys exist in all three dictionaries, the flow "
            "posts only curriculum_id, the chip renders the SERVER state, no "
            "week maths in the console",
            keys_three_dicts
            and "curriculum_id: curriculumId" in api_src
            and "mountCurriculum" in api_src
            and "curriculumCatalog" in api_src
            and "classCurriculum" in api_src
            and "createClass" in api_src
            and "ClassCurriculumResponse" in types_src
            and "CreateClassResponse" in types_src
            and "api.mountCurriculum" in flow_src
            and "api.curriculumCatalog" in flow_src
            and "api.createClass" in flow_src
            and "course.state === 'none'" in list_src
            and "current_week +" not in code_lines
            and "week_no" not in code_lines
            and "topic_id" not in code_lines,
            f"keys_three_dicts={keys_three_dicts} | chip=courseChipText(server state)",
        )

        # ── 15. audit sink isolation ──────────────────────────────────────
        sink_before = len(_audit_events())
        await teacher.get(f"/api/classes/{class_id}/curriculum", headers=HEADERS)
        sink_after = len(_audit_events())
        repo_audit_after = REPO_ROOT / "audit_log.jsonl"
        check(
            "15. audit sink isolation: repo audit_log.jsonl untouched; a plain "
            "console read writes nothing to the sink",
            repo_audit_after.exists() == repo_audit_before
            and sink_after == sink_before,
            f"trial sink events={sink_after} (no new line on read); "
            f"repo file exists={repo_audit_after.exists()}",
        )
    finally:
        for c in (teacher, teacher_b, parent, anon):
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
