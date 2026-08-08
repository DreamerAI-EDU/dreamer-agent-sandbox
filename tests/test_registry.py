"""
test_registry.py — SubagentRegistry unit tests.

Key cases:
- register / get / list_all / list_by_mode / list_by_kb
- duplicate name rejection
- thread safety (concurrent registration)
- mode_allowlist=None semantics (excluded from list_by_mode)
- lazy init: agent only instantiated on first get()
"""

import sys
import os
import threading
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.registry import SubagentRegistry


# ── Dummy agent classes for testing ────────────────────

class DummyAgentA:
    instantiated = 0

    def __init__(self):
        DummyAgentA.instantiated += 1

    def execute(self, task_id, params):
        return {"agent": "a", "task_id": task_id, "result": "ok"}


class DummyAgentB:
    instantiated = 0

    def __init__(self):
        DummyAgentB.instantiated += 1

    def execute(self, task_id, params):
        return {"agent": "b", "task_id": task_id, "result": "ok"}


class DummyNonStudent:
    """mode_allowlist=None — non-student-facing."""

    def execute(self, task_id, params):
        return {"agent": "non_student", "task_id": task_id, "result": "ok"}


# ── Fixture ────────────────────────────────────────────


@pytest.fixture
def registry():
    return SubagentRegistry()


# ── Basic registration ─────────────────────────────────


class TestRegistration:

    def test_register_and_get(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT", "HYBRID"])
        agent = registry.get("agent_a")
        assert isinstance(agent, DummyAgentA)

    def test_list_all(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT"])
        registry.register("agent_b", DummyAgentB,
                          kb_ownership=["english"], capabilities=["lesson"],
                          mode_allowlist=["CONTEXTUAL"])
        assert registry.list_all() == ["agent_a", "agent_b"]

    def test_len_and_contains(self, registry):
        assert len(registry) == 0
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=[], capabilities=[], mode_allowlist=["DIRECT"])
        assert len(registry) == 1
        assert "agent_a" in registry
        assert "agent_b" not in registry


# ── Duplicate name rejection ────────────────────────────


class TestDuplicateRejection:

    def test_duplicate_raises(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=[], capabilities=[], mode_allowlist=[])
        with pytest.raises(ValueError, match="already registered"):
            registry.register("agent_a", DummyAgentB,
                              kb_ownership=[], capabilities=[], mode_allowlist=[])


# ── list_by_mode ─────────────────────────────────────────


class TestListByMode:

    def test_mode_filtering(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT", "HYBRID"])
        registry.register("agent_b", DummyAgentB,
                          kb_ownership=["english"], capabilities=["lesson"],
                          mode_allowlist=["CONTEXTUAL"])

        direct = registry.list_by_mode("DIRECT")
        assert len(direct) == 1
        assert direct[0]["name"] == "agent_a"

        contextual = registry.list_by_mode("CONTEXTUAL")
        assert len(contextual) == 1
        assert contextual[0]["name"] == "agent_b"

        both = registry.list_by_mode("HYBRID")
        assert len(both) == 1
        assert both[0]["name"] == "agent_a"

    def test_non_student_excluded(self, registry):
        """mode_allowlist=None agents must never appear in list_by_mode."""
        registry.register("student", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT"])
        registry.register("non_student", DummyNonStudent,
                          kb_ownership=["reports"], capabilities=["report"],
                          mode_allowlist=None)

        result = registry.list_by_mode("DIRECT")
        names = [r["name"] for r in result]
        assert "student" in names
        assert "non_student" not in names

    def test_empty_mode_allowlist(self, registry):
        """mode_allowlist=[] should behave as list, not None."""
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=[])

        # Empty allowlist: never matches any mode
        for mode in ("DIRECT", "CONTEXTUAL", "HYBRID"):
            result = registry.list_by_mode(mode)
            assert len(result) == 0, f"mode={mode} should return empty"


# ── list_by_kb ──────────────────────────────────────────


class TestListByKb:

    def test_kb_filtering(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths", "english"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT"])
        registry.register("agent_b", DummyAgentB,
                          kb_ownership=["science", "maths"], capabilities=["lesson"],
                          mode_allowlist=["CONTEXTUAL"])

        maths_agents = registry.list_by_kb("maths")
        assert maths_agents == ["agent_a", "agent_b"]

        english_agents = registry.list_by_kb("english")
        assert english_agents == ["agent_a"]

    def test_no_match(self, registry):
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT"])
        assert registry.list_by_kb("history") == []


# ── Lazy init ────────────────────────────────────────────


class TestLazyInit:

    def test_agent_not_instantiated_until_get(self, registry):
        DummyAgentA.instantiated = 0
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=[], capabilities=[], mode_allowlist=["DIRECT"])
        # Registration alone should NOT instantiate
        assert DummyAgentA.instantiated == 0
        # get() triggers lazy instantiation
        agent = registry.get("agent_a")
        assert isinstance(agent, DummyAgentA)
        assert DummyAgentA.instantiated == 1

    def test_second_get_returns_same_instance(self, registry):
        DummyAgentA.instantiated = 0
        registry.register("agent_a", DummyAgentA,
                          kb_ownership=[], capabilities=[], mode_allowlist=["DIRECT"])
        a1 = registry.get("agent_a")
        a2 = registry.get("agent_a")
        assert a1 is a2
        assert DummyAgentA.instantiated == 1  # only instantiated once


