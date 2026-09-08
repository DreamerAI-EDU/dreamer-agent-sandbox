"""W6 PR-B — Data retention cleanup for the auth/learning SQLite DB.

Policy (single source of truth, mirrors privacy policy three-language copy
and D-W6-7 / D-W6-10 decisions):

  * safety_events (welfare events, authdb):
      - reviewed rows          -> DELETE after 90 days.
      - unreviewed rows         -> NEVER deleted by this job. They are
        listed separately (never silently mixed into the delete batch).
        The real defence is health_monitor --check-retention failing loud
        when an unreviewed event is older than 7 days (same family as the
        W6-R1 high-risk notification workflow).
  * learning records (six authdb tables: assessment_logs,
    progress_snapshots, portfolio_items, plan_proposals, session_logs,
    obs_events):
      - student-level proxy for "course finished": a student whose latest
        learning activity (max(created_at) across the six tables) is older
        than LEARNING_RETENTION_MONTHS (12 months) is treated as finished;
        ALL six tables are cascade-deleted for that student. Reports list
        students, not rows. Active students are never touched.

chat_history.db (DeepTutor container) is handled by scripts/
chat_history_cleanup.py — same policy family, different execution plane
(container), kept as a separate module.

Red lines (unchanged from W6):
  * dry-run first: the job ALWAYS reports before it deletes.
  * real deletes require an explicit --apply flag.
  * a last-run marker file is written after an --apply run (dry-runs
    never write it) so health_monitor --check-retention can fail loud
    if the DELETE cron slips.

Usage:
    python scripts/retention_cleanup.py --dry-run [--db <path>] [--marker <path>]
    python scripts/retention_cleanup.py --apply   [--db <path>] [--marker <path>]

Exit codes: 0 ok; 2 usage/error. Deleting nothing is still exit 0; the
report carries the numbers.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

WELFARE_RETENTION_DAYS = 90          # reviewed safety_events
LEARNING_RETENTION_MONTHS = 12       # student-level inactivity proxy
UNREVIEWED_ALERT_DAYS = 7            # health_monitor threshold (fail-loud)

# The six learning-record tables (all live in the authdb / dreamer.db).
LEARNING_TABLES: tuple[str, ...] = (
    "assessment_logs",
    "progress_snapshots",
    "portfolio_items",
    "plan_proposals",
    "session_logs",
    "obs_events",
)

DEFAULT_DB = Path(__file__).resolve().parent.parent / "dreamer.db"
DEFAULT_MARKER = Path(__file__).resolve().parent.parent / "state" / "retention_last_run.json"


def _now_utc() -> str:
    """ISO-8601 UTC (lexicographically comparable with SQLite datetime())."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")  # wait out brief writer locks
    return conn


# ---------------------------------------------------------------------------
# Safety events
# ---------------------------------------------------------------------------

def plan_safety_cleanup(
    conn: sqlite3.Connection,
    cutoff_utc: str,
) -> dict[str, Any]:
    """Classify safety_events into a delete batch (reviewed + older than the
    cutoff) and a separate unreviewed listing.

    Never returns unreviewed rows inside the delete batch.
    """
    delete_rows = conn.execute(
        """SELECT id, student_id, event_type, severity, created_at, reviewed
             FROM safety_events
            WHERE reviewed = 1 AND created_at < ?""",
        (cutoff_utc,),
    ).fetchall()

    unreviewed_rows = conn.execute(
        """SELECT id, student_id, event_type, severity, created_at, reviewed
             FROM safety_events
            WHERE reviewed = 0
            ORDER BY created_at DESC, id DESC""",
    ).fetchall()

    oldest_unreviewed = None
    if unreviewed_rows:
        oldest_unreviewed = min(
            (r["created_at"] for r in unreviewed_rows),
        )

    return {
        "delete_batch": [dict(r) for r in delete_rows],
        "unreviewed": [dict(r) for r in unreviewed_rows],
        "oldest_unreviewed_at": oldest_unreviewed,
    }


