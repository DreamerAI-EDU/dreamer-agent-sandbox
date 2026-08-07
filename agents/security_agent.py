"""
Dreamer AI Phase 3 — Security Agent
Post-generation / Pre-merge code security auditor.

Audit flow:
  1. Parse agent output file with all registered rules
  2. Classify findings by severity
  3. Critical → block; High → warn; Medium → log
  4. Retry cap: same finding can trigger at most 2 re-generations
  5. Override: user can override with mandatory reason, logged to audit_log.jsonl
"""

import json
import os
import time
from typing import List, Dict, Optional

from .security_rules import (
    Finding,
    RuleRegistry,
)

MAX_RETRIES = 2


class SecurityReport:
    """Result of a single security audit."""

    def __init__(self, agent: str, task_id: str, filename: str):
        self.agent = agent
        self.task_id = task_id
        self.filename = filename
        self.findings: List[Finding] = []
        self.verdict: str = "pass"  # pass, warn, blocked
        self.retry_count: Dict[str, int] = {}  # finding rule_id → count

    @property
    def blocked(self) -> bool:
        return self.verdict == "blocked"

    @property
    def has_warnings(self) -> bool:
        return self.verdict in ("warn", "blocked")


class SecurityAgent:
    """Security gate: runs rules, enforces retry cap, logs overrides."""

    def __init__(self, audit_log_path: str = "audit_log.jsonl"):
        self.audit_log_path = audit_log_path
        self._retry_history: Dict[str, Dict[str, int]] = {}  # task_id → rule_id → count

    # ── Core audit ──────────────────────────────────────

    def audit(self, file_path: str, agent: str, task_id: str) -> SecurityReport:
        """Run all security rules against a source file."""
        report = SecurityReport(agent, task_id, os.path.basename(file_path))

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception:
            return report

        for rule_func in RuleRegistry.all():
            findings = rule_func(code, report.filename)
            report.findings.extend(findings)

        # Classify verdict
        severities = {f.severity for f in report.findings}
        if "critical" in severities:
            report.verdict = "blocked"
        elif "high" in severities:
            report.verdict = "warn"

        return report

    # ── Retry cap ───────────────────────────────────────

    def can_retry(self, task_id: str, finding: Finding) -> bool:
        """Check if a finding is still within the retry budget."""
        history = self._retry_history.get(task_id, {})
        count = history.get(finding.rule_id, 0)
        return count < MAX_RETRIES

    def record_retry(self, task_id: str, finding: Finding):
        """Increment retry counter for a finding."""
        if task_id not in self._retry_history:
            self._retry_history[task_id] = {}
        self._retry_history[task_id][finding.rule_id] = (
            self._retry_history[task_id].get(finding.rule_id, 0) + 1
        )

    def escalated_findings(self, report: SecurityReport, task_id: str) -> List[Finding]:
        """Return findings that have exhausted retries and need human review."""
        history = self._retry_history.get(task_id, {})
        return [
            f for f in report.findings
            if history.get(f.rule_id, 0) >= MAX_RETRIES
        ]

    # ── Override ────────────────────────────────────────

    def override(self, report: SecurityReport, reason: str) -> dict:
        """Override a blocked verdict. Logs reason to audit_log.jsonl."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent": report.agent,
            "task_id": report.task_id,
            "file": report.filename,
            "verdict_original": report.verdict,
            "verdict_after": "overridden",
            "reason": reason,
            "findings": [
                {"rule_id": f.rule_id, "severity": f.severity, "line": f.line}
                for f in report.findings
            ],
        }

        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        report.verdict = "overridden"
        return entry

    # ── Recommendation prompt for LLM ───────────────────

    def fix_hint(self, report: SecurityReport, task_id: str) -> Optional[str]:
        """
        Generate a fix prompt for the LLM, only for retry-eligible findings.
        Returns None if no fixable findings remain (all escalated).
        """
        fixable = [f for f in report.findings if self.can_retry(task_id, f)]
        if not fixable:
            return None

        lines = ["Fix the following security issues in the generated code:"]
        for i, f in enumerate(fixable, 1):
            lines.append(f"\n{i}. [{f.rule_id}] {f.severity.upper()} — line {f.line}")
            lines.append(f"   {f.description}")
            lines.append(f"   → {f.recommendation}")
            self.record_retry(task_id, f)

        return "\n".join(lines)
