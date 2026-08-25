"""
Dreamer AI Phase 1 — Hermes Scheduler
DAG builder, parallel scheduler, lock conflict resolver.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict
import logging
import os
import sqlite3
import uuid as _uuid
from .registry import SubagentRegistry

_log = logging.getLogger(__name__)


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

    # ── Phase 2.3: Kid-Safe Output Layer wiring ─────────

    @staticmethod
    def inject_kb_query(
        content: str,
        age_band: Optional[str] = None,
    ) -> str:
        """Inject Ethical AI KB prefix into a student query.

        Call this BEFORE sending content to DeepTutor.

        Args:
            content: Raw student query text.
            age_band: "P1-P3", "P4-P6", "S1-S3", or None.

        Returns:
            Query with dreamer-ethical-ai KB prepended.
        """
        from .kid_safe.ethical_ai_kb import inject_kb
        return inject_kb(content, age_band)

    @staticmethod
    def kid_safe_input(
        query: str,
        age_band: str,
        lang_code: str,
        student_id: str = "",
        session_id: str = "",
    ) -> Optional[dict]:
        """Phase 2.5 — Input safety gate. Run BEFORE inject_kb_query.

        Order in pipeline:
            student input → kid_safe_input() → inject_kb_query() → DeepTutor

        If query is safe, returns None (pass-through).
        If query is blocked, returns dict with:
            - response_message: str  (student-facing friendly message)
            - event: dict           (for safety_events DB insert)
            - is_welfare: bool      (True = welfare alert needed)

        Welfare events fire async webhook alert (fire-and-forget).

        Args:
            query: Raw student query text.
            age_band: "P1-P3", "P4-P6", or "S1-S3".
            lang_code: "en", "zh-hk", or "zh-cn".
            student_id: Student identifier for audit trail.
            session_id: Session identifier for audit trail.

        Returns:
            None if safe; block dict if unsafe.
        """
        from .kid_safe.input_guard import InputGuard, notify_welfare

        guard = InputGuard()
        verdict = guard.check(
            query, age_band, lang_code,
            student_id=student_id, session_id=session_id,
        )

        if verdict.is_safe:
            return None

        # Blocked — persist to safety_events (must write before webhook)
        if verdict.event is not None:
            _write_safety_event(verdict.event)

        # Fire webhook for welfare events
        if verdict.is_welfare and verdict.event is not None:
            notify_welfare(verdict.event)

        return {
            "response_message": verdict.response_message,
            "event": verdict.event,
            "is_welfare": verdict.is_welfare,
        }

    @staticmethod
    def kid_safe_wrap(
        response_text: str,
        age_band: str,
        lang_code: str,
        session: Optional["SessionState"] = None,
    ) -> str:
        """Pipe a DeepTutor response through KidSafePipeline.

        Middleware position: DeepTutor response → KidSafe → student.

        Args:
            response_text: Raw DeepTutor response.
            age_band: "P1-P3", "P4-P6", or "S1-S3".
            lang_code: "en", "zh-hk", or "zh-cn".
            session: Optional SessionState for turn tracking.

        Returns:
            Kid-safe student-facing output.
        """
        from .kid_safe import KidSafePipeline
        pipeline = KidSafePipeline()
        return pipeline.process_response(
            response_text, age_band, lang_code, session=session,
        )

    @staticmethod
    def kid_safe_error(
        raw_error: str,
        error_type: str,
        age_band: str,
        lang_code: str,
    ) -> str:
        """Pipe an error through KidSafePipeline error path.

        Errors bypass ToneRewrite/LabelSoften/SessionWrap.
        Student sees only a friendly template-based message.

        Args:
            raw_error: Raw/internal error string.
            error_type: "ws_error", "timeout", "server_error",
                        "empty_response", "unknown".
            age_band: "P1-P3", "P4-P6", or "S1-S3".
            lang_code: "en", "zh-hk", or "zh-cn".

        Returns:
            Student-facing friendly error message.
        """
        from .kid_safe import KidSafePipeline
        pipeline = KidSafePipeline()
        return pipeline.process_error(raw_error, error_type, age_band, lang_code)


# ═══════════════════════════════════════════════════════════
# Phase 4: Student Query Routing Plan
# ═══════════════════════════════════════════════════════════

@dataclass
class PlanContext:
    """Output of build_plan(): complete context for student query routing.

    Fields:
        mode:       DIRECT | CONTEXTUAL | HYBRID
        lang_code:  en | zh-hk | zh-cn
        age_band:   P1-P3 | P4-P6 | S1-S3 (validated)
        agent_list: eligible agent names for this mode
        kb_list:    knowledge bases to query (includes ethical-ai)
        prereq_gaps: prerequisite gaps (empty if no topic_id provided)
        matched_keyword: first keyword that triggered mode match (None if no hit)
    """
    mode: str
    lang_code: str
    age_band: str
    agent_list: List[str]
    kb_list: List[str]
    prereq_gaps: List[Dict[str, Any]] = field(default_factory=list)
    matched_keyword: Optional[str] = None

    def __post_init__(self):
        if self.mode not in ("DIRECT", "CONTEXTUAL", "HYBRID"):
            raise ValueError(f"Invalid mode: {self.mode}")
        if self.lang_code not in ("en", "zh-hk", "zh-cn"):
            raise ValueError(f"Invalid lang_code: {self.lang_code}")
        from .curriculum_navigator import validate_age_band
        self.age_band = validate_age_band(self.age_band)


def build_plan(
    text: str,
    student_id: str,
    age_band: str,
    *,
    topic_id: Optional[str] = None,
    registry: Optional[SubagentRegistry] = None,
    mode_router: Optional[Any] = None,
    navigator: Optional[Any] = None,
    session_id: str = "",
) -> PlanContext:
    """Build a PlanContext from a student query.

    Deterministic pipeline:
      1. Validate age_band
      2. ModeRouter.detect_language + route → mode + lang_code
      3. registry.list_by_mode → agent_list
      4. If topic_id: navigator.resolve_kb_list, check_prereq_gaps

    Args:
        text:       Raw student query text.
        student_id: Student identifier.
        age_band:   P1-P3 | P4-P6 | S1-S3.
        topic_id:   Optional topic context.
        registry:   SubagentRegistry for agent lookups.
        mode_router: ModeRouter instance (default: lazy init).
        navigator:  CurriculumNavigator instance (default: lazy init).

    Returns:
        PlanContext with mode, lang_code, agent_list, kb_list, prereq_gaps.

    Raises:
        ValueError: if age_band is invalid.
        RuntimeError: if registry is None and agent list is needed.
    """
    from .curriculum_navigator import (
        CurriculumNavigator,
        ETHICAL_AI_KB,
        validate_age_band,
    )
    from .mode_router import ModeRouter

    # Step 1: Validate age_band
    age_band = validate_age_band(age_band)

    # Step 2: Route mode + language
    router = mode_router if mode_router is not None else ModeRouter()
    mode_val, lang_code, matched_kw = router.route_with_trace(text)

    # Step 3: Agent list from registry
    if registry is None:
        raise RuntimeError("build_plan() requires SubagentRegistry for agent list")
    candidates = registry.list_by_mode(mode_val.value)
    agent_list = [c["name"] for c in candidates]

    # Step 4: KB list + prereq gaps (topic-dependent)
    if topic_id:
        nav = navigator if navigator is not None else CurriculumNavigator()
        kb_list = nav.resolve_kb_list(mode_val.value, topic_id)
        prereq_gaps = nav.check_prereq_gaps(student_id, topic_id)
    else:
        kb_list = [ETHICAL_AI_KB]
        prereq_gaps = []

    return PlanContext(
        mode=mode_val.value,
        lang_code=lang_code,
        age_band=age_band,
        agent_list=agent_list,
        kb_list=kb_list,
        prereq_gaps=prereq_gaps,
        matched_keyword=matched_kw,
    )


# ═══════════════════════════════════════════════════════════
# Phase 4 Day 21: execute() — Real Dispatch Pipeline
# ═══════════════════════════════════════════════════════════

async def execute(
    text: str,
    student_id: str,
    age_band: str,
    *,
    topic_id: Optional[str] = None,
    capability: Optional[str] = None,
    registry: Optional[SubagentRegistry] = None,
    mode_router: Optional[Any] = None,
    navigator: Optional[Any] = None,
    session_id: str = "",
) -> Dict[str, Any]:
    """Real dispatch pipeline for student queries.

    Async — callers must await this function.

    Pipeline order (do not reorder):
      student query → kid_safe_input() → build_plan()
        → dispatch by mode → kid_safe_wrap() → session_logs → structured JSON

    DIRECT / HYBRID → Assessment Agent (quiz_gen by default).
    DIRECT no topic_id → Kid-Safe clarifying template.
    CONTEXTUAL → WS DeepTutor chat → kid_safe_wrap().

    Args:
        text:       Raw student query text.
        student_id: Student identifier.
        age_band:   P1-P3 | P4-P6 | S1-S3.
        topic_id:   Optional topic context for DIRECT/HYBRID routing.
        capability: Assessment capability override (default: quiz_gen).
        registry:   SubagentRegistry for agent lookups.
        mode_router: ModeRouter instance.
        navigator:  CurriculumNavigator instance.
        session_id: Session identifier for audit trail.

    Returns:
        Structured JSON dict:
        {
            content, mode, lang_code, age_band, kid_label,
            citations, cost_summary
        }
    """
    import uuid
    import time

    sid = session_id or f"stu_{student_id}_{uuid.uuid4().hex[:8]}"
    start_time = time.perf_counter()

    # ── Step 1: kid_safe_input (must run first) ──────
    # Use ModeRouter.detect_language() for correct guard rule table matching
    router = mode_router
    if router is None:
        from .mode_router import ModeRouter
        router = ModeRouter()
    lang_code_hint = router.detect_language(text)
    block = HermesScheduler.kid_safe_input(
        text, age_band, lang_code_hint,
        student_id=student_id, session_id=sid,
    )
    if block is not None:
        # Safety-triggered block — return immediately, no further routing
        block_elapsed_ms = (time.perf_counter() - start_time) * 1000
        _write_session_log(
            session_id=sid, student_id=student_id,
            mode="BLOCKED", lang_code=lang_code_hint,
            age_band=age_band, agent_list=[],
            topic_ids=[topic_id] if topic_id else [],
            cost_summary={"input_safety_blocked": True},
            duration_seconds=int(block_elapsed_ms / 1000),
        )
        # Emit safety event with pointer only (no raw text)
        try:
            from .observability import emit_event, EVENT_SAFETY
            ev = block.get("event", {}) if isinstance(block, dict) else {}
            emit_event(
                EVENT_SAFETY,
                {
                    "safety_event_id": ev.get("id") if isinstance(ev, dict) else None,
                    "block_type": ev.get("event_type") if isinstance(ev, dict) else None,
                },
                student_id=student_id,
                session_id=sid,
            )
        except Exception:
            pass
        return {
            "content": block["response_message"],
            "mode": "BLOCKED",
            "lang_code": lang_code_hint,
            "age_band": age_band,
            "kid_label": "blocked",
            "citations": [],
            "cost_summary": {"input_safety_blocked": True},
        }

    # ── Step 2: build_plan() ─────────────────────────
    reg = registry if registry is not None else _default_registry()
    plan = build_plan(
        text, student_id, age_band,
        topic_id=topic_id, registry=reg,
        mode_router=router, navigator=navigator,
        session_id=session_id,
    )

    # ── Step 3: dispatch by mode ────────────────────
    mode_val = plan.mode
    lang_code = plan.lang_code

    # ── emit routing event ──────────────────────────
    matched_kw = plan.matched_keyword
    try:
        from .observability import emit_event, EVENT_ROUTING
        emit_event(
            EVENT_ROUTING,
            {
                "mode": mode_val,
                "lang_code": lang_code,
                "matched_keyword": matched_kw,
            },
            student_id=student_id,
            session_id=sid,
        )
    except Exception:
        pass

    if mode_val == "DIRECT":
        if not topic_id:
            # No topic — clarifying template instead of quiz_gen
            result = _direct_clarifying_response(lang_code, plan.age_band)
            mode_label = "DIRECT_clarifying"
            agent_list: list = []
            # emit clarifying event
            try:
                from .observability import emit_event, EVENT_CLARIFYING
                emit_event(
                    EVENT_CLARIFYING,
                    {"mode": mode_val, "lang_code": lang_code},
                    student_id=student_id,
                    session_id=sid,
                )
            except Exception:
                pass
        else:
            actual_cap = capability or "quiz_gen"
            result = await _call_assessment(plan, topic_id, actual_cap, student_id, sid)
            mode_label = "DIRECT"
            agent_list = ["assessment"]
    elif mode_val == "HYBRID":
        if not topic_id:
            # No topic — clarifying template instead of quiz_gen
            # HYBRID requires topic_id for Curriculum context; without it,
            # quiz_gen(topic=None) would produce garbage
            result = _direct_clarifying_response(lang_code, plan.age_band)
            mode_label = "HYBRID_clarifying"
            agent_list = []
            # emit clarifying event
            try:
                from .observability import emit_event, EVENT_CLARIFYING
                emit_event(
                    EVENT_CLARIFYING,
                    {"mode": mode_val, "lang_code": lang_code},
                    student_id=student_id,
                    session_id=sid,
                )
            except Exception:
                pass
        else:
            actual_cap = capability or "quiz_gen"
            result = await _call_assessment(plan, topic_id, actual_cap, student_id, sid)
            mode_label = "HYBRID"
            agent_list = ["assessment"]  # v1: only assessment runs here
    elif mode_val == "CONTEXTUAL":
        result = await _run_contextual(text, plan, student_id, sid)
        mode_label = "CONTEXTUAL"
        agent_list = ["deeptutor"]
        # emit ws event
        try:
            from .observability import emit_event, EVENT_WS
            emit_event(
                EVENT_WS,
                {"mode": mode_val, "lang_code": lang_code},
                student_id=student_id,
                session_id=sid,
            )
        except Exception:
            pass
    else:
        result = {
            "content": "I'm not sure how to help with that.",
            "kid_label": "unknown",
            "citations": [],
            "cost_summary": {},
        }
        mode_label = mode_val
        agent_list = []

    # ── Step 4: session_logs ─────────────────────────
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    cost = result.get("cost_summary", {})
    cost["elapsed_ms"] = round(elapsed_ms, 1)

    _write_session_log(
        session_id=sid, student_id=student_id,
        mode=mode_label, lang_code=lang_code,
        age_band=plan.age_band, agent_list=agent_list,
        topic_ids=[topic_id] if topic_id else [],
        cost_summary=cost,
        duration_seconds=int(elapsed_ms / 1000),
    )

    # ── emit cost event (single source of truth, all modes) ──
    _emit_cost_event(cost, student_id=student_id, session_id=sid)

    # ── Step 5: structured JSON ─────────────────────
    return {
        "content": result.get("content", ""),
        "mode": mode_label,
        "lang_code": lang_code,
        "age_band": plan.age_band,
        "kid_label": result.get("kid_label", "ok"),
        "citations": result.get("citations", []),
        "cost_summary": cost,
    }


# ── execute() helper: default registry ───────────────────

_registry_cache: Optional[SubagentRegistry] = None


def _default_registry() -> SubagentRegistry:
    """Lazy singleton registry with all agents registered."""
    global _registry_cache
    if _registry_cache is None:
        from .subagents import register_all
        reg = SubagentRegistry()
        register_all(reg)
        _registry_cache = reg
    return _registry_cache


# ── execute() helper: DIRECT clarifying response ─────────

def _direct_clarifying_response(lang_code: str, age_band: str) -> dict:
    """Return a Kid-Safe clarifying message for DIRECT mode without topic_id."""
    from .kid_safe.clarifying_templates import get_clarifying_message
    content = get_clarifying_message(age_band, lang_code)
    return {
        "content": content,
        "kid_label": "clarifying",
        "citations": [],
        "cost_summary": {"direct_clarifying": True},
    }


# ── execute() helper: Assessment Agent dispatch ──────────

async def _call_assessment(
    plan: PlanContext,
    topic_id: str,
    capability: str,
    student_id: str,
    session_id: str,
) -> dict:
    """Call AssessmentAgent.quiz_gen (or specified capability) for DIRECT/HYBRID.

    Uses async agent.quiz_gen() for real LLM assessment.
    Falls back to stub if container is unreachable.
    """
    from .assessment_agent import AssessmentAgent
    agent = AssessmentAgent()
    # Map age_band to grade_level: P1-P3→1, P4-P6→4, S1-S3→7
    _age_grade_map = {"P1": 1, "P2": 1, "P3": 1, "P4": 4, "P5": 4, "P6": 4, "S1": 7, "S2": 7, "S3": 7}
    grade_level = _age_grade_map.get(plan.age_band, 1)
    params = {
        "capability": capability,
        "topic": topic_id,
        "mode": plan.mode,
        "grade_level": grade_level,
        "count": 3,
        "question_type": "short_answer",
        "lang_code": plan.lang_code,
        "age_band": plan.age_band,
        "student_id": student_id,
        "session_id": session_id,
    }

    if capability == "quiz_gen":
        raw = await agent.quiz_gen(params)
    elif capability == "rubric_gen":
        raw = await agent.rubric_gen(params)
    elif capability == "auto_marking":
        raw = await agent.auto_marking(params)
    elif capability == "progress_track":
        raw = await agent.progress_track(params)
    else:
        raw = agent.execute(task_id=session_id, params=params)

    if raw.get("status") in ("ok", "ok_stub"):
        questions = raw.get("questions", [])
        content = _format_questions(questions, plan.lang_code, plan.age_band)
        # Kid-Safe Output Layer: all outputs pass through kid_safe_wrap
        content = HermesScheduler.kid_safe_wrap(content, plan.age_band, plan.lang_code)
        cost = {
            "agent": "assessment",
            "capability": capability,
            "status": raw.get("status", "ok"),
            "questions_count": len(questions),
        }
        # Merge WS-derived cost fields (total_tokens/total_cost_usd/total_calls).
        # Context fields above take precedence; missing keys fall back to raw.
        for _k, _v in (raw.get("cost_summary") or {}).items():
            cost.setdefault(_k, _v)
        # Emit fallback if LLM fell to stub
        if raw.get("status") == "ok_stub":
            try:
                from .observability import emit_event, EVENT_FALLBACK
                emit_event(
                    EVENT_FALLBACK,
                    {
                        "component": "assessment",
                        "reason": "ok_stub",
                        "capability": capability,
                    },
                    student_id=student_id,
                    session_id=session_id,
                )
            except Exception:
                pass
        return {
            "content": content,
            "kid_label": "ok",
            "citations": [],
            "cost_summary": cost,
        }
    # Fallback: return raw stub content
    _err_cost = {"agent": "assessment", "status": raw.get("status", "error")}
    for _k, _v in (raw.get("cost_summary") or {}).items():
        _err_cost.setdefault(_k, _v)
    return {
        "content": str(raw.get("result", "")),
        "kid_label": "ok",
        "citations": [],
        "cost_summary": _err_cost,
    }


def _format_questions(questions: list, lang_code: str, age_band: str) -> str:
    """Format quiz questions as student-facing text."""
    if not questions:
        from .kid_safe.error_templates import get_error_message
        return get_error_message(age_band, lang_code)

    lines = []
    for i, q in enumerate(questions, 1):
        text = q.get("question", q.get("id", f"Q{i}"))
        lines.append(f"{i}. {text}")
    return "\n\n".join(lines)


# ── execute() helper: CONTEXTUAL WS chat ─────────────────

async def _run_contextual(
    text: str,
    plan: PlanContext,
    student_id: str,
    session_id: str,
) -> dict:
    """Run CONTEXTUAL mode: WS DeepTutor chat → kid_safe_wrap."""
    import asyncio

    # Inject ethical-ai KB into query
    injected = HermesScheduler.inject_kb_query(text, plan.age_band)

    from .deeptutor_ws import DeepTutorWSClient
    client = DeepTutorWSClient()
    try:
        if not client.is_connected:
            await client.wait_until_ready(max_retries=5, interval=2.0)
        # Day 27 #6: removed DREAMER_MAX_TOKENS → ws_config["max_tokens"] injection.
        # The env var now only serves quality_audit's cost cap assertion (audit-only).
        ws_result = await client.query(
            session_id=session_id,
            content=injected,
            capability="chat",
            language=plan.lang_code,
        )
    except Exception as exc:
        _log = logging.getLogger(__name__)
        _log.warning("CONTEXTUAL WS failed (%s), falling back to stub", exc)
        # Emit fallback event for WS error
        try:
            from .observability import emit_event, EVENT_FALLBACK
            emit_event(
                EVENT_FALLBACK,
                {
                    "component": "ws",
                    "reason": str(exc),
                    "mode": plan.mode,
                },
                student_id=student_id,
                session_id=session_id,
            )
        except Exception:
            pass
        from .kid_safe.error_templates import get_error_message
        return {
            "content": get_error_message(plan.age_band, plan.lang_code),
            "kid_label": "ws_error",
            "citations": [],
            "cost_summary": {"ws_fallback": "stub", "error": str(exc)},
        }
    finally:
        if client.is_connected:
            await client.disconnect()

    # kid_safe_wrap the WS response
    wrapped = HermesScheduler.kid_safe_wrap(
        ws_result.content, plan.age_band, plan.lang_code,
    )
    return {
        "content": wrapped,
        "kid_label": "ok",
        "citations": ws_result.citations,
        "cost_summary": ws_result.cost_summary,
    }


# ── execute() helper: cost event emit (single source of truth) ──

def _emit_cost_event(cost: dict, student_id: str, session_id: str) -> None:
    """Emit one obs_events cost row. All modes (DIRECT/HYBRID/CONTEXTUAL)
    funnel through this helper so the cost event schema has exactly one
    origin — callers only shape the payload, never emit themselves."""
    try:
        from .observability import emit_event, EVENT_COST
        emit_event(
            EVENT_COST,
            cost,
            student_id=student_id,
            session_id=session_id,
        )
    except Exception:
        pass


# ── execute() helper: session_logs persistence ───────────

_SESSION_LOGS_TABLE_ENSURED = False


def _ensure_session_logs_table() -> None:
    """Create session_logs table if not exists (idempotent, with migration).

    Phase 7 (Day 27): duration_seconds added. SQLite has no
    ADD COLUMN IF NOT EXISTS — check via PRAGMA so repeated runs on both
    fresh and legacy DBs never throw. Legacy rows keep NULL (unknown), not 0.
    """
    global _SESSION_LOGS_TABLE_ENSURED
    if _SESSION_LOGS_TABLE_ENSURED:
        return
    import os as _os
    db_path = _os.environ.get(
        "DREAMER_DB_PATH",
        _os.path.join(_os.path.dirname(__file__), "..", "dreamer.db"),
    )
    db_path = _os.path.abspath(db_path)
    _os.makedirs(_os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS session_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT '',
                lang_code TEXT NOT NULL DEFAULT '',
                age_band TEXT NOT NULL DEFAULT '',
                agent_list TEXT NOT NULL DEFAULT '[]',
                topic_ids TEXT NOT NULL DEFAULT '[]',
                cost_summary TEXT NOT NULL DEFAULT '{}',
                duration_seconds INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_session_logs_sid
                ON session_logs(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_session_logs_student
                ON session_logs(student_id, created_at);
        """)
        # Migration: legacy DBs created before duration_seconds.
        cols = [row[1] for row in conn.execute("PRAGMA table_info(session_logs)")]
        if "duration_seconds" not in cols:
            conn.execute(
                "ALTER TABLE session_logs ADD COLUMN duration_seconds INTEGER"
            )
        conn.commit()
    finally:
        conn.close()
    _SESSION_LOGS_TABLE_ENSURED = True


