"""c1-1 — curriculum-mode persona routing on the WS chat relay.

Design: PR-D-c1 v0.3 §2.2 (flag contract) / §3 (week authority, fallback
table) / §6.2 (change points). One case per hard check HC-A…HC-G (§6.3, D10).

The relay is driven at frame level (`_inject_persona` + `_start_turn`), so
these tests need no socket, no upstream dial and no engine — none of the
decisions under test involve them.

HC-C / HC-F also read `deeptutor/personas/` in the repo. c1-1 lands before the
persona files do (c1-2), so until they arrive the file half of the pin is
skipped; once they land, the same tests assert all 16 are present.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from auth import ws_chat as ws_chat_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONAS_DIR = REPO_ROOT / "deeptutor" / "personas"

BAND = "p4-p6"
BAND_PERSONA = "dibi-p4-p6"
P1_P3_PERSONA = "dibi-p1-p3"
STUDENT_MASK = "abcd1234"
STUDENT_ID = "full-student-id-never-outward"
WEEK_SLUG_WK03 = "dibi-curriculum-p4-p6-wk03"
WEEK_SLUG_WK08 = "dibi-curriculum-p4-p6-wk08"

#: v0.3 §4.3 — the 16 personas wired in c1-2 (p4-p6 wk01-08 + s1-s3 wk01-08)
ALL_SLUGS = frozenset(
    f"dibi-curriculum-{band}-wk{week:02d}"
    for band in ("p4-p6", "s1-s3")
    for week in range(1, 9)
)


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _badge(state: str = "active", week_index: int | None = 3):
    return {
        "state": state,
        "week_index": week_index,
        "total_weeks": 8,
        "unit_title": "Unit",
    }


def _router(*, band: str = BAND, persona: str = BAND_PERSONA, badge=None, raises=False):
    def badge_fn(student_id: str):
        assert student_id == STUDENT_ID
        if raises:
            raise RuntimeError("badge db down")
        return _badge() if badge is None else badge

    return ws_chat_mod._PersonaRouter(band, persona, STUDENT_ID, badge_fn=badge_fn)


def _turn(**extra) -> str:
    frame = {"type": "message", "content": "hello", "message_id": "m-hc"}
    frame.update(extra)
    return json.dumps(frame)


def _inject(raw: str, *, persona: str = BAND_PERSONA, router=None) -> dict:
    return json.loads(ws_chat_mod._inject_persona(raw, persona, router=router))


def _relay(*, persona: str = BAND_PERSONA, band: str = BAND, badge=None, raises=False):
    relay = ws_chat_mod._ChatRelay(
        ws=object(),
        session=None,
        upstream_url="ws://unused/",
        persona=persona,
        band=band,
        student_mask=STUDENT_MASK,
        student_id=STUDENT_ID,
        language="zh-hk",
    )
    relay._router = _router(band=band, persona=persona, badge=badge, raises=raises)
    return relay


# --- HC-A ------------------------------------------------------------------
def test_hc_a_unknown_mode_value_is_ignored_never_guessed():
    """HC-A: only the exact flag value routes; anything else keeps the band
    persona — and the flag is consumed either way."""
    router = _router()

    out = _inject(_turn(dibi_mode="homework"), router=router)
    assert out["persona"] == BAND_PERSONA
    assert "dibi_mode" not in out

    out = _inject(_turn(dibi_mode=7), router=router)
    assert out["persona"] == BAND_PERSONA
    assert "dibi_mode" not in out


# --- HC-B ------------------------------------------------------------------
def test_hc_b_week_comes_from_the_server_not_the_frame():
    """HC-B: the client only says *that* it is in curriculum mode.

    A frame claiming week 8 against a server-side week 3 must still be routed
    to the week-3 persona: the week number is never read from the wire.
    """
    router = _router(badge=_badge(state="active", week_index=3))

    out = _inject(
        _turn(dibi_mode="curriculum", week=8, curriculum_week=8, week_index=8),
        router=router,
    )

    assert out["persona"] == WEEK_SLUG_WK03


# --- HC-C ------------------------------------------------------------------
def test_hc_c_slug_allowlist_is_frozen_to_the_16_shipped_personas():
    """HC-C: the relay may only stamp slugs from the frozen 16-item allowlist,
    and the repo may only ever hold none of them (c1-1) or all 16 (c1-2)."""
    assert ws_chat_mod._CURRICULUM_PERSONA_SLUGS == ALL_SLUGS
    assert len(ALL_SLUGS) == 16

    # P1-P3 is deliberately unwired: those students keep the band persona
    assert ws_chat_mod._curriculum_slug("p1-p3", 1) is None
    # a week / value the curriculum does not have can never be stamped
    assert ws_chat_mod._curriculum_slug(BAND, 9) is None
    assert ws_chat_mod._curriculum_slug(BAND, 0) is None
    assert ws_chat_mod._curriculum_slug(None, 3) is None

    present = {slug for slug in ALL_SLUGS if (PERSONAS_DIR / slug / "PERSONA.md").is_file()}
    assert present in (set(), set(ALL_SLUGS)), "half-copied persona set"


# --- HC-D ------------------------------------------------------------------
def test_hc_d_guard_falls_back_to_the_band_persona():
    """HC-D: hidden badge, out-of-range week, raising lookup, unwired band —
    every one of them keeps the band persona, none of them raises."""
    assert _router(badge=_badge("none", None)).slug_for("curriculum") == BAND_PERSONA
    assert _router(badge=_badge("active", 9)).slug_for("curriculum") == BAND_PERSONA
    assert _router(badge=_badge("active", None)).slug_for("curriculum") == BAND_PERSONA
    assert _router(badge=_badge("weird", 3)).slug_for("curriculum") == BAND_PERSONA
    assert _router(raises=True).slug_for("curriculum") == BAND_PERSONA
    assert (
        _router(band="p1-p3", persona=P1_P3_PERSONA).slug_for("curriculum")
        == P1_P3_PERSONA
    )

    # the healthy edge: a finished course routes to its last week
    assert (
        _router(badge=_badge("completed", 8)).slug_for("curriculum") == WEEK_SLUG_WK08
    )


# --- HC-E ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hc_e_turn_start_audit_carries_mode_words_only(monkeypatch):
    """HC-E (red-line 8): the audit row proves the route with mode/slug words
    and keeps the masked prefix — the full student id never leaves the server."""
    recorded = []
    monkeypatch.setattr(
        ws_chat_mod.relay_audit,
        "record",
        lambda event, **kwargs: recorded.append((event, kwargs)),
    )

    relay = _relay()
    relay._router.reset_route()
    raw = _turn(message_id="m-hc-e", dibi_mode="curriculum")
    injected = ws_chat_mod._inject_persona(raw, relay.persona, router=relay._router)
    await relay._start_turn(injected)

    rows = [
        kwargs
        for event, kwargs in recorded
        if event == ws_chat_mod.relay_audit.EVENT_TURN_START
    ]
    assert len(rows) == 1
    detail = rows[0]["detail"]
    assert "mode=curriculum" in detail
    assert f"slug={WEEK_SLUG_WK03}" in detail
    assert rows[0]["student_mask"] == STUDENT_MASK
    assert STUDENT_ID not in detail
    assert STUDENT_ID not in injected


# --- HC-F ------------------------------------------------------------------
def _manifest_entries() -> dict:
    """Parse the persona hash manifest that ships next to the persona dirs."""
    text = (PERSONAS_DIR / "README.md").read_text(encoding="utf-8")
    entries = {}
    for match in re.finditer(r"`(personas/[^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-f]{64})`", text):
        entries[match.group(1)] = (int(match.group(2)), match.group(3))
    return entries


def test_hc_f_shipped_persona_files_match_the_manifest_and_are_english_only():
    """HC-F: the 16 persona files reproduce the hash manifest they ship with.

    Hashes are LF-normalised, so the pin holds whatever `core.autocrlf` does to
    a working copy — the manifest is the same "before" table c1-2 is reviewed
    against. The Chinese reference version is deliberately *not* checked here:
    §4.4 keeps it out of the engine's persona dirs.
    """
    manifest_path = PERSONAS_DIR / "README.md"
    if not manifest_path.is_file():
        pytest.skip("persona manifest + files land with c1-2")

    manifest = _manifest_entries()
    for slug in sorted(ALL_SLUGS):
        path = PERSONAS_DIR / slug / "PERSONA.md"
        assert path.is_file(), f"missing persona file: {slug}"

        text = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        payload = text.encode("utf-8")
        size, digest = manifest[f"personas/{slug}/PERSONA.md"]
        assert len(payload) == size, f"{slug}: {len(payload)} B != manifest {size} B"
        assert hashlib.sha256(payload).hexdigest() == digest, f"{slug}: hash != manifest"
        assert not _has_cjk(text), f"{slug}: persona file carries CJK"


# --- HC-G ------------------------------------------------------------------
def test_hc_g_flag_never_reaches_the_engine():
    """HC-G: `dibi_mode` is a relay control word — consumed on the way in and
    absent from everything forwarded upstream."""
    router = _router()

    for extra in ({"dibi_mode": "curriculum"}, {"dibi_mode": "homework"}, {"dibi_mode": None}):
        assert "dibi_mode" not in _inject(_turn(**extra), router=router)

    # non-turn frames keep the pre-c1-1 verbatim path (F-5)
    sub = '{"type":"tool_result","dibi_mode":"curriculum"}'
    assert ws_chat_mod._inject_persona(sub, BAND_PERSONA, router=router) == sub

    # a flag-less turn frame is still returned byte-identical (no re-dump)
    raw = _turn(persona=BAND_PERSONA)
    assert ws_chat_mod._inject_persona(raw, BAND_PERSONA, router=router) == raw

    # pre-c1-1 call shape still stamps the band persona
    assert _inject(_turn(), router=None)["persona"] == BAND_PERSONA
