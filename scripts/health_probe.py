#!/usr/bin/env python3
"""Container-side probe for dreamer-api (Gate-B leg ③).

Called by the Dockerfile ``HEALTHCHECK`` against 127.0.0.1:8000/health, and by
hand from the VPS as ``python scripts/health_probe.py --url http://127.0.0.1:8000/health``.

Exit codes: 0 = 200 with ``status: ok``; 1 = anything else (non-200, degraded
body, connection refused, timeout). One line on stdout, never a traceback —
probe noise in ``docker inspect`` is worse than no probe.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000/health"
DEFAULT_TIMEOUT = 4.0


def probe(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = resp.status
            raw = resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 503 from a degraded app
        detail = "degraded"
        try:
            detail = json.loads(exc.read(4096).decode("utf-8", "replace")).get(
                "status", "degraded"
            )
        except Exception:  # noqa: BLE001 — body may be empty
            pass
        return False, f"HTTP {exc.code} ({detail})"
    except Exception as exc:  # noqa: BLE001 — refused / timeout / DNS
        return False, f"{type(exc).__name__}: {exc}"

    if code != 200:
        return False, f"HTTP {code}"
    try:
        body = json.loads(raw)
    except Exception:  # noqa: BLE001
        return False, "body is not JSON"
    status = body.get("status")
    if status != "ok":
        return False, f"status={status!r}"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dreamer-api health probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    healthy, detail = probe(args.url, args.timeout)
    print(("HEALTHY: " if healthy else "UNHEALTHY: ") + detail)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
