"""aiohttp.web application exposing the W2 auth core (PR#1) + consent gate (PR#2).

Endpoints:
    POST /api/auth/register      teacher-only (invite code + email + password)
    POST /api/auth/login         session cookie on success; re-sign gate
    POST /api/auth/logout        delete session row + clear cookie
    GET  /api/auth/me            current user (401 when not logged in)
    POST /api/auth/verify-email  consume single-use verification token
    GET  /api/consent/docs       registered documents + current versions
    POST /api/consent/sign       append agreed row (version-checked)
    POST /api/consent/withdraw   append withdrawn row (media only; audit marker)
    GET  /api/consent/status     latest per-document consent status
    GET  /legal/privacy-policy   embedded legal page (public)
    GET  /legal/media-consent    embedded legal page (public)

Hard specs implemented here (per PR brief §3):
- Session cookie: HttpOnly + Secure + SameSite=Lax (all three flags).
- Session token: secrets.token_urlsafe(32) — server-side DB row, 7 days.
  No JWT, nothing in localStorage.
- Brute force: 5 failed logins/email → lock 15 min (429 + unified wording);
  IP 20 failures/hour → IP lock 1 hour (in-memory, see security.py).
- Unified wording: login/register/verify failures all return the same
  401/400 + "email 或密碼不正確 / 請求無效" style; no path reveals email
  existence (dummy Argon2 verify on unknown email to equalize timing).
- CSRF: all POST /api/auth/* require header `X-Requested-With: XMLHttpRequest`
  (custom-header scheme, chosen over double-submit for simplicity; browser
  same-origin SPA requests set it via fetch). Missing header → 403.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any, Optional

from aiohttp import web

from . import classes as classes_mod
from . import consent
from . import db
from . import reports as reports_mod
from . import safety as safety_mod
from . import students as students_mod
from .email import send_reset_email, send_verification_email
from .security import (
    dummy_verify,
    forgot_email_limiter,
    forgot_ip_limiter,
    hash_password,
    hash_reset_token,
    ip_rate_limiter,
    new_session_token,
    new_verify_token,
    validate_password_strength,
    verify_password,
)

logger = logging.getLogger("dreamer.auth.api")

SESSION_COOKIE = "auth_session"
SESSION_DAYS = 7
LOCK_FAILURES = 5
LOCK_MINUTES = 15
VERIFY_HOURS = 24
RESET_TOKEN_MINUTES = 60  # W4 PR-D §3.2 — password reset link lifetime
STEP_UP_MINUTES = 10

# Student ids are never echoed in full to the frontend (W2 PR#3 brief §3:
# "student_id 唔准出現喺任何公開 URL/前端 state" — pin-verify URL paths are
# the single documented exception). Responses carry a fixed-length prefix.
STUDENT_ID_MASK_LEN = 8

_ERR_AUTH = {"error": "email 或密碼不正確"}
_ERR_INVALID = {"error": "請求無效"}
_ERR_INVITE_INVALID = {"error": "連結無效或已過期"}
_ERR_LOCKED = {"error": "嘗試次數過多，請稍後再試"}
_ERR_FORBIDDEN = {"error": "無權操作"}
_ERR_STEP_UP = {"error": "需要重新驗證密碼"}
_ERR_NOTHING_TO_WITHDRAW = {"error": "未有可撤回嘅同意紀錄"}
_ERR_PRIVACY_REQUIRED = {"error": "必須同意私隱政策先可以繼續"}
_ERR_CHAT_CONSENT_REQUIRED = {"error": "必須同意 AI 對話服務同意書先可以繼續"}

# Student profile enumerations (B24: no last_name / school / other PII).
AGE_BANDS = ("P1-P3", "P4-P6", "S1-S3")
LANG_CODES = ("en", "zh-hk", "zh-cn")


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _future_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _client_ip(request: web.Request) -> str:
    # Behind a reverse proxy, prefer X-Forwarded-For first entry; otherwise
    # fall back to the peer address. Never trust it for anything stronger
    # than rate limiting.
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    peername = request.transport.get_extra_info("peername") if request.transport else None
    if peername:
        return str(peername[0])
    return "unknown"


def _public_user(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "email_verified": bool(row["email_verified"]),
    }


async def _read_json(request: web.Request) -> Optional[dict[str, Any]]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


# ---------------------------------------------------------------------------
# CSRF middleware — custom header check on all auth POSTs
# ---------------------------------------------------------------------------

@web.middleware
async def csrf_guard(request: web.Request, handler):
    if request.method == "POST":
        path = request.path
        protected = (
            path.startswith("/api/auth/")
            or path.startswith("/api/consent/")
            or path.startswith("/api/classes")
            or path.startswith("/api/students")
            or path.startswith("/api/teacher/")
            or path == "/api/invites"
            # The parent 1-click confirm link is opened from an email, not
            # from the SPA — no custom header there. Every other invite POST
            # (create / resend) is an SPA call and must carry the header.
            or (
                path.startswith("/api/invites/")
                and not path.endswith("/confirm")
            )
        )
        if protected and request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return web.json_response(_ERR_INVALID, status=403)
    return await handler(request)


def _session_user(request: web.Request) -> Optional[dict[str, Any]]:
    """Resolve the logged-in user from the session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return db.get_session_user(token)


