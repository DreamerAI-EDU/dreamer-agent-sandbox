"""
Dreamer AI Phase 7 — Plan Agent (D11 Plan-Proposal Flow v1.1)

Generates an 8-week (variable `duration_weeks`) learning plan proposal from
student baseline → rule-based validation layer (zero LLM) → Dreamer AI teacher
human gate (approve / request_changes / reject) → one-shot adjustment.

Real implementation: queries Dreamer DB (session_logs / assessment_logs /
progress_snapshots) for baseline, then builds the structured plan (spec §3)
via LLM (OpenRouter via codex_cli) with a rule-based stub fallback (CI-safe).

Capabilities (routed via execute params["capability"]):
  plan_proposal    — generate a new plan draft (default)
  approve          — teacher approves a pending plan
  request_changes  — teacher requests changes → regenerate (old superseded)
  reject           — teacher rejects a pending plan (does NOT consume adjustment)
  adjust           — one-shot adjustment of an approved plan (v2 supersedes v1)
  get_student_plan — student-visible plan (approved only)
  get_plan         — any-status plan lookup (teacher / ops)

Design decisions (D11 v1.1, boss-signed 2026-08-24):
  - Teacher human gate (NOT parent) — async gate, ops-level action.
  - One-shot adjustment: `adjustment.used` hard gate; only unfinished weeks
    regenerate; reject does NOT consume the adjustment budget.
  - `duration_weeks` is a field, not a constant (schema ready for 1-year).
  - Idempotent: one pending_review per student (new generation supersedes old
    pending; enforced by partial unique index in the migration).
  - Student visibility: only `approved` plans appear in student queries.
  - LLM unavailable → stub fallback keeps CI green (spec §6).
  - zh-cn depends on B26 (zh-cn enum already synced to main 3f79f76).

Schema contract: every response carries the 7-field envelope
(content / mode / lang_code / age_band / kid_label / citations / cost_summary)
plus the nested `plan` object. mode fixed to "plan_proposal".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_AGE_BANDS = ("P1-P3", "P4-P6", "S1-S3")
VALID_LANG_CODES = ("en", "zh-hk", "zh-cn")
VALID_4D = ("Dream", "Discover", "Design", "Deliver")

# parent_summary must NOT contain these internal/de-grading markers (§3)
LEAK_MARKERS = (
    "not yet", "developing", "achieved", "exemplary",
    "confidence", "rubric", "internal_label", "mastery_pct",
)
# welfare / sensitive topics must never appear (§4 safety)
SENSITIVE_MARKERS = (
    "welfare", "abuse", "self-harm", "suicide", "violence", "weapon",
)
# parent_summary must contain the expectation-management sentence (§3)
ADJUST_EXPECTATION_MARKERS = ("調整", "调整", "adjust")

MAX_LLM_TRIES = 2          # 1 initial generation + at most 1 regenerate (§4)
COST_CAP_TOKENS = 20000    # beyond cap → stub error template (§4 cost)
DEFAULT_DURATION_WEEKS = 8
PARENT_SUMMARY_MAX_CHARS = 600
WEEK_SESSION_EST_DEFAULT = 1

DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)
DB_PATH = os.path.abspath(DB_PATH)

# Manifest + KB root (relative to repo root, same layout as seed_kb.py)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANIFEST_PATH = os.path.join(REPO_ROOT, "kb", "manifest.yaml")
KB_ROOT = os.path.join(REPO_ROOT, "knowledge_bases")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plan_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    student_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    lang_code TEXT NOT NULL DEFAULT 'zh-hk',
    age_band TEXT NOT NULL DEFAULT 'P4-P6',
    duration_weeks INTEGER NOT NULL DEFAULT 8,
    cycle_label TEXT NOT NULL DEFAULT '',
    weeks TEXT NOT NULL DEFAULT '[]',
    parent_summary TEXT NOT NULL DEFAULT '',
    baseline_ref TEXT NOT NULL DEFAULT '{}',
    cost_summary TEXT NOT NULL DEFAULT '{}',
    review TEXT NOT NULL DEFAULT '{}',
    adjustment TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_plan_proposals_student
    ON plan_proposals(student_id, status, version);
CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_proposals_one_pending
    ON plan_proposals(student_id) WHERE status = 'pending_review';
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_plan_id() -> str:
    return f"plan_{uuid.uuid4().hex}"


def _parse_json_block(text: str) -> Any:
    """Extract JSON object/array from LLM output (mirrors assessment_agent)."""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        pass
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Plan Agent
# ---------------------------------------------------------------------------

class PlanAgent:
    """Plan proposal generation + teacher approval + one-shot adjustment."""

    AGENT_NAME = "plan"
    KB_OWNERSHIP: list = []
    KBS_READ = ["dreamer-core-kb"]
    CAPABILITIES = [
        "plan_proposal", "approve", "request_changes", "reject",
        "adjust", "get_student_plan", "get_plan",
    ]
    MODE_ALLOWLIST = None  # non-student-facing; explicitly invoked by scheduler

    def __init__(
        self,
        db_path: Optional[str] = None,
        manifest_path: Optional[str] = None,
        kb_root: Optional[str] = None,
        topic_pool: Optional[Dict[str, str]] = None,
        generator: Optional[Callable[[Dict], Optional[Dict]]] = None,
        llm_enabled: bool = False,
    ):
        self._db_path = os.path.abspath(db_path or DB_PATH)
        self._manifest_path = os.path.abspath(manifest_path or MANIFEST_PATH)
        self._kb_root = os.path.abspath(kb_root or KB_ROOT)
        # topic_pool: {topic_id: kb_name} — injectable for tests; None → live read
        self._injected_pool = topic_pool
        # generator: callable(context) -> Optional[plan dict]; None → stub
        # llm_enabled: when True AND no injected generator, try codex_cli LLM
        # path first, stub on failure (CI stays green without keys).
        self._generator = generator
        self._llm_enabled = llm_enabled
        self._ensure_table()

    # ── DB helpers ────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA read_uncommitted=1")
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # ── Manifest / topic pool (dynamic read, zero LLM) ──

    def _load_manifest_kb_names(self) -> List[str]:
        """Parse kb/manifest.yaml KB names without a YAML dependency."""
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            logger.warning("plan_agent: manifest unreadable: %s", exc)
            return []
        names = []
        for line in text.splitlines():
            m = re.match(r"^\s*-\s*name:\s*(\S+)\s*$", line)
            if m:
                names.append(m.group(1))
        return names

    def _load_topic_pool_from_kb(self) -> Dict[str, str]:
        """Scan knowledge_bases/<manifest kb>/**/*.md frontmatter for topic_id.

        Only manifest KBs are accepted (spec §4: topic_ids ⊆ manifest topics).
        The pool grows automatically when the boss adds lesson plans.
        """
        pool: Dict[str, str] = {}
        for kb in self._load_manifest_kb_names():
            kb_dir = os.path.join(self._kb_root, kb)
            if not os.path.isdir(kb_dir):
                continue
            for root, _dirs, files in os.walk(kb_dir):
                for fn in files:
                    if not fn.endswith(".md"):
                        continue
                    path = os.path.join(root, fn)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            head = f.read(2000)
                    except OSError:
                        continue
                    m = re.search(r"^topic_id:\s*(\S+)", head, re.MULTILINE)
                    if m:
                        pool.setdefault(m.group(1), kb)
        return pool

    def _get_topic_pool(self) -> Dict[str, str]:
        if self._injected_pool is not None:
            return dict(self._injected_pool)
        return self._load_topic_pool_from_kb()

    # ── Student profile / baseline ────────────────────

    def _query_latest_session(self, student_id: str) -> Optional[dict]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT lang_code, age_band FROM session_logs
                       WHERE student_id=?
                       ORDER BY created_at DESC, id DESC LIMIT 1""",
                    (student_id,),
                ).fetchone()
            return dict(row) if row else None
        except sqlite3.OperationalError:
            return None

    def _query_assessment_logs(self, student_id: str) -> List[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT id, topic_id, internal_label, confidence,
                              rubric_id, created_at
                       FROM assessment_logs
                       WHERE student_id=?
                       ORDER BY created_at ASC""",
                    (student_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _resolve_profile(
        self, student_id: str, params: Dict
    ) -> Dict[str, str]:
        """age_band / lang_code: explicit params win, else latest session."""
        lang = params.get("lang_code") or ""
        band = params.get("age_band") or ""
        if not lang or not band:
            sess = self._query_latest_session(student_id)
            if sess:
                lang = lang or sess.get("lang_code") or ""
                band = band or sess.get("age_band") or ""
        return {
            "lang_code": lang if lang in VALID_LANG_CODES else "zh-hk",
            "age_band": band if band in VALID_AGE_BANDS else "P4-P6",
        }

    # ── Stub generator (deterministic, CI-safe) ───────

    def _stub_plan(
        self,
        student_id: str,
        profile: Dict[str, str],
        duration_weeks: int,
        cycle_label: str,
        frozen_weeks: Optional[List[dict]] = None,
        regenerate_from: int = 0,
        teacher_comment: str = "",
        performance_ref: Optional[dict] = None,
    ) -> dict:
        """Deterministic template plan. Always passes the validation layer.

        frozen_weeks: list of already-finished week dicts (adjustment only) —
        these are copied verbatim and never regenerated (spec §5).
        regenerate_from: 0-based index where regeneration starts.
        """
        lang = profile.get("lang_code", "zh-hk")
        pool = self._get_topic_pool()
        topic_ids = sorted(pool.keys())
        if not topic_ids:
            topic_ids = [f"missing-pool-{i}" for i in range(duration_weeks)]

        theme_tpl = {
            "zh-hk": {
                "Dream": "夢想啟航", "Discover": "發現小宇宙",
                "Design": "動手設計", "Deliver": "展示成果",
            },
            "zh-cn": {
                "Dream": "梦想启航", "Discover": "发现小宇宙",
                "Design": "动手设计", "Deliver": "展示成果",
            },
            "en": {
                "Dream": "Dream Launch", "Discover": "Discover the World",
                "Design": "Hands-on Design", "Deliver": "Showcase",
            },
        }[lang]
        artifact_tpl = {
            "zh-hk": "完成一份關於本週主題嘅小作品（portfolio 候選）",
            "zh-cn": "完成一份关于本周主题的小作品（portfolio 候选）",
            "en": "Complete a small artifact on this week's theme (portfolio candidate)",
        }[lang]

        weeks: List[dict] = []
        if frozen_weeks:
            weeks = [dict(w) for w in frozen_weeks]
        start = len(weeks)
        for i in range(start, duration_weeks):
            comp = VALID_4D[i % 4]
            secondary = VALID_4D[(i + 2) % 4] if i % 2 == 1 else None
            focus = [comp] if secondary is None else [comp, secondary]
            tid = topic_ids[i % len(topic_ids)] if topic_ids else f"t{i}"
            weeks.append({
                "week": i + 1,
                "theme": f"{theme_tpl[comp]} ({i + 1})",
                "competency_focus": focus,
                "topic_ids": [tid],
                "artifact_goal": artifact_tpl,
                "session_est": WEEK_SESSION_EST_DEFAULT,
            })

        parent_summary = self._parent_summary_template(lang)
        now = _now_iso()
        plan = {
            "plan_id": _new_plan_id(),
            "version": 1,
            "student_id": student_id,
            "created_at": now,
            "status": "pending_review",
            "lang_code": profile.get("lang_code", "zh-hk"),
            "age_band": profile.get("age_band", "P4-P6"),
            "duration_weeks": duration_weeks,
            "cycle_label": cycle_label,
            "weeks": weeks,
            "parent_summary": parent_summary,
            "baseline_ref": {"assessment_log_ids": []},
            "cost_summary": {"tokens_in": 0, "tokens_out": 0, "est_cost_hkd": 0.0},
            "review": {
                "decided_by": None, "decided_by_role": "teacher",
                "decided_at": None, "comment": None,
            },
            "adjustment": {
                "used": False, "used_at": None, "reason": None,
                "performance_ref": {"progress_snapshot_ids": []},
                "result_plan_id": None,
            },
        }
        if teacher_comment or performance_ref:
            plan["adjustment"] = {
                "used": True,
                "used_at": now,
                "reason": teacher_comment or "",
                "performance_ref": performance_ref
                or {"progress_snapshot_ids": []},
                "result_plan_id": None,
            }
        return plan

    def _parent_summary_template(self, lang_code: str) -> str:
        tpl = {
            "zh-hk": (
                "呢份八週學習計劃會帶住囝囡一步步探索、設計同展示自己嘅作品。"
                "計劃會按學習表現調整一次，確保進度啱啱好。"
            ),
            "zh-cn": (
                "这份八周学习计划会带着孩子一步步探索、设计并展示自己的作品。"
                "计划会根据学习表现调整一次，确保进度恰到好处。"
            ),
            "en": (
                "This 8-week learning plan guides your child through exploring, "
                "designing and showcasing their own work. The plan will be "
                "adjusted once based on learning progress to keep the pace just right."
            ),
        }
        return tpl.get(lang_code, tpl["zh-hk"])[:PARENT_SUMMARY_MAX_CHARS]

    # ── LLM generator (OpenRouter via codex_cli) ──────

    def _pick_generator(self) -> Callable[[Dict], Optional[Dict]]:
        """Injected generator wins; else LLM path only when llm_enabled."""
        if self._generator is not None:
            return self._generator
        if self._llm_enabled:
            return self._default_generator
        return lambda _ctx: None  # stub-only (CI-safe, no network probe)

    def _default_generator(self, context: Dict) -> Optional[dict]:
        """Real LLM path; returns parsed plan dict or None (unavailable/fail)."""
        try:
            from .codex_cli import generate_code, is_available
        except Exception:
            return None
        if not is_available():
            return None

        pool = self._get_topic_pool()
        topic_ids = sorted(pool.keys())
        lang = context.get("profile", {}).get("lang_code", "zh-hk")
        lang_names = {"zh-hk": "Traditional Chinese (HK)",
                      "zh-cn": "Simplified Chinese", "en": "English"}
        lang_name = lang_names.get(lang, "English")

        schema_hint = {
            "plan_id": "plan_<uuid>", "version": 1,
            "student_id": context["student_id"],
            "status": "pending_review",
            "lang_code": lang, "age_band": context["profile"]["age_band"],
            "duration_weeks": context["duration_weeks"],
            "cycle_label": context["cycle_label"],
            "weeks": [
                {
                    "week": 1, "theme": "kid-facing theme",
                    "competency_focus": ["Dream", "Discover"],
                    "topic_ids": ["<real topic_id from pool>"],
                    "artifact_goal": "week artifact (portfolio candidate)",
                    "session_est": 1,
                }
            ],
            "parent_summary": "one paragraph for parents, MUST mention the plan "
                              "will be adjusted once based on learning progress",
            "baseline_ref": {"assessment_log_ids": []},
            "cost_summary": {"tokens_in": 0, "tokens_out": 0, "est_cost_hkd": 0.0},
            "review": {"decided_by": None, "decided_by_role": "teacher",
                       "decided_at": None, "comment": None},
            "adjustment": {"used": False, "used_at": None, "reason": None,
                           "performance_ref": {"progress_snapshot_ids": []},
                           "result_plan_id": None},
        }

        system_prompt = (
            "You are the curriculum planner for Dreamer AI, a learning "
            "companion for children. Produce a structured JSON learning plan. "
            "STRICT RULES: "
            "1) topic_ids MUST come only from the provided pool — never invent. "
            "2) Each week 1-2 competency_focus drawn from Dream/Discover/"
            "Design/Deliver; the WHOLE plan must cover all four at least once. "
            "3) Exactly len(weeks) == duration_weeks weeks, week numbered 1..N. "
            "4) parent_summary: kid-safe, parent-facing, MUST contain the "
            "expectation that the plan will be adjusted once; never output "
            "internal labels, confidence, rubric ids, or raw evidence. "
            "5) No markdown, no code fences — raw JSON only. "
            "6) Write theme/artifact_goal/parent_summary in " + lang_name + "."
        )
        user_prompt = (
            f"Student: {context['student_id']}\n"
            f"age_band: {context['profile']['age_band']}\n"
            f"lang_code: {lang}\n"
            f"duration_weeks: {context['duration_weeks']}\n"
            f"cycle_label: {context['cycle_label']}\n"
            f"Allowed topic pool ({len(topic_ids)}): {', '.join(topic_ids)}\n"
            + (f"Teacher feedback / adjustment context: {context.get('teacher_comment', '')}\n"
               if context.get("teacher_comment") else "")
            + f"Return the plan object matching this schema: {json.dumps(schema_hint)}"
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # inside a running event loop — cannot nest asyncio.run → stub fallback
            return None
        try:
            raw = asyncio.run(
                generate_code(system_prompt=system_prompt, prompt=user_prompt)
            )
            text = _parse_json_block(raw)
        except Exception as exc:
            logger.warning("plan_agent LLM failed: %s", exc)
            return None
        if not isinstance(text, dict):
            return None
        return text

    # ── Validation layer (zero LLM, spec §4) ──────────

    def _validate_plan(
        self, plan: Any, profile: Dict[str, str]
    ) -> List[str]:
        """Return list of validation errors; empty list = valid."""
        errors: List[str] = []
        if not isinstance(plan, dict):
            return ["plan is not a JSON object"]

        # structure
        for key in (
            "plan_id", "version", "student_id", "created_at", "status",
            "lang_code", "age_band", "duration_weeks", "cycle_label",
            "weeks", "parent_summary", "baseline_ref", "cost_summary",
            "review", "adjustment",
        ):
            if key not in plan:
                errors.append(f"missing field: {key}")
        if errors:
            return errors

        duration = plan.get("duration_weeks")
        weeks = plan.get("weeks")
        if not isinstance(duration, int) or duration < 1:
            errors.append("duration_weeks must be a positive integer")
        if not isinstance(weeks, list):
            errors.append("weeks must be a list")
            return errors
        if len(weeks) != duration:
            errors.append(
                f"len(weeks)={len(weeks)} != duration_weeks={duration}"
            )
        for idx, w in enumerate(weeks):
            if not isinstance(w, dict):
                errors.append(f"week[{idx}] is not an object")
                continue
            if w.get("week") != idx + 1:
                errors.append(f"week[{idx}].week must be {idx + 1}")
            for key in ("theme", "competency_focus", "topic_ids",
                        "artifact_goal", "session_est"):
                if key not in w:
                    errors.append(f"week[{idx}] missing field: {key}")
            cf = w.get("competency_focus")
            if not isinstance(cf, list) or not cf:
                errors.append(f"week[{idx}].competency_focus must be non-empty list")
            else:
                if len(cf) > 2:
                    errors.append(f"week[{idx}].competency_focus max 2")
                for c in cf:
                    if c not in VALID_4D:
                        errors.append(f"week[{idx}].competency_focus invalid: {c}")

        # topic existence (hard gate — dynamic manifest read)
        pool = self._get_topic_pool()
        for idx, w in enumerate(weeks if isinstance(weeks, list) else []):
            for tid in (w.get("topic_ids") or []) if isinstance(w, dict) else []:
                if tid not in pool:
                    errors.append(f"week[{idx}] hallucinated topic_id: {tid}")

        # age band
        if plan.get("age_band") not in VALID_AGE_BANDS:
            errors.append(f"invalid age_band: {plan.get('age_band')}")
        elif plan.get("age_band") != profile.get("age_band"):
            errors.append(
                f"age_band mismatch: plan={plan.get('age_band')} "
                f"profile={profile.get('age_band')}"
            )
        if plan.get("lang_code") not in VALID_LANG_CODES:
            errors.append(f"invalid lang_code: {plan.get('lang_code')}")

        # 4D coverage (whole plan)
        covered = set()
        for w in weeks if isinstance(weeks, list) else []:
            if isinstance(w, dict):
                for c in (w.get("competency_focus") or []):
                    if c in VALID_4D:
                        covered.add(c)
        missing_4d = [c for c in VALID_4D if c not in covered]
        if missing_4d:
            errors.append(f"4D coverage missing: {','.join(missing_4d)}")

        # parent_summary safety (label leak + sensitive + expectation sentence)
        ps = str(plan.get("parent_summary") or "").lower()
        for marker in LEAK_MARKERS:
            if marker in ps:
                errors.append(f"parent_summary label leak marker: {marker}")
        for marker in SENSITIVE_MARKERS:
            if marker in ps:
                errors.append(f"parent_summary sensitive marker: {marker}")
        if not any(m in ps for m in ADJUST_EXPECTATION_MARKERS):
            errors.append("parent_summary missing adjustment expectation sentence")

        return errors

    # ── Persistence ───────────────────────────────────

    def _supersede_pending(self, student_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET status='superseded', updated_at=?
                   WHERE student_id=? AND status='pending_review'""",
                (_now_iso(), student_id),
            )
            conn.commit()

    def _insert_plan(self, plan: dict) -> str:
        """Insert plan row; returns plan_id. Assumes pending already superseded."""
        # Force a fresh plan_id: LLM generators may echo a fixed id and would
        # otherwise collide on the UNIQUE constraint (idempotency guard).
        plan_id = "plan_" + uuid.uuid4().hex
        plan["plan_id"] = plan_id
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO plan_proposals
                   (plan_id, version, student_id, status, lang_code, age_band,
                    duration_weeks, cycle_label, weeks, parent_summary,
                    baseline_ref, cost_summary, review, adjustment,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    plan_id, int(plan.get("version") or 1),
                    plan.get("student_id", ""),
                    plan.get("status", "pending_review"),
                    plan.get("lang_code", "zh-hk"),
                    plan.get("age_band", "P4-P6"),
                    int(plan.get("duration_weeks") or 8),
                    plan.get("cycle_label", ""),
                    json.dumps(plan.get("weeks", []), ensure_ascii=False),
                    plan.get("parent_summary", ""),
                    json.dumps(plan.get("baseline_ref", {}), ensure_ascii=False),
                    json.dumps(plan.get("cost_summary", {}), ensure_ascii=False),
                    json.dumps(plan.get("review", {}), ensure_ascii=False),
                    json.dumps(plan.get("adjustment", {}), ensure_ascii=False),
                    plan.get("created_at") or _now_iso(),
                    _now_iso(),
                ),
            )
            conn.commit()
        return plan_id

    def _fetch_plan(self, plan_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plan_proposals WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def _fetch_student_plan(self, student_id: str, status: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM plan_proposals
                   WHERE student_id=? AND status=?
                   ORDER BY version DESC LIMIT 1""",
                (student_id, status),
            ).fetchone()
        return self._row_to_plan(row) if row else None

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> dict:
        def _load(raw: str, default: Any) -> Any:
            try:
                return json.loads(raw) if raw else default
            except (json.JSONDecodeError, TypeError):
                return default
        return {
            "plan_id": row["plan_id"],
            "version": row["version"],
            "student_id": row["student_id"],
            "status": row["status"],
            "lang_code": row["lang_code"],
            "age_band": row["age_band"],
            "duration_weeks": row["duration_weeks"],
            "cycle_label": row["cycle_label"],
            "weeks": _load(row["weeks"], []),
            "parent_summary": row["parent_summary"],
            "baseline_ref": _load(row["baseline_ref"], {}),
            "cost_summary": _load(row["cost_summary"], {}),
            "review": _load(row["review"], {}),
            "adjustment": _load(row["adjustment"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── Generation flow ───────────────────────────────

    def generate_plan(
        self,
        student_id: str,
        params: Optional[Dict] = None,
    ) -> Dict:
        """Generate plan draft → validate → (regenerate once) → write pending.

        Idempotent: supersedes any existing pending_review for the student.
        """
        params = params or {}
        profile = self._resolve_profile(student_id, params)
        duration_weeks = int(params.get("duration_weeks", DEFAULT_DURATION_WEEKS))
        if duration_weeks < 1:
            return self._error("duration_weeks must be a positive integer")
        cycle_label = params.get("cycle_label") or self._default_cycle_label()
        logs = self._query_assessment_logs(student_id)
        baseline_ref = {"assessment_log_ids": [str(l["id"]) for l in logs]}

        context = {
            "student_id": student_id,
            "profile": profile,
            "duration_weeks": duration_weeks,
            "cycle_label": cycle_label,
            "baseline_ref": baseline_ref,
        }

        plan = None
        generator = self._pick_generator()
        errors: List[str] = []
        for attempt in range(MAX_LLM_TRIES):
            try:
                if attempt > 0:
                    # regenerate: inject validation errors into context
                    ctx = dict(context)
                    ctx["teacher_comment"] = (
                        f"Previous draft rejected by validation: {'; '.join(errors)}"
                    )
                    plan = generator(ctx)
                else:
                    plan = generator(context)
            except Exception as exc:
                # LLM crashed → fall back to stub (spec §4 LLM stub fallback)
                errors.append(f"{type(exc).__name__}: {exc}")
                plan = None
            if plan is None:
                # LLM unavailable or failed → stub fallback (CI-safe)
                plan = self._stub_plan(
                    student_id, profile, duration_weeks, cycle_label
                )
                break
            errors = self._validate_plan(plan, profile)
            if not errors:
                break
            if attempt == MAX_LLM_TRIES - 1:
                plan = None  # force error template below
        else:
            plan = None

        if plan is None:
            # error template: deterministic stub, guaranteed valid
            plan = self._stub_plan(
                student_id, profile, duration_weeks, cycle_label
            )
            plan["generation_note"] = "error_template"
        else:
            plan.setdefault("baseline_ref", baseline_ref)
            if not plan.get("cost_summary"):
                plan["cost_summary"] = {
                    "tokens_in": 0, "tokens_out": 0, "est_cost_hkd": 0.0,
                }
            # cost cap (§4): beyond cap → stub error template
            cs = plan.get("cost_summary") or {}
            if int(cs.get("tokens_in") or 0) + int(cs.get("tokens_out") or 0) > COST_CAP_TOKENS:
                plan = self._stub_plan(
                    student_id, profile, duration_weeks, cycle_label
                )
                plan["generation_note"] = "cost_cap_error_template"

        plan.setdefault("student_id", student_id)
        plan.setdefault("lang_code", profile["lang_code"])
        plan.setdefault("age_band", profile["age_band"])
        plan.setdefault("duration_weeks", duration_weeks)
        plan.setdefault("cycle_label", cycle_label)
        plan["status"] = "pending_review"

        # final validation guard (defense in depth)
        final_errors = self._validate_plan(plan, profile)
        if final_errors:
            return self._error("plan failed final validation: " + "; ".join(final_errors))

        # idempotency: supersede old pending → insert new
        self._supersede_pending(student_id)
        try:
            self._insert_plan(plan)
        except sqlite3.IntegrityError as exc:
            # concurrent pending insert — supersede again then retry once
            self._supersede_pending(student_id)
            try:
                self._insert_plan(plan)
            except sqlite3.IntegrityError as exc2:
                return self._error(f"idempotency conflict: {exc2}")
        return self._envelope(plan)

    def _default_cycle_label(self) -> str:
        now = datetime.now(timezone.utc)
        quarter = (now.month - 1) // 3 + 1
        return f"{now.year}-Q{quarter}-cycle-1"

    # ── Teacher gate (approve / request_changes / reject) ──

    def approve(
        self, plan_id: str, decided_by: str, comment: Optional[str] = None
    ) -> Dict:
        plan = self._fetch_plan(plan_id)
        if plan is None:
            return self._error("plan not found")
        if plan["status"] != "pending_review":
            return self._error(f"cannot approve plan in status: {plan['status']}")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET status='approved', updated_at=?,
                   review=? WHERE plan_id=?""",
                (
                    now,
                    json.dumps({
                        "decided_by": decided_by,
                        "decided_by_role": "teacher",
                        "decided_at": now,
                        "comment": comment,
                    }, ensure_ascii=False),
                    plan_id,
                ),
            )
            conn.commit()
        approved = self._fetch_plan(plan_id)
        return self._envelope(approved)

    def request_changes(
        self, plan_id: str, decided_by: str, comment: str
    ) -> Dict:
        """Teacher asks for changes → old pending superseded, new draft generated.

        The comment is mandatory (it is the regeneration instruction). The new
        plan inherits baseline / duration / lang; version bumps by one so the
        audit trail is unambiguous. Adjustment budget is NOT consumed.
        """
        plan = self._fetch_plan(plan_id)
        if plan is None:
            return self._error("plan not found")
        if plan["status"] != "pending_review":
            return self._error(f"cannot request changes on status: {plan['status']}")
        if not comment or not comment.strip():
            return self._error("comment is required for request_changes")

        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET status='superseded', updated_at=?,
                   review=? WHERE plan_id=?""",
                (
                    now,
                    json.dumps({
                        "decided_by": decided_by,
                        "decided_by_role": "teacher",
                        "decided_at": now,
                        "comment": comment,
                    }, ensure_ascii=False),
                    plan_id,
                ),
            )
            conn.commit()

        profile = {
            "lang_code": plan["lang_code"], "age_band": plan["age_band"],
        }
        context = {
            "student_id": plan["student_id"],
            "profile": profile,
            "duration_weeks": plan["duration_weeks"],
            "cycle_label": plan["cycle_label"],
            "baseline_ref": plan.get("baseline_ref", {}),
            "teacher_comment": comment,
        }
        generator = self._pick_generator()
        try:
            new_plan = generator(context)
        except Exception as exc:
            new_plan = None
        if new_plan is None:
            new_plan = self._stub_plan(
                plan["student_id"], profile, plan["duration_weeks"],
                plan["cycle_label"],
            )
        errors = self._validate_plan(new_plan, profile)
        if errors:
            new_plan = self._stub_plan(
                plan["student_id"], profile, plan["duration_weeks"],
                plan["cycle_label"],
            )
            new_plan["generation_note"] = "error_template"
        new_plan["version"] = int(plan["version"]) + 1
        new_plan["status"] = "pending_review"
        new_plan["student_id"] = plan["student_id"]
        new_plan["lang_code"] = profile["lang_code"]
        new_plan["age_band"] = profile["age_band"]
        new_plan.setdefault("baseline_ref", plan.get("baseline_ref", {}))
        new_plan.setdefault("cycle_label", plan["cycle_label"])
        new_plan["review"] = {
            "decided_by": None, "decided_by_role": "teacher",
            "decided_at": None, "comment": None,
        }
        self._insert_plan(new_plan)
        return self._envelope(self._fetch_plan(new_plan["plan_id"]))

    def reject(
        self, plan_id: str, decided_by: str, comment: Optional[str] = None
    ) -> Dict:
        """Reject a pending plan. Does NOT consume the adjustment budget."""
        plan = self._fetch_plan(plan_id)
        if plan is None:
            return self._error("plan not found")
        if plan["status"] != "pending_review":
            return self._error(f"cannot reject plan in status: {plan['status']}")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET status='rejected', updated_at=?,
                   review=? WHERE plan_id=?""",
                (
                    now,
                    json.dumps({
                        "decided_by": decided_by,
                        "decided_by_role": "teacher",
                        "decided_at": now,
                        "comment": comment,
                    }, ensure_ascii=False),
                    plan_id,
                ),
            )
            conn.commit()
        rejected = self._fetch_plan(plan_id)
        return self._envelope(rejected)

    # ── One-shot adjustment (v1.1) ────────────────────

    def adjust(
        self,
        plan_id: str,
        decided_by: str,
        comment: str,
        performance_ref: Optional[Dict] = None,
        completed_weeks: int = 0,
    ) -> Dict:
        """One-shot adjustment of an APPROVED plan.

        - `adjustment.used` hard gate: second adjustment is rejected.
        - Only unfinished weeks (completed_weeks..duration_weeks-1) regenerate;
          already-finished weeks are frozen verbatim (spec §5).
        - Produces v2 (pending_review) which supersedes v1; full history kept.
        """
        plan = self._fetch_plan(plan_id)
        if plan is None:
            return self._error("plan not found")
        if plan["status"] != "approved":
            return self._error(f"adjust requires approved plan, got: {plan['status']}")
        adj = plan.get("adjustment") or {}
        if adj.get("used"):
            return self._error(
                "adjustment already used for this plan (one-shot hard gate)"
            )
        if not comment or not comment.strip():
            return self._error("comment is required for adjust")

        duration = int(plan["duration_weeks"])
        if completed_weeks < 0 or completed_weeks > duration:
            return self._error(
                f"completed_weeks out of range: {completed_weeks} (0..{duration})"
            )
        if completed_weeks >= duration:
            return self._error("no unfinished weeks left to adjust")

        profile = {
            "lang_code": plan["lang_code"], "age_band": plan["age_band"],
        }
        frozen = plan["weeks"][:completed_weeks]
        perf = performance_ref or {"progress_snapshot_ids": []}

        generator = self._pick_generator()
        context = {
            "student_id": plan["student_id"],
            "profile": profile,
            "duration_weeks": duration,
            "cycle_label": plan["cycle_label"],
            "baseline_ref": plan.get("baseline_ref", {}),
            "teacher_comment": comment,
            "performance_ref": perf,
            "completed_weeks": completed_weeks,
        }
        try:
            new_plan = generator(context)
        except Exception as exc:
            new_plan = None
        if new_plan is None:
            new_plan = self._stub_plan(
                plan["student_id"], profile, duration, plan["cycle_label"],
                frozen_weeks=frozen, regenerate_from=completed_weeks,
                teacher_comment=comment, performance_ref=perf,
            )
        else:
            # merge: freeze completed weeks verbatim, keep regenerated tail
            tail = new_plan.get("weeks") or []
            new_plan["weeks"] = frozen + tail[len(frozen):] if len(tail) >= completed_weeks else frozen + tail
            new_plan["duration_weeks"] = duration

        errors = self._validate_plan(new_plan, profile)
        if errors:
            new_plan = self._stub_plan(
                plan["student_id"], profile, duration, plan["cycle_label"],
                frozen_weeks=frozen, regenerate_from=completed_weeks,
                teacher_comment=comment, performance_ref=perf,
            )
            new_plan["generation_note"] = "adjustment_error_template"

        new_plan["version"] = int(plan["version"]) + 1
        new_plan["student_id"] = plan["student_id"]
        new_plan["lang_code"] = profile["lang_code"]
        new_plan["age_band"] = profile["age_band"]
        new_plan["duration_weeks"] = duration
        new_plan["cycle_label"] = plan["cycle_label"]
        new_plan["status"] = "pending_review"
        new_plan["review"] = {
            "decided_by": None, "decided_by_role": "teacher",
            "decided_at": None, "comment": None,
        }
        # v2 inherits the consumed adjustment budget (one-shot, whole cycle)
        new_plan["adjustment"] = {
            "used": True,
            "used_at": _now_iso(),
            "reason": comment,
            "performance_ref": perf,
            "result_plan_id": None,
        }

        # v1: superseded + link result (result_plan_id patched after insert,
        # since the final plan_id is minted inside _insert_plan)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET status='superseded', updated_at=?,
                   adjustment=? WHERE plan_id=?""",
                (
                    now,
                    json.dumps({
                        "used": True,
                        "used_at": now,
                        "reason": comment,
                        "performance_ref": perf,
                        "result_plan_id": None,
                    }, ensure_ascii=False),
                    plan_id,
                ),
            )
            conn.commit()

        pid = self._insert_plan(new_plan)
        with self._connect() as conn:
            conn.execute(
                """UPDATE plan_proposals SET adjustment=? WHERE plan_id=?""",
                (
                    json.dumps({
                        "used": True,
                        "used_at": now,
                        "reason": comment,
                        "performance_ref": perf,
                        "result_plan_id": pid,
                    }, ensure_ascii=False),
                    plan_id,
                ),
            )
            conn.commit()
        return self._envelope(self._fetch_plan(pid))

    # ── Visibility ────────────────────────────────────

    def get_student_plan(self, student_id: str) -> Dict:
        """Student-visible plan: only `approved` (spec §6)."""
        plan = self._fetch_student_plan(student_id, "approved")
        if plan is None:
            return self._envelope(None)
        return self._envelope(plan)

    def get_plan(self, plan_id: str) -> Dict:
        plan = self._fetch_plan(plan_id)
        if plan is None:
            return self._error("plan not found")
        return self._envelope(plan)

    # ── Envelope / errors ─────────────────────────────

    @staticmethod
    def _envelope(plan: Optional[dict]) -> Dict:
        if plan is None:
            return {
                "content": "",
                "mode": "plan_proposal",
                "lang_code": "zh-hk",
                "age_band": None,
                "kid_label": None,
                "citations": [],
                "cost_summary": {"status": "no_data", "total_tokens": 0},
                "plan": None,
            }
        cs = plan.get("cost_summary") or {}
        return {
            "content": plan.get("parent_summary", ""),
            "mode": "plan_proposal",
            "lang_code": plan.get("lang_code", "zh-hk"),
            "age_band": plan.get("age_band", None),
            "kid_label": None,
            "citations": [],
            "cost_summary": {
                "status": "ok",
                "total_tokens": int(cs.get("tokens_in") or 0)
                + int(cs.get("tokens_out") or 0),
            },
            "plan": plan,
        }

    @staticmethod
    def _error(message: str) -> Dict:
        return {
            "content": "",
            "mode": "plan_proposal",
            "lang_code": "zh-hk",
            "age_band": None,
            "kid_label": None,
            "citations": [],
            "cost_summary": {"status": "no_data", "total_tokens": 0},
            "plan": None,
            "error": message,
        }

    # ── Hermes entry ──────────────────────────────────

    def execute(self, task_id: str, params: Dict) -> Dict:
        """Hermes-compatible entry (sync).

        Returns the same envelope as parent_report_agent:
            {"agent": "plan", "task_id": task_id,
             "status": "ok"|"error", "result": <7-field envelope>}

        Params:
            capability: "plan_proposal" (default) | "approve" |
                        "request_changes" | "reject" | "adjust" |
                        "get_student_plan" | "get_plan"
            student_id: str (required for generation / student queries)
            plan_id: str (required for approve / request_changes / reject /
                          adjust / get_plan)
            decided_by: str (teacher name / ops marker for gate actions)
            comment: str (required for request_changes / adjust)
            duration_weeks: int (default 8)
            age_band / lang_code: optional overrides
            completed_weeks: int (adjust only, default 0)
            performance_ref: dict (adjust only)
        """
        def ok(result: Dict) -> Dict:
            return {"agent": self.AGENT_NAME, "task_id": task_id,
                    "status": "ok", "result": result}

        def err(message: str) -> Dict:
            return {"agent": self.AGENT_NAME, "task_id": task_id,
                    "status": "error", "error": message}

        capability = params.get("capability", "plan_proposal")
        student_id = params.get("student_id", "")

        if capability == "approve":
            plan_id = params.get("plan_id", "")
            if not plan_id or not params.get("decided_by"):
                return err("plan_id and decided_by are required")
            result = self.approve(plan_id, params["decided_by"], params.get("comment"))
            return err(result["error"]) if result.get("error") else ok(result)
        if capability == "request_changes":
            plan_id = params.get("plan_id", "")
            if not plan_id or not params.get("decided_by"):
                return err("plan_id and decided_by are required")
            result = self.request_changes(
                plan_id, params["decided_by"], params.get("comment", "")
            )
            return err(result["error"]) if result.get("error") else ok(result)
        if capability == "reject":
            plan_id = params.get("plan_id", "")
            if not plan_id or not params.get("decided_by"):
                return err("plan_id and decided_by are required")
            result = self.reject(plan_id, params["decided_by"], params.get("comment"))
            return err(result["error"]) if result.get("error") else ok(result)
        if capability == "adjust":
            plan_id = params.get("plan_id", "")
            if not plan_id or not params.get("decided_by"):
                return err("plan_id and decided_by are required")
            result = self.adjust(
                plan_id, params["decided_by"], params.get("comment", ""),
                performance_ref=params.get("performance_ref"),
                completed_weeks=int(params.get("completed_weeks", 0)),
            )
            return err(result["error"]) if result.get("error") else ok(result)
        if capability == "get_student_plan":
            if not student_id:
                return err("student_id is required")
            return ok(self.get_student_plan(student_id))
        if capability == "get_plan":
            plan_id = params.get("plan_id", "")
            if not plan_id:
                return err("plan_id is required")
            return ok(self.get_plan(plan_id))

        # plan_proposal
        if not student_id:
            return err("student_id is required")
        try:
            return ok(self.generate_plan(student_id, params))
        except Exception as exc:
            logger.exception("plan_agent execute failed")
            return err(f"{type(exc).__name__}: {exc}")