def apply_safety_deletes(conn: sqlite3.Connection, ids: list[str]) -> int:
    if not ids:
        return 0
    cur = conn.executemany(
        "DELETE FROM safety_events WHERE id = ?",
        [(i,) for i in ids],
    )
    return cur.rowcount if cur.rowcount != -1 else len(ids)


# ---------------------------------------------------------------------------
# Learning records (student-level)
# ---------------------------------------------------------------------------

def _student_last_activity_sql() -> str:
    """Overall max(created_at) per student across the six learning tables.

    UNION ALL + outer MAX avoids per-table ordering surprises and stays
    valid even when some tables are empty (empty GROUP BY simply yields no
    rows for that table).
    """
    branches = "\n  UNION ALL\n".join(
        f"SELECT student_id, MAX(created_at) AS last_activity "
        f"FROM {t} GROUP BY student_id"
        for t in LEARNING_TABLES
    )
    return (
        "SELECT student_id, MAX(last_activity) AS last_activity "
        "FROM (\n" + branches + "\n) GROUP BY student_id"
    )


def plan_learning_cleanup(
    conn: sqlite3.Connection,
    cutoff_utc: str,
) -> dict[str, Any]:
    """Students whose latest activity is older than the cutoff, with per-
    table row counts (for dry-run reports and apply-time sanity checks)."""
    rows = conn.execute(
        "SELECT student_id, last_activity FROM (" + _student_last_activity_sql() + ")"
        " WHERE last_activity < ? ORDER BY last_activity",
        (cutoff_utc,),
    ).fetchall()

    students: list[dict[str, Any]] = []
    for r in rows:
        per_table: dict[str, int] = {}
        for t in LEARNING_TABLES:
            n = conn.execute(
                f"SELECT COUNT(*) AS n FROM {t} WHERE student_id = ?",
                (r["student_id"],),
            ).fetchone()["n"]
            per_table[t] = n
        students.append(
            {
                "student_id": r["student_id"],
                "last_activity": r["last_activity"],
                "per_table_rows": per_table,
                "total_rows": sum(per_table.values()),
            }
        )
    return {"students": students}


def apply_learning_deletes(
    conn: sqlite3.Connection,
    student_ids: list[str],
) -> dict[str, int]:
    """Cascade-delete one student across all six learning tables."""
    deleted: dict[str, int] = {}
    for t in LEARNING_TABLES:
        count = 0
        for sid in student_ids:
            cur = conn.execute(f"DELETE FROM {t} WHERE student_id = ?", (sid,))
            count += cur.rowcount if cur.rowcount != -1 else 0
        deleted[t] = count
    return deleted


# ---------------------------------------------------------------------------
# Report + marker
# ---------------------------------------------------------------------------

def build_report(
    *,
    mode: str,
    run_at: str,
    welfare_cutoff: str,
    learning_cutoff: str,
    safety: dict[str, Any],
    learning: dict[str, Any],
    applied: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "run_at": run_at,
        "mode": mode,
        "cutoffs": {
            "welfare_reviewed_deleted_before": welfare_cutoff,
            "learning_inactive_before": learning_cutoff,
        },
        "safety_events": {
            "reviewed_delete_candidates": len(safety["delete_batch"]),
            "unreviewed_kept": len(safety["unreviewed"]),
            "oldest_unreviewed_at": safety["oldest_unreviewed_at"],
            "candidates": safety["delete_batch"],
            "unreviewed": safety["unreviewed"],
        },
        "learning_records": {
            "inactive_students": len(learning["students"]),
            "students": learning["students"],
        },
        "applied": applied,
    }