def _log_security_warning(
    event: str, *, user_id: str, target_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Best-effort security log line (WARNING, JSONL audit channel)."""
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "WARNING",
            "event": event,
            "user_id": user_id,
            "target_id": target_id,
            "message": detail or event,
        }
    )


def _mask_student_id(student_id: str) -> str:
    """Fixed-length prefix — full student ids never leave the server."""
    return student_id[:STUDENT_ID_MASK_LEN]


def _public_student(row) -> dict[str, Any]:
    return {
        "id": _mask_student_id(row["id"]),
        "first_name": row["first_name"],
        "age_band": row["age_band"],
        "lang_code": row["lang_code"],
    }


def _consent_student_owned(user, student_id: Optional[str]) -> bool:
    """§0 ownership gate for sign/withdraw with a student_id.

    When no student_id is supplied the request is unconstrained (account
    level consent). When present, the student must exist and belong to the
    current user as parent (students.parent_id == user.id); a student with
    parent_id NULL (not yet bound) is rejected. Unknown ids and foreign
    students share the same 403 so the response never reveals whether a
    student id exists.
    """
    if not student_id:
        return True
    student = students_mod.get_student_by_id(student_id)
    if student is None:
        return False
    if student["parent_id"] is None:
        return False
    return student["parent_id"] == user["id"]


def _pin_authorized(user, student) -> bool:
    """Authorisation for PIN endpoints: parent owns the student, the
    teacher teaches a class containing the student, or the caller is an
    admin (reachable set = all students, matching the prefix-resolution
    scope)."""
    if user["role"] == "parent":
        return bool(student["parent_id"]) and student["parent_id"] == user["id"]
    if user["role"] == "teacher":
        return classes_mod.teacher_teaches_student(user["id"], student["id"])
    if user["role"] == "admin":
        return True
    return False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_register(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    invite_code = str(payload.get("invite_code") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    password = payload.get("password")

    if not invite_code or not email or not isinstance(password, str) or not password:
        return web.json_response(_ERR_INVALID, status=400)

    if validate_password_strength(password) is not None:
        return web.json_response(_ERR_INVALID, status=400)

    # Unified timing: even when the email already exists we burn an Argon2
    # verify so the response time does not reveal registration status.
    existing = db.get_user_by_email(email)
    if existing is not None:
        dummy_verify(password)
        return web.json_response(_ERR_INVALID, status=400)

    invite = db.is_invite_valid(invite_code)
    if invite is None:
        dummy_verify(password)
        return web.json_response(_ERR_INVALID, status=400)

    user_id = str(uuid.uuid4())
    verify_token = new_verify_token()
    db.create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(password),
        role="teacher",
        email_verified=False,
        email_verify_token=verify_token,
        email_verify_expires_at=_future_iso(hours=VERIFY_HOURS),
    )
    db.mark_invite_used(invite_code, user_id)

    # Fire-and-forget verification email — never blocks the response.
    sent = send_verification_email(to_addr=email, token=verify_token)
    if not sent:
        logger.warning(
            "verification email not sent for user=%s (SMTP unavailable)", user_id
        )

    user = db.get_user_by_id(user_id)
    return web.json_response({"user": _public_user(user)}, status=201)


async def handle_login(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    email = str(payload.get("email") or "").strip().lower()
    password = payload.get("password")
    ip = _client_ip(request)

    if not email or not isinstance(password, str) or not password:
        return web.json_response(_ERR_INVALID, status=400)

    # IP-level block (20 failures/hour, in-memory).
    if ip_rate_limiter.is_blocked(ip):
        return web.json_response(_ERR_LOCKED, status=429)

    user = db.get_user_by_email(email)
    if user is None:
        # Timing equalizer for unknown email.
        dummy_verify(password)
        return web.json_response(_ERR_AUTH, status=401)

    # Email-level lockout window.
    lock_until = user["lock_until"]
    if lock_until and lock_until > _now_iso():
        return web.json_response(_ERR_LOCKED, status=429)

    if not verify_password(password, user["password_hash"]):
        new_count = int(user["failed_logins"] or 0) + 1
        if new_count >= LOCK_FAILURES:
            db.set_user_lock(user["id"], _future_iso(minutes=LOCK_MINUTES))
            logger.warning(
                "login lock triggered email=%s ip=%s failures=%d",
                user["email"], ip, new_count,
            )
        else:
            db.increment_failed_logins(user["id"], new_count)
        ip_rate_limiter.record_failure(ip)
        return web.json_response(_ERR_AUTH, status=401)

    # Success — clear counters and create a server-side session.
    db.reset_failed_logins(user["id"])
    ip_rate_limiter.reset(ip)

    token = new_session_token()
    db.create_session(
        session_id=token,
        user_id=user["id"],
        expires_at=_future_iso(days=SESSION_DAYS),
        created_ip=ip,
    )

    # W2 PR#2 re-sign gate: required documents without a current-version
    # agreed row force the frontend to show the re-sign page.
    missing = consent.required_consent_gaps(user["id"])

    resp = web.json_response(
        {
            "user": _public_user(user),
            "consent_required": bool(missing),
            "missing_consent": missing,
        }
    )
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return resp


async def handle_logout(request: web.Request) -> web.Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
    resp = web.json_response({"ok": True})
    resp.del_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return resp


async def handle_me(request: web.Request) -> web.Response:
    token = request.cookies.get(SESSION_COOKIE)
    user = db.get_session_user(token) if token else None
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    return web.json_response({"user": _public_user(user)})


async def handle_verify_email(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    token = str(payload.get("token") or "").strip()
    if not token:
        return web.json_response(_ERR_INVALID, status=400)

    user = db.consume_email_verify_token(token)
    if user is None:
        # Unknown / expired / already-used token — unified wording.
        return web.json_response(_ERR_INVALID, status=400)

    return web.json_response({"user": _public_user(user)})


# ---------------------------------------------------------------------------
# Forgot-password / reset-password (W4 PR-D, B-新2)
# ---------------------------------------------------------------------------

async def handle_forgot_password(request: web.Request) -> web.Response:
    """POST /api/auth/forgot-password — request a password-reset email.

    Anti-enumeration: the response is identical whether or not the email is
    registered (200 + {"ok": true}), and the unknown-email path burns a dummy
    Argon2 verify so CPU timing does not reveal account existence either.
    Rate limited per-email (3/hour) and per-IP (30/hour) — boss ruling
    2026-09-07. New tokens invalidate any older pending one (single valid
    link at a time).
    """
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    email = str(payload.get("email") or "").strip().lower()
    if not email:
        return web.json_response(_ERR_INVALID, status=400)

    ip = _client_ip(request)

    # Limit BEFORE the lookup so registered and unregistered emails behave
    # identically; every request counts (bombers repeat successes too).
    if not forgot_email_limiter.allow(email) or not forgot_ip_limiter.allow(ip):
        return web.json_response(_ERR_LOCKED, status=429)

    user = db.get_user_by_email(email)
    if user is None:
        # Timing equalizer for unknown email (same philosophy as login).
        dummy_verify("reset-dummy-password-not-a-real-one")
        return web.json_response({"ok": True})

    raw_token = new_verify_token()
    db.insert_password_reset_token(
        user_id=user["id"],
        token_hash=hash_reset_token(raw_token),
        expires_at=_future_iso(minutes=RESET_TOKEN_MINUTES),
    )

    base_url = classes_mod.get_frontend_base_url()
    link = f"{base_url.rstrip('/')}/reset?token={raw_token}"
    # users has no lang_code; account language comes from its students rows
    # (teacher_id / parent_id). None → email falls back to zh-hk (§3.3).
    lang = db.get_user_lang_code(user["id"]) or "zh-hk"
    sent = send_reset_email(to_addr=email, link=link, lang=lang)
    if not sent:
        logger.warning(
            "reset email not sent for user=%s (SMTP unavailable)", user["id"]
        )
    return web.json_response({"ok": True})


async def handle_reset_password(request: web.Request) -> web.Response:
    """POST /api/auth/reset-password — consume a reset token, set new password.

    Side effects on success: token marked used_at (single-use, no replay),
    ALL of the user's sessions revoked (old cookies immediately 401), and an
    audit-log row is written — the token itself is never logged (plaintext or
    hash).
    """
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    token = str(payload.get("token") or "").strip()
    password = payload.get("password")
    if not token or not isinstance(password, str) or not password:
        return web.json_response(_ERR_INVALID, status=400)
    if validate_password_strength(password) is not None:
        return web.json_response(_ERR_INVALID, status=400)

    user = db.consume_password_reset_token(hash_reset_token(token))
    if user is None:
        # Unknown / expired / already-used token — unified wording.
        return web.json_response(_ERR_INVITE_INVALID, status=400)

    db.update_user_password(user["id"], hash_password(password))
    db.revoke_all_sessions(user["id"])

    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "password_reset",
            "user_id": user["id"],
            "target_id": None,
            "message": "password reset via emailed link",
        }
    )
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Step-up auth (W2 PR#4)
# ---------------------------------------------------------------------------

def _require_stepped_up(request: web.Request) -> Optional[web.Response]:
    """Fresh per-request step-up check (sessions.stepped_up_until > now).

    The session row is read on every protected request — the step-up state
    is never cached outside the request, and no separate cookie/JWT is used.
    Returns an error response when not stepped up, else None.
    """
    token = request.cookies.get(SESSION_COOKIE)
    session = db.get_session_row(token) if token else None
    if session is None:
        return web.json_response(_ERR_AUTH, status=401)
    until = session["stepped_up_until"]
    if not until or until <= _now_iso():
        return web.json_response(_ERR_STEP_UP, status=403)
    return None


async def handle_step_up(request: web.Request) -> web.Response:
    """POST /api/auth/step-up — re-authenticate the current session.

    Body carries the current account's login password (never a new password
    or a student PIN). On success the session row gains `stepped_up_until`
    = now + 10 minutes; the state lives in the server-side session only.
    Wrong passwords share the login unified wording and flow into the
    existing failed_logins / lockout machinery (no second counter).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    password = payload.get("password")
    if not isinstance(password, str) or not password:
        return web.json_response(_ERR_INVALID, status=400)

    ip = _client_ip(request)
    if ip_rate_limiter.is_blocked(ip):
        return web.json_response(_ERR_LOCKED, status=429)

    lock_until = user["lock_until"]
    if lock_until and lock_until > _now_iso():
        return web.json_response(_ERR_LOCKED, status=429)

    if not verify_password(password, user["password_hash"]):
        new_count = int(user["failed_logins"] or 0) + 1
        if new_count >= LOCK_FAILURES:
            db.set_user_lock(user["id"], _future_iso(minutes=LOCK_MINUTES))
            logger.warning(
                "step-up lock triggered email=%s ip=%s failures=%d",
                user["email"], ip, new_count,
            )
        else:
            db.increment_failed_logins(user["id"], new_count)
        ip_rate_limiter.record_failure(ip)
        return web.json_response(_ERR_AUTH, status=401)

    db.reset_failed_logins(user["id"])
    ip_rate_limiter.reset(ip)

    token = request.cookies.get(SESSION_COOKIE)
    until = _future_iso(minutes=STEP_UP_MINUTES)
    db.set_session_stepped_up(token, until)
    return web.json_response({"ok": True, "expires_at": until})


