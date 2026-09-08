"""W6 PR-B — retention_cleanup + chat_history_cleanup core tests.

Covers the red lines decided at PR-B kickoff:
  - safety_events: reviewed >90d deleted; unreviewed NEVER deleted and
    reported in a separate listing (never mixed into the delete batch).
  - learning records: student-level proxy — student whose max(created_at)
    across the six learning tables is older than 12 months gets all six
    tables cascade-deleted; active students untouched.
  - dry-run never mutates the DB; --apply is the only mutating path.
  - chat_history core: sessions with updated_at older than 90d are the
    delete root; FK cascade removes descendants (messages/turns/...).
"""

from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import retention_cleanup  # noqa: E402
import chat_history_cleanup  # noqa: E402


def _iso(days_ago: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def authdb(tmp_path: Path) -> Path:
    db = tmp_path / "auth.db"
    conn = _connect(db)
    conn.executescript(
        """
        CREATE TABLE safety_events (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            raw_input TEXT NOT NULL,
            reviewed BOOLEAN DEFAULT FALSE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE assessment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            topic_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE progress_snapshots (
            student_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (student_id, topic_id)
        );
        CREATE TABLE portfolio_items (
            item_id TEXT NOT NULL UNIQUE,
            student_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE plan_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE obs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()
    return db


def _seed_safety(conn: sqlite3.Connection, *rows: tuple[str, str, int, int]) -> None:
    """(id, student, reviewed 0/1, days_ago)"""
    for event_id, student, reviewed, days_ago in rows:
        conn.execute(
            "INSERT INTO safety_events "
            "(id, student_id, event_type, severity, raw_input, reviewed, created_at) "
            "VALUES (?, ?, 'welfare', 'high', 'x', ?, ?)",
            (event_id, student, reviewed, _iso(days_ago)),
        )
    conn.commit()


def _seed_learning(conn: sqlite3.Connection, student: str, days_ago: int) -> None:
    conn.execute(
        "INSERT INTO assessment_logs (student_id, topic_id, session_id, created_at) "
        "VALUES (?, 't1', 's1', ?)",
        (student, _iso(days_ago)),
    )
    conn.execute(
        "INSERT INTO progress_snapshots (student_id, topic_id, created_at) "
        "VALUES (?, 't1', ?)",
        (student, _iso(days_ago)),
    )
    conn.execute(
        "INSERT INTO portfolio_items (item_id, student_id, created_at) "
        "VALUES (?, ?, ?)",
        (f"pf-{student}", student, _iso(days_ago)),
    )
    conn.execute(
        "INSERT INTO plan_proposals (student_id, status, version, created_at) "
        "VALUES (?, 'approved', 1, ?)",
        (student, _iso(days_ago)),
    )
    conn.execute(
        "INSERT INTO session_logs (session_id, student_id, created_at) "
        "VALUES ('sx', ?, ?)",
        (student, _iso(days_ago)),
    )
    conn.execute(
        "INSERT INTO obs_events (student_id, event_type, event_data, created_at) "
        "VALUES (?, 'routing', '{}', ?)",
        (student, _iso(days_ago)),
    )
    conn.commit()


# --- safety_events ---------------------------------------------------------


def test_safety_reviewed_old_only_in_delete_batch(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_safety(
        conn,
        ("ev-old-reviewed", "stu1", 1, 120),
        ("ev-old-unreviewed", "stu1", 0, 120),
        ("ev-recent-reviewed", "stu1", 1, 10),
    )
    plan = retention_cleanup.plan_safety_cleanup(conn, _iso(90))
    ids = {r["id"] for r in plan["delete_batch"]}
    assert ids == {"ev-old-reviewed"}
    unreviewed = {r["id"] for r in plan["unreviewed"]}
    assert unreviewed == {"ev-old-unreviewed"}
    conn.close()


def test_safety_dry_run_never_mutates(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_safety(conn, ("ev-1", "stu1", 1, 120))
    retention_cleanup.plan_safety_cleanup(conn, _iso(90))
    n = conn.execute("SELECT COUNT(*) FROM safety_events").fetchone()[0]
    assert n == 1
    conn.close()


def test_safety_apply_deletes_only_reviewed(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_safety(
        conn,
        ("ev-reviewed", "stu1", 1, 120),
        ("ev-unreviewed", "stu1", 0, 120),
    )
    plan = retention_cleanup.plan_safety_cleanup(conn, _iso(90))
    deleted = retention_cleanup.apply_safety_deletes(
        conn, [r["id"] for r in plan["delete_batch"]]
    )
    conn.commit()
    assert deleted == 1
    remaining = [
        r["id"]
        for r in conn.execute("SELECT id FROM safety_events").fetchall()
    ]
    assert remaining == ["ev-unreviewed"]
    conn.close()


def test_main_dry_run_never_writes_marker(authdb: Path, tmp_path: Path) -> None:
    """Marker proves the DELETE cron ran — dry-run must not fake it."""
    conn = _connect(authdb)
    _seed_safety(conn, ("ev-1", "stu1", 1, 120))
    conn.close()
    marker = tmp_path / "state" / "retention_last_run.json"
    code = retention_cleanup.main(["--db", str(authdb), "--marker", str(marker)])
    assert code == 0
    assert not marker.exists()


def test_main_apply_writes_marker(authdb: Path, tmp_path: Path) -> None:
    conn = _connect(authdb)
    _seed_safety(conn, ("ev-1", "stu1", 1, 120))
    conn.close()
    marker = tmp_path / "state" / "retention_last_run.json"
    code = retention_cleanup.main(
        ["--db", str(authdb), "--apply", "--marker", str(marker)]
    )
    assert code == 0
    import json
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["mode"] == "apply"
    assert "run_at" in payload


# --- learning records -------------------------------------------------------


def test_learning_inactive_student_cascades_all_six(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_learning(conn, "stu-inactive", 400)  # > 12 months
    _seed_learning(conn, "stu-active", 5)      # active
    plan = retention_cleanup.plan_learning_cleanup(conn, _iso(365))
    assert [s["student_id"] for s in plan["students"]] == ["stu-inactive"]
    assert plan["students"][0]["per_table_rows"] == {
        "assessment_logs": 1,
        "progress_snapshots": 1,
        "portfolio_items": 1,
        "plan_proposals": 1,
        "session_logs": 1,
        "obs_events": 1,
    }
    assert plan["students"][0]["total_rows"] == 6

    applied = retention_cleanup.apply_learning_deletes(
        conn, ["stu-inactive"]
    )
    conn.commit()
    assert sum(applied.values()) == 6
    for table in retention_cleanup.LEARNING_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 1, f"{table} should keep the active student row"
    conn.close()


def test_learning_dry_run_never_mutates(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_learning(conn, "stu-inactive", 400)
    retention_cleanup.plan_learning_cleanup(conn, _iso(365))
    for table in retention_cleanup.LEARNING_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 1
    conn.close()


def test_learning_boundary_just_under_cutoff_kept(authdb: Path) -> None:
    conn = _connect(authdb)
    _seed_learning(conn, "stu-border", 364)  # just inside 12 months
    plan = retention_cleanup.plan_learning_cleanup(conn, _iso(365))
    assert plan["students"] == []
    conn.close()


# --- chat_history core ------------------------------------------------------


@pytest.fixture()
def chatdb(tmp_path: Path) -> Path:
    db = tmp_path / "chat_history.db"
    conn = _connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE TABLE turns (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        );
        CREATE TABLE turn_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        );
        CREATE TABLE notebook_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        );
        CREATE TABLE notebook_entry_categories (
            entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
            category TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    return db


def _epoch_days_ago(days: int) -> float:
    import time
    return time.time() - days * 86400


def _seed_session(conn: sqlite3.Connection, sid: str, days_ago: int) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (sid, "t", _epoch_days_ago(days_ago), _epoch_days_ago(days_ago)),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, created_at) "
        "VALUES (?, 'user', 'hi', ?)",
        (sid, _epoch_days_ago(days_ago)),
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, created_at) VALUES (?, ?, ?)",
        (f"turn-{sid}", sid, _epoch_days_ago(days_ago)),
    )
    conn.execute(
        "INSERT INTO turn_events (turn_id, created_at) VALUES (?, ?)",
        (f"turn-{sid}", _epoch_days_ago(days_ago)),
    )
    conn.execute(
        "INSERT INTO notebook_entries (session_id, created_at) VALUES (?, ?)",
        (sid, _epoch_days_ago(days_ago)),
    )
    conn.commit()


def test_chat_old_session_plan_and_cascade(chatdb: Path) -> None:
    conn = _connect(chatdb)
    _seed_session(conn, "s-old", 120)
    _seed_session(conn, "s-recent", 5)
    plan = chat_history_cleanup.plan_chat_cleanup(conn, _epoch_days_ago(90))
    assert plan["session_count"] == 1
    assert plan["sessions"][0]["session_id"] == "s-old"

    applied = chat_history_cleanup.apply_chat_deletes(conn, ["s-old"])
    conn.commit()
    assert applied["sessions"] == 1
    assert applied["messages"] == 1
    assert applied["turns"] == 1
    assert applied["turn_events"] == 1
    assert applied["notebook_entries"] == 1
    # recent session and descendants untouched
    assert conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE id='s-recent'"
    ).fetchone()[0] == 1
    conn.close()


def test_chat_dry_run_never_mutates(chatdb: Path) -> None:
    conn = _connect(chatdb)
    _seed_session(conn, "s-old", 120)
    chat_history_cleanup.plan_chat_cleanup(conn, _epoch_days_ago(90))
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert n == 1
    conn.close()
