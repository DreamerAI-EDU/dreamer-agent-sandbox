"""W3-A — WS chat handshake gate + DeepTutor upstream relay (dreamer-api side).

Real WS chat replaces the frontend mock (W3-A work instruction v1.0 §4).
Every gate runs server-side BEFORE the connection upgrades; a failure
rejects at the HTTP layer (JSON + status) with a WARNING audit trail —
never an upgrade-then-kick, never a client-side-only decision.

Gate order (spec v1.4 §1.1, same state sources as pin-verify):
    1. auth      — auth_session cookie resolves to a live user
    2. role      — only `parent` may open a kid chat (Q4: a teacher or
                   admin session opening a chat as a student is refused;
                   teacher watch/join flows are out of W3-A scope)
    3. ownership — the student identifier belongs to this parent; the
                   query carries the 8-char masked prefix (full student
                   ids never leave the server — W2 PR#3 rule), resolved
                   inside the caller's reachable set
    4. class     — classes.student_class_confirmed() (the single shared
                   decision with pin-verify — never a second copy)
    5. consent   — the student may open AI chat (W6 PR-C2 decoupled:
                   the gate hangs off chat_consent, not media_consent).
                   Default-deny (PR-D, yaml chat_consent required: true):
                   a current-version agreed row must cover the student —
                   unsigned / withdrawn / stale version all refuse. Before
                   the flip (required: false) the legacy rule applies:
                   only an explicit chat_consent withdrawal refuses.

On success the request upgrades and frames relay bidirectionally to the
DeepTutor unified endpoint (/api/v1/ws). One chat connection = one
upstream connection; server-assigned session ids are relayed untouched.
P2 — every turn-bearing frame (type = message / start_turn) is re-stamped
with the persona derived from the student's DB `age_band` (the band does
not travel in any client payload). A student without a band is relayed
unchanged, so the engine's empty-persona behaviour stays the fallback.

P3 — relay resilience (boss-approved scope, 2026-09-14). Three behaviours,
none of which touch the engine or the DB schema of any existing table:

* retry    — an upstream 429 is re-sent **only while the child has seen
             nothing** (no content chunk forwarded yet). Once any answer text
             is on screen the turn is never re-sent: duplicate sentences are a
             confusion-grade experience for a child, while "please ask again"
             is a small nuisance. Re-sending after content would need a
             frontend clear-and-redraw, which is cross-boundary and stays out
             of this PR (post-launch enhancement PR, with UX design).
* watchdog — the upstream staying silent for 90s **while a turn is open and
             the relay has received zero frames in that window** ends the turn.
             Idle-based, never an absolute turn deadline: a legitimate long
             turn (deep reasoning / many tool calls) keeps emitting frames and
             is never killed.
* audit    — turn start/end, every retry attempt (with its number), every
             non-retry mid-stream failure and every watchdog kill land in
             ws_chat_relay_audit (auth/relay_audit.py), each with an
             `upstream_error` code. Never success-only.

A non-retry mid-stream failure is never silent: the student always gets a
localized graceful message instead of half an answer hanging on screen. The
failed turn's remaining upstream frames (a second error, a late `done`) are
then swallowed — they must not trail raw provider text onto that screen or
re-open a turn that is already closed.

P4 — student session continuity (boss-approved scope, 2026-09-15, spec
handover v4.1 §4.1 relay layer). One engine session per student, owned by
the relay:

* blanket rewrite — every client frame carrying a ``session_id`` field has
  it replaced by the relay's mapping (or removed when no mapping exists), so
  a client can never pick another student's session (IDOR) nor forge its
  own. Structural fix, not validation.
* session map — ``ws_chat_session_map`` (business table, student_id PK,
  red-line 8 ruling 2026-09-15) remembers which engine session belongs to
  which student across WS connections, page refreshes and API restarts. The
  engine's ``session`` frame upserts it; a dead session (engine rejects it)
  invalidates it and the next turn opens a fresh one (self-healing).
* busy — an upstream refusal because the session already has an active turn
  (second tab) is non-retryable under its own code ``session_busy``, with
  markers deliberately disjoint from the rate-limit set so the 429 budget
  and the audit trail stay clean.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

from . import api as api_mod
from . import classes as classes_mod
from . import consent as consent_mod
from . import db
from . import relay_audit
from . import students as students_mod

logger = logging.getLogger("dreamer.auth.ws_chat")

_UPSTREAM_CONNECT_TIMEOUT = 30.0  # seconds for the upstream WS connect


def _read_upstream_config() -> dict:
    """DeepTutor unified WS endpoint config (config/ws_client.yaml).

    Mirrors agents/deeptutor_ws.py resolution (scheme://host:port+path)
    but reads the YAML directly so this auth package stays independent of
    the heavy `agents` package import graph. env override for tests.
    """
    override = os.environ.get("DEEPTUTOR_WS_URL")
    if override:
        return {"scheme": "ws", "host": "override", "port": 0, "path": "", "_url": override}
    try:
        import yaml

        cfg_path = (
            Path(__file__).resolve().parent.parent / "config" / "ws_client.yaml"
        )
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return dict(data.get("deeptutor_ws") or {})
    except (OSError, yaml.YAMLError):
        return {}


def _upstream_ws_url() -> str:
    """Resolve the upstream DeepTutor WS URL for this relay connection."""
    cfg = _read_upstream_config()
    url = cfg.get("_url")
    if url:
        return str(url)
    scheme = cfg.get("scheme", "ws")
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8001)
    path = cfg.get("path", "/api/v1/ws")
    return f"{scheme}://{host}:{port}{path}"


# ---------------------------------------------------------------------------
# Handshake helpers
# ---------------------------------------------------------------------------

def _reject(
    status: int,
    error_body: dict,
    *,
    gate: str,
    user_id: str,
    target_id: Optional[str] = None,
) -> web.Response:
    """HTTP-layer handshake rejection + WARNING audit trail.

    The gate name goes to the server-side audit only; the HTTP body keeps
    the unified wording used across the auth API so callers cannot learn
    which guard fired (no id-oracle / gate-oracle).
    """
    api_mod._log_security_warning(
        "ws_chat_rejected",
        user_id=user_id,
        target_id=target_id,
        detail=f"handshake gate={gate}",
    )
    return web.json_response(error_body, status=status)


async def _close_quietly(ws) -> None:
    try:
        await ws.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# P2 — age-band persona injection
# ---------------------------------------------------------------------------

#: students.age_band -> DeepTutor persona slug (deeptutor/personas/<slug>/)
_PERSONA_BY_BAND = {
    "p1-p3": "dibi-p1-p3",
    "p4-p6": "dibi-p4-p6",
    "s1-s3": "dibi-s1-s3",
}

#: frames that open or carry a turn (match the unified_ws dispatch table)
_TURN_FRAME_TYPES = ("message", "start_turn")


def _row_get(row, key):
    """sqlite3.Row-safe accessor (Row raises rather than returning None)."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _persona_for_student(student) -> Optional[str]:
    """Resolve the persona slug from the student row resolved by the gate.

    age_band is read from the DB row — never from the query string or a
    client frame — so a tampered request cannot move a student onto
    another band's persona. Unknown / missing band -> None (no injection).
    """
    band = _row_get(student, "age_band")
    if not band:
        return None
    return _PERSONA_BY_BAND.get(str(band).strip().lower().replace("\u2013", "-"))


def _inject_persona(raw: str, persona: Optional[str]) -> str:
    """Return the frame unchanged unless it is a turn frame needing persona."""
    if not persona:
        return raw
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return raw  # not JSON — forward verbatim
    if not isinstance(frame, dict) or frame.get("type") not in _TURN_FRAME_TYPES:
        return raw
    if frame.get("persona") == persona:
        return raw
    frame["persona"] = persona
    return json.dumps(frame, ensure_ascii=False)


# ---------------------------------------------------------------------------
# P3 — relay resilience: pre-content retry, idle watchdog, audit
# ---------------------------------------------------------------------------

#: frames that terminate a turn upstream (mirror of the unified_ws dispatch)
_TERMINAL_FRAME_TYPES = ("done", "error")

#: upstream frame types that put visible text in front of the child. `progress`
#: carries the kid-friendly stage note, so it counts as visible too: once one
#: of these has been forwarded, the turn must never be re-sent.
_VISIBLE_FRAME_TYPES = ("content", "progress")

#: how long the upstream may stay silent *inside an open turn* before the
#: watchdog reaps it. Idle-based (boss review condition 2): the timer restarts
#: on every upstream frame and only runs while a turn is open, so a long but
#: live turn (deep reasoning / many tool calls) is never killed. Never an
#: absolute turn deadline.
_IDLE_WATCHDOG_SECONDS = 90.0

#: retry delays, one entry per attempt; length == retry budget (pre-content only)
_RETRY_BACKOFF_SECONDS = (1.5, 4.0)

#: 429 / quota wording seen in the wild. DeepTutor relays the provider error
#: text through an `error` frame, so match on markers rather than a fixed
#: string — and only inside an `error` frame, so a legitimate content frame
#: that happens to contain "429" can never be mistaken for a limit rejection.
_RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "resource_exhausted",
    "resourceexhausted",
    "quota",
)

