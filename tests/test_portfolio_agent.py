"""
Dreamer AI Phase 6 — Portfolio Agent unit tests (mock DB, no LLM).

Covers (checklist §2.4):
  - Auto-candidates: label IN (achieved, exemplary) AND confidence >= 0.45
  - Upsert idempotency (run twice -> single item)
  - Growth note derived from progress_snapshots (earliest vs latest mastery)
  - Kid-facing labels via label_soften (not parent-facing)
  - P4: mode_allowlist = CONTEXTUAL + HYBRID; DIRECT rejected
  - P5 PDPO red line: share_card payload NEVER contains
    student_id / full name / school (blacklist test — required deliverable)
  - Empty data -> welcome-style content, no error
  - execute() Hermes wrapper
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from agents.portfolio_agent import PortfolioAgent, SHARE_CARD_BLACKLIST


@pytest.fixture()
def agent(tmp_path):
    db_path = str(tmp_path / "portfolio_test.db")
    conn = sqlite3.connect(db_path)
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
        """
    )
    conn.commit()
    conn.close()
    return PortfolioAgent(db_path=db_path)


def _seed_log(agent, student_id="stu_1", topic_id="t_art", label="achieved",
              confidence=0.8, evidence="built a paper rocket", created_at="2026-08-01T10:00:00Z",
              mode="CONTEXTUAL"):
    with agent._connect() as conn:
        conn.execute(
            """INSERT INTO assessment_logs
               (student_id, session_id, topic_id, mode, lang_code, internal_label,
                confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (student_id, "s1", topic_id, mode, "zh-hk", label, confidence,
             "rubric_x", evidence, "assessment", 0, created_at),
        )


def _seed_snapshot(agent, student_id, topic_id, mastery_pct, updated_at):
    with agent._connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO progress_snapshots
               (student_id, topic_id, mastery_pct, attempt_count, last_label, streak, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (student_id, topic_id, mastery_pct, 1, "achieved", 0, updated_at),
        )


# ── Candidate selection ───────────────────────────────────────────

def test_candidates_include_only_high_confidence_achieved(agent):
    _seed_log(agent, label="achieved", confidence=0.8)
    _seed_log(agent, label="exemplary", confidence=0.9, topic_id="t_music")
    _seed_log(agent, label="developing", confidence=0.9, topic_id="t_dev")
    _seed_log(agent, label="achieved", confidence=0.3, topic_id="t_low")  # below threshold

    result = agent.generate_portfolio("stu_1")
    topics = {i["topic_id"] for i in result["portfolio"]["items"]}
    assert topics == {"t_art", "t_music"}


def test_upsert_is_idempotent(agent):
    _seed_log(agent)
    agent.generate_portfolio("stu_1")
    agent.generate_portfolio("stu_1")
    with agent._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM portfolio_items WHERE student_id=?", ("stu_1",)
        ).fetchone()[0]
    assert count == 1


def test_empty_data_welcome_content(agent):
    result = agent.generate_portfolio("stu_empty")
    assert result["portfolio"]["items"] == []
    assert "繼續探索" in result["content"]


# ── Growth note ───────────────────────────────────────────────────

def test_growth_note_improvement(agent):
    _seed_log(agent, label="developing", confidence=0.5, created_at="2026-07-01T10:00:00Z")
    _seed_log(agent, label="achieved", confidence=0.8, created_at="2026-08-01T10:00:00Z")
    result = agent.generate_portfolio("stu_1")
    assert "進步" in result["portfolio"]["items"][0]["growth_note"]


def test_growth_note_consistent(agent):
    _seed_log(agent, label="achieved", confidence=0.7, created_at="2026-07-01T10:00:00Z")
    _seed_log(agent, label="achieved", confidence=0.9, created_at="2026-08-01T10:00:00Z")
    result = agent.generate_portfolio("stu_1")
    assert "保持出色" in result["portfolio"]["items"][0]["growth_note"]


# ── Labels ────────────────────────────────────────────────────────

def test_kid_facing_label_used(agent):
    _seed_log(agent, label="exemplary")
    result = agent.generate_portfolio("stu_1")
    item = result["portfolio"]["items"][0]
    assert item["kid_label"] != ""
    # kid-facing label should not be the raw internal label
    assert item["kid_label"] != "exemplary"


# ── P4 mode allowlist ─────────────────────────────────────────────

def test_direct_mode_rejected(agent):
    _seed_log(agent)
    with pytest.raises(ValueError):
        agent.generate_portfolio("stu_1", mode="DIRECT")


def test_hybrid_mode_allowed(agent):
    _seed_log(agent, mode="HYBRID")
    result = agent.generate_portfolio("stu_1", mode="HYBRID")
    assert result["mode"] == "HYBRID"
    assert len(result["portfolio"]["items"]) == 1


# ── P5 PDPO red line: share_card blacklist (required) ────────────

@pytest.mark.parametrize("leak", ["student_id", "school", "full_name"])
def test_share_card_never_leaks_identity(agent, leak):
    _seed_log(agent)
    result = agent.generate_portfolio(
        "stu_1", display_name="Alex", competency_map={"t_art": ["design", "deliver"]},
    )
    for card in result["portfolio"]["share_cards"]:
        # structural guard: field must not exist
        assert leak not in card, f"share_card leaked field: {leak}"
        # payload guard: value must not appear anywhere in serialized card
        payload = repr(card)
        assert "stu_1" not in payload
        assert "Alex" in card.get("display_name", "")
        assert "school" not in payload.lower()


def test_share_card_whitelist_fields_only(agent):
    _seed_log(agent)
    result = agent.generate_portfolio("stu_1", display_name="Alex")
    card = result["portfolio"]["share_cards"][0]
    assert set(card.keys()) <= {
        "display_name", "item_id", "title", "artifact_summary",
        "competencies_4d", "kid_label", "brand", "generated_at",
    }
    assert card["brand"] == "Dreamer AI"


def test_share_card_competencies_from_map(agent):
    _seed_log(agent)
    result = agent.generate_portfolio(
        "stu_1", competency_map={"t_art": ["design", "deliver"]},
    )
    assert result["portfolio"]["items"][0]["competencies_4d"] == ["design", "deliver"]
    assert result["portfolio"]["share_cards"][0]["competencies_4d"] == ["design", "deliver"]


# ── execute() wrapper ─────────────────────────────────────────────

def test_execute_missing_student_id(agent):
    result = agent.execute("t_1", {})
    assert result["status"] == "error"
    assert "student_id" in result["error"]


def test_execute_ok(agent):
    _seed_log(agent)
    result = agent.execute(
        "t_2",
        {"student_id": "stu_1", "mode": "CONTEXTUAL", "lang_code": "zh-hk",
         "age_band": "P4-P6", "display_name": "Alex"},
    )
    assert result["status"] == "ok"
    assert result["agent"] == "portfolio"
    assert len(result["result"]["portfolio"]["items"]) == 1
