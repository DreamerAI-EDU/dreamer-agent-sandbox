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
    duration_seconds INTEGER,
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


def _seed_session(conn, student_id, days_ago, session_id="s1", mode="DIRECT", topic_ids="t_maths", duration_seconds=None):
    conn.execute(
        """INSERT INTO session_logs
           (session_id, student_id, mode, lang_code, age_band, agent_list,
            topic_ids, cost_summary, duration_seconds, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (session_id, student_id, mode, "zh-hk", "P4-P6", '["assessment"]',
         topic_ids, '{}', duration_seconds, _iso(days_ago)),
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


def test_variant_boundary_exact_five_sessions_long_span(db_path):
    """Boundary (D7): exactly 5 sessions + first session ≥14 days ago → standard."""
    conn = sqlite3.connect(db_path)
    # 5 sessions exactly; first one 20 days ago (≥ FIRST_STEPS_MIN_DAYS)
    for i, days_ago in enumerate([20, 10, 5, 2, 0]):
        _seed_log(conn, "stu_b5", "t_maths", "achieved", days_ago, session_id=f"s{i}")
        _seed_session(conn, "stu_b5", days_ago, session_id=f"s{i}")
    _seed_snapshot(conn, "stu_b5", "t_maths", 0.75, "achieved", 5, attempts=5)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_b5", period="journey", lang_code="zh-hk")
    report = result["report"]
    assert report["summary"]["session_count"] == 5
    assert report["variant"] == "standard"
    assert report["baseline"] is None


def test_variant_boundary_five_sessions_short_span(db_path):
    """Boundary (D7): exactly 5 sessions but first session <14 days ago → first_steps."""
    conn = sqlite3.connect(db_path)
    # 5 sessions exactly; first one only 10 days ago (< FIRST_STEPS_MIN_DAYS)
    for i, days_ago in enumerate([10, 5, 2, 1, 0]):
        _seed_log(conn, "stu_b5s", "t_maths", "achieved", days_ago, session_id=f"s{i}")
        _seed_session(conn, "stu_b5s", days_ago, session_id=f"s{i}")
    _seed_snapshot(conn, "stu_b5s", "t_maths", 0.75, "achieved", 5, attempts=5)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_b5s", period="journey", lang_code="zh-hk")
    report = result["report"]
    assert report["summary"]["session_count"] == 5
    assert report["variant"] == "first_steps"
    assert report["baseline"] is not None
    assert report["roadmap"] is not None


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

def test_duration_from_session_logs(db_path):
    """total_duration_seconds aggregates session_logs.duration_seconds."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_t", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_t", 1, duration_seconds=120)
    _seed_session(conn, "stu_t", 1, session_id="s2", duration_seconds=30)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_t", period="cycle", lang_code="zh-hk")
    assert result["report"]["summary"]["total_duration_seconds"] == 150


def test_duration_all_null_is_no_data(db_path):
    """D7 spot check: all session durations NULL → no_data, NOT silent 0."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_d7", "t_maths", "achieved", 1)
    # legacy rows: no duration recorded
    _seed_session(conn, "stu_d7", 1)
    _seed_session(conn, "stu_d7", 1, session_id="s2")
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_d7", period="cycle", lang_code="zh-hk")
    assert result["report"]["summary"]["total_duration_seconds"] is None


def test_duration_mixed_null_and_value(db_path):
    """Partial NULL: sum only rows with recorded duration."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_d7m", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_d7m", 1)  # legacy NULL
    _seed_session(conn, "stu_d7m", 1, session_id="s2", duration_seconds=90)
    _seed_session(conn, "stu_d7m", 1, session_id="s3", duration_seconds=10)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_d7m", period="cycle", lang_code="zh-hk")
    assert result["report"]["summary"]["total_duration_seconds"] == 100


def test_session_logs_duration_migration_idempotent(monkeypatch, tmp_path):
    """ALTER TABLE ADD COLUMN duration_seconds runs twice without throw."""
    import agents.hermes_scheduler as hs

    # legacy DB with old schema (no duration_seconds)
    db = tmp_path / "migrate_dur.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT '',
            lang_code TEXT NOT NULL DEFAULT '',
            age_band TEXT NOT NULL DEFAULT '',
            agent_list TEXT NOT NULL DEFAULT '[]',
            topic_ids TEXT NOT NULL DEFAULT '[]',
            cost_summary TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    monkeypatch.setenv("DREAMER_DB_PATH", str(db))
    old_flag = hs._SESSION_LOGS_TABLE_ENSURED
    try:
        # first run adds the column
        hs._SESSION_LOGS_TABLE_ENSURED = False
        hs._ensure_session_logs_table()
        conn = sqlite3.connect(str(db))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(session_logs)")]
        conn.close()
        assert "duration_seconds" in cols

        # second run must not throw (idempotent)
        hs._SESSION_LOGS_TABLE_ENSURED = False
        hs._ensure_session_logs_table()
        conn = sqlite3.connect(str(db))
        cols2 = [r[1] for r in conn.execute("PRAGMA table_info(session_logs)")]
        conn.close()
        assert cols2.count("duration_seconds") == 1
    finally:
        hs._SESSION_LOGS_TABLE_ENSURED = old_flag
        monkeypatch.delenv("DREAMER_DB_PATH", raising=False)


def test_write_session_log_persists_duration(monkeypatch, tmp_path):
    """New session rows carry real duration_seconds."""
    import agents.hermes_scheduler as hs

    db = str(tmp_path / "write_dur.db")
    monkeypatch.setenv("DREAMER_DB_PATH", db)
    old_flag = hs._SESSION_LOGS_TABLE_ENSURED
    try:
        hs._SESSION_LOGS_TABLE_ENSURED = False
        hs._write_session_log(
            session_id="s_dur", student_id="stu_w",
            mode="DIRECT", lang_code="zh-hk", age_band="P4-P6",
            agent_list=["assessment"], topic_ids=["t_maths"],
            cost_summary={"total_tokens": 100}, duration_seconds=42,
        )
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT duration_seconds FROM session_logs WHERE session_id='s_dur'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 42
    finally:
        hs._SESSION_LOGS_TABLE_ENSURED = old_flag
        monkeypatch.delenv("DREAMER_DB_PATH", raising=False)


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


def test_cost_summary_all_tokenless_is_no_data(db_path):
    """D5 spot check: all cost events token-less → status=no_data, NOT silent 0."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_c0", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_c0", 1)
    # cost events exist but carry no total_tokens
    _seed_obs(conn, "stu_c0", "cost", {"elapsed_ms": 9000}, 1)
    _seed_obs(conn, "stu_c0", "cost", {"elapsed_ms": 3000}, 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_c0", period="cycle", lang_code="zh-hk")
    assert result["cost_summary"]["status"] == "no_data"
    assert result["cost_summary"]["total_tokens"] == 0


def test_cost_summary_no_cost_events_is_no_data(db_path):
    """D5 spot check: no cost events at all → status=no_data."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_c1", "t_maths", "achieved", 1)
    _seed_session(conn, "stu_c1", 1)
    _seed_obs(conn, "stu_c1", "routing", {"matched_keyword": "溫書"}, 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_c1", period="cycle", lang_code="zh-hk")
    assert result["cost_summary"]["status"] == "no_data"
    assert result["cost_summary"]["total_tokens"] == 0


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


# ── Narrative numeric fixes (Day 27) ───────────────────

def test_narrative_mastery_pct_50_percent(db_path):
    """Regression: 0-1 mastery float must render as 50%, not int() truncated 0%."""
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_pct", "t_maths", "developing", 1)
    _seed_session(conn, "stu_pct", 1)
    _seed_snapshot(conn, "stu_pct", "t_maths", 0.5, "developing", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_pct", period="cycle", lang_code="zh-hk")
    content = result["content"]
    assert "掌握度約 50%" in content, f"expected 50% display, got: {content!r}"
    assert "掌握度約 0%" not in content


def test_narrative_mastery_delta_50_points(db_path):
    """Regression: mastery_delta 0.5 must render as 上升50個百分點, not 0."""
    conn = sqlite3.connect(db_path)
    # Standard variant: ≥5 sessions, first ≥14 days ago; not_yet → achieved = +0.5
    for i, days_ago in enumerate([60, 45, 30, 15, 5, 1]):
        _seed_log(conn, "stu_dlt", "t_maths",
                  "not_yet" if i == 0 else "achieved", days_ago,
                  session_id=f"s{i}")
        _seed_session(conn, "stu_dlt", days_ago, session_id=f"s{i}")
    _seed_snapshot(conn, "stu_dlt", "t_maths", 0.75, "achieved", 1, attempts=6)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_dlt", period="journey", lang_code="zh-hk")
    assert result["report"]["variant"] == "standard"
    topics = {t["topic_id"]: t for t in result["report"]["topics"]}
    assert topics["t_maths"]["mastery_delta"] == 0.5
    assert "上升 50 個百分點" in result["content"], result["content"]


def test_round_half_up_quarter(db_path):
    """Regression: 0.25 must round half-up to 0.3 (not banker's 0.2)."""
    from agents.parent_report_agent import _round_half_up
    assert _round_half_up(0.25, 1) == 0.3
    assert _round_half_up(0.35, 1) == 0.4
    assert _round_half_up(0.05, 1) == 0.1
    assert _round_half_up(0.15, 1) == 0.2

    # Surface-level: snapshot mastery 0.25 → topics[0].mastery_pct == 0.3
    conn = sqlite3.connect(db_path)
    _seed_log(conn, "stu_rhu", "t_maths", "not_yet", 1)
    _seed_session(conn, "stu_rhu", 1)
    _seed_snapshot(conn, "stu_rhu", "t_maths", 0.25, "not_yet", 1)
    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)
    result = agent.generate_report("stu_rhu", period="cycle", lang_code="zh-hk")
    topics = {t["topic_id"]: t for t in result["report"]["topics"]}
    assert topics["t_maths"]["mastery_pct"] == 0.3
