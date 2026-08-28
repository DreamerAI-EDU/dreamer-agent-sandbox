"""Security primitives for the auth core: Argon2id hashing, session tokens,
login failure counters, lockout and IP rate limiting.

Design notes (per W2 spec §4 / PR brief §2-§3):
- Passwords: Argon2id via argon2-cffi with library defaults (RFC 9106
  recommended profile). Fixtures must never use real passwords.
- Session tokens: secrets.token_urlsafe(32) — >= 32 bytes entropy. uuid is
  NOT acceptable as a security token.
- Lockout: 5 consecutive failures per email → lock_until = now + 15 min.
- IP rate limit: 20 failures per hour per IP → IP locked for 1 hour.
  Counter storage: in-memory dict (process-local). Documented in PR
  description — adequate for the current single-process backend; a shared
  store (Redis) is out of scope for PR#1.
- Unified responses: no code path may reveal whether an email is registered
  (timing-safe dummy verify on unknown email).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

logger = logging.getLogger("dreamer.auth.security")

_hasher = PasswordHasher()

# A fixed Argon2id hash of a throwaway value used only to equalize login
# timing for unknown emails (never a real password).
_DUMMY_PASSWORD_HASH = _hasher.hash("dummy-timing-equalizer-not-a-real-password")

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Argon2id hash with library defaults (RFC 9106 recommended)."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2id hash.

    Never raises for malformed hashes (treated as mismatch) so the unified
    error path is safe even if a DB row is corrupt.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """Run a dummy Argon2 verify for unknown emails (timing equalizer).

    Result is discarded; it only consumes comparable CPU time so response
    time does not reveal whether an email is registered.
    """
    try:
        _hasher.verify(_DUMMY_PASSWORD_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


# ---------------------------------------------------------------------------
# Session tokens / verification tokens
# ---------------------------------------------------------------------------

def new_session_token() -> str:
    """Cryptographically random session token (>= 32 bytes entropy)."""
    return secrets.token_urlsafe(32)


def new_verify_token() -> str:
    """Cryptographically random single-use verification token."""
    return secrets.token_urlsafe(32)


def constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ---------------------------------------------------------------------------
# Per-email lockout (DB-backed fields) + per-IP rate limit (in-memory)
# ---------------------------------------------------------------------------

class IpRateLimiter:
    """Process-local per-IP failure counter (20 failures / rolling hour).

    Chosen storage: in-memory dict — see module docstring. Thread-safe via
    an RLock; entries are pruned lazily.
    """

    MAX_FAILURES_PER_HOUR = 20
    LOCK_SECONDS = 3600  # 1 hour

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # ip -> list[epoch seconds of failed login attempts]
        self._failures: dict[str, list[float]] = {}
        # ip -> epoch seconds until which the IP is blocked
        self._blocked_until: dict[str, float] = {}

    def record_failure(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            window = [t for t in self._failures.get(ip, []) if now - t < 3600]
            window.append(now)
            self._failures[ip] = window
            if len(window) >= self.MAX_FAILURES_PER_HOUR:
                self._blocked_until[ip] = now + self.LOCK_SECONDS

    def is_blocked(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            until = self._blocked_until.get(ip, 0)
            if until > now:
                return True
            if until != 0:
                # lock expired — reset state
                self._blocked_until.pop(ip, None)
                self._failures.pop(ip, None)
            return False

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)
            self._blocked_until.pop(ip, None)


# Module-level singleton used by the API layer.
ip_rate_limiter = IpRateLimiter()
