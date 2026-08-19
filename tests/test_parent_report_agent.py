"""
Dreamer AI Phase 6 — Parent Report Agent unit tests (mock DB, no LLM).

Covers (checklist §1.4):
  - Three period windows: weekly / cycle / journey
  - Two variants: first_steps / standard
  - Empty data → graceful empty report
  - Seven-field envelope contract
  - D3: no deficit-framing label in narrative
  - Safety alerts: pointer-only (event_ref), no raw event_data
  - execute() Hermes wrapper
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agents.parent_report_agent import ParentReportAgent


# ── DB seed helpers ────────────────────────────────────

SCHEMA = """
CREATE TABLE assessment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en',
    internal_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    rubric_id TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '',
    agent_used TEXT NOT NULL DEFAULT 'assessment',
    cost_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE progress_snapshots (
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    mastery_pct REAL NOT NULL DEFAULT 0.0,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    last_label TEXT NOT NULL DEFAULT '',
    streak INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (student_id, topic_id)
);
CREATE TABLE session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en',
    age_band TEXT NOT NULL DEFAULT 'P4-P6',
    agent_list TEXT NOT NULL DEFAULT '',
    topic_ids TEXT NOT NULL DEFAULT '',
    cost_summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE obs_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "parent_report_test.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.close()
    return path


def _seed_log(conn, student_id, topic_id, label, days_ago, mode="DIRECT", session_id="s1"):
    conn.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code, internal_label,
            confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (student_id, session_id, topic_id, mode, "zh-hk", label, 0.8,
         "r1", "ok", "assessment", 100, _iso(days_ago)),
    )


def _seed_session(conn, student_id, days_ago, session_id="s1", mode="DIRECT", topic_ids="t_maths"):
    conn.execute(
        """INSERT INTO session_logs
           (session_id, student_id, mode, lang_code, age_band, agent_list,
            topic_ids, cost_summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (session_id, student_id, mode, "zh-hk", "P4-P6", '["assessment"]',
         topic_ids, '{}', _iso(days_ago)),
    )


def _seed_snapshot(conn, student_id, topic_id, mastery_pct, label, days_ago, attempts=1):
    conn.execute(
        """INSERT INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count, last_label,
            streak, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (student_id, topic_id, mastery_pct, attempts, label, 0, _iso(days_ago)),
    )


def _seed_obs(conn, student_id, event_type, event_data, days_ago):
    conn.execute(
        """INSERT INTO obs_events (student_id, session_id, event_type, event_data, created_at)
           VALUES (?,?,?,?,?)""",
        (student_id, "s1", event_type, json.dumps(event_data), _iso(days_ago)),
    )


# ── Envelope contract ──────────────────────────────────

def test_envelope_contract(db_path):
    """Seven-field envelope always present."""
    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_empty", period="cycle", lang_code="zh-hk")
    for key in ["content", "mode", "lang_code", "age_band", "kid_label",
                "citations", "cost_summary"]:
        assert key in result, f"missing envelope key: {key}"
    assert result["mode"] == "parent_report"
    assert result["lang_code"] == "zh-hk"
    assert result["age_band"] is None
    assert result["kid_label"] is None
    assert isinstance(result["citations"], list)
    assert result["cost_summary"]["status"] in ("ok", "no_data")


# ── Empty data ─────────────────────────────────────────

def test_empty_data_graceful(db_path):
    """No records → empty report, welcome narrative, no crash."""
    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_ghost", period="cycle", lang_code="zh-hk")
    report = result["report"]
    assert report["student_id"] == "stu_ghost"
    assert report["variant"] == "first_steps"
    assert report["summary"]["session_count"] == 0
    assert report["topics"] == []
    assert "歡迎" in result["content"] or "Welcome" in result["content"]
    assert report["period"]["type"] == "cycle"


# ── Variants ───────────────────────────────────────────

def test_first_steps_variant_single_session(db_path):
    """One recent session → first_steps with baseline + roadmap."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_new", "t_maths", "not_yet", 1)
    _seed_session(conn, "stu_new", 1)
    _seed_snapshot(conn, "stu_new", "t_maths", 0.25, "not_yet", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_new", period="cycle", lang_code="zh-hk")
    report = result["report"]
    assert report["variant"] == "first_steps"
    assert report["baseline"] is not None
    assert report["roadmap"] is not None
    assert report["summary"]["session_count"] == 1


def test_standard_variant_established(db_path):
    """Many sessions over long span → standard, no baseline/roadmap."""
    conn = sqlite3.connect(db_path)
    for i in range(6):
        _seed_log(conn, "stu_est", "t_maths", "achieved", 30 + i * 10, session_id=f"s{i}")
        _seed_session(conn, "stu_est", 30 + i * 10, session_id=f"s{i}")
    _seed_snapshot(conn, "stu_est", "t_maths", 0.75, "achieved", 5, attempts=6)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_est", period="journey", lang_code="zh-hk")
    report = result["report"]
    assert report["variant"] == "standard"
    assert report["baseline"] is None
    assert report["roadmap"] is None
    assert report["summary"]["session_count"] >= 4


# ── Period windows ─────────────────────────────────────

def test_weekly_window_filters_old_logs(db_path):
    """Weekly period must exclude logs older than 7 days."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_p", "t_maths", "not_yet", 30)
    _seed_log(conn, "stu_p", "t_maths", "achieved", 2)
    _seed_session(conn, "stu_p", 2)
    _seed_snapshot(conn, "stu_p", "t_maths", 0.75, "achieved", 2)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_p", period="weekly", lang_code="zh-hk")
    report = result["report"]
    assert report["period"]["type"] == "weekly"
    assert report["period"]["days"] == 7
    assert report["summary"]["session_count"] == 1  # only the recent session
    # topics derived from period-filtered logs: old t_maths log excluded,
    # but snapshot still contributes t_maths → topic present, delta from logs only
    assert len(report["topics"]) >= 1