#: P4 — upstream wording that means "this engine session already has an
#: active turn" (same student, second tab). Deliberately disjoint from
#: _RATE_LIMIT_MARKERS (boss condition 3): busy never spends the retry
#: budget and is audited under its own upstream_error code.
_BUSY_MARKERS = (
    "already has an active",
    "active turn",
    "turn in progress",
)

#: P4 — upstream wording that means the engine no longer knows the session
#: it was routed to (expired / evicted / never existed). The mapping is
#: stale: it is dropped and the next turn opens a fresh session instead.
_SESSION_INVALID_MARKERS = (
    "session not found",
    "session_not_found",
    "invalid session",
    "session expired",
    "session_expired",
)

#: localized "we are busy, please ask again" copy (review condition 1)
_GRACEFUL_BUSY_COPY = {
    "zh-hk": "Dibi 而家有啲忙，請再問一次。",
    "zh-cn": "Dibi 现在有点忙，请再问一次。",
    "en": "Dibi is a bit busy right now — please ask again.",
}

_DEFAULT_LANGUAGE = "zh-hk"

#: unchanged copy for "the relay cannot reach the engine at all"
_UPSTREAM_UNAVAILABLE_COPY = "連線暫時不可用，請稍後再試"

#: internal upstream_error code -> client error_code (the frontend maps every
#: upstream error onto the kid copy it already owns; this keeps the wire
#: vocabulary honest for logs and for non-frontend clients)
_CLIENT_ERROR_CODE = {
    relay_audit.ERR_RATE_LIMITED: "upstream_rate_limited",
    relay_audit.ERR_UPSTREAM_ERROR: "upstream_error",
    relay_audit.ERR_UPSTREAM_CLOSED: "upstream_unavailable",
    relay_audit.ERR_IDLE_TIMEOUT: "upstream_idle_timeout",
    relay_audit.ERR_CONNECT_FAILED: "upstream_unavailable",
    relay_audit.ERR_SESSION_BUSY: "session_busy",
}


