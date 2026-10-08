"""c1-13b Phase 1 — voice cost gates + mic access gate (P1-P3 trial).

Three gates, per the boss-signed 實施令 2026-10-04:

1. Azure monthly budget $50 with 50/80/100% alerts — portal-side, the
   screenshot is part of the evidence pack (not code).
2. This module: the app-layer minute meters. A 60 s segment cap, 15 min per
   student per day, and a global monthly meter that auto-stops voice when it
   is reached (default 3000 min = the $50 budget at S0 $1.00/audio-hour).
3. ``STT_PROVIDER`` env switch (see auth/voice_stt.py) — the Deepgram adapter
   ships dormant in the same PR, so the switch day needs no code.

Access gate: the mic button is invisible unless the flag is on, the student is
in an allowed band, the guardian holds a current ``voice_consent`` record, and
the monthly meter is still running. Every branch that would show a button is
decided server-side; the frontend only renders what this module allows.

Privacy: counts and timestamps only. No audio, no transcript text, no
provider key material ever lands in the database or the audit log — the
student id is masked before it enters the audit line.
"""

from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from . import consent, db, email, voice_stt

logger = logging.getLogger(__name__)

#: HK business calendar. Fixed UTC+8 (no zoneinfo dependency on the host).
LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=8))

VOICE_CONSENT_DOC = "voice_consent"

_TRUE = {"1", "true", "yes", "on"}

_DEFAULTS = {
    "max_segment_seconds": 60,
    "daily_student_seconds": 900,
    "monthly_global_seconds": 180000,
    "max_upload_bytes": 2097152,
}

_ENV_OVERRIDE = {
    "max_segment_seconds": "VOICE_MAX_SEGMENT_SECONDS",
    "daily_student_seconds": "VOICE_DAILY_STUDENT_SECONDS",
    "monthly_global_seconds": "VOICE_MONTHLY_GLOBAL_SECONDS",
    "max_upload_bytes": "VOICE_MAX_UPLOAD_BYTES",
}


def _now(now: Optional[datetime.datetime] = None) -> datetime.datetime:
    return now or datetime.datetime.now(datetime.timezone.utc)


def _iso(ts: datetime.datetime) -> str:
    return ts.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _local(ts: datetime.datetime) -> datetime.datetime:
    return ts.astimezone(LOCAL_TZ)


def day_key(now: Optional[datetime.datetime] = None) -> str:
    return _local(_now(now)).strftime("%Y-%m-%d")


def month_key(now: Optional[datetime.datetime] = None) -> str:
    return _local(_now(now)).strftime("%Y-%m")


def mask_student_id(student_id: str) -> str:
    """Audit lines carry a mask, not the id the ledger is keyed by."""
    return f"{student_id[:8]}…" if len(student_id) > 8 else "…"


# ---------------------------------------------------------------------------
# Limits / flag
# ---------------------------------------------------------------------------

def limits() -> dict[str, int]:
    """YAML limits with a per-value env override (no restart-free reload)."""
    cfg_limits = (voice_stt.load_config().get("limits") or {})
    resolved: dict[str, int] = {}
    for name, default in _DEFAULTS.items():
        raw: Any = os.environ.get(_ENV_OVERRIDE[name], "")
        value: Any = raw.strip() if raw else cfg_limits.get(name, default)
        try:
            resolved[name] = int(value)
        except (TypeError, ValueError):
            resolved[name] = default
        if resolved[name] <= 0:
            resolved[name] = default
    return resolved


def flag_enabled() -> bool:
    """Feature flag ``voice_p1p3``: env wins, YAML default is OFF."""
    raw = (os.environ.get("VOICE_P1P3_ENABLED") or "").strip().lower()
    if raw:
        return raw in _TRUE
    cfg = voice_stt.load_config().get("feature_flag") or {}
    return bool(cfg.get("voice_p1p3", False))


def allowed_bands() -> set[str]:
    cfg = voice_stt.load_config().get("feature_flag") or {}
    bands = cfg.get("bands") or ["P1-P3"]
    return {str(b) for b in bands}


# ---------------------------------------------------------------------------
# Meters
# ---------------------------------------------------------------------------

def student_daily_seconds(student_id: str, day: Optional[str] = None) -> int:
    day = day or day_key()
    db.ensure_schema()
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS total FROM voice_usage_ledger "
            "WHERE student_id = ? AND day = ?",
            (student_id, day),
        ).fetchone()
        return int(row["total"] or 0)
    finally:
        conn.close()


def month_meter(month: Optional[str] = None) -> dict[str, Any]:
    month = month or month_key()
    db.ensure_schema()
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT month, seconds, stopped_at, alerted_at FROM voice_month_meter "
            "WHERE month = ?",
            (month,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"month": month, "seconds": 0, "stopped_at": None, "alerted_at": None}
    return dict(row)


def month_stopped(month: Optional[str] = None) -> bool:
    meter = month_meter(month)
    return bool(meter["stopped_at"]) or meter["seconds"] >= limits()["monthly_global_seconds"]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    max_seconds: int
    daily_remaining_seconds: int
    global_remaining_seconds: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": None if self.allowed else self.code,
            "max_seconds": self.max_seconds,
            "daily_remaining_seconds": self.daily_remaining_seconds,
        }


