"""Hygiene (test sink) — the suite must never touch the production audit trail.

Root cause this file exists for: ``auth/consent.py`` resolves its default sink
once at import time (``DREAMER_AUDIT_LOG_PATH`` → ``<repo>/audit_log.jsonl``),
so any test that drives an audited code path without monkeypatching the
constant appended rows to the repo-wide append-only trail — a local working
tree that never stayed clean, and a red-line #3 (audit append-only) smell.

Two layers now guard it:

  1. ``tests/conftest.py::_isolate_audit_log_sink`` (session-scoped, autouse)
     redirects ``consent.AUDIT_LOG_PATH`` to a tmp sink for the whole run;
  2. this file pins the guarantee down — resolved sink lives outside the repo,
     writes land in the sink, and ``<repo>/audit_log.jsonl`` stays untouched.

The ``phase2-tests`` CI job adds a third, blunt layer after pytest (ci.yml):
``test ! -e audit_log.jsonl`` plus ``git diff --name-only`` empty, which
catches any sink we forgot to enumerate here. Red line #9: the guard test is
registered in the CI manifest, so it actually runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from auth import consent as consent_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_TRAIL = REPO_ROOT / "audit_log.jsonl"


def _production_trail_bytes():
    """Snapshot the repo trail: None when it does not exist at all."""
    return PRODUCTION_TRAIL.read_bytes() if PRODUCTION_TRAIL.exists() else None


def test_resolved_sink_is_redirected_outside_the_repo():
    sink = Path(consent_mod.AUDIT_LOG_PATH).resolve()
    assert sink != PRODUCTION_TRAIL, (
        "audit sink still points at the repo trail — the conftest isolation "
        "fixture did not run"
    )
    assert REPO_ROOT not in sink.parents, f"test sink must live outside {REPO_ROOT}"


def test_default_sink_constant_is_the_repo_trail():
    """Sanity: if this changes, the guard above is testing the wrong thing."""
    from auth import consent as fresh_consent  # noqa: PLC0415 (explicit re-read)

    assert fresh_consent.DEFAULT_AUDIT_LOG_PATH == str(PRODUCTION_TRAIL)


def test_write_lands_in_sink_and_leaves_production_trail_untouched():
    before = _production_trail_bytes()

    consent_mod.write_audit_log(
        {"event": "hygiene_probe", "message": "test sink guard"}
    )

    sink = Path(consent_mod.AUDIT_LOG_PATH)
    assert sink.exists(), "write_audit_log did not write to the resolved sink"
    rows = [
        json.loads(line)
        for line in sink.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row.get("event") == "hygiene_probe" for row in rows), rows

    assert _production_trail_bytes() == before, (
        "tests appended to <repo>/audit_log.jsonl — production trail polluted"
    )
