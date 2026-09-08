"""W6 PR-B — health_monitor.check_retention fail-loud tests.

  - unreviewed safety event older than 7 days        -> fail (exit 1)
  - unreviewed events only recent                     -> pass
  - retention marker missing                          -> fail
  - retention marker stale (> 7 days)                 -> fail
  - retention marker fresh                            -> pass
  - marker unreadable (bad JSON / missing run_at)     -> fail
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import health_monitor  # noqa: E402


def _iso(days_ago: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")


def _make_db(path: Path, oldest_unreviewed_days_ago: int | None) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE safety_events ("
        " id TEXT PRIMARY KEY, student_id TEXT NOT NULL, event_type TEXT NOT NULL,"
        " severity TEXT NOT NULL, raw_input TEXT NOT NULL,"
        " reviewed BOOLEAN DEFAULT FALSE, created_at TEXT NOT NULL)"
    )
    if oldest_unreviewed_days_ago is not None:
        conn.execute(
            "INSERT INTO safety_events "
            "(id, student_id, event_type, severity, raw_input, reviewed, created_at) "
            "VALUES ('ev1', 'stu1', 'welfare', 'high', 'x', 0, ?)",
            (_iso(oldest_unreviewed_days_ago),),
        )
    conn.commit()
    conn.close()


def _marker(path: Path, run_days_ago: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"run_at": _iso(run_days_ago), "mode": "apply"}),
        encoding="utf-8",
    )


def test_unreviewed_older_than_7d_fails(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, oldest_unreviewed_days_ago=8)
    code, msg = health_monitor.check_retention(
        db_path=db, marker_paths=()
    )
    assert code == 1
    assert "unreviewed safety event" in msg


def test_unreviewed_recent_passes(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, oldest_unreviewed_days_ago=2)
    code, _ = health_monitor.check_retention(db_path=db, marker_paths=())
    assert code == 0


def test_no_unreviewed_passes(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, oldest_unreviewed_days_ago=None)
    code, _ = health_monitor.check_retention(db_path=db, marker_paths=())
    assert code == 0


def test_marker_missing_fails(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, None)
    missing = tmp_path / "state" / "retention_last_run.json"
    code, msg = health_monitor.check_retention(
        db_path=db, marker_paths=(missing,)
    )
    assert code == 1
    assert "marker missing" in msg


def test_marker_stale_fails(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, None)
    marker = tmp_path / "retention_last_run.json"
    _marker(marker, run_days_ago=8)
    code, msg = health_monitor.check_retention(
        db_path=db, marker_paths=(marker,)
    )
    assert code == 1
    assert "stale" in msg


def test_marker_fresh_passes(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, None)
    marker = tmp_path / "retention_last_run.json"
    _marker(marker, run_days_ago=0)
    code, msg = health_monitor.check_retention(
        db_path=db, marker_paths=(marker,)
    )
    assert code == 0
    assert "markers fresh" in msg


def test_marker_unreadable_fails(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    _make_db(db, None)
    marker = tmp_path / "retention_last_run.json"
    marker.write_text("{not json", encoding="utf-8")
    code, msg = health_monitor.check_retention(
        db_path=db, marker_paths=(marker,)
    )
    assert code == 1
    assert "unreadable" in msg
