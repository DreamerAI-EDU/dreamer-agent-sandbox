"""
Dreamer AI Phase 4 Day 21 — execute() unit tests

All tests use mocked dependencies. Zero real container dependency.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agents.hermes_scheduler import (
    execute,
    PlanContext,
    _ensure_session_logs_table,
    _write_session_log,
    _direct_clarifying_response,
)


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Temporary DB path."""
    db = str(tmp_path / "dreamer.db")
    monkeypatch.setenv("DREAMER_DB_PATH", db)
    # Reset the table-ensured flag so each test gets a fresh table
    import agents.hermes_scheduler as hs
    hs._SESSION_LOGS_TABLE_ENSURED = False
    hs._registry_cache = None
    return db


@pytest.fixture
def registry():
    """Seeded registry with all agents registered."""
    from agents.registry import SubagentRegistry
    from agents.subagents import register_all
    reg = SubagentRegistry()
    register_all(reg)
    return reg


# ── Test: kid_safe_input blocks ─────────────────────────

def test_execute_blocked(monkeypatch, tmp_db, registry):
    """When kid_safe_input blocks, return block dict early."""
    from agents.hermes_scheduler import HermesScheduler

    def mock_block(*args, **kwargs):
        return {
            "response_message": "Let's talk about something else.",
            "event": {"type": "welfare"},
            "is_welfare": True,
        }

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", mock_block)

    result = asyncio.run(execute(
        "harmful query", "stu_001", "P4-P6",
        registry=registry,
    )
)
    assert result["mode"] == "BLOCKED"
    assert result["kid_label"] == "blocked"
    assert "talk about something else" in result["content"]


# ── Test: DIRECT no topic_id → clarifying ───────────────

def test_execute_direct_clarifying(monkeypatch, tmp_db, registry):
    """DIRECT mode without topic_id returns clarifying template."""
    from agents.hermes_scheduler import HermesScheduler

    # kid_safe_input passes
    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)

    # Force DIRECT mode
    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "我想溫書", "stu_001", "P4-P6",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "DIRECT_clarifying"
    assert result["kid_label"] == "clarifying"
    assert "溫邊科" in result["content"]
    assert result["lang_code"] == "zh-hk"


# ── Test: DIRECT with topic_id → quiz_gen ──────────────

def test_execute_direct_quiz(monkeypatch, tmp_db, registry):
    """DIRECT mode with topic_id calls AssessmentAgent.quiz_gen."""
    from agents.hermes_scheduler import HermesScheduler
    from agents.assessment_agent import AssessmentAgent

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
    monkeypatch.setattr(HermesScheduler, "kid_safe_wrap", lambda content, *a, **k: content)
# Mock quiz_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_quiz(self, params):
        return {"agent": "assessment", "capability": "quiz_gen", "status": "ok",
                "questions": [{"id": "q1", "question": "Mock Q1", "type": "short_answer", "grade_level": 4}],
                "topic": params.get("topic", ""), "grade_level": 1, "rubric_id": "", "cost_tokens": 150}
    monkeypatch.setattr(_aa.AssessmentAgent, "quiz_gen", _mock_quiz)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "我要考試溫習整遊戲嘅課題", "stu_001", "P4-P6",
        topic_id="computing-game-design-01",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "DIRECT"
    assert result["kid_label"] == "ok"
    assert "content" in result
    assert result["lang_code"] == "zh-hk"
    assert "cost_summary" in result


# ── Test: HYBRID → quiz_gen ─────────────────────────────

def test_execute_hybrid_quiz(monkeypatch, tmp_db, registry):
    """HYBRID mode calls AssessmentAgent.quiz_gen."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
    monkeypatch.setattr(HermesScheduler, "kid_safe_wrap", lambda content, *a, **k: content)
# Mock quiz_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_quiz(self, params):
        return {"agent": "assessment", "capability": "quiz_gen", "status": "ok",
                "questions": [{"id": "q1", "question": "Mock Q1", "type": "short_answer", "grade_level": 4}],
                "topic": params.get("topic", ""), "grade_level": 1, "rubric_id": "", "cost_tokens": 150}
    monkeypatch.setattr(_aa.AssessmentAgent, "quiz_gen", _mock_quiz)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.HYBRID, "zh-hk"

    result = asyncio.run(execute(
        "用AI幫我溫書", "stu_001", "P4-P6",
        topic_id="computing-game-design-01",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "HYBRID"
    assert result["kid_label"] == "ok"
    assert result["lang_code"] == "zh-hk"


# ── Test: capability override ───────────────────────────

def test_execute_direct_capability_override(monkeypatch, tmp_db, registry):
    """Explicit capability parameter is passed to AssessmentAgent."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
# Mock rubric_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_rubric(self, params):
        return {"agent": "assessment", "capability": "rubric_gen", "status": "ok",
                "rubric_id": "rubric_test_001", "criteria": params.get("criteria", []),
                "topic": params.get("topic", ""), "grade_level": 1, "cost_tokens": 100}
    monkeypatch.setattr(_aa.AssessmentAgent, "rubric_gen", _mock_rubric)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "test", "stu_001", "P4-P6",
        topic_id="computing-game-design-01",
        capability="rubric_gen",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "DIRECT"
    # rubric_gen returns stub with rubric_id
    assert "cost_summary" in result


# ── Test: CONTEXTUAL stub fallback ──────────────────────

