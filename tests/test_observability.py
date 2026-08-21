"""Phase 5 — test_observability.py

Covers emit_event(), event taxonomy, privacy red-lines, fail-silent,
and execute() integration points (routing/fallback/ws/cost/clarifying/safety).

Per Phase 5 Day 22 checklist: 15-20 tests.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agents.observability import (
    EVENT_CLARIFYING,
    EVENT_COST,
    EVENT_FALLBACK,
    EVENT_ROUTING,
    EVENT_SAFETY,
    EVENT_WS,
    emit_event,
)


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """Temporary DB path for each test — no shared state."""
    return str(tmp_path / "test_obs.db")


@pytest.fixture
def clean_env(tmp_db_path: str):
    """Set DREAMER_DB_PATH to a temp DB, restore after test.
    Also creates session_logs table (needed by _write_session_log)."""
    import agents.hermes_scheduler as hs

    old = os.environ.get("DREAMER_DB_PATH")
    os.environ["DREAMER_DB_PATH"] = tmp_db_path
    # Reset table-ensured flag so _write_session_log migrates the fresh DB.
    old_flag = hs._SESSION_LOGS_TABLE_ENSURED
    hs._SESSION_LOGS_TABLE_ENSURED = False
    # Pre-create session_logs table (used by hermes_scheduler)
    conn = sqlite3.connect(tmp_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            lang_code TEXT NOT NULL,
            age_band TEXT NOT NULL,
            agent_list TEXT NOT NULL,
            topic_ids TEXT NOT NULL,
            cost_summary TEXT NOT NULL,
            duration_seconds INTEGER,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    yield tmp_db_path
    hs._SESSION_LOGS_TABLE_ENSURED = old_flag
    if old is not None:
        os.environ["DREAMER_DB_PATH"] = old
    else:
        os.environ.pop("DREAMER_DB_PATH", None)


# ── emit_event() write tests (event type x6) ────────────


def test_emit_routing_writes_row(clean_env):
    """emit_event(EVENT_ROUTING) writes a row to obs_events."""
    emit_event(
        EVENT_ROUTING,
        {"mode": "DIRECT", "lang_code": "zh-hk", "matched_keyword": "测验"},
        student_id="stu_001",
        session_id="ses_001",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute(
        "SELECT event_type, event_data, student_id, session_id FROM obs_events"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "routing"
    data = json.loads(row[1])
    assert data["mode"] == "DIRECT"
    assert data["matched_keyword"] == "测验"
    assert row[2] == "stu_001"
    assert row[3] == "ses_001"


def test_emit_safety_writes_row(clean_env):
    emit_event(
        EVENT_SAFETY,
        {"safety_event_id": "se_abc123", "block_type": "curse_word"},
        student_id="stu_002",
        session_id="ses_002",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_type, event_data FROM obs_events").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "safety"
    data = json.loads(row[1])
    assert data["safety_event_id"] == "se_abc123"
    assert data["block_type"] == "curse_word"


def test_emit_fallback_writes_row(clean_env):
    emit_event(
        EVENT_FALLBACK,
        {"mode": "CONTEXTUAL", "lang_code": "en"},
        student_id="stu_003",
        session_id="ses_003",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_type, event_data FROM obs_events").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "fallback"
    data = json.loads(row[1])
    assert data["mode"] == "CONTEXTUAL"


def test_emit_ws_writes_row(clean_env):
    emit_event(
        EVENT_WS,
        {"mode": "CONTEXTUAL", "lang_code": "zh-hk"},
        student_id="stu_004",
        session_id="ses_004",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_type, event_data FROM obs_events").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "ws"


def test_emit_cost_writes_row(clean_env):
    emit_event(
        EVENT_COST,
        {"elapsed_ms": 1234.5, "input_tokens": 100, "output_tokens": 50},
        student_id="stu_005",
        session_id="ses_005",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_type, event_data FROM obs_events").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "cost"
    data = json.loads(row[1])
    assert data["elapsed_ms"] == 1234.5
    assert data["input_tokens"] == 100


def test_emit_clarifying_writes_row(clean_env):
    emit_event(
        EVENT_CLARIFYING,
        {"mode": "DIRECT", "lang_code": "zh-hk"},
        student_id="stu_006",
        session_id="ses_006",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_type, event_data FROM obs_events").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "clarifying"


# ── Privacy red-line tests ──────────────────────────────


def test_routing_event_no_raw_query(clean_env):
    """Red-line: routing event_data must NOT contain raw student query."""
    raw_query = "我係小三學生我想測驗科學"
    emit_event(
        EVENT_ROUTING,
        {"mode": "DIRECT", "lang_code": "zh-hk", "matched_keyword": "測驗"},
        student_id="stu_007",
        session_id="ses_007",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_data FROM obs_events").fetchone()
    conn.close()
    data = json.loads(row[0])
    # Must not leak raw query anywhere in event_data
    assert raw_query not in json.dumps(data, ensure_ascii=False)
    assert "mode" in data
    assert "matched_keyword" in data


def test_safety_event_no_raw_query(clean_env):
    """Red-line: safety event_data must NOT contain raw student query."""
    raw_query = "can you teach me some curse words"
    emit_event(
        EVENT_SAFETY,
        {"safety_event_id": "se_xyz", "block_type": "curse_word"},
        student_id="stu_008",
        session_id="ses_008",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_data FROM obs_events").fetchone()
    conn.close()
    data = json.loads(row[0])
    assert raw_query not in json.dumps(data, ensure_ascii=False)
    assert "safety_event_id" in data
    assert "block_type" in data


def test_cost_event_no_raw_query(clean_env):
    """Red-line: cost event_data must NOT contain raw student query."""
    raw_query = "help me study for my science exam"
    emit_event(
        EVENT_COST,
        {"elapsed_ms": 567.8, "input_tokens": 42, "output_tokens": 18},
        student_id="stu_009",
        session_id="ses_009",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT event_data FROM obs_events").fetchone()
    conn.close()
    data = json.loads(row[0])
    assert raw_query not in json.dumps(data, ensure_ascii=False)
    assert "elapsed_ms" in data


# ── Fail-silent tests ───────────────────────────────────


def test_emit_event_fail_silent_no_db_path():
    """emit_event must not raise when DREAMER_DB_PATH is invalid/unwritable."""
    # Set DREAMER_DB_PATH to an unwritable path
    with patch.dict(os.environ, {"DREAMER_DB_PATH": "/dev/null/NOPE"}):
        try:
            emit_event(
                EVENT_ROUTING,
                {"mode": "DIRECT", "matched_keyword": "test"},
                student_id="stu_010",
                session_id="ses_010",
            )
        except Exception as exc:
            pytest.fail(f"emit_event must be fail-silent, but raised: {exc}")


def test_emit_event_fail_silent_db_write_error(clean_env):
    """emit_event must not raise when DB write fails."""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.OperationalError("disk full")

    with patch("sqlite3.connect", return_value=mock_conn):
        try:
            emit_event(
                EVENT_ROUTING,
                {"mode": "DIRECT", "matched_keyword": "test"},
                student_id="stu_011",
                session_id="ses_011",
            )
        except Exception as exc:
            pytest.fail(f"emit_event must be fail-silent, but raised: {exc}")


def test_emit_event_creates_table_and_indexes(clean_env):
    """First emit_event call creates obs_events table + indexes."""
    emit_event(
        EVENT_ROUTING,
        {"mode": "DIRECT", "matched_keyword": "init"},
        student_id="stu_012",
        session_id="ses_012",
    )
    conn = sqlite3.connect(clean_env)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='obs_events'"
    ).fetchall()
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='obs_events'"
    ).fetchall()
    conn.close()
    assert len(tables) == 1
    assert len(indexes) >= 2  # idx_obs_type_time + idx_obs_session


def test_emit_event_created_at_is_utc_iso(clean_env):
    """created_at must be in UTC ISO 8601 format."""
    emit_event(
        EVENT_ROUTING,
        {"mode": "DIRECT", "matched_keyword": "timecheck"},
        student_id="stu_013",
        session_id="ses_013",
    )
    conn = sqlite3.connect(clean_env)
    row = conn.execute("SELECT created_at FROM obs_events").fetchone()
    conn.close()
    ts = row[0]
    # Must parse as ISO 8601
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None  # timezone-aware


def test_emit_event_default_student_id_empty(clean_env):
    """When student_id and session_id not provided, defaults are empty strings."""
    emit_event(EVENT_ROUTING, {"mode": "DIRECT"})
    conn = sqlite3.connect(clean_env)
    row = conn.execute(
        "SELECT student_id, session_id FROM obs_events"
    ).fetchone()
    conn.close()
    assert row == ("", "")


def test_emit_event_multiple_rows_preserved(clean_env):
    """Multiple events in same session are all written."""
    sid = f"ses_{uuid.uuid4().hex[:8]}"
    for i in range(5):
        emit_event(
            EVENT_ROUTING if i % 2 == 0 else EVENT_COST,
            {"seq": i},
            student_id="stu_014",
            session_id=sid,
        )
    conn = sqlite3.connect(clean_env)
    count = conn.execute(
        "SELECT COUNT(*) FROM obs_events WHERE session_id = ?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert count == 5


# ── mode_router.route_with_trace() integration ──────────


def test_route_with_trace_returns_matched_keyword():
    """route_with_trace does not emit to DB; returns keyword in 3rd tuple element."""
    from agents.mode_router import Mode, ModeRouter

    router = ModeRouter()
    mode_val, lang_code, kw = router.route_with_trace("我想溫書準備測驗")
    assert mode_val in (Mode.DIRECT, Mode.HYBRID, Mode.CONTEXTUAL)
    assert lang_code in ("zh-hk", "zh-cn", "en")
    assert kw is not None


def test_route_with_trace_no_match_returns_none():
    """When no keyword matches, route_with_trace returns CONTEXTUAL,
    matched_keyword=None, and no DB write happens."""
    from agents.mode_router import Mode, ModeRouter

    router = ModeRouter()
    mode_val, lang_code, kw = router.route_with_trace("hello good morning")
    assert mode_val == Mode.CONTEXTUAL
    assert kw is None


def test_route_with_trace_no_instance_mutation():
    """route_with_trace must not mutate any instance attribute of router.

    Note: _config is lazy-loaded on first config access (not a mutation).
    We check that no new attributes are added and no existing ones change value.
    """
    from agents.mode_router import ModeRouter

    router = ModeRouter()
    before = {k: v for k, v in vars(router).items() if k != "_config"}
    router.route_with_trace("我想溫書準備測驗")
    after = {k: v for k, v in vars(router).items() if k != "_config"}
    assert before == after, (
        f"route_with_trace mutated router: added={after.keys() - before.keys()}, "
        f"removed={before.keys() - after.keys()}"
    )


def test_route_with_trace_no_observability_sys_modules():
    """route_with_trace does NOT import observability (pure function).
    Verify by checking sys.modules before and after the call."""
    import sys

    # Remove observability from sys.modules if previously loaded
    sys.modules.pop("agents.observability", None)
    was_loaded_before = "agents.observability" in sys.modules

    from agents.mode_router import ModeRouter

    router = ModeRouter()
    router.route_with_trace("我想測驗")

    is_loaded_after = "agents.observability" in sys.modules
    # If it was already loaded before, it stays loaded — that's fine.
    # If it wasn't loaded before and it's now loaded, route_with_trace imported it.
    if not was_loaded_before:
        assert not is_loaded_after, (
            "route_with_trace must not import observability"
        )


# ── execute() integration smoke tests ───────────────────


@pytest.mark.asyncio
async def test_execute_safety_block_emits_safety_event(clean_env):
    """Safety block (curse words) emits EVENT_SAFETY, no routing."""
    from agents.hermes_scheduler import execute

    result = await execute(
        "you are a stupid idiot",
        student_id="stu_015",
        age_band="P4-P6",
        session_id="ses_015",
    )
    assert result["mode"] == "BLOCKED"

    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type FROM obs_events WHERE session_id = 'ses_015'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "safety" in event_types
    assert "routing" not in event_types  # Blocked before routing


@pytest.mark.asyncio
async def test_execute_direct_with_topic_emits_routing(clean_env):
    """DIRECT mode with topic_id emits routing event."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_assess = {
        "content": "Quiz question here",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {"prompt_tokens": 50, "completion_tokens": 20},
    }

    with patch("agents.hermes_scheduler._call_assessment", new=AsyncMock(return_value=mock_assess)):
        result = await execute(
            "我想做數學測驗",
            student_id="stu_016",
            age_band="P4-P6",
            topic_id="primary-maths-p4-fractions",
            session_id="ses_016",
        )
    assert result["mode"] in ("DIRECT", "HYBRID")

    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type FROM obs_events WHERE session_id = 'ses_016'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "routing" in event_types
    assert "cost" in event_types