def test_journey_window_span(db_path):
    """Journey period spans from first activity to now."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_j", "t_maths", "not_yet", 25)
    _seed_session(conn, "stu_j", 25)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_j", period="journey", lang_code="zh-hk")
    report = result["report"]
    assert report["period"]["type"] == "journey"
    assert report["period"]["from"] is not None
    assert report["period"]["days"] >= 24  # ~25 days span


# ── Mastery delta (D8-friendly) ────────────────────────

def test_mastery_delta_positive_from_logs(db_path):
    """delta computed from first/last assessment_logs label in window."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_d", "t_maths", "not_yet", 10)
    _seed_log(conn, "stu_d", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_d", 1)
    _seed_snapshot(conn, "stu_d", "t_maths", 0.75, "achieved", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_d", period="cycle", lang_code="zh-hk")
    report = result["report"]
    topics = {t["topic_id"]: t for t in report["topics"]}
    assert topics["t_maths"]["mastery_delta"] > 0  # 0.75 - 0.25 = +0.5


# ── D3 deficit-framing red line ────────────────────────

def test_d3_no_deficit_framing(db_path):
    """Narrative must not contain deficit-framing parent-facing labels."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_d3", "t_maths", "not_yet", 1)
    _seed_session(conn, "stu_d3", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_d3", period="cycle", lang_code="zh-hk")
    content = result["content"]
    for bad in ["尚未達標", "未達標", "Not Yet Achieved", "不及格"]:
        assert bad not in content, f"D3 violation: {bad} in narrative"


# ── Safety alerts pointer-only ─────────────────────────

def test_safety_alerts_pointer_only(db_path):
    """include_safety=True → alerts carry event_ref, never raw data."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_s", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_s", 1)
    _seed_obs(conn, "stu_s", "cost", {"elapsed_ms": 45000}, 1)
    _seed_obs(conn, "stu_s", "safety", {"block_type": "self_harm", "detail": "raw sensitive text"}, 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_s", period="cycle", lang_code="zh-hk",
                                   include_safety=True)
    alerts = result["report"]["safety_alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["type"] == "self_harm"
    assert alert["event_ref"].startswith("obs_")
    assert "detail" not in alert
    assert "raw sensitive text" not in json.dumps(alert)


# ── Duration aggregation ───────────────────────────────

def test_duration_from_cost_events(db_path):
    """total_duration_seconds aggregates cost event elapsed_ms."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_t", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_t", 1)
    _seed_obs(conn, "stu_t", "cost", {"elapsed_ms": 120000}, 1)
    _seed_obs(conn, "stu_t", "cost", {"elapsed_ms": 30000}, 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_t", period="cycle", lang_code="zh-hk")
    assert result["report"]["summary"]["total_duration_seconds"] == 150


def test_cost_summary_tokens_aggregated(db_path):
    """cost_summary.total_tokens aggregates cost event total_tokens (D5)."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_c", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_c", 1)
    _seed_obs(conn, "stu_c", "cost", {"total_tokens": 6283, "elapsed_ms": 17000}, 1)
    _seed_obs(conn, "stu_c", "cost", {"total_tokens": 500, "elapsed_ms": 3000}, 1)
    # Non-cost events and token-less cost events contribute 0
    _seed_obs(conn, "stu_c", "routing", {"matched_keyword": "溫書"}, 1)
    _seed_obs(conn, "stu_c", "cost", {"elapsed_ms": 9000}, 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_c", period="cycle", lang_code="zh-hk")
    assert result["cost_summary"]["status"] == "ok"
    assert result["cost_summary"]["total_tokens"] == 6783


# ── execute() wrapper ──────────────────────────────────

def test_execute_wrapper(db_path):
    """execute() returns Hermes-compatible envelope with report."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_x", "t_maths", "developing", 1)
    _seed_session(conn, "stu_x", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.execute("task_abc", {
        "student_id": "stu_x",
        "period": "cycle",
        "lang_code": "zh-hk",
    })
    assert result["agent"] == "parent_report"
    assert result["task_id"] == "task_abc"
    assert result["status"] == "ok"
    assert "report" in result["result"]
    assert result["result"]["report"]["student_id"] == "stu_x"


def test_execute_missing_student(db_path):
    """execute() with unknown student → graceful empty report."""
    agent = ParentReportAgent(db_path=db_path)
    result = agent.execute("task_xyz", {
        "student_id": "stu_nope",
        "period": "cycle",
        "lang_code": "en",
    })
    assert result["status"] == "ok"
    assert result["result"]["report"]["variant"] == "first_steps"
    assert result["result"]["report"]["summary"]["session_count"] == 0
