-- Bridge-3d — student self-login (join code + PIN, no email).
--
-- Canonical DDL for the two tables behind POST /api/student/login
-- (dreamer-api). Mirrored in auth/db.py (_DDL) so a fresh DB bootstraps
-- without a migration runner — same convention as phase8_auth.sql /
-- phase8b_password_reset.sql / phase8c_class_curriculum.sql.
--
-- Design notes (boss work order 2026-09-13):
--   * A student has NO email and NO users row, so the parent/teacher
--     sessions table cannot hold a kid session. student_sessions is a
--     separate, independent credential store: server-side opaque token
--     (secrets.token_urlsafe, same grade as auth_session), never a JWT.
--   * student_login_locks is deliberately NOT students.failed_pin_count:
--     the existing pin-verify surface (parent/teacher delegated check) is
--     a locked contract at 10 failures / 1 minute, while this kid-facing
--     endpoint is 5 failures / 10 minutes. Two surfaces, two counters —
--     one can never lock the other out.
--   * The lock scope is the join code (case-normalised), not the student:
--     an attacker enumerating PINs cannot be charged to a single innocent
--     student, and a shared class code cannot be brute-forced past 5
--     attempts. A successful login clears the scope.

CREATE TABLE IF NOT EXISTS student_sessions (
    id         TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id),
    expires_at TEXT NOT NULL,
    created_ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_student_sessions_student
    ON student_sessions(student_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_student_sessions_expires
    ON student_sessions(expires_at);

CREATE TABLE IF NOT EXISTS student_login_locks (
    scope        TEXT PRIMARY KEY,          -- 'jc:<NORMALISED_JOIN_CODE>'
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,                      -- ISO timestamp while locked, else NULL
    updated_at   TEXT NOT NULL
);