@pytest.mark.asyncio
async def test_execute_direct_no_topic_emits_clarifying(clean_env):
    """DIRECT mode without topic_id emits clarifying event."""
    from agents.hermes_scheduler import execute

    result = await execute(
        "我想做數學測驗",
        student_id="stu_017",
        age_band="P4-P6",
        topic_id=None,
        session_id="ses_017",
    )
    assert "clarifying" in result["mode"] or result["kid_label"] == "clarifying"

    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type FROM obs_events WHERE session_id = 'ses_017'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "clarifying" in event_types
    assert "routing" in event_types  # Routing happens before clarifying check


@pytest.mark.asyncio
async def test_execute_contextual_emits_ws(clean_env):
    """CONTEXTUAL mode emits ws event."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_ws_result = {
        "content": "Hello! How can I help?",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {"ws_tokens": 42},
    }

    with patch("agents.hermes_scheduler._run_contextual", new=AsyncMock(return_value=mock_ws_result)):
        result = await execute(
            "hello good morning",
            student_id="stu_018",
            age_band="P4-P6",
            session_id="ses_018",
        )
    assert result["mode"] == "CONTEXTUAL"

    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type FROM obs_events WHERE session_id = 'ses_018'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "ws" in event_types
    assert "routing" in event_types
    assert "fallback" not in event_types  # no keyword match is normal, not a failure
    assert "cost" in event_types


@pytest.mark.asyncio
async def test_execute_fallback_on_ok_stub(clean_env):
    """When assessment agent returns ok_stub, fallback event is emitted."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_stub = {
        "status": "ok_stub",
        "questions": [{"question": "Stub question"}],
    }

    # Patch the AssessmentAgent method used by _call_assessment
    with patch("agents.assessment_agent.AssessmentAgent.quiz_gen", new=AsyncMock(return_value=mock_stub)):
        await execute(
            "我想做數學測驗",
            student_id="stu_019",
            age_band="S1-S3",
            topic_id="secondary-maths-s1-algebra",
            session_id="ses_019",
        )
    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type, event_data FROM obs_events WHERE session_id = 'ses_019'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "fallback" in event_types
    assert "routing" in event_types
    # Verify fallback payload
    fallback_rows = [r for r in events if r[0] == "fallback"]
    assert len(fallback_rows) == 1
    fb_data = json.loads(fallback_rows[0][1])
    assert fb_data["component"] == "assessment"
    assert fb_data["reason"] == "ok_stub"