def evaluate(
    student_id: str,
    requested_seconds: int,
    *,
    now: Optional[datetime.datetime] = None,
) -> Decision:
    """Would this segment fit in both meters? Read-only (no side effects)."""
    lim = limits()
    required = max(1, min(int(requested_seconds or 0), lim["max_segment_seconds"]))
    daily_used = student_daily_seconds(student_id, day_key(now))
    month = month_meter(month_key(now))

    daily_remaining = max(0, lim["daily_student_seconds"] - daily_used)
    global_remaining = max(0, lim["monthly_global_seconds"] - int(month["seconds"] or 0))

    if month["stopped_at"] or global_remaining <= 0:
        code = "voice_monthly_budget_reached"
    elif daily_remaining <= 0:
        code = "voice_daily_limit_reached"
    elif global_remaining < required:
        code = "voice_monthly_budget_reached"
    elif daily_remaining < required:
        code = "voice_daily_limit_reached"
    else:
        code = ""
    return Decision(
        allowed=not code,
        code=code,
        max_seconds=lim["max_segment_seconds"],
        daily_remaining_seconds=daily_remaining,
        global_remaining_seconds=global_remaining,
    )


def record_usage(
    *,
    student_id: str,
    seconds: int,
    provider: str,
    now: Optional[datetime.datetime] = None,
) -> None:
    """Move both meters for one completed segment, then alert if the cap hit.

    The ledger row and the monthly meter land in one transaction; the audit
    line and the operator alert are best-effort afterwards (a mail failure
    must never fail a child's question).
    """
    ts = _now(now)
    day = day_key(ts)
    month = month_key(ts)
    seconds = max(0, int(seconds))
    cap = limits()["monthly_global_seconds"]

    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO voice_month_meter(month, seconds, updated_at)
                    VALUES(?, ?, ?)
               ON CONFLICT(month) DO UPDATE
                    SET seconds = seconds + excluded.seconds,
                        updated_at = excluded.updated_at""",
            (month, seconds, _iso(ts)),
        )
        conn.execute(
            "INSERT INTO voice_usage_ledger(student_id, day, seconds, provider, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (student_id, day, seconds, provider, _iso(ts)),
        )
        row = conn.execute(
            "SELECT seconds, stopped_at FROM voice_month_meter WHERE month = ?",
            (month,),
        ).fetchone()
        total = int(row["seconds"] or 0)
        just_stopped = total >= cap and not row["stopped_at"]
        if just_stopped:
            conn.execute(
                "UPDATE voice_month_meter SET stopped_at = ? "
                "WHERE month = ? AND stopped_at IS NULL",
                (_iso(ts), month),
            )
        conn.commit()
    finally:
        conn.close()

    consent.write_audit_log(
        {
            "timestamp": _iso(ts),
            "event": "voice_usage",
            "student": mask_student_id(student_id),
            "day": day,
            "seconds": seconds,
            "provider": provider,
        }
    )
    if just_stopped:
        _stop_and_alert(month=month, total=total, cap=cap, ts=ts)


def _stop_and_alert(
    *, month: str, total: int, cap: int, ts: datetime.datetime
) -> None:
    minutes = round(total / 60)
    logger.warning(
        "voice: monthly meter reached (%s min of %s min) — voice stopped for %s",
        minutes,
        round(cap / 60),
        month,
    )
    consent.write_audit_log(
        {
            "timestamp": _iso(ts),
            "event": "voice_month_cap_reached",
            "month": month,
            "seconds": total,
            "cap_seconds": cap,
            "action": "voice_auto_stopped",
        }
    )
    to_addr = (os.environ.get("VOICE_ALERT_TO") or "").strip()
    if not to_addr:
        # No mailbox configured for this host: the audit line is the record.
        return
    try:
        email.send_email(
            to_addr=to_addr,
            subject=f"[Dreamer] Voice monthly meter reached ({minutes} min) — voice auto-stopped",
            body=(
                f"The app-layer voice meter for {month} reached {minutes} min "
                f"({cap} min cap). Voice input is stopped for the rest of the "
                f"month; the Azure budget alert is the second line of defence.\n"
                f"Deepgram switch (if needed): STT_PROVIDER=deepgram\n"
            ),
        )
    except Exception:  # never let an alert failure break the request path
        logger.warning("voice: cap alert e-mail failed (month=%s)", month)


def month_minutes(month: Optional[str] = None) -> int:
    """Operator-facing figure (evidence pack / ops console)."""
    return round(int(month_meter(month)["seconds"] or 0) / 60)


# ---------------------------------------------------------------------------
# Mic access gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Access:
    enabled: bool
    reason: Optional[str]
    decision: Optional[Decision]


def access_decision(
    student: Any, *, now: Optional[datetime.datetime] = None
) -> Access:
    """Server-side answer to "may this child see a mic button at all?".

    Reasons are operator-facing only ("flag_off" / "band" / "consent" /
    "voice_monthly_budget_reached" / "voice_daily_limit_reached"). The kid
    never reads them: a closed gate simply renders no button.
    """
    if not flag_enabled():
        return Access(False, "flag_off", None)
    if student is None:
        return Access(False, "no_student", None)
    band = str(student["age_band"] or "")
    if band not in allowed_bands():
        return Access(False, "band", None)
    parent_id = student["parent_id"]
    if not parent_id or not consent.student_has_current_agreement(
        parent_id, VOICE_CONSENT_DOC, student["id"]
    ):
        # 冇 consent 記錄 = 睇都睇唔到 mic 掣 (實施令 §3).
        return Access(False, "consent", None)
    decision = evaluate(student["id"], limits()["max_segment_seconds"], now=now)
    if not decision.allowed:
        return Access(False, decision.code, decision)
    return Access(True, None, decision)
