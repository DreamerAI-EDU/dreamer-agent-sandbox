"""
Dreamer AI Phase 1 — OTel SQLite Exporter
Minimal, zero-network SpanExporter that writes to a local SQLite database.
No external collector, no gRPC, no HTTP. Just spans in a file.
"""

import os
import sqlite3
import json
import time
import threading
from typing import Sequence, Optional
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace import ReadableSpan


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS spans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT    NOT NULL,
    span_id         TEXT    NOT NULL,
    parent_span_id  TEXT,
    name            TEXT    NOT NULL,
    kind            TEXT    NOT NULL DEFAULT 'INTERNAL',
    start_time      INTEGER NOT NULL,   -- nanoseconds since epoch
    end_time        INTEGER NOT NULL,
    duration_us     INTEGER NOT NULL,   -- microseconds, for easy querying
    status          TEXT    NOT NULL DEFAULT 'UNSET',
    status_message  TEXT,
    attributes      TEXT,               -- JSON blob
    events          TEXT,               -- JSON blob: [{name, timestamp, attributes}]
    resource        TEXT,               -- JSON blob: service info
    source          TEXT,               -- "state_bus", "agent:curriculum", etc.
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_parent   ON spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_spans_name     ON spans(name);
CREATE INDEX IF NOT EXISTS idx_spans_source   ON spans(source);
"""


class SQLiteSpanExporter(SpanExporter):
    """
    Dumps every span to a local SQLite file.

    Usage:
        exporter = SQLiteSpanExporter("traces.db")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    """

    def __init__(self, db_path: str, service_name: str = "dreamer-ai"):
        self.db_path = db_path
        self.service_name = service_name
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        with self._lock:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(CREATE_TABLE_SQL)
            conn.commit()
            self._conn = conn

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans or not self._conn:
            return SpanExportResult.SUCCESS

        rows = []
        for span in spans:
            ctx = span.get_span_context()
            if ctx is None:
                continue

            duration_ns = 0
            if span.start_time and span.end_time:
                duration_ns = span.end_time - span.start_time

            rows.append((
                self._format_trace_id(ctx.trace_id),
                self._format_span_id(ctx.span_id),
                self._format_span_id(span.parent.span_id) if span.parent else None,
                span.name or "unnamed",
                str(span.kind.name) if span.kind else "INTERNAL",
                span.start_time or 0,
                span.end_time or 0,
                duration_ns // 1000,  # ns → us
                str(span.status.status_code.name) if span.status else "UNSET",
                span.status.description if span.status else None,
                json.dumps(dict(span.attributes)) if span.attributes else None,
                json.dumps([
                    {"name": e.name, "timestamp": e.timestamp,
                     "attributes": dict(e.attributes) if e.attributes else {}}
                    for e in (span.events or [])
                ]) if span.events else None,
                json.dumps({
                    "service.name": self.service_name,
                    **{
                        k: v for k, v in (span.resource.attributes if span.resource else {}).items()
                    }
                }) if span.resource else None,
                dict(span.attributes).get("source", "") if span.attributes else "",
            ))

        with self._lock:
            try:
                self._conn.executemany(
                    """INSERT INTO spans
                       (trace_id, span_id, parent_span_id, name, kind,
                        start_time, end_time, duration_us, status, status_message,
                        attributes, events, resource, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                self._conn.commit()
            except sqlite3.Error as e:
                print(f"[OTel] SQLite write error: {e}")
                return SpanExportResult.FAILURE

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    # ── Helpers ──────────────────────────────────────────

    @staticmethod
    def _format_trace_id(trace_id: int) -> str:
        return format(trace_id, "032x")

    @staticmethod
    def _format_span_id(span_id: int) -> str:
        return format(span_id, "016x")


# ── Query helpers for CLI viewer ─────────────────────────

def query_trace_tree(db_path: str, trace_id_hex: str) -> list[dict]:
    """Return all spans for a trace, ordered by start_time."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM spans
           WHERE trace_id = ?
           ORDER BY start_time ASC""",
        (trace_id_hex,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_trace_summary(db_path: str) -> list[dict]:
    """Return all traces with span counts and total duration."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT trace_id,
                  COUNT(*) AS span_count,
                  MAX(duration_us) AS max_duration_us,
                  SUM(duration_us) AS total_duration_us,
                  MIN(created_at) AS first_seen,
                  MAX(created_at) AS last_seen
           FROM spans
           GROUP BY trace_id
           ORDER BY first_seen DESC
           LIMIT 20"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_errors(db_path: str) -> list[dict]:
    """Return spans with ERROR status."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT trace_id, span_id, name, status_message, source
           FROM spans
           WHERE status = 'ERROR'
           ORDER BY created_at DESC
           LIMIT 20"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
