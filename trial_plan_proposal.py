"""
Dreamer AI Phase 7 — D11 Plan-Proposal Flow v1.1 Trial (真容器 trial)

Seeds a temp SQLite DB with real-shaped student data and exercises the full
Plan-Proposal lifecycle against the PlanAgent:

  1. generate_plan  → pending_review, validated (topic hard gate / 4D coverage /
     len(weeks)==duration_weeks / label non-leak / cost cap)
  2. approve        → approved, visible to student via get_student_plan
  3. request_changes → review JSON records teacher comment + state
  4. One-shot adjust → v2 pending_review, unfinished weeks regenerated,
     completed weeks frozen verbatim, adjustment.used=True
  5. Hard gate      → second adjust on same plan is rejected
  6. reject         → does NOT consume the adjustment budget: a fresh plan
     can still be adjusted once

LLM: uses codex_cli when an OpenRouter key is available; otherwise the
deterministic stub fallback keeps the trial green with zero credentials.

Run: python trial_plan_proposal.py
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.plan_agent import PlanAgent, VALID_4D
from agents import codex_cli

# Stable topic pool used ONLY as a fallback when the local KB has not been
# seeded yet; the primary path reads kb/manifest.yaml + knowledge_bases/.
TOPIC_POOL_FALLBACK = {
    "maths-place-value": "dreamer-maths-ai",
    "maths-fractions": "dreamer-maths-ai",
    "english-story": "dreamer-english-kb",
    "science-plants": "dreamer-science-kb",
    "history-hk-1950s": "dreamer-history-kb",
}


def _seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
            topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
            lang_code TEXT NOT NULL DEFAULT 'en', age_band TEXT NOT NULL DEFAULT 'P4-P6',
            agent_list TEXT NOT NULL DEFAULT '[]',
            cost_summary TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE assessment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
            topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
            lang_code TEXT NOT NULL DEFAULT 'en', internal_label TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0, rubric_id TEXT NOT NULL DEFAULT '',
            evidence_text TEXT NOT NULL DEFAULT '',
            agent_used TEXT NOT NULL DEFAULT 'assessment',
            cost_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE progress_snapshots (
            student_id TEXT NOT NULL, topic_id TEXT NOT NULL,
            mastery_pct REAL NOT NULL DEFAULT 0.0, attempt_count INTEGER NOT NULL DEFAULT 1,
            last_label TEXT NOT NULL DEFAULT '', streak INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, PRIMARY KEY (student_id, topic_id)
        );
    """)


def _seed_log(conn: sqlite3.Connection, student_id: str, topic_id: str, label: str,
              created_at: str, session_id: str = "s1") -> None:
    conn.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code, internal_label,
            confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (student_id, session_id, topic_id, "DIRECT", "zh-hk", label, 0.8,
         "rubric_x", "good progress", "assessment", 0, created_at),
    )