# ---------------------------------------------------------------------------
# Consent gate (W2 PR#2)
# ---------------------------------------------------------------------------

async def handle_consent_docs(request: web.Request) -> web.Response:
    """GET /api/consent/docs — registry (current_version + required + titles)."""
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    docs = consent.load_consent_docs()
    documents = {}
    for doc_type, cfg in docs["documents"].items():
        documents[doc_type] = {
            "doc_type": doc_type,
            "current_version": cfg["current_version"],
            "required": bool(cfg.get("required")),
            "title_zh": cfg.get("title_zh", ""),
            "title_en": cfg.get("title_en", ""),
        }
    return web.json_response({"documents": documents})


async def handle_consent_sign(request: web.Request) -> web.Response:
    """POST /api/consent/sign — append agreed row; server checks version."""
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    doc_type = str(payload.get("doc_type") or "").strip()
    doc_version = str(payload.get("doc_version") or "").strip()
    student_id = str(payload.get("student_id") or "").strip() or None

    doc = consent.get_doc_config(doc_type)
    if doc is None:
        # Unknown doc_type — unified invalid wording, no hint of valid keys.
        return web.json_response(_ERR_INVALID, status=400)
    if doc_version != doc["current_version"]:
        # Refuse signing an old / fake / missing version.
        return web.json_response(_ERR_INVALID, status=400)

    # W2 PR#3 §0: when a student_id is supplied the signer must be that
    # student's bound parent; otherwise 403 (unified, no id-existence hint).
    if not _consent_student_owned(user, student_id):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    consent.insert_consent_row(
        user_id=user["id"],
        doc_type=doc_type,
        doc_version=doc_version,
        action="agreed",
        ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        student_id=student_id,
    )
    return web.json_response({"ok": True, "doc_type": doc_type}, status=201)


async def handle_consent_withdraw(request: web.Request) -> web.Response:
    """POST /api/consent/withdraw — append withdrawn row (never mutate old).

    media_consent: allowed only when a current-version agreed row covers
    the withdraw scope (P3-2 prior-agree gate); success writes an audit-log
    media_takedown_pending marker for the human 24h takedown flow. A second
    withdraw is rejected by the same gate — nothing to withdraw.
    privacy_policy: rejected — withdrawing privacy consent equals an account
    deactivation request, handled manually via info@.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    doc_type = str(payload.get("doc_type") or "").strip()
    student_id = str(payload.get("student_id") or "").strip() or None

    if doc_type not in consent.DOC_TYPES:
        return web.json_response(_ERR_INVALID, status=400)

    if doc_type == "privacy_policy":
        return web.json_response(
            {
                "error": "私隱政策係使用服務嘅前提，唔可以喺度撤回；如要停用帳戶，請電郵 info@dreamer-aiedu.com",
                "email": "info@dreamer-aiedu.com",
            },
            status=400,
        )

    doc = consent.get_doc_config(doc_type)
    if doc is None:
        return web.json_response(_ERR_INVALID, status=400)

    # W2 PR#3 §0: same ownership gate as sign — withdraw with a student_id
    # is only allowed for that student's bound parent.
    if not _consent_student_owned(user, student_id):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    # P3-2 prior-agree gate: without a current-version agreed row covering
    # this scope there is nothing to withdraw — uniform 400, zero writes,
    # zero fake WARNING rows. This also collapses the double-withdraw path
    # (latest row already `withdrawn`) into the same gate.
    if not consent.has_withdrawable_agreement(
        user["id"], doc_type, student_id=student_id
    ):
        return web.json_response(_ERR_NOTHING_TO_WITHDRAW, status=400)

    consent.insert_consent_row(
        user_id=user["id"],
        doc_type=doc_type,
        doc_version=doc["current_version"],
        action="withdrawn",
        ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        student_id=student_id,
    )

    if doc_type == "media_consent":
        consent.record_media_takedown_pending(
            user_id=user["id"], student_id=student_id
        )

    return web.json_response({"ok": True, "doc_type": doc_type})


async def handle_consent_status(request: web.Request) -> web.Response:
    """GET /api/consent/status — latest per-document consent state."""
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    return web.json_response(
        {"documents": consent.status_for_user(user["id"])}
    )


async def handle_legal_page(request: web.Request) -> web.Response:
    """GET /legal/{slug} — embedded legal page (public, version from YAML)."""
    slug = request.match_info.get("slug", "")
    html = consent.render_legal_page(slug)
    if html is None:
        return web.json_response(_ERR_INVALID, status=404)
    return web.Response(
        text=html,
        content_type="text/html",
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# Classes + students + PIN + invites (W2 PR#3)
# ---------------------------------------------------------------------------

def _validate_student_profile(payload: dict[str, Any]) -> Optional[str]:
    """Validate first_name / age_band / lang_code; return error wording or
    None when valid. Raises nothing — callers map None to proceed."""
    first_name = str(payload.get("first_name") or "").strip()
    age_band = str(payload.get("age_band") or "").strip()
    lang_code = str(payload.get("lang_code") or "").strip()
    if not first_name:
        return "請求無效"
    if age_band not in AGE_BANDS:
        return "請求無效"
    if lang_code not in LANG_CODES:
        return "請求無效"
    return None


def _resolve_pin(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (pin, pin_hash). Uses the supplied PIN when present and valid,
    otherwise generates one. Callers pre-validate with is_valid_pin."""
    raw = payload.get("pin")
    if raw is not None:
        pin = str(raw).strip()
        if students_mod.is_valid_pin(pin):
            return pin, students_mod.hash_pin(pin)
    pin = students_mod.generate_pin()
    return pin, students_mod.hash_pin(pin)


