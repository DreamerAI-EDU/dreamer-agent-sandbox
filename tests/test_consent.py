"""W2 PR#2 — consent gate tests (12 cases, per PR brief §6).

Covers: registry + legal page SoT pairing, docs endpoint auth, sign
version-check + ip/user_agent capture, unknown doc_type, re-sign gate on
login (including version bump), media withdraw append-only + audit marker,
privacy withdraw rejection, role scoping (W6 PR-F/G: teacher accounts are
gated by the staff notice only), and the code-level guard that the consent
module has no UPDATE/DELETE path on consent_log.

No real passwords anywhere: all fixtures use `test-pass-` prefix (guard
test 13 enforces this repo-wide).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

PRIVACY_HTML_SNIPPET = "DREAMER AI EDUCATION LIMITED"
MEDIA_HTML_SNIPPET = "Media Consent Form 媒體同意書"


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _session_cookie(resp) -> str:
    """Extract auth_session token from a login response (see test_auth)."""
    set_cookies = resp.headers.getall("Set-Cookie", [])
    for sc in set_cookies:
        if sc.startswith("auth_session="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no auth_session cookie in {set_cookies}")


def _register_teacher(client, *, email="teacher@test.local",
                      password="test-pass-teacher1", invite="invite-ok-001"):
    return client.post(
        "/api/auth/register",
        json={"invite_code": invite, "email": email, "password": password},
        headers=HEADERS,
    )


async def _login(client, *, email="teacher@test.local",
                 password="test-pass-teacher1"):
    return await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )


async def _setup_logged_in_user(client):
    await _register_teacher(client)
    login = await _login(client)
    assert login.status == 200
    return _session_cookie(login)


def _consent_rows(db_path, *, user_id, doc_type):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id, doc_type, doc_version, action, ip, user_agent "
            "FROM consent_log WHERE user_id = ? AND doc_type = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (user_id, doc_type),
        )
        return cur.fetchall()
    finally:
        conn.close()


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
def fresh_invite():
    auth_db.insert_teacher_invite(
        code="invite-ok-001",
        created_by="admin-cli",
        expires_at=_future_iso(days=7),
    )


# ---------------------------------------------------------------------------
# 1. GET /api/consent/docs requires login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_docs_requires_login(client):
    resp = await client.get("/api/consent/docs")
    assert resp.status == 401


# ---------------------------------------------------------------------------
# 2. Docs registry + legal pages share the YAML SoT version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_docs_registry_and_legal_pages_pair_with_yaml(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)

    resp = await client.get(
        "/api/consent/docs", headers={"Cookie": f"auth_session={token}"}
    )
    assert resp.status == 200
    body = await resp.json()
    documents = body["documents"]
    assert set(documents) == {
        "privacy_policy", "media_consent", "chat_consent",
        "staff_data_processing",
    }

    pp = documents["privacy_policy"]
    assert pp["current_version"] == "v2026-08-26"
    assert pp["required"] is True
    assert pp["roles"] == ["parent"]
    assert pp["title_zh"] == "私隱政策"
    assert pp["title_en"] == "Privacy Policy"

    mc = documents["media_consent"]
    assert mc["current_version"] == "v2026-08-26"
    assert mc["required"] is False
    assert mc["title_zh"] == "媒體同意書"
    assert mc["title_en"] == "Media Consent Form"

    cc = documents["chat_consent"]
    assert cc["current_version"] == "v2026-09-08"
    assert cc["required"] is True
    assert cc["roles"] == ["parent"]
    assert cc["title_zh"] == "AI 對話服務同意書"
    assert cc["title_en"] == "AI Chat Service Consent"

    # W6 PR-G: the staff data-processing notice is its own registry entry,
    # scoped to classroom staff — it is NOT a parent document.
    sd = documents["staff_data_processing"]
    assert sd["current_version"] == "v2026-09-10"
    assert sd["required"] is True
    assert sd["roles"] == ["teacher", "admin"]
    assert sd["title_zh"] == "職員資料處理守則"
    assert sd["title_en"] == "Staff Data Processing Notice"

    # Embedded legal pages are public, carry the same version from the same
    # YAML (never a second hardcoded copy), and hold the approved copy.
    pp_page = await client.get("/legal/privacy-policy")
    assert pp_page.status == 200
    pp_html = await pp_page.text()
    assert "v2026-08-26" in pp_html
    assert PRIVACY_HTML_SNIPPET in pp_html
    assert "Effective Date 生效日期：26 August 2026" in pp_html
    assert "我們絕不要求或儲存學生全名" in pp_html
    assert "info@dreamer-aiedu.com" in pp_html

    mc_page = await client.get("/legal/media-consent")
    assert mc_page.status == 200
    mc_html = await mc_page.text()
    assert "v2026-08-26" in mc_html
    assert MEDIA_HTML_SNIPPET in mc_html
    assert "withdraw consent at any time" in mc_html
    assert "24 小時內" in mc_html

    # W6 PR-D: chat-consent legal page ships on the same route + version
    # injection pipeline. The version literal must NEVER leak as {{VERSION}}.
    cc_page = await client.get("/legal/chat-consent")
    assert cc_page.status == 200
    cc_html = await cc_page.text()
    assert "v2026-09-08" in cc_html
    assert "{{VERSION}}" not in cc_html
    assert "Effective Date 生效日期：8 September 2026" in cc_html
    assert "90 日" in cc_html
    assert "本人<strong>同意</strong>" in cc_html
    assert "info@dreamer-aiedu.com" in cc_html

    # W6 PR-G: the staff notice ships on the same route + version injection
    # pipeline (the page is public policy copy, like the other two).
    sd_page = await client.get("/legal/staff-data-processing")
    assert sd_page.status == 200
    sd_html = await sd_page.text()
    assert "v2026-09-10" in sd_html
    assert "{{VERSION}}" not in sd_html
    assert "Effective Date 生效日期：10 September 2026" in sd_html
    assert "職員資料處理守則" in sd_html
    assert "info@dreamer-aiedu.com" in sd_html

    # Unknown legal slug → 404.
    missing = await client.get("/legal/not-a-page")
    assert missing.status == 404


# ---------------------------------------------------------------------------
# 3. Sign requires login and CSRF header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_sign_requires_login_and_csrf(client, fresh_invite):
    # No session cookie → 401.
    resp = await client.post(
        "/api/consent/sign",
        json={"doc_type": "privacy_policy", "doc_version": "v2026-08-26"},
        headers=HEADERS,
    )
    assert resp.status == 401

    # Session cookie but missing CSRF header → 403.
    await _register_teacher(client)
    login = await _login(client)
    token = _session_cookie(login)
    resp_csrf = await client.post(
        "/api/consent/sign",
        json={"doc_type": "privacy_policy", "doc_version": "v2026-08-26"},
        headers={"Cookie": f"auth_session={token}"},
    )
    assert resp_csrf.status == 403


# ---------------------------------------------------------------------------
# 4. Sign success persists ip + user_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_sign_success_records_ip_and_user_agent(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    resp = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "privacy_policy",
            "doc_version": "v2026-08-26",
        },
        headers={
            **HEADERS,
            "Cookie": f"auth_session={token}",
            "User-Agent": "test-consent-agent/1.0",
        },
    )
    assert resp.status == 201
    body = await resp.json()
    assert body["ok"] is True

    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=user["id"], doc_type="privacy_policy"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row[2] == "v2026-08-26"     # doc_version
    assert row[3] == "agreed"          # action
    assert row[4] is not None          # ip
    assert row[5] == "test-consent-agent/1.0"  # user_agent


# ---------------------------------------------------------------------------
# 5. Sign rejects old / fake version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_sign_rejects_old_or_fake_version(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    for bad_version in ("v2026-08-25", "v1.0", "latest", ""):
        resp = await client.post(
            "/api/consent/sign",
            json={"doc_type": "privacy_policy", "doc_version": bad_version},
            headers={**HEADERS, "Cookie": f"auth_session={token}"},
        )
        assert resp.status == 400, f"version {bad_version!r} must be rejected"
        rows = _consent_rows(
            os.environ["DREAMER_DB_PATH"],
            user_id=user["id"],
            doc_type="privacy_policy",
        )
        assert len(rows) == 0, f"version {bad_version!r} must not insert a row"


# ---------------------------------------------------------------------------
# 6. Sign rejects unknown doc_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_sign_rejects_unknown_doc_type(client, fresh_invite):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    resp = await client.post(
        "/api/consent/sign",
        json={"doc_type": "cookies_policy", "doc_version": "v2026-08-26"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 400

    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM consent_log WHERE user_id = ?",
            (user["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# 7. Re-sign gate on login: unsigned required doc → true; after sign → false
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_re_sign_gate_toggles_with_privacy_signature(
    client, fresh_invite
):
    # W6 PR-F role scope: the parent/child registry only applies to
    # role=parent, so this re-sign flow runs on a parent account.
    parent_id, email, password = _create_parent_user()

    # Fresh parent: both required docs (privacy + chat) unsigned -> gate on.
    login1 = await _login(client, email=email, password=password)
    assert login1.status == 200
    body1 = await login1.json()
    assert body1["consent_required"] is True
    assert body1["missing_consent"] == ["privacy_policy", "chat_consent"]
    token1 = _session_cookie(login1)

    # Signing ONLY privacy_policy still leaves chat_consent missing (PR-D).
    resp = await client.post(
        "/api/consent/sign",
        json={"doc_type": "privacy_policy", "doc_version": "v2026-08-26"},
        headers={**HEADERS, "Cookie": f"auth_session={token1}"},
    )
    assert resp.status == 201
    login_mid = await _login(client, email=email, password=password)
    body_mid = await login_mid.json()
    assert body_mid["consent_required"] is True
    assert body_mid["missing_consent"] == ["chat_consent"]

    # Sign chat_consent too -> gate off, nothing missing.
    resp2 = await client.post(
        "/api/consent/sign",
        json={"doc_type": "chat_consent", "doc_version": "v2026-09-08"},
        headers={**HEADERS, "Cookie": f"auth_session={token1}"},
    )
    assert resp2.status == 201

    login2 = await _login(client, email=email, password=password)
    assert login2.status == 200
    body2 = await login2.json()
    assert body2["consent_required"] is False
    assert body2["missing_consent"] == []


# ---------------------------------------------------------------------------
# 8. media_consent (required:false) never triggers the gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_consent_does_not_trigger_re_sign_gate(
    client, fresh_invite
):
    _parent_id, email, password = _create_parent_user()

    login = await _login(client, email=email, password=password)
    assert login.status == 200
    body = await login.json()
    # Missing list holds the required docs (privacy + chat) -- media_consent
    # is optional and never appears.
    assert body["missing_consent"] == ["privacy_policy", "chat_consent"]


# ---------------------------------------------------------------------------
# 8b. W6 PR-F role scope: staff accounts stay outside the parent gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_teacher_gate_uses_staff_notice_not_parent_docs(client, fresh_invite):
    """W6 PR-F/G: a teacher is gated by the staff notice, never by parent docs.

    The parent/child documents stay scoped to role=parent, so a teacher's
    missing list contains ONLY staff_data_processing (roles teacher+admin,
    required:true). Signing it clears the gate; the parent documents were
    never part of the teacher's gate at any point.
    """
    await _register_teacher(client)

    login = await _login(client)
    assert login.status == 200
    body = await login.json()
    assert body["consent_required"] is True
    assert body["missing_consent"] == ["staff_data_processing"]

    token = _session_cookie(login)
    headers = {**HEADERS, "Cookie": f"auth_session={token}"}
    status = await client.get("/api/consent/status", headers=headers)
    assert status.status == 200
    docs = (await status.json())["documents"]
    assert docs["privacy_policy"]["roles"] == ["parent"]
    assert docs["privacy_policy"]["required"] is False
    assert docs["chat_consent"]["required"] is False
    assert docs["media_consent"]["required"] is False
    assert docs["staff_data_processing"]["roles"] == ["teacher", "admin"]
    assert docs["staff_data_processing"]["required"] is True
    assert docs["staff_data_processing"]["status"] == "unsigned"

    docs_resp = await client.get("/api/consent/docs", headers=headers)
    assert docs_resp.status == 200
    registry = (await docs_resp.json())["documents"]
    assert registry["privacy_policy"]["roles"] == ["parent"]
    assert registry["chat_consent"]["roles"] == ["parent"]
    assert registry["staff_data_processing"]["roles"] == ["teacher", "admin"]

    # Signing the staff notice is what clears a teacher's gate.
    sign = await client.post(
        "/api/consent/sign",
        json={"doc_type": "staff_data_processing", "doc_version": "v2026-09-10"},
        headers=headers,
    )
    assert sign.status == 201
    assert (await sign.json())["doc_type"] == "staff_data_processing"

    relogin = await _login(client)
    assert relogin.status == 200
    body2 = await relogin.json()
    assert body2["consent_required"] is False
    assert body2["missing_consent"] == []


@pytest.mark.asyncio
async def test_staff_notice_withdraw_rejected_with_email_pointer(
    client, fresh_invite
):
    """W6 PR-G: the staff notice is a condition of holding a staff account,
    so it is not withdrawable through the API (same account-level route as
    privacy_policy). Nothing is written — the agreed row stays latest.
    """
    await _register_teacher(client)
    login = await _login(client)
    token = _session_cookie(login)
    headers = {**HEADERS, "Cookie": f"auth_session={token}"}

    sign = await client.post(
        "/api/consent/sign",
        json={"doc_type": "staff_data_processing", "doc_version": "v2026-09-10"},
        headers=headers,
    )
    assert sign.status == 201

    withdraw = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "staff_data_processing"},
        headers=headers,
    )
    assert withdraw.status == 400
    wbody = await withdraw.json()
    assert wbody["email"] == "info@dreamer-aiedu.com"
    assert "撤回" in wbody["error"]

    user = auth_db.get_user_by_email("teacher@test.local")
    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"],
        user_id=user["id"],
        doc_type="staff_data_processing",
    )
    assert len(rows) == 1
    assert rows[0][3] == "agreed"


# ---------------------------------------------------------------------------
# 9. Version bump invalidates old agreement -> gate re-triggers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_version_bump_re_triggers_re_sign_gate(
    client, fresh_invite, tmp_path, monkeypatch
):
    parent_id, email, password = _create_parent_user()

    # Sign both required docs -> gate off.
    login1 = await _login(client, email=email, password=password)
    token1 = _session_cookie(login1)
    for doc_type, doc_version in (
        ("privacy_policy", "v2026-08-26"),
        ("chat_consent", "v2026-09-08"),
    ):
        resp = await client.post(
            "/api/consent/sign",
            json={"doc_type": doc_type, "doc_version": doc_version},
            headers={**HEADERS, "Cookie": f"auth_session={token1}"},
        )
        assert resp.status == 201
    login_ok = await _login(client, email=email, password=password)
    assert (await login_ok.json())["consent_required"] is False

    # Ship a new document version in the registry.
    yaml_path = tmp_path / "consent_docs.yaml"
    yaml_path.write_text(
        "documents:\n"
        "  privacy_policy:\n"
        '    current_version: "v2026-08-27"\n'
        "    required: true\n"
        '    title_zh: "\u79c1\u96b1\u653f\u7b56"\n'
        '    title_en: "Privacy Policy"\n'
        "  media_consent:\n"
        '    current_version: "v2026-08-26"\n'
        "    required: false\n"
        '    title_zh: "\u5a92\u9ad4\u540c\u610f\u66f8"\n'
        '    title_en: "Media Consent Form"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(consent_mod, "DOCS_PATH", str(yaml_path))

    # Old agreed row (v2026-08-26) no longer satisfies the gate.
    login3 = await _login(client, email=email, password=password)
    assert login3.status == 200
    body3 = await login3.json()
    assert body3["consent_required"] is True
    assert body3["missing_consent"] == ["privacy_policy"]

    # Old row still present (append-only, never mutated) but not current.
    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=parent_id, doc_type="privacy_policy"
    )
    assert [r[3] for r in rows] == ["agreed"]
    assert rows[0][2] == "v2026-08-26"


# ---------------------------------------------------------------------------
# 10. media withdraw: prior-agree gate (P3-2) — one audit marker only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_withdraw_appends_withdrawn_row_and_audit_marker(
    client, fresh_invite, tmp_path
):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    # Sign media_consent first.
    sign = await client.post(
        "/api/consent/sign",
        json={"doc_type": "media_consent", "doc_version": "v2026-08-26"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert sign.status == 201

    # Withdraw media_consent — allowed while a current-version agreed row
    # covers the scope.
    w1 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w1.status == 200

    # Double withdraw now hits the P3-2 prior-agree gate: the latest row is
    # already `withdrawn`, so there is nothing to withdraw — uniform 400,
    # zero writes, zero fake WARNING rows.
    w2 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w2.status == 400
    body = await w2.json()
    assert body["error"] == "未有可撤回嘅同意紀錄"

    # All rows survive: agreed + withdrawn; old row untouched.
    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=user["id"], doc_type="media_consent"
    )
    assert [r[3] for r in rows] == ["withdrawn", "agreed"]

    # Status reflects the latest row.
    status = await client.get(
        "/api/consent/status", headers={"Cookie": f"auth_session={token}"}
    )
    assert status.status == 200
    status_body = await status.json()
    assert status_body["documents"]["media_consent"]["status"] == "withdrawn"
    assert status_body["documents"]["privacy_policy"]["status"] == "unsigned"

    # Audit log carries exactly one media_takedown_pending marker (the
    # rejected second withdraw must not emit a fake WARNING).
    audit_lines = [
        line for line in (tmp_path / "audit_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert len(audit_lines) == 1
    record = __import__("json").loads(audit_lines[0])
    assert record["event"] == "media_takedown_pending"
    assert record["level"] == "WARNING"
    assert record["doc_type"] == "media_consent"
    assert record["user_id"] == user["id"]
    assert record["student_id"] is None


# ---------------------------------------------------------------------------
# 11. privacy_policy withdraw rejected with info@ pointer, no new row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_privacy_withdraw_rejected_with_email_pointer(
    client, fresh_invite
):
    token = await _setup_logged_in_user(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    resp = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "privacy_policy"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 400
    body = await resp.json()
    assert "info@dreamer-aiedu.com" in body["error"]

    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=user["id"], doc_type="privacy_policy"
    )
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# 12. Code guard: consent module has no UPDATE / DELETE on consent_log
# ---------------------------------------------------------------------------

def test_consent_module_has_no_update_or_delete_on_consent_log():
    """B31-style read-only guard — the consent gate must stay append-only.

    Scanning auth/consent.py and auth/api.py for mutation statements on the
    consent_log table (case-insensitive, whitespace-tolerant).
    """
    files = [
        os.path.join(REPO_ROOT, "auth", "consent.py"),
        os.path.join(REPO_ROOT, "auth", "api.py"),
    ]
    bad = []
    patterns = [
        re.compile(r"UPDATE\s+consent_log", re.IGNORECASE),
        re.compile(r"DELETE\s+FROM\s+consent_log", re.IGNORECASE),
    ]
    for path in files:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for pattern in patterns:
            if pattern.search(text):
                bad.append((os.path.relpath(path, REPO_ROOT), pattern.pattern))
    assert not bad, f"consent_log mutation statements found: {bad}"


# ---------------------------------------------------------------------------
# 13-16. W2 PR#3 §0 — consent student_id ownership gate (blocking item).
# sign/withdraw with student_id must verify students.parent_id == current
# user; cross-parent and unbound students are rejected with a uniform 403.
# ---------------------------------------------------------------------------

def _create_parent_user(email="parent-a@test.local",
                        password="test-pass-parent1"):
    """Create a parent user directly in DB (role=parent, verified)."""
    from auth import security as auth_security
    import uuid
    user_id = str(uuid.uuid4())
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=auth_security.hash_password(password),
        role="parent",
        email_verified=True,
    )
    return user_id, email, password


async def _login_parent(client, email, password):
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=HEADERS,
    )
    assert login.status == 200, await login.text()
    return _session_cookie(login)


def _create_db_student(*, parent_id, first_name="Child",
                       age_band="P1-P3", lang_code="zh-hk", pin="1234"):
    from auth import students as students_mod
    return students_mod.create_student(
        parent_id=parent_id,
        first_name=first_name,
        age_band=age_band,
        lang_code=lang_code,
        pin_hash=students_mod.hash_pin(pin),
    )


def _consent_count_for_student(db_path, student_id):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM consent_log WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]
    finally:
        conn.close()


# 13. cross-parent sign → 403, no consent row
@pytest.mark.asyncio
async def test_consent_sign_cross_parent_student_forbidden(
    client, fresh_invite
):
    parent_a, _, _ = _create_parent_user("parent-a@test.local")
    student_id = _create_db_student(parent_id=parent_a)
    _, email_b, pw_b = _create_parent_user("parent-b@test.local")
    token_b = await _login_parent(client, email_b, pw_b)

    resp = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "privacy_policy",
            "doc_version": "v2026-08-26",
            "student_id": student_id,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token_b}"},
    )
    assert resp.status == 403
    assert _consent_count_for_student(
        os.environ["DREAMER_DB_PATH"], student_id
    ) == 0


# 14. cross-parent withdraw → 403
@pytest.mark.asyncio
async def test_consent_withdraw_cross_parent_student_forbidden(
    client, fresh_invite
):
    parent_a, _, _ = _create_parent_user("parent-a@test.local")
    student_id = _create_db_student(parent_id=parent_a)
    _, email_b, pw_b = _create_parent_user("parent-b@test.local")
    token_b = await _login_parent(client, email_b, pw_b)

    resp = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token_b}"},
    )
    assert resp.status == 403
    assert _consent_count_for_student(
        os.environ["DREAMER_DB_PATH"], student_id
    ) == 0


# 15. unbound student (parent_id NULL) → sign rejected
@pytest.mark.asyncio
async def test_consent_sign_rejects_unbound_student(client, fresh_invite):
    student_id = _create_db_student(parent_id=None)
    _, email, pw = _create_parent_user("parent-a@test.local")
    token = await _login_parent(client, email, pw)

    resp = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "privacy_policy",
            "doc_version": "v2026-08-26",
            "student_id": student_id,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 403
    assert _consent_count_for_student(
        os.environ["DREAMER_DB_PATH"], student_id
    ) == 0


# 16. own parent sign/withdraw with own student → allowed (regression path)
@pytest.mark.asyncio
async def test_consent_own_parent_sign_withdraw_own_student_ok(
    client, fresh_invite
):
    parent_a, email_a, pw_a = _create_parent_user("parent-a@test.local")
    student_id = _create_db_student(parent_id=parent_a)
    token = await _login_parent(client, email_a, pw_a)

    sign = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "privacy_policy",
            "doc_version": "v2026-08-26",
            "student_id": student_id,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert sign.status == 201

    sign_media = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "media_consent",
            "doc_version": "v2026-08-26",
            "student_id": student_id,
        },
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert sign_media.status == 201

    withdraw = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": student_id},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert withdraw.status == 200

    # Rows landed with the correct student linkage (version from YAML SoT).
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        rows = conn.execute(
            "SELECT doc_type, doc_version, action, student_id "
            "FROM consent_log WHERE student_id = ? ORDER BY rowid",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("privacy_policy", "v2026-08-26", "agreed"),
        ("media_consent", "v2026-08-26", "agreed"),
        ("media_consent", "v2026-08-26", "withdrawn"),
    ]
    assert all(r[3] == student_id for r in rows)


# ---------------------------------------------------------------------------
# 17-20. W6 PR-E — per-student status + mask-prefix resolution.
# The parent dashboard only holds the 8-char masked Student.id; sign /
# withdraw / status?student must accept the mask, resolve it inside the
# caller's reachable set, and never leak full ids to the client.
# ---------------------------------------------------------------------------

def _mask_of(full_id: str) -> str:
    return full_id[:8]


# 17. per-student status + withdraw round-trip via mask (PR-E happy path)
@pytest.mark.asyncio
async def test_consent_status_and_withdraw_via_mask(client, tmp_path):
    parent_id, email, pw = _create_parent_user("parent-pr-e@test.local")
    student_id = _create_db_student(parent_id=parent_id, first_name="小明")
    token = await _login_parent(client, email, pw)
    mask = _mask_of(student_id)
    headers = {**HEADERS, "Cookie": f"auth_session={token}"}

    # Fresh student: per-student status reports unsigned for everything.
    status = await client.get(
        f"/api/consent/status?student={mask}", headers=headers
    )
    assert status.status == 200
    docs = (await status.json())["documents"]
    assert docs["media_consent"]["status"] == "unsigned"
    assert docs["chat_consent"]["status"] == "unsigned"

    # Sign media consent scoped to the student, using the mask.
    sign = await client.post(
        "/api/consent/sign",
        json={
            "doc_type": "media_consent",
            "doc_version": "v2026-08-26",
            "student_id": mask,
        },
        headers=headers,
    )
    assert sign.status == 201, await sign.text()

    # The row is stored against the FULL student id — never the mask.
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        rows = conn.execute(
            "SELECT doc_version, action, student_id FROM consent_log "
            "WHERE doc_type = 'media_consent' AND student_id = ?",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("v2026-08-26", "agreed", student_id)]

    # Per-student status (mask == full id) now shows agreed.
    for param in (mask, student_id):
        status = await client.get(
            f"/api/consent/status?student={param}", headers=headers
        )
        assert status.status == 200
        assert (await status.json())["documents"]["media_consent"]["status"] == "agreed"

    # Withdraw via the mask → per-student status flips to withdrawn, and the
    # media takedown audit marker carries the full student id.
    withdraw = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": mask},
        headers=headers,
    )
    assert withdraw.status == 200, await withdraw.text()

    status = await client.get(
        f"/api/consent/status?student={mask}", headers=headers
    )
    assert (await status.json())["documents"]["media_consent"]["status"] == "withdrawn"

    audit = tmp_path / "audit_log.jsonl"
    events = [
        json.loads(line)
        for line in audit.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    marker = [e for e in events if e.get("event") == "media_takedown_pending"]
    assert len(marker) == 1
    assert marker[0]["student_id"] == student_id

    # Double withdraw through the mask collapses into the uniform 400.
    again = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent", "student_id": mask},
        headers=headers,
    )
    assert again.status == 400


# 18. account-level rows cover the student; per-student status honours the
# same scope as the chat gate (student rows + NULL rows, latest decides).
@pytest.mark.asyncio
async def test_consent_status_student_account_level_null_covers(client):
    parent_id, email, pw = _create_parent_user("parent-pr-e2@test.local")
    student_id = _create_db_student(parent_id=parent_id)
    token = await _login_parent(client, email, pw)
    mask = _mask_of(student_id)
    headers = {**HEADERS, "Cookie": f"auth_session={token}"}

    # Account-level chat_consent signature (no student_id).
    sign = await client.post(
        "/api/consent/sign",
        json={"doc_type": "chat_consent", "doc_version": "v2026-09-08"},
        headers=headers,
    )
    assert sign.status == 201, await sign.text()

    status = await client.get(
        f"/api/consent/status?student={mask}", headers=headers
    )
    assert status.status == 200
    docs = (await status.json())["documents"]
    assert docs["chat_consent"]["status"] == "agreed"
    # Student-scoped rows (none here) must not mask the NULL agreement.
    assert docs["privacy_policy"]["status"] == "unsigned"


# 19. foreign student's mask → 403, and the status endpoint stays silent on
# id existence (uniform 403, no hint).
@pytest.mark.asyncio
async def test_consent_status_foreign_student_mask_forbidden(client):
    parent_a, _, _ = _create_parent_user("parent-pr-e3-a@test.local")
    student_id = _create_db_student(parent_id=parent_a)
    _, email_b, pw_b = _create_parent_user("parent-pr-e3-b@test.local")
    token_b = await _login_parent(client, email_b, pw_b)

    resp = await client.get(
        f"/api/consent/status?student={_mask_of(student_id)}",
        headers={**HEADERS, "Cookie": f"auth_session={token_b}"},
    )
    assert resp.status == 403

    # A random 8-char mask that does not exist must look identical.
    resp = await client.get(
        "/api/consent/status?student=ffffffff",
        headers={**HEADERS, "Cookie": f"auth_session={token_b}"},
    )
    assert resp.status == 403


# 20. ambiguous mask (two reachable students sharing the prefix) → 400
@pytest.mark.asyncio
async def test_consent_status_ambiguous_mask_bad_request(client):
    parent_id, email, pw = _create_parent_user("parent-pr-e4@test.local")
    token = await _login_parent(client, email, pw)
    prefix = "abcd1234"
    now = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        for suffix, name in (("0000aaaaaaaaaaaa", "甲"), ("0000bbbbbbbbbbbb", "乙")):
            conn.execute(
                "INSERT INTO students (id, parent_id, first_name, age_band, "
                "lang_code, created_at) VALUES (?, ?, ?, 'P1-P3', 'zh-hk', ?)",
                (prefix + suffix, parent_id, name, now),
            )
        conn.commit()
    finally:
        conn.close()

    resp = await client.get(
        f"/api/consent/status?student={prefix}",
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert resp.status == 400
