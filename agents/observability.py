"""
Dreamer AI Phase 5 — Observability layer (obs_events).

Fail-silent by design: this is telemetry, not safety evidence.
Per Phase 5 red-line:
  - No module-level _TABLE_ENSURED global (inline CREATE IF NOT EXISTS only)
  - routing events only store matched keyword (never raw student query)
  - safety events only store pointer (safety_event_id + block_type)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

# ── Event type constants ─────────────────────────────────

EVENT_ROUTING       = "routing"
EVENT_SAFETY_BLOCK  = "safety_block"
EVENT_LLM_CALL      = "llm_call"
EVENT_SESSION_START = "session_start"
EVENT_SESSION_END   = "session_end"
EVENT_ERROR         = "error"


# ── emit_event ───────────────────────────────────────────

def emit_event(
    event_type: str,
    event_data: dict,
    *,
    student_id: str = "",
    session_id: str = "",
) -> None:
    """Write one row to obs_events. Fail-silent — never blocks execution.

    Per Phase 5 red-line:
      - event_data for routing must only contain matched keyword, not raw text.
      - event_data for safety_block must only contain pointer (safety_event_id + block_type).
      - This is telemetry, not safety evidence — fail-silent is acceptable.
    """
    try:
        db_path = os.path.abspath(os.environ.get(
            "DREAMER_DB_PATH",
            os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
        ))
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS obs_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_obs_type_time
                    ON obs_events(event_type, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_obs_session
                    ON obs_events(session_id, created_at DESC);
            """)
            conn.execute(
                """INSERT INTO obs_events
                   (student_id, session_id, event_type, event_data, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    student_id,
                    session_id,
                    event_type,
                    json.dumps(event_data, ensure_ascii=False, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log.debug("obs_events write skipped (non-critical): %s", exc)