async def handle_create_class(request: web.Request) -> web.Response:
    """POST /api/classes — teacher creates a class (own classes only).

    W3-C: accepts optional class_type (monthly/workshop), grade_band
    (P1-P3/P4-P6/S1-S3) and is_one_on_one (0/1). Defaults keep old clients
    working: class_type=monthly, grade_band=NULL, is_one_on_one=0.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 60:
        return web.json_response(_ERR_INVALID, status=400)

    class_type = str(payload.get("class_type") or "monthly").strip()
    if class_type not in ("monthly", "workshop"):
        return web.json_response(_ERR_INVALID, status=400)

    grade_band_raw = payload.get("grade_band")
    grade_band: Optional[str] = None
    if grade_band_raw not in (None, ""):
        grade_band = str(grade_band_raw).strip()
        if grade_band not in AGE_BANDS:
            return web.json_response(_ERR_INVALID, status=400)

    is_one_on_one = payload.get("is_one_on_one") in (True, 1, "1", "true")

    class_id = classes_mod.create_class(
        teacher_id=user["id"],
        name=name,
        class_type=class_type,
        grade_band=grade_band,
        is_one_on_one=is_one_on_one,
    )
    cls = classes_mod.get_class_by_id(class_id)
    return web.json_response(
        {
            "class": {
                "id": cls["id"],
                "name": cls["name"],
                "join_code": cls["join_code"],
                "class_type": cls["class_type"],
                "grade_band": cls["grade_band"],
                "is_one_on_one": int(cls["is_one_on_one"] or 0),
            }
        },
        status=201,
    )


async def handle_list_classes(request: web.Request) -> web.Response:
    """GET /api/classes — teacher's classes with pending/confirmed counts."""
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)
    return web.json_response(
        {"classes": classes_mod.list_classes_for_teacher(user["id"])}
    )


async def handle_create_student(request: web.Request) -> web.Response:
    """POST /api/students — parent adds a student with a PIN.

    Response carries only the masked student id (fixed-length prefix), never
    the full id (W2 PR#3 §3). A generated PIN is echoed once so the parent
    can store it; when the parent supplied the PIN it is not echoed.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    err = _validate_student_profile(payload)
    if err is not None:
        return web.json_response(_ERR_INVALID, status=400)

    raw_pin = payload.get("pin")
    if raw_pin is not None and not students_mod.is_valid_pin(str(raw_pin).strip()):
        return web.json_response(_ERR_INVALID, status=400)
    pin, pin_hash = _resolve_pin(payload)

    student_id = students_mod.create_student(
        parent_id=user["id"],
        first_name=str(payload["first_name"]).strip(),
        age_band=str(payload["age_band"]).strip(),
        lang_code=str(payload["lang_code"]).strip(),
        pin_hash=pin_hash,
    )
    student = students_mod.get_student_by_id(student_id)
    resp = {
        "student": _public_student(student),
    }
    if raw_pin is None:
        resp["pin"] = pin
    return web.json_response(resp, status=201)


async def handle_list_students(request: web.Request) -> web.Response:
    """GET /api/students — parent's own students / teacher's class students."""
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    if user["role"] == "parent":
        rows = students_mod.list_students_for_parent(user["id"])
    elif user["role"] == "teacher":
        rows = classes_mod.list_students_for_teacher(user["id"])
    else:
        return web.json_response(_ERR_FORBIDDEN, status=403)

    return web.json_response(
        {"students": [_public_student(row) for row in rows]}
    )


async def handle_pin_verify(request: web.Request) -> web.Response:
    """POST /api/students/{id}/pin-verify — check a PIN against a student.

    {id} accepts a full student id (legacy) or the 8-char mask prefix; the
    prefix is resolved within the current user's reachable set (parent =
    own children, teacher = own classes, admin = all). Unique match
    proceeds; no match and unknown full ids share the same 403 wording (no
    id-existence oracle); multiple prefix matches return 400. Only the
    bound parent or a teacher teaching the student may verify. A pending
    (not yet teacher-confirmed) student is rejected with 403 等待老師確認 so
    the PIN cannot be probed before the teacher approves the binding. 10
    consecutive wrong PINs lock the student for 1 minute (429).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    student_id = request.match_info.get("id", "")
    student, ambiguous = students_mod.resolve_student_identifier(
        student_id, user
    )
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    if not _pin_authorized(user, student):
        _log_security_warning(
            "pin_verify_cross_access",
            user_id=user["id"],
            target_id=student_id,
            detail="unauthorised PIN verify attempt",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    if not classes_mod.student_class_confirmed(student["id"]):
        return web.json_response({"error": "等待老師確認"}, status=403)

    # Lockout bookkeeping is keyed by the resolved full student id — never
    # by the raw {id} path segment (which may be an 8-char mask prefix).
    lock_remaining = students_mod.pin_lock_remaining(student["id"])
    if lock_remaining is not None:
        return web.json_response(_ERR_LOCKED, status=429)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)
    pin = str(payload.get("pin") or "").strip()
    if not students_mod.is_valid_pin(pin):
        return web.json_response(_ERR_INVALID, status=400)

    if student["pin_hash"] is None:
        # Data anomaly: a confirmed student without a PIN hash. Return the
        # uniform wrong-PIN wording (never a 500 from verify_pin(None)),
        # do NOT touch the lockout counter (not a guessing failure) and
        # leave a server-side WARNING trail for the operator.
        _log_security_warning(
            "pin_verify_null_pinhash",
            user_id=user["id"],
            target_id=student["id"],
            detail="confirmed student has NULL pin_hash",
        )
        return web.json_response({"error": "PIN 不正確"}, status=401)

    if not students_mod.verify_pin(pin, student["pin_hash"]):
        count = students_mod.record_pin_failure(student["id"])
        if count == 0 and students_mod.pin_lock_remaining(student["id"]) is not None:
            _log_security_warning(
                "pin_locked",
                user_id=user["id"],
                target_id=student["id"],
                detail="student PIN locked after 10 consecutive failures",
            )
        return web.json_response({"error": "PIN 不正確"}, status=401)

    students_mod.clear_pin_failures(student["id"])
    return web.json_response({"ok": True})


