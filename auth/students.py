"""W2 PR#3 — student records + PIN gate (DAO layer).

Scope (per W2-PR3 brief §2 / §3):
  - students table carries B24-minimal columns only: id, parent_id,
    teacher_id, first_name, age_band, lang_code, pin_hash,
    pin_lock_until, failed_pin_count. No full_name / last_name / school /
    dob — a repo-wide B24 guard scans the schema.
  - age_band is a server-side enum (P1-P3 / P4-P6 / S1-S3); lang_code is a
    server-side enum (en / zh-hk / zh-cn). Free text is rejected by the
    API layer before any DAO call.
  - PIN hashing is Argon2id via auth.security.hash_password (same grade as
    passwords). No plaintext, no weak hash.
  - Lockout: 10 consecutive wrong PINs -> pin_lock_until = now + 1 minute;
    during the lock window even the correct PIN is rejected (429).
  - PIN values never appear in any log — the API layer only logs event
    names, never the value.

This module is deliberately thin (no business rules; the API layer owns
authorisation and validation), following the PR#1 DAO convention.
"""

from __future__ import annotations

import datetime
import secrets
import uuid
from typing import Any, Optional

from . import db
from .security import hash_password, verify_password

AGE_BANDS = ("P1-P3", "P4-P6", "S1-S3")
LANG_CODES = ("en", "zh-hk", "zh-cn")

PIN_LOCK_FAILURES = 10
PIN_LOCK_MINUTES = 1


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


# ---------------------------------------------------------------------------
# PIN helpers
# ---------------------------------------------------------------------------

def is_valid_pin(pin: Any) -> bool:
    """PIN must be a 4-digit numeric string (no letters, no spaces)."""
    return (
        isinstance(pin, str)
        and len(pin) == 4
        and pin.isdigit()
    )


def generate_pin() -> str:
    """Random 4-digit PIN (system draw path; never a fixed default)."""
    return f"{secrets.randbelow(10000):04d}"


def hash_pin(pin: str) -> str:
    """Argon2id hash — same grade as passwords (security.hash_password)."""
    return hash_password(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its Argon2id hash (never raises)."""
    return verify_password(pin, pin_hash)


# ---------------------------------------------------------------------------
# Student DAO
# ---------------------------------------------------------------------------

def create_student(
    *,
    student_id: Optional[str] = None,
    first_name: str,
    age_band: str,
    lang_code: str,
    pin_hash: str,
    parent_id: Optional[str] = None,
    teacher_id: Optional[str] = None,
) -> str:
    """Insert one student row; returns the student id."""
    if student_id is None:
        student_id = str(uuid.uuid4())
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO students
               (id, parent_id, teacher_id, first_name, age_band, lang_code,
                pin_hash, pin_lock_until, failed_pin_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)""",
            (
                student_id,
                parent_id,
                teacher_id,
                first_name,
                age_band,
                lang_code,
                pin_hash,
                _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return student_id


def get_student_by_id(student_id: str) -> Optional[Any]:
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        return cur.fetchone()
    finally:
        conn.close()


def list_students_for_parent(parent_id: str) -> list[Any]:
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT * FROM students WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def can_access_student(user: Any, student: Any) -> bool:
    """Authorisation helper: parent owns the student, or teacher teaches the
    student's class (teacher branch covers class_students membership)."""
    if student is None:
        return False
    if user["role"] == "parent":
        return bool(student["parent_id"]) and student["parent_id"] == user["id"]
    if user["role"] == "teacher":
        from . import classes as classes_mod

        return classes_mod.teacher_teaches_student(user["id"], student["id"])
    return False


# ---------------------------------------------------------------------------
# PIN lockout / reset
# ---------------------------------------------------------------------------

def pin_lock_remaining(student_id: str) -> Optional[str]:
    """Return pin_lock_until ISO when the student is currently locked (future),
    else None."""
    row = get_student_by_id(student_id)
    if row is None:
        return None
    lock_until = row["pin_lock_until"]
    if lock_until and lock_until > _now_iso():
        return lock_until
    return None


def record_pin_failure(student_id: str) -> int:
    """Increment the failure counter; on the 10th consecutive failure set
    pin_lock_until = now + 1 minute and reset the counter.

    Returns the new failure count (0 when the student just got locked).
    """
    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            "SELECT failed_pin_count, pin_lock_until FROM students WHERE id = ?",
            (student_id,),
        )
        row = cur.fetchone()
        if row is None:
            return 0
        # A lock window may have started since the handler's pre-check — do
        # not keep counting inside an active lock.
        if row["pin_lock_until"] and row["pin_lock_until"] > _now_iso():
            return 0
        count = int(row["failed_pin_count"] or 0) + 1
        if count >= PIN_LOCK_FAILURES:
            conn.execute(
                "UPDATE students SET failed_pin_count = 0, pin_lock_until = ? "
                "WHERE id = ?",
                (_future_iso(minutes=PIN_LOCK_MINUTES), student_id),
            )
            conn.commit()
            return 0
        conn.execute(
            "UPDATE students SET failed_pin_count = ? WHERE id = ?",
            (count, student_id),
        )
        conn.commit()
        return count
    finally:
        conn.close()


def clear_pin_failures(student_id: str) -> None:
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE students SET failed_pin_count = 0 WHERE id = ?",
            (student_id,),
        )
        conn.commit()
    finally:
        conn.close()


def set_pin(student_id: str, pin_hash: str) -> None:
    """Set a new PIN hash; immediately usable and unlocks the student
    (clears pin_lock_until + failure counter)."""
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE students SET pin_hash = ?, pin_lock_until = NULL, "
            "failed_pin_count = 0 WHERE id = ?",
            (pin_hash, student_id),
        )
        conn.commit()
    finally:
        conn.close()
