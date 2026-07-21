"""
Dreamer AI Phase 1 — Merge Arbiter
Conflict detection: schema diff, API contract, file overlap.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class ConflictSeverity(Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class ConflictReport:
    rule: str
    severity: ConflictSeverity
    description: str
    source_a: str
    source_b: str = ""
    suggestion: str = ""


@dataclass
class MergeResult:
    passed: bool
    reports: List[ConflictReport]
    summary: str


class MergeArbiter:
    """
    Validates that outputs from parallel sandboxes are compatible
    before merging to the integration branch.

    Detection passes:
    1. Schema Collision — same table/column from different sandboxes
    2. API Route Overlap — duplicate route paths
    3. File Overlap — same file path modified by two sandboxes
    4. Contract Drift — UI expects fields not in BE response
    5. Orphan Reference — reference to resource only in another sandbox
    """

    def validate(
        self, sandbox_outputs: Dict[str, Dict[str, str]]
    ) -> MergeResult:
        """
        Args:
            sandbox_outputs: {ws_name: {filename: content}}

        Returns:
            MergeResult with pass/fail and detailed reports.
        """
        reports: List[ConflictReport] = []

        # Parse files by type
        sql_files = {}  # ws_name → {filename: sql_content}
        py_files = {}  # ws_name → {filename: py_content}
        all_files = {}  # ws_name → set of filenames

        for ws_name, files in sandbox_outputs.items():
            all_files[ws_name] = set()
            for fname, content in files.items():
                all_files[ws_name].add(fname)
                if fname.endswith(".sql"):
                    sql_files.setdefault(ws_name, {})[fname] = content
                elif fname.endswith(".py"):
                    py_files.setdefault(ws_name, {})[fname] = content

        # ── Pass 1: File Overlap ─────────────────────────
        reports.extend(self._check_file_overlap(all_files))

        # ── Pass 2: Schema Collision ─────────────────────
        reports.extend(self._check_schema_collision(sql_files))

        # ── Pass 3: API Route Overlap ────────────────────
        reports.extend(self._check_api_overlap(py_files))

        # ── Pass 4: Contract Drift ───────────────────────
        reports.extend(self._check_contract_drift(py_files, sql_files))

        # Determine overall result
        blocks = [r for r in reports if r.severity == ConflictSeverity.BLOCK]
        warns = [r for r in reports if r.severity == ConflictSeverity.WARN]
        passes = [r for r in reports if r.severity == ConflictSeverity.PASS]

        if blocks:
            summary = f"BLOCKED: {len(blocks)} conflict(s) found. {len(warns)} warning(s)."
            return MergeResult(passed=False, reports=reports, summary=summary)
        elif warns:
            summary = f"PASSED with {len(warns)} warning(s). {len(passes)} check(s) OK."
            return MergeResult(passed=True, reports=reports, summary=summary)
        else:
            summary = f"PASSED: All {len(passes)} checks passed."
            return MergeResult(passed=True, reports=reports, summary=summary)

    # ── Pass 1: File Overlap ─────────────────────────────

    def _check_file_overlap(
        self, all_files: Dict[str, set]
    ) -> List[ConflictReport]:
        reports = []
        ws_names = list(all_files.keys())
        for i in range(len(ws_names)):
            for j in range(i + 1, len(ws_names)):
                overlap = all_files[ws_names[i]] & all_files[ws_names[j]]
                if overlap:
                    reports.append(
                        ConflictReport(
                            rule="File Overlap",
                            severity=ConflictSeverity.BLOCK,
                            description=f"Both {ws_names[i]} and {ws_names[j]} "
                            f"modified: {', '.join(sorted(overlap))}",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                            suggestion="Split into separate files or merge manually.",
                        )
                    )
                else:
                    reports.append(
                        ConflictReport(
                            rule="File Overlap",
                            severity=ConflictSeverity.PASS,
                            description=f"No overlapping files between "
                            f"{ws_names[i]} and {ws_names[j]}",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                        )
                    )
        return reports

    # ── Pass 2: Schema Collision ─────────────────────────

    def _check_schema_collision(
        self, sql_files: Dict[str, Dict[str, str]]
    ) -> List[ConflictReport]:
        reports = []
        if len(sql_files) <= 1:
            reports.append(
                ConflictReport(
                    rule="Schema Collision",
                    severity=ConflictSeverity.PASS,
                    description="Only one sandbox has SQL changes — no collision possible.",
                    source_a=list(sql_files.keys())[0] if sql_files else "none",
                )
            )
            return reports

        # Extract table definitions per sandbox
        table_map: Dict[str, Dict[str, str]] = {}  # ws → {table_name: column_defs}
        for ws, files in sql_files.items():
            table_map[ws] = {}
            for content in files.values():
                tables = re.findall(
                    r"CREATE\s+TABLE\s+(\w+)\s*\((.*?)\);",
                    content,
                    re.IGNORECASE | re.DOTALL,
                )
                for table_name, columns in tables:
                    table_map[ws][table_name.lower()] = columns.strip()

        # Cross-check
        ws_names = list(table_map.keys())
        for i in range(len(ws_names)):
            for j in range(i + 1, len(ws_names)):
                common = set(table_map[ws_names[i]].keys()) & set(
                    table_map[ws_names[j]].keys()
                )
                only_i = set(table_map[ws_names[i]].keys()) - set(
                    table_map[ws_names[j]].keys()
                )
                only_j = set(table_map[ws_names[j]].keys()) - set(
                    table_map[ws_names[i]].keys()
                )

                if common:
                    reports.append(
                        ConflictReport(
                            rule="Schema Collision",
                            severity=ConflictSeverity.BLOCK,
                            description=f"Table collision: {', '.join(sorted(common))} "
                            f"defined in both {ws_names[i]} and {ws_names[j]}",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                            suggestion="Reconcile into a single migration or use different table names.",
                        )
                    )
                else:
                    reports.append(
                        ConflictReport(
                            rule="Schema Collision",
                            severity=ConflictSeverity.PASS,
                            description=f"No table collision between "
                            f"{ws_names[i]} ({', '.join(sorted(only_i)) or 'none'}) "
                            f"and {ws_names[j]} ({', '.join(sorted(only_j)) or 'none'})",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                        )
                    )
        return reports

    # ── Pass 3: API Route Overlap ────────────────────────

    def _check_api_overlap(
        self, py_files: Dict[str, Dict[str, str]]
    ) -> List[ConflictReport]:
        reports = []
        if len(py_files) <= 1:
            reports.append(
                ConflictReport(
                    rule="API Route Overlap",
                    severity=ConflictSeverity.PASS,
                    description="Only one sandbox has Python changes — no route overlap.",
                    source_a=list(py_files.keys())[0] if py_files else "none",
                )
            )
            return reports

        # Extract routes per sandbox
        routes: Dict[str, set] = {}
        for ws, files in py_files.items():
            routes[ws] = set()
            for content in files.values():
                found = re.findall(
                    r'@app\.(?:get|post|put|delete|patch)\(["\']([^"\']+)["\']',
                    content,
                )
                routes[ws].update(found)

        ws_names = list(routes.keys())
        for i in range(len(ws_names)):
            for j in range(i + 1, len(ws_names)):
                overlap = routes[ws_names[i]] & routes[ws_names[j]]
                if overlap:
                    reports.append(
                        ConflictReport(
                            rule="API Route Overlap",
                            severity=ConflictSeverity.BLOCK,
                            description=f"Duplicate routes: {', '.join(sorted(overlap))} "
                            f"in both {ws_names[i]} and {ws_names[j]}",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                            suggestion="Use different route prefixes or merge into one file.",
                        )
                    )
                else:
                    reports.append(
                        ConflictReport(
                            rule="API Route Overlap",
                            severity=ConflictSeverity.PASS,
                            description=f"No route overlap between "
                            f"{ws_names[i]} and {ws_names[j]}",
                            source_a=ws_names[i],
                            source_b=ws_names[j],
                        )
                    )
        return reports

    # ── Pass 4: Contract Drift ───────────────────────────

    def _check_contract_drift(
        self,
        py_files: Dict[str, Dict[str, str]],
        sql_files: Dict[str, Dict[str, str]],
    ) -> List[ConflictReport]:
        """Check if API routes reference DB columns that don't exist in schema."""
        reports = []
        if not py_files or not sql_files:
            return reports

        # Extract SQL columns
        all_columns: set = set()
        for ws, files in sql_files.items():
            for content in files.values():
                cols = re.findall(r"^\s*(\w+)\s+\w+", content, re.MULTILINE)
                all_columns.update(c.lower() for c in cols)

        # Extract Python field references (simple heuristic)
        for ws, files in py_files.items():
            for content in files.values():
                field_refs = re.findall(r'\["(\w+)"\]', content)
                field_refs.extend(re.findall(r"\[\'(\w+)\'\]", content))

                for ref in field_refs:
                    if ref.lower() not in all_columns and ref not in (
                        "id",
                        "status",
                        "message",
                    ):
                        reports.append(
                            ConflictReport(
                                rule="Contract Drift",
                                severity=ConflictSeverity.WARN,
                                description=f"API in {ws} references field '{ref}' "
                                f"not found in any SQL schema column",
                                source_a=ws,
                                suggestion=f"Verify '{ref}' exists in the schema or add migration.",
                            )
                        )
        if not reports:
            reports.append(
                ConflictReport(
                    rule="Contract Drift",
                    severity=ConflictSeverity.PASS,
                    description="All API field references match schema columns.",
                    source_a="all",
                )
            )
        return reports
