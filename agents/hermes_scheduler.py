"""
Dreamer AI Phase 1 — Hermes Scheduler
DAG builder, parallel scheduler, lock conflict resolver.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict
from .registry import SubagentRegistry


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    QUEUED = "queued"  # Waiting for resource lock


@dataclass
class ResourceLock:
    domain: str
    resource_key: str
    mode: str  # "rw" | "ro"


@dataclass
class TaskNode:
    task_id: str
    agent: str  # "curriculum", "assessment", "ui", "be", "db"
    action: str
    params: Dict = field(default_factory=dict)
    parallel_group: str = ""
    depends_on: List[str] = field(default_factory=list)
    locks: List[ResourceLock] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    artifacts: List[str] = field(default_factory=list)


@dataclass
class ExecutionBatch:
    group_id: str
    tasks: List[TaskNode]
    can_parallel: bool = True


@dataclass
class ExecutionPlan:
    batches: List[ExecutionBatch]
    total_tasks: int


class HermesScheduler:
    """
    Builds a Task DAG from a high-level goal, resolves lock conflicts,
    and produces an ordered ExecutionPlan with parallel groups.
    """

    def __init__(self, registry: Optional[SubagentRegistry] = None):
        self._tasks: Dict[str, TaskNode] = {}
        self._completed: Set[str] = set()
        self._failed: Set[str] = set()
        self.registry = registry  # Phase 2.1: injected singleton

    def add_task(self, task: TaskNode) -> None:
        self._tasks[task.task_id] = task

    def add_tasks(self, tasks: List[TaskNode]) -> None:
        for t in tasks:
            self.add_task(t)

    def build_dag_example(self) -> List[TaskNode]:
        """
        Build the trial run DAG: "Build lesson management feature"

        PG-1: Curriculum Agent → design lesson spec (solo)
        PG-2: Backend Agent + Database Agent (parallel, no lock conflict)
              - Backend: resource.be.lock (route:/api/lessons)
              - Database: resource.db.lock (schema:lessons)
        PG-3: Merge Arbiter
        """
        trace_id = "trace-trial-001"

        t1 = TaskNode(
            task_id="t1-curriculum-spec",
            agent="curriculum",
            action="design_lesson_spec",
            params={
                "topic": "Basic Arithmetic",
                "grade_level": 3,
                "output_file": "lesson_spec.json",
            },
            parallel_group="pg-1",
            depends_on=[],
            locks=[],
        )

        t2 = TaskNode(
            task_id="t2-backend-api",
            agent="be",
            action="generate_api_routes",
            params={
                "spec_from": "t1-curriculum-spec",
                "output_file": "lesson_api.py",
            },
            parallel_group="pg-2",
            depends_on=["t1-curriculum-spec"],
            locks=[ResourceLock(domain="be", resource_key="route:/api/lessons", mode="rw")],
        )

        t3 = TaskNode(
            task_id="t3-database-schema",
            agent="db",
            action="generate_schema",
            params={
                "spec_from": "t1-curriculum-spec",
                "output_file": "lesson_schema.sql",
            },
            parallel_group="pg-2",
            depends_on=["t1-curriculum-spec"],
            locks=[
                ResourceLock(domain="db", resource_key="schema:lessons", mode="rw")
            ],
        )

        t4 = TaskNode(
            task_id="t4-merge-arbiter",
            agent="merge_arbiter",
            action="validate_merge",
            params={
                "sources": ["t2-backend-api", "t3-database-schema"],
            },
            parallel_group="pg-3",
            depends_on=["t2-backend-api", "t3-database-schema"],
            locks=[],
        )

        tasks = [t1, t2, t3, t4]
        self.add_tasks(tasks)
        return tasks

    def resolve_lock_conflicts(
        self, tasks: List[TaskNode], held_locks: Dict[str, Dict]
    ) -> Tuple[List[TaskNode], List[TaskNode]]:
        """
        Given a batch of candidate tasks and current lock state,
        split into (safe_to_run, must_queue).

        Lock conflict: two tasks want same (domain, resource_key) with rw mode.
        Resolution: first by priority (task order), second gets queued.
        """
        safe = []
        queued = []
        # Track what this batch wants to lock
        batch_locks: Dict[str, str] = {}  # lock_key → task_id (first claimant)

        for task in tasks:
            blocked = False
            for lock in task.locks:
                lock_key = f"{lock.domain}.{lock.resource_key}"

                # Check against external held locks
                if lock_key in held_locks:
                    held = held_locks[lock_key]
                    if held.get("mode") == "rw" or lock.mode == "rw":
                        blocked = True
                        break

                # Check against batch-internal locks
                if lock_key in batch_locks and batch_locks[lock_key] != task.task_id:
                    blocked = True
                    break

            if blocked:
                queued.append(task)
            else:
                safe.append(task)
                for lock in task.locks:
                    lock_key = f"{lock.domain}.{lock.resource_key}"
                    batch_locks[lock_key] = task.task_id

        return safe, queued

    def plan(self, held_locks: Optional[Dict[str, Dict]] = None) -> ExecutionPlan:
        """
        Kahn's algorithm variant: produce ordered batches.
        Each batch = tasks that can run in parallel (same parallel_group, no lock conflict).
        """
        if held_locks is None:
            held_locks = {}

        in_degree = {t.task_id: len(t.depends_on) for t in self._tasks.values()}
        ready = [
            t for t in self._tasks.values() if in_degree[t.task_id] == 0
        ]

        batches: List[ExecutionBatch] = []
        completed: Set[str] = set()
        iteration = 0

        while ready:
            # Group by parallel_group
            groups: Dict[str, List[TaskNode]] = defaultdict(list)
            for task in ready:
                groups[task.parallel_group].append(task)

            for pg_id, group_tasks in groups.items():
                safe, queued = self.resolve_lock_conflicts(group_tasks, held_locks)

                if safe:
                    batches.append(
                        ExecutionBatch(
                            group_id=f"{pg_id}-batch-{iteration}",
                            tasks=safe,
                            can_parallel=len(safe) > 1,
                        )
                    )
                    completed.update(t.task_id for t in safe)
                    # Simulate lock acquisition for scheduling
                    for t in safe:
                        for lock in t.locks:
                            lock_key = f"{lock.domain}.{lock.resource_key}"
                            held_locks[lock_key] = {
                                "agent": t.agent,
                                "mode": lock.mode,
                                "task_id": t.task_id,
                                "expires_at": float("inf"),
                            }

                # Re-queue blocked tasks (add dependency on winner)
                for qt in queued:
                    # Find which safe task holds the conflicting lock
                    for lock in qt.locks:
                        lock_key = f"{lock.domain}.{lock.resource_key}"
                        if lock_key in held_locks:
                            winner_task_id = held_locks[lock_key]["task_id"]
                            if winner_task_id not in qt.depends_on:
                                qt.depends_on.append(winner_task_id)

            iteration += 1

            # Find next ready tasks
            ready = [
                t
                for t in self._tasks.values()
                if t.task_id not in completed
                and all(d in completed for d in t.depends_on)
            ]

        return ExecutionPlan(batches=batches, total_tasks=len(self._tasks))

    def mark_completed(self, task_id: str) -> None:
        self._completed.add(task_id)
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.COMPLETED

    def mark_failed(self, task_id: str) -> None:
        self._failed.add(task_id)
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.FAILED

    # ── Phase 2.1: Registry-based routing ──────────────

    def route(self, agent_name: str, task_id: str, params: Dict) -> Dict:
        """Delegate execution to a registered sub-agent via the registry.

        Returns the agent's execute() result dict.
        Raises RuntimeError if registry is not injected.
        """
        if self.registry is None:
            raise RuntimeError(
                "HermesScheduler.route() called without SubagentRegistry injected"
            )
        agent = self.registry.get(agent_name)
        return agent.execute(task_id, params)

    def select_candidates(self, mode: str) -> List[dict]:
        """Return candidate agents for a given student-query mode.

        Delegates to registry.list_by_mode(). Returns only student-facing agents.
        Raises RuntimeError if registry is not injected.
        """
        if self.registry is None:
            raise RuntimeError(
                "HermesScheduler.select_candidates() called without SubagentRegistry injected"
            )
        return self.registry.list_by_mode(mode)

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        return self._tasks.get(task_id)

    def get_active_locks(self, tasks: List[TaskNode]) -> Dict[str, Dict]:
        """Build a lock table from a list of running tasks."""
        locks = {}
        for t in tasks:
            for lock in t.locks:
                lock_key = f"{lock.domain}.{lock.resource_key}"
                locks[lock_key] = {
                    "agent": t.agent,
                    "mode": lock.mode,
                    "task_id": t.task_id,
                }
        return locks


# ── Phase 3: Security Gate ──────────────────────────────

class SecurityGate:
    """
    Post-generation / Pre-merge security gate.

    Sits between code-generating agents (be, db) and Merge Arbiter.
    Audits each task's artifacts against SecurityAgent rules.

    Flow:
      1. Task completes → artifacts produced
      2. SecurityGate.audit_artifacts(task) runs
      3. If pass → proceed to next batch (Merge Arbiter)
      4. If blocked → attempt retry (up to cap) or escalate
    """

    def __init__(self, output_dir: str = "."):
        from .security_agent import SecurityAgent, MAX_RETRIES
        self.auditor = SecurityAgent()
        self.output_dir = output_dir
        self.MAX_RETRIES = MAX_RETRIES

    def audit_artifacts(
        self, task: TaskNode
    ) -> dict:
        """
        Audit all artifacts produced by a task.
        Returns: {
            "verdict": "pass" | "blocked" | "escalated",
            "findings": [...],
            "escalated_findings": [...],
            "retries_exhausted": bool
        }
        """
        import os

        all_findings = []
        blocked = False
        all_escalated = True

        for artifact in task.artifacts:
            path = os.path.join(self.output_dir, artifact)
            if not os.path.isfile(path):
                continue
            report = self.auditor.audit(path, task.agent, task.task_id)

            if report.blocked:
                blocked = True
                # Check which findings are still retry-eligible
                escalated = self.auditor.escalated_findings(report, task.task_id)
                fixable = [f for f in report.findings
                           if f not in escalated and self.auditor.can_retry(task.task_id, f)]

                if fixable:
                    all_escalated = False
                    # Record attempts and return fix hint
                    for f in fixable:
                        self.auditor.record_retry(task.task_id, f)

                all_findings.extend(
                    {"artifact": artifact, "rule_id": f.rule_id, "severity": f.severity,
                     "line": f.line, "description": f.description, "recommendation": f.recommendation}
                    for f in report.findings
                )

        if not all_findings:
            return {"verdict": "pass", "findings": [], "escalated_findings": [], "retries_exhausted": False}

        if not blocked:
            return {"verdict": "pass", "findings": all_findings, "escalated_findings": [], "retries_exhausted": False}

        if all_escalated:
            return {"verdict": "escalated", "findings": all_findings,
                    "escalated_findings": list(set(f["rule_id"] for f in all_findings)),
                    "retries_exhausted": True}

        return {"verdict": "blocked", "findings": all_findings,
                "escalated_findings": [], "retries_exhausted": False}

    def fix_hint(self, task: TaskNode) -> str:
        """
        Generate a fix prompt for the LLM to retry code generation.
        Only includes retry-eligible (non-exhausted) findings.
        """
        import os
        from .security_agent import SecurityReport, Finding

        hints = []
        for artifact in task.artifacts:
            path = os.path.join(self.output_dir, artifact)
            if not os.path.isfile(path):
                continue
            report = self.auditor.audit(path, task.agent, task.task_id)
            hint = self.auditor.fix_hint(report, task.task_id)
            if hint:
                hints.append(f"[{artifact}]\n{hint}")

        return "\n\n".join(hints) if hints else ""
