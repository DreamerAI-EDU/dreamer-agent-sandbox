"""Relay audit sink for the WS chat relay (W3-C P3: relay resilience).

Why this module exists
----------------------
The relay (auth/ws_chat.py) is the only place that can see the *shape* of a
failed turn: how many times it was re-sent, whether the student had already
seen an answer chunk when the upstream failed, and whether a watchdog had to
step in. Without a durable record, "429 間歇" stays a rumour — we cannot tell
transient upstream pressure from a real regression.

What lands here (boss work order 2026-09-14, review condition 3)
---------------------------------------------------------------
Every non-happy path is recorded, each with an ``upstream_error`` code:

* ``turn_retry``       — a re-send attempt, with ``attempt`` = which one (1-based)
* ``midstream_error``  — a non-retry 429 (content already on screen: no retry by
                         design, but never silent — the student gets a localized
                         graceful message)
* ``watchdog_kill``    — idle-based 90s watchdog reaped an open turn
* ``upstream_unavailable`` — the relay could not even dial the upstream

plus the two bookends (``turn_start`` / ``turn_end`` with ``final_status``) so a
turn can be reconstructed end to end. Success-only logging is what we are
trying to avoid.

Rules baked in
--------------
* Append-only. The table carries DB-level triggers that abort UPDATE/DELETE
  (migrations/phase8f_ws_chat_relay_audit.sql) — a row is evidence.
* No PII. The student is identified by the 8-char masked prefix the request
  already carried (W2 PR#3: full student ids never leave the server, and never
  enter an append-only record). No prompt text, no upstream payloads.
* Fail-open. An audit failure must never break a child's turn or mask the
  original relay error, so every write swallows its exception and logs a
  warning instead.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Optional

from . import db as auth_db

logger = logging.getLogger("dreamer.auth.relay_audit")

# --- events ---------------------------------------------------------------

EVENT_TURN_START = "turn_start"
EVENT_TURN_RETRY = "turn_retry"
EVENT_MIDSTREAM_ERROR = "midstream_error"
EVENT_WATCHDOG_KILL = "watchdog_kill"
EVENT_TURN_END = "turn_end"
EVENT_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
EVENT_SESSION_MAP_INVALIDATED = "session_map_invalidated"
EVENT_GREETING_SHORT_CIRCUIT = "greeting_short_circuit"
#: PR-C item 5 — a frame the relay wanted to forward to the child could not be
#: delivered (client socket died mid-stream). Previously only a log warning;
#: now an audit row so delivery gaps are reconstructable end to end.
EVENT_DELIVERY_FAIL = "delivery_fail"
#: PR-D-b — the engine asked the child to pick an option on a clarification
#: card. The frame itself is forwarded verbatim (it is a contract frame now);
#: the row exists so "the turn was waiting on a human" is reconstructable and
#: separable from "the engine went quiet" (watchdog) in the ledger.
EVENT_TOOL_CALL = "tool_call"
#: PR-D-b — the child's pick came back and was forwarded upstream on the same
#: open turn. One row per forwarded pick; a dropped (non-pending) pick leaves
#: no row, exactly like the frame it never sent.
EVENT_TOOL_RESULT = "tool_result"
#: PR-D-b — the clarify wait budget expired while the turn was still awaiting
#: the child's pick. Paired with ERR_CLARIFY_TIMEOUT on the midstream row and
#: on the turn_end row so a killed wait is never mistaken for an idle kill.
EVENT_CLARIFY_TIMEOUT = "clarify_timeout"

#: every event name this module may write (nothing else is allowed into the table)
EVENTS = (
    EVENT_TURN_START,
    EVENT_TURN_RETRY,
    EVENT_MIDSTREAM_ERROR,
    EVENT_WATCHDOG_KILL,
    EVENT_TURN_END,
    EVENT_UPSTREAM_UNAVAILABLE,
    EVENT_SESSION_MAP_INVALIDATED,
    EVENT_GREETING_SHORT_CIRCUIT,
    EVENT_DELIVERY_FAIL,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_CLARIFY_TIMEOUT,
)

# --- upstream_error codes (normalized; the relay never logs raw upstream text) --

ERR_RATE_LIMITED = "rate_limited"          # upstream 429 / quota exhausted
#: a terminal upstream `error` frame that is *not* a rate limit (500 / timeout /
#: provider fault). Never retried: retry budget is spent on rate limits only.
ERR_UPSTREAM_ERROR = "upstream_error"
ERR_UPSTREAM_CLOSED = "upstream_closed"    # upstream socket died mid-turn
ERR_IDLE_TIMEOUT = "idle_timeout"          # watchdog: zero upstream frames
ERR_CONNECT_FAILED = "connect_failed"      # relay could not dial the upstream
#: upstream refused a NEW turn because this engine session already has an
#: active turn (same student, second tab). Distinct from rate_limited on
#: purpose: busy never spends the retry budget and is audited separately.
ERR_SESSION_BUSY = "session_busy"
#: PR-D-b — the child never picked an option on a clarification card within
#: `_CLARIFY_WAIT_MAX_SECONDS` (design v0.2.1 §A.5). Deliberately NOT
#: ERR_IDLE_TIMEOUT: the engine was not silent here, the turn was parked on a
#: human, and the two must stay separable in the ledger. Non-retryable.
ERR_CLARIFY_TIMEOUT = "clarify_timeout"

# --- final_status values --------------------------------------------------

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_ABORTED = "aborted"

_INSERT_SQL = (
    "INSERT INTO ws_chat_relay_audit"
    " (occurred_at, event, session_id, turn_id, student_mask, attempt,"
    "  final_status, upstream_error, detail)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def record(
    event: str,
    *,
    student_mask: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    attempt: Optional[int] = None,
    final_status: Optional[str] = None,
    upstream_error: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Append one relay audit row. Never raises (fail-open by design)."""
    params = (
        _now_iso(),
        event,
        session_id,
        turn_id,
        student_mask,
        attempt,
        final_status,
        upstream_error,
        detail,
    )
    try:
        conn = auth_db.connect()
        try:
            try:
                conn.execute(_INSERT_SQL, params)
            except Exception:
                # A DB that predates phase8f (or a fresh tmp DB) may not carry
                # the table yet: ensure_schema() is idempotent, so bootstrap
                # once and retry — the deploy window itself needs no step.
                conn.rollback()
                auth_db.ensure_schema()
                conn.execute(_INSERT_SQL, params)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — auditing must never break a turn
        logger.warning("relay audit write failed event=%s err=%s", event, exc)


def rows(
    *,
    event: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read back audit rows (operator / test helper). Newest first."""
    sql = "SELECT * FROM ws_chat_relay_audit"
    where: list[str] = []
    params: list[Any] = []
    if event:
        where.append("event = ?")
        params.append(event)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))

    conn = auth_db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
