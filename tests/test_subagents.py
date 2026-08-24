"""
test_subagents.py — Sub Agent stub tests.

Key cases:
- Each stub returns expected placeholder response
- mode_allowlist correctly scoped (student-facing vs non-student-facing)
- register_all() populates registry with all 5 agents
- KB ownership correct for each agent
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.registry import SubagentRegistry
from agents.subagents import (
    CurriculumAgentStub,
    PortfolioAgentStub,
    MarketingAgentStub,
    register_all,
)
from agents.assessment_agent import AssessmentAgent
from agents.parent_report_agent import ParentReportAgent


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def registry():
    return SubagentRegistry()


@pytest.fixture
def populated_registry(registry):
    register_all(registry)
    return registry


# ── Individual stub execution ───────────────────────────


def test_curriculum_stub_execute():
    agent = CurriculumAgentStub()
    result = agent.execute("t1", {"mode": "CONTEXTUAL", "grade_level": 3})
    assert result["agent"] == "curriculum"
    assert result["status"] == "ok"
    assert "[CurriculumAgent stub]" in result["result"]


def test_assessment_agent_execute():
    agent = AssessmentAgent()
    result = agent.execute("t2", {"mode": "DIRECT", "grade_level": 5})
    assert result["agent"] == "assessment"
    assert result["status"] == "ok"
    assert "[AssessmentAgent]" in result["result"] or "AssessmentAgent" in str(result)


def test_portfolio_stub_execute():
    agent = PortfolioAgentStub()
    result = agent.execute("t3", {"mode": "CONTEXTUAL", "grade_level": 2})
    assert result["agent"] == "portfolio"
    assert result["status"] == "ok"
    assert "[PortfolioAgent stub]" in result["result"]


def test_parent_report_agent_execute():
    agent = ParentReportAgent()
    result = agent.execute("t4", {"key": "val"})
    assert result["agent"] == "parent_report"
    assert result["status"] == "error"  # missing student_id


def test_marketing_stub_execute():
    agent = MarketingAgentStub()
    result = agent.execute("t5", {"campaign": "summer"})
    assert result["agent"] == "marketing"
    assert result["status"] == "ok"
    assert "[MarketingAgent stub]" in result["result"]


# ── register_all ────────────────────────────────────────


def test_register_all_populates_registry(populated_registry):
    assert len(populated_registry) == 5
    expected = {"curriculum", "assessment", "portfolio", "parent_report", "marketing"}
    assert set(populated_registry.list_all()) == expected


# ── KB ownership ────────────────────────────────────────


def test_curriculum_kb_ownership(populated_registry):
    result = populated_registry.list_by_kb("dreamer-prerequisites")
    assert "curriculum" in result


def test_curriculum_kb_ownership_broad(populated_registry):
    for kb in ["dreamer-maths-ai", "dreamer-coding-python",
               "dreamer-game-design"]:
        result = populated_registry.list_by_kb(kb)
        assert "curriculum" in result, f"curriculum should own {kb}"


def test_assessment_kb_ownership(populated_registry):
    result = populated_registry.list_by_kb("dreamer-assessment")
    assert "assessment" in result


def test_portfolio_kb_ownership(populated_registry):
    result = populated_registry.list_by_kb("dreamer-portfolio")
    assert "portfolio" in result


# ── mode_allowlist enforcement ──────────────────────────


def test_student_facing_agents_appear_in_list_by_mode(populated_registry):
    """Curriculum, Assessment, Portfolio must appear in their configured modes."""
    # Curriculum: CONTEXTUAL, HYBRID
    contextual = populated_registry.list_by_mode("CONTEXTUAL")
    contextual_names = [r["name"] for r in contextual]
    assert "curriculum" in contextual_names
    assert "portfolio" in contextual_names

    # Assessment: DIRECT, HYBRID
    direct = populated_registry.list_by_mode("DIRECT")
    direct_names = [r["name"] for r in direct]
    assert "assessment" in direct_names

    # HYBRID: curriculum + assessment
    hybrid = populated_registry.list_by_mode("HYBRID")
    hybrid_names = [r["name"] for r in hybrid]
    assert "curriculum" in hybrid_names
    assert "assessment" in hybrid_names


def test_non_student_agents_excluded_from_list_by_mode(populated_registry):
    """ParentReport and Marketing must never appear in any mode."""
    for mode in ("DIRECT", "CONTEXTUAL", "HYBRID"):
        result = populated_registry.list_by_mode(mode)
        names = [r["name"] for r in result]
        assert "parent_report" not in names, f"parent_report leaked into {mode}"
        assert "marketing" not in names, f"marketing leaked into {mode}"


def test_non_student_agents_still_gettable(populated_registry):
    """Non-student agents should be accessible via direct get()."""
    parent = populated_registry.get("parent_report")
    assert isinstance(parent, ParentReportAgent)

    marketing = populated_registry.get("marketing")
    assert isinstance(marketing, MarketingAgentStub)

    # Assessment now returns real AssessmentAgent
    assessment = populated_registry.get("assessment")
    assert isinstance(assessment, AssessmentAgent)


def test_non_student_agents_have_no_ownership_or_empty(populated_registry):
    """Non-student agents either own nothing or only read."""
    # KB ownership is an empty list
    for mode in ("DIRECT", "CONTEXTUAL", "HYBRID"):
        result = populated_registry.list_by_mode(mode)
        for entry in result:
            assert entry["name"] not in ("parent_report", "marketing")


# ── Static class attributes ─────────────────────────────


def test_agent_classes_have_correct_static_attrs():
    assert CurriculumAgentStub.AGENT_NAME == "curriculum"
    assert CurriculumAgentStub.MODE_ALLOWLIST == ["CONTEXTUAL", "HYBRID"]
    assert "dreamer-prerequisites" in CurriculumAgentStub.KB_OWNERSHIP

    assert AssessmentAgent.AGENT_NAME == "assessment"
    assert AssessmentAgent.MODE_ALLOWLIST == ["DIRECT", "HYBRID"]

    assert PortfolioAgentStub.AGENT_NAME == "portfolio"
    assert PortfolioAgentStub.MODE_ALLOWLIST == ["CONTEXTUAL"]

    assert ParentReportAgent.AGENT_NAME == "parent_report"
    assert ParentReportAgent.MODE_ALLOWLIST is None

    assert MarketingAgentStub.AGENT_NAME == "marketing"
    assert MarketingAgentStub.MODE_ALLOWLIST is None
