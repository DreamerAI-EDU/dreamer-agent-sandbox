"""
Dreamer AI Phase 2.1 — Sub Agent Stubs
Placeholder agent classes for registry wiring.
Full LLM integration deferred to Phase 4 (Mode Routing).

Non-student-facing agents (ParentReport, Marketing) register with
mode_allowlist=None and use different invocation paths.
"""

from typing import Dict, Optional


class CurriculumAgentStub:
    """Student-facing: designs lesson plans and curriculum navigation.

    KB owner: dreamer-maths/english/computing/science/psd/life_skills/l2l/history
              + dreamer-prerequisites (Curriculum Navigator sub-role)
    Modes: CONTEXTUAL, HYBRID
    """

    AGENT_NAME = "curriculum"
    KB_OWNERSHIP = [
        "dreamer-maths", "dreamer-english", "dreamer-computing",
        "dreamer-science", "dreamer-psd", "dreamer-life_skills",
        "dreamer-l2l", "dreamer-history", "dreamer-prerequisites",
    ]
    CAPABILITIES = ["lesson_plan", "curriculum_nav", "topic_design", "prerequisite_check"]
    MODE_ALLOWLIST = ["CONTEXTUAL", "HYBRID"]

    def execute(self, task_id: str, params: Dict) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": f"[CurriculumAgent stub] params={params}",
            "mode": params.get("mode", "CONTEXTUAL"),
            "grade_level": params.get("grade_level", 1),
        }


class AssessmentAgentStub:
    """Student-facing: generates assessments, quizzes, and rubrics.

    KB reader: dreamer-maths/english/computing/science/l2l
    KB owner: dreamer-rubrics
    Modes: DIRECT, HYBRID
    """

    AGENT_NAME = "assessment"
    KB_OWNERSHIP = ["dreamer-rubrics"]
    KBS_READ = [
        "dreamer-maths", "dreamer-english", "dreamer-computing",
        "dreamer-science", "dreamer-l2l",
    ]
    CAPABILITIES = ["quiz_gen", "rubric_gen", "auto_marking", "progress_track"]
    MODE_ALLOWLIST = ["DIRECT", "HYBRID"]

    def execute(self, task_id: str, params: Dict) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": f"[AssessmentAgent stub] params={params}",
            "mode": params.get("mode", "DIRECT"),
            "grade_level": params.get("grade_level", 1),
        }


class PortfolioAgentStub:
    """Student-facing: manages student portfolio and reflections.

    KB reader: dreamer-psd/life_skills
    KB owner: dreamer-portfolio
    Modes: CONTEXTUAL
    """

    AGENT_NAME = "portfolio"
    KB_OWNERSHIP = ["dreamer-portfolio"]
    KBS_READ = ["dreamer-psd", "dreamer-life_skills"]
    CAPABILITIES = ["portfolio_mgmt", "reflection_prompt", "artifact_curate"]
    MODE_ALLOWLIST = ["CONTEXTUAL"]

    def execute(self, task_id: str, params: Dict) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": f"[PortfolioAgent stub] params={params}",
            "mode": params.get("mode", "CONTEXTUAL"),
            "grade_level": params.get("grade_level", 1),
        }


class ParentReportAgentStub:
    """Non-student-facing: generates parent-facing progress reports.

    Queries Dreamer DB only (not DeepTutor).
    Read-only on portfolio KB.
    mode_allowlist=None — no student-query routing.
    """

    AGENT_NAME = "parent_report"
    KB_OWNERSHIP: list = []
    KBS_READ = ["dreamer-portfolio"]
    CAPABILITIES = ["report_gen", "db_query", "progress_summary"]
    MODE_ALLOWLIST = None  # non-student-facing

    def execute(self, task_id: str, params: Dict) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": f"[ParentReportAgent stub] params={params}",
        }


class MarketingAgentStub:
    """Non-student-facing: generates social media / marketing content.

    KB reader: dreamer-computing/science
    Social content only.
    mode_allowlist=None — no student-query routing.
    """

    AGENT_NAME = "marketing"
    KB_OWNERSHIP: list = []
    KBS_READ = ["dreamer-computing", "dreamer-science"]
    CAPABILITIES = ["social_content", "campaign_brief", "brand_copy"]
    MODE_ALLOWLIST = None  # non-student-facing

    def execute(self, task_id: str, params: Dict) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": f"[MarketingAgent stub] params={params}",
        }


# ── Registry helper ────────────────────────────────────

def register_all(registry) -> None:
    """Register all Phase 2.1 agent stubs into the given registry."""
    registry.register(
        CurriculumAgentStub.AGENT_NAME,
        CurriculumAgentStub,
        kb_ownership=CurriculumAgentStub.KB_OWNERSHIP,
        capabilities=CurriculumAgentStub.CAPABILITIES,
        mode_allowlist=CurriculumAgentStub.MODE_ALLOWLIST,
    )
    registry.register(
        AssessmentAgentStub.AGENT_NAME,
        AssessmentAgentStub,
        kb_ownership=AssessmentAgentStub.KB_OWNERSHIP,
        capabilities=AssessmentAgentStub.CAPABILITIES,
        mode_allowlist=AssessmentAgentStub.MODE_ALLOWLIST,
    )
    registry.register(
        PortfolioAgentStub.AGENT_NAME,
        PortfolioAgentStub,
        kb_ownership=PortfolioAgentStub.KB_OWNERSHIP,
        capabilities=PortfolioAgentStub.CAPABILITIES,
        mode_allowlist=PortfolioAgentStub.MODE_ALLOWLIST,
    )
    registry.register(
        ParentReportAgentStub.AGENT_NAME,
        ParentReportAgentStub,
        kb_ownership=ParentReportAgentStub.KB_OWNERSHIP,
        capabilities=ParentReportAgentStub.CAPABILITIES,
        mode_allowlist=ParentReportAgentStub.MODE_ALLOWLIST,
    )
    registry.register(
        MarketingAgentStub.AGENT_NAME,
        MarketingAgentStub,
        kb_ownership=MarketingAgentStub.KB_OWNERSHIP,
        capabilities=MarketingAgentStub.CAPABILITIES,
        mode_allowlist=MarketingAgentStub.MODE_ALLOWLIST,
    )
