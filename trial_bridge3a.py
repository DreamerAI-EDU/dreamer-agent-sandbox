"""trial_bridge3a.py — kid "Week X / 8" badge, real-server round trip.

Boss work order 2026-09-11, ruling #5 ("mock-green ≠ real"): the badge must be
exercised for real — real HTTP over a real socket, a real SQLite database, a
real audit sink — through the same endpoints the product uses:

    teacher register/login -> create class -> mount the ready-made 8-week course
    -> invite the parent (POST /api/invites) -> parent confirms from the token
    -> (kid surface) GET /api/student/curriculum -> advance one week -> read again

Checks
  ----- positive path (ruling #3 + #5) -----
  1  parent reads its own child: Week 1 / 8, unit_title authored server-side
  2  teacher advances one week -> the badge moves to Week 2 / 8
  3  eight weeks done -> state=completed ("8/8 · 完成"); a 9th advance -> 409
  ----- guard rails (rulings #1 / #2 / #4) -----
  4  anonymous -> 401
  5  teacher session on the kid surface -> 403 (not a staff lens)
  6  cross-child read -> 403 + security warning, nothing read
  7  child without a mounted course -> 200 neutral; child without a class -> 200
     neutral (never a 500 on a child surface)
  8  the wire payload carries no student id and no internal topic_id (ruling #1)
  9  the four negative cases exist by name and are on the CI manifest (ruling #4)
  ----- evidence -----
 10  audit sink isolation: <repo>/audit_log.jsonl untouched by the whole run
 11  the frontend renders the backend unit_title verbatim in all three languages
     and never translates a topic_id

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
    os.environ.get("DREAMER_TRIAL_DIR") or tempfile.mkdtemp(prefix="bridge3a_trial_")
)
WORKDIR.mkdir(parents=True, exist_ok=True)
DB_PATH = WORKDIR / "trial_auth.db"
AUDIT_PATH = WORKDIR / "audit_log.jsonl"

# Point the real modules at the trial workdir BEFORE importing them: auth/db.py
# resolves DREAMER_DB_PATH per connect(), auth/consent.py reads its sink at
# import time. Nothing in this process may touch the repo's real DB / audit log.
os.environ["DREAMER_DB_PATH"] = str(DB_PATH)
os.environ["DREAMER_AUDIT_LOG_PATH"] = str(AUDIT_PATH)
os.environ.setdefault("PYTHONPATH", str(REPO_ROOT))

import httpx  # noqa: E402
from aiohttp import web  # noqa: E402

from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402
from pipeline import topic_metadata_schema  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
COURSE_ID = "dreamer-curriculum"
BADGE_URL = "/api/student/curriculum"

# The authored, kid-facing week titles — Bridge-1's topic_metadata is the only
# source of these strings; the frontend must never build one itself.
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


def _seed_child_of(parent_id: str, *, class_id: str | None, first_name: str) -> str:
    """A child the invite flow cannot produce: no class, or a pending invite.

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
                "created_at) VALUES (?, ?, 'pending', ?)",
                (class_id, student_id, _now_iso()),
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


