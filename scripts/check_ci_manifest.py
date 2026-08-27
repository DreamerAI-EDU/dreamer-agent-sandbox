#!/usr/bin/env python3
"""B31: CI manifest vs on-disk test suite consistency guard.

Compares the test files actually tracked in the repo (A) against the ones
declared in the phase2-tests pytest command in .github/workflows/ci.yml (B).

- A - B (test file exists but MISSING from CI list): a real incident — the
  new test would silently never run. Reported as RED, exits non-zero.
- B - A (listed in CI but file no longer tracked): housekeeping only — the
  list entry is stale. Reported as a WARNING, does not fail the build.

Exit codes:
  0   consistent (or only stale-list warnings)
  1   at least one test file is missing from the CI list
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI_REL = Path(".github/workflows/ci.yml")


def tracked_test_files() -> set[str]:
    """A: all tests/test_*.py files currently tracked by git."""
    r = subprocess.run(
        ["git", "ls-files", "tests/test_*.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    return {p.replace("\\", "/").removeprefix("tests/")
            for p in r.stdout.split() if p}


def ci_listed_test_files() -> set[str]:
    """B: test files named in the pytest invocation inside ci.yml."""
    ci = (REPO / CI_REL).read_text(encoding="utf-8")
    # anchor on the literal `run: pytest ` command line so that annotation
    # comments (which may themselves mention "pytest") cannot be matched
    m = re.search(r"run:\s*pytest\s+(.*?)-v\s+--tb=short", ci, re.S)
    if not m:
        sys.exit("check_ci_manifest: cannot locate pytest command in ci.yml")
    return set(re.findall(r"test_[\w]+\.py", m.group(1)))


def main() -> int:
    real = tracked_test_files()
    listed = ci_listed_test_files()

    missing = sorted(real - listed)   # A - B  -> RED
    stale = sorted(listed - real)     # B - A  -> WARNING

    print(f"tracked test files     : {len(real)}")
    print(f"ci.yml listed files    : {len(listed)}")

    if missing:
        print("\n[RED] test file(s) tracked but MISSING from ci.yml pytest list:")
        for f in missing:
            print(f"  - tests/{f}")
    if stale:
        print("\n[WARN] listed in ci.yml but not tracked anymore (housekeeping):")
        for f in stale:
            print(f"  - tests/{f}")

    if missing:
        print(f"\nFAIL: {len(missing)} test file(s) would never run in CI.")
        return 1
    if stale:
        print(f"\nPASS: suite consistent ({len(real)} files); "
              f"{len(stale)} stale list entry (fix at leisure).")
    else:
        print(f"\nPASS: suite consistent, {len(real)}/{len(real)} aligned with ci.yml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
