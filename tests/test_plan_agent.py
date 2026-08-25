"""
Dreamer AI Phase 7 — Plan Agent unit tests (D11 Plan-Proposal Flow v1.1).

Covers (spec §8 checklist):
  - Schema freeze: 7-field envelope + plan fields + len(weeks)==duration_weeks
  - Topic hallucination hard gate (inject fake topic → reject → regenerate →
    error template)
  - Idempotency: repeated generation → old pending superseded (one pending only)
  - 4D coverage missing → rejected
  - parent_summary label leak negative (parametrized internal markers)
  - Adjustment mechanism: used hard gate / frozen completed weeks / reject does
    not consume the adjustment budget
  - Student visibility: pending / rejected invisible; approved visible
  - Trilingual generation (zh-hk / zh-cn / en)
  - duration_weeks non-8 case (4-week trial)

No LLM: generator is injected or stub fallback is used.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agents.plan_agent import PlanAgent, VALID_4D, SCHEMA_SQL


# ── DB schema (superset of what plan_agent touches) ─────────

SCHEMA = """
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
"""

TOPIC_POOL = {
    **{f"dreamer-maths-ai-t{i:02d}": "dreamer-maths-ai" for i in range(1, 5)},
    **{f"dreamer-coding-python-t{i:02d}": "dreamer-coding-python" for i in range(1, 5)},
}
STUDENT = "student-001"


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "plan_agent_test.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        """INSERT INTO session_logs
           (session_id, student_id, mode, lang_code, age_band, agent_list,
            topic_ids, cost_summary, duration_seconds, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("s1", STUDENT, "DIRECT", "zh-hk", "P4-P6", '["assessment"]',
         "dreamer-maths-ai-t01", "{}", 600, _iso(1)),
    )
    conn.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code, internal_label,
            confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (STUDENT, "s1", "dreamer-maths-ai-t01", "DIRECT", "zh-hk", "Developing",
         0.6, "rubric_x", "good progress", "assessment", 100, _iso(1)),
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def agent(db_path):
    return PlanAgent(
        db_path=db_path,
        topic_pool=dict(TOPIC_POOL),
    )


def _stub_based_generator(agent: PlanAgent, mutate) -> callable:
    """Build an injectable LLM generator: real stub plan + caller mutation."""
    def gen(context):
        plan = agent._stub_plan(
            context["student_id"], context["profile"],
            context["duration_weeks"], context["cycle_label"],
        )
        mutate(plan, context)
        return plan
    return gen


def _count_status(db_path, student_id, status):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM plan_proposals WHERE student_id=? AND status=?",
            (student_id, status),
        ).fetchone()[0]
    finally:
        conn.close()


def _all_topic_ids(plan):
    out = []
    for w in plan.get("weeks", []):
        out.extend(w.get("topic_ids") or [])
    return out


# ── 1. Schema freeze ───────────────────────────────────────

def test_envelope_and_plan_schema_frozen(agent):
    res = agent.execute("t1", {"student_id": STUDENT})
    assert res["status"] == "ok"
    result = res["result"]
    # 7-field envelope
    for key in ("content", "mode", "lang_code", "age_band", "kid_label",
                "citations", "cost_summary"):
        assert key in result
    assert result["mode"] == "plan_proposal"
    plan = result["plan"]
    for key in ("plan_id", "version", "student_id", "created_at", "status",
                "lang_code", "age_band", "duration_weeks", "cycle_label",
                "weeks", "parent_summary", "baseline_ref", "cost_summary",
                "review", "adjustment"):
        assert key in plan
    assert plan["status"] == "pending_review"
    assert len(plan["weeks"]) == plan["duration_weeks"] == 8
    assert plan["version"] == 1
    assert plan["age_band"] == "P4-P6"
    assert plan["lang_code"] == "zh-hk"
    assert plan["review"]["decided_by_role"] == "teacher"
    assert plan["adjustment"]["used"] is False


# ── 2. Topic hallucination hard gate ────────────────────────

def test_topic_hallucination_hard_gate(db_path, agent):
    def mutate(plan, ctx):
        plan["weeks"][0]["topic_ids"] = ["fake-topic-999"]
    agent._generator = _stub_based_generator(agent, mutate)
    res = agent.execute("t2", {"student_id": STUDENT})
    assert res["status"] == "ok"
    plan = res["result"]["plan"]
    # rejected twice → error template
    assert plan.get("generation_note") == "error_template"
    for tid in _all_topic_ids(plan):
        assert tid in TOPIC_POOL, f"topic escaped gate: {tid}"


