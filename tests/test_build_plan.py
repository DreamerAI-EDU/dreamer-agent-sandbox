"""
Dreamer AI Phase 4 Day 20 — build_plan() integration tests

Test cases:
  1. 不同 input → 正確 mode + agent list + kb_list
  2. topic_id 提供時 navigator kb_list + prereq_gaps 正確
  3. age_band validation fail-fast
  4. full PlanContext structure

All tests use fake DB + fake config. Zero real container dependency.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agents.hermes_scheduler import PlanContext, build_plan
from agents.registry import SubagentRegistry
from agents.subagents import register_all
from agents.mode_router import ModeRouter
from agents.curriculum_navigator import (
    CurriculumNavigator,
    ETHICAL_AI_KB,
    validate_age_band,
)


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
def registry():
    """Seeded registry with all agents registered."""
    reg = SubagentRegistry()
    register_all(reg)
    return reg


@pytest.fixture
def router():
    return ModeRouter()


@pytest.fixture
def seeded_db(tmp_path):
    """Seeded in-memory DB for topic_metadata + progress_snapshots."""
    db = str(tmp_path / "test_plan.db")
    conn = sqlite3.connect(db)
    try:
        # topic_metadata
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS topic_metadata (
                topic_id      TEXT PRIMARY KEY,
                subject       TEXT NOT NULL,
                grade_level   TEXT NOT NULL,
                prerequisites TEXT NOT NULL DEFAULT '[]',
                kb_list       TEXT NOT NULL DEFAULT '[]',
                created_at    TEXT NOT NULL DEFAULT ''
            );
        """)
        conn.execute(
            "INSERT OR REPLACE INTO topic_metadata "
            "(topic_id, subject, grade_level, prerequisites, kb_list) "
            "VALUES (?,?,?,?,?)",
            (
                "maths-fractions-01", "Mathematics", "P4-P6",
                json.dumps(["maths-numbers-01"]),
                json.dumps(["dreamer-maths-ai"]),
            ),
        )
        # progress_snapshots
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS progress_snapshots (
                student_id    TEXT NOT NULL,
                topic_id      TEXT NOT NULL,
                mastery_pct   REAL NOT NULL DEFAULT 0.0,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                last_label    TEXT NOT NULL DEFAULT '',
                streak        INTEGER NOT NULL DEFAULT 0,
                updated_at    TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (student_id, topic_id)
            );
        """)
        conn.execute(
            "INSERT OR REPLACE INTO progress_snapshots "
            "(student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("student-alice", "maths-numbers-01", 0.50, 2, "Developing", 0, "2025-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def navigator(seeded_db):
    return CurriculumNavigator(db_path=seeded_db)


# ═══════════════════════════════════════════════════════════
# Basic plan() routing tests
# ═══════════════════════════════════════════════════════════

class TestBuildPlanRouting:
    """Different inputs → correct mode + agent list."""

    def test_direct_mode_from_exam_query(self, registry, router):
        plan = build_plan(
            "我要溫書準備測驗", "student-1", "P4-P6",
            registry=registry, mode_router=router,
        )
        assert plan.mode == "DIRECT"
        assert plan.lang_code == "zh-hk"
        assert plan.age_band == "P4-P6"

    def test_contextual_mode_from_project_query(self, registry, router):
        plan = build_plan(
            "我想做一個AI project來解決水污染問題",
            "student-2", "S1-S3",
            registry=registry, mode_router=router,
        )
        assert plan.mode == "CONTEXTUAL"
        assert plan.lang_code == "zh-hk"

    def test_hybrid_mode(self, registry, router):
        plan = build_plan(
            "Teach me about AI ethics and how to design a chatbot",
            "student-3", "P4-P6",
            registry=registry, mode_router=router,
        )
        assert plan.mode == "HYBRID"

    def test_agent_list_contains_expected_agents(self, registry, router):
        plan = build_plan(
            "我要溫書準備考試", "student-1", "P4-P6",
            registry=registry, mode_router=router,
        )
        # DIRECT mode: curriculum agent NOT in allowlist -> only assessment
        assert len(plan.agent_list) >= 1
        agent_names = set(plan.agent_list)
        assert "assessment" in agent_names
        # curriculum is CONTEXTUAL/HYBRID only → should not appear in DIRECT
        assert "curriculum" not in agent_names

    def test_hybrid_agents_include_both(self, registry, router):
        plan = build_plan(
            "Design an AI project and explain exam concepts",
            "student-1", "S1-S3",
            registry=registry, mode_router=router,
        )
        agent_names = set(plan.agent_list)
        assert "assessment" in agent_names
        assert "curriculum" in agent_names


class TestBuildPlanKBList:
    """KB list correctness: ethical-ai always, topic-specific when topic_id given."""

    def test_no_topic_id_defaults_to_ethical_only(self, registry, router):
        plan = build_plan(
            "我想溫書準備測驗", "student-1", "P4-P6",
            registry=registry, mode_router=router,
        )
        assert plan.kb_list == [ETHICAL_AI_KB]
        assert plan.prereq_gaps == []

    def test_with_topic_id_resolves_kb_list(self, registry, router, navigator):
        plan = build_plan(
            "我想做分數練習", "student-alice", "P4-P6",
            topic_id="maths-fractions-01",
            registry=registry, mode_router=router, navigator=navigator,
        )
        assert ETHICAL_AI_KB in plan.kb_list
        assert "dreamer-maths-ai" in plan.kb_list

    def test_direct_mode_keeps_all_kbs(self, registry, router, navigator):
        """B21 §1: FILTER_IN_DIRECT is empty (psd/life_skills have no manifest
        counterpart) — DIRECT no longer drops any kb."""
        # Seed a topic with several kbs
        conn = sqlite3.connect(navigator._db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS topic_metadata (
                    topic_id      TEXT PRIMARY KEY,
                    subject       TEXT NOT NULL,
                    grade_level   TEXT NOT NULL,
                    prerequisites TEXT NOT NULL DEFAULT '[]',
                    kb_list       TEXT NOT NULL DEFAULT '[]',
                    created_at    TEXT NOT NULL DEFAULT ''
                );
            """)
            conn.execute(
                "INSERT OR REPLACE INTO topic_metadata "
                "(topic_id, subject, grade_level, prerequisites, kb_list) "
                "VALUES (?,?,?,?,?)",
                ("psd-exam-01", "PSD", "S1-S3", "[]",
                 json.dumps(["dreamer-coding-python", "dreamer-game-design",
                             "dreamer-maths-ai"])),
            )
            conn.commit()
        finally:
            conn.close()
        plan = build_plan(
            "PSD考試準備", "student-1", "S1-S3",
            topic_id="psd-exam-01",
            registry=registry, mode_router=router, navigator=navigator,
        )
        assert plan.mode == "DIRECT"
        assert "dreamer-coding-python" in plan.kb_list
        assert "dreamer-game-design" in plan.kb_list
        assert "dreamer-maths-ai" in plan.kb_list
        assert ETHICAL_AI_KB in plan.kb_list


