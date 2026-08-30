"""W2 PR#2 — consent gate tests (12 cases, per PR brief §6).

Covers: registry + legal page SoT pairing, docs endpoint auth, sign
version-check + ip/user_agent capture, unknown doc_type, re-sign gate on
login (including version bump), media withdraw append-only + audit marker,
privacy withdraw rejection, and the code-level guard that the consent module
has no UPDATE/DELETE path on consent_log.

No real passwords anywhere: all fixtures use `test-pass-` prefix (guard
test 13 enforces this repo-wide).
"""

from __future__ import annotations

import datetime
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
    assert set(documents) == {"privacy_policy", "media_consent"}

    pp = documents["privacy_policy"]
    assert pp["current_version"] == "v2026-08-26"
    assert pp["required"] is True
    assert pp["title_zh"] == "私隱政策"
    assert pp["title_en"] == "Privacy Policy"

    mc = documents["media_consent"]
    assert mc["current_version"] == "v2026-08-26"
    assert mc["required"] is False
    assert mc["title_zh"] == "媒體同意書"
    assert mc["title_en"] == "Media Consent Form"

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
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    # Fresh user: privacy_policy required, unsigned → gate on.
    login1 = await _login(client)
    assert login1.status == 200
    body1 = await login1.json()
    assert body1["consent_required"] is True
    assert body1["missing_consent"] == ["privacy_policy"]
    token1 = _session_cookie(login1)

    # Sign privacy_policy at the current version.
    resp = await client.post(
        "/api/consent/sign",
        json={"doc_type": "privacy_policy", "doc_version": "v2026-08-26"},
        headers={**HEADERS, "Cookie": f"auth_session={token1}"},
    )
    assert resp.status == 201

    # Next login: gate off, nothing missing.
    login2 = await _login(client)
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
    await _register_teacher(client)

    login = await _login(client)
    assert login.status == 200
    body = await login.json()
    # Missing list contains only the required doc — media_consent is optional.
    assert body["missing_consent"] == ["privacy_policy"]


# ---------------------------------------------------------------------------
# 9. Version bump invalidates old agreement → gate re-triggers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_version_bump_re_triggers_re_sign_gate(
    client, fresh_invite, tmp_path, monkeypatch
):
    await _register_teacher(client)
    user = auth_db.get_user_by_email("teacher@test.local")

    # Sign at v2026-08-26 → gate off.
    login1 = await _login(client)
    token1 = _session_cookie(login1)
    await client.post(
        "/api/consent/sign",
        json={"doc_type": "privacy_policy", "doc_version": "v2026-08-26"},
        headers={**HEADERS, "Cookie": f"auth_session={token1}"},
    )
    login_ok = await _login(client)
    assert (await login_ok.json())["consent_required"] is False

    # Ship a new document version in the registry.
    yaml_path = tmp_path / "consent_docs.yaml"
    yaml_path.write_text(
        "documents:\n"
        "  privacy_policy:\n"
        '    current_version: "v2026-08-27"\n'
        "    required: true\n"
        '    title_zh: "私隱政策"\n'
        '    title_en: "Privacy Policy"\n'
        "  media_consent:\n"
        '    current_version: "v2026-08-26"\n'
        "    required: false\n"
        '    title_zh: "媒體同意書"\n'
        '    title_en: "Media Consent Form"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(consent_mod, "DOCS_PATH", str(yaml_path))

    # Old agreed row (v2026-08-26) no longer satisfies the gate.
    login3 = await _login(client)
    assert login3.status == 200
    body3 = await login3.json()
    assert body3["consent_required"] is True
    assert body3["missing_consent"] == ["privacy_policy"]

    # Old row still present (append-only, never mutated) but not current.
    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=user["id"], doc_type="privacy_policy"
    )
    assert [r[3] for r in rows] == ["agreed"]
    assert rows[0][2] == "v2026-08-26"


# ---------------------------------------------------------------------------
# 10. media withdraw: append-only + audit marker; repeat withdraw is fine
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

    # Withdraw media_consent.
    w1 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w1.status == 200

    # Repeat withdraw still succeeds (append-only, idempotent enough).
    w2 = await client.post(
        "/api/consent/withdraw",
        json={"doc_type": "media_consent"},
        headers={**HEADERS, "Cookie": f"auth_session={token}"},
    )
    assert w2.status == 200

    # All rows survive: agreed + withdrawn + withdrawn; old row untouched.
    rows = _consent_rows(
        os.environ["DREAMER_DB_PATH"], user_id=user["id"], doc_type="media_consent"
    )
    assert [r[3] for r in rows] == ["withdrawn", "withdrawn", "agreed"]

    # Status reflects the latest row.
    status = await client.get(
        "/api/consent/status", headers={"Cookie": f"auth_session={token}"}
    )
    assert status.status == 200
    status_body = await status.json()
    assert status_body["documents"]["media_consent"]["status"] == "withdrawn"
    assert status_body["documents"]["privacy_policy"]["status"] == "unsigned"

    # Audit log carries the media_takedown_pending marker (human 24h flow).
    audit_lines = [
        line for line in (tmp_path / "audit_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert len(audit_lines) == 2  # one per withdraw
    for line in audit_lines:
        record = __import__("json").loads(line)
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
