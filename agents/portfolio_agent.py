"""Dreamer AI Phase 6 Day 25 — Portfolio Agent.

Student-facing artifact showcase (NOT a report card).

Pipeline:
  1. Auto-candidates: assessment_logs label IN (achieved, exemplary)
     AND confidence >= 0.45  → upsert into portfolio_items (idempotent)
  2. growth_note derived from progress_snapshots (earliest vs latest mastery)
  3. Kid-Safe wrap: content passes rewrite_tone (age_band + lang_code aware)
  4. share_card payload per item — P5 PDPO red line:
     whitelist only (display_name first-name-only / title / artifact /
     competencies / kid_label / brand / generated_at).
     NEVER student_id / full name / school.

P4: mode_allowlist = CONTEXTUAL + HYBRID (DIRECT quiz marks stay out of
showcase so the portfolio keeps its project-achievement positioning).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .kid_safe.label_soften import soften_label
from .kid_safe.tone_rewrite import rewrite_tone

DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)
DB_PATH = os.path.abspath(DB_PATH)

CONFIDENCE_THRESHOLD = 0.45
INCLUDE_LABELS = ("achieved", "exemplary")
SHARE_CARD_WHITELIST = {
    "display_name",
    "item_id",
    "title",
    "artifact_summary",
    "competencies_4d",
    "kid_label",
    "brand",
    "generated_at",
}
SHARE_CARD_BLACKLIST = ("student_id", "school", "full_name", "name_last")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PortfolioAgent:
    """Student-facing portfolio agent backed by portfolio_items table."""

    AGENT_NAME = "portfolio"
    KB_OWNERSHIP = ["dreamer-portfolio"]
    KBS_READ = ["dreamer-psd", "dreamer-life_skills"]
    CAPABILITIES = ["portfolio_mgmt", "reflection_prompt", "artifact_curate"]
    MODE_ALLOWLIST = ["CONTEXTUAL", "HYBRID"]

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = os.path.abspath(db_path or DB_PATH)

    # ── DB helpers ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        """Idempotent bootstrap (mirrors migrations/phase4_portfolio.sql)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL UNIQUE,
                    student_id TEXT NOT NULL,
                    topic_id TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    evidence_excerpt TEXT NOT NULL DEFAULT '',
                    competencies_4d TEXT NOT NULL DEFAULT '[]',
                    growth_note TEXT NOT NULL DEFAULT '',
                    kid_label TEXT NOT NULL DEFAULT '',
                    internal_label TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    rubric_id TEXT NOT NULL DEFAULT '',
                    achieved_at TEXT NOT NULL,
                    linked_project_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portfolio_student "
                "ON portfolio_items(student_id, achieved_at)"
            )

    # ── Candidate query ───────────────────────────────────────────

    def _query_candidates(
        self, student_id: str, start: Optional[str] = None, end: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Auto-candidates: achieved/exemplary evidence with confidence >= 0.45."""
        params: List[Any] = [student_id, *INCLUDE_LABELS, CONFIDENCE_THRESHOLD]
        sql = (
            "SELECT id, student_id, topic_id, mode, internal_label, confidence,"
            " rubric_id, evidence_text, created_at"
            " FROM assessment_logs"
            " WHERE student_id = ? AND internal_label IN (?, ?)"
            " AND confidence >= ?"
        )
        if start:
            sql += " AND created_at >= ?"
            params.append(start)
        if end:
            sql += " AND created_at <= ?"
            params.append(end)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── Subject lookup ────────────────────────────────────────────

    def _subject_for_topic(self, topic_id: str) -> str:
        try:
            from .curriculum_navigator import CurriculumNavigator

            nav = CurriculumNavigator(db_path=self._db_path)
            meta = nav.get_topic_metadata(topic_id)
            if meta:
                return meta.get("subject", "")
        except Exception:
            pass
        return ""

    # ── Upsert ────────────────────────────────────────────────────

    def _upsert_item(
        self,
        candidate: Dict[str, Any],
        lang_code: str,
        age_band: str,
        competency_map: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """Insert or refresh a portfolio item from an auto candidate."""
        topic_id = candidate.get("topic_id", "")
        internal_label = candidate.get("internal_label", "")
        item_id = f"pf_{candidate['id']}"
        subject = self._subject_for_topic(topic_id)
        kid_label = soften_label(internal_label, age_band, lang_code, audience="kid_facing")
        competencies = list((competency_map or {}).get(topic_id, []))
        evidence = (candidate.get("evidence_text") or "").strip()
        excerpt = evidence[:200]
        title = subject or topic_id

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_items (
                    item_id, student_id, topic_id, subject, title, description,
                    evidence_excerpt, competencies_4d, growth_note, kid_label,
                    internal_label, confidence, rubric_id, achieved_at,
                    linked_project_id, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET
                    subject=excluded.subject,
                    title=excluded.title,
                    description=excluded.description,
                    evidence_excerpt=excluded.evidence_excerpt,
                    competencies_4d=excluded.competencies_4d,
                    kid_label=excluded.kid_label,
                    internal_label=excluded.internal_label,
                    confidence=excluded.confidence,
                    rubric_id=excluded.rubric_id,
                    updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    candidate.get("student_id", ""),
                    topic_id,
                    subject,
                    title,
                    "",
                    excerpt,
                    json.dumps(competencies),
                    "",  # growth_note filled in second pass
                    kid_label,
                    internal_label,
                    candidate.get("confidence", 0.0),
                    candidate.get("rubric_id", ""),
                    candidate.get("created_at", _now_iso()),
                    None,
                    _now_iso(),
                ),
            )

        return {
            "item_id": item_id,
            "topic_id": topic_id,
            "subject": subject,
            "title": title,
            "description": "",
            "evidence_excerpt": excerpt,
            "competencies_4d": competencies,
            "growth_note": "",
            "kid_label": kid_label,
            "internal_label": internal_label,
            "confidence": candidate.get("confidence", 0.0),
            "rubric_id": candidate.get("rubric_id", ""),
            "achieved_at": candidate.get("created_at", _now_iso()),
            "linked_project_id": None,
        }

    # ── Growth note ───────────────────────────────────────────────

    def _derive_growth_note(
        self, student_id: str, topic_id: str, lang_code: str
    ) -> str:
        """One-line improvement note from earliest vs latest assessment label.

        progress_snapshots keeps a single row per (student, topic), so growth
        is derived from the assessment_logs history for the same topic.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT internal_label FROM assessment_logs
                    WHERE student_id = ? AND topic_id = ?
                    ORDER BY created_at ASC
                    """,
                    (student_id, topic_id),
                ).fetchall()
            if not rows:
                return ""
            earliest = rows[0]["internal_label"]
            latest = rows[-1]["internal_label"]
            grew = earliest in ("not_yet", "developing") and latest in ("achieved", "exemplary")
            if grew:
                return (
                    "你喺呢個項目度有明顯進步！"
                    if lang_code == "zh-hk"
                    else "You've made great progress on this project!"
                )
            if latest in ("not_yet", "developing"):
                return (
                    "呢個項目仲有進步空間，繼續加油！"
                    if lang_code == "zh-hk"
                    else "Keep going — there's room to grow here!"
                )
            return (
                "你一直保持出色表現！"
                if lang_code == "zh-hk"
                else "You've stayed consistently strong!"
            )
        except Exception:
            return ""

    # ── Share card (P5 PDPO red line) ─────────────────────────────

    def _build_share_card(
        self, item: Dict[str, Any], display_name: str, lang_code: str
    ) -> Dict[str, Any]:
        """Self-contained share payload.

        Whitelist-only: NEVER student_id / full name / school.
        """
        card = {
            "display_name": (display_name or "Dreamer Explorer").strip(),
            "item_id": item.get("item_id", ""),
            "title": item.get("title", ""),
            "artifact_summary": item.get("evidence_excerpt", ""),
            "competencies_4d": item.get("competencies_4d", []),
            "kid_label": item.get("kid_label", ""),
            "brand": "Dreamer AI",
            "generated_at": _now_iso(),
        }
        # whitelist guard: drop anything not explicitly allowed
        card = {k: v for k, v in card.items() if k in SHARE_CARD_WHITELIST}
        # blacklist guard: never leak identity fields (defense in depth)
        for key in SHARE_CARD_BLACKLIST:
            if key in card:
                card.pop(key)
        return card

    # ── Main flow ─────────────────────────────────────────────────

    def generate_portfolio(
        self,
        student_id: str,
        lang_code: str = "zh-hk",
        age_band: str = "P4-P6",
        mode: str = "CONTEXTUAL",
        display_name: str = "",
        competency_map: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        if mode not in self.MODE_ALLOWLIST:
            raise ValueError(
                f"mode {mode!r} not in portfolio allowlist {self.MODE_ALLOWLIST}"
            )
        self._ensure_table()
        candidates = self._query_candidates(student_id)

        items: List[Dict[str, Any]] = []
        for cand in candidates:
            item = self._upsert_item(
                cand, lang_code=lang_code, age_band=age_band,
                competency_map=competency_map,
            )
            item["growth_note"] = self._derive_growth_note(
                student_id, item["topic_id"], lang_code
            )
            items.append(item)

        share_cards = [
            self._build_share_card(it, display_name, lang_code) for it in items
        ]

        # kid-facing narrative, passed through Kid-Safe tone layer
        if items:
            raw_content = (
                "你嘅作品集有新作品喇！睇吓你做到嘅嘢啦～"
                if lang_code == "zh-hk"
                else "Your portfolio has new pieces! Look what you've made!"
            )
        else:
            raw_content = (
                "繼續探索新項目，作品集就會慢慢豐富起嚟！"
                if lang_code == "zh-hk"
                else "Keep exploring new projects — your portfolio is growing!"
            )
        content = rewrite_tone(raw_content, age_band, lang_code)

        return {
            "content": content,
            "mode": mode,
            "lang_code": lang_code,
            "age_band": age_band,
            "kid_label": soften_label("achieved", age_band, lang_code, audience="kid_facing"),
            "citations": [],
            "cost_summary": {},
            "portfolio": {
                "student_id": student_id,
                "items": items,
                "share_cards": share_cards,
            },
        }

    # ── Hermes entry ──────────────────────────────────────────────

    def execute(self, task_id: str, params: Dict) -> Dict:
        """Hermes-compatible entry (sync).

        Params:
            student_id: str (required)
            mode: "CONTEXTUAL" | "HYBRID" (default CONTEXTUAL)
            lang_code: "en" | "zh-hk" | "zh-cn" (default zh-hk)
            age_band: "P1-P3" | "P4-P6" | "S1-S3" (default P4-P6)
            display_name: str first-name-only (P5 red line)
            competency_map: dict topic_id -> list[str] badges (optional)
            capability: "portfolio_mgmt" (default) | "reflection_prompt" | "artifact_curate"
        """
        student_id = params.get("student_id", "")
        if not student_id:
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": "missing student_id",
            }
        capability = params.get("capability", "portfolio_mgmt")
        if capability not in self.CAPABILITIES:
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": f"unsupported capability {capability}",
            }
        mode = params.get("mode", "CONTEXTUAL")
        lang_code = params.get("lang_code", "zh-hk")
        age_band = params.get("age_band", "P4-P6")
        try:
            result = self.generate_portfolio(
                student_id,
                lang_code=lang_code,
                age_band=age_band,
                mode=mode,
                display_name=params.get("display_name", ""),
                competency_map=params.get("competency_map"),
            )
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "ok",
                "result": result,
                "mode": mode,
                "grade_level": params.get("grade_level", 1),
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
