"""W2 account system: DB schema + auth core (PR#1).

Package layout:
  db.py       — SQLite connection + schema bootstrap + DAO helpers
  security.py — Argon2id hashing, session tokens, rate limiting, lockout
  email.py    — shared SMTP helper (reuses B33a SAFETY_SMTP_* env config)
  api.py      — aiohttp.web application with /api/auth/* endpoints + CSRF guard
"""

from .db import (
    connect,
    ensure_schema,
    create_user,
    get_user_by_email,
    get_user_by_id,
    insert_teacher_invite,
    mark_invite_used,
    is_invite_valid,
    create_session,
    get_session_user,
    delete_session,
    set_user_lock,
    increment_failed_logins,
    reset_failed_logins,
    set_email_verify_token,
    consume_email_verify_token,
)

__all__ = [
    "connect",
    "ensure_schema",
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "insert_teacher_invite",
    "mark_invite_used",
    "is_invite_valid",
    "create_session",
    "get_session_user",
    "delete_session",
    "set_user_lock",
    "increment_failed_logins",
    "reset_failed_logins",
    "set_email_verify_token",
    "consume_email_verify_token",
]