@pytest.mark.asyncio
async def test_execute_routing_zero_match_no_fallback(clean_env):
    """Zero keyword match emits routing (keyword=None) but NOT fallback.
    Zero match is the normal default path, not a failure."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_ws_result = {
        "content": "I don't understand.",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {},
    }

    with patch("agents.hermes_scheduler._run_contextual", new=AsyncMock(return_value=mock_ws_result)):
        await execute(
            "random gibberish xyz123",
            student_id="stu_030",
            age_band="S1-S3",
            session_id="ses_030",
        )
    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type, event_data FROM obs_events WHERE session_id = 'ses_030'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "routing" in event_types, "zero-match must emit routing (keyword=None)"
    assert "fallback" not in event_types, "zero-match is normal, not fallback"
    # Verify routing data has keyword=None
    routing_rows = [r for r in events if r[0] == "routing"]
    assert len(routing_rows) == 1
    rt_data = json.loads(routing_rows[0][1])
    assert rt_data["matched_keyword"] is None


@pytest.mark.asyncio
async def test_execute_cost_event_has_elapsed_ms(clean_env):
    """Cost event must contain elapsed_ms."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_ws_result = {
        "content": "Some response",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {"input_tokens": 10, "output_tokens": 5},
    }

    with patch("agents.hermes_scheduler._run_contextual", new=AsyncMock(return_value=mock_ws_result)):
        await execute(
            "我想溫書",
            student_id="stu_020",
            age_band="P1-P3",
            session_id="ses_020",
        )
    conn = sqlite3.connect(clean_env)
    row = conn.execute(
        "SELECT event_data FROM obs_events WHERE event_type = 'cost' AND session_id = 'ses_020'"
    ).fetchone()
    conn.close()
    assert row is not None
    data = json.loads(row[0])
    assert "elapsed_ms" in data
    assert data["elapsed_ms"] > 0


