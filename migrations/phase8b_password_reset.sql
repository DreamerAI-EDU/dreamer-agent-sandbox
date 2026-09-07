-- Phase 8b (W4 PR-D): forgot-password reset token table — password_reset_tokens
-- Run against Dreamer DB (SQLite, DREAMER_DB_PATH or default repo dreamer.db).
-- Idempotent: all statements use IF NOT EXISTS, safe to re-run.
-- NOTE: DB stores ONLY the SHA-256 hash of the raw reset token (three-iron-rule);
--       the plaintext token appears only in the emailed reset link.

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash TEXT PRIMARY KEY,           -- SHA-256 hex of the raw token (never the raw token)
    user_id    TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,              -- ISO timestamp; now + RESET_TOKEN_MINUTES (default 60)
    used_at    TEXT,                       -- ISO timestamp; single-use marker
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id, expires_at);
