"""
Dreamer AI Phase 5 — Health Monitor

Usage:
    python scripts/health_monitor.py --once    # exit 0 on healthy, 1 on unhealthy
    python scripts/health_monitor.py           # continuous mode (Ctrl-C to stop)

Health check: DB reachable + obs_events table exists.
Continuous mode: polls every 30s; 3 consecutive failures → exit 1.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time


def check_health(db_path: str) -> bool:
    """Return True if the system is healthy (DB reachable, obs_events initialized)."""
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            # Verify obs_events table exists (system fully initialized)
            cur = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='obs_events'"
            )
            return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Dreamer AI health monitor")
    parser.add_argument(
        "--once", action="store_true",
        help="Run one health check and exit. Exit 0 = healthy, 1 = unhealthy.",
    )
    args = parser.parse_args()

    db_path = os.path.abspath(os.environ.get(
        "DREAMER_DB_PATH",
        os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
    ))

    if args.once:
        if check_health(db_path):
            sys.exit(0)
        else:
            sys.exit(1)

    # Continuous mode
    consecutive_failures = 0
    while True:
        if check_health(db_path):
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(
                    f"[health_monitor] {consecutive_failures} consecutive "
                    f"failures — exiting with code 1",
                    file=sys.stderr,
                )
                sys.exit(1)
        time.sleep(30)


if __name__ == "__main__":
    main()
