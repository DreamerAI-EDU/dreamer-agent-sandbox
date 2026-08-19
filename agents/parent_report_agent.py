"""
Dreamer AI Phase 6 — Parent Report Agent (Day 24)

Real implementation: queries Dreamer DB directly (no DeepTutor dependency)
and produces the parent-facing progress report defined in
docs/phase6-schemas.md §1.

Sources: assessment_logs / progress_snapshots / session_logs / obs_events.

Capabilities:
  report_gen        — build full parent report (default)
  progress_summary  — lightweight metrics-only summary (no narrative LLM)
  db_query          — raw parameterized DB query (internal debugging)

Design decisions (Day 24 kickoff, user-signed):
  - D8: mastery_pct uses rolling average (progress_snapshots upsert)
  - D3: parent-facing labels from label_soften(audience='parent_facing');
        not_yet → "Building Foundations" / 「建立基礎中」 (no deficit framing)
  - narrative: LLM (OpenRouter via codex_cli) with template fallback;
        aggregate data only — never raw evidence or student identifiers
  - safety: obs_events event_type='safety' → pointer-only alerts
        (event_ref=row id, never the original message) — P5 PDPO red line
  - evidence_text truncated to ≤200 chars
  - portfolio_highlights: v1 empty [] (portfolio_items table arrives Day 25)

Schema contract: every response carries the 7-field envelope
(content/mode/lang_code/age_band/kid_label/citations/cost_summary)
plus the nested `report` object. mode fixed to "parent_report".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .kid_safe.label_soften import soften_label, get_mastery_pct

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEEKLY_DAYS = 7
CYCLE_DAYS = 56            # 8-week learning cycle
PERIOD_DAYS = {
    "weekly": WEEKLY_DAYS,
    "cycle": CYCLE_DAYS,
}
EVIDENCE_MAX_CHARS = 200
FIRST_STEPS_MIN_SESSIONS = 5
FIRST_STEPS_MIN_DAYS = 14   # 2 weeks
MASTERY_STRONG = 60.0       # ≥60% → prerequisite considered achieved
MAX_NARRATIVE_CHARS = 800
MAX_TOPICS_IN_REPORT = 8
MAX_TIMELINE_DAYS = 60

DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)
DB_PATH = os.path.abspath(DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago_iso(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(text: str, limit: int = EVIDENCE_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _subject_of(topic_id: str) -> str:
    """Derive subject label from topic_id ('computing-scratch-basics-01'
    → 'computing'). Unknown → 'general'."""
    if not topic_id:
        return "general"
    return str(topic_id).split("-", 1)[0]


# ---------------------------------------------------------------------------
# Parent Report Agent
# ---------------------------------------------------------------------------

class ParentReportAgent:
    """Parent-facing progress report built from Dreamer DB."""

    AGENT_NAME = "parent_report"
    KB_OWNERSHIP: list = []
    KBS_READ = ["dreamer-portfolio"]
    CAPABILITIES = ["report_gen", "progress_summary", "db_query"]
    MODE_ALLOWLIST = None  # non-student-facing

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = os.path.abspath(db_path or DB_PATH)

    # ── DB helpers ────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Parameterized queries ─────────────────────────

    def _query_assessment_logs(
        self, student_id: str, start: Optional[str], end: str
    ) -> List[dict]:
        with self._connect() as conn:
            if start is None:
                rows = conn.execute(
                    """SELECT * FROM assessment_logs
                       WHERE student_id=? AND created_at<=?
                       ORDER BY created_at ASC""",
                    (student_id, end),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM assessment_logs
                       WHERE student_id=? AND created_at>=? AND created_at<=?
                       ORDER BY created_at ASC""",
                    (student_id, start, end),
                ).fetchall()
        return [dict(r) for r in rows]

    def _query_progress_snapshots(self, student_id: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM progress_snapshots
                   WHERE student_id=?
                   ORDER BY updated_at ASC""",
                (student_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _query_session_logs(
        self, student_id: str, start: Optional[str], end: str
    ) -> List[dict]:
        with self._connect() as conn:
            if start is None:
                rows = conn.execute(
                    """SELECT * FROM session_logs
                       WHERE student_id=? AND created_at<=?
                       ORDER BY created_at ASC""",
                    (student_id, end),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM session_logs
                       WHERE student_id=? AND created_at>=? AND created_at<=?
                       ORDER BY created_at ASC""",
                    (student_id, start, end),
                ).fetchall()
        return [dict(r) for r in rows]

    def _query_obs_events(
        self,
        student_id: str,
        start: Optional[str],
        end: str,
        event_type: Optional[str] = None,
    ) -> List[dict]:
        with self._connect() as conn:
            if event_type is None:
                if start is None:
                    rows = conn.execute(
                        """SELECT * FROM obs_events
                           WHERE student_id=? AND created_at<=?
                           ORDER BY created_at ASC""",
                        (student_id, end),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM obs_events
                           WHERE student_id=? AND created_at>=? AND created_at<=?
                           ORDER BY created_at ASC""",
                        (student_id, start, end),
                    ).fetchall()
            else:
                if start is None:
                    rows = conn.execute(
                        """SELECT * FROM obs_events
                           WHERE student_id=? AND event_type=? AND created_at<=?
                           ORDER BY created_at ASC""",
                        (student_id, event_type, end),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM obs_events
                           WHERE student_id=? AND event_type=?
                             AND created_at>=? AND created_at<=?
                           ORDER BY created_at ASC""",
                        (student_id, event_type, start, end),
                    ).fetchall()
        return [dict(r) for r in rows]

    # ── Period window ─────────────────────────────────

    @staticmethod
    def _period_window(
        period: str, first_activity_iso: Optional[str]
    ) -> Tuple[Optional[str], str, int]:
        """Return (start_iso, end_iso, days). journey → (earliest, now, span)."""
        end = _now_iso()
        if period == "journey":
            if not first_activity_iso:
                return None, end, 0
            try:
                first = datetime.fromisoformat(first_activity_iso)
                now = datetime.now(timezone.utc)
                span = max((now - first).days, 0)
            except ValueError:
                span = 0
            return first_activity_iso, end, span
        days = PERIOD_DAYS.get(period, CYCLE_DAYS)
        return _days_ago_iso(days), end, days

    # ── Variant ───────────────────────────────────────

    def _pick_variant(
        self, session_count: int, first_session_iso: Optional[str]
    ) -> str:
        if session_count < FIRST_STEPS_MIN_SESSIONS:
            return "first_steps"
        if first_session_iso:
            try:
                first = datetime.fromisoformat(first_session_iso)
                if (datetime.now(timezone.utc) - first).days < FIRST_STEPS_MIN_DAYS:
                    return "first_steps"
            except ValueError:
                pass
        return "standard"

    # ── Aggregates ────────────────────────────────────

    def _aggregate_summary(
        self,
        sessions: List[dict],
        logs: List[dict],
        duration_seconds: int,
        topic_ids: List[str],
    ) -> dict:
        mode_dist = {"DIRECT": 0, "CONTEXTUAL": 0, "HYBRID": 0}
        for s in sessions:
            m = s.get("mode") or ""
            if m in mode_dist:
                mode_dist[m] += 1
        return {
            "session_count": len(sessions),
            "total_duration_seconds": duration_seconds,
            "topics_touched": len(topic_ids),
            "mode_distribution": mode_dist,
        }

    def _aggregate_duration(
        self, obs_events: List[dict]
    ) -> int:
        """Total LLM elapsed from obs_events cost events (real measurement).

        session_logs has no duration column (backlog known gap); cost event
        elapsed_ms is the only real timing signal. 0 when unavailable.
        """
        total_ms = 0.0
        for ev in obs_events:
            if ev.get("event_type") != "cost":
                continue
            try:
                data = json.loads(ev.get("event_data") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            total_ms += float(data.get("elapsed_ms") or 0.0)
        return int(total_ms / 1000)

    def _aggregate_cost(
        self, obs_events: List[dict]
    ) -> int:
        """Total token usage from obs_events cost events (summary level).

        D5 (Phase 6): report-level total only — no per-assessment detail.
        Cost events written by the WS client carry total_tokens; events written
        directly by assessment (no LLM) carry no token field → contribute 0.
        Returns 0 when unavailable.
        """
        total = 0
        for ev in obs_events:
            if ev.get("event_type") != "cost":
                continue
            try:
                data = json.loads(ev.get("event_data") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            tokens = data.get("total_tokens") or 0
            try:
                total += int(tokens)
            except (TypeError, ValueError):
                continue
        return total

    def _build_topics(
        self,
        logs: List[dict],
        snapshots: List[dict],
        start: Optional[str],
        lang_code: str,
    ) -> List[dict]:
        """Per-topic aggregates from assessment_logs + progress_snapshots."""
        # Latest snapshot per topic (journey-level current state)
        snap_by_topic: Dict[str, dict] = {}
        for s in snapshots:
            tid = s.get("topic_id") or ""
            if not tid:
                continue
            snap_by_topic[tid] = s  # rows ordered ASC → last wins

        # First & last snapshot within period (for mastery_delta)
        period_snap_by_topic: Dict[str, List[dict]] = {}
        for s in snapshots:
            tid = s.get("topic_id") or ""
            ts = s.get("updated_at") or ""
            if not tid:
                continue
            if start is not None and ts < start:
                continue
            period_snap_by_topic.setdefault(tid, []).append(s)

        # Assessment logs per topic (for recent_evidence)
        logs_by_topic: Dict[str, List[dict]] = {}
        for log in logs:
            tid = log.get("topic_id") or ""
            if not tid:
                continue
            logs_by_topic.setdefault(tid, []).append(log)

        topic_ids = list(
            set(list(snap_by_topic.keys()) + list(logs_by_topic.keys()))
        )
        topic_ids.sort(key=lambda t: (
            snap_by_topic.get(t, {}).get("updated_at", ""),
            logs_by_topic.get(t, [{}])[0].get("created_at", "") if logs_by_topic.get(t) else "",
        ), reverse=True)
        topic_ids = topic_ids[:MAX_TOPICS_IN_REPORT]

        topics = []
        for tid in topic_ids:
            snap = snap_by_topic.get(tid, {})
            p_snaps = period_snap_by_topic.get(tid, [])
            t_logs = logs_by_topic.get(tid, [])

            mastery = float(snap.get("mastery_pct") or 0.0)
            # delta: progress_snapshots only keeps LATEST state per topic
            # (PK student_id+topic_id) — derive delta from period logs instead.
            delta = 0.0
            if len(t_logs) >= 2:
                first_pct = get_mastery_pct(t_logs[0].get("internal_label") or "")
                last_pct = get_mastery_pct(t_logs[-1].get("internal_label") or "")
                delta = round(last_pct - first_pct, 1)

            # Recent evidence: last 3 logs, evidence truncated
            recent = []
            for log in t_logs[-3:]:
                internal = log.get("internal_label") or ""
                recent.append({
                    "date": (log.get("created_at") or "")[:10],
                    "label_parent": soften_label(
                        internal, "P4-P6", lang_code, audience="parent_facing"
                    ) if internal else "",
                    "evidence_text": _truncate(log.get("evidence_text") or ""),
                })

            last_internal = snap.get("last_label") or (
                t_logs[-1].get("internal_label") if t_logs else ""
            ) or ""
            topics.append({
                "topic_id": tid,
                "subject": _subject_of(tid),
                "mastery_pct": round(mastery, 1),
                "mastery_delta": delta,
                "attempt_count": int(snap.get("attempt_count") or len(t_logs)),
                "last_label_internal": last_internal,
                "last_label_parent": soften_label(
                    last_internal, "P4-P6", lang_code, audience="parent_facing"
                ) if last_internal else "",
                "streak": int(snap.get("streak") or 0),
                "recent_evidence": recent,
            })
        return topics

    def _build_timeline(self, sessions: List[dict]) -> List[dict]:
        """Daily session aggregation (max MAX_TIMELINE_DAYS entries)."""
        by_day: Dict[str, List[str]] = {}
        for s in sessions:
            day = (s.get("created_at") or "")[:10]
            if not day:
                continue
            mode = s.get("mode") or ""
            by_day.setdefault(day, []).append(mode)
        days = sorted(by_day.keys())
        # Limit to most recent MAX_TIMELINE_DAYS days
        if len(days) > MAX_TIMELINE_DAYS:
            days = days[-MAX_TIMELINE_DAYS:]
        return [
            {
                "date": day,
                "sessions": len(by_day[day]),
                "modes": sorted(set(by_day[day])),
            }
            for day in days
        ]

    def _build_baseline(self, logs: List[dict], lang_code: str) -> Optional[dict]:
        """First DIRECT assessment log → starting level (first_steps only)."""
        direct = [l for l in logs if (l.get("mode") or "").startswith("DIRECT")]
        if not direct:
            return None
        first = direct[0]
        internal = first.get("internal_label") or ""
        return {
            "date": (first.get("created_at") or "")[:10],
            "topic_id": first.get("topic_id") or "",
            "subject": _subject_of(first.get("topic_id") or ""),
            "label_parent": soften_label(
                internal, "P4-P6", lang_code, audience="parent_facing"
            ) if internal else "",
            "confidence": float(first.get("confidence") or 0.0),
        }

    def _build_roadmap(
        self,
        topics: List[dict],
        snap_by_topic: Dict[str, dict],
        lang_code: str,
    ) -> Optional[List[dict]]:
        """Curriculum Navigator prerequisite chain → next-step suggestions.

        Uses get_prerequisites() for the most-recent topic; prerequisites
        without a strong snapshot (mastery ≥ MASTERY_STRONG) become the
        roadmap. Falls back to a generic practice suggestion when the
        navigator returns nothing usable.
        """
        try:
            from .curriculum_navigator import CurriculumNavigator
            nav = CurriculumNavigator(db_path=self._db_path)
        except Exception as exc:
            logger.warning("parent_report roadmap: navigator unavailable: %s", exc)
            nav = None

        if not topics:
            return []

        latest = topics[0]
        latest_id = latest["topic_id"]
        prereq_ids: List[str] = []
        if nav is not None:
            try:
                prereq_ids = nav.get_prerequisites(latest_id) or []
            except Exception as exc:
                logger.warning(
                    "parent_report roadmap: get_prerequisites failed: %s", exc
                )
                prereq_ids = []

        if not prereq_ids:
            # No navigator data → generic next-step suggestion
            return [{
                "topic_id": latest_id,
                "topic_name": latest["subject"],
                "reason": "continue_practice",
                "action": {
                    "zh-hk": "繼續定期練習，鞏固理解後再挑戰下一課題。",
                    "zh-cn": "继续定期练习，巩固理解后再挑战下一课题。",
                    "en": "Keep practicing regularly; consolidate understanding before moving on.",
                }.get(lang_code, ""),
            }]

        steps = []
        for pid in prereq_ids:
            snap = snap_by_topic.get(pid)
            mastery = float(snap.get("mastery_pct") or 0.0) if snap else 0.0
            if mastery >= MASTERY_STRONG:
                continue  # already strong
            steps.append({
                "topic_id": pid,
                "topic_name": _subject_of(pid),
                "reason": "prerequisite_not_strong" if snap else "prerequisite_untouched",
                "action": {
                    "zh-hk": f"建議先鞏固 {_subject_of(pid)} 嘅基礎概念，再繼續「{latest['subject']}」。",
                    "zh-cn": f"建议先巩固 {_subject_of(pid)} 的基础概念，再继续「{latest['subject']}」。",
                    "en": f"Strengthen foundations in {_subject_of(pid)} before continuing with {latest['subject']}.",
                }.get(lang_code, ""),
            })
        return steps[:3]

    def _build_safety_alerts(
        self, obs_events: List[dict]
    ) -> List[dict]:
        """Pointer-only safety alerts from obs_events (P5 PDPO red line)."""
        alerts = []
        for ev in obs_events:
            if ev.get("event_type") != "safety":
                continue
            try:
                data = json.loads(ev.get("event_data") or "{}")
            except (json.JSONDecodeError, TypeError):
                data = {}
            alerts.append({
                "type": data.get("block_type") or "safety_block",
                "severity": "info",
                "ts": (ev.get("created_at") or "")[:10],
                "event_ref": f"obs_{ev.get('id')}",
            })
        return alerts

    # ── Narrative ─────────────────────────────────────

    def _narrative_template(
        self, summary: dict, topics: List[dict], lang_code: str, variant: str
    ) -> str:
        sessions = summary["session_count"]
        minutes = int(summary["total_duration_seconds"] / 60)
        topics_n = summary["topics_touched"]
        top = topics[0] if topics else None
        top_name = top["subject"] if top else ""
        top_mastery = int(top["mastery_pct"]) if top else 0

        if sessions == 0:
            return {
                "zh-hk": "歡迎使用 Dreamer AI！暫時未有學習記錄，完成第一次練習後，呢度就會顯示進度概覽。",
                "zh-cn": "欢迎使用 Dreamer AI！暂时还没有学习记录，完成第一次练习后，这里就会显示进度概览。",
                "en": "Welcome to Dreamer AI! No learning records yet — complete your first practice and progress will appear here.",
            }.get(lang_code, "")

        if variant == "first_steps":
            return {
                "zh-hk": (
                    f"囝囡啱啱開始使用 Dreamer AI，目前已進行 {sessions} 次學習，"
                    f"覆蓋 {topics_n} 個課題，累計約 {minutes} 分鐘。"
                    + (f"喺「{top_name}」方面已建立基礎（掌握度約 {top_mastery}%）。" if top else "")
                    + "建議保持每週 2–3 次練習，逐步建立學習習慣。"
                ),
                "zh-cn": (
                    f"孩子刚开始使用 Dreamer AI，目前已进行 {sessions} 次学习，"
                    f"覆盖 {topics_n} 个课题，累计约 {minutes} 分钟。"
                    + (f"在「{top_name}」方面已建立基础（掌握度约 {top_mastery}%）。" if top else "")
                    + "建议保持每周 2–3 次练习，逐步建立学习习惯。"
                ),
                "en": (
                    f"Your child has just started with Dreamer AI — {sessions} sessions, "
                    f"{topics_n} topic(s), about {minutes} minutes in total."
                    + (f" Foundations are forming in {top_name} (about {top_mastery}% mastery)." if top else "")
                    + " Aim for 2–3 short practices per week to build a steady routine."
                ),
            }.get(lang_code, "")

        # standard
        delta_str = ""
        if top and top["mastery_delta"] > 0:
            delta_str = {
                "zh-hk": f"「{top_name}」掌握度較期初上升 {int(top['mastery_delta'])} 個百分點。",
                "zh-cn": f"「{top_name}」掌握度较期初上升 {int(top['mastery_delta'])} 个百分点。",
                "en": f"Mastery in {top_name} is up {int(top['mastery_delta'])} points from the start of the period.",
            }.get(lang_code, "")
        return {
            "zh-hk": (
                f"呢段時間囝囡共進行咗 {sessions} 次學習，覆蓋 {topics_n} 個課題，"
                f"累計約 {minutes} 分鐘。" + delta_str
                + "整體學習投入穩定，繼續保持！"
            ),
            "zh-cn": (
                f"这段时间孩子共进行了 {sessions} 次学习，覆盖 {topics_n} 个课题，"
                f"累计约 {minutes} 分钟。" + delta_str
                + "整体学习投入稳定，继续保持！"
            ),
            "en": (
                f"Your child completed {sessions} sessions this period across "
                f"{topics_n} topic(s), about {minutes} minutes in total. " + delta_str
                + "Consistent engagement — keep it up!"
            ),
        }.get(lang_code, "")

    async def _narrative_llm(
        self, summary: dict, topics: List[dict], variant: str, lang_code: str
    ) -> Optional[str]:
        """LLM narrative via OpenRouter (codex_cli). Aggregate data only."""
        try:
            from .codex_cli import generate_code, is_available
        except Exception:
            return None
        if not is_available():
            return None

        lang_names = {"zh-hk": "Traditional Chinese (HK)", "zh-cn": "Simplified Chinese", "en": "English"}
        lang_name = lang_names.get(lang_code, "English")

        system_prompt = (
            "You are the parent-facing report writer for Dreamer AI, a "
            "learning companion for children. Write warm, concise, "
            "encouraging progress summaries. "
            "STRICT RULES: "
            "1) Use only the numbers and topic names provided — never invent data. "
            "2) Never output student identifiers, school names, or raw evidence. "
            "3) Use parent-friendly words; no deficit framing. "
            "4) Keep the summary under 800 characters. "
            "5) No markdown, no lists — one short paragraph."
        )

        topics_summary = "; ".join(
            f"{t['subject']} ({int(t['mastery_pct'])}% mastery)"
            for t in topics[:5]
        ) or "no topics yet"

        user_prompt = (
            f"Write a parent progress summary in {lang_name}.\n"
            f"Variant: {variant}\n"
            f"Sessions: {summary['session_count']}, "
            f"minutes: {int(summary['total_duration_seconds']/60)}, "
            f"topics touched: {summary['topics_touched']}\n"
            f"Topics: {topics_summary}"
        )

        try:
            text = await generate_code(
                system_prompt=system_prompt, prompt=user_prompt
            )
            text = (text or "").strip()
            if not text:
                return None
            return text[:MAX_NARRATIVE_CHARS]
        except Exception as exc:
            logger.warning("parent_report narrative LLM failed: %s", exc)
            return None

    # ── Report assembly ───────────────────────────────

    async def generate_report_async(
        self,
        student_id: str,
        period: str = "cycle",
        lang_code: str = "zh-hk",
        age_band: str = "P4-P6",
        include_safety: bool = False,
        use_llm_narrative: bool = True,
    ) -> dict:
        """Build full parent report (async path, LLM narrative)."""
        # 1. raw queries
        logs_all = self._query_assessment_logs(student_id, None, _now_iso())
        sessions_all = self._query_session_logs(student_id, None, _now_iso())
        snapshots = self._query_progress_snapshots(student_id)

        if not logs_all and not sessions_all and not snapshots:
            # New student — welcome report, never an error
            return self._empty_report(student_id, period, lang_code, use_llm_narrative)

        first_activity = None
        candidates = [l.get("created_at") for l in logs_all if l.get("created_at")]
        candidates += [s.get("created_at") for s in sessions_all if s.get("created_at")]
        candidates += [s.get("updated_at") for s in snapshots if s.get("updated_at")]
        if candidates:
            first_activity = min(candidates)

        start, end, days = self._period_window(period, first_activity)
        logs = logs_all if start is None else [
            l for l in logs_all
            if (l.get("created_at") or "") >= start
        ]
        sessions = sessions_all if start is None else [
            s for s in sessions_all
            if (s.get("created_at") or "") >= start
        ]

        obs_events = self._query_obs_events(student_id, start, end)
        duration_seconds = self._aggregate_duration(obs_events)
        total_tokens = self._aggregate_cost(obs_events)

        # 2. aggregates
        topic_ids = sorted({
            (l.get("topic_id") or "") for l in logs if l.get("topic_id")
        } | {
            (s.get("topic_id") or "") for s in snapshots if s.get("topic_id")
        })
        topic_ids = [t for t in topic_ids if t]

        summary = self._aggregate_summary(
            sessions, logs, duration_seconds, topic_ids
        )
        topics = self._build_topics(logs, snapshots, start, lang_code)
        timeline = self._build_timeline(sessions)

        # 3. variant — decided by JOURNEY totals (period-agnostic)
        first_session_iso = min(
            [s.get("created_at") for s in sessions_all if s.get("created_at")],
            default=None,
        )
        variant = self._pick_variant(len(sessions_all), first_session_iso)

        # 4. first_steps extras
        baseline = None
        roadmap = None
        if variant == "first_steps":
            baseline = self._build_baseline(logs_all, lang_code)
            snap_by_topic = {s.get("topic_id"): s for s in snapshots}
            roadmap = self._build_roadmap(topics, snap_by_topic, lang_code)

        # 5. narrative
        narrative = None
        if use_llm_narrative:
            narrative = await self._narrative_llm(
                summary, topics, variant, lang_code
            )
        if not narrative:
            narrative = self._narrative_template(summary, topics, lang_code, variant)

        # 6. assemble
        report = {
            "student_id": student_id,
            "variant": variant,
            "period": {
                "type": period,
                "from": start,
                "to": end,
                "days": days,
            },
            "summary": summary,
            "topics": topics,
            "activity_timeline": timeline,
            "baseline": baseline,
            "roadmap": roadmap,
            "portfolio_highlights": [],
        }
        if include_safety:
            report["safety_alerts"] = self._build_safety_alerts(obs_events)

        return {
            "content": narrative,
            "mode": "parent_report",
            "lang_code": lang_code,
            "age_band": None,
            "kid_label": None,
            "citations": [],
            "cost_summary": {"status": "ok", "total_tokens": total_tokens},
            "report": report,
        }

    def _empty_report(
        self, student_id: str, period: str, lang_code: str, use_llm_narrative: bool
    ) -> dict:
        start, end, days = self._period_window(period, None)
        narrative = {
            "zh-hk": "歡迎使用 Dreamer AI！暫時未有學習記錄，完成第一次練習後，呢度就會顯示進度概覽。",
            "zh-cn": "欢迎使用 Dreamer AI！暂时还没有学习记录，完成第一次练习后，这里就会显示进度概览。",
            "en": "Welcome to Dreamer AI! No learning records yet — complete your first practice and progress will appear here.",
        }.get(lang_code, "")
        return {
            "content": narrative,
            "mode": "parent_report",
            "lang_code": lang_code,
            "age_band": None,
            "kid_label": None,
            "citations": [],
            "cost_summary": {"status": "no_data", "total_tokens": 0},
            "report": {
                "student_id": student_id,
                "variant": "first_steps",
                "period": {"type": period, "from": start, "to": end, "days": days},
                "summary": {
                    "session_count": 0,
                    "total_duration_seconds": 0,
                    "topics_touched": 0,
                    "mode_distribution": {"DIRECT": 0, "CONTEXTUAL": 0, "HYBRID": 0},
                },
                "topics": [],
                "activity_timeline": [],
                "baseline": None,
                "roadmap": None,
                "portfolio_highlights": [],
            },
        }

    # ── Sync entry points ─────────────────────────────

    def generate_report(
        self,
        student_id: str,
        period: str = "cycle",
        lang_code: str = "zh-hk",
        age_band: str = "P4-P6",
        include_safety: bool = False,
    ) -> dict:
        """Sync report (template narrative; no LLM). Hermes-safe."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # Already inside an event loop → build sync path directly
            return self._generate_report_sync_core(
                student_id, period, lang_code, include_safety
            )
        return asyncio.run(
            self.generate_report_async(
                student_id,
                period=period,
                lang_code=lang_code,
                include_safety=include_safety,
                use_llm_narrative=False,
            )
        )

    def _generate_report_sync_core(
        self,
        student_id: str,
        period: str,
        lang_code: str,
        include_safety: bool,
    ) -> dict:
        """Pure-sync core (no asyncio) used inside a running loop."""
        logs_all = self._query_assessment_logs(student_id, None, _now_iso())
        sessions_all = self._query_session_logs(student_id, None, _now_iso())
        snapshots = self._query_progress_snapshots(student_id)

        if not logs_all and not sessions_all and not snapshots:
            return self._empty_report(student_id, period, lang_code, False)

        candidates = [l.get("created_at") for l in logs_all if l.get("created_at")]
        candidates += [s.get("created_at") for s in sessions_all if s.get("created_at")]
        candidates += [s.get("updated_at") for s in snapshots if s.get("updated_at")]
        first_activity = min(candidates) if candidates else None

        start, end, days = self._period_window(period, first_activity)
        logs = logs_all if start is None else [
            l for l in logs_all if (l.get("created_at") or "") >= start
        ]
        sessions = sessions_all if start is None else [
            s for s in sessions_all if (s.get("created_at") or "") >= start
        ]

        obs_events = self._query_obs_events(student_id, start, end)
        duration_seconds = self._aggregate_duration(obs_events)
        total_tokens = self._aggregate_cost(obs_events)

        topic_ids = sorted({
            (l.get("topic_id") or "") for l in logs if l.get("topic_id")
        } | {
            (s.get("topic_id") or "") for s in snapshots if s.get("topic_id")
        })
        topic_ids = [t for t in topic_ids if t]

        summary = self._aggregate_summary(sessions, logs, duration_seconds, topic_ids)
        topics = self._build_topics(logs, snapshots, start, lang_code)
        timeline = self._build_timeline(sessions)

        first_session_iso = min(
            [s.get("created_at") for s in sessions_all if s.get("created_at")],
            default=None,
        )
        variant = self._pick_variant(len(sessions_all), first_session_iso)

        baseline = None
        roadmap = None
        if variant == "first_steps":
            baseline = self._build_baseline(logs_all, lang_code)
            snap_by_topic = {s.get("topic_id"): s for s in snapshots}
            roadmap = self._build_roadmap(topics, snap_by_topic, lang_code)

        narrative = self._narrative_template(summary, topics, lang_code, variant)

        report = {
            "student_id": student_id,
            "variant": variant,
            "period": {"type": period, "from": start, "to": end, "days": days},
            "summary": summary,
            "topics": topics,
            "activity_timeline": timeline,
            "baseline": baseline,
            "roadmap": roadmap,
            "portfolio_highlights": [],
        }
        if include_safety:
            report["safety_alerts"] = self._build_safety_alerts(obs_events)

        return {
            "content": narrative,
            "mode": "parent_report",
            "lang_code": lang_code,
            "age_band": None,
            "kid_label": None,
            "citations": [],
            "cost_summary": {"status": "ok", "total_tokens": total_tokens},
            "report": report,
        }

    def execute(self, task_id: str, params: Dict) -> Dict:
        """Hermes-compatible entry (sync).

        Params:
            student_id: str (required)
            period: "weekly" | "cycle" | "journey" (default cycle)
            lang_code: "en" | "zh-hk" | "zh-cn" (default zh-hk)
            include_safety: bool (default False)
            capability: "report_gen" (default) | "progress_summary" | "db_query"
        """
        student_id = params.get("student_id", "")
        if not student_id:
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": "missing student_id",
            }
        capability = params.get("capability", "report_gen")
        period = params.get("period", "cycle")
        lang_code = params.get("lang_code", "zh-hk")
        include_safety = bool(params.get("include_safety", False))

        try:
            if capability == "db_query":
                table = params.get("table", "")
                return self._db_query_capability(task_id, student_id, table, params)
            if capability == "progress_summary":
                report = self.generate_report(
                    student_id, period=period, lang_code=lang_code,
                    include_safety=include_safety,
                )
                report["report"] = report["report"]["summary"]
                return {
                    "agent": self.AGENT_NAME,
                    "task_id": task_id,
                    "status": "ok",
                    "result": report,
                }
            # report_gen
            report = self.generate_report(
                student_id, period=period, lang_code=lang_code,
                include_safety=include_safety,
            )
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "ok",
                "result": report,
            }
        except Exception as exc:
            logger.exception("parent_report execute failed")
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _db_query_capability(
        self, task_id: str, student_id: str, table: str, params: Dict
    ) -> Dict:
        """Internal capability: parameterized single-table query."""
        allowed = {"assessment_logs", "session_logs", "progress_snapshots", "obs_events"}
        if table not in allowed:
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": f"table not allowed: {table}",
            }
        start = params.get("start")
        end = params.get("end", _now_iso())
        event_type = params.get("event_type")
        if table == "assessment_logs":
            rows = self._query_assessment_logs(student_id, start, end)
        elif table == "session_logs":
            rows = self._query_session_logs(student_id, start, end)
        elif table == "progress_snapshots":
            rows = self._query_progress_snapshots(student_id)
        else:
            rows = self._query_obs_events(student_id, start, end, event_type)
        return {
            "agent": self.AGENT_NAME,
            "task_id": task_id,
            "status": "ok",
            "result": {
                "table": table,
                "row_count": len(rows),
                "rows": rows,
            },
        }
