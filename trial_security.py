"""
Dreamer AI Phase 3 — Security Agent Trial
Two scenarios:
  A) Generate code with deliberate vulnerabilities → Security Agent must block
  B) Generate clean code → Security Agent must pass (no false positives)
"""

import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.security_agent import SecurityAgent, MAX_RETRIES

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_trials")


# ═══════════════════════════════════════════════════════════
# Scenario A — Deliberate vulnerabilities, verify blocking
# ═══════════════════════════════════════════════════════════

VULNERABLE_CODE = textwrap.dedent("""\
import sqlite3
import os
import pickle

def get_user(user_id):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    # SEC-001 / SEC-006: SQL injection via f-string
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return cursor.fetchone()

def run_backup(filename):
    # SEC-003: os.system with variable input
    os.system(f"tar -czf backup.tar.gz {filename}")

def load_session(data):
    # SEC-005: pickle.loads with variable input
    return pickle.loads(data)

API_KEY = "sk-or-v1-abc123def456"  # SEC-002: hardcoded key
""")


def trial_a_blocking() -> bool:
    """Security Agent must detect and block vulnerable code."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "vulnerable_demo.py")
    with open(filepath, "w") as f:
        f.write(VULNERABLE_CODE)

    agent = SecurityAgent()
    report = agent.audit(filepath, "be", "trial-a-vuln")

    # Must have critical findings
    criticals = [f for f in report.findings if f.severity == "critical"]
    all_findings = len(report.findings)

    print(f"  [Scenario A] {all_findings} findings, {len(criticals)} critical, verdict={report.verdict}")

    ok = report.blocked and len(criticals) >= 3  # Expect: SEC-001, SEC-002, SEC-003 at minimum
    print(f"  [Scenario A] {'PASS' if ok else 'FAIL'} — blocked={report.blocked}, criticals={len(criticals)}")

    # Also verify retry cap works
    for f in criticals:
        if not agent.can_retry("trial-a-vuln", f):
            print(f"  [Scenario A] FAIL — fresh report should allow retries")
            return False

    # Simulate 2 retries → should exhaust
    for _ in range(MAX_RETRIES):
        agent.record_retry("trial-a-vuln", criticals[0])

    if agent.can_retry("trial-a-vuln", criticals[0]):
        print(f"  [Scenario A] FAIL — retry cap not enforced after {MAX_RETRIES} retries")
        return False

    print(f"  [Scenario A] Retry cap: {MAX_RETRIES} retries exhausted → escalated correctly")
    return ok


# ═══════════════════════════════════════════════════════════
# Scenario B — Clean code, verify no false positives
# ═══════════════════════════════════════════════════════════

CLEAN_CODE = textwrap.dedent("""\
import sqlite3
import os
import json
import shutil

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

