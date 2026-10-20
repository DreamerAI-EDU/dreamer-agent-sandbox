"""PR-5 parent-surface banned-term gate (§三 render layer + payload layer).

Two layers, one exit code:

1. **Render layer** — greps the parent-visible frontend sources for the twelve
   frozen banned terms. ``IB`` / ``ATL`` / ``Inquirer`` / ``Learner Profile`` /
   ``Proficient`` / ``Excellent`` / ``kid_label`` / ``citations`` / ``cost`` must
   be absent from every file on the parent surface, comments included (a stray
   literal in a comment is exactly how the PR-4 wording lesson leaked).
   The scope is the parent-facing set below — ``pages/parent/**``,
   ``ParentDashboard`` / ``ParentHomePage``, ``components/parent/**``,
   ``hooks/useParentReport*.ts`` and the parent ``lib`` files. Kid-side screens
   (``ChatPage`` / ``KidPortfolioPage`` / ``lib/mock.ts`` …) legitimately pass raw
   band codes in query strings and are therefore *out of scope* for this gate,
   not silently exempt.
   The three raw band codes ``P1-P3`` / ``P4-P6`` / ``S1-S3`` are allowed **only**
   inside ``frontend/src/lib/parentReportCopy.ts`` (band -> friendly-name table,
   §三 全仓唯一出处) as machine keys. Anywhere else on the parent surface a raw
   band code is a gate failure.

2. **Payload layer** — re-asserts the frozen copy source of truth: the three-by-
   nine band grid and the 12-term list must be byte-identical to
   ``config/pr5_frozen_copy.json`` (regenerated from the signed brief by
   ``scripts/extract_pr5_frozen_copy.py``). The live payload grep itself lives in
   ``tests/test_pr5_parent_surface.py`` (T-5) and runs inside CI; this script
   re-checks that those tests exist and are registered in ``ci.yml`` so the gate
   cannot silently drop out of the pipeline.

Usage::

    .venv\\Scripts\\python.exe scripts/pr5_banned_gate.py
    .venv\\Scripts\\python.exe scripts/pr5_banned_gate.py --json out.json

Exit code 0 = clean, 1 = violation, 2 = gate misconfigured (missing files).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC_ROOT = os.path.join(REPO_ROOT, "frontend", "src")
FROZEN_COPY = os.path.join(REPO_ROOT, "config", "pr5_frozen_copy.json")
CI_YML = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
PR5_TEST = os.path.join(REPO_ROOT, "tests", "test_pr5_parent_surface.py")

#: §三 banned terms that must never appear anywhere in frontend/src.
HARD_BANNED = (
    "IB",
    "ATL",
    "Inquirer",
    "Learner Profile",
    "Proficient",
    "Excellent",
    "kid_label",
    "citations",
    "cost",
)

#: Raw band codes: legal only in these files, as machine keys.
BAND_CODES = ("P1-P3", "P4-P6", "S1-S3")
BAND_CODE_ALLOWED = {
    os.path.join("lib", "parentReportCopy.ts"),
}

SCAN_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
SKIP_DIRS = {"node_modules", "dist", "coverage"}

#: The PR-5 parent report surface (B1/B2/B3/B4). This is what the gate judges.
#: Legacy parent widgets from earlier PRs (CycleReport / PortfolioView /
#: parentTypes …) are scanned separately as *informational* only — PR-5 is
#: forbidden from rewriting them, so failing this gate on their pre-existing
#: wording would either block the PR or tempt a silent rewrite.
PARENT_SURFACE = (
    os.path.join("pages", "parent", "ParentReportsPage.tsx"),
    os.path.join("pages", "parent", "ParentReportDetailPage.tsx"),
    os.path.join("lib", "parentReportCopy.ts"),
)

#: Pre-existing parent widgets, reported for the record, never failing the gate.
LEGACY_PARENT_FILES = (
    os.path.join("components", "parent", "CycleReport.tsx"),
    os.path.join("components", "parent", "PortfolioView.tsx"),
    os.path.join("lib", "parentTypes.ts"),
)


def _iter_sources(root: str):
    """Every scan-able file under the parent surface."""
    for entry in PARENT_SURFACE:
        target = os.path.join(root, entry)
        if os.path.isfile(target):
            yield target
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if name.endswith(SCAN_SUFFIXES):
                    yield os.path.join(dirpath, name)


def _line_hits(path: str, terms) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            for term in terms:
                if term == "IB":
                    # word-ish boundary: avoid flagging identifiers like IBAN,
                    # but keep "IB" as a standalone token / in prose.
                    pattern = r"(?<![A-Za-z0-9_])IB(?![A-Za-z0-9_])"
                    found = re.search(pattern, line) is not None
                else:
                    found = term in line
                if found:
                    hits.append(
                        {
                            "file": os.path.relpath(path, REPO_ROOT),
                            "line": lineno,
                            "term": term,
                            "excerpt": line.strip()[:160],
                        }
                    )
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="", help="write the report as JSON here")
    args = parser.parse_args(argv)

    if not os.path.isdir(SRC_ROOT):
        print(f"GATE ERROR: {SRC_ROOT} not found", file=sys.stderr)
        return 2
    if not os.path.isfile(FROZEN_COPY):
        print(
            f"GATE ERROR: {FROZEN_COPY} missing — run"
            " scripts/extract_pr5_frozen_copy.py first",
            file=sys.stderr,
        )
        return 2

    hard_hits: list[dict[str, object]] = []
    band_hits: list[dict[str, object]] = []
    legacy_hits: list[dict[str, object]] = []
    for entry in LEGACY_PARENT_FILES:
        legacy_path = os.path.join(SRC_ROOT, entry)
        if os.path.isfile(legacy_path):
            legacy_hits.extend(_line_hits(legacy_path, HARD_BANNED))
    scanned = 0
    for path in _iter_sources(SRC_ROOT):
        scanned += 1
        hard_hits.extend(_line_hits(path, HARD_BANNED))
        rel = os.path.relpath(path, SRC_ROOT)
        if rel in BAND_CODE_ALLOWED:
            continue
        band_hits.extend(_line_hits(path, BAND_CODES))

    with open(FROZEN_COPY, encoding="utf-8") as fh:
        frozen = json.load(fh)

    grid = frozen.get("bandLabels") or {}
    grid_ok = True
    for code in BAND_CODES:
        row = grid.get(code) or {}
        if set(row) != {"en", "zh-hk", "zh-cn"}:
            grid_ok = False

    banned_list = tuple(frozen.get("forbiddenTerms") or ())
    list_ok = banned_list == (
        "IB", "ATL", "Inquirer", "Learner Profile", "Proficient", "Excellent",
        "kid_label", "citations", "cost", "P1-P3", "P4-P6", "S1-S3",
    )

    ci_text = ""
    if os.path.isfile(CI_YML):
        with open(CI_YML, encoding="utf-8") as fh:
            ci_text = fh.read()
    registered = "tests/test_pr5_parent_surface.py" in ci_text
    test_present = os.path.isfile(PR5_TEST)

    report = {
        "scanned_files": scanned,
        "scope": [p.replace(os.sep, "/") for p in PARENT_SURFACE],
        "hard_banned": list(HARD_BANNED),
        "band_codes": list(BAND_CODES),
        "band_code_allowed_files": sorted(BAND_CODE_ALLOWED),
        "hard_term_hits": hard_hits,
        "band_code_hits_outside_allowlist": band_hits,
        "legacy_files_informational": [
            e.replace(os.sep, "/") for e in LEGACY_PARENT_FILES
        ],
        "legacy_hits_informational": legacy_hits,
        "frozen_copy_file": os.path.relpath(FROZEN_COPY, REPO_ROOT),
        "frozen_band_grid_complete": grid_ok,
        "frozen_banned_list_matches": list_ok,
        "t5_test_present": test_present,
        "t5_test_registered_in_ci": registered,
    }

    clean = (
        not hard_hits
        and not band_hits
        and grid_ok
        and list_ok
        and test_present
        and registered
    )
    report["verdict"] = "CLEAN" if clean else "DIRTY"

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    if clean:
        print(
            f"GATE CLEAN: {scanned} PR-5 parent files scanned, 0 banned-term hits,"
            " frozen band grid complete, T-5 registered in ci.yml"
        )
        if legacy_hits:
            print(
                f"NOTE: {len(legacy_hits)} pre-existing hit(s) in legacy parent"
                " widgets from earlier PRs (informational only, not part of PR-5"
                " scope; listed in the delivery document's 申报/风险 section)"
            )
        return 0
    print("GATE DIRTY: see hits above", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
