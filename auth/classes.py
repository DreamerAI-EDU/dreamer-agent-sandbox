"""W2 PR#3 — classes + parent-invite flow (DAO + flow layer).

Scope (per W2-PR3 brief §1 / §4):
  - Classes: teacher creates a class with a human-friendly 8-char join_code
    (uppercase letters + digits, excluding 0/O/1/I/L confusion chars);
    a teacher only sees their own classes (cross-teacher access attempt is
    recorded as a security WARNING carrying both user ids).
  - Invite flow: one-shot creation of students row (parent_id NULL,
    teacher_id = current teacher) + class_students row (status=pending) +
    invites row (token = secrets.token_urlsafe(32), 72h expiry).
  - Confirm: the parent's 1-click confirm runs inside a single SQLite
    transaction — users row (email_verified=TRUE) + consent_log rows +
    parent binding + used_at + session are all-or-nothing. A missing
    privacy_policy agreement rejects the whole confirm with no rows left.
  - Resend: new token row, old row superseded_by points at the new token so
    only one valid link exists at a time.
  - Teacher confirm: four conditions (own class / student in class /
    status=pending / parent bound) before status becomes confirmed.
  - Rate limit: invites + resends share a per-teacher daily cap of 20.

All SQL is parameterized. Audit / security records are appended via
auth.consent.write_audit_log (the repo's JSONL audit channel) — the API
layer owns business wording, this module owns row integrity.
"""

from __future__ import annotations

import datetime
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Optional

from . import db

logger = logging.getLogger("dreamer.auth.classes")

INVITE_HOURS = 72
DAILY_INVITE_LIMIT = 20

# Human-friendly join code alphabet: 0/O/1/I/L removed (confusion chars).
_JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


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


def _today_start_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def generate_join_code() -> str:
    """8-char join code from the confusion-free alphabet."""
    return "".join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(8))


def create_class(
    *,
    class_id: Optional[str] = None,
    teacher_id: str,
    name: str,
    join_code: Optional[str] = None,
    class_type: str = "monthly",
    grade_band: Optional[str] = None,
    is_one_on_one: bool = False,
) -> str:
    if class_id is None:
        class_id = str(uuid.uuid4())
    if join_code is None:
        join_code = generate_join_code()
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO classes
                   (id, teacher_id, name, join_code, class_type, grade_band,
                    is_one_on_one, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                class_id,
                teacher_id,
                name,
                join_code,
                class_type,
                grade_band,
                1 if is_one_on_one else 0,
                _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return class_id


def get_class_by_id(class_id: str) -> Optional[Any]:
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,))
        return cur.fetchone()
    finally:
        conn.close()


