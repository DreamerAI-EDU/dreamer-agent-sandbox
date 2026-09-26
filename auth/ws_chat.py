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
import time
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

# PR-C item 4/5 — client message_id dedup. Process-lifetime memory only: a
# relay restart clears it, which is a known limitation (boss-approved PR
# description note 3). Entries are opportunistic-TTL-pruned when the map
# grows; the turn_state answer is "in_progress" until the turn finishes.
_DEDUP_TTL_SECONDS = 600.0
_DEDUP_RECENT: dict[str, dict] = {}

# PR-C item 6 — relay-side replay of a completed turn, keyed by engine
# session id. Lives in process memory exactly like the dedup map: a relay
# restart loses it (known limitation, recorded in the PR description) and the
# next subscribe_session then degrades to session-closed, which the frontend
# treats as "clear the in-flight marker, no scary error".
_COMPLETED_TURN_TAIL: dict[str, tuple[float, list[str]]] = {}
_COMPLETED_TURN_TAIL_MAX = 256


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

#: PR-D-b — upstream frame types that ask the child something (a clarification
#: card) instead of answering them. A `tool_call` is a contract frame now: the
#: relay forwards it verbatim (it is neither terminal nor visible answer text),
#: and parks the turn in "awaiting the child" so the idle watchdog can tell an
#: engine that went quiet from a child still reading a card (design §A.5 #1/#3).
_INTERACTIVE_FRAME_TYPES = ("tool_call",)

#: PR-D-b — frames worth replaying to a re-subscribing child. `content` is the
#: answer text (PR-C item 6); `tool_call` is the clarification card, without
#: which a refresh mid-wait would drop the question the child was answering.
#: R5 β (boss-signed): the engine's terminal `result` frame joins them — that
#: is the 7a fix proper, so a replayed turn ends on the same terminal frame the
#: live turn ended on instead of "card and answer text but no terminal state".
#: The child's own pick is deliberately NOT here: `tool_result` is a
#: client→engine frame with no consumer on the child side (design §A.7 7a).
_REPLAYABLE_FRAME_TYPES = ("content", "tool_call", "result")

#: how long the upstream may stay silent *inside an open turn* before the
#: watchdog reaps it. Idle-based (boss review condition 2): the timer restarts
#: on every upstream frame and only runs while a turn is open, so a long but
#: live turn (deep reasoning / many tool calls) is never killed. Never an
#: absolute turn deadline.
_IDLE_WATCHDOG_SECONDS = 90.0

#: PR-D-b — how long a turn may stay parked on a clarification card before the
#: relay closes it (boss-signed 2026-09-20: 300s). The idle watchdog cannot
#: serve here: it measures *engine* silence, and a card the child is reading is
#: not a silent engine. Env-tunable like the other timings, so a future
#: tightening to 240s stays a config one-liner (design §A.5 #1/#5).
_CLARIFY_WAIT_MAX_SECONDS = 300.0

#: 案 1 — idle upstream socket recycle. A turn that just finished leaves the
#: relay<->engine socket parked; the engine evicts idle sessions and anything
#: in between may drop a quiet socket without either end noticing, so the next
#: turn could land on a half-dead pipe. Recycling it *between* turns means
#: every turn starts from a socket this relay dialled moments ago.
#: Pure hygiene: no audit row, no frame to the child, never while a turn is
#: open (design §3.3). The cost is one re-dial for the first question after an
#: idle gap (design §3.5).
_IDLE_RECYCLE_SECONDS = 30.0

#: retry delays, one entry per attempt; length == retry budget (pre-content only)
_RETRY_BACKOFF_SECONDS = (1.5, 4.0)

#: 429 / quota wording seen in the wild. DeepTutor relays the provider error
#: text through an `error` frame, so match on markers rather than a fixed
#: string — and only inside an `error` frame, so a legitimate content frame
#: that happens to contain "429" can never be mistaken for a limit rejection.
_RATE_LIMIT_MARKERS = (
    "too many requests",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "resource_exhausted",
    "resourceexhausted",
    "quota",
)

#: The bare status code is deliberately NOT a substring marker (backlog #15).
#: A plain `"429" in text` also matches longer digit runs, so an ephemeral
#: port such as 42959 inside a connect error read as a limit rejection and
#: the relay audited a dead engine as upstream_rate_limited. A 429 only
#: counts as a status code when it stands alone — never glued to another
#: digit on either side.
_RATE_LIMIT_429_RE = re.compile(r"(?<!\d)429(?!\d)")

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
    # PR-D-b: the wire value is the literal §A.8 expects the frontend to match
    # (`code === 'ERR_CLARIFY_TIMEOUT'`) so the card can fall to its timeout
    # state and the banner show the clarify-specific copy instead of the
    # generic upstream one.
    relay_audit.ERR_CLARIFY_TIMEOUT: "ERR_CLARIFY_TIMEOUT",
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