def _seed_session(conn: sqlite3.Connection, student_id: str, created_at: str,
                  session_id: str = "s1", topic_ids: str = "maths-place-value") -> None:
    conn.execute(
        """INSERT INTO session_logs
           (student_id, session_id, topic_id, mode, lang_code, age_band,
            agent_list, cost_summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (student_id, session_id, topic_ids, "DIRECT", "zh-hk", "P4-P6",
         '["assessment"]', "{}", created_at),
    )


def _seed_snapshot(conn: sqlite3.Connection, student_id: str, topic_id: str,
                   mastery_pct: float, label: str, created_at: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (student_id, topic_id, mastery_pct, 3, label, 0, created_at),
    )


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"TRIAL FAILED: {msg}")
    print(f"[OK] {msg}")


def main() -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="trial_plan_")
    os.close(fd)
    os.unlink(db_path)

    conn = sqlite3.connect(db_path)
    _seed_schema(conn)
    now = _now()
    _seed_log(conn, "stu_a", "maths-place-value", "developing", now)
    _seed_session(conn, "stu_a", now)
    _seed_snapshot(conn, "stu_a", "maths-place-value", 0.45, "developing", now)
    conn.commit()
    conn.close()

    # Real container path: live manifest + KB scan; fallback pool only if empty.
    agent = PlanAgent(db_path=db_path, llm_enabled=codex_cli.is_available())
    pool = agent._load_topic_pool_from_kb()
    if not pool:
        agent = PlanAgent(db_path=db_path, topic_pool=TOPIC_POOL_FALLBACK,
                          llm_enabled=codex_cli.is_available())
        pool = TOPIC_POOL_FALLBACK
    print(f"[info] topic pool size={len(pool)} | llm_enabled={agent._llm_enabled}")

    # ── 1. generate → pending_review ───────────────────────────────
    r1 = agent.execute("trial-1", {"student_id": "stu_a", "lang_code": "zh-hk",
                                   "age_band": "P4-P6"})
    _check(r1["status"] == "ok", f"generate returns ok ({r1['status']})")
    plan1 = r1["result"]["plan"]
    _check(plan1["status"] == "pending_review", "new plan starts pending_review")
    _check(len(plan1["weeks"]) == int(plan1["duration_weeks"]),
           f"len(weeks)==duration_weeks ({len(plan1['weeks'])})")
    covered = {c for w in plan1["weeks"] for c in w["competency_focus"]}
    _check(set(VALID_4D) <= covered, f"4D coverage present ({sorted(set(VALID_4D) & covered)})")
    lowered = plan1["parent_summary"].lower()
    _check(not any(bad in lowered for bad in (
        "not yet", "developing", "achieved", "exemplary", "confidence",
        "rubric", "mastery_pct")), "parent_summary has no label leak")
    cs = plan1["cost_summary"] or {}
    tokens = int(cs.get("tokens_in") or 0) + int(cs.get("tokens_out") or 0)
    _check(tokens <= 20000, f"cost within cap ({tokens})")
    print(f"[info] plan1={plan1['plan_id']} v{plan1['version']} "
          f"weeks={len(plan1['weeks'])} note={plan1.get('generation_note')}")

    # ── 2. approve → student visibility ────────────────────────────
    r2 = agent.execute("trial-2", {"capability": "approve",
                                   "plan_id": plan1["plan_id"],
                                   "decided_by": "teacher-ops",
                                   "comment": "approved in trial"})
    _check(r2["status"] == "ok", "approve returns ok")
    _check(r2["result"]["plan"]["status"] == "approved", "plan approved")
    _check(r2["result"]["plan"]["review"]["decided_by"] == "teacher-ops",
           "review JSON records approving teacher")
    vis = agent.execute("trial-2b", {"capability": "get_student_plan",
                                     "student_id": "stu_a"})
    _check(vis["result"]["plan"]["plan_id"] == plan1["plan_id"],
           "student sees approved plan")

    # ── 3. request_changes (fresh student) ─────────────────────────
    r3 = agent.execute("trial-3", {"student_id": "stu_b", "lang_code": "zh-hk"})
    plan_b = r3["result"]["plan"]
    rc = agent.execute("trial-3b", {"capability": "request_changes",
                                    "plan_id": plan_b["plan_id"],
                                    "decided_by": "teacher-ops",
                                    "comment": "減一週作業量"})
    _check(rc["status"] == "ok", "request_changes returns ok")
    rc_plan = rc["result"]["plan"]
    _check(rc_plan["status"] == "pending_review",
           "request_changes regenerates a pending_review plan")
    _check(int(rc_plan["version"]) == int(plan_b["version"]) + 1,
           "request_changes bumps version (regeneration)")
    old_b = agent.execute("trial-3c", {"capability": "get_plan",
                                       "plan_id": plan_b["plan_id"]})
    _check(old_b["result"]["plan"]["status"] == "superseded",
           "old pending plan superseded")

    # ── 4. one-shot adjust: frozen completed weeks + used hard gate ─
    adj1 = agent.execute("trial-4", {"capability": "adjust",
                                     "plan_id": plan1["plan_id"],
                                     "decided_by": "teacher-ops",
                                     "comment": "增加數學練習",
                                     "completed_weeks": 2})
    _check(adj1["status"] == "ok", "first adjust returns ok")
    v2 = adj1["result"]["plan"]
    _check(v2["version"] == 2, f"adjust produces v2 (got v{v2['version']})")
    _check(v2["status"] == "pending_review", "v2 back to pending_review")
    _check(v2["adjustment"]["used"] is True, "adjustment.used=True after one-shot")
    frozen = plan1["weeks"][:2]
    _check(v2["weeks"][:2] == frozen, "completed weeks frozen verbatim")
    _check(v2["weeks"][2]["week"] == 3 and len(v2["weeks"]) == 8,
           "unfinished weeks rebuilt with continuous week numbers")
    v2_covered = {c for w in v2["weeks"] for c in w["competency_focus"]}
    _check(set(VALID_4D) <= v2_covered, "regenerated weeks keep 4D coverage")

    appr_v2 = agent.execute("trial-4c", {"capability": "approve",
                                         "plan_id": v2["plan_id"],
                                         "decided_by": "teacher-ops"})
    _check(appr_v2["status"] == "ok" and
           appr_v2["result"]["plan"]["status"] == "approved",
           "v2 approved for one-shot gate check")
    adj2 = agent.execute("trial-4b", {"capability": "adjust",
                                      "plan_id": v2["plan_id"],
                                      "decided_by": "teacher-ops",
                                      "comment": "再調一次"})
    _check(adj2["status"] == "error" and "already used" in adj2.get("error", ""),
           "second adjust hard-gated (one-shot)")

    # ── 5. reject does NOT consume the adjustment budget ───────────
    r5 = agent.execute("trial-5", {"student_id": "stu_c", "lang_code": "zh-hk"})
    plan_c = r5["result"]["plan"]
    rej = agent.execute("trial-5b", {"capability": "reject",
                                     "plan_id": plan_c["plan_id"],
                                     "decided_by": "teacher-ops",
                                     "comment": "難度過高"})
    _check(rej["status"] == "ok" and rej["result"]["plan"]["status"] == "rejected",
           "reject works")
    _check(not (rej["result"]["plan"].get("adjustment") or {}).get("used"),
           "rejected plan has no adjustment.used")
    r5c = agent.execute("trial-5c", {"student_id": "stu_c", "lang_code": "zh-hk"})
    plan_c2 = r5c["result"]["plan"]
    appr = agent.execute("trial-5d", {"capability": "approve",
                                      "plan_id": plan_c2["plan_id"],
                                      "decided_by": "teacher-ops"})
    _check(appr["status"] == "ok", "fresh plan after reject can be approved")
    adj3 = agent.execute("trial-5e", {"capability": "adjust",
                                      "plan_id": plan_c2["plan_id"],
                                      "decided_by": "teacher-ops",
                                      "comment": "reject 後仍可調整一次"})
    _check(adj3["status"] == "ok" and adj3["result"]["plan"]["adjustment"]["used"] is True,
           "reject does not consume adjustment budget")

    try:
        os.unlink(db_path)
    except OSError:
        pass

    print("\nTRIAL PASS — D11 plan-proposal flow end-to-end OK "
          "(generate → approve → request_changes → one-shot adjust → reject)")


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        raise
