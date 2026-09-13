"""Bridge-3d — student self-login (join code + PIN, no email).

The student console is the third and last identity in the family flow
(boss product ruling 2026-09-12 §5.4): a kid holds **no email address**,
so there is no `users` row and no `auth_session` cookie. This module owns
the independent credential store:

    POST /api/student/login {join_code, pin}   → kid_session cookie
    POST /api/student/logout
    GET  /api/student/me                       → own profile + Week X / 8

Rules (work order 2026-09-13):

* **Gate parity with the existing kid surfaces.** A candidate must be a
  `confirmed` member of the class (the same binding `pin-verify` and the
  W3-A WS chat handshake require — a `pending` student can never log in),
  and must already have a PIN hash (server-generated at `createInvite`
  time; the teacher hands it to the kid).
* **One unified failure.** Unknown join code / wrong PIN / malformed PIN
  / ambiguous match all return the same 401 body — the response never
  reveals whether a join code exists, nor which student matched.
* **5 strikes / 10-minute lock, per join code.** Deliberately separate
  from `students.failed_pin_count` (the parent/teacher delegated
  `pin-verify` surface stays a locked contract at 10 strikes / 1 minute):
  two surfaces, two counters, neither can lock the other out. Scoping the
  lock to the join code means a kid fat-fingering their PIN cannot lock a
  single innocent classmate, and a shared class code cannot be brute
  forced past five attempts. A successful login clears the scope.
* **Opaque server-side session.** `secrets.token_urlsafe(32)` persisted
  in `student_sessions`, HttpOnly/Secure/SameSite=Lax cookie, 7-day life,
  no JWT, nothing in localStorage — the same grade as `auth_session`.

Known limit (recorded for the v2 backlog): resolving (join_code, pin)
requires one Argon2 verify per confirmed classmate with a PIN, so the
endpoint is O(class size) on the failure path. Fine for current class
sizes; if classes grow, add a per-class PIN lookup index instead of
weakening the hash.
"""

from __future__ import annotations

import datetime
import logging
import secrets
from typing import Any, Optional

from . import db
from . import students as students_mod

logger = logging.getLogger("dreamer.auth.student_auth")

STUDENT_SESSION_COOKIE = "kid_session"
STUDENT_SESSION_DAYS = 7
STUDENT_LOGIN_MAX_FAILURES = 5
STUDENT_LOGIN_LOCK_MINUTES = 10

# Health-check identifier: students are never addressed by their full id
# outside the server (same fixed-length mask as auth/api.py).
STUDENT_ID_MASK_LEN = 8


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


def _mask_student_id(student_id: str) -> str:
    return student_id[:STUDENT_ID_MASK_LEN]


# ---------------------------------------------------------------------------
# Join code handling
# ---------------------------------------------------------------------------

def normalise_join_code(raw: Any) -> str:
    """Upper-case, strip whitespace/hyphens — kids type codes by hand.

    The class code alphabet (auth/classes.py) is already upper-case and
    excludes confusable characters (0/O/1/I/L), so normalising is enough
    to make 'abcd-efgh' and ' ABCDEFGH ' the same code.
    """
    if not isinstance(raw, str):
        return ""
    cleaned = raw.strip().upper().replace("-", "").replace(" ", "")
    return cleaned


def _scope(join_code: str) -> str:
    return f"jc:{join_code}"


def lock_remaining(join_code: str) -> Optional[str]:
    """Return locked_until ISO while the scope is locked, else None."""
    code = normalise_join_code(join_code)
    if not code:
        return None
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT locked_until FROM student_login_locks WHERE scope = ?",
            (_scope(code),),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None or not row["locked_until"]:
        return None
    if row["locked_until"] > _now_iso():
        return row["locked_until"]
    return None


def record_failure(join_code: str) -> int:
    """Count one failed attempt against the join-code scope.

    On the 5th consecutive failure the scope locks for 10 minutes and the
    counter resets (mirrors students.record_pin_failure's shape). Returns
    the new count, or 0 when the scope just (or already) locked.
    """
    code = normalise_join_code(join_code)
    if not code:
        return 0
    scope = _scope(code)
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT failed_count, locked_until FROM student_login_locks "
            "WHERE scope = ?",
            (scope,),
        )
        row = cur.fetchone()
        now = _now_iso()
        if row is not None and row["locked_until"] and row["locked_until"] > now:
            # Already locked — a concurrent attempt must not keep counting.
            return 0
        count = int(row["failed_count"] or 0) + 1 if row is not None else 1
        if count >= STUDENT_LOGIN_MAX_FAILURES:
            conn.execute(
                "UPDATE student_login_locks SET failed_count = 0, "
                "locked_until = ?, updated_at = ? WHERE scope = ?",
                (_future_iso(minutes=STUDENT_LOGIN_LOCK_MINUTES), now, scope),
            )
            conn.commit()
            return 0
        if row is None:
            conn.execute(
                "INSERT INTO student_login_locks "
                "(scope, failed_count, locked_until, updated_at) "
                "VALUES (?, ?, NULL, ?)",
                (scope, count, now),
            )
        else:
            conn.execute(
                "UPDATE student_login_locks SET failed_count = ?, "
                "updated_at = ? WHERE scope = ?",
                (count, now, scope),
            )
        conn.commit()
        return count
    finally:
        conn.close()