def _env_positive_float(name: str, default: float) -> float:
    """Deploy-time knob: override a relay timing constant via env."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _idle_watchdog_seconds() -> float:
    return _env_positive_float(
        "WS_CHAT_IDLE_WATCHDOG_SECONDS", _IDLE_WATCHDOG_SECONDS
    )


def _retry_backoff_seconds() -> tuple:
    """Retry delays; WS_CHAT_RETRY_BACKOFF (comma-separated) for tests/ops."""
    raw = os.environ.get("WS_CHAT_RETRY_BACKOFF")
    if not raw:
        return _RETRY_BACKOFF_SECONDS
    try:
        values = tuple(float(p) for p in raw.split(",") if p.strip())
        return values or _RETRY_BACKOFF_SECONDS
    except ValueError:
        return _RETRY_BACKOFF_SECONDS


def _normalise_language(language: Optional[str]) -> str:
    lang = (language or "").strip().lower().replace("_", "-")
    if lang.startswith("zh"):
        return "zh-cn" if ("cn" in lang or "hans" in lang) else "zh-hk"
    if lang.startswith("en"):
        return "en"
    return _DEFAULT_LANGUAGE


def _parse_frame(raw) -> dict:
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return frame if isinstance(frame, dict) else {}


def _looks_rate_limited(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def _is_rate_limit_frame(raw: str) -> bool:
    """True only for an upstream `error` frame that reads as 429 / quota."""
    return _parse_frame(raw).get("type") == "error" and _looks_rate_limited(raw)


def _looks_busy(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BUSY_MARKERS)


def _is_busy_frame(raw: str) -> bool:
    """True only for an upstream `error` frame that reads as busy.

    Busy = this engine session already has an active turn (second tab).
    Never retried (disjoint from rate limits) — the child gets the same
    "please ask again" copy and the 429 budget stays untouched.
    """
    return _parse_frame(raw).get("type") == "error" and _looks_busy(raw)


def _looks_session_invalid(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _SESSION_INVALID_MARKERS)


def _frame_session_id(frame: dict) -> Optional[str]:
    """Session id from an upstream frame: top-level or inside metadata.

    DeepTutor announces a (re)assigned session with a `session` frame; the
    id appears either on the frame or in its metadata blob depending on the
    engine version, so both are read.
    """
    sid = frame.get("session_id")
    if not isinstance(sid, str) or not sid:
        meta = frame.get("metadata")
        if isinstance(meta, dict):
            sid = meta.get("session_id")
    return sid if isinstance(sid, str) and sid else None


def _error_code_of(frame: dict) -> Optional[str]:
    """Upstream's own error code, normalised for an append-only record.

    Whatever the provider sends is untrusted text: keep a short,
    charset-limited token (or nothing at all), so prose or a stack trace can
    never land in the audit table's ``upstream_error`` column.
    """
    code = frame.get("error_code") or frame.get("code")
    if not isinstance(code, str):
        return None
    token = re.sub(r"[^a-z0-9_.:-]+", "_", code.strip().lower())
    token = token[:64].strip("_.:-")
    return token or None


class _TurnInFlight:
    """Relay-side view of one turn (one relayed client frame that opens a turn).

    Everything the retry/watchdog decisions need, and nothing else: how many
    retries are already spent, whether the child has seen any text yet, and the
    engine-side ids so the audit row can be joined back to a session.
    """

    __slots__ = (
        "raw_frame",
        "language",
        "student_mask",
        "attempt",
        "content_emitted",
        "session_id",
        "turn_id",
    )

    def __init__(self, raw_frame: str, language: str, student_mask: str) -> None:
        self.raw_frame = raw_frame
        self.language = _normalise_language(language)
        self.student_mask = student_mask or ""
        self.attempt = 0  # retries already spent on this turn
        self.content_emitted = False  # any visible frame forwarded?
        self.session_id: Optional[str] = None
        self.turn_id: Optional[str] = None


class _ChatRelay:
    """One client <-> DeepTutor chat connection.

    Frames are forwarded verbatim (after the P2 persona re-stamp) with the P3
    behaviours layered on top. The relay owns both directions explicitly rather
    than using two blind pumps, because the retry / watchdog / audit decisions
    only exist where both the upstream error and the child's screen are known.
    """

    def __init__(
        self,
        *,
        ws,
        session,
        upstream_url: str,
        persona: Optional[str],
        student_mask: str,
        student_id: str,
        language: Optional[str],
    ) -> None:
        self.ws = ws
        self.session = session
        self.upstream_url = upstream_url
        self.persona = persona
        self.student_mask = student_mask or ""
        # P4: full student id, server-internal only — drives the session map
        # lookup. Never leaves the relay (red-line 8: no logs, no audit, no
        # frames); every outward surface keeps using student_mask.
        self.student_id = student_id
        self.language = _normalise_language(language)
        self._upstream = None
        self._turn: Optional[_TurnInFlight] = None
        self._draining = False  # discarding the tail of an already-failed turn
        # set when a *poisoned* upstream socket is dropped on purpose (review
        # 裁決 A, graceful stop): the reader must not retry on it — there is no
        # turn left to save and the child's next turn dials a fresh socket.
        self._upstream_dropped = False
        self._backoff = _retry_backoff_seconds()
        self._idle_timeout = _idle_watchdog_seconds()

    # -- connection --------------------------------------------------------

    async def _dial(self):
        """Open a fresh upstream socket. Returns (ws, error_code)."""
        try:
            upstream = await self.session.ws_connect(
                self.upstream_url,
                heartbeat=30.0,
                timeout=aiohttp.ClientWSTimeout(
                    ws_close=_UPSTREAM_CONNECT_TIMEOUT
                ),
            )
            return upstream, None
        except Exception as exc:  # connect refused / timeout / DNS / 429
            logger.warning(
                "ws_chat upstream connect failed url=%s err=%s",
                self.upstream_url,
                exc,
            )
            code = (
                relay_audit.ERR_RATE_LIMITED
                if _looks_rate_limited(str(exc))
                else relay_audit.ERR_CONNECT_FAILED
            )
            return None, code

    async def _ensure_upstream(self) -> bool:
        if self._upstream is not None and not self._upstream.closed:
            return True
        self._upstream, _ = await self._dial()
        if self._upstream is not None:
            # a live socket is a clean slate again (review 裁決 A)
            self._upstream_dropped = False
        return self._upstream is not None

    async def run(self) -> None:
        upstream, code = await self._dial()
        if upstream is None:
            await self._upstream_unavailable(code)
            return
        self._upstream = upstream

        client_task = asyncio.ensure_future(self._client_loop())
        upstream_task = asyncio.ensure_future(self._upstream_loop())
        done, pending = await asyncio.wait(
            {client_task, upstream_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # Teardown reap: a turn still open here means the child's answer died
        # with the upstream socket — record it instead of a silent zombie row.
        # (A client-side end reaps its own turn and clears it, so reaching this
        # line with a turn open means the upstream leg ended first.)
        await self._reap_turn("relay_teardown", relay_audit.ERR_UPSTREAM_CLOSED)
        self._upstream = None
        await _close_quietly(upstream)

    # -- client -> upstream -------------------------------------------------

    # -- P4 session map (ws_chat_session_map) -------------------------------
    # One engine session per student, owned by the relay. The map is what the
    # blanket rewrite below trusts; the client never supplies a session id.

    def _load_mapping(self) -> Optional[str]:
        """Engine session for this student (None = none yet / stale dropped)."""
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT engine_session FROM ws_chat_session_map "
                "WHERE student_id = ?",
                (self.student_id,),
            ).fetchone()
        finally:
            conn.close()
        return str(row["engine_session"]) if row is not None else None

    def _save_mapping(self, engine_session: str) -> None:
        """Record the engine-assigned session (atomic upsert, created kept).

        SQLite serializes writers, so the rare two-tabs-open-a-fresh-session
        race cannot interleave: the last upsert wins and the earlier engine
        session becomes an orphan the map no longer references — harmless,
        the next turn already routes through this row (boss condition 1).
        """
        now = db._now_iso()
        conn = db.connect()
        try:
            conn.execute(
                """INSERT INTO ws_chat_session_map
                   (student_id, engine_session, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(student_id) DO UPDATE SET
                       engine_session = excluded.engine_session,
                       updated_at = excluded.updated_at""",
                (self.student_id, engine_session, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "ws_chat session map saved mask=%s session_len=%s",
            self.student_mask,
            len(engine_session),
        )

    def _invalidate_mapping(self, reason: str) -> None:
        """Drop this student's map row + audit (mask only, red-line 8).

        Fires when the engine rejects a turn because the routed session no
        longer exists. The next turn then carries no session_id and the
        engine opens a fresh one — the self-healing path. The audit event is
        what makes "Dibi 唔記得昨日嘅嘢" diagnosable as map failure vs engine
        problem (boss condition 2).
        """
        conn = db.connect()
        try:
            conn.execute(
                "DELETE FROM ws_chat_session_map WHERE student_id = ?",
                (self.student_id,),
            )
            conn.commit()
        finally:
            conn.close()
        relay_audit.record(
            relay_audit.EVENT_SESSION_MAP_INVALIDATED,
            student_mask=self.student_mask,
            detail=f"reason={reason}",
        )
        logger.warning(
            "ws_chat session map invalidated mask=%s reason=%s",
            self.student_mask,
            reason,
        )

    def _restamp_session(self, raw: str) -> str:
        """P4: blanket session_id rewrite — never trust the client.

        Any client frame carrying a ``session_id`` field gets it replaced by
        the relay's own mapping, or removed when no mapping exists yet so the
        engine assigns a fresh session. Structural fix, not validation:
        there is no "client got it right, let it through" path left for the
        IDOR surface (new frame types included).
        """
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        if not isinstance(frame, dict) or "session_id" not in frame:
            return raw
        mapped = self._load_mapping()
        if mapped is None:
            frame.pop("session_id", None)
        else:
            frame["session_id"] = mapped
        return json.dumps(frame, ensure_ascii=False)

    async def _client_loop(self) -> None:
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._on_client_frame(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    if not await self._send_upstream(msg.data, binary=True):
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.warning(
                        "ws_chat relay client error: %s", self.ws.exception()
                    )
                    break
                else:  # CLOSE / CLOSING / CLOSED
                    break
        except (aiohttp.ClientConnectionError, ConnectionResetError):
            pass
        finally:
            # The child is gone: nothing can be shown any more, so an open turn
            # is reaped and the upstream socket is released.
            await self._reap_turn("client_closed")
            upstream = self._upstream
            self._upstream = None
            await _close_quietly(upstream)

    async def _on_client_frame(self, raw: str) -> None:
        # P4: every client frame is session-restamped before anything else —
        # turn frames and subscribe/cancel alike, blanket by field.
        raw = self._restamp_session(raw)
        injected = _inject_persona(raw, self.persona)
        if _parse_frame(injected).get("type") in _TURN_FRAME_TYPES:
            await self._start_turn(injected)
        if not await self._send_upstream(injected):
            logger.warning("ws_chat relay could not forward a client frame")

    async def _start_turn(self, raw: str) -> None:
        if self._turn is not None:
            # client opened a new turn while the previous one never finished
            await self._reap_turn("superseded_by_new_turn")
        # the child is talking again: any leftover tail of an older turn stops
        # being ours to swallow
        self._draining = False
        turn = _TurnInFlight(
            raw_frame=raw,
            language=self.language,
            student_mask=self.student_mask,
        )
        self._turn = turn
        frame_type = _parse_frame(raw).get("type")
        relay_audit.record(
            relay_audit.EVENT_TURN_START,
            student_mask=self.student_mask,
            detail=f"frame_type={frame_type}",
        )

    async def _send_upstream(self, payload, *, binary: bool = False) -> bool:
        if not await self._ensure_upstream():
            return False
        try:
            if binary:
                await self._upstream.send_bytes(payload)
            else:
                await self._upstream.send_str(payload)
            return True
        except (aiohttp.ClientConnectionError, ConnectionResetError, RuntimeError) as exc:
            logger.warning("ws_chat relay upstream send failed: %s", exc)
            self._upstream = None
            return False

    # -- upstream -> client -------------------------------------------------

    async def _upstream_loop(self) -> None:
        while True:
            upstream = self._upstream
            if upstream is None or upstream.closed:
                if self._upstream_dropped:
                    # Review 裁決 A: the poisoned socket was discarded on
                    # purpose after a graceful stop — there is no turn left to
                    # save and no tail worth reading. Ending the relay here
                    # keeps this leg identical to a watchdog kill; the child's
                    # next question opens a fresh stream (and a fresh dial).
                    return
                if not await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED):
                    return
                continue

            # Idle-based watchdog: the timeout only arms while a turn is open,
            # and it restarts on every frame (review condition 2).
            timeout = self._idle_timeout if self._turn is not None else None
            try:
                msg = await asyncio.wait_for(upstream.receive(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._watchdog_kill()
                return
            except (aiohttp.ClientConnectionError, ConnectionResetError) as exc:
                logger.warning("ws_chat upstream receive failed: %s", exc)
                self._upstream = None
                if not await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED):
                    return
                continue

            if msg.type == aiohttp.WSMsgType.TEXT:
                if await self._on_upstream_text(msg.data):
                    continue
                await self._forward(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await self._forward(msg.data, binary=True)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning(
                    "ws_chat upstream error: %s", upstream.exception()
                )
                self._upstream = None
                if not await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED):
                    return
                continue
            else:  # CLOSE / CLOSING / CLOSED
                self._upstream = None
                if not await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED):
                    return
                continue

    async def _on_upstream_text(self, raw: str) -> bool:
        """Handle one upstream frame. True when the relay consumed it."""
        turn = self._turn
        frame = _parse_frame(raw)

        # After a graceful stop that turn's screen is closed for good: nothing
        # the upstream still says about it may follow the localized message —
        # raw provider text would trail it, a late `done` would re-open a turn
        # that is already over. The drain ends when the child starts a new turn
        # (a fresh engine answer can only follow the frame that asked for it).
        if self._draining:
            return True

        # P4: the engine announced a (possibly fresh) session for this
        # student — remember it so later connections / tabs / refreshes route
        # to the same conversation. The frame is still forwarded to the child
        # (the frontend needs the id too).
        if frame.get("type") == "session":
            sid = _frame_session_id(frame)
            if sid:
                self._save_mapping(sid)

        if turn is not None:
            self._note_turn_metadata(turn, frame)

        if turn is not None and frame.get("type") == "error":
            # Every `error` frame of an open turn is consumed here, so the
            # provider's raw wording never reaches the child.
            if _is_rate_limit_frame(raw):
                if turn.content_emitted or turn.attempt >= len(self._backoff):
                    # Either the answer is already on screen (re-sending would
                    # duplicate text) or the budget is spent: fail gracefully.
                    await self._midstream_error(turn, relay_audit.ERR_RATE_LIMITED)
                else:
                    await self._retry_turn(turn, relay_audit.ERR_RATE_LIMITED)
            elif _is_busy_frame(raw):
                # P4: engine refused because this session already has an active
                # turn (second tab). Deliberately non-retryable: spending the
                # retry budget here would leak the 429 budget, and the audit
                # row keeps busy apart from rate_limited (boss condition 3).
                await self._midstream_error(
                    turn,
                    relay_audit.ERR_SESSION_BUSY,
                    detail="session_busy_non_retryable",
                )
            else:
                # Review Q: only `rate_limited` may spend retry budget. Any
                # other upstream error — 500, timeout, provider fault — is not
                # retried; it ends the turn with localized copy, and the dead
                # turn's tail is drained. `upstream_error` stays the normalized
                # vocabulary; the provider's own code rides along in `detail`.
                if _looks_session_invalid(raw):
                    # P4 self-heal: the routed session is dead — drop the map
                    # row so the next turn opens a fresh engine session
                    # instead of hitting the same wall (boss condition 2).
                    self._invalidate_mapping("engine_rejected_session")
                provider = _error_code_of(frame) or relay_audit.ERR_UPSTREAM_ERROR
                await self._midstream_error(
                    turn,
                    relay_audit.ERR_UPSTREAM_ERROR,
                    detail=f"non_retryable_error_frame provider={provider}",
                )
            return True  # the raw error frame never reaches the child

        if turn is not None and frame.get("type") in _TERMINAL_FRAME_TYPES:
            # Only `done` can reach this point: every `error` frame was handled
            # above (rate limits retried, everything else stopped gracefully).
            self._finish_turn(relay_audit.STATUS_COMPLETED, None)
        return False

    @staticmethod
    def _note_turn_metadata(turn: _TurnInFlight, frame: dict) -> None:
        session_id = frame.get("session_id")
        if isinstance(session_id, str) and session_id:
            turn.session_id = session_id
        turn_id = frame.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            turn.turn_id = turn_id
        if frame.get("type") in _VISIBLE_FRAME_TYPES:
            content = frame.get("content")
            if isinstance(content, str) and content.strip():
                turn.content_emitted = True

    async def _forward(self, data, *, binary: bool = False) -> None:
        try:
            if binary:
                await self.ws.send_bytes(data)
            else:
                await self.ws.send_str(data)
        except (
            aiohttp.ClientConnectionError,
            ConnectionResetError,
            RuntimeError,
        ) as exc:
            logger.warning("ws_chat client forward failed: %s", exc)
            upstream = self._upstream
            self._upstream = None
            await _close_quietly(upstream)

    # -- resilience decisions ----------------------------------------------

    async def _maybe_retry(self, code: str) -> bool:
        """Retry an invisible turn after an upstream drop. True = re-sent."""
        turn = self._turn
        if turn is None:
            return False
        if turn.content_emitted or turn.attempt >= len(self._backoff):
            await self._midstream_error(turn, code)
            return False
        return await self._retry_turn(turn, code)

    async def _retry_turn(self, turn: _TurnInFlight, code: str) -> bool:
        """Re-send the turn frame. False = the turn ended with a graceful note."""
        turn.attempt += 1
        delay = self._backoff[min(turn.attempt, len(self._backoff)) - 1]
        # review condition 3: the attempt number and its cause are always logged
        relay_audit.record(
            relay_audit.EVENT_TURN_RETRY,
            student_mask=self.student_mask,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            attempt=turn.attempt,
            upstream_error=code,
            detail=f"backoff={delay}s",
        )
        logger.warning(
            "ws_chat relay retry attempt=%s/%s code=%s mask=%s",
            turn.attempt,
            len(self._backoff),
            code,
            self.student_mask,
        )
        await asyncio.sleep(delay)
        if not await self._send_upstream(turn.raw_frame):
            await self._midstream_error(turn, relay_audit.ERR_CONNECT_FAILED)
            return False
        return True

    async def _midstream_error(
        self, turn: _TurnInFlight, code: str, *, detail: Optional[str] = None
    ) -> None:
        """Non-retry failure: never leave half an answer hanging (条件 1)."""
        relay_audit.record(
            relay_audit.EVENT_MIDSTREAM_ERROR,
            student_mask=self.student_mask,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            attempt=turn.attempt or None,
            upstream_error=code,
            detail=detail
            or (
                "content_already_streamed"
                if turn.content_emitted
                else "retry_budget_exhausted"
            ),
        )
        logger.warning(
            "ws_chat relay mid-stream failure code=%s streamed=%s mask=%s",
            code,
            turn.content_emitted,
            self.student_mask,
        )
        # Review 裁決 A: hang up on the poisoned upstream *before* the graceful
        # message. This turn's screen is closed for good and so is its pipe —
        # `_draining` alone only covers what the socket buffer already delivered:
        # the upstream was never cancelled, so its tail can arrive *after* the
        # child re-asks (the copy literally tells them to ask again now) and slip
        # into the new turn. Dropping the socket removes that window
        # structurally, exactly like _watchdog_kill (_upstream=None +
        # _close_quietly, next turn dials fresh). Doing it before any await also
        # means a new turn can never land its frame on an already-doomed socket.
        self._draining = True
        self._upstream_dropped = True
        upstream = self._upstream
        self._upstream = None
        await _close_quietly(upstream)
        await self._send_error_frame(
            code, turn.language, self._graceful_copy(code, turn.language)
        )
        # The child may have opened a new turn during the awaits above (asking
        # again without waiting for the error frame): only close *our* turn.
        if self._turn is turn:
            self._finish_turn(relay_audit.STATUS_FAILED, code)

    async def _watchdog_kill(self) -> None:
        turn = self._turn
        idle = self._idle_timeout
        relay_audit.record(
            relay_audit.EVENT_WATCHDOG_KILL,
            student_mask=self.student_mask,
            session_id=turn.session_id if turn else None,
            turn_id=turn.turn_id if turn else None,
            upstream_error=relay_audit.ERR_IDLE_TIMEOUT,
            detail=f"upstream_idle>{idle}s",
        )
        logger.warning(
            "ws_chat relay watchdog kill: upstream idle %.1fs with a turn open "
            "mask=%s",
            idle,
            self.student_mask,
        )
        upstream = self._upstream
        self._upstream = None
        await _close_quietly(upstream)
        if turn is not None:
            await self._send_error_frame(
                relay_audit.ERR_IDLE_TIMEOUT,
                turn.language,
                self._graceful_copy(relay_audit.ERR_IDLE_TIMEOUT, turn.language),
            )
            self._finish_turn(relay_audit.STATUS_FAILED, relay_audit.ERR_IDLE_TIMEOUT)

    async def _upstream_unavailable(self, code: Optional[str]) -> None:
        code = code or relay_audit.ERR_CONNECT_FAILED
        relay_audit.record(
            relay_audit.EVENT_UPSTREAM_UNAVAILABLE,
            student_mask=self.student_mask,
            upstream_error=code,
        )
        await self._send_error_frame(code, self.language, _UPSTREAM_UNAVAILABLE_COPY)

    async def _send_error_frame(self, code: str, language: str, content: str) -> None:
        """Hand the child a localized stop message (never a silent dead end)."""
        try:
            await self.ws.send_json(
                {
                    "type": "error",
                    "error_code": _CLIENT_ERROR_CODE.get(
                        code, "upstream_unavailable"
                    ),
                    "content": content,
                }
            )
        except Exception as exc:  # client already gone — the audit row stands
            logger.warning("ws_chat graceful error not delivered: %s", exc)

    @staticmethod
    def _graceful_copy(code: str, language: str) -> str:
        if code in (relay_audit.ERR_RATE_LIMITED, relay_audit.ERR_SESSION_BUSY):
            lang = _normalise_language(language)
            return _GRACEFUL_BUSY_COPY.get(lang) or _GRACEFUL_BUSY_COPY[_DEFAULT_LANGUAGE]
        return _UPSTREAM_UNAVAILABLE_COPY

    def _finish_turn(
        self,
        status: str,
        upstream_error: Optional[str] = None,
        *,
        detail: Optional[str] = None,
    ) -> None:
        turn = self._turn
        if turn is None:
            return
        relay_audit.record(
            relay_audit.EVENT_TURN_END,
            student_mask=self.student_mask,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            attempt=turn.attempt or None,
            final_status=status,
            upstream_error=upstream_error,
            detail=detail,
        )
        self._turn = None

    async def _reap_turn(
        self, reason: str, upstream_error: Optional[str] = None
    ) -> bool:
        """Close out a turn that is still open at teardown. True = reaped.

        ``reason`` lands in ``detail`` (relay-side cause: ``client_closed`` /
        ``relay_teardown`` / ``superseded_by_new_turn``) so ``upstream_error``
        keeps meaning "an upstream fault" and nothing else.
        """
        turn = self._turn
        if turn is None:
            return False
        logger.warning(
            "ws_chat relay reaping open turn mask=%s reason=%s",
            self.student_mask,
            reason,
        )
        self._finish_turn(
            relay_audit.STATUS_ABORTED, upstream_error, detail=reason
        )
        return True


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def handle_ws_chat(request: web.Request) -> web.Response:
    """GET /api/ws/chat?student=<8-char-masked-prefix> — handshake, relay.

    Two caller kinds are allowed past auth:
      * staff / parent session (auth_session) — the unchanged parent flow;
      * the student's own live kid_session (P0 student-console entry) —
        may only ever open their OWN chat (mask or full id), never a
        classmate's; consent is evaluated against the student's parent
        (consent is a parent-signed artefact; a kid_session alone is not
        a consent signal).
    """
    user = api_mod._session_user(request)
    kid = api_mod._student_session_student(request)

    if user is None and kid is None:
        return _reject(
            401,
            api_mod._ERR_AUTH,
            gate="auth",
            user_id="anonymous",
            target_id=request.query.get("student") or None,
        )

    student_identifier = request.query.get("student", "")

    if user is not None:
        # ---- parent flow (unchanged) ----
        if user["role"] != "parent":
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="role",
                user_id=user["id"],
                target_id=student_identifier or None,
            )
        student, ambiguous = students_mod.resolve_student_identifier(
            student_identifier, user
        )
        if ambiguous:
            return _reject(
                400,
                api_mod._ERR_INVALID,
                gate="ambiguous",
                user_id=user["id"],
                target_id=student_identifier or None,
            )
        if student is None:
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="ownership",
                user_id=user["id"],
                target_id=student_identifier or None,
            )
        if student["parent_id"] is None or student["parent_id"] != user["id"]:
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="ownership",
                user_id=user["id"],
                target_id=student["id"],
            )
        consent_user_id: Optional[str] = user["id"]
    else:
        # ---- student self-serve flow (P0 student-console entry) ----
        student = kid
        own_mask = student["id"][:8]
        if student_identifier not in (own_mask, student["id"]):
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="ownership",
                user_id=student["id"],
                target_id=student_identifier or None,
            )
        consent_user_id = student["parent_id"]
        if consent_user_id is None:
            # Invite-created students always carry a parent; fail closed.
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="consent_scope",
                user_id=student["id"],
                target_id=student["id"],
            )

    caller_id = user["id"] if user is not None else student["id"]

    if not classes_mod.student_class_confirmed(student["id"]):
        return _reject(
            403,
            {"error": "等待老師確認"},
            gate="class_confirmed",
            user_id=caller_id,
            target_id=student["id"],
        )

    chat_doc = consent_mod.get_doc_config("chat_consent")
    if chat_doc is not None and chat_doc.get("required"):
        # Default-deny: a current-version agreed row must cover the
        # student. Unsigned / withdrawn / stale version all refuse.
        if not consent_mod.student_has_current_agreement(
            consent_user_id, "chat_consent", student["id"]
        ):
            return _reject(
                403,
                api_mod._ERR_FORBIDDEN,
                gate="chat_consent_required",
                user_id=caller_id,
                target_id=student["id"],
            )
    elif consent_mod.student_chat_consent_withdrawn(
        consent_user_id, student["id"]
    ):
        return _reject(
            403,
            api_mod._ERR_FORBIDDEN,
            gate="chat_consent_withdrawn",
            user_id=caller_id,
            target_id=student["id"],
        )

    # Handshake passed — upgrade and relay to DeepTutor (P3 resilience inside).
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    try:
        async with aiohttp.ClientSession() as session:
            relay = _ChatRelay(
                ws=ws,
                session=session,
                upstream_url=_upstream_ws_url(),
                persona=_persona_for_student(student),
                # the query already carries the 8-char masked prefix only —
                # full student ids never leave the server, audit rows included
                student_mask=request.query.get("student", ""),
                # server-internal full id: drives the session map only and
                # never appears on any outward surface (red-line 8)
                student_id=student["id"],
                language=_row_get(student, "lang_code"),
            )
            await relay.run()
    finally:
        await _close_quietly(ws)
    return ws