# ── 3. Idempotency ──────────────────────────────────────────

def test_idempotent_single_pending(agent, db_path):
    r1 = agent.execute("t3a", {"student_id": STUDENT})
    r2 = agent.execute("t3b", {"student_id": STUDENT})
    assert r1["status"] == "ok" and r2["status"] == "ok"
    first_id = r1["result"]["plan"]["plan_id"]
    assert _count_status(db_path, STUDENT, "pending_review") == 1
    assert _count_status(db_path, STUDENT, "superseded") == 1
    conn = sqlite3.connect(db_path)
    try:
        status = conn.execute(
            "SELECT status FROM plan_proposals WHERE plan_id=?", (first_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "superseded"


# ── 4. 4D coverage ──────────────────────────────────────────

def test_4d_coverage_missing_rejected(agent):
    def mutate(plan, ctx):
        for w in plan["weeks"]:
            w["competency_focus"] = ["Dream"]
    agent._generator = _stub_based_generator(agent, mutate)
    res = agent.execute("t4", {"student_id": STUDENT})
    assert res["status"] == "ok"
    plan = res["result"]["plan"]
    assert plan.get("generation_note") == "error_template"
    covered = {c for w in plan["weeks"] for c in w["competency_focus"]}
    assert set(VALID_4D) <= covered


# ── 5. parent_summary label leak (negative) ─────────────────

@pytest.mark.parametrize("marker", [
    "Not Yet", "Developing", "Achieved", "Exemplary",
    "confidence", "rubric_id", "mastery_pct",
])
def test_parent_summary_label_leak_rejected(agent, marker):
    def mutate(plan, ctx):
        plan["parent_summary"] = (
            "这份计划会根据学习表现调整一次。"
            f"Internal marker: {marker}."
        )
    agent._generator = _stub_based_generator(agent, mutate)
    res = agent.execute("t5", {"student_id": STUDENT})
    assert res["status"] == "ok"
    plan = res["result"]["plan"]
    assert plan.get("generation_note") == "error_template"
    lowered = plan["parent_summary"].lower()
    for bad in ("not yet", "developing", "achieved", "exemplary",
                "confidence", "rubric", "mastery_pct"):
        assert bad not in lowered


# ── 6. Adjustment: used hard gate ───────────────────────────

def test_adjustment_used_hard_gate(agent):
    gen = agent.execute("t6a", {"student_id": STUDENT})
    v1 = gen["result"]["plan"]
    appr = agent.execute("t6b", {
        "capability": "approve", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops",
    })
    assert appr["result"]["plan"]["status"] == "approved"

    adj1 = agent.execute("t6c", {
        "capability": "adjust", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops", "comment": "学生需要更多数学练习",
        "completed_weeks": 2,
    })
    assert adj1["status"] == "ok"
    v2 = adj1["result"]["plan"]
    assert v2["version"] == 2
    assert v2["status"] == "pending_review"
    assert v2["adjustment"]["used"] is True

    # approve v2, then try adjusting v2 → hard gate refuses
    appr2 = agent.execute("t6d", {
        "capability": "approve", "plan_id": v2["plan_id"],
        "decided_by": "teacher-ops",
    })
    assert appr2["result"]["plan"]["status"] == "approved"
    adj2 = agent.execute("t6e", {
        "capability": "adjust", "plan_id": v2["plan_id"],
        "decided_by": "teacher-ops", "comment": "再调一次",
    })
    assert adj2["status"] == "error"
    assert "already used" in adj2.get("error", "")


# ── 7. Adjustment: frozen completed weeks ───────────────────

def test_adjustment_freezes_completed_weeks(agent):
    gen = agent.execute("t7a", {"student_id": STUDENT})
    v1 = gen["result"]["plan"]
    agent.execute("t7b", {
        "capability": "approve", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops",
    })
    adj = agent.execute("t7c", {
        "capability": "adjust", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops", "comment": "前三周内容保持不变",
        "completed_weeks": 3,
    })
    assert adj["status"] == "ok"
    v2 = adj["result"]["plan"]
    assert v2["weeks"][0:3] == v1["weeks"][0:3], "completed weeks must be frozen"
    assert v2["weeks"][3]["week"] == 4
    assert len(v2["weeks"]) == 8


# ── 8. reject does not consume adjustment budget ────────────

def test_reject_does_not_consume_adjustment(agent):
    gen = agent.execute("t8a", {"student_id": STUDENT})
    v1 = gen["result"]["plan"]
    rej = agent.execute("t8b", {
        "capability": "reject", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops", "comment": "主题不合适",
    })
    assert rej["status"] == "ok"
    assert rej["result"]["plan"]["status"] == "rejected"
    assert rej["result"]["plan"]["adjustment"]["used"] is False

    # regenerate → approve → adjustment still available
    gen2 = agent.execute("t8c", {"student_id": STUDENT})
    v1b = gen2["result"]["plan"]
    agent.execute("t8d", {
        "capability": "approve", "plan_id": v1b["plan_id"],
        "decided_by": "teacher-ops",
    })
    adj = agent.execute("t8e", {
        "capability": "adjust", "plan_id": v1b["plan_id"],
        "decided_by": "teacher-ops", "comment": "调整一下",
        "completed_weeks": 1,
    })
    assert adj["status"] == "ok"
    assert adj["result"]["plan"]["version"] == 2


# ── 9. Student visibility ───────────────────────────────────

def test_student_visibility(agent, db_path):
    # pending → invisible
    gen = agent.execute("t9a", {"student_id": STUDENT})
    plan_id = gen["result"]["plan"]["plan_id"]
    vis = agent.execute("t9b", {
        "capability": "get_student_plan", "student_id": STUDENT,
    })
    assert vis["result"]["plan"] is None

    # rejected → invisible
    agent.execute("t9c", {
        "capability": "reject", "plan_id": plan_id,
        "decided_by": "teacher-ops", "comment": "no",
    })
    vis = agent.execute("t9d", {
        "capability": "get_student_plan", "student_id": STUDENT,
    })
    assert vis["result"]["plan"] is None

    # approved → visible (only latest approved)
    gen2 = agent.execute("t9e", {"student_id": STUDENT})
    plan2 = gen2["result"]["plan"]
    agent.execute("t9f", {
        "capability": "approve", "plan_id": plan2["plan_id"],
        "decided_by": "teacher-ops",
    })
    vis = agent.execute("t9g", {
        "capability": "get_student_plan", "student_id": STUDENT,
    })
    assert vis["result"]["plan"] is not None
    assert vis["result"]["plan"]["plan_id"] == plan2["plan_id"]


# ── 10. Trilingual generation ───────────────────────────────

@pytest.mark.parametrize("lang_code", ["zh-hk", "zh-cn", "en"])
def test_trilingual_generation(agent, db_path, lang_code):
    res = agent.execute("t10", {"student_id": STUDENT, "lang_code": lang_code})
    assert res["status"] == "ok"
    plan = res["result"]["plan"]
    assert plan["lang_code"] == lang_code
    assert plan["parent_summary"].strip() != ""
    assert res["result"]["lang_code"] == lang_code
    if lang_code == "en":
        # simplified/traditional Chinese characters must not appear
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in plan["parent_summary"])


# ── 11. duration_weeks non-8 case ───────────────────────────

def test_duration_weeks_variable(agent):
    res = agent.execute("t11", {"student_id": STUDENT, "duration_weeks": 4})
    assert res["status"] == "ok"
    plan = res["result"]["plan"]
    assert plan["duration_weeks"] == 4
    assert len(plan["weeks"]) == 4
    assert [w["week"] for w in plan["weeks"]] == [1, 2, 3, 4]
    assert plan["adjustment"]["used"] is False


# ── 12. request_changes flow ────────────────────────────────

def test_request_changes_regenerates_and_supersedes(agent, db_path):
    gen = agent.execute("t12a", {"student_id": STUDENT})
    v1 = gen["result"]["plan"]
    rc = agent.execute("t12b", {
        "capability": "request_changes", "plan_id": v1["plan_id"],
        "decided_by": "teacher-ops", "comment": "主题需要更贴近生活",
    })
    assert rc["status"] == "ok"
    v2 = rc["result"]["plan"]
    assert v2["status"] == "pending_review"
    assert v2["version"] == v1["version"] + 1
    assert v2["plan_id"] != v1["plan_id"]
    assert _count_status(db_path, STUDENT, "superseded") >= 1
    assert _count_status(db_path, STUDENT, "pending_review") == 1
