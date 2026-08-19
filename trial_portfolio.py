"""
Dreamer AI Phase 6 Day 25 — Portfolio Agent Trial (DoD #1: real-container smoke).

Temp SQLite seed (assessment_logs / progress_snapshots / portfolio_items) +
PortfolioAgent end-to-end, no DeepTutor / PostgreSQL dependency.

Checks:
  1. Candidates: achieved/exemplary >= 0.45 only; developing/low-confidence out
  2. Upsert idempotent (run twice -> single portfolio_items row)
  3. Growth note: label history developing->achieved -> improvement line
  4. Kid-facing labels: kid_label != raw internal_label
  5. P4: DIRECT rejected; HYBRID accepted (mode_allowlist CONTEXTUAL+HYBRID)
  6. P5 PDPO red line: share_card never contains student_id/full name/school
  7. Empty student -> welcome content, zero items, no error
  8. execute() wrapper + registry wiring (HermesScheduler route)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.portfolio_agent import PortfolioAgent

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
            topic_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL DEFAULT '',
            total_turns INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE obs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL DEFAULT '{}',
            event_ref TEXT NOT NULL DEFAULT '',
            student_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )


def seed_log(conn, student_id, topic_id, label, confidence, evidence,
             created_at, mode="CONTEXTUAL"):
    conn.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code, internal_label,
            confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (student_id, "s1", topic_id, mode, "zh-hk", label, confidence,
         "rubric_x", evidence, "assessment", 0, created_at),
    )


def main() -> int:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    seed_schema(conn)
    # stu_1: developing (Jul) -> achieved (Aug) => growth; + exemplary (Aug)
    seed_log(conn, "stu_1", "t_art", "developing", 0.5,
             "first draft of rocket", "2026-07-01T10:00:00Z")
    seed_log(conn, "stu_1", "t_art", "achieved", 0.8,
             "built a paper rocket that flies", "2026-08-01T10:00:00Z")
    seed_log(conn, "stu_1", "t_music", "exemplary", 0.95,
             "composed a 16-bar melody", "2026-08-05T10:00:00Z")
    # out-of-pool: low confidence + developing
    seed_log(conn, "stu_1", "t_low", "achieved", 0.3,
             "low confidence artifact", "2026-08-06T10:00:00Z")
    seed_log(conn, "stu_1", "t_dev", "developing", 0.8,
             "still building", "2026-08-07T10:00:00Z")
    conn.commit()
    conn.close()

    agent = PortfolioAgent(db_path=db_path)

    # 1. candidates
    result = agent.generate_portfolio("stu_1", display_name="Alex",
                                      competency_map={"t_music": ["design"]})
    topics = {i["topic_id"] for i in result["portfolio"]["items"]}
    check("1. candidates only achieved/exemplary>=0.45",
          topics == {"t_art", "t_music"}, f"got {topics}")

    # 2. upsert idempotent
    agent.generate_portfolio("stu_1")
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM portfolio_items WHERE student_id='stu_1'"
    ).fetchone()[0]
    conn.close()
    check("2. upsert idempotent (single row)", count == 2, f"rows={count}")

    # 3. growth note (developing -> achieved)
    art_item = next(i for i in result["portfolio"]["items"] if i["topic_id"] == "t_art")
    check("3. growth note improvement line", "進步" in art_item["growth_note"],
          art_item["growth_note"])

    # 4. kid-facing labels
    labels_ok = all(i["kid_label"] != i["internal_label"] and i["kid_label"] != ""
                    for i in result["portfolio"]["items"])
    check("4. kid-facing labels", labels_ok,
          [i["kid_label"] for i in result["portfolio"]["items"]])

    # 5. P4 mode allowlist
    try:
        agent.generate_portfolio("stu_1", mode="DIRECT")
        direct_ok = False
    except ValueError:
        direct_ok = True
    hybrid = agent.generate_portfolio("stu_1", mode="HYBRID")
    check("5a. DIRECT rejected", direct_ok)
    check("5b. HYBRID accepted", hybrid["mode"] == "HYBRID")

    # 6. P5 share_card blacklist (PDPO red line)
    leaks = []
    for card in result["portfolio"]["share_cards"]:
        payload = json.dumps(card, ensure_ascii=False)
        for term in ("stu_1", "student_id", "school", "full_name"):
            if term in payload:
                leaks.append(term)
        if "Alex" not in card.get("display_name", ""):
            leaks.append("display_name_missing")
    check("6. share_card no identity leak (PDPO)", not leaks, f"leaks={leaks}")

    # 7. empty student
    empty = agent.generate_portfolio("stu_empty")
    check("7. empty student graceful", empty["portfolio"]["items"] == []
          and "繼續探索" in empty["content"])

    # 8. execute() + registry wiring via HermesScheduler
    from agents.hermes_scheduler import HermesScheduler
    from agents.registry import SubagentRegistry
    from agents.subagents import register_all

    registry = SubagentRegistry()
    register_all(registry)
    scheduler = HermesScheduler()
    scheduler.registry = registry

    routed = scheduler.route("portfolio", "t_trial_1",
                             {"student_id": "stu_1", "mode": "CONTEXTUAL",
                              "display_name": "Alex"})
    check("8a. scheduler route ok", routed.get("status") == "ok"
          and routed.get("agent") == "portfolio",
          f"status={routed.get('status')} agent={routed.get('agent')}")
    mode_list = {a["name"] for a in scheduler.select_candidates("HYBRID")}
    check("8b. HYBRID candidates include portfolio", "portfolio" in mode_list,
          f"hybrid agents={sorted(mode_list)}")

    print(f"\n{sum(1 for _, ok, _ in CHECKS if ok)}/{len(CHECKS)} checks passed")
    return 0 if all(ok for _, ok, _ in CHECKS) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        import traceback
        traceback.print_exc()
        print(f"\nTRIAL ERROR: {exc}")
        sys.exit(1)