def _clarify_wait_max_seconds() -> float:
    """PR-D-b knob: how long a parked clarify wait may last (design §A.5)."""
    return _env_positive_float(
        "WS_CHAT_CLARIFY_WAIT_SECONDS", _CLARIFY_WAIT_MAX_SECONDS
    )


def _idle_recycle_seconds() -> float:
    """案 1 knob; <= 0 disables recycling entirely."""
    raw = os.environ.get("WS_CHAT_IDLE_RECYCLE_SECONDS")
    if raw is None or raw == "":
        return _IDLE_RECYCLE_SECONDS
    try:
        return float(raw)
    except ValueError:
        return _IDLE_RECYCLE_SECONDS


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


# ---------------------------------------------------------------------------
# PR-A — pure-greeting short circuit (relay layer)
# ---------------------------------------------------------------------------
#: full-match anchored: ONLY a bare greeting is short-circuited. Anything
#: longer ("hi, what is 2+2?") still reaches the engine — the regex never
#: matches mid-sentence. Kid-friendly tone, per normalised locale.
_GREETING_RE = {
    "en": re.compile(
        r"^(?:hi|hello|hey|hi there|hello there|good (?:morning|afternoon|evening))"
        r"[!.]?$",
        re.IGNORECASE,
    ),
    "zh-hk": re.compile(
        r"^(?:你好|您好|哈囉|嗨|早晨|喂|hello|hi|hey)[!.]?$",
        re.IGNORECASE,
    ),
    "zh-cn": re.compile(
        r"^(?:你好|您好|嗨|哈喽|hello|hi|hey)[!.]?$",
        re.IGNORECASE,
    ),
}

_GREETING_REPLIES = {
    "en": "Hi there! I'm your AI learning buddy. What shall we explore today?",
    "zh-hk": "哈囉！我係你嘅 AI 學習夥伴，今日想學啲咩呀？",
    "zh-cn": "你好！我是你的 AI 学习伙伴，今天想学点什么呢？",
}


def _frame_text(frame: dict) -> str:
    """Extract the user's chat text from a client turn frame."""
    for key in ("content", "message"):
        value = frame.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _greeting_reply(text: str, language: str) -> Optional[str]:
    """Local kid-friendly reply when *text* is a bare greeting, else None."""
    text = (text or "").strip()
    if not text:
        return None
    pattern = _GREETING_RE.get(_normalise_language(language))
    if pattern is None or not pattern.fullmatch(text):
        return None
    return _GREETING_REPLIES.get(_normalise_language(language))


def _parse_frame(raw) -> dict:
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return frame if isinstance(frame, dict) else {}


def _looks_rate_limited(text: str) -> bool:
    """Upstream wording that reads as 429 / quota exhausted.

    Wording markers are plain substring matches; the bare status code is not
    — it must stand alone (see ``_RATE_LIMIT_429_RE``), so the digits of a
    port, an address or a request id can never be read as a limit rejection.
    """
    lowered = (text or "").lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return True
    return _RATE_LIMIT_429_RE.search(lowered) is not None


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
        "message_id",
        "content_frames",
        "awaiting_tool_result",
        "pending_tool_call_ids",
        "clarify_wait_started",
        "pending_ask_user",
    )

    def __init__(self, raw_frame: str, language: str, student_mask: str) -> None:
        self.raw_frame = raw_frame
        self.language = _normalise_language(language)
        self.student_mask = student_mask or ""
        self.attempt = 0  # retries already spent on this turn
        self.content_emitted = False  # any visible frame forwarded?
        self.session_id: Optional[str] = None
        self.turn_id: Optional[str] = None
        # PR-C item 4/5: client-supplied id (if any) — used to flip the
        # dedup entry to inactive when this turn finishes.
        self.message_id: Optional[str] = None
        # PR-C item 6: raw content frames already delivered to the child this
        # turn — kept so a later subscribe_session can replay the completed
        # turn without dialing the engine again.
        self.content_frames: list[str] = []
        # PR-D-b: the turn is parked on a clarification card the engine asked
        # for (`tool_call`) and is waiting for the child's `tool_result`. While
        # this is true the idle watchdog is replaced by the clarify wait budget
        # (design §A.5 #5) — a card being read is not a silent engine.
        self.awaiting_tool_result = False
        # The tool_call_ids this turn is still waiting on (engine-owned ids,
        # opaque, never generated relay-side). Deliberately NOT a dedup record:
        # it only decides whether a `tool_result` belongs to the open turn and
        # whether the wait is still on (design §A.6, OB-1).
        self.pending_tool_call_ids: set[str] = set()
        # monotonic() at the moment the wait started (re-set on each tool_call);
        # None = not waiting. Cleared with the wait, never across turns.
        self.clarify_wait_started: Optional[float] = None
        # PR-D-b4 PR-1: the card this turn is parked on, as the relay needs it
        # to translate the child's pick back into the engine's own channel —
        # `{questionId, labels: {opt_N -> label}, multi_select}`. The labels are
        # the relay↔frontend private contract minted in
        # `_clarify_contract_args` (the engine's own options carry no id at all,
        # F-b4-6(b)); the pick comes back as those ids and must reach the engine
        # as labels. None = no card parked on.
        self.pending_ask_user: Optional[dict] = None