async def handle_pin_reset(request: web.Request) -> web.Response:
    """POST /api/students/{id}/pin-reset — parent/teacher resets a PIN.

    {id} accepts a full student id (legacy) or the 8-char mask prefix
    resolved within the current user's reachable set (same rules as
    pin-verify: unique match proceeds, no match 403, multiple matches 400).
    New PIN is supplied in the payload or generated server-side. The reset
    is audit-logged (INFO) with user + student ids.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)

    student_id = request.match_info.get("id", "")
    student, ambiguous = students_mod.resolve_student_identifier(
        student_id, user
    )
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    if not _pin_authorized(user, student):
        _log_security_warning(
            "pin_reset_cross_access",
            user_id=user["id"],
            target_id=student_id,
            detail="unauthorised PIN reset attempt",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)
    raw_pin = payload.get("pin")
    if raw_pin is not None and not students_mod.is_valid_pin(str(raw_pin).strip()):
        return web.json_response(_ERR_INVALID, status=400)
    pin, pin_hash = _resolve_pin(payload)

    students_mod.set_pin(student_id, pin_hash)
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "pin_reset",
            "user_id": user["id"],
            "student_id": student_id,
        }
    )
    resp = {"ok": True}
    if raw_pin is None:
        resp["pin"] = pin
    return web.json_response(resp)


async def handle_create_invite(request: web.Request) -> web.Response:
    """POST /api/invites — teacher invites a parent to a class.

    Creates student + pending class_students + 72h invite in one shot,
    then sends the bilingual confirmation email (fire-and-forget). Rate
    limited to 20 invites+resends per teacher per day (429 when exceeded).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    err = _validate_student_profile(payload)
    if err is not None:
        return web.json_response(_ERR_INVALID, status=400)

    parent_email = str(payload.get("parent_email") or "").strip().lower()
    if not parent_email or "@" not in parent_email or len(parent_email) > 255:
        return web.json_response(_ERR_INVALID, status=400)

    class_id = str(payload.get("class_id") or "").strip()
    cls = classes_mod.get_class_by_id(class_id)
    if cls is None or cls["teacher_id"] != user["id"]:
        _log_security_warning(
            "invite_cross_teacher",
            user_id=user["id"],
            target_id=class_id,
            detail="attempted to invite into a class owned by another teacher",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    if classes_mod.daily_invite_count(user["id"]) >= classes_mod.DAILY_INVITE_LIMIT:
        return web.json_response({"error": "今日邀請名額已用完"}, status=429)

    raw_pin = payload.get("pin")
    if raw_pin is not None and not students_mod.is_valid_pin(str(raw_pin).strip()):
        return web.json_response(_ERR_INVALID, status=400)
    pin, pin_hash = _resolve_pin(payload)

    student_id, token = classes_mod.create_invite_flow(
        teacher_id=user["id"],
        class_id=class_id,
        first_name=str(payload["first_name"]).strip(),
        age_band=str(payload["age_band"]).strip(),
        lang_code=str(payload["lang_code"]).strip(),
        pin_hash=pin_hash,
        parent_email=parent_email,
    )
    base_url = classes_mod.get_frontend_base_url()
    classes_mod.send_invite_email(
        to_addr=parent_email, token=token, base_url=base_url
    )
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "invite_created",
            "user_id": user["id"],
            "teacher_id": user["id"],
            "class_id": class_id,
            "student_id": student_id,
            "parent_email": parent_email,
        }
    )
    resp = {"message": "邀請已發送"}
    if raw_pin is None:
        resp["pin"] = pin
    return web.json_response(resp, status=201)


async def handle_invite_public(request: web.Request) -> web.Response:
    """GET /api/invites/{token} — public read-only invite lookup.

    The token itself is the credential (same trust level as confirm, no
    login session required). Returns only the four public fields:
    first_name / age_band / lang_code / parent_email (the invite's parent
    address, echoed back for the parent to double-check). Invalid /
    expired / used / superseded tokens all map to the same 400 wording as
    confirm (_ERR_INVITE_INVALID). GET is never CSRF-protected (the guard
    only inspects POSTs); a basic per-IP rate limit applies. The full
    student id is never returned.
    """
    token = request.match_info.get("token", "")
    ip = _client_ip(request)

    if ip_rate_limiter.is_blocked(ip):
        return web.json_response(_ERR_LOCKED, status=429)

    info = classes_mod.get_invite_public_by_token(token)
    if info is None:
        ip_rate_limiter.record_failure(ip)
        return web.json_response(_ERR_INVITE_INVALID, status=400)

    ip_rate_limiter.reset(ip)
    return web.json_response(info)


async def handle_confirm_invite(request: web.Request) -> web.Response:
    """POST /api/invites/{token}/confirm — parent 1-click confirm.

    Called from the email link (no X-Requested-With, CSRF-exempt by design).
    privacy_policy and chat_consent agreements are both mandatory (W6
    PR-D: one checkbox binds the two required consents; the API keeps
    both flags explicit so no caller can half-sign): without both the
    whole confirm is rejected and no rows are written. Creates the parent account (verified)
    + consent rows + parent binding + session in one transaction.
    """
    token = request.match_info.get("token", "")
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    password = payload.get("password")
    if validate_password_strength(password) is not None:
        return web.json_response(_ERR_INVALID, status=400)

    privacy_agreed = payload.get("privacy_policy")
    if not isinstance(privacy_agreed, bool) or not privacy_agreed:
        # P3-4: explicit wording — privacy_policy is the mandatory gate.
        return web.json_response(_ERR_PRIVACY_REQUIRED, status=400)
    chat_agreed = payload.get("chat_consent")
    if not isinstance(chat_agreed, bool) or not chat_agreed:
        # W6 PR-D: register binds privacy + chat to one required checkbox;
        # the API keeps both flags explicit so no caller can half-sign.
        return web.json_response(_ERR_CHAT_CONSENT_REQUIRED, status=400)
    media_agreed = bool(payload.get("media_consent"))

    privacy_doc = consent.get_doc_config("privacy_policy")
    chat_doc = consent.get_doc_config("chat_consent")
    media_doc = consent.get_doc_config("media_consent")
    if privacy_doc is None or chat_doc is None or media_doc is None:
        return web.json_response(_ERR_INVALID, status=400)

    parent_user_id = str(uuid.uuid4())
    session_id = new_session_token()
    expires_at = _future_iso(days=SESSION_DAYS)
    result = classes_mod.confirm_invite_flow(
        token=token,
        parent_user_id=parent_user_id,
        password_hash=hash_password(password),
        privacy_version=privacy_doc["current_version"],
        chat_version=chat_doc["current_version"],
        media_version=media_doc["current_version"],
        media_agreed=media_agreed,
        session_id=session_id,
        session_expires_at=expires_at,
        ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    if result is None:
        return web.json_response(_ERR_INVITE_INVALID, status=400)

    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "invite_confirmed",
            "user_id": parent_user_id,
            "parent_user_id": parent_user_id,
            "student_id": result["student_id"],
            "class_id": result["class_id"],
        }
    )
    # W3-C 通知-1 — email the class teacher (class-owner route, never
    # hardcoded). Fail-silent + audited; never blocks the confirm flow.
    _notify_teacher_pending(
        class_id=result["class_id"],
        student_id=result["student_id"],
        actor_user_id=parent_user_id,
    )
    resp = web.json_response(
        {"ok": True, "user": {"id": parent_user_id, "email": result["parent_email"]}},
        status=201,
    )
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return resp


