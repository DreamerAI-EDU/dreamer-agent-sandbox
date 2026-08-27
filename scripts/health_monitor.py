"""
Dreamer AI Phase 5 — Health Monitor (+ Phase 7 B22 KB fail-loud)

Usage:
    python scripts/health_monitor.py --once [--url http://localhost:8001]
    python scripts/health_monitor.py --once --check-kb [--kb-manifest kb/manifest.yaml] [--url ...]
    python scripts/health_monitor.py                  # continuous mode (Ctrl-C to stop)

Health check: DeepTutor container HTTP endpoint reachable.
  - GET /              → 200 = healthy
  - GET /api/v1/knowledge/health → 200 = healthy

--check-kb (B22) adds runtime KB fail-loud, aligned with `seed_kb --check`
semantics but runtime-only (no source frontmatter validation):
  - DeepTutor knowledge health status ok AND knowledge_bases_count > 0
  - every content KB (manifest expected_doc_count > 0) has raw_documents > 0
    (structural KBs — expected_doc_count == 0 — are skipped, raw 0 is normal)
  - embedding profile test passes
Exit codes: 0 ok / 1 KB fail-loud / 3 not ready (mirrors seed_kb EXIT_*).
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import urllib.error

import seed_kb  # B22: reuse TutorAPI + manifest semantics (single source of truth)


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


def check_kb(
    api_base: str,
    manifest_path: str,
    timeout: int = 10,
) -> tuple[int, str]:
    """B22 runtime KB fail-loud. Returns (exit_code, message).

    Mirrors `seed_kb --check` semantics but runtime-only: no source
    frontmatter scan — only live KB state via the DeepTutor API.
    """
    # 1. DeepTutor reachable + healthy + has KBs
    try:
        api = seed_kb.TutorAPI(api_base, timeout)
        health = api.health()
    except seed_kb.SeedError as exc:
        return seed_kb.EXIT_NOT_READY, f"DeepTutor not ready: {exc}"

    status = health.get("status")
    count = health.get("knowledge_bases_count", 0)
    if status != "ok":
        return seed_kb.EXIT_NOT_READY, f"DeepTutor status={status!r}"
    if count == 0:
        return seed_kb.EXIT_VERIFY_FAIL, f"KB count = 0 (B22 fail-loud)"

    # 2. manifest → structural (expected_doc_count 0) vs content KBs
    try:
        manifest = seed_kb.load_manifest(seed_kb.Path(manifest_path))
    except seed_kb.SeedError as exc:
        return seed_kb.EXIT_VERIFY_FAIL, f"manifest: {exc}"
    manifest_kbs = {
        entry["name"]: entry
        for entry in manifest["knowledge_bases"]
        if "name" in entry
    }
    structural = {
        name
        for name, entry in manifest_kbs.items()
        if entry.get("expected_doc_count", 0) == 0
    }

    # 3. content KBs must have raw_documents > 0
    try:
        kbs_api = {kb["name"]: kb for kb in api.list_kbs()}
    except seed_kb.SeedError as exc:
        return seed_kb.EXIT_NOT_READY, f"list_kbs failed: {exc}"
    for name in sorted(manifest_kbs):
        if name in structural:
            continue
        raw = ((kbs_api.get(name) or {}).get("statistics") or {}).get(
            "raw_documents", 0
        )
        if raw == 0:
            return seed_kb.EXIT_VERIFY_FAIL, f"KB {name}: raw_documents = 0 (B22 fail-loud)"

    # 4. embedding profile must work
    try:
        api.test_embeddings()
    except seed_kb.SeedError as exc:
        return seed_kb.EXIT_VERIFY_FAIL, f"embedding profile: {exc}"

    return (
        seed_kb.EXIT_OK,
        f"KB ok: {count} KBs, content raw_documents>0, embeddings ok",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dreamer AI health monitor")
    parser.add_argument(
        "--once", action="store_true",
        help="Run one health check and exit. Exit 0 = healthy, 1 = unhealthy.",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8001",
        help="DeepTutor base URL (default: http://127.0.0.1:8001)",
    )
    parser.add_argument(
        "--check-kb", action="store_true",
        help="B22: also run runtime KB fail-loud (count / raw_documents / embeddings)",
    )
    parser.add_argument(
        "--kb-manifest", default=str(seed_kb.MANIFEST_PATH),
        help="Manifest path for KB structural classification "
             f"(default: {seed_kb.MANIFEST_PATH})",
    )
    args = parser.parse_args()

    if args.once:
        healthy = check_health(args.url)
        if not healthy:
            print(f"[health_monitor] {args.url} is unhealthy", file=sys.stderr)
            sys.exit(1)
        if args.check_kb:
            code, msg = check_kb(args.url, args.kb_manifest, timeout=10)
            if code != seed_kb.EXIT_OK:
                print(f"[health_monitor --check-kb] {msg}", file=sys.stderr)
                sys.exit(code)
            print(f"[health_monitor --check-kb] {msg}")
        else:
            print(f"[health_monitor] {args.url} is healthy")
        sys.exit(0)

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