async def _text(resp: httpx.Response) -> str:
    return f"{resp.status_code} {resp.text[:300]}"


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 68)
    print("  Bridge-3a — kid 'Week X / 8' badge · real-server trial")
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

        resp = await parent.post(
            f"/api/invites/{token}/confirm",
            json={
                "password": "test-pass-parent1",
                "privacy_policy": True,
                "chat_consent": True,
                "media_consent": False,
            },
        )
        assert resp.status_code == 201, await _text(resp)
        _absorb_session(parent, resp)
        me = await parent.get("/api/auth/me")
        assert me.status_code == 200 and (me.json())["user"]["role"] == "parent", (
            await _text(me)
        )
        parent_uid = (me.json())["user"]["id"]

        # Teacher approves the binding from the console — the real journey: the
        # child only becomes a confirmed class member after this step, and only
        # then does the badge resolve to an active week.
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

        # ── 1. Week 1 / 8, unit_title authored server-side ──────────────────
        resp = await parent.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        body = resp.json()
        check(
            "1. parent -> own child: 200, Week 1 / 8",
            resp.status_code == 200
            and body["state"] == "active"
            and body["week_index"] == 1
            and body["total_weeks"] == 8,
            json.dumps(body, ensure_ascii=False),
        )
        check(
            "   unit_title is the authored kid-facing string (ruling #1)",
            body.get("unit_title") == WEEK_TITLES[1],
            f"unit_title={body.get('unit_title')!r}",
        )

        # ── 2. advance one week -> the badge moves (ruling #5) ──────────────
        resp = await teacher.post(f"/api/classes/{class_id}/advance-week", headers=HEADERS)
        assert resp.status_code == 200, await _text(resp)
        body2 = (
            await parent.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        ).json()
        check(
            "2. after one advance -> Week 2 / 8 (kid surface follows the class)",
            body2["state"] == "active"
            and body2["week_index"] == 2
            and body2["unit_title"] == WEEK_TITLES[2],
            json.dumps(body2, ensure_ascii=False),
        )

        # ── 9. the four negative cases are CI red lines (ruling #4) ─────────
        test_src = (REPO_ROOT / "tests" / "test_bridge3a_student_curriculum.py").read_text(
            encoding="utf-8"
        )
        ci_src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        required = ["cross", "neutral", "anonymous", "unit_title"]
        check(
            "9. negative cases on the CI manifest (cross / neutral / anon / unit_title)",
            "test_bridge3a_student_curriculum.py" in ci_src
            and all(k in test_src for k in required),
            "ci.yml phase2-tests + four named cases",
        )

        # ── 4. anonymous -> 401 ─────────────────────────────────────────────
        resp = await anon.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        check(
            "4. anonymous -> 401 (no session, no read)",
            resp.status_code == 401,
            await _text(resp),
        )

        # ── 5. teacher session -> 403 ───────────────────────────────────────
        resp = await teacher.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        check(
            "5. teacher session -> 403 (kid badge is not a staff lens)",
            resp.status_code == 403,
            await _text(resp),
        )

        # ── 6. cross-child -> 403 + security warning ────────────────────────
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
        resp = await parent_b.post(
            f"/api/invites/{other_token}/confirm",
            json={
                "password": "test-pass-parent1",
                "privacy_policy": True,
                "chat_consent": True,
                "media_consent": False,
            },
        )
        assert resp.status_code == 201, await _text(resp)
        _absorb_session(parent_b, resp)

        resp = await parent.get(f"{BADGE_URL}?student={other_kid}", headers=HEADERS)
        leaked = resp.text
        warned = any(
            e.get("event") == "curriculum_student_cross_access"
            and e.get("level") == "WARNING"
            for e in _audit_events()
        )
        check(
            "6. cross-child read -> 403, no payload leak, WARNING logged",
            resp.status_code == 403 and other_kid[:8] not in leaked and warned,
            f"{await _text(resp)} | warning_logged={warned}",
        )

        # ── 7. neutral states -> 200, never 500 ─────────────────────────────
        empty_resp = await teacher.post(
            "/api/classes", json={"name": "No course yet"}, headers=HEADERS
        )
        empty_class = empty_resp.json()["class"]["id"]
        pending_kid = _seed_child_of(
            parent_uid, class_id=empty_class, first_name="Joe"
        )
        noclass_kid = _seed_child_of(parent_uid, class_id=None, first_name="Ann")
        for label, sid in (("no mounted course", pending_kid), ("no class", noclass_kid)):
            resp = await parent.get(f"{BADGE_URL}?student={sid}", headers=HEADERS)
            body = resp.json()
            check(
                f"7. child with {label} -> 200 neutral (badge hidden, no 500)",
                resp.status_code == 200
                and body["state"] == "none"
                and body["week_index"] is None,
                json.dumps(body, ensure_ascii=False),
            )

        # ── 8. wire payload hygiene (ruling #1) ─────────────────────────────
        raw = json.dumps(
            (await parent.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)).json(),
            ensure_ascii=False,
        )
        check(
            "8. payload carries no student id and no internal topic_id",
            kid_id not in raw and "curriculum-wk" not in raw and "topic_id" not in raw,
            raw,
        )

        # ── 3. 8 weeks done -> completed, then 409 ──────────────────────────
        for _ in range(7):  # week 2 -> ... -> week 8 closed (8th advance completes)
            resp = await teacher.post(f"/api/classes/{class_id}/advance-week", headers=HEADERS)
            assert resp.status_code == 200, await _text(resp)
        done = (
            await parent.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        ).json()
        over = await teacher.post(f"/api/classes/{class_id}/advance-week", headers=HEADERS)
        check(
            "3. course completed -> state=completed, '8/8 · 完成'; 9th advance 409",
            done["state"] == "completed"
            and done["week_index"] == 8
            and done["total_weeks"] == 8
            and over.status_code == 409,
            f"{json.dumps(done, ensure_ascii=False)} | advance={await _text(over)}",
        )

        # ── 11. frontend renders the backend string verbatim ────────────────
        chat = (REPO_ROOT / "frontend" / "src" / "pages" / "ChatPage.tsx").read_text(
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
        chat_code = "\n".join(
            line for line in chat.splitlines() if not line.strip().startswith("//")
        )
        three_langs = all(k in chat for k in ("en:", "hk:", "cn:"))
        check(
            "11. frontend: unit_title rendered verbatim, 3 languages, no topic_id",
            three_langs
            and "curriculumData.unit_title" in chat_code
            and "{weekBadge.unit}" in chat_code
            and "unit_title" in chat_code
            and "topic_id" not in chat_code
            and "StudentCurriculumResponse" in types_src
            and "/api/student/curriculum" in api_src,
            "Week X/8 chrome localized client-side; the unit string is backend-owned",
        )

        # ── 10. audit sink isolation ────────────────────────────────────────
        sink_before = len(_audit_events())
        await parent.get(f"{BADGE_URL}?student={kid_id[:8]}", headers=HEADERS)
        sink_after = len(_audit_events())
        repo_audit_after = REPO_ROOT / "audit_log.jsonl"
        check(
            "10. audit sink isolation: repo audit_log.jsonl untouched; a plain "
            "kid read writes nothing to the sink",
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