def _contract_tool_call_id(frame: dict) -> tuple[str, str]:
    """Return (id, source) for a contract `tool_call` frame.

    The engine never puts a call id at the frame top level (StreamEvent has
    no such field); it lives in `metadata`. Relay maps, never mints.
    """
    top = frame.get("tool_call_id")
    if isinstance(top, str) and top:
        return top, "top"
    meta = frame.get("metadata") if isinstance(frame.get("metadata"), dict) else {}
    for key in ("tool_call_id", "call_id"):  # provider id first, trace id second
        val = meta.get(key)
        if isinstance(val, str) and val:
            return val, f"metadata.{key}"
    return "", "missing"


def _clarify_contract_args(args: dict) -> tuple[dict, dict]:
    """Flatten the engine's native `ask_user` args into the frontend contract.

    Engine side (image `v1.5.8`, `tools/ask_user.py`): `metadata.args` is
    `{intro?, questions:[{id, prompt, header?, multi_select?, allow_free_text?,
    options:[{label, description}]}]}` — **options carry no id**, and
    `allow_free_text` sits on the *question*, not on the payload root
    (`ask_user.py` reads it per question). Frontend side (`chatWs.ts:617-621`)
    is `{question, options:[{id,label}], allow_free_text}`, and
    `normalizeClarifyOptions` **drops every option without an id**
    (`chatWs.ts:83-94`). Without this flatten+mint the card renders with zero
    options (F-b4-6(b)). The minted `opt_1…opt_N` is positional and stable, and
    is a relay↔frontend private contract — NOT an engine call id.

    Returns (tool_args_for_frame, pending_ask_user).
    """
    args = args if isinstance(args, dict) else {}
    questions = args.get("questions")
    if not isinstance(questions, list) or not questions:
        questions = [
            {  # legacy single-question shape
                "prompt": args.get("question") or "",
                "options": args.get("options") or [],
            }
        ]
    q = questions[0] if isinstance(questions[0], dict) else {}
    labels: dict[str, str] = {}
    options = []
    for idx, opt in enumerate(q.get("options") or [], start=1):
        if isinstance(opt, dict):
            label = str(opt.get("label") or "").strip()
            description = opt.get("description")
        else:
            label, description = str(opt or "").strip(), None
        if not label:
            continue
        oid = f"opt_{idx}"
        labels[oid] = label
        options.append({"id": oid, "label": label, "description": description})
    # W-b4-1 (對版修正): the engine keeps `allow_free_text` on the *question*
    # (`tools/ask_user.py` `AskUserQuestion.to_dict()` / the per-question raw
    # read), so the question is the authoritative level — the args-level read
    # only covers the legacy single-question shape, and True is the engine's
    # own default when neither is set.
    free_text = q.get("allow_free_text")
    if free_text is None:
        free_text = args.get("allow_free_text")
    tool_args = {
        "question": str(q.get("prompt") or q.get("header") or ""),
        "options": options,
        "allow_free_text": True if free_text is None else bool(free_text),
        "multi_select": bool(q.get("multi_select")),
    }
    pending = {
        "questionId": str(q.get("id") or ""),
        "labels": labels,
        "multi_select": tool_args["multi_select"],
    }
    return tool_args, pending


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
        # PR-D-b: budget for a turn parked on a clarification card. Resolved
        # once per relay, exactly like the idle watchdog it stands in for.
        self._clarify_wait = _clarify_wait_max_seconds()
        # 案 1 — idle upstream socket recycle (design v1.1). `_recycle_timer` is
        # the armed task, `_recycled_socket` marks the socket *this relay* closed
        # on purpose (so the reader can tell hygiene from a real fault), and
        # `_upstream_ready` parks that reader until the next dial.
        self._recycle_after = _idle_recycle_seconds()
        self._recycle_timer: Optional[asyncio.Task] = None
        self._recycled_socket = None
        self._upstream_ready = asyncio.Event()

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
            # 案 1: wake a reader that is parked waiting for exactly this — a
            # fresh socket to read from. Assigned and signalled in the same
            # synchronous step, so `_wait_for_upstream` can never miss it.
            self._upstream_ready.set()
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
            # 案 1: no timer may fire against a relay whose child has left.
            self._cancel_recycle()
            upstream = self._upstream
            self._upstream = None
            await _close_quietly(upstream)

    async def _on_client_frame(self, raw: str) -> None:
        # 案 1, race layer 1 (design §3.4): cancel the idle-recycle timer
        # synchronously, before *any* await in this frame's handling. Cancelling
        # later would leave a window where the frame is in flight, the coroutine
        # yields, and the timer fires first — closing the very socket the new
        # turn is about to use.
        self._cancel_recycle()
        # P4: every client frame is session-restamped before anything else —
        # turn frames and subscribe/cancel alike, blanket by field.
        raw = self._restamp_session(raw)
        frame = _parse_frame(raw)
        ftype = frame.get("type")

        # PR-C item 1 — app-level heartbeat: a ping is answered locally and
        # never leaves the relay (no turn, no engine dial, no audit row).
        if ftype == "ping":
            await self.ws.send_json({"type": "pong"})
            return

        # PR-C item 6 — subscribe_session is answered by the relay itself,
        # never forwarded to the engine: a completed turn whose content this
        # relay process already delivered is replayed from memory (content +
        # done); a session the relay has no memory of (fresh, or lost in a
        # restart — the known in-memory limitation) is answered session-closed
        # so the child clears its in-flight flag without a scary error.
        if ftype == "subscribe_session":
            await self._handle_subscribe_session(frame)
            return

        # PR-D-b — the child picked an option on a clarification card. This is
        # NOT a new turn: it is the answer to the `tool_call` the engine is
        # already waiting on, so it rides the open turn upstream. A pick this
        # relay is not waiting on is dropped silently (idempotent), and either
        # way no turn is opened and no dedup entry is written.
        if ftype == "tool_result":
            await self._handle_tool_result(raw, frame)
            return

        # PR-C item 4/5 — immediate-receipt ack + dedup. Any turn frame
        # carrying a client message_id is acked BEFORE any engine work so a
        # slow engine can never trip the client's 10s resend timer (ack means
        # "relay received it", not "engine answered"). A duplicate message_id
        # is answered with dup-ack + the current turn state and is never
        # re-opened nor re-forwarded.
        mid = frame.get("message_id")
        if ftype in _TURN_FRAME_TYPES and isinstance(mid, str) and mid:
            self._prune_dedup()
            entry = _DEDUP_RECENT.get(mid)
            if entry is not None:
                state = "in_progress" if entry["active"] else "completed"
                await self.ws.send_json(
                    {
                        "type": "ack",
                        "message_id": mid,
                        "status": "dup",
                        "turn_state": state,
                    }
                )
                logger.info(
                    "ws_chat dedup hit message_id=%s state=%s mask=%s",
                    mid,
                    state,
                    self.student_mask,
                )
                return
            await self.ws.send_json(
                {"type": "ack", "message_id": mid, "status": "received"}
            )

        # PR-A: a bare greeting is answered locally — no engine dial, no
        # turn opened, no session row written (zero pollution). The reply
        # mirrors the engine's content+done shape so the frontend renders
        # it exactly like a real answer.
        if ftype in _TURN_FRAME_TYPES:
            reply = _greeting_reply(_frame_text(frame), self.language)
            if reply is not None:
                if isinstance(mid, str) and mid:
                    # a greeting completes instantly: remember it as inactive
                    # so a resent message_id never replies duplicate content
                    _DEDUP_RECENT[mid] = {"active": False, "ts": time.monotonic()}
                await self._forward(
                    json.dumps(
                        {"type": "content", "content": reply},
                        ensure_ascii=False,
                    )
                )
                await self._forward(json.dumps({"type": "done"}))
                relay_audit.record(
                    relay_audit.EVENT_GREETING_SHORT_CIRCUIT,
                    student_mask=self.student_mask,
                    detail=f"lang={self.language}",
                )
                return
        injected = _inject_persona(raw, self.persona)
        if _parse_frame(injected).get("type") in _TURN_FRAME_TYPES:
            await self._start_turn(injected)
        if not await self._send_upstream(injected):
            logger.warning("ws_chat relay could not forward a client frame")

    @staticmethod
    def _prune_dedup() -> None:
        """Opportunistic TTL cleanup for the process-lifetime dedup map."""
        if len(_DEDUP_RECENT) < 256:
            return
        now = time.monotonic()
        stale = [
            key
            for key, value in _DEDUP_RECENT.items()
            if now - value["ts"] > _DEDUP_TTL_SECONDS
        ]
        for key in stale:
            _DEDUP_RECENT.pop(key, None)

    @staticmethod
    def _prune_completed_tail() -> None:
        """Opportunistic TTL cleanup for the process-lifetime replay cache."""
        if len(_COMPLETED_TURN_TAIL) < _COMPLETED_TURN_TAIL_MAX:
            return
        now = time.monotonic()
        stale = [
            key
            for key, (ts, _frames) in _COMPLETED_TURN_TAIL.items()
            if now - ts > _DEDUP_TTL_SECONDS
        ]
        for key in stale:
            _COMPLETED_TURN_TAIL.pop(key, None)

    async def _handle_subscribe_session(self, frame: dict) -> None:
        """PR-C item 6 — replay a completed turn from relay memory, or answer
        session-closed. Never forwards to the engine (engine image untouched)."""
        sid = frame.get("session_id")
        if isinstance(sid, str) and sid:
            entry = _COMPLETED_TURN_TAIL.get(sid)
            if entry is not None:
                _ts, frames = entry
                for raw in frames:
                    await self._forward(raw)
                await self._forward(json.dumps({"type": "done"}))
                return
        await self.ws.send_json(
            {
                "type": "error",
                "error_code": "session_closed",
                "content": "session is no longer active",
            }
        )

    async def _handle_tool_result(self, raw: str, frame: dict) -> None:
        """PR-D-b — resume the parked turn with the child's pick, or drop it.

        Only a `tool_call_id` this relay is actually waiting on is accepted —
        it came from the engine, so an unknown one cannot belong to the open
        turn. Everything else (a replay of an old pick, a pick that arrived
        after the clarify wait was already killed, a forged id) is dropped
        without a turn, without a dial and without an audit row: the turn it
        belonged to is over and the engine must never see it. That idempotence
        is what lets the frontend resend freely.

        PR-D-b4 PR-1 (design v0.2.1 §A.2 F2): what leaves here is no longer the
        child's frame. The engine never had a `tool_result` consumer, so the
        pick is translated into its own resume channel — `submit_user_reply`,
        keyed by the `turn_id` the engine already carries — and the option ids
        the child echoed are mapped back to the labels the engine offered
        (`_build_user_reply`).

        ``raw`` arrives already session-restamped by the caller (P4 blanket
        rewrite), so a pick can only ever travel on this student's session.
        """
        turn = self._turn
        tool_call_id = frame.get("tool_call_id")
        if (
            turn is None
            or not isinstance(tool_call_id, str)
            or not tool_call_id
            or tool_call_id not in turn.pending_tool_call_ids
        ):
            logger.info(
                "ws_chat relay dropped a non-pending tool_result mask=%s",
                self.student_mask,
            )
            return
        turn.pending_tool_call_ids.discard(tool_call_id)
        if not turn.pending_tool_call_ids:
            # every card this turn was waiting on has been answered: the turn
            # is no longer parked on a human, so the idle watchdog takes over
            # again on the next receive (design §A.5 #6 — "re-arm watchdog").
            turn.awaiting_tool_result = False
            turn.clarify_wait_started = None
        relay_audit.record(
            relay_audit.EVENT_TOOL_RESULT,
            student_mask=self.student_mask,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            detail=f"tool_call_id={tool_call_id}",
        )
        if not await self._send_upstream(self._build_user_reply(turn, frame)):
            logger.warning("ws_chat relay could not forward a user reply")

    def _build_user_reply(self, turn: _TurnInFlight, frame: dict) -> str:
        """Translate the child's pick into the engine's own resume channel.

        The engine has no consumer for a `tool_result` frame — it never sent
        one — so the pick has to arrive as the frame it *does* understand:
        `submit_user_reply`, keyed by `turn_id`, which the engine already
        carries on every event (N-1). The relay therefore neither mints nor
        stores a resume id, and the answer's `questionId` is the engine's own
        question id when it sent one.

        The option ids are the relay↔frontend private contract minted in
        `_clarify_contract_args`, so they are mapped back to labels here: the
        engine must only ever be handed labels it actually offered
        (F-b4-6(b)(d)). An id this relay never minted is dropped, never
        guessed at, and the drop is audited — a stale card the child really
        saw can then be told apart from a forged frame.
        """
        pending = turn.pending_ask_user or {}
        labels = pending.get("labels") or {}
        result = frame.get("result") if isinstance(frame.get("result"), dict) else {}
        selected = result.get("selected")
        selected = selected if isinstance(selected, list) else []
        picked: list[str] = []
        unknown: list[str] = []
        for oid in selected:
            label = labels.get(oid) if isinstance(oid, str) else None
            if label:
                picked.append(label)
            else:
                unknown.append(str(oid))
        free_text = result.get("free_text")
        free_text = str(free_text).strip() if isinstance(free_text, str) else ""
        text = "、".join(picked + ([free_text] if free_text else []))
        if unknown:
            relay_audit.record(
                relay_audit.EVENT_UNMAPPED_PICK,
                student_mask=self.student_mask,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                detail="ids=" + ",".join(unknown),
            )
        payload: dict = {"type": "submit_user_reply", "turn_id": turn.turn_id}
        question_id = pending.get("questionId")
        if question_id:
            payload["answers"] = [{"questionId": question_id, "text": text}]
        else:
            payload["text"] = text
        return json.dumps(payload, ensure_ascii=False)

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
        # 案 1: a turn is open again — the recycle clock must not be running.
        # (The entry-point cancel covers the normal path; this one covers the
        # `superseded_by_new_turn` path, where `_finish_turn` armed a timer for
        # the *previous* turn microseconds before this one opened.)
        self._cancel_recycle()
        frame_type = _parse_frame(raw).get("type")
        relay_audit.record(
            relay_audit.EVENT_TURN_START,
            student_mask=self.student_mask,
            detail=f"frame_type={frame_type}",
        )
        # PR-C item 4/5: remember this message_id as an active turn so a
        # duplicate re-send gets dup-ack + in_progress and never re-opens.
        mid = _parse_frame(raw).get("message_id")
        if isinstance(mid, str) and mid:
            turn.message_id = mid
            _DEDUP_RECENT[mid] = {"active": True, "ts": time.monotonic()}

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
                if self._recycled_socket is not None:
                    # 案 1: our own idle recycle is still settling — park for
                    # the next dial rather than tear the relay down.
                    self._recycled_socket = None
                    await self._wait_for_upstream()
                    continue
                if not await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED):
                    return
                continue

            # Idle-based watchdog: the timeout only arms while a turn is open,
            # and it restarts on every frame (review condition 2).
            timeout = self._receive_timeout()
            try:
                msg = await asyncio.wait_for(upstream.receive(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._watchdog_kill()
                return
            except (aiohttp.ClientConnectionError, ConnectionResetError) as exc:
                logger.warning("ws_chat upstream receive failed: %s", exc)
                if not await self._socket_lost(upstream):
                    return
                continue

            if msg.type == aiohttp.WSMsgType.TEXT:
                if await self._on_upstream_text(msg.data):
                    continue
                self._remember_frame(msg.data)
                await self._forward(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await self._forward(msg.data, binary=True)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning(
                    "ws_chat upstream error: %s", upstream.exception()
                )
                if not await self._socket_lost(upstream):
                    return
                continue
            else:  # CLOSE / CLOSING / CLOSED
                if not await self._socket_lost(upstream):
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

        if turn is not None and frame.get("type") in _INTERACTIVE_FRAME_TYPES:
            # PR-D-b: the engine is asking the child to pick an option — a
            # clarification card. What the relay adds is the knowledge that
            # this turn is parked on a human, so the idle watchdog stops
            # measuring engine silence and the clarify wait budget takes over
            # (design §A.5 #3/#5).
            #
            # PR-D-b4 PR-1 (design v0.2.1 §A.2 F2): the frame can no longer be
            # forwarded verbatim. The engine puts its call id in `metadata`
            # (never at the top level, B4-1) and its options carry no id at all,
            # so the relay maps the id in and mints the card's option ids
            # (F-b4-6(b)) — the id itself is only ever *mapped*, never minted,
            # or the engine could not match the pick back to its call.
            tool_call_id, id_source = _contract_tool_call_id(frame)
            if tool_call_id:
                turn.pending_tool_call_ids.add(tool_call_id)
            meta = (
                frame.get("metadata")
                if isinstance(frame.get("metadata"), dict)
                else {}
            )
            turn.awaiting_tool_result = True
            turn.clarify_wait_started = time.monotonic()
            relay_audit.record(
                relay_audit.EVENT_TOOL_CALL,
                student_mask=self.student_mask,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                detail=f"tool_call_id={tool_call_id} id_source={id_source}",
            )
            if tool_call_id:
                frame["tool_call_id"] = tool_call_id
                frame["tool_args"], turn.pending_ask_user = _clarify_contract_args(
                    meta.get("args") or meta.get("tool_metadata") or {}
                )
                frame.setdefault("status", "awaiting_input")
                enriched = json.dumps(frame, ensure_ascii=False)
                # `tool_call` stays in `_REPLAYABLE_FRAME_TYPES`, so the replay
                # cache keeps carrying the card a refresh must still show.
                self._remember_frame(enriched)
                await self._forward(enriched)
                return True
            # No id anywhere (U-1 scenario): forward as-is, never mint one.
            return False

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

    def _remember_frame(self, raw: str) -> None:
        """PR-C item 6 / PR-D-b — keep the raw replayable frames of the current
        turn so a later subscribe_session can replay a completed turn without
        the engine. Widened in D-b: the answer text is no longer the only thing
        worth replaying — the clarification card and the engine's terminal
        `result` frame belong to the same screen (7a). Bounded to the same
        constant as the tail cache."""
        turn = self._turn
        if turn is None:
            return
        frame = _parse_frame(raw)
        if frame.get("type") not in _REPLAYABLE_FRAME_TYPES:
            return
        if len(turn.content_frames) >= _COMPLETED_TURN_TAIL_MAX:
            return
        turn.content_frames.append(raw)

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
            # PR-C item 5: a frame the child never received is evidence —
            # previously warning-only, now an audit row so delivery gaps are
            # reconstructable (turn40 audit gap fix).
            turn = self._turn
            relay_audit.record(
                relay_audit.EVENT_DELIVERY_FAIL,
                student_mask=self.student_mask,
                session_id=turn.session_id if turn else None,
                turn_id=turn.turn_id if turn else None,
                detail="client_forward_failed",
            )
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

    def _receive_timeout(self) -> Optional[float]:
        """How long the next upstream receive may block.

        None outside a turn, the idle watchdog inside one, and the clarify wait
        budget while the turn is parked on a clarification card (PR-D-b §A.5
        #5). The parked case must be *wider*: a child reading a card produces
        no upstream traffic at all, so the 90s idle watchdog would kill a
        perfectly healthy turn. It is a deadline, not an idle timer — counted
        from the `tool_call`, so an engine that keeps talking while still
        awaiting the pick cannot extend the child's budget either.
        """
        turn = self._turn
        if turn is None:
            return None
        if turn.awaiting_tool_result and turn.clarify_wait_started is not None:
            remaining = self._clarify_wait - (
                time.monotonic() - turn.clarify_wait_started
            )
            return remaining if remaining > 0 else 0.0
        return self._idle_timeout

    async def _watchdog_kill(self) -> None:
        turn = self._turn
        # PR-D-b: the budget that just expired names the kill. A turn parked on
        # a clarification card is not a silent engine — it is a child still
        # deciding — so it gets its own error code and its own event, and the
        # child gets the clarify copy instead of the "upstream is unavailable"
        # one (design §A.5 #5/#8). Same teardown either way.
        clarify = bool(turn is not None and turn.awaiting_tool_result)
        if clarify:
            budget = self._clarify_wait
            code = relay_audit.ERR_CLARIFY_TIMEOUT
            event = relay_audit.EVENT_CLARIFY_TIMEOUT
            detail = f"clarify_wait>{budget}s"
            reason = "clarify wait"
        else:
            budget = self._idle_timeout
            code = relay_audit.ERR_IDLE_TIMEOUT
            event = relay_audit.EVENT_WATCHDOG_KILL
            detail = f"upstream_idle>{budget}s"
            reason = "upstream idle"
        relay_audit.record(
            event,
            student_mask=self.student_mask,
            session_id=turn.session_id if turn else None,
            turn_id=turn.turn_id if turn else None,
            upstream_error=code,
            detail=detail,
        )
        logger.warning(
            "ws_chat relay watchdog kill: %s %.1fs with a turn open mask=%s",
            reason,
            budget,
            self.student_mask,
        )
        upstream = self._upstream
        self._upstream = None
        await _close_quietly(upstream)
        if turn is not None:
            await self._send_error_frame(
                code,
                turn.language,
                self._graceful_copy(code, turn.language),
            )
            self._finish_turn(relay_audit.STATUS_FAILED, code)

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
        # PR-C item 4/5: this message_id's turn is no longer in flight — a
        # later duplicate is answered dup-ack + completed.
        if turn.message_id:
            entry = _DEDUP_RECENT.get(turn.message_id)
            if entry is not None:
                entry["active"] = False
        # PR-C item 6: a completed turn with relay-side content becomes the
        # replay source for a later subscribe_session. In-process memory only
        # — a restart loses it (known limitation, PR description).
        if status == relay_audit.STATUS_COMPLETED:
            if turn.session_id and turn.content_frames:
                _COMPLETED_TURN_TAIL[turn.session_id] = (
                    time.monotonic(),
                    list(turn.content_frames),
                )
                _ChatRelay._prune_completed_tail()
        # PR-D-b: the wait state belongs to the turn, so it dies with the turn
        # whatever ended it (done / error / watchdog / teardown). Nothing is
        # carried across turns, so no stale id can ever gate the next turn's
        # `tool_result` — and the next turn starts on the idle watchdog again.
        # PR-D-b4 PR-1: the parked card (its minted option ids and their labels)
        # is turn state too, and goes with the same sweep — a later pick can
        # never be mapped against a card from a turn that is already over.
        turn.awaiting_tool_result = False
        turn.pending_tool_call_ids.clear()
        turn.clarify_wait_started = None
        turn.pending_ask_user = None
        self._turn = None
        # 案 1: the socket is idle between turns now — start the recycle clock.
        self._arm_recycle()

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

    # -- 案 1: idle upstream socket recycle ---------------------------------
    # Design: `案1_socket_idle_recycle_設計稿_v1.md` (v1.1, boss-signed).
    # Between turns the relay<->engine socket just sits there; the engine
    # evicts idle sessions and a quiet socket can go half-dead without either
    # end noticing. Recycling it means every turn starts from a socket this
    # relay dialled moments ago. Hard rules: only between turns, never an
    # audit row, never a frame to the child, never a session-map touch.

    def _cancel_recycle(self) -> None:
        """Disarm the recycle timer. Idempotent, safe to call anywhere."""
        timer = self._recycle_timer
        if timer is not None:
            timer.cancel()
            self._recycle_timer = None

    def _arm_recycle(self) -> None:
        """Start the recycle clock. Only ever armed with no turn open."""
        self._cancel_recycle()
        if self._turn is not None or self._recycle_after <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop, no timer
            return
        self._recycle_timer = loop.create_task(self._idle_recycle())

    async def _idle_recycle(self) -> None:
        """Close the idle upstream socket. Silent by contract (design §3.3)."""
        try:
            await asyncio.sleep(self._recycle_after)
        except asyncio.CancelledError:
            return
        # Disarm first: from here on this task is committed, so a frame
        # arriving mid-close must not try to cancel it.
        self._recycle_timer = None
        # Race layer 2 (design §3.4): the entry-point cancel covers the normal
        # path; this identity check covers the window where a frame arrived
        # while this coroutine was already past its last cancellation point.
        if self._turn is not None or self._draining:
            return
        upstream = self._upstream
        if upstream is None or upstream.closed:
            return
        # Mark the socket as "recycled, not dead" *before* releasing it, so the
        # reader can tell our own hygiene from a real upstream fault. The next
        # turn dials fresh through `_ensure_upstream`; the session id still
        # comes from the P4 map, so continuity is untouched (design §3.2).
        self._recycled_socket = upstream
        self._upstream = None
        await _close_quietly(upstream)

    async def _socket_lost(self, upstream) -> bool:
        """Settle one dead socket. True = the reader loop should keep going.

        Identity-safe by design: a socket whose death is noticed *after* a
        fresh dial replaced it must never clear ``self._upstream`` — that
        would orphan the new socket's frames (案 1 recycle race).

        A socket this relay recycled on purpose between turns is not a fault:
        no retry (there is nothing to save), no audit (zero pollution), no
        teardown (a hygiene action must never hang up on the child). The
        reader parks until the next turn dials a fresh socket.
        """
        if self._upstream is upstream:
            self._upstream = None
        if upstream is not None and upstream is self._recycled_socket:
            self._recycled_socket = None
            await self._wait_for_upstream()
            return True
        return await self._maybe_retry(relay_audit.ERR_UPSTREAM_CLOSED)

    async def _wait_for_upstream(self) -> None:
        """Park until a live socket exists (案 1). Cancelled at teardown."""
        while self._upstream is None or self._upstream.closed:
            self._upstream_ready.clear()
            # Re-check after clear(): `_ensure_upstream` assigns the socket and
            # sets the event in one synchronous step, so either we see the
            # socket here or the wait below is already signalled.
            if self._upstream is not None and not self._upstream.closed:
                break
            await self._upstream_ready.wait()


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