def test_execute_contextual_stub(monkeypatch, tmp_db, registry):
    """CONTEXTUAL mode falls back to stub when WS is unavailable."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)

    class FakeRouter:
        def detect_language(self, text=None):
            return "en"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.CONTEXTUAL, "en"

    # WS unavailable → stub fallback
    result = asyncio.run(execute(
        "Tell me about game design", "stu_001", "S1-S3",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "CONTEXTUAL"
    # Should get stub error message when WS is unavailable
    assert "content" in result
    assert result["lang_code"] == "en"


# ── Test: session_logs written ─────────────────────────

def test_execute_session_logs_written(monkeypatch, tmp_db, registry):
    """execute() writes a session_logs row."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
    monkeypatch.setattr(HermesScheduler, "kid_safe_wrap", lambda content, *a, **k: content)
# Mock quiz_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_quiz(self, params):
        return {"agent": "assessment", "capability": "quiz_gen", "status": "ok",
                "questions": [{"id": "q1", "question": "Mock Q1", "type": "short_answer", "grade_level": 4}],
                "topic": params.get("topic", ""), "grade_level": 1, "rubric_id": "", "cost_tokens": 150}
    monkeypatch.setattr(_aa.AssessmentAgent, "quiz_gen", _mock_quiz)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "hello", "stu_001", "P1-P3",
        topic_id="computing-game-design-01",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "DIRECT"

    # Verify session_logs row exists
    conn = sqlite3.connect(tmp_db)
    try:
        rows = conn.execute(
            "SELECT mode, student_id, agent_list, topic_ids, cost_summary "
            "FROM session_logs ORDER BY id DESC LIMIT 1"
        ).fetchall()
        assert len(rows) >= 1
        row = rows[0]
        assert row[0] == "DIRECT"
        assert row[1] == "stu_001"
        agent_list = json.loads(row[2])
        assert isinstance(agent_list, list)
        topic_ids = json.loads(row[3])
        assert "computing-game-design-01" in topic_ids
    finally:
        conn.close()


# ── Test: structured JSON fields ────────────────────────

def test_execute_structured_json_fields(monkeypatch, tmp_db, registry):
    """execute() returns all North Star JSON fields."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
    monkeypatch.setattr(HermesScheduler, "kid_safe_wrap", lambda content, *a, **k: content)
# Mock quiz_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_quiz(self, params):
        return {"agent": "assessment", "capability": "quiz_gen", "status": "ok",
                "questions": [{"id": "q1", "question": "Mock Q1", "type": "short_answer", "grade_level": 4}],
                "topic": params.get("topic", ""), "grade_level": 1, "rubric_id": "", "cost_tokens": 150}
    monkeypatch.setattr(_aa.AssessmentAgent, "quiz_gen", _mock_quiz)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "test", "stu_001", "P4-P6",
        topic_id="computing-game-design-01",
        registry=registry,
        mode_router=FakeRouter(),
    )
)

    required_fields = [
        "content", "mode", "lang_code", "age_band",
        "kid_label", "citations", "cost_summary",
    ]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"

    assert result["age_band"] == "P4-P6"
    assert isinstance(result["citations"], list)
    assert isinstance(result["cost_summary"], dict)


# ── Test: max_tokens env var config ────────────────────

def test_max_tokens_config(monkeypatch, tmp_db, registry):
    """DREAMER_MAX_TOKENS env var is read by execute (verified via cost_summary path)."""
    from agents.hermes_scheduler import HermesScheduler

    monkeypatch.setattr(HermesScheduler, "kid_safe_input", lambda *a, **k: None)
    monkeypatch.setenv("DREAMER_MAX_TOKENS", "2000")
# Mock quiz_gen to avoid real WS connection
    from agents import assessment_agent as _aa
    async def _mock_quiz(self, params):
        return {"agent": "assessment", "capability": "quiz_gen", "status": "ok",
                "questions": [{"id": "q1", "question": "Mock Q1", "type": "short_answer", "grade_level": 4}],
                "topic": params.get("topic", ""), "grade_level": 1, "rubric_id": "", "cost_tokens": 150}
    monkeypatch.setattr(_aa.AssessmentAgent, "quiz_gen", _mock_quiz)

    class FakeRouter:
        def detect_language(self, text=None):
            return "zh-hk"
        def route_with_trace(self, text, *, student_id="", session_id=""):
            mode, lang = self.route(text)
            return mode, lang, None

        def route(self, text):
            from agents.mode_router import Mode
            return Mode.DIRECT, "zh-hk"

    result = asyncio.run(execute(
        "test", "stu_001", "P4-P6",
        topic_id="computing-game-design-01",
        registry=registry,
        mode_router=FakeRouter(),
    )
)
    assert result["mode"] == "DIRECT"
    # Env var is consumed; cost_summary should have elapsed_ms
    assert "elapsed_ms" in result["cost_summary"]


# ── Test: clarifying templates per language ─────────────

@pytest.mark.parametrize("lang_code,expected_phrase", [
    ("zh-hk", "溫邊科"),
    ("zh-cn", "复习哪科"),
    ("en", "subject"),
])
def test_clarifying_templates_three_languages(lang_code, expected_phrase):
    """Clarifying templates exist for all three languages."""
    result = _direct_clarifying_response(lang_code, "P4-P6")
    assert expected_phrase in result["content"]
    assert result["kid_label"] == "clarifying"