def _write_session_log(
    session_id: str,
    student_id: str,
    mode: str,
    lang_code: str,
    age_band: str,
    agent_list: list,
    topic_ids: list,
    cost_summary: dict,
    duration_seconds: Optional[int] = None,
) -> None:
    """Write a session_logs row (duration_seconds = real session span)."""
    import json
    import datetime

    _ensure_session_logs_table()

    db_path = os.environ.get(
        "DREAMER_DB_PATH",
        os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
    )
    db_path = os.path.abspath(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """INSERT INTO session_logs
               (session_id, student_id, mode, lang_code, age_band,
                agent_list, topic_ids, cost_summary, duration_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, student_id, mode, lang_code, age_band,
                json.dumps(agent_list, ensure_ascii=False),
                json.dumps(topic_ids, ensure_ascii=False),
                json.dumps(cost_summary, ensure_ascii=False),
                duration_seconds,
                datetime.datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── execute() helper: safety_events persistence ───────────

def _write_safety_event(event: dict) -> None:
    """INSERT event dict into safety_events table.

    Must succeed to preserve audit trail. On failure, logs error and
    sets db_write_failed=True on the event so webhook knows evidence is missing.
    Per Phase 5 red-line: safety evidence ≠ observability — fail-silent is NOT
    acceptable here.
    """
    import datetime as _dt
    try:
        db_path = os.path.abspath(os.environ.get(
            "DREAMER_DB_PATH",
            os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
        ))
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS safety_events (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    raw_input TEXT NOT NULL,
                    matched_rule TEXT,
                    age_band TEXT,
                    lang_code TEXT,
                    reviewed BOOLEAN DEFAULT FALSE,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_safety_unreviewed
                    ON safety_events(reviewed, severity, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_safety_student
                    ON safety_events(student_id, created_at DESC);
            """)
            conn.execute(
                """INSERT INTO safety_events
                   (id, student_id, session_id, event_type, severity,
                    raw_input, matched_rule, age_band, lang_code,
                    reviewed, reviewed_by, reviewed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("id") or _uuid.uuid4().hex,
                    event.get("student_id", ""),
                    event.get("session_id", ""),
                    event.get("event_type", ""),
                    event.get("severity", ""),
                    event.get("raw_input", ""),
                    event.get("matched_rule", ""),
                    event.get("age_band", ""),
                    event.get("lang_code", ""),
                    event.get("reviewed", False),
                    event.get("reviewed_by"),
                    event.get("reviewed_at"),
                    event.get("created_at") or _dt.datetime.utcnow().isoformat() + "Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log.error("SAFETY EVENT DB WRITE FAILED — evidence lost: %s", exc)
        event["db_write_failed"] = True


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