# ── Thread safety ────────────────────────────────────────


class TestThreadSafety:

    def test_concurrent_registration(self, registry):
        """Concurrent register() calls from multiple threads should not corrupt."""
        errors = []

        def register_agent(idx):
            try:
                registry.register(
                    f"thread_agent_{idx}", DummyAgentA,
                    kb_ownership=[f"kb_{idx}"], capabilities=[f"cap_{idx}"],
                    mode_allowlist=["DIRECT"],
                )
            except ValueError as e:
                errors.append(str(e))

        threads = []
        for i in range(20):
            t = threading.Thread(target=register_agent, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(registry) == 20
        assert len(errors) == 0
        names = registry.list_all()
        assert len(names) == 20
        # Each should be unique
        assert len(set(names)) == 20

    def test_concurrent_get_and_register(self, registry):
        """Concurrent get() + register() should not deadlock or corrupt state."""
        registry.register("existing", DummyAgentA,
                          kb_ownership=[], capabilities=[], mode_allowlist=["DIRECT"])
        errors = []

        def getter():
            try:
                registry.get("existing")
            except Exception as e:
                errors.append(str(e))

        def register_new(idx):
            try:
                registry.register(
                    f"new_{idx}", DummyAgentB,
                    kb_ownership=[], capabilities=[],
                    mode_allowlist=["CONTEXTUAL"],
                )
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(10):
            t1 = threading.Thread(target=getter)
            t2 = threading.Thread(target=register_new, args=(i,))
            threads.extend([t1, t2])
            t1.start()
            t2.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert "existing" in registry
        assert len(registry) >= 11  # 1 existing + 10 new


# ── get() error ──────────────────────────────────────────


class TestGetErrors:

    def test_get_unregistered_raises(self, registry):
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent")


# ── mode permission enforcement ──────────────────────────


class TestModePermissionEnforcement:

    def test_non_student_agent_never_appears_in_list_by_mode(self, registry):
        registry.register("student_a", DummyAgentA,
                          kb_ownership=["maths"], capabilities=["quiz"],
                          mode_allowlist=["DIRECT"])
        registry.register("student_b", DummyAgentB,
                          kb_ownership=["english"], capabilities=["lesson"],
                          mode_allowlist=["CONTEXTUAL", "HYBRID"])
        registry.register("parent_report", DummyNonStudent,
                          kb_ownership=[], capabilities=["report"],
                          mode_allowlist=None)
        registry.register("marketing", DummyNonStudent,
                          kb_ownership=[], capabilities=["social"],
                          mode_allowlist=None)

        for mode in ("DIRECT", "CONTEXTUAL", "HYBRID"):
            result = registry.list_by_mode(mode)
            names = [r["name"] for r in result]
            assert "parent_report" not in names, f"parent_report leaked into {mode}"
            assert "marketing" not in names, f"marketing leaked into {mode}"

    def test_non_student_agents_still_accessible_via_get(self, registry):
        """Non-student agents must be accessible via direct get() calls,
        just not via student query routing."""
        registry.register("parent_report", DummyNonStudent,
                          kb_ownership=[], capabilities=["report"],
                          mode_allowlist=None)
        agent = registry.get("parent_report")
        assert isinstance(agent, DummyNonStudent)
        result = agent.execute("task_1", {"key": "val"})
        assert result["agent"] == "non_student"
        assert result["result"] == "ok"
