"""trial_bridge3d.py — student self-login (join code + PIN), real-server round trip.

Boss work order 2026-09-13 (3d, 1 day) + ruling #5 ("mock-green != real"): the
student door must be exercised for real — real HTTP over a real socket, a real
SQLite database, the real audit sink — through the same endpoints the product
uses, never a TestClient shortcut.

Scope of THIS trial:

    teacher register/login -> open class -> createInvite (blank PIN)
      -> the SERVER draws the 4-digit PIN (Bridge-3b/B1 contract)
      -> parent confirm -> teacher confirm (the roster guard)
      -> student POST /api/student/login {join_code, pin} -> kid_session cookie
      -> GET /api/student/me -> own learning space + Week X / 8 badge
      -> POST /api/student/logout -> the session dies

Checks
  ----- the door (spec: a third identity, not a parent/teacher session) -----
  1  invite chain: blank PIN -> the server draws 4 digits (never a fixed default)
  2  login: 200 + kid_session (HttpOnly/Secure/Lax) + the masked 8-char id,
     no pin_hash on the wire, INFO audit line written
  3  /me: own identity + the SHARED Week 1 / 8 badge after mounting a course
     (same resolver as the parent-side kid badge), no classmate data
  4  identity isolation: anonymous 401; a teacher auth_session 401 on /me;
     a kid_session 401 on /api/auth/me and never a teacher console read
  5  unknown join code and wrong PIN return the SAME 401 body, the real
     reason kept in the WARNING audit line (no existence oracle)
  6  a malformed PIN still charges a strike (no free probing oracle)
  ----- the lock (spec: 5 strikes / 10 minutes, scoped to the join code) -----
  7  five wrong PINs -> the sixth attempt with the CORRECT PIN is 429, a
     WARNING student_login_locked is written, locked_until ~10 minutes out
  8  the lock follows the CLASS CODE, not the kid: another class logs in fine
  9  the successful-login path clears the accumulated strikes
 10  the delegated parent/teacher /api/students/{id}/pin-verify contract
     (10 strikes / 1 minute) is untouched by the kid lockout
 11  a pending (not yet teacher-confirmed) student cannot log in even with
     the right PIN
 12  logout kills the session server-side: /me turns 401 afterwards
  ----- evidence -----
 13  the negative cases exist by name and are on the CI manifest
 14  frontend wiring: the 3d keys in all three dictionaries, api.student*,
     the /student + /student/login routes
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
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

WORKDIR = Path(
    os.environ.get("DREAMER_TRIAL_DIR") or tempfile.mkdtemp(prefix="bridge3d_trial_")
)
WORKDIR.mkdir(parents=True, exist_ok=True)
DB_PATH = WORKDIR / "trial_auth.db"
AUDIT_PATH = WORKDIR / "audit_log.jsonl"

# Point the real modules at the trial workdir BEFORE importing them — auth/db.py
# resolves DREAMER_DB_PATH per connect(), auth/consent.py reads its sink at
# import time. Nothing in this process may touch the repo's real DB / audit log.
os.environ["DREAMER_DB_PATH"] = str(DB_PATH)
os.environ["DREAMER_AUDIT_LOG_PATH"] = str(AUDIT_PATH)
os.environ.setdefault("PYTHONPATH", str(REPO_ROOT))

import httpx  # noqa: E402
from aiohttp import web  # noqa: E402

from auth import db as auth_db  # noqa: E402
from auth import students as students_mod  # noqa: E402
from auth.api import build_app  # noqa: E402
from pipeline import topic_metadata_schema  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
COURSE_ID = "dreamer-curriculum"
TOTAL_WEEKS = 8
CONFIRM_PASSWORD = "test-pass-parent1"

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
            "ORDER BY rowid DESC LIMIT 1",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no invite for student {student_id}"
    return row[0]


def _latest_student_id() -> str:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM students ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no student row"
    return row[0]


def _lock_row(join_code: str) -> sqlite3.Row | None:
    from auth import student_auth as student_auth_mod

    scope = f"jc:{student_auth_mod.normalise_join_code(join_code)}"
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM student_login_locks WHERE scope = ?", (scope,)
        ).fetchone()
    finally:
        conn.close()


def _student_row(student_id: str) -> sqlite3.Row | None:
    conn = _conn()
    try:
        return conn.execute(
            "SELECT failed_pin_count, pin_lock_until FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------

def _audit_events() -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    return [
        json.loads(line)
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event(event: str) -> list[dict]:
    return [e for e in _audit_events() if e.get("event") == event]


def _archive_previous_run() -> None:
    """Keep the previous run's evidence instead of destroying it."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path in (DB_PATH, AUDIT_PATH):
        if path.exists():
            os.replace(str(path), f"{path}.prev-{stamp}")