def render_human(report: dict[str, Any]) -> str:
    lines: list[str] = []
    s = report["safety_events"]
    lr = report["learning_records"]
    lines.append(f"retention_cleanup [{report['mode']}] run at {report['run_at']} UTC")
    lines.append(
        f"  safety_events: {s['reviewed_delete_candidates']} reviewed candidate(s) "
        f"for deletion (cutoff {report['cutoffs']['welfare_reviewed_deleted_before']}); "
        f"{s['unreviewed_kept']} unreviewed kept (oldest at {s['oldest_unreviewed_at']})"
    )
    if s["reviewed_delete_candidates"]:
        lines.append("  safety delete candidates (reviewed):")
        for ev in s["candidates"]:
            lines.append(
                f"    - {ev['id']} {ev['event_type']}/{ev['severity']} "
                f"created {ev['created_at']} student={ev['student_id']}"
            )
    if s["unreviewed_kept"]:
        lines.append("  safety unreviewed (NOT deleted, separate column):")
        for ev in s["unreviewed"]:
            lines.append(
                f"    - {ev['id']} {ev['event_type']}/{ev['severity']} "
                f"created {ev['created_at']} student={ev['student_id']}"
            )
    lines.append(
        f"  learning_records: {lr['inactive_students']} inactive student(s) "
        f"(cutoff {report['cutoffs']['learning_inactive_before']})"
    )
    for stu in lr["students"]:
        per = ", ".join(f"{t}={n}" for t, n in stu["per_table_rows"].items() if n)
        lines.append(
            f"    - student {stu['student_id']} last_activity "
            f"{stu['last_activity']} total_rows={stu['total_rows']} ({per})"
        )
    if report["applied"]:
        ap = report["applied"]
        lines.append(
            f"  applied: safety deleted {ap['safety_deleted']}; "
            f"learning deleted {ap['learning_deleted_per_table']}"
        )
    return "\n".join(lines)


def write_marker(marker_path: Path, report: dict[str, Any]) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": report["run_at"],
        "mode": report["mode"],
        "safety_reviewed_delete_candidates": report["safety_events"][
            "reviewed_delete_candidates"
        ],
        "unreviewed_kept": report["safety_events"]["unreviewed_kept"],
        "oldest_unreviewed_at": report["safety_events"]["oldest_unreviewed_at"],
        "learning_inactive_students": report["learning_records"][
            "inactive_students"
        ],
    }
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="W6 PR-B retention cleanup (authdb: safety_events + "
                    "learning records). Dry-run by default.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete. Default is dry-run (report only).",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB,
        help=f"SQLite database path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--marker", type=Path, default=DEFAULT_MARKER,
        help=f"last-run marker path (default: {DEFAULT_MARKER})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON report on stdout instead of human text.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[retention_cleanup] db not found: {args.db}", file=sys.stderr)
        return 2

    run_at = _now_utc()
    welfare_cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=WELFARE_RETENTION_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    learning_cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=30 * LEARNING_RETENTION_MONTHS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = _connect(args.db)
    try:
        safety = plan_safety_cleanup(conn, welfare_cutoff)
        learning = plan_learning_cleanup(conn, learning_cutoff)

        applied: Optional[dict[str, Any]] = None
        if args.apply:
            applied = {}
            safety_deleted = apply_safety_deletes(
                conn,
                [r["id"] for r in safety["delete_batch"]],
            )
            learning_ids = [s["student_id"] for s in learning["students"]]
            per_table = apply_learning_deletes(conn, learning_ids)
            applied = {
                "safety_deleted": safety_deleted,
                "learning_deleted_per_table": per_table,
                "learning_students_deleted": len(learning_ids),
            }
            conn.commit()

        report = build_report(
            mode="apply" if args.apply else "dry-run",
            run_at=run_at,
            welfare_cutoff=welfare_cutoff,
            learning_cutoff=learning_cutoff,
            safety=safety,
            learning=learning,
            applied=applied,
        )
        # Marker semantics: proves the DELETE cron actually ran. A dry-run
        # must NOT write it, or health_monitor would report healthy while
        # the apply job silently stopped running.
        if args.apply:
            write_marker(args.marker, report)

        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(render_human(report))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