def clear_failures(join_code: str) -> None:
    code = normalise_join_code(join_code)
    if not code:
        return
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            "DELETE FROM student_login_locks WHERE scope = ?",
            (_scope(code),),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Candidate resolution + login decision
# ---------------------------------------------------------------------------

def confirmed_candidates(join_code: str) -> list[Any]:
    """Confirmed students of every class carrying this join code, with a PIN.

    `status = 'confirmed'` is the same binding pin-verify and the WS chat
    handshake require; `pin_hash IS NOT NULL` skips kids whose PIN the
    teacher has not drawn yet (they cannot be logged in as, by design).
    """
    code = normalise_join_code(join_code)
    if not code:
        return []
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT s.*
                 FROM classes c
                 JOIN class_students cs ON cs.class_id = c.id
                 JOIN students s ON s.id = cs.student_id
                WHERE c.join_code = ?
                  AND cs.status = 'confirmed'
                  AND s.pin_hash IS NOT NULL""",
            (code,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def login(join_code: Any, pin: Any) -> dict[str, Any]:
    """Verify (join_code, pin) and return the decision.

    Result: {"ok": bool, "reason": "ok"|"invalid"|"locked"|"ambiguous",
             "student": row|None, "locked_until": iso|None}
    The HTTP layer maps every non-ok reason to one identical 401 (or 429
    when locked) body, so nothing here leaks which step failed.
    """
    code = normalise_join_code(join_code)
    if not code:
        return {"ok": False, "reason": "invalid", "student": None,
                "locked_until": None}

    locked_until = lock_remaining(code)
    if locked_until:
        return {"ok": False, "reason": "locked", "student": None,
                "locked_until": locked_until}

    # A malformed PIN still counts as a strike: otherwise the format check
    # becomes a free oracle for probing without ever locking the scope.
    if not students_mod.is_valid_pin(pin):
        record_failure(code)
        return {"ok": False, "reason": "invalid", "student": None,
                "locked_until": None}

    match = None
    ambiguous = False
    for candidate in confirmed_candidates(code):
        try:
            if students_mod.verify_pin(pin, candidate["pin_hash"]):
                if match is not None:
                    ambiguous = True
                    break
                match = candidate
        except Exception:  # noqa: BLE001 — a broken hash row never 500s login
            logger.warning(
                "student_login: unreadable pin_hash for student=%s",
                candidate["id"],
            )
            continue

    if ambiguous:
        record_failure(code)
        return {"ok": False, "reason": "ambiguous", "student": None,
                "locked_until": None}
    if match is None:
        record_failure(code)
        return {"ok": False, "reason": "invalid", "student": None,
                "locked_until": None}

    clear_failures(code)
    return {"ok": True, "reason": "ok", "student": match,
            "locked_until": None}


# ---------------------------------------------------------------------------
# Student session store
# ---------------------------------------------------------------------------

def create_session(
    *,
    student_id: str,
    created_ip: Optional[str] = None,
) -> tuple[str, str]:
    """Persist a fresh opaque kid session; returns (session_id, expires_at)."""
    db.ensure_schema()
    session_id = secrets.token_urlsafe(32)
    expires_at = _future_iso(days=STUDENT_SESSION_DAYS)
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO student_sessions
               (id, student_id, expires_at, created_ip, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, student_id, expires_at, created_ip, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id, expires_at


def get_session_student(session_id: str) -> Optional[Any]:
    """Return the student row for a live kid session, else None."""
    if not session_id:
        return None
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT s.* FROM student_sessions ss
                 JOIN students s ON s.id = ss.student_id
                WHERE ss.id = ? AND ss.expires_at > ?""",
            (session_id, _now_iso()),
        )
        return cur.fetchone()
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    if not session_id:
        return
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute("DELETE FROM student_sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Own-profile payload
# ---------------------------------------------------------------------------

def student_home(student_id: str) -> dict[str, Any]:
    """The kid's own learning space header: identity + Week X / 8 badge.

    The badge comes from the shared kid resolver
    (curriculum.student_week_badge — the very same source Bridge-3a's kid
    badge reads), so a logged-in student and their parent can never be
    told two different weeks. Mastery figures are deliberately NOT here:
    the class mastery the teacher console shows is a class average, and a
    kid must never receive their classmates' data.

    Shape: {student: {id(masked), first_name, age_band, lang_code},
            class:   {id, name} | None,
            badge:   {state, week_index, total_weeks, unit_title}}
    """
    from . import curriculum as curriculum_mod

    student = students_mod.get_student_by_id(student_id)
    badge = curriculum_mod.student_week_badge(student_id)
    if student is None:
        return {"student": None, "class": None, "badge": badge}

    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT c.id, c.name
                 FROM classes c
                 JOIN class_students cs ON cs.class_id = c.id
                WHERE cs.student_id = ? AND cs.status = 'confirmed'
                ORDER BY cs.created_at ASC LIMIT 1""",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()

    return {
        "student": {
            "id": _mask_student_id(student["id"]),
            "first_name": student["first_name"],
            "age_band": student["age_band"],
            "lang_code": student["lang_code"],
        },
        "class": {"id": row["id"], "name": row["name"]} if row else None,
        "badge": badge,
    }