def list_classes_for_teacher(teacher_id: str) -> list[dict[str, Any]]:
    """Teacher's classes with pending/confirmed student counts."""
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT c.id, c.teacher_id, c.name, c.join_code,
                      c.class_type, c.grade_band, c.is_one_on_one, c.created_at,
                      SUM(CASE WHEN cs.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                      SUM(CASE WHEN cs.status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed_count
               FROM classes c
               LEFT JOIN class_students cs ON cs.class_id = c.id
               WHERE c.teacher_id = ?
               GROUP BY c.id
               ORDER BY c.created_at""",
            (teacher_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "join_code": row["join_code"],
                "class_type": row["class_type"],
                "grade_band": row["grade_band"],
                "is_one_on_one": int(row["is_one_on_one"] or 0),
                "pending_count": int(row["pending_count"] or 0),
                "confirmed_count": int(row["confirmed_count"] or 0),
                "created_at": row["created_at"],
            }
        )
    return out


def teacher_teaches_student(teacher_id: str, student_id: str) -> bool:
    """True when the student appears in any class owned by the teacher."""
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT 1 FROM class_students cs
               JOIN classes c ON c.id = cs.class_id
               WHERE c.teacher_id = ? AND cs.student_id = ? LIMIT 1""",
            (teacher_id, student_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def list_students_for_teacher(teacher_id: str) -> list[Any]:
    """Students in any class owned by the teacher (deduplicated)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT DISTINCT s.* FROM students s
               JOIN class_students cs ON cs.student_id = s.id
               JOIN classes c ON c.id = cs.class_id
               WHERE c.teacher_id = ?
               ORDER BY s.created_at""",
            (teacher_id,),
        )
        return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Invite flow — creation / lookup / resend
# ---------------------------------------------------------------------------

def create_invite_flow(
    *,
    teacher_id: str,
    class_id: str,
    first_name: str,
    age_band: str,
    lang_code: str,
    pin_hash: str,
    parent_email: str,
    student_id: Optional[str] = None,
) -> tuple[str, str]:
    """One-shot: students row (parent_id NULL) + class_students(pending) +
    invites row. Returns (student_id, token). All-or-nothing (single conn)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        if student_id is None:
            student_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = _now_iso()
        conn.execute(
            """INSERT INTO students
               (id, parent_id, teacher_id, first_name, age_band, lang_code,
                pin_hash, pin_lock_until, failed_pin_count, created_at)
               VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, 0, ?)""",
            (student_id, teacher_id, first_name, age_band, lang_code, pin_hash, now),
        )
        conn.execute(
            """INSERT INTO class_students (class_id, student_id, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (class_id, student_id, now),
        )
        conn.execute(
            """INSERT INTO invites
               (token, parent_email, student_id, class_id, expires_at,
                used_at, superseded_by, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
            (
                token,
                parent_email,
                student_id,
                class_id,
                _future_iso(hours=INVITE_HOURS),
                teacher_id,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return student_id, token


def get_invite_by_token(token: str) -> Optional[Any]:
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute("SELECT * FROM invites WHERE token = ?", (token,))
        return cur.fetchone()
    finally:
        conn.close()


def daily_invite_count(teacher_id: str) -> int:
    """Invites + resends created by this teacher since UTC midnight."""
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM invites "
            "WHERE created_by = ? AND created_at >= ?",
            (teacher_id, _today_start_iso()),
        )
        row = cur.fetchone()
        return int(row["n"] or 0)
    finally:
        conn.close()


def resend_invite(
    *,
    teacher_id: str,
    token: str,
    new_parent_email: Optional[str] = None,
) -> str:
    """Create a new token row; old row superseded_by -> new token.

    Returns the new token. Raises ValueError for non-own / already-used
    invites so the API layer can map to the unified error wording.
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute("SELECT * FROM invites WHERE token = ?", (token,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("not_found")
        if row["created_by"] != teacher_id:
            raise ValueError("not_owned")
        if row["used_at"] is not None:
            raise ValueError("already_used")

        new_token = secrets.token_urlsafe(32)
        now = _now_iso()
        parent_email = (new_parent_email or row["parent_email"]).strip().lower()
        conn.execute(
            """INSERT INTO invites
               (token, parent_email, student_id, class_id, expires_at,
                used_at, superseded_by, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
            (
                new_token,
                parent_email,
                row["student_id"],
                row["class_id"],
                _future_iso(hours=INVITE_HOURS),
                teacher_id,
                now,
            ),
        )
        conn.execute(
            "UPDATE invites SET superseded_by = ? WHERE token = ?",
            (new_token, token),
        )
        conn.commit()
        return new_token
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Parent 1-click confirm (single transaction)
# ---------------------------------------------------------------------------

def get_invite_public_by_token(token: str) -> Optional[dict[str, str]]:
    """Read-only public invite lookup for the landing page.

    The token itself is the credential (same trust level as confirm — no
    login session needed). Validity rules are identical to
    confirm_invite_flow: invalid / expired / used / superseded all return
    None so the caller maps every failure to the unified 400 wording.

    Only the four public fields are exposed: first_name, age_band,
    lang_code, parent_email (the invite's parent address, echoed back for
    verification). The full student id and all other sensitive columns are
    never returned.
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT i.parent_email, i.used_at, i.expires_at,
                      i.superseded_by, s.first_name, s.age_band, s.lang_code
               FROM invites i
               JOIN students s ON s.id = i.student_id
               WHERE i.token = ?""",
            (token,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        if row["used_at"] is not None:
            return None
        if row["expires_at"] and row["expires_at"] < _now_iso():
            return None
        if row["superseded_by"] is not None:
            return None
        return {
            "first_name": row["first_name"],
            "age_band": row["age_band"],
            "lang_code": row["lang_code"],
            "parent_email": row["parent_email"],
        }
    finally:
        conn.close()


def confirm_invite_flow(
    *,
    token: str,
    parent_user_id: str,
    password_hash: str,
    privacy_version: str,
    media_version: str,
    media_agreed: bool,
    session_id: str,
    session_expires_at: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Atomically confirm an invite.

    Steps (all-or-nothing inside one SQLite connection):
      1. validate token (exists, unused, not expired, not superseded)
      2. create parent user (email_verified=TRUE)
      3. append consent_log rows — privacy_policy is mandatory agreed;
         media_consent only when the parent opted in (voluntary)
      4. bind students.parent_id
      5. mark invites.used_at
      6. open a session for the parent

    Returns a result dict on success, or None when the token is invalid /
    expired / used / superseded (unified wording, no case split).
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT i.*, s.parent_id AS student_parent_id
               FROM invites i
               JOIN students s ON s.id = i.student_id
               WHERE i.token = ?""",
            (token,),
        )
        invite = cur.fetchone()
        if invite is None:
            return None
        if invite["used_at"] is not None:
            return None
        if invite["expires_at"] and invite["expires_at"] < _now_iso():
            return None
        if invite["superseded_by"] is not None:
            return None

        now = _now_iso()
        student_id = invite["student_id"]
        parent_email = invite["parent_email"]

        # Pre-check: the invite's parent email must not already own an
        # account. Without this, the INSERT below trips the users.email
        # unique constraint and surfaces as an unhandled 500; a repeat
        # click / duplicate invite must fail cleanly with 400 instead.
        already_registered = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (parent_email,)
        ).fetchone()
        if already_registered is not None:
            return None

        conn.execute(
            """INSERT INTO users
               (id, email, password_hash, role, email_verified,
                email_verify_token, email_verify_expires_at,
                failed_logins, lock_until, created_at)
               VALUES (?, ?, ?, 'parent', 1, NULL, NULL, 0, NULL, ?)""",
            (parent_user_id, parent_email, password_hash, now),
        )
        consent_rows = [
            (
                str(uuid.uuid4()),
                parent_user_id,
                student_id,
                "privacy_policy",
                privacy_version,
                "agreed",
                ip,
                user_agent,
                now,
            ),
        ]
        if media_agreed:
            consent_rows.append(
                (
                    str(uuid.uuid4()),
                    parent_user_id,
                    student_id,
                    "media_consent",
                    media_version,
                    "agreed",
                    ip,
                    user_agent,
                    now,
                )
            )
        conn.executemany(
            """INSERT INTO consent_log
               (id, user_id, student_id, doc_type, doc_version, action,
                ip, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            consent_rows,
        )
        conn.execute(
            "UPDATE students SET parent_id = ? WHERE id = ?",
            (parent_user_id, student_id),
        )
        conn.execute(
            "UPDATE invites SET used_at = ? WHERE token = ?",
            (now, token),
        )
        conn.execute(
            """INSERT INTO sessions (id, user_id, expires_at, created_ip, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, parent_user_id, session_expires_at, ip, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "parent_user_id": parent_user_id,
        "parent_email": parent_email,
        "student_id": student_id,
        "class_id": invite["class_id"],
    }


# ---------------------------------------------------------------------------
# Teacher confirm binding
# ---------------------------------------------------------------------------

def student_class_statuses(student_id: str) -> list[str]:
    """All class_students statuses for a student (empty when never invited)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT status FROM class_students WHERE student_id = ?",
            (student_id,),
        )
        return [row["status"] for row in cur.fetchall()]
    finally:
        conn.close()


def confirm_class_student(
    *,
    teacher_id: str,
    class_id: str,
    student_id: str,
) -> tuple[bool, str]:
    """Teacher confirms a pending student in their own class.

    Four conditions must all hold: class owned by teacher / student in
    class / status=pending / student already bound to a parent. Returns
    (ok, reason) where reason is 'ok' | 'forbidden' | 'not_found' |
    'not_pending' | 'no_parent'.
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cls = conn.execute(
            "SELECT * FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
        if cls is None:
            return False, "forbidden"
        if cls["teacher_id"] != teacher_id:
            return False, "forbidden"

        cs = conn.execute(
            "SELECT * FROM class_students WHERE class_id = ? AND student_id = ?",
            (class_id, student_id),
        ).fetchone()
        if cs is None:
            return False, "not_found"
        if cs["status"] != "pending":
            return False, "not_pending"

        student = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        if student is None:
            return False, "not_found"
        if student["parent_id"] is None:
            return False, "no_parent"

        conn.execute(
            "UPDATE class_students SET status = 'confirmed' "
            "WHERE class_id = ? AND student_id = ?",
            (class_id, student_id),
        )
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Email (invite channel reuses the shared SMTP helper)
# ---------------------------------------------------------------------------

def get_frontend_base_url() -> str:
    """Invite-link base URL — read from config/auth_config.yaml (never
    hardcoded in handlers; env var override for tests / staging)."""
    override = os.environ.get("DREAMER_FRONTEND_BASE_URL")
    if override:
        return override
    try:
        import yaml

        cfg_path = (
            Path(__file__).resolve().parent.parent / "config" / "auth_config.yaml"
        )
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return str(data.get("frontend_base_url") or "http://localhost:5173")
    except (OSError, yaml.YAMLError):
        return "http://localhost:5173"


def send_invite_email(*, to_addr: str, token: str, base_url: str) -> bool:
    """Send the bilingual parent-invitation email (72h validity link)."""
    from .email import send_email

    link = f"{base_url.rstrip('/')}/invite/{token}"
    subject = "[Dreamer AI Edu] 家長邀請 / Parent Invitation"
    body = "\n".join([
        "Dreamer AI Edu 家長邀請 / Parent Invitation",
        "",
        "老師已邀請你加入子女嘅學習帳戶。",
        "A teacher has invited you to join your child's learning account.",
        "",
        "請喺 72 小時內完成確認（連結只能使用一次）。",
        "Please confirm within 72 hours (the link is single-use).",
        "",
        "確認連結 / Confirmation link: " + link,
        "",
        "如非你本人，請忽略此電郵。",
        "If this is not for you, you can ignore this email.",
    ])
    return send_email(to_addr=to_addr, subject=subject, body=body)


# ---------------------------------------------------------------------------
# W3-C — lifecycle notifications (通知-1 / 通知-2) + teacher pending console
# ---------------------------------------------------------------------------

def student_label(info: dict[str, Any]) -> str:
    """Kid-facing label for notification templates — first name + age band
    only. The schema has no last name by design (B24), and the label never
    includes the student id or the parent's name."""
    return f"{info['first_name']} ({info['age_band']})"


def teacher_notify_info(
    *, class_id: str, student_id: str
) -> Optional[dict[str, Any]]:
    """Teacher + class context for the 通知-1 email (after parent confirm)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT c.id AS class_id, c.name AS class_name,
                      t.id AS teacher_id, t.email AS teacher_email,
                      s.first_name, s.age_band
               FROM class_students cs
               JOIN classes c ON c.id = cs.class_id
               JOIN users t ON t.id = c.teacher_id
               JOIN students s ON s.id = cs.student_id
               WHERE cs.class_id = ? AND cs.student_id = ?""",
            (class_id, student_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def parent_notify_info(
    *, class_id: str, student_id: str
) -> Optional[dict[str, Any]]:
    """Parent + class context for the 通知-2 email (after teacher confirm)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT c.id AS class_id, c.name AS class_name,
                      p.id AS parent_id, p.email AS parent_email,
                      s.first_name, s.age_band
               FROM class_students cs
               JOIN classes c ON c.id = cs.class_id
               JOIN students s ON s.id = cs.student_id
               JOIN users p ON p.id = s.parent_id
               WHERE cs.class_id = ? AND cs.student_id = ?
                 AND cs.status = 'confirmed'""",
            (class_id, student_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def send_teacher_pending_notice(
    *, to_addr: str, student_label: str, class_name: str, base_url: str
) -> bool:
    """通知-1 — email the teacher after a parent confirms an invite.

    Fail-silent contract: returns False on SMTP failure, never raises.
    The confirm handler writes an audit row with the outcome either way.
    """
    from .email import send_email

    link = f"{base_url.rstrip('/')}/teacher"
    subject = "[Dreamer AI Edu] 家長已確認邀請 / Parent confirmed an invitation"
    body = "\n".join([
        "Dreamer AI Edu 班級通知 / Class Notice",
        "",
        "你發出嘅家長邀請已被確認，學生而家等待你確認班級連結。",
        "A parent has accepted your invitation. The student is now waiting for you to confirm the class link.",
        "",
        "學生 / Student: " + student_label,
        "班別 / Class: " + class_name,
        "",
        "待確認連結 / Review link: " + link,
        "",
        "登入後喺「我的班級」揀相應班別確認即可。",
        "Sign in and confirm the student under the matching class.",
    ])
    return send_email(to_addr=to_addr, subject=subject, body=body)


def send_parent_confirmed_notice(
    *, to_addr: str, student_label: str, class_name: str
) -> bool:
    """通知-2 — email the parent after the teacher confirms the binding.

    Parent-facing, formal tone (W3 spec §7-3, 老板 09-03 拍板). Fail-silent
    like the rest of the notification channel.
    """
    from .email import send_email

    subject = "[Dreamer AI Edu] 老師已確認你嘅子女帳戶 / Teacher confirmed your child's account"
    body = "\n".join([
        "Dreamer AI Edu 家長通知 / Parent Notice",
        "",
        "老師已確認你子女嘅帳戶連結。佢哋而家可以開始使用 Dreamer AI。",
        "Your child's account has been confirmed by the teacher and is now ready to use Dreamer AI.",
        "",
        "學生 / Student: " + student_label,
        "班別 / Class: " + class_name,
        "",
        "如有任何疑問，請直接聯絡學校老師。",
        "If you have any questions, please contact the school teacher.",
    ])
    return send_email(to_addr=to_addr, subject=subject, body=body)


def list_class_pending_students(
    *, teacher_id: str, class_id: str
) -> Optional[list[dict[str, Any]]]:
    """Pending students in a teacher-owned class.

    Returns None when the class does not belong to this teacher (unified
    with the confirm guard), otherwise the pending list. Full student ids
    are returned — this is the trusted teacher console surface (same
    precedent as the safety-review detail view), never the parent-side
    8-char mask.
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cls = conn.execute(
            "SELECT teacher_id FROM classes WHERE id = ?", (class_id,)
        ).fetchone()
        if cls is None or cls["teacher_id"] != teacher_id:
            return None
        rows = conn.execute(
            """SELECT s.id AS student_id, s.first_name, s.age_band,
                      s.lang_code, i.parent_email
               FROM class_students cs
               JOIN students s ON s.id = cs.student_id
               LEFT JOIN invites i
                 ON i.student_id = cs.student_id
                AND i.class_id = cs.class_id
                AND i.used_at IS NOT NULL
               WHERE cs.class_id = ? AND cs.status = 'pending'
               GROUP BY s.id
               ORDER BY s.created_at""",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "student_id": row["student_id"],
                "first_name": row["first_name"],
                "age_band": row["age_band"],
                "lang_code": row["lang_code"],
                "parent_email": row["parent_email"],
            }
        )
    return out