async def handle_resend_invite(request: web.Request) -> web.Response:
    """POST /api/invites/{token}/resend — teacher re-sends an invite link.

    Old token is superseded (single valid link at a time). Shares the daily
    invite budget. Cross-teacher / already-used tokens are rejected.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    token = request.match_info.get("token", "")
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)

    invite = classes_mod.get_invite_by_token(token)
    if invite is None:
        return web.json_response(_ERR_INVALID, status=400)
    if invite["created_by"] != user["id"]:
        _log_security_warning(
            "invite_resend_cross_teacher",
            user_id=user["id"],
            target_id=token,
            detail="attempted to resend another teacher's invite",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)
    if invite["used_at"] is not None:
        return web.json_response(_ERR_INVALID, status=400)

    if classes_mod.daily_invite_count(user["id"]) >= classes_mod.DAILY_INVITE_LIMIT:
        return web.json_response({"error": "今日邀請名額已用完"}, status=429)

    new_email = str(payload.get("parent_email") or "").strip().lower() or None
    if new_email is not None and (
        "@" not in new_email or len(new_email) > 255
    ):
        return web.json_response(_ERR_INVALID, status=400)

    new_token = classes_mod.resend_invite(
        teacher_id=user["id"], token=token, new_parent_email=new_email
    )
    base_url = classes_mod.get_frontend_base_url()
    classes_mod.send_invite_email(
        to_addr=(new_email or invite["parent_email"]),
        token=new_token,
        base_url=base_url,
    )
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "invite_resent",
            "user_id": user["id"],
            "teacher_id": user["id"],
            "class_id": invite["class_id"],
            "student_id": invite["student_id"],
            "old_token": token,
            "new_token": new_token,
        }
    )
    return web.json_response({"message": "邀請已重發"})


async def handle_confirm_class_student(request: web.Request) -> web.Response:
    """POST /api/classes/{id}/confirm — teacher approves a pending binding.

    Four conditions enforced in the DAO: own class / student in class /
    status=pending / parent already bound. Cross-teacher attempts are
    logged as security WARNING before the unified 403.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    class_id = request.match_info.get("id", "")
    payload = await _read_json(request)
    if not payload:
        return web.json_response(_ERR_INVALID, status=400)
    student_id = str(payload.get("student_id") or "").strip()
    if not student_id:
        return web.json_response(_ERR_INVALID, status=400)

    cls = classes_mod.get_class_by_id(class_id)
    if cls is not None and cls["teacher_id"] != user["id"]:
        _log_security_warning(
            "class_confirm_cross_teacher",
            user_id=user["id"],
            target_id=class_id,
            detail="attempted to confirm a class owned by another teacher",
        )

    ok, reason = classes_mod.confirm_class_student(
        teacher_id=user["id"], class_id=class_id, student_id=student_id
    )
    if not ok:
        if reason == "forbidden":
            return web.json_response(_ERR_FORBIDDEN, status=403)
        return web.json_response(_ERR_INVALID, status=400)

    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "class_student_confirmed",
            "user_id": user["id"],
            "teacher_id": user["id"],
            "class_id": class_id,
            "student_id": student_id,
        }
    )
    # W3-C 通知-2 — email the parent (formal, parent-facing tone) after the
    # teacher confirms. Fail-silent + audited; never blocks the response.
    _notify_parent_confirmed(
        class_id=class_id,
        student_id=student_id,
        actor_user_id=user["id"],
    )
    return web.json_response({"ok": True, "status": "confirmed"})


# ---------------------------------------------------------------------------
# W3-C lifecycle notifications (通知-1 / 通知-2) + teacher pending console
# ---------------------------------------------------------------------------

def _notify_teacher_pending(
    *, class_id: str, student_id: str, actor_user_id: str
) -> None:
    """通知-1 — email the class teacher after a parent confirms an invite.

    Recipient routing follows the class owner (classes.teacher_id), never a
    hardcoded address. Fail-silent contract: SMTP failures only downgrade
    the audit level, they never raise into the confirm flow.
    """
    info = classes_mod.teacher_notify_info(class_id=class_id, student_id=student_id)
    if info is None:
        consent.write_audit_log(
            {
                "timestamp": _now_iso(),
                "level": "WARNING",
                "event": "notify_teacher_pending_skipped",
                "user_id": actor_user_id,
                "class_id": class_id,
                "student_id": student_id,
                "detail": "teacher_notify_info returned None (no class row)",
            }
        )
        return
    ok = classes_mod.send_teacher_pending_notice(
        to_addr=info["teacher_email"],
        student_label=classes_mod.student_label(info),
        class_name=info["class_name"],
        base_url=classes_mod.get_frontend_base_url(),
    )
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO" if ok else "WARNING",
            "event": "notify_teacher_pending",
            "user_id": actor_user_id,
            "teacher_id": info["teacher_id"],
            "class_id": class_id,
            "student_id": student_id,
            "to": info["teacher_email"],
            "ok": ok,
        }
    )


def _notify_parent_confirmed(
    *, class_id: str, student_id: str, actor_user_id: str
) -> None:
    """通知-2 — email the parent after the teacher confirms the binding.

    Parent-facing, formal tone (spec §7-3). Fail-silent + audited.
    """
    info = classes_mod.parent_notify_info(class_id=class_id, student_id=student_id)
    if info is None:
        consent.write_audit_log(
            {
                "timestamp": _now_iso(),
                "level": "WARNING",
                "event": "notify_parent_confirmed_skipped",
                "user_id": actor_user_id,
                "class_id": class_id,
                "student_id": student_id,
                "detail": "parent_notify_info returned None (not confirmed)",
            }
        )
        return
    ok = classes_mod.send_parent_confirmed_notice(
        to_addr=info["parent_email"],
        student_label=classes_mod.student_label(info),
        class_name=info["class_name"],
    )
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO" if ok else "WARNING",
            "event": "notify_parent_confirmed",
            "user_id": actor_user_id,
            "parent_user_id": info["parent_id"],
            "class_id": class_id,
            "student_id": student_id,
            "to": info["parent_email"],
            "ok": ok,
        }
    )


async def handle_class_pending(request: web.Request) -> web.Response:
    """GET /api/classes/{id}/pending — teacher console pending list.

    Teacher-only; cross-teacher attempts are WARNING-logged then rejected
    with the unified 403 (DAO returns None for a foreign/unowned class).
    Returns full student ids — this is the trusted teacher surface, never
    the parent-side 8-char mask.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    class_id = request.match_info.get("id", "")
    cls = classes_mod.get_class_by_id(class_id)
    if cls is not None and cls["teacher_id"] != user["id"]:
        _log_security_warning(
            "class_pending_cross_teacher",
            user_id=user["id"],
            target_id=class_id,
            detail="attempted to list pending students of another teacher's class",
        )
    pending = classes_mod.list_class_pending_students(
        teacher_id=user["id"], class_id=class_id
    )
    if pending is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    return web.json_response({"class_id": class_id, "pending": pending})


# ---------------------------------------------------------------------------
# W3-B Parent Dashboard + Teacher progress lens (shared reports layer)
# ---------------------------------------------------------------------------


async def handle_parent_report(request: web.Request) -> web.Response:
    """GET /api/parent/report?student_id=<mask|full>&period=cycle|weekly|journey

    Parent-only. The identifier is resolved inside the parent's reachable set
    (8-char mask or full id) and the canonical Parent Report envelope is
    returned with the embedded student_id masked to the fixed-length prefix.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    query = request.query
    identifier = (query.get("student_id") or "").strip()
    period = (query.get("period") or "cycle").strip()
    if not identifier:
        return web.json_response(_ERR_INVALID, status=400)
    if period not in reports_mod.PARENT_PERIODS:
        return web.json_response(_ERR_INVALID, status=400)

    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None or not students_mod.can_access_student(user, student):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    report = reports_mod.parent_report_for_student(
        student, period, include_safety=True, mask_student_id=True
    )
    return web.json_response(report)


