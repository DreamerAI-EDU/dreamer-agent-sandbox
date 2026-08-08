"""
Dreamer AI Phase 2.5 — Input Guard
Pre-generation safety filter. Rule-based, zero LLM.

Three layers + welfare path:
  1. Prompt injection detection (3 langs, normalized matching)
  2. Welfare check (self-harm / crisis keywords) — separate warm message + alert
  3. Age-inappropriate keyword blocklist (per age band)

Context whitelist: each block keyword has allow_if_contains terms.
e.g. "kill" is allowed with "process"/"task" (computing), blocked otherwise.

Design:
  - Welfare fires BEFORE injection/age checks — warm message is distinct
  - Block redirect: friendly per-age-band message, never raw refusal
  - Normalization: lowercase, strip spaces/strip punctuation → prevents
    "i g n o r e" bypass attempts
  - Audit: every block/welfare event writes to safety_events
"""

import json
import os
import re
import uuid
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


class InputGuard:
    """Pre-generation input safety filter.

    Usage:
        guard = InputGuard("config/input_guard_rules.json")
        verdict = guard.check(query="...", age_band="P1-P3", lang_code="zh-hk",
                               student_id="stu_001", session_id="sess_abc")

        if verdict.is_safe:
            # pass to DeepTutor
        else:
            # return verdict.response_message to student
            # verdict.event dict → log to safety_events
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "config", "input_guard_rules.json"
            )
        with open(config_path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        self._injection_patterns = self._config["injection_patterns"]
        self._age_inappropriate = self._config["age_inappropriate"]
        self._context_whitelist = self._config["context_whitelist"]
        self._block_messages = self._config["block_messages"]
        self._welfare = self._config["welfare"]

    # ── Public API ─────────────────────────────────────

    def check(
        self,
        query: str,
        age_band: str,
        lang_code: str,
        student_id: str = "",
        session_id: str = "",
    ) -> "InputGuardVerdict":
        """Run all safety checks. Returns verdict with action.

        Order: welfare → injection → age_inappropriate
        Welfare takes priority — its message differs from generic block.
        """
        normalized = self._normalize(query)

        # 1. Welfare check (highest priority)
        welfare_msg = self._check_welfare(normalized, age_band, lang_code)
        if welfare_msg is not None:
            event = self._build_event(
                "welfare", "high", query, age_band, lang_code,
                student_id, session_id, matched_rule="welfare_pattern",
            )
            return InputGuardVerdict(
                is_safe=False, is_welfare=True,
                response_message=welfare_msg, event=event,
            )

        # 2. Prompt injection check
        if self._check_injection(normalized, lang_code):
            event = self._build_event(
                "injection", "medium", query, age_band, lang_code,
                student_id, session_id, matched_rule="injection_pattern",
            )
            msg = self._get_block_message(age_band, lang_code)
            return InputGuardVerdict(
                is_safe=False, is_welfare=False,
                response_message=msg, event=event,
            )

        # 3. Age-inappropriate check
        blocked_kw = self._check_age_inappropriate(normalized, age_band, lang_code, query)
        if blocked_kw is not None:
            event = self._build_event(
                "age_inappropriate", "medium" if age_band != "P1-P3" else "low",
                query, age_band, lang_code,
                student_id, session_id, matched_rule=blocked_kw,
            )
            msg = self._get_block_message(age_band, lang_code)
            return InputGuardVerdict(
                is_safe=False, is_welfare=False,
                response_message=msg, event=event,
            )

        # Safe
        return InputGuardVerdict(is_safe=True)

    # ── Normalization ──────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip spaces/punctuation. Prevent 'i g n o r e' bypass."""
        text = text.lower()
        # Strip whitespace between characters (defeat spaced-out bypass)
        text = re.sub(r"\s+", "", text)
        # Strip common ASCII + fullwidth punctuation that could be used as delimiters
        text = re.sub(r"[\.,;:!?\-_/\\|@#$%^&*()\[\]{}<>\"'`~+=，。；：！？、]", "", text)
        return text

    # ── Injection Check ────────────────────────────────

    def _check_injection(self, normalized: str, lang_code: str) -> bool:
        """Check for prompt injection / jailbreak patterns."""
        patterns = self._injection_patterns.get(lang_code, [])
        for pattern in patterns:
            norm_pattern = self._normalize(pattern)
            if norm_pattern and norm_pattern in normalized:
                return True
        return False

    # ── Welfare Check ──────────────────────────────────

    def _check_welfare(
        self, normalized: str, age_band: str, lang_code: str
    ) -> Optional[str]:
        """Check for self-harm / crisis keywords. Returns warm message or None."""
        patterns = self._welfare["patterns"].get(lang_code, [])
        for pattern in patterns:
            norm_pattern = self._normalize(pattern)
            if norm_pattern and norm_pattern in normalized:
                messages = self._welfare["messages"].get(age_band, {})
                return messages.get(lang_code, messages.get("en", ""))
        return None

    # ── Age-Inappropriate Check ────────────────────────

    def _check_age_inappropriate(
        self, normalized: str, age_band: str, lang_code: str, original: str
    ) -> Optional[str]:
        """Check age-inappropriate keywords with context whitelist. Returns blocked keyword or None."""
        age_rules = self._age_inappropriate.get(age_band, {})
        keywords = age_rules.get(lang_code, [])
        for kw in keywords:
            norm_kw = self._normalize(kw)
            if not norm_kw or norm_kw not in normalized:
                continue
            # Check context whitelist — if allowed context also present, skip
            if self._is_whitelisted(kw, original, lang_code):
                continue
            return kw
        return None

    def _is_whitelisted(self, keyword: str, original: str, lang_code: str) -> bool:
        """Check if a blocked keyword appears in an allowed educational context."""
        # Match by normalized keyword root
        norm_kw = self._normalize(keyword)
        # Try exact match first, then substring
        for whitelist_key, contexts in self._context_whitelist.items():
            norm_wl = self._normalize(whitelist_key)
            if norm_wl == norm_kw or norm_wl in norm_kw or norm_kw in norm_wl:
                allowed = contexts.get(lang_code, [])
                norm_original = self._normalize(original)
                for ctx in allowed:
                    norm_ctx = self._normalize(ctx)
                    if norm_ctx and norm_ctx in norm_original:
                        return True
        return False

    # ── Helpers ────────────────────────────────────────

    def _get_block_message(self, age_band: str, lang_code: str) -> str:
        """Return friendly redirect message for blocked queries."""
        messages = self._block_messages.get(age_band, self._block_messages.get("P4-P6", {}))
        return messages.get(lang_code, messages.get("en", "I can only help with your studies. Let's focus on learning!"))

    @staticmethod
    def _build_event(
        event_type: str,
        severity: str,
        raw_input: str,
        age_band: str,
        lang_code: str,
        student_id: str,
        session_id: str,
        matched_rule: str,
    ) -> dict:
        """Build a safety_events-compatible dict (for DB insert / webhook)."""
        return {
            "id": str(uuid.uuid4()),
            "student_id": student_id,
            "session_id": session_id,
            "event_type": event_type,
            "severity": severity,
            "raw_input": raw_input,
            "matched_rule": matched_rule,
            "age_band": age_band,
            "lang_code": lang_code,
            "reviewed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class InputGuardVerdict:
    """Result of InputGuard.check()."""

    def __init__(
        self,
        is_safe: bool,
        is_welfare: bool = False,
        response_message: str = "",
        event: Optional[dict] = None,
    ):
        self.is_safe = is_safe
        self.is_welfare = is_welfare
        self.response_message = response_message
        self.event = event


# ── Webhook Notifier (fire-and-forget) ────────────────

def notify_welfare(event: dict, webhook_url: Optional[str] = None) -> bool:
    """POST welfare event to SAFETY_WEBHOOK_URL. Fire-and-forget.

    Args:
        event: safety_events dict from InputGuard._build_event()
        webhook_url: override URL; defaults to env SAFETY_WEBHOOK_URL

    Returns:
        True if webhook was fired (or skipped — never blocks student response).
    """
    url = webhook_url or os.environ.get("SAFETY_WEBHOOK_URL")
    if not url:
        return False  # webhook not configured, skip silently

    payload = {
        "event_id": event.get("id"),
        "student_id": event.get("student_id"),
        "session_id": event.get("session_id"),
        "severity": event.get("severity"),
        "matched_rule": event.get("matched_rule"),
        "age_band": event.get("age_band"),
        "lang_code": event.get("lang_code"),
        "timestamp": event.get("created_at"),
        # raw_input intentionally excluded from webhook —
        # sensitive content routed to safety_events DB only
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        # Fire-and-forget: webhook failure must never affect student response
        return False