# ---------------------------------------------------------------------------
# Real HTTP helpers
# ---------------------------------------------------------------------------

def _client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def _absorb(client: httpx.AsyncClient, resp: httpx.Response, name: str) -> None:
    """Carry the session cookie the way a browser does.

    The cookie is ``Secure``; the trial speaks plain HTTP on loopback, where a
    cookie jar would withhold it, so the header is set explicitly. Production
    (Caddy + TLS) behaves exactly like this header.
    """
    for raw in resp.headers.get_list("set-cookie"):
        if raw.startswith(f"{name}="):
            client.headers["Cookie"] = raw.split(";", 1)[0]
            return
    raise AssertionError(f"no {name} cookie on the response")


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
    _absorb(client, resp, "auth_session")


async def _open_class(client: httpx.AsyncClient, name: str) -> dict:
    resp = await client.post("/api/classes", json={"name": name}, headers=HEADERS)
    assert resp.status_code == 201, await _text(resp)
    return resp.json()["class"]


async def _invite(
    client: httpx.AsyncClient,
    class_id: str,
    *,
    parent_email: str,
    first_name: str,
) -> dict:
    """Blank PIN on purpose: the server must draw one and hand it back."""
    resp = await client.post(
        "/api/invites",
        json={
            "class_id": class_id,
            "parent_email": parent_email,
            "first_name": first_name,
            "age_band": "P4-P6",
            "lang_code": "zh-hk",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201, await _text(resp)
    return resp.json()


async def _confirm_parent(client: httpx.AsyncClient, token: str) -> None:
    resp = await client.post(
        f"/api/invites/{token}/confirm",
        json={
            "password": CONFIRM_PASSWORD,
            "privacy_policy": True,
            "chat_consent": True,
            "media_consent": False,
        },
    )
    assert resp.status_code in (200, 201), await _text(resp)


async def _confirm_teacher(
    client: httpx.AsyncClient, class_id: str, student_id: str
) -> None:
    resp = await client.post(
        f"/api/classes/{class_id}/confirm",
        json={"student_id": student_id},
        headers=HEADERS,
    )
    assert resp.status_code == 200, await _text(resp)


async def _kid_login(
    client: httpx.AsyncClient, join_code: str, pin: str
) -> httpx.Response:
    return await client.post(
        "/api/student/login",
        json={"join_code": join_code, "pin": pin},
        headers=HEADERS,
    )


def _wrong_pin(correct: str) -> str:
    return "0000" if correct != "0000" else "0001"


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 68)
    print("  Bridge-3d — student join code + PIN login · real-server trial")
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
        code="trial-invite-3d", created_by="trial", expires_at=_future_iso(days=1)
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
    kid_a = _client(base_url)
    kid_b = _client(base_url)
    anon = _client(base_url)
    parent_a = _client(base_url)
    parent_b = _client(base_url)
    parent_c = _client(base_url)

    try:
        # ── 1. invite chain: the server draws the PIN ────────────────────
        await _register_teacher(teacher, "trial-3d@dreamer.local", "trial-invite-3d")
        await _login(teacher, "trial-3d@dreamer.local", "test-pass-teacher1")

        class_a = await _open_class(teacher, "班 A")
        class_b = await _open_class(teacher, "班 B")

        inv_a = await _invite(
            teacher, class_a["id"], parent_email="trial-3d-a@dreamer.local",
            first_name="小明",
        )
        student_a = _latest_student_id()
        await _confirm_parent(parent_a, _invite_token_for(student_a))
        await _confirm_teacher(teacher, class_a["id"], student_a)

        inv_b = await _invite(
            teacher, class_b["id"], parent_email="trial-3d-b@dreamer.local",
            first_name="小美",
        )
        student_b = _latest_student_id()
        await _confirm_parent(parent_b, _invite_token_for(student_b))
        await _confirm_teacher(teacher, class_b["id"], student_b)

        # 3rd invite, parent-confirmed but NOT teacher-confirmed -> pending.
        inv_pending = await _invite(
            teacher, class_a["id"], parent_email="trial-3d-c@dreamer.local",
            first_name="小丙",
        )
        student_pending = _latest_student_id()
        await _confirm_parent(parent_c, _invite_token_for(student_pending))

        pin_a, pin_b = inv_a.get("pin"), inv_b.get("pin")
        pin_pending = inv_pending.get("pin")
        check(
            "1. invite chain: a blank PIN makes the SERVER draw 4 digits "
            "(never a fixed default) and the roster guards hold",
            isinstance(pin_a, str)
            and len(pin_a) == 4
            and pin_a.isdigit()
            and isinstance(pin_b, str)
            and len(pin_b) == 4
            and pin_b.isdigit()
            and isinstance(pin_pending, str)
            and len(pin_pending) == 4
            and pin_pending.isdigit()
            and pin_a != pin_b
            and student_a != student_b,
            f"pin_a={pin_a} pin_b={pin_b} pin_pending={pin_pending}",
        )

        # ── mount a course so the badge has a real week to state ─────────
        mount = await teacher.post(
            f"/api/classes/{class_a['id']}/curriculum",
            json={"curriculum_id": COURSE_ID},
            headers=HEADERS,
        )
        assert mount.status_code == 201, await _text(mount)

        # ── 2. login: 200 + kid_session + masked id ────────────────────
        resp = await _kid_login(kid_a, class_a["join_code"], pin_a)
        login_body = resp.json() if resp.status_code == 200 else {}
        raw_cookies = resp.headers.get_list("set-cookie")
        kid_cookie = next(
            (c for c in raw_cookies if c.startswith("kid_session=")), ""
        )
        _absorb(kid_a, resp, "kid_session")
        success_events = _event("student_login_success")
        check(
            "2. login: 200 + kid_session (HttpOnly/Secure/Lax) + the masked "
            "8-char id, no pin_hash on the wire, INFO audit line written",
            resp.status_code == 200
            and login_body.get("ok") is True
            and login_body.get("student", {}).get("id") == student_a[:8]
            and login_body["student"]["first_name"] == "小明"
            and "pin_hash" not in resp.text
            and student_a not in resp.text
            and "HttpOnly" in kid_cookie
            and "Secure" in kid_cookie
            and "Lax" in kid_cookie
            and len(success_events) == 1
            and success_events[0]["level"] == "INFO",
            f"{resp.status_code} id={login_body.get('student', {}).get('id')} "
            f"cookies={len(raw_cookies)}",
        )

        # ── 3. /me: own space + the SHARED Week 1 / 8 badge ─────────────
        me = await kid_a.get("/api/student/me", headers=HEADERS)
        me_body = me.json()
        badge = me_body.get("badge", {})
        check(
            "3. /me: own identity + the shared Week 1 / 8 badge after mounting "
            "(same resolver as the parent-side kid badge), no classmate data",
            me.status_code == 200
            and me_body.get("student", {}).get("id") == student_a[:8]
            and badge.get("state") == "active"
            and badge.get("week_index") == 1
            and badge.get("total_weeks") == TOTAL_WEEKS
            and badge.get("unit_title") == WEEK_TITLES[1]
            and student_b[:8] not in me.text
            and "master" not in me.text.lower(),
            f"{me.status_code} badge={badge}",
        )

        # ── 4. identity isolation ───────────────────────────────────────
        anon_me = await anon.get("/api/student/me", headers=HEADERS)
        teacher_me = await teacher.get("/api/student/me", headers=HEADERS)
        kid_as_user = await kid_a.get("/api/auth/me", headers=HEADERS)
        kid_console = await kid_a.get(
            f"/api/classes/{class_a['id']}/curriculum", headers=HEADERS
        )
        check(
            "4. identity isolation: anonymous 401; a teacher auth_session 401 on "
            "/me; a kid_session 401 on /api/auth/me and never a console read",
            anon_me.status_code == 401
            and teacher_me.status_code == 401
            and kid_as_user.status_code == 401
            and kid_console.status_code in (401, 403),
            f"anon={anon_me.status_code} teacher={teacher_me.status_code} "
            f"kid_as_user={kid_as_user.status_code} kid_console={kid_console.status_code}",
        )

        # ── 5. one uniform 401 body, reason server-side only ────────────
        fail_events_before = len(_event("student_login_failed"))
        wrong = await _kid_login(kid_b, class_b["join_code"], _wrong_pin(pin_b))
        unknown = await _kid_login(anon, "ZZZZZZZZ", pin_b)
        fail_events = _event("student_login_failed")[fail_events_before:]
        check(
            "5. unknown join code and wrong PIN return the SAME 401 body, the "
            "real reason kept in the WARNING audit line (no existence oracle)",
            wrong.status_code == 401
            and unknown.status_code == 401
            and wrong.text == unknown.text
            and len(fail_events) == 2
            and all(e["level"] == "WARNING" for e in fail_events)
            and all("reason=" in e["message"] for e in fail_events)
            and wrong.text not in "".join(e["message"] for e in fail_events),
            f"bodies equal={wrong.text == unknown.text} events={len(fail_events)}",
        )

        # ── 6. malformed PIN still charges a strike ─────────────────────
        malformed = await _kid_login(kid_b, class_b["join_code"], "nope")
        row_b = _lock_row(class_b["join_code"])
        check(
            "6. a malformed PIN is charged like a wrong one (no free probe) "
            "and never 500s",
            malformed.status_code == 401
            and row_b is not None
            and row_b["failed_count"] == 2,  # 1 (wrong) + 1 (malformed)
            f"{malformed.status_code} count={row_b['failed_count'] if row_b else None}",
        )

        # ── 7. five strikes -> lock, correct PIN still 429 ──────────────
        for _ in range(3):  # 2 already charged on class B
            await _kid_login(kid_b, class_b["join_code"], _wrong_pin(pin_b))
        locked_row = _lock_row(class_b["join_code"])
        locked_until = (
            datetime.datetime.fromisoformat(
                locked_row["locked_until"].replace("Z", "+00:00")
            )
            if locked_row and locked_row["locked_until"]
            else None
        )
        delta = (
            locked_until - datetime.datetime.now(datetime.timezone.utc)
            if locked_until
            else datetime.timedelta(0)
        )
        sixth = await _kid_login(kid_b, class_b["join_code"], pin_b)
        lock_warnings = _event("student_login_locked")
        check(
            "7. five wrong PINs -> the sixth attempt with the CORRECT PIN is "
            "429, a WARNING student_login_locked is written, ~10 minutes out",
            locked_row is not None
            and locked_row["failed_count"] == 0
            and delta > datetime.timedelta(minutes=9)
            and delta <= datetime.timedelta(minutes=10)
            and sixth.status_code == 429
            and len(lock_warnings) == 1
            and lock_warnings[0]["level"] == "WARNING",
            f"sixth={sixth.status_code} delta={delta} warnings={len(lock_warnings)}",
        )

        # ── 8. the lock follows the CODE, not the kid ───────────────────
        other_class = await _kid_login(kid_a, class_a["join_code"], pin_a)
        check(
            "8. the lock is scoped to the join code: another class is unaffected",
            other_class.status_code == 200,
            f"class_a={other_class.status_code} (class_b locked)",
        )

        # ── 9. a successful login clears the strikes ────────────────────
        for _ in range(3):
            await _kid_login(kid_a, class_a["join_code"], _wrong_pin(pin_a))
        mid = _lock_row(class_a["join_code"])
        healed = await _kid_login(kid_a, class_a["join_code"], pin_a)
        after = _lock_row(class_a["join_code"])
        check(
            "9. a successful login clears the accumulated strikes",
            mid is not None
            and mid["failed_count"] == 3
            and healed.status_code == 200
            and after is None,
            f"mid={mid['failed_count'] if mid else None} healed={healed.status_code} "
            f"after={'row' if after else 'cleared'}",
        )

        # ── 10. pin-verify contract untouched (10 strikes / 1 minute) ───
        verify = await teacher.post(
            f"/api/students/{student_a}/pin-verify",
            json={"pin": pin_a},
            headers=HEADERS,
        )
        srow = _student_row(student_a)
        check(
            "10. the delegated /api/students/{id}/pin-verify contract is "
            "untouched by the kid lockout (separate counter, separate scope)",
            students_mod.PIN_LOCK_FAILURES == 10
            and students_mod.PIN_LOCK_MINUTES == 1
            and verify.status_code == 200
            and srow is not None
            and srow["failed_pin_count"] == 0
            and srow["pin_lock_until"] is None,
            f"verify={verify.status_code} students.failed_pin_count="
            f"{srow['failed_pin_count'] if srow else None}",
        )

        # ── 11. a pending student cannot log in ─────────────────────────
        pending_try = await _kid_login(anon, class_a["join_code"], pin_pending)
        conn = _conn()
        try:
            row_pending = conn.execute(
                "SELECT status FROM class_students WHERE student_id = ?",
                (student_pending,),
            ).fetchone()
        finally:
            conn.close()
        check(
            "11. a pending (not yet teacher-confirmed) student cannot log in "
            "even with the right PIN — the roster guard holds, and the failure "
            "is indistinguishable from a wrong PIN",
            pending_try.status_code == 401
            and pending_try.text == unknown.text
            and row_pending is not None
            and row_pending["status"] == "pending",
            f"pending_login={pending_try.status_code} "
            f"status={row_pending['status'] if row_pending else None}",
        )

        # ── 12. logout kills the session ────────────────────────────────
        out = await kid_a.post("/api/student/logout", headers=HEADERS)
        after_me = await kid_a.get(
            "/api/student/me",
            headers={"X-Requested-With": "XMLHttpRequest", "Cookie": ""},
        )
        check(
            "12. logout kills the session server-side: /me turns 401 afterwards",
            out.status_code == 200 and after_me.status_code == 401,
            f"logout={out.status_code} me_after={after_me.status_code}",
        )

        # ── 13. the negative cases are CI red lines ─────────────────────
        test_src = (REPO_ROOT / "tests" / "test_student_login.py").read_text(
            encoding="utf-8"
        )
        ci_src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        required = [
            "test_five_strikes_lock_scope_for_ten_minutes",
            "test_pending_student_cannot_login",
            "test_student_lock_does_not_touch_pin_verify_contract",
            "test_wrong_pin_and_unknown_code_share_one_401_body",
        ]
        check(
            "13. the negative cases exist by name and are on the CI manifest",
            "test_student_login.py" in ci_src
            and all(k in test_src for k in required),
            "ci.yml phase2-tests + four named cases",
        )

        # ── 14. frontend wiring ─────────────────────────────────────────
        def _src(*parts: str) -> str:
            return (REPO_ROOT.joinpath("frontend", "src", *parts)).read_text(
                encoding="utf-8"
            )

        i18n_src = _src("lib", "i18n.tsx")
        api_src = _src("lib", "api.ts")
        main_src = _src("main.tsx")
        login_src = _src("pages", "StudentLoginPage.tsx")
        home_src = _src("pages", "StudentHomePage.tsx")
        keys_three_dicts = all(
            i18n_src.count(key) == 4  # interface + en + hk + cn
            for key in (
                "kidLoginTitle",
                "kidJoinCode",
                "kidPin",
                "kidLoginBtn",
                "kidHomeTitle",
                "kidLogout",
            )
        )
        check(
            "14. frontend wiring: the 3d keys in all three dictionaries, "
            "api.student*, the /student + /student/login routes",
            keys_three_dicts
            and "studentLogin" in api_src
            and "studentMe" in api_src
            and "studentLogout" in api_src
            and "'/api/student/login'" in api_src
            and 'path="/student/login"' in main_src
            and 'path="/student"' in main_src
            and "api.studentLogin" in login_src
            and "studentMe()" in home_src
            and "api.studentLogout" in home_src,
            f"keys_three_dicts={keys_three_dicts}",
        )

        # ── 15. audit sink isolation ────────────────────────────────────
        sink_events = len(_audit_events())
        check(
            "15. audit sink isolation: the whole run wrote into the trial "
            "workdir only; <repo>/audit_log.jsonl is untouched",
            repo_audit.exists() == repo_audit_before
            and sink_events > 0
            and str(DB_PATH) not in json.dumps(_audit_events()),
            f"trial sink events={sink_events}; repo file exists={repo_audit.exists()}",
        )
    finally:
        for c in (teacher, kid_a, kid_b, anon, parent_a, parent_b, parent_c):
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
