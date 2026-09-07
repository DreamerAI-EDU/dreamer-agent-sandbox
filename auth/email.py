"""Shared SMTP helper for the auth core (W2 PR#1).

Reuses the B33a SMTP channel configuration — the same SAFETY_SMTP_* /
SAFETY_EMAIL_* env variables, no second config set (per PR brief §4):
    SAFETY_EMAIL_FROM      — From header (default info@dreamer-aiedu.net)
    SAFETY_SMTP_USER       — SMTP login user (defaults to SAFETY_EMAIL_FROM)
    SAFETY_SMTP_HOST       — default smtp.gmail.com
    SAFETY_SMTP_PORT       — 465 (SSL, default) or 587 (STARTTLS)
    SAFETY_SMTP_PASSWORD   — app password (the only real secret)

The existing B33a notifier (agents/kid_safe/input_guard.notify_welfare_email)
is intentionally NOT refactored — it stays as the safety-channel producer.
This module is the generic channel that the auth flow uses for
verification emails, and it follows the same fire-and-forget contract:
never raises, never blocks the caller on SMTP failure.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("dreamer.auth.email")


def send_email(*, to_addr: str, subject: str, body: str) -> bool:
    """Send an email over the shared SMTP channel.

    Returns True if accepted by the SMTP server; False on any failure
    (missing password / SMTP error) — never raises.

    Note: the SAFETY_EMAIL_ENABLED master switch is deliberately NOT
    consulted here — it gates the safety high-alert channel (B33a) only.
    Verification email is a core auth function and must not be silenced by
    the safety switch. PR description documents this decision.
    """
    password = os.environ.get("SAFETY_SMTP_PASSWORD")
    if not password:
        logger.error(
            "auth email skipped: SAFETY_SMTP_PASSWORD not set (to=%s)", to_addr
        )
        return False

    from_addr = os.environ.get("SAFETY_EMAIL_FROM", "info@dreamer-aiedu.net")
    smtp_user = os.environ.get("SAFETY_SMTP_USER") or os.environ.get(
        "SAFETY_EMAIL_FROM", "info@dreamer-aiedu.net"
    )
    host = os.environ.get("SAFETY_SMTP_HOST", "smtp.gmail.com")
    try:
        port = int(os.environ.get("SAFETY_SMTP_PORT", "465"))
    except ValueError:
        port = 465

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        if port == 465:
            # Preferred path: implicit SSL (smtp.gmail.com:465)
            with smtplib.SMTP_SSL(
                host, port, timeout=10, context=ssl.create_default_context()
            ) as server:
                server.login(smtp_user, password)
                server.send_message(msg)
        else:
            # Fallback path: STARTTLS (587)
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(smtp_user, password)
                server.send_message(msg)
        return True
    except Exception:
        logger.error(
            "auth email send failed (to=%s)", to_addr, exc_info=True
        )
        return False


def send_verification_email(*, to_addr: str, token: str) -> bool:
    """Send the teacher email-verification message (single-use link token)."""
    subject = "[Dreamer AI Edu] 驗證你的帳戶 / Verify your account"
    body = "\n".join([
        "Dreamer AI Edu 帳戶驗證 / Account Verification",
        "",
        "請喺 24 小時內完成驗證（連結只能使用一次）。",
        "Please verify within 24 hours (the link is single-use).",
        "",
        "驗證碼 / Verification code: " + token,
        "",
        "如非你本人註冊，請忽略此電郵。",
        "If you did not register, you can ignore this email.",
    ])
    return send_email(to_addr=to_addr, subject=subject, body=body)


def send_reset_email(*, to_addr: str, link: str, lang: str = "zh-hk") -> bool:
    """Send the password-reset message (single-use link token, 60 min).

    Copy follows the account's lang_code (en / zh-hk / zh-cn); unknown or
    missing lang falls back to bilingual en + zh-hk per W4 spec §3.3. The
    plaintext token rides only inside `link`; the DB never sees it.
    """
    subject = "[Dreamer AI Edu] 重設密碼 / Password Reset"

    if lang == "en":
        body = "\n".join([
            "Dreamer AI Edu Password Reset",
            "",
            "Reset within 60 minutes (the link is single-use).",
            "",
            "Reset link: " + link,
            "",
            "If you did not request this, you can ignore this email.",
        ])
    elif lang == "zh-cn":
        body = "\n".join([
            "Dreamer AI Edu 密码重置",
            "",
            "请在 60 分钟内完成重置（链接只能使用一次）。",
            "",
            "重置链接：" + link,
            "",
            "如非本人申请，请忽略此邮件。",
        ])
    elif lang == "zh-hk":
        body = "\n".join([
            "Dreamer AI Edu 密碼重設",
            "",
            "請喺 60 分鐘內完成重設（連結只能使用一次）。",
            "",
            "重設連結：" + link,
            "",
            "如非你本人申請，請忽略此電郵。",
        ])
    else:
        body = "\n".join([
            "Dreamer AI Edu 密碼重設 / Password Reset",
            "",
            "請喺 60 分鐘內完成重設（連結只能使用一次）。",
            "Please reset within 60 minutes (the link is single-use).",
            "",
            "重設連結 / Reset link: " + link,
            "",
            "如非你本人申請，請忽略此電郵。",
            "If you did not request this, you can ignore this email.",
        ])
    return send_email(to_addr=to_addr, subject=subject, body=body)
