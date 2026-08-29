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

from . import consent
from . import db
from .email import send_verification_email
from .security import (
    dummy_verify,
    hash_password,
    ip_rate_limiter,
    new_session_token,
    new_verify_token,
    verify_password,
)

logger = logging.getLogger("dreamer.auth.api")

SESSION_COOKIE = "auth_session"
SESSION_DAYS = 7
LOCK_FAILURES = 5
LOCK_MINUTES = 15
VERIFY_HOURS = 24

_ERR_AUTH = {"error": "email 或密碼不正確"}
_ERR_INVALID = {"error": "請求無效"}
_ERR_LOCKED = {"error": "嘗試次數過多，請稍後再試"}


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
    if request.method == "POST" and (
        request.path.startswith("/api/auth/")
        or request.path.startswith("/api/consent/")
    ):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return web.json_response(_ERR_INVALID, status=403)
    return await handler(request)


def _session_user(request: web.Request) -> Optional[dict[str, Any]]:
    """Resolve the logged-in user from the session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return db.get_session_user(token)


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

    media_consent: allowed; writes an audit-log media_takedown_pending
    marker for the human 24h takedown flow.
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
# App factory
# ---------------------------------------------------------------------------

def build_app() -> web.Application:
    app = web.Application(middlewares=[csrf_guard])
    app.router.add_post("/api/auth/register", handle_register)
    app.router.add_post("/api/auth/login", handle_login)
    app.router.add_post("/api/auth/logout", handle_logout)
    app.router.add_get("/api/auth/me", handle_me)
    app.router.add_post("/api/auth/verify-email", handle_verify_email)
    app.router.add_get("/api/consent/docs", handle_consent_docs)
    app.router.add_post("/api/consent/sign", handle_consent_sign)
    app.router.add_post("/api/consent/withdraw", handle_consent_withdraw)
    app.router.add_get("/api/consent/status", handle_consent_status)
    app.router.add_get("/legal/{slug}", handle_legal_page)
    return app
