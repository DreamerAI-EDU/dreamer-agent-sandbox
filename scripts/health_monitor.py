"""
Dreamer AI Phase 5 — Health Monitor

Usage:
    python scripts/health_monitor.py --once [--url http://localhost:8001]
    python scripts/health_monitor.py                  # continuous mode (Ctrl-C to stop)

Health check: DeepTutor container HTTP endpoint reachable.
  - GET /              → 200 = healthy
  - GET /api/v1/knowledge/health → 200 = healthy
Continuous mode: polls every 30s; 3 consecutive failures → exit 1.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import urllib.error


def check_health(url: str, timeout: int = 5) -> bool:
    """Return True if the DeepTutor endpoint is healthy."""
    try:
        req = urllib.request.Request(f"{url}/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
    except Exception:
        return False

    try:
        req2 = urllib.request.Request(f"{url}/api/v1/knowledge/health", method="GET")
        with urllib.request.urlopen(req2, timeout=timeout) as resp2:
            if resp2.status != 200:
                return False
    except Exception:
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Dreamer AI health monitor")
    parser.add_argument(
        "--once", action="store_true",
        help="Run one health check and exit. Exit 0 = healthy, 1 = unhealthy.",
    )
    parser.add_argument(
        "--url", default="http://localhost:8001",
        help="DeepTutor base URL (default: http://localhost:8001)",
    )
    args = parser.parse_args()

    if args.once:
        healthy = check_health(args.url)
        if healthy:
            print(f"[health_monitor] {args.url} is healthy")
        else:
            print(f"[health_monitor] {args.url} is unhealthy", file=sys.stderr)
        sys.exit(0 if healthy else 1)

    # Continuous mode
    consecutive_failures = 0
    while True:
        if check_health(args.url):
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            print(
                f"[health_monitor] {args.url} unhealthy — "
                f"{consecutive_failures}/3 consecutive failures",
                file=sys.stderr,
            )
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