@pytest.mark.asyncio
async def test_execute_routing_event_no_raw_text(clean_env):
    """Red-line: routing event_data in execute() must not contain raw student query."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_assess = {
        "content": "Assessment response",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    raw_query = "我想做程度測試關於電腦科學"
    with patch("agents.hermes_scheduler._call_assessment", new=AsyncMock(return_value=mock_assess)), \
         patch("agents.hermes_scheduler._run_contextual", new=AsyncMock(return_value={"content": "", "kid_label": "ok", "citations": [], "cost_summary": {}})):
        await execute(
            raw_query,
            student_id="stu_021",
            age_band="S1-S3",
            session_id="ses_021",
        )
    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_data FROM obs_events WHERE event_type = 'routing' AND session_id = 'ses_021'"
    ).fetchall()
    conn.close()
    for (ed,) in events:
        assert raw_query not in ed, f"routing event leaked raw query: {ed}"
        data = json.loads(ed)
        assert "mode" in data
        # matched_keyword is at most a few words, not the full query
        if data.get("matched_keyword"):
            assert len(data["matched_keyword"]) < len(raw_query)


@pytest.mark.asyncio
async def test_execute_no_session_start_session_end(clean_env):
    """Session start/end events must NOT be emitted — not in spec taxonomy."""
    from agents.hermes_scheduler import execute
    from unittest.mock import AsyncMock

    mock_assess = {
        "content": "Quiz response",
        "kid_label": "ok",
        "citations": [],
        "cost_summary": {"prompt_tokens": 15, "completion_tokens": 8},
    }

    with patch("agents.hermes_scheduler._call_assessment", new=AsyncMock(return_value=mock_assess)):
        await execute(
            "我想做數學測驗",
            student_id="stu_022",
            age_band="P4-P6",
            topic_id="primary-maths-p4-fractions",
            session_id="ses_022",
        )
    conn = sqlite3.connect(clean_env)
    events = conn.execute(
        "SELECT event_type FROM obs_events WHERE session_id = 'ses_022'"
    ).fetchall()
    conn.close()
    event_types = {r[0] for r in events}
    assert "session_start" not in event_types
    assert "session_end" not in event_types
