"""W6 PR-B — Chat history retention cleanup (DeepTutor chat_history.db).

Policy: AI chat sessions with no activity for CHAT_RETENTION_DAYS (90) are
deleted. The sessions table is the deletion root; messages / turns /
turn_events / notebook_entries / notebook_entry_categories are removed via
SQLite ON DELETE CASCADE (foreign_keys pragma is enabled per-connection).

Execution plane (volume is NOT shared with the repo host — verified W6 PR-B
kickoff: deeptutor_dreamer_api_data is only mounted on dreamer-api; the
deeptutor container keeps /app/data/user/chat_history.db on its own
writable layer). So the repo host cannot open the DB directly:

  * container mode  — run INSIDE the deeptutor container (or a temp db for
    tests). This is the tested core: plan + apply.
  * host mode       — the VPS cron entry. docker cp this script into
    dreamer-deeptutor:/tmp, docker exec python3 <script> --db
    /app/data/user/chat_history.db, capture the JSON report and write the
    host-side last-run marker (health_monitor --check-retention reads it).

Usage:
    # inside deeptutor container / tests:
    python scripts/chat_history_cleanup.py --dry-run [--db <path>]
    python scripts/chat_history_cleanup.py --apply   [--db <path>]

    # VPS host (cron):
    python scripts/chat_history_cleanup.py --host --apply \
        [--container dreamer-deeptutor] [--marker <host marker path>]

Exit codes: 0 ok; 2 usage/error.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

CHAT_RETENTION_DAYS = 90
DEFAULT_CONTAINER = "dreamer-deeptutor"
CONTAINER_DB = "/app/data/user/chat_history.db"
DEFAULT_HOST_MARKER = (
    Path(__file__).resolve().parent.parent / "state" / "chat_retention_last_run.json"
)


# ---------------------------------------------------------------------------
# Core (container / test side)
# ---------------------------------------------------------------------------

def _connect(db_path: Path):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # deeptutor may hold short write locks
    return conn


def plan_chat_cleanup(conn, cutoff_epoch: float) -> dict[str, Any]:
    """Sessions with updated_at older than the cutoff, plus per-session
    descendant row counts (dry-run reporting)."""
    rows = conn.execute(
        """SELECT id, title, created_at, updated_at
             FROM sessions
            WHERE updated_at < ? AND updated_at > 0
            ORDER BY updated_at""",
        (cutoff_epoch,),
    ).fetchall()
    sessions = []
    for r in rows:
        sessions.append(
            {
                "session_id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return {"sessions": sessions, "session_count": len(sessions)}


def apply_chat_deletes(conn, session_ids: list[str]) -> dict[str, int]:
    """DELETE root sessions; FK cascade removes descendants."""
    if not session_ids:
        return {}
    conn.execute("PRAGMA foreign_keys=ON")  # cascade is per-connection
    before = {}
    for t in ("messages", "turns", "turn_events", "notebook_entries",
              "notebook_entry_categories"):
        before[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    cur = conn.executemany(
        "DELETE FROM sessions WHERE id = ?",
        [(sid,) for sid in session_ids],
    )
    deleted_sessions = cur.rowcount if cur.rowcount != -1 else len(session_ids)
    after = {}
    for t in before:
        after[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    cascade = {t: before[t] - after[t] for t in before}
    cascade["sessions"] = deleted_sessions
    return cascade


def render_human(report: dict[str, Any]) -> str:
    lines = [
        f"chat_history_cleanup [{report['mode']}] run at {report['run_at']} UTC",
        f"  sessions older than {report['cutoff_iso']} "
        f"(updated_at < {report['cutoff_epoch']:.0f}): "
        f"{report['session_count']}",
    ]
    for s in report["sessions"][:200]:
        lines.append(
            f"    - {s['session_id']} updated {s['updated_at']:.0f} "
            f"title={s['title']!r}"
        )
    if report["session_count"] > 200:
        lines.append(f"    ... and {report['session_count'] - 200} more")
    if report.get("applied"):
        lines.append(
            "  applied: " + ", ".join(
                f"{k}={v}" for k, v in report["applied"].items()
            )
        )
    return "\n".join(lines)


def run_core(db_path: Path, apply: bool) -> dict[str, Any]:
    """Container-side logic: plan (+apply) against db_path. Pure, testable."""
    cutoff_epoch = time.time() - CHAT_RETENTION_DAYS * 86400
    cutoff_iso = datetime.datetime.fromtimestamp(
        cutoff_epoch, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    run_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = _connect(db_path)
    try:
        plan = plan_chat_cleanup(conn, cutoff_epoch)
        applied = None
        if apply:
            applied = apply_chat_deletes(
                conn, [s["session_id"] for s in plan["sessions"]]
            )
            conn.commit()
        return {
            "run_at": run_at,
            "mode": "apply" if apply else "dry-run",
            "db": str(db_path),
            "cutoff_epoch": cutoff_epoch,
            "cutoff_iso": cutoff_iso,
            "session_count": plan["session_count"],
            "sessions": plan["sessions"],
            "applied": applied,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Host-side wrapper (VPS cron)
# ---------------------------------------------------------------------------

def run_host(container: str, apply: bool, marker_path: Path) -> dict[str, Any]:
    """docker cp this script into the container, exec it, parse the JSON
    report and write the host-side last-run marker."""
    script = Path(__file__).resolve()
    remote = "/tmp/chat_history_cleanup.py"
    subprocess.run(
        ["docker", "cp", str(script), f"{container}:{remote}"],
        check=True,
        capture_output=True,
        text=True,
    )
    cmd = [
        "docker", "exec", container, "python3", remote,
        "--db", CONTAINER_DB,
    ]
    if apply:
        cmd.append("--apply")
    cmd.append("--json")
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    report = json.loads(proc.stdout)
    # Marker is written only on apply runs — a dry-run marker would fool the
    # retention health check into thinking the deletion job actually ran.
    if not apply:
        return report
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "run_at": report["run_at"],
        "mode": report["mode"],
        "container": container,
        "session_count": report["session_count"],
        "cutoff_iso": report["cutoff_iso"],
        "applied": report.get("applied"),
    }
    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="W6 PR-B chat history retention cleanup "
                    "(dry-run by default).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete. Default is dry-run (report only).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicit dry-run (default behaviour; accepted for clarity).",
    )
    parser.add_argument(
        "--host", action="store_true",
        help="Host mode: docker cp + docker exec into the deeptutor container.",
    )
    parser.add_argument(
        "--container", default=DEFAULT_CONTAINER,
        help=f"Container name for --host (default: {DEFAULT_CONTAINER})",
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help="SQLite path (container mode; default: /app/data/user/chat_history.db).",
    )
    parser.add_argument(
        "--marker", type=Path, default=DEFAULT_HOST_MARKER,
        help=f"Host-side last-run marker (default: {DEFAULT_HOST_MARKER})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON report on stdout.",
    )
    args = parser.parse_args(argv)

    if args.host:
        report = run_host(args.container, args.apply, args.marker)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(render_human(report))
        return 0

    db_path = args.db or Path("/app/data/user/chat_history.db")
    if not db_path.exists():
        print(f"[chat_history_cleanup] db not found: {db_path}", file=sys.stderr)
        return 2
    report = run_core(db_path, args.apply)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