async def handle_teacher_class_progress(request: web.Request) -> web.Response:
    """GET /api/teacher/classes/{id}/progress - teacher lens class rollups.

    Teacher-only; a foreign/unowned class returns the unified 403 (cross-
    teacher attempts are WARNING-logged, same discipline as class pending).
    Full student ids are returned - this is the trusted teacher console
    surface, never the parent-side 8-char mask.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    class_id = request.match_info.get("id", "")
    cls = classes_mod.get_class_by_id(class_id)
    if cls is not None and cls["teacher_id"] != user["id"]:
        _log_security_warning(
            "class_progress_cross_teacher",
            user_id=user["id"],
            target_id=class_id,
            detail="attempted to read progress of another teacher's class",
        )
    payload = reports_mod.teacher_class_progress(
        teacher_id=user["id"], class_id=class_id
    )
    if payload is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    return web.json_response(payload)


async def handle_teacher_student_progress(request: web.Request) -> web.Response:
    """GET /api/teacher/student/{id}/progress - teacher drill-down view.

    Teacher-only. The identifier is resolved inside the teacher's reachable
    set and the teacher must teach that student (unified 403). Response is
    the canonical Parent Report for the requested period plus a sanitised
    assessment history - internal labels / confidence / rubric ids / evidence
    never leave the server (P-series red line).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "teacher":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    query = request.query
    identifier = (request.match_info.get("id") or "").strip()
    period = (query.get("period") or "cycle").strip()
    if not identifier:
        return web.json_response(_ERR_INVALID, status=400)
    if period not in reports_mod.PARENT_PERIODS:
        return web.json_response(_ERR_INVALID, status=400)

    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = reports_mod.teacher_student_progress(
        teacher_id=user["id"], student=student, period=period
    )
    if payload is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    return web.json_response(payload)


# ---------------------------------------------------------------------------
# W4 Portfolio API (PR-A) — kid view + parent view + single share_card
# ---------------------------------------------------------------------------


