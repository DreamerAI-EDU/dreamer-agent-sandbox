"""
Dreamer AI Phase 6 Day 24 — Parent Report Agent Trial (DoD #1)

Seeds a temp SQLite DB with real-shaped data and exercises:
  1. New student  → First Steps variant (baseline + roadmap)
  2. 8-week student → Standard variant (cycle report + mastery_delta)
  3. Cost aggregate (D5) from obs_events cost events

No LLM involved (Parent Report is deterministic DB → template).
Run: python trial_parent_report.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.parent_report_agent import ParentReportAgent


def _seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
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
        CREATE TABLE session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
            topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
            lang_code TEXT NOT NULL DEFAULT 'en', age_band TEXT NOT NULL DEFAULT 'P4-P6',
            agent_list TEXT NOT NULL DEFAULT '[]',
            cost_summary TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE progress_snapshots (
            student_id TEXT NOT NULL, topic_id TEXT NOT NULL,
            mastery_pct REAL NOT NULL DEFAULT 0.0, attempt_count INTEGER NOT NULL DEFAULT 1,
            last_label TEXT NOT NULL DEFAULT '', streak INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, PRIMARY KEY (student_id, topic_id)
        );
        CREATE TABLE obs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL, event_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


def _seed_log(conn, student_id, topic_id, label, created_at, mode="DIRECT",
              session_id="s1", confidence=0.8, evidence="good progress"):
    conn.execute(
        """INSERT INTO assessment_logs
           (student_id, session_id, topic_id, mode, lang_code, internal_label,
            confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (student_id, session_id, topic_id, mode, "zh-hk", label, confidence,
         "rubric_x", evidence, "assessment", 0, created_at),
    )


def _seed_session(conn, student_id, created_at, session_id="s1", mode="DIRECT",
                  topic_ids="t_maths"):
    conn.execute(
        """INSERT INTO session_logs
           (student_id, session_id, topic_id, mode, lang_code, age_band,
            agent_list, cost_summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (student_id, session_id, topic_ids, mode, "zh-hk", "P4-P6",
         '["assessment"]', "{}", created_at),
    )


def _seed_snapshot(conn, student_id, topic_id, mastery_pct, label, created_at, attempts=1):
    conn.execute(
        """INSERT OR REPLACE INTO progress_snapshots
           (student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (student_id, topic_id, mastery_pct, attempts, label, 0, created_at),
    )


def _seed_obs_cost(conn, student_id, total_tokens, elapsed_ms, created_at):
    import json
    conn.execute(
        """INSERT INTO obs_events (student_id, session_id, event_type, event_data, created_at)
           VALUES (?,?,?,?,?)""",
        (student_id, "s_obs", "cost",
         json.dumps({"total_tokens": total_tokens, "elapsed_ms": elapsed_ms}),
         created_at),
    )


def main() -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="trial_parent_")
    os.close(fd)
    os.unlink(db_path)

    conn = sqlite3.connect(db_path)
    _seed_schema(conn)

    # ── Student A: new student (first steps) ─────────────
    _seed_log(conn, "stu_a", "t_maths", "developing", "2026-08-18T10:00:00Z")
    _seed_session(conn, "stu_a", "2026-08-18T10:00:00Z", session_id="sa1")
    _seed_snapshot(conn, "stu_a", "t_maths", 0.45, "developing", "2026-08-18T10:00:00Z")
    _seed_obs_cost(conn, "stu_a", 1234, 15000, "2026-08-18T10:00:01Z")

    # ── Student B: 8-week established (standard + cycle) ─
    for i in range(7):  # 7 sessions across ~50 days
        day = 50 - i * 8
        label = "achieved" if i >= 3 else "developing"
        mastery = 0.75 if i >= 3 else 0.45
        _seed_log(conn, "stu_b", "t_computing", label,
                  f"2026-07-01T0{i % 5 + 1}:00:00Z", session_id=f"sb{i}")
        _seed_session(conn, "stu_b", f"2026-07-01T0{i % 5 + 1}:00:00Z",
                      session_id=f"sb{i}", mode="HYBRID", topic_ids="t_computing")
        _seed_snapshot(conn, "stu_b", "t_computing", mastery, label,
                       f"2026-07-01T0{i % 5 + 1}:00:00Z", attempts=i + 1)
        _seed_obs_cost(conn, "stu_b", 2000 + i * 500, 20000 + i * 3000,
                       f"2026-07-0{i % 5 + 1}T0{i % 5 + 1}:30:00Z")
    _seed_log(conn, "stu_b", "t_maths", "achieved", "2026-08-15T09:00:00Z", session_id="sb_last")
    _seed_session(conn, "stu_b", "2026-08-15T09:00:00Z", session_id="sb_last", mode="DIRECT")
    _seed_snapshot(conn, "stu_b", "t_maths", 0.8, "achieved", "2026-08-15T09:00:00Z", attempts=4)

    conn.commit()
    conn.close()

    agent = ParentReportAgent(db_path=db_path)

    # 1. New student → First Steps
    r1 = agent.generate_report("stu_a", period="cycle", lang_code="zh-hk")
    v1 = r1["report"]["variant"]
    assert v1 == "first_steps", f"expected first_steps, got {v1}"
    assert r1["report"]["baseline"] is not None, "first_steps must have baseline"
    assert r1["report"]["roadmap"] is not None, "first_steps must have roadmap"
    assert r1["cost_summary"]["total_tokens"] == 1234, r1["cost_summary"]
    print(f"[OK] A new student → variant={v1}, baseline={len(r1['report']['baseline'])} topic(s), "
          f"roadmap={len(r1['report']['roadmap'])} item(s), tokens={r1['cost_summary']['total_tokens']}")

    # 2. 8-week student → Standard cycle report
    r2 = agent.generate_report("stu_b", period="cycle", lang_code="zh-hk")
    v2 = r2["report"]["variant"]
    assert v2 == "standard", f"expected standard, got {v2}"
    assert r2["report"]["baseline"] is None and r2["report"]["roadmap"] is None
    assert r2["report"]["summary"]["session_count"] >= 6
    topics = r2["report"]["topics"]
    assert any(t["mastery_delta"] != 0.0 for t in topics), "standard must have mastery_delta"
    assert r2["cost_summary"]["total_tokens"] > 0, "cycle report must aggregate cost"
    print(f"[OK] B 8-week → variant={v2}, sessions={r2['report']['summary']['session_count']}, "
          f"topics={len(topics)}, tokens={r2['cost_summary']['total_tokens']}")

    # 3. Envelope contract (7 fields)
    for tag, r in (("A", r1), ("B", r2)):
        assert r["mode"] == "parent_report"
        assert r["lang_code"] == "zh-hk"
        assert set(r.keys()) >= {"content", "mode", "lang_code", "age_band",
                                 "kid_label", "citations", "cost_summary", "report"}
        print(f"[OK] {tag} envelope 7+1 fields present; content prefix: "
              f"{r['content'][:40]}…")

    # 4. Journey window
    r3 = agent.generate_report("stu_b", period="journey", lang_code="zh-hk")
    assert r3["report"]["period"]["type"] == "journey"
    assert r3["report"]["period"]["days"] >= 40
    print(f"[OK] B journey span={r3['report']['period']['days']}d, "
          f"topics={len(r3['report']['topics'])}")

    try:
        os.unlink(db_path)
    except OSError:
        pass  # temp file may be held open by an unclosed connection; OS cleans up
    print("\nTRIAL PASS — parent report end-to-end OK")


if __name__ == "__main__":
    main()