def get_user(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()

def create_backup(output_name: str):
    out = os.path.abspath(output_name)
    base = os.path.dirname(DB_PATH)
    if not out.startswith(base):
        raise ValueError("Backup must stay within data directory")
    shutil.copy(DB_PATH, out)

def load_config(path: str):
    with open(path, "r") as f:
        return json.load(f)

def get_api_key() -> str:
    return os.environ.get("API_KEY", "")
""")


def trial_b_no_false_positive() -> bool:
    """Security Agent must NOT flag clean code."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "clean_demo.py")
    with open(filepath, "w") as f:
        f.write(CLEAN_CODE)

    agent = SecurityAgent()
    report = agent.audit(filepath, "be", "trial-b-clean")

    criticals = [f for f in report.findings if f.severity == "critical"]
    highs = [f for f in report.findings if f.severity == "high"]
    all_findings = len(report.findings)

    print(f"  [Scenario B] {all_findings} findings, {len(criticals)} critical, {len(highs)} high, verdict={report.verdict}")

    # Clean code has os.system with literal + a variable, but it's a constant DB_PATH.
    # SEC-003 may flag os.system with f-string, but DB_PATH is a constant, not user input.
    # If it flags, that's a false positive we need to tune.
    # For now, expect 0 critical findings. Some high findings on os.system are acceptable.
    ok = len(criticals) == 0

    if not ok:
        for f in criticals:
            print(f"  [Scenario B] FALSE POSITIVE: {f.rule_id} line {f.line}: {f.description}")

    print(f"  [Scenario B] {'PASS' if ok else 'FAIL'} — {len(criticals)} false positive(s)")

    # Also test override mechanism
    if report.blocked:
        agent.override(report, "False positive — DB_PATH is a constant, not user input")
        override_path = agent.audit_log_path
        if os.path.exists(override_path):
            with open(override_path) as f:
                lines = [l for l in f if l.strip()]
            if lines:
                print(f"  [Scenario B] Override logged: {lines[-1][:80]}...")
        ok = ok and report.verdict == "overridden"

    return ok


# ═══════════════════════════════════════════════════════════
# Scenario C — Pipeline integration: PG → Security Gate → Merge
# ═══════════════════════════════════════════════════════════

def trial_c_pipeline_integration() -> bool:
    """Verify SecurityGate inserts correctly between PG execution and Merge Arbiter."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agents.hermes_scheduler import (
        HermesScheduler, SecurityGate, TaskNode, ResourceLock,
    )

    # 1. Build DAG: be+db agents produce code → Security Gate → Merge Arbiter
    sched = HermesScheduler()
    tasks = sched.build_dag_example()

    # 2. Write the artifacts that PG-2 tasks would produce
    be_task = sched.get_task("t2-backend-api")
    db_task = sched.get_task("t3-database-schema")
    be_task.artifacts = ["lesson_api.py"]
    db_task.artifacts = ["lesson_schema.sql"]

    # Write a vulnerable backend artifact
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    be_path = os.path.join(OUTPUT_DIR, "lesson_api.py")
    with open(be_path, "w") as f:
        f.write(textwrap.dedent("""\
            import sqlite3
            API_KEY = "sk-live-abc123"
            def get_lesson(lesson_id):
                conn = sqlite3.connect("db")
                conn.execute(f"SELECT * FROM lessons WHERE id = {lesson_id}")
        """))

    # Write a clean DB artifact
    db_path = os.path.join(OUTPUT_DIR, "lesson_schema.sql")
    with open(db_path, "w") as f:
        f.write("CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, title TEXT);\n")

    # 3. Run security gate
    gate = SecurityGate(output_dir=OUTPUT_DIR)

    # Backend artifact should be blocked
    be_result = gate.audit_artifacts(be_task)
    print(f"  [Scenario C - BE] verdict={be_result['verdict']}, findings={len(be_result['findings'])}")
    if be_result["verdict"] not in ("blocked", "escalated"):
        print(f"  [Scenario C] FAIL — vulnerable BE artifact not blocked: verdict={be_result['verdict']}")
        return False

    # DB artifact should pass
    db_result = gate.audit_artifacts(db_task)
    print(f"  [Scenario C - DB] verdict={db_result['verdict']}, findings={len(db_result['findings'])}")
    if db_result["verdict"] != "pass":
        print(f"  [Scenario C] FAIL — clean DB artifact flagged: {db_result['findings']}")
        return False

    # 4. Fix hint for retry
    hint = gate.fix_hint(be_task)
    if not hint:
        print("  [Scenario C] FAIL — no fix hint generated for blocked task")
        return False
    print(f"  [Scenario C] Fix hint generated ({len(hint)} chars)")

    # 5. Simulate retry exhaustion
    for _ in range(gate.MAX_RETRIES):
        gate.audit_artifacts(be_task)  # re-audit records retries
    # After cap, should escalate
    final = gate.audit_artifacts(be_task)
    print(f"  [Scenario C - After cap] verdict={final['verdict']}, retries_exhausted={final['retries_exhausted']}")
    if final["verdict"] != "escalated":
        print(f"  [Scenario C] FAIL — should escalate after retry cap, got {final['verdict']}")
        return False

    print("  [Scenario C] PASS — gate blocks, fix hint generated, retry cap works")
    return True


# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Dreamer AI — Security Agent Trial")
    print("=" * 60)

    a = trial_a_blocking()
    b = trial_b_no_false_positive()
    c = trial_c_pipeline_integration()

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  {'PASS' if a else 'FAIL'}  Scenario A — Block vulnerable code")
    print(f"  {'PASS' if b else 'FAIL'}  Scenario B — Don't kill clean code")
    print(f"  {'PASS' if c else 'FAIL'}  Scenario C — Pipeline integration")
    print(f"\n  Passed: {(1 if a else 0) + (1 if b else 0) + (1 if c else 0)}/3")

    if not (a and b and c):
        sys.exit(1)


if __name__ == "__main__":
    main()