async def handle_student_portfolio(request: web.Request) -> web.Response:
    """GET /api/student/portfolio?student=<mask|full> — kid-facing portfolio.

    The platform has no separate student login (users role = parent/teacher/
    admin; children are PIN-unlocked rows reached through the acting parent's
    session — same model as the WS chat handshake). This surface therefore
    accepts a parent session acting on behalf of the unlocked child:
      * parent + own child       -> 200 (items only, never share_cards)
      * parent + another child   -> unified 403
      * teacher / admin session  -> unified 403 (W4 teacher view is out of
        scope; cross-role attempts are WARNING-logged)
    Kid-facing output carries NO student id and NO share_card payload (R2:
    the child interface has no share affordance).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        _log_security_warning(
            "portfolio_student_role_denied",
            user_id=user["id"],
            detail="non-parent session attempted the kid portfolio surface",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    identifier = (request.query.get("student") or "").strip()
    if not identifier:
        return web.json_response(_ERR_INVALID, status=400)
    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None or not students_mod.can_access_student(user, student):
        _log_security_warning(
            "portfolio_student_cross_access",
            user_id=user["id"],
            target_id=identifier,
            detail="attempted to read another child's portfolio via kid surface",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = reports_mod.portfolio_items_for_student(student)
    return web.json_response(payload)


async def handle_parent_portfolio(request: web.Request) -> web.Response:
    """GET /api/parent/portfolio/{student_id} — parent dashboard portfolio.

    Parent-only; the identifier is resolved inside the parent's reachable set
    (8-char mask or full id). Response = the same shared item view as the kid
    surface plus one share_card payload per item (whitelist-only, R3) for the
    parent-mediated share flow (R2).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    identifier = (request.match_info.get("student_id") or "").strip()
    if not identifier:
        return web.json_response(_ERR_INVALID, status=400)
    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None or not students_mod.can_access_student(user, student):
        _log_security_warning(
            "portfolio_parent_cross_access",
            user_id=user["id"],
            target_id=identifier,
            detail="attempted to read another parent's child portfolio",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    payload = reports_mod.parent_portfolio_for_student(student)
    return web.json_response(payload)


async def handle_parent_share_card(request: web.Request) -> web.Response:
    """GET /api/parent/portfolio/{student_id}/share_card/{item_id} — one card.

    Parent-only, child must be reachable AND the item must belong to that
    child (unknown/foreign item -> unified 403, no existence oracle). The
    payload is the single share_card whitelist contract consumed by the W4
    renderers (R3 / R4).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    identifier = (request.match_info.get("student_id") or "").strip()
    item_id = (request.match_info.get("item_id") or "").strip()
    if not identifier or not item_id:
        return web.json_response(_ERR_INVALID, status=400)
    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None or not students_mod.can_access_student(user, student):
        _log_security_warning(
            "portfolio_share_card_cross_access",
            user_id=user["id"],
            target_id=identifier,
            detail="attempted to read another parent's child share_card",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    items = reports_mod.portfolio_items_for_student(student)["items"]
    item = next((it for it in items if it["item_id"] == item_id), None)
    if item is None:
        _log_security_warning(
            "portfolio_share_card_unknown_item",
            user_id=user["id"],
            target_id=item_id,
            detail="share_card requested for unknown/foreign portfolio item",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    card = reports_mod.share_card_for_item(item, student)
    return web.json_response(card)


async def handle_parent_portfolio_pdf(request: web.Request) -> web.Response:
    """GET /api/parent/portfolio/{student_id}/pdf — kid-safe PDF download.

    Parent-only, same reachable-set gate as the JSON portfolio surface.
    The renderer receives ONLY share_card payloads (R3 whitelist, produced
    by the reports layer) plus display_name / generated_at — the function
    signature has no student / db handle, so a direct DB read is impossible
    from inside the render path (R4). growth_note (already kid-safe in the
    item view) is appended to each card for the growth section; every other
    internal field stays out of the PDF.

    spec §6 gates: A4 pages, five sections, PDPO text-scan clean, empty
    portfolio renders cover+summary only, pagination holds <= 6 items/page
    (P4-P6+) / <= 4 (P1-P3) — covered by tests/test_portfolio_pdf.py.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if user["role"] != "parent":
        return web.json_response(_ERR_FORBIDDEN, status=403)

    identifier = (request.match_info.get("student_id") or "").strip()
    if not identifier:
        return web.json_response(_ERR_INVALID, status=400)
    student, ambiguous = students_mod.resolve_student_identifier(identifier, user)
    if ambiguous:
        return web.json_response(_ERR_INVALID, status=400)
    if student is None or not students_mod.can_access_student(user, student):
        _log_security_warning(
            "portfolio_pdf_cross_access",
            user_id=user["id"],
            target_id=identifier,
            detail="attempted to download another parent's child portfolio PDF",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    from agents.portfolio_pdf import render_portfolio_pdf  # renderer import stays lazy

    view = reports_mod.parent_portfolio_for_student(student)
    items_by_id = {item["item_id"]: item for item in view["items"]}
    pdf_cards: list[dict[str, Any]] = []
    for card in view["share_cards"]:
        row = dict(card)
        growth_note = items_by_id.get(card["item_id"], {}).get("growth_note")
        if growth_note:
            row["growth_note"] = growth_note
        pdf_cards.append(row)

    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pdf = render_portfolio_pdf(
        pdf_cards,
        display_name=view["student"]["display_name"],
        generated_at=generated_at,
        lang_code=view["student"]["lang_code"],
        age_band=view["student"]["age_band"],
    )
    filename = f"portfolio-{view['student']['student_id']}.pdf"  # 8-char mask only
    return web.Response(
        body=pdf,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Safety review API (W2 PR#4) — teacher-only; admin bypasses class filter
# ---------------------------------------------------------------------------

def _is_teacher_or_admin(user) -> bool:
    return user["role"] in ("teacher", "admin")


async def handle_safety_events_list(request: web.Request) -> web.Response:
    """GET /api/teacher/safety-events — pointer-only inbox.

    Teacher sees only events for students in their own classes; admin sees
    all events. `?reviewed=false` filters to unreviewed events (default:
    all). The list never includes raw_input (B33a pointer-only discipline).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if not _is_teacher_or_admin(user):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    unreviewed_only = request.query.get("reviewed", "").lower() == "false"
    events = safety_mod.list_events_for_teacher(
        user["id"],
        admin=user["role"] == "admin",
        unreviewed_only=unreviewed_only,
    )
    return web.json_response({"events": events})


async def handle_safety_event_detail(request: web.Request) -> web.Response:
    """GET /api/teacher/safety-events/{id} — full event incl. raw_input.

    Requires a fresh step-up (re-entered login password, 10-minute window,
    checked fresh per request). Cross-teacher and unknown ids get the same
    403 so existence never leaks; cross-teacher access is additionally
    recorded as a security WARNING. student_id is masked in the response
    (PR#3 convention) — first_name is enough for the teacher to recognise
    the child.
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if not _is_teacher_or_admin(user):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    step_err = _require_stepped_up(request)
    if step_err is not None:
        return step_err

    event_id = request.match_info.get("id", "")
    event = safety_mod.get_event_with_student(event_id)
    if event is None:
        # Unknown id — unified 403, same wording as a foreign event.
        return web.json_response(_ERR_FORBIDDEN, status=403)
    if user["role"] != "admin" and not safety_mod.event_owned_by_teacher(
        event_id, user["id"]
    ):
        _log_security_warning(
            "safety_detail_cross_access",
            user_id=user["id"],
            target_id=event_id,
            detail="teacher attempted to view another teacher's safety event",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "safety_detail_viewed",
            "user_id": user["id"],
            "event_id": event_id,
            "student_id": event["student_id"],
        }
    )
    return web.json_response(
        {
            "event": {
                "event_id": event["id"],
                "created_at": event["created_at"],
                "event_type": event["event_type"],
                "severity": event["severity"],
                "raw_input": event["raw_input"],
                "matched_rule": event["matched_rule"],
                "age_band": event["age_band"],
                "lang_code": event["lang_code"],
                "reviewed": bool(event["reviewed"]),
                "reviewed_by": event["reviewed_by"],
                "reviewed_at": event["reviewed_at"],
                "student_first_name": event["student_first_name"],
                "student_id": _mask_student_id(event["student_id"]),
            }
        }
    )


async def handle_safety_event_review(request: web.Request) -> web.Response:
    """POST /api/teacher/safety-events/{id}/review — mark reviewed.

    The single sanctioned UPDATE on safety_events. Unknown ids get the same
    403 as foreign events (no existence leak); cross-teacher review is
    blocked and recorded as a security WARNING. The review decision itself
    is stored in safety_events (reviewed / reviewed_by / reviewed_at).
    """
    user = _session_user(request)
    if user is None:
        return web.json_response(_ERR_AUTH, status=401)
    if not _is_teacher_or_admin(user):
        return web.json_response(_ERR_FORBIDDEN, status=403)

    event_id = request.match_info.get("id", "")
    event = safety_mod.get_event_with_student(event_id)
    if event is None:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    if user["role"] != "admin" and not safety_mod.event_owned_by_teacher(
        event_id, user["id"]
    ):
        _log_security_warning(
            "safety_review_cross_access",
            user_id=user["id"],
            target_id=event_id,
            detail="teacher attempted to review another teacher's safety event",
        )
        return web.json_response(_ERR_FORBIDDEN, status=403)

    ok = safety_mod.review_event(
        event_id,
        reviewed_by=user["id"],
        reviewed_at=_now_iso(),
    )
    if not ok:
        return web.json_response(_ERR_FORBIDDEN, status=403)
    # P3-1: a review is a review action — every review must leave an audit
    # trail (same record shape as safety_detail_viewed, reviewed_by added).
    consent.write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "INFO",
            "event": "safety_event_reviewed",
            "user_id": user["id"],
            "event_id": event_id,
            "student_id": event["student_id"],
            "reviewed_by": user["id"],
        }
    )
    return web.json_response(
        {"ok": True, "event_id": event_id, "reviewed": True}
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_app() -> web.Application:
    app = web.Application(middlewares=[csrf_guard])
    app.router.add_post("/api/auth/register", handle_register)
    app.router.add_post("/api/auth/login", handle_login)
    app.router.add_post("/api/auth/logout", handle_logout)
    app.router.add_get("/api/auth/me", handle_me)
    app.router.add_post("/api/auth/verify-email", handle_verify_email)
    app.router.add_post("/api/auth/forgot-password", handle_forgot_password)
    app.router.add_post("/api/auth/reset-password", handle_reset_password)
    app.router.add_get("/api/consent/docs", handle_consent_docs)
    app.router.add_post("/api/consent/sign", handle_consent_sign)
    app.router.add_post("/api/consent/withdraw", handle_consent_withdraw)
    app.router.add_get("/api/consent/status", handle_consent_status)
    # W2 PR#3 — classes / students / PIN / invites
    app.router.add_post("/api/classes", handle_create_class)
    app.router.add_get("/api/classes", handle_list_classes)
    app.router.add_get("/api/classes/{id}/pending", handle_class_pending)
    app.router.add_post("/api/classes/{id}/confirm", handle_confirm_class_student)
    app.router.add_post("/api/students", handle_create_student)
    app.router.add_get("/api/students", handle_list_students)
    app.router.add_post("/api/students/{id}/pin-verify", handle_pin_verify)
    app.router.add_post("/api/students/{id}/pin-reset", handle_pin_reset)
    app.router.add_post("/api/invites", handle_create_invite)
    app.router.add_get("/api/invites/{token}", handle_invite_public)
    app.router.add_post("/api/invites/{token}/confirm", handle_confirm_invite)
    app.router.add_post("/api/invites/{token}/resend", handle_resend_invite)
    # W2 PR#4 — safety review + step-up auth
    app.router.add_post("/api/auth/step-up", handle_step_up)
    app.router.add_get(
        "/api/teacher/safety-events", handle_safety_events_list
    )
    app.router.add_get(
        "/api/teacher/safety-events/{id}", handle_safety_event_detail
    )
    app.router.add_post(
        "/api/teacher/safety-events/{id}/review", handle_safety_event_review
    )
    # W3-B — parent dashboard + teacher progress lens (shared reports layer)
    app.router.add_get("/api/parent/report", handle_parent_report)
    app.router.add_get(
        "/api/teacher/classes/{id}/progress", handle_teacher_class_progress
    )
    app.router.add_get(
        "/api/teacher/student/{id}/progress", handle_teacher_student_progress
    )
    # W4 PR-A — portfolio surfaces (kid view + parent view + single share_card)
    app.router.add_get("/api/student/portfolio", handle_student_portfolio)
    app.router.add_get(
        "/api/parent/portfolio/{student_id}", handle_parent_portfolio
    )
    app.router.add_get(
        "/api/parent/portfolio/{student_id}/share_card/{item_id}",
        handle_parent_share_card,
    )
    app.router.add_get(
        "/api/parent/portfolio/{student_id}/pdf", handle_parent_portfolio_pdf
    )
    # W3-A — real WS chat (server-side handshake gate + DeepTutor relay).
    # GET (WS upgrade); csrf_guard only protects POSTs. Import is deferred
    # to keep this module's top-level dependency graph unchanged.
    from . import ws_chat as ws_chat_mod

    app.router.add_get("/api/ws/chat", ws_chat_mod.handle_ws_chat)
    app.router.add_get("/legal/{slug}", handle_legal_page)
    return app
