"""trial_bridge3e.py — admin payment mark-paid, real-server round trip.

Boss work order 2026-09-13 (3e, decision ②) + ruling #5 ("mock-green !=
real"): the reconciliation surface must be exercised for real — real HTTP
over a real socket, a real SQLite database, the real audit sink — through
the same endpoints the console uses, never a TestClient shortcut.

Scope of THIS trial:

    teacher register/login -> open class -> two invites -> parent confirm
      -> teacher confirm (the roster guard)
      -> admin user (real ``users`` row, role='admin') -> login
      -> GET /api/admin/payments  (everyone reads as pending, LEFT JOIN)
      -> parent payload carries payment_status='pending' (no row needed)
      -> admin POST mark-paid {note} -> row written, audit payment_marked
      -> parent re-read -> 'paid'
      -> repeat mark-paid -> same single row (idempotent, still 200)
      -> mark-pending -> back to pending, audit written again
      -> the negative ring: anonymous 401 / teacher+parent 403 /
         unknown student 404 / bad status filter 400 / overlong note 400

Checks
  ----- the gate (spec: admin only, no drift between read and write) -----
  1  anonymous 401 on mark-paid, mark-pending AND the list — one body, all three
  2  a teacher session AND a parent session get 403 on both marks + list,
     with a WARNING audit line per denial
  3  an unknown student id is 404 (admin is the highest role: it gets the
     real answer, unlike the parent-facing surfaces), a bad ?status= is 400
  ----- the data (spec: one row per student, current state only) -----
  4  the admin list shows every student and reads a never-marked student as
     pending (LEFT JOIN, not "missing")
  5  the parent payload carries payment_status='pending' before any row exists
  6  mark-paid with a note: 200, status flips, exactly ONE payments row, and
     exactly one payment_marked audit line (actor + masked pointer + status;
     the note never reaches the trail)
  7  re-marking an already-paid student is idempotent: 200, STILL one row
  8  the parent re-read turns 'paid' (the badge the console shows)
  9  ?status=pending / ?status=paid split the list correctly
 10  mark-pending restores 'pending' and writes a second audit line — as an
     UPDATE of the same row, never an inserted second row
 11  family isolation: the other parent still reads 'pending' for their own
     child, and neither parent can read or write across families
 12  body validation: no body is fine, an overlong note is 400, a non-string
     note is 400, and a rejected body changes nothing
  ----- evidence -----
 13  the negative cases exist by name and are on the CI manifest
 14  frontend wiring: the 3e keys in all three dictionaries, the three
     api.admin* calls, the section mounted on the existing admin page
     (SafetyPage, admin-only) and the badge in the parent WeekMap
 15  audit sink isolation: <repo>/audit_log.jsonl untouched by the whole
     run; the payments table really has student_id as PRIMARY KEY

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
    os.environ.get("DREAMER_TRIAL_DIR") or tempfile.mkdtemp(prefix="bridge3e_trial_")
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
from auth import security as auth_security  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CONFIRM_PASSWORD = "test-pass-parent1"
ADMIN_PASSWORD = "test-pass-admin1"
LIST_URL = "/api/admin/payments"
MAP_URL = "/api/parent/curriculum"

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


def _payment_rows(student_id: str) -> list[dict]:
    auth_db.ensure_schema()
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT rowid, * FROM payments WHERE student_id = ?", (student_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _payments_table_pk() -> tuple[bool, str]:
    """True when student_id really is the PRIMARY KEY (one row per student)."""
    conn = _conn()
    try:
        info = conn.execute("PRAGMA table_info(payments)").fetchall()
    finally:
        conn.close()
    pk_cols = [r["name"] for r in info if r["pk"]]
    return (pk_cols == ["student_id"], ",".join(pk_cols) or "none")


def _invite_token_for(student_id: str) -> str:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT token FROM invites WHERE student_id = ? ORDER BY rowid DESC LIMIT 1",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no invite for student {student_id}"
    return row[0]


def _latest_student_id() -> str:
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM students ORDER BY rowid DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None, "no student row"
    return row[0]


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
    """Carry the session cookie the way a browser does (Secure cookie, loopback)."""
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
    client: httpx.AsyncClient, class_id: str, *, parent_email: str, first_name: str
) -> dict:
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


async def _mark(
    client: httpx.AsyncClient, student_id: str, kind: str = "paid", *, note=None
) -> httpx.Response:
    body = {} if note is None else {"note": note}
    return await client.post(
        f"/api/admin/payments/{student_id}/mark-{kind}", json=body, headers=HEADERS
    )


async def _list(client: httpx.AsyncClient, *, status: str | None = None) -> httpx.Response:
    url = LIST_URL if status is None else f"{LIST_URL}?status={status}"
    return await client.get(url, headers=HEADERS)


async def _parent_payload(
    client: httpx.AsyncClient, student_id: str
) -> httpx.Response:
    return await client.get(f"{MAP_URL}?student_id={student_id[:8]}", headers=HEADERS)


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 68)
    print("  Bridge-3e — admin payment mark-paid · real-server trial")
    print("=" * 68)
    print(f"  workdir : {WORKDIR}")
    print(f"  db      : {DB_PATH}")
    print(f"  audit   : {AUDIT_PATH}")

    repo_audit = REPO_ROOT / "audit_log.jsonl"
    repo_audit_before = repo_audit.exists()

    _archive_previous_run()
    _seed_schema()
    auth_db.insert_teacher_invite(
        code="trial-invite-3e", created_by="trial", expires_at=_future_iso(days=1)
    )

    # The admin is a real ``users`` row — never a patched role on some session.
    admin_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=admin_id,
        email="trial-3e-admin@dreamer.local",
        password_hash=auth_security.hash_password(ADMIN_PASSWORD),
        role="admin",
        email_verified=True,
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
    admin = _client(base_url)
    parent_a = _client(base_url)
    parent_b = _client(base_url)
    anon = _client(base_url)

    try:
        # ── fixtures: a class with two confirmed students ───────────────
        await _register_teacher(teacher, "trial-3e@dreamer.local", "trial-invite-3e")
        await _login(teacher, "trial-3e@dreamer.local", "test-pass-teacher1")
        class_a = await _open_class(teacher, "班 3e")

        await _invite(
            teacher, class_a["id"], parent_email="trial-3e-a@dreamer.local", first_name="小明"
        )
        student_a = _latest_student_id()
        await _confirm_parent(parent_a, _invite_token_for(student_a))
        await _login(parent_a, "trial-3e-a@dreamer.local", CONFIRM_PASSWORD)
        await _confirm_teacher(teacher, class_a["id"], student_a)

        await _invite(
            teacher, class_a["id"], parent_email="trial-3e-b@dreamer.local", first_name="小美"
        )
        student_b = _latest_student_id()
        await _confirm_parent(parent_b, _invite_token_for(student_b))
        await _login(parent_b, "trial-3e-b@dreamer.local", CONFIRM_PASSWORD)
        await _confirm_teacher(teacher, class_a["id"], student_b)

        await _login(admin, "trial-3e-admin@dreamer.local", ADMIN_PASSWORD)

        mask_a, mask_b = student_a[:8], student_b[:8]

        # ── 1. anonymous 401 on all three endpoints ─────────────────────
        anon_mark = await _mark(anon, mask_a)
        anon_undo = await _mark(anon, mask_a, "pending")
        anon_list = await _list(anon)
        check(
            "1. anonymous 401 on mark-paid, mark-pending AND the list — one "
            "body, all three (no endpoint drifts out of the gate)",
            anon_mark.status_code == 401
            and anon_undo.status_code == 401
            and anon_list.status_code == 401
            and anon_mark.text == anon_undo.text == anon_list.text,
            f"mark={anon_mark.status_code} undo={anon_undo.status_code} "
            f"list={anon_list.status_code}",
        )

        # ── 2. teacher + parent 403, with a WARNING each ────────────────
        teacher_mark = await _mark(teacher, mask_a)
        teacher_list = await _list(teacher)
        parent_mark = await _mark(parent_a, mask_a)
        parent_list = await _list(parent_a)
        denials = [
            e
            for e in _audit_events()
            if e.get("level") == "WARNING"
            and str(e.get("event", "")).startswith("payment_")
        ]
        warned_kinds = {e.get("event") for e in denials}
        check(
            "2. a teacher AND a parent session get 403 on the marks + the list, "
            "with a WARNING audit line per denial (4 denials, both codes)",
            teacher_mark.status_code == 403
            and teacher_list.status_code == 403
            and parent_mark.status_code == 403
            and parent_list.status_code == 403
            and len(denials) >= 4
            and {
                "payment_mark_paid_denied",
                "payment_list_denied",
            }.issubset(warned_kinds),
            f"403s ok; warnings={sorted(warned_kinds)}",
        )

        # ── 3. unknown student 404 / bad filter 400 ─────────────────────
        unknown = await _mark(admin, "deadbeef")
        bad_filter = await _list(admin, status="refunded")
        check(
            "3. an unknown student id is 404 and a bad ?status= is 400 — the "
            "admin gets the real answer, never a silently-empty list",
            unknown.status_code == 404 and bad_filter.status_code == 400,
            f"unknown={unknown.status_code} bad_filter={bad_filter.status_code}",
        )

        # ── 4. the list reads a never-marked student as pending ─────────
        listing = await _list(admin)
        rows = listing.json().get("payments", [])
        by_mask = {r["student_id"]: r for r in rows}
        check(
            "4. the admin list shows every student and reads a never-marked "
            "student as pending (LEFT JOIN, not 'missing')",
            listing.status_code == 200
            and mask_a in by_mask
            and mask_b in by_mask
            and by_mask[mask_a]["status"] == "pending"
            and by_mask[mask_b]["status"] == "pending"
            and student_a not in listing.text,
            f"{listing.status_code} rows={len(rows)}",
        )

        # ── 5. parent payload carries pending before any row exists ─────
        p_before = await _parent_payload(parent_a, student_a)
        check(
            "5. the parent payload carries payment_status='pending' before any "
            "payments row exists (the read path never invents a row)",
            p_before.status_code == 200
            and p_before.json().get("payment_status") == "pending"
            and _payment_rows(student_a) == [],
            f"{p_before.status_code} status={p_before.json().get('payment_status')}",
        )

        # ── 6. mark-paid + note: one row, one audit line ────────────────
        marked = await _mark(admin, mask_a, "paid", note="已收 9 月學費")
        body = marked.json() if marked.status_code == 200 else {}
        rows_after = _payment_rows(student_a)
        audits = _event("payment_marked")
        audit = audits[0] if audits else {}
        check(
            "6. mark-paid with a note: 200, status flips, exactly ONE payments "
            "row, exactly one payment_marked audit line — actor + masked "
            "pointer + status, and the note never reaches the trail",
            marked.status_code == 200
            and body.get("status") == "paid"
            and body.get("student_id") == mask_a
            and body.get("note") == "已收 9 月學費"
            and len(rows_after) == 1
            and rows_after[0]["status"] == "paid"
            and rows_after[0]["marked_by"] == admin_id
            and len(audits) == 1
            and audit.get("user_id") == admin_id
            and audit.get("target_id") == mask_a
            and audit.get("level") == "INFO"
            and "已收" not in json.dumps(audit, ensure_ascii=False)
            and "學費" not in json.dumps(audit, ensure_ascii=False),
            f"{marked.status_code} rows={len(rows_after)} audits={len(audits)}",
        )
        first_marked_at = rows_after[0]["marked_at"] if rows_after else None

        # ── 7. idempotent re-mark ───────────────────────────────────────
        again = await _mark(admin, mask_a, "paid")
        rows_again = _payment_rows(student_a)
        check(
            "7. re-marking an already-paid student is idempotent: 200 and "
            "STILL one row (UPDATE, never an inserted second row)",
            again.status_code == 200
            and len(rows_again) == 1
            and rows_again[0]["status"] == "paid"
            and len({r["student_id"] for r in rows_again}) == 1,
            f"{again.status_code} rows={len(rows_again)}",
        )

        # ── 8. the parent re-read turns paid ────────────────────────────
        p_after = await _parent_payload(parent_a, student_a)
        check(
            "8. the parent re-read turns 'paid' — the badge the console shows",
            p_after.status_code == 200
            and p_after.json().get("payment_status") == "paid",
            f"{p_after.status_code} status={p_after.json().get('payment_status')}",
        )

        # ── 9. the status filter really splits the list ─────────────────
        only_paid = await _list(admin, status="paid")
        only_pending = await _list(admin, status="pending")
        paid_masks = {r["student_id"] for r in only_paid.json().get("payments", [])}
        pending_masks = {r["student_id"] for r in only_pending.json().get("payments", [])}
        check(
            "9. ?status=pending / ?status=paid split the list correctly "
            "(小美 still untouched, 小明 out of the pending half)",
            paid_masks == {mask_a} and pending_masks == {mask_b},
            f"paid={sorted(paid_masks)} pending={sorted(pending_masks)}",
        )

        # ── 10. mark-pending restores, second audit line, same row ──────
        restored = await _mark(admin, mask_a, "pending")
        rows_restored = _payment_rows(student_a)
        audits2 = _event("payment_marked")
        check(
            "10. mark-pending restores 'pending' and writes a second audit "
            "line — as an UPDATE of the same row, never a new one",
            restored.status_code == 200
            and restored.json().get("status") == "pending"
            and len(rows_restored) == 1
            and rows_restored[0]["status"] == "pending"
            and len(audits2) == 3
            and audits2[-1].get("message") == "payment marked pending"
            and first_marked_at is not None,
            f"{restored.status_code} rows={len(rows_restored)} audits={len(audits2)}",
        )

        # ── 11. family isolation ────────────────────────────────────────
        p_b_own = await _parent_payload(parent_b, student_b)
        p_b_cross = await _parent_payload(parent_b, student_a)
        p_a_cross_mark = await _mark(parent_a, mask_b)
        check(
            "11. family isolation: the other parent still reads 'pending' for "
            "their own child and cannot read or write across families",
            p_b_own.status_code == 200
            and p_b_own.json().get("payment_status") == "pending"
            and p_b_cross.status_code in (403, 404)
            and p_a_cross_mark.status_code == 403,
            f"own={p_b_own.status_code} cross_read={p_b_cross.status_code} "
            f"cross_mark={p_a_cross_mark.status_code}",
        )

        # ── 12. body validation changes nothing ─────────────────────────
        no_body = await admin.post(
            f"{LIST_URL}/{mask_a}/mark-paid", json=None, headers=HEADERS
        )
        long_note = await _mark(admin, mask_b, "paid", note="x" * 501)
        bad_note = await admin.post(
            f"{LIST_URL}/{mask_b}/mark-paid", json={"note": 123}, headers=HEADERS
        )
        rows_b = _payment_rows(student_b)
        check(
            "12. body validation: no body is fine, an overlong note is 400, a "
            "non-string note is 400 — and the rejected writes changed nothing",
            no_body.status_code == 200
            and long_note.status_code == 400
            and bad_note.status_code == 400
            and rows_b == [],
            f"nobody={no_body.status_code} long={long_note.status_code} "
            f"bad={bad_note.status_code} rows_b={len(rows_b)}",
        )
        # the no-body call marked 小明 paid; put it back so the state is tidy
        await _mark(admin, mask_a, "pending")

        # ── 13. the negative cases are CI red lines ─────────────────────
        test_src = (REPO_ROOT / "tests" / "test_bridge3e_payments.py").read_text(
            encoding="utf-8"
        )
        ci_src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        required = [
            "test_mark_paid_rejects_anonymous_and_non_admin",
            "test_payment_list_rejects_unknown_status_filter",
            "test_repeat_mark_paid_is_idempotent",
            "test_parent_cannot_read_another_family_payment",
            "test_overlong_note_is_rejected",
        ]
        check(
            "13. the negative cases exist by name and are on the CI manifest",
            "test_bridge3e_payments.py" in ci_src
            and all(k in test_src for k in required),
            "ci.yml phase2-tests + five named cases",
        )

        # ── 14. frontend wiring ─────────────────────────────────────────
        def _src(*parts: str) -> str:
            return (REPO_ROOT.joinpath("frontend", "src", *parts)).read_text(
                encoding="utf-8"
            )

        i18n_src = _src("lib", "i18n.tsx")
        api_src = _src("lib", "api.ts")
        safety_src = _src("pages", "SafetyPage.tsx")
        weekmap_src = _src("components", "parent", "WeekMap.tsx")
        section_src = _src("components", "teacher", "PaymentReconciliationSection.tsx")
        keys = (
            "paymentStatusPending",
            "paymentStatusPaid",
            "paymentSectionTitle",
            "paymentSectionSubtitle",
            "paymentFilterAll",
            "paymentMarkPaid",
            "paymentMarkPending",
            "paymentNotePlaceholder",
            "paymentMarkedAt",
            "paymentEmpty",
        )
        keys_three_dicts = all(i18n_src.count(k) == 4 for k in keys)
        check(
            "14. frontend wiring: the 3e keys in all three dictionaries, the "
            "three api.admin* calls, the section on the existing admin page "
            "(admin-only) and the badge in the parent WeekMap",
            keys_three_dicts
            and "adminPayments" in api_src
            and "adminMarkPaid" in api_src
            and "adminMarkPending" in api_src
            and "/api/admin/payments" in api_src
            and "mark-paid" in api_src
            and "mark-pending" in api_src
            and "PaymentReconciliationSection" in safety_src
            and "user.role === 'admin'" in safety_src
            and "api.adminMarkPaid" in section_src
            and "api.adminMarkPending" in section_src
            and "payment_status" in weekmap_src
            and "paymentStatusPaid" in weekmap_src,
            f"keys_three_dicts={keys_three_dicts}",
        )

        # ── 15. audit sink isolation + the one-row invariant ────────────
        sink_events = len(_audit_events())
        pk_ok, pk_cols = _payments_table_pk()
        check(
            "15. audit sink isolation: the whole run wrote into the trial "
            "workdir only; <repo>/audit_log.jsonl is untouched — and the "
            "payments table really keys on student_id alone",
            repo_audit.exists() == repo_audit_before
            and sink_events > 0
            and str(DB_PATH) not in json.dumps(_audit_events())
            and pk_ok,
            f"trial sink events={sink_events}; repo file exists={repo_audit.exists()}; "
            f"pk={pk_cols}",
        )
    finally:
        for c in (teacher, admin, parent_a, parent_b, anon):
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