class TestBuildPlanPrereqGaps:
    """prereq_gaps only populated when topic_id provided."""

    def test_prereq_gaps_with_topic(self, registry, router, navigator):
        plan = build_plan(
            "分數練習", "student-alice", "P4-P6",
            topic_id="maths-fractions-01",
            registry=registry, mode_router=router, navigator=navigator,
        )
        # Alice has maths-numbers-01 = Developing → 1 gap
        assert len(plan.prereq_gaps) == 1
        assert plan.prereq_gaps[0]["topic_id"] == "maths-numbers-01"

    def test_prereq_gaps_empty_when_no_topic(self, registry, router):
        plan = build_plan(
            "分數練習", "student-alice", "P4-P6",
            registry=registry, mode_router=router,
        )
        assert plan.prereq_gaps == []


class TestBuildPlanAgeBandValidation:
    """age_band validation fail-fast."""

    def test_invalid_age_band_raises(self, registry, router):
        with pytest.raises(ValueError, match="Invalid age_band"):
            build_plan(
                "test", "student-1", "P7",
                registry=registry, mode_router=router,
            )

    def test_valid_age_band_accepted(self, registry, router):
        for band in ("P1-P3", "P4-P6", "S1-S3"):
            plan = build_plan(
                "test", "student-1", band,
                registry=registry, mode_router=router,
            )
            assert plan.age_band == band


class TestPlanContextValidation:
    """PlanContext post_init validation."""

    def test_valid_plan_context(self):
        pc = PlanContext(
            mode="DIRECT", lang_code="zh-hk", age_band="P4-P6",
            agent_list=["assessment"], kb_list=[ETHICAL_AI_KB],
        )
        assert pc.mode == "DIRECT"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            PlanContext(
                mode="INVALID", lang_code="en", age_band="P4-P6",
                agent_list=[], kb_list=[],
            )

    def test_invalid_lang_code_raises(self):
        with pytest.raises(ValueError, match="Invalid lang_code"):
            PlanContext(
                mode="DIRECT", lang_code="fr", age_band="P4-P6",
                agent_list=[], kb_list=[],
            )

    def test_invalid_age_band_raises(self):
        """PlanContext direct construction bypasses build_plan() → must validate."""
        with pytest.raises(ValueError, match="Invalid age_band"):
            PlanContext(
                mode="DIRECT", lang_code="en", age_band="K1-K3",
                agent_list=[], kb_list=[],
            )


class TestBuildPlanNoRegistryRaises:
    def test_no_registry_raises_runtime_error(self, router):
        with pytest.raises(RuntimeError, match="SubagentRegistry"):
            build_plan(
                "test", "student-1", "P4-P6",
                mode_router=router,
            )
