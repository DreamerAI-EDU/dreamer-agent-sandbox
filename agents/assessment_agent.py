"""
Dreamer AI Phase 3 — Assessment Agent (real implementation)

Replaces AssessmentAgentStub with real LLM-backed capabilities:
  quiz_gen      — generate quizzes via DeepTutorWSClient deep_question
  rubric_gen    — generate 4-level criterion-based rubrics
  auto_marking  — mark student answers → {internal_label, confidence,
                   evidence_text, rubric_id}
  progress_track — write assessment_logs + upsert progress_snapshots

Architecture:
  quiz_gen / rubric_gen / auto_marking → DeepTutorWSClient (async)
  progress_track → DB write (async fire-and-forget)
  auto_marking output → label_soften → kid_safe_wrap()

Compatibility: LLM unavailable → falls back to stub (keeps CI green).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import os
from typing import Any, Optional

from .kid_safe.label_soften import soften_label, get_mastery_pct, is_streak_improvement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERNAL_LABELS = ["not_yet", "developing", "achieved", "exemplary"]
DEFAULT_CONFIDENCE_THRESHOLD = 0.45  # below → don't write snapshot
DB_PATH = os.environ.get(
    "DREAMER_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "dreamer.db"),
)
DB_PATH = os.path.abspath(DB_PATH)


# ---------------------------------------------------------------------------
# Assessment Result Dataclass
# ---------------------------------------------------------------------------

class AssessmentResult:
    """Output of auto_marking."""

    __slots__ = (
        "internal_label", "confidence", "evidence_text",
        "rubric_id", "raw_response", "cost_summary",
    )

    def __init__(
        self,
        internal_label: str,
        confidence: float,
        evidence_text: str,
        rubric_id: str = "",
        raw_response: str = "",
        cost_summary: dict | None = None,
    ):
        self.internal_label = internal_label
        self.confidence = confidence
        self.evidence_text = evidence_text
        self.rubric_id = rubric_id
        self.raw_response = raw_response
        self.cost_summary = cost_summary or {}

    def to_dict(self) -> dict:
        return {
            "internal_label": self.internal_label,
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "rubric_id": self.rubric_id,
        }

    def is_confident(self, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
        return self.confidence >= threshold


# ---------------------------------------------------------------------------
# 3.1 Assessment Agent — Real Implementation
# ---------------------------------------------------------------------------

class AssessmentAgent:
    """Real Assessment Agent backed by DeepTutor WS + SQLite DB.

    Four capabilities — quiz_gen, rubric_gen, auto_marking, progress_track.
    """

    AGENT_NAME = "assessment"
    KB_OWNERSHIP = ["dreamer-rubrics"]
    KBS_READ = [
        "dreamer-maths", "dreamer-english", "dreamer-computing",
        "dreamer-science", "dreamer-l2l",
    ]
    CAPABILITIES = ["quiz_gen", "rubric_gen", "auto_marking", "progress_track"]
    MODE_ALLOWLIST = ["DIRECT", "HYBRID"]

    def __init__(self):
        self._ws_client = None                   # lazy-init in async context
        self._ws_client_lock = asyncio.Lock()
        self._llm_available: Optional[bool] = None

    # ── WS client lazy access ─────────────────────────

    async def _get_ws_client(self):
        """Lazy-init DeepTutor WS client, thread-safe."""
        if self._ws_client is None:
            async with self._ws_client_lock:
                if self._ws_client is None:
                    from .deeptutor_ws import DeepTutorWSClient
                    self._ws_client = DeepTutorWSClient()
        return self._ws_client

    async def _is_llm_available(self) -> bool:
        """Check if DeepTutor container is reachable."""
        if self._llm_available is not None:
            return self._llm_available
        try:
            client = await self._get_ws_client()
            if not client.is_connected:
                await client.wait_until_ready(max_retries=3, interval=1.0)
            self._llm_available = client.is_connected
        except Exception:
            self._llm_available = False
        return self._llm_available

    # ── Stub fallback (CI-safe) ──────────────────────

    def _stub_quiz(self, params: dict) -> dict:
        questions = []
        count = min(params.get("count", 3), 10)
        for i in range(count):
            questions.append({
                "id": f"q{i+1}",
                "question": f"[stub] Question {i+1} for {params.get('topic', 'general')}",
                "type": params.get("question_type", "short_answer"),
                "grade_level": params.get("grade_level", 1),
            })
        return {
            "agent": self.AGENT_NAME,
            "capability": "quiz_gen",
            "status": "ok_stub",
            "questions": questions,
            "topic": params.get("topic", ""),
            "grade_level": params.get("grade_level", 1),
            "rubric_id": "",
        }

    def _stub_rubric(self, params: dict) -> dict:
        criteria = params.get("criteria", ["accuracy", "completeness", "clarity"])
        levels = {
            "0": {"label": "not_yet", "desc": "Needs significant improvement"},
            "1": {"label": "developing", "desc": "Shows partial understanding"},
            "2": {"label": "achieved", "desc": "Meets expectations"},
            "3": {"label": "exemplary", "desc": "Exceeds expectations with insight"},
        }
        return {
            "agent": self.AGENT_NAME,
            "capability": "rubric_gen",
            "status": "ok_stub",
            "rubric_id": "rubric_stub_000",
            "criteria": criteria,
            "levels": levels,
            "grade_level": params.get("grade_level", 1),
        }

    def _stub_marking(self, params: dict) -> AssessmentResult:
        return AssessmentResult(
            internal_label="developing",
            confidence=0.6,
            evidence_text="[stub] Student shows partial understanding.",
            rubric_id=params.get("rubric_id", ""),
            raw_response="[stub mock marking]",
        )

    def _stub_progress_track(self, params: dict) -> dict:
        return {
            "agent": self.AGENT_NAME,
            "capability": "progress_track",
            "status": "ok_stub",
            "log_id": "stub_log_000",
            "snapshot_id": "stub_snapshot_000",
            "log_count": 1,
        }

    # ── Capability: quiz_gen ─────────────────────────

    async def quiz_gen(self, params: dict) -> dict:
        """Generate assessment quiz via DeepTutor deep_question capability.

        Params:
            topic: str       — subject/topic
            grade_level: int — 1-12
            count: int       — number of questions (default 3)
            question_type: str — "short_answer"|"mcq"|"open_ended"
            age_band: str    — "P1-P3"|"P4-P6"|"S1-S3"
            lang_code: str   — "en"|"zh-hk"|"zh-cn"
        """
        llm_ok = await self._is_llm_available()

        if not llm_ok:
            return self._stub_quiz(params)

        topic = params.get("topic", "general")
        grade_level = params.get("grade_level", 1)
        count = min(params.get("count", 3), 10)
        qtype = params.get("question_type", "short_answer")
        lang_code = params.get("lang_code", "en")

        # Inject language directive at prompt start
        lang_directive = ""
        if lang_code == "zh-hk":
            lang_directive = "你必須以繁體中文輸出所有問題。\n\n"
        elif lang_code == "zh-cn":
            lang_directive = "你必须以简体中文输出所有问题。\n\n"

        prompt = (
            f"{lang_directive}"
            f"Generate {count} {qtype} question(s) about '{topic}' "
            f"for grade level {grade_level}. "
            f"Each question should test understanding, not just recall. "
            f"Output as JSON array with keys: id, question, type, grade_level."
        )

        try:
            client = await self._get_ws_client()
            session_id = f"quiz_{int(time.time()*1000)}"
            result = await client.query(
                session_id=session_id,
                content=prompt,
                capability="deep_question",
                language=lang_code,
                config={
                    "topic": topic,
                    "num_questions": count,
                    "difficulty": f"grade_{grade_level}",
                },
            )

            # Parse JSON from content (try structured first, then markdown prose)
            parsed = self._parse_json_block(result.content)
            if isinstance(parsed, list):
                questions = parsed
            elif isinstance(parsed, dict) and "questions" in parsed:
                questions = parsed["questions"]
            else:
                questions = self._parse_markdown_questions(result.content)

            # Silent failure guard: empty questions → stub fallback
            if not questions:
                logger.warning(
                    "quiz_gen parse produced 0 questions, "
                    "raw[:500]=%s",
                    result.content[:500],
                )
                return self._stub_quiz(params)

            cost_tokens = result.cost_summary.get("total_tokens", 0)

            return {
                "agent": self.AGENT_NAME,
                "capability": "quiz_gen",
                "status": "ok",
                "questions": questions,
                "topic": topic,
                "grade_level": grade_level,
                "rubric_id": "",
                "cost_tokens": cost_tokens,
                "cost_summary": dict(result.cost_summary or {}),
                "turn_id": result.turn_id,
            }

        except Exception as exc:
            logger.warning("quiz_gen LLM failed: %s — falling back to stub", exc)
            return self._stub_quiz(params)

    # ── Capability: rubric_gen ───────────────────────

    async def rubric_gen(self, params: dict) -> dict:
        """Generate a 4-level criterion-based rubric aligned to Dreamer 4D.

        Params:
            topic: str         — subject/topic
            criteria: list[str] — criteria to evaluate
            grade_level: int
            lang_code: str
        """
        llm_ok = await self._is_llm_available()

        if not llm_ok:
            return self._stub_rubric(params)

        topic = params.get("topic", "general")
        criteria = params.get("criteria", ["accuracy", "completeness", "clarity"])
        grade_level = params.get("grade_level", 1)
        lang_code = params.get("lang_code", "en")
        rubric_id = f"rubric_{int(time.time()*1000)}"

        # Inject language directive at prompt start
        lang_directive = ""
        if lang_code == "zh-hk":
            lang_directive = "你必須以繁體中文輸出所有評分標準描述。\n\n"
        elif lang_code == "zh-cn":
            lang_directive = "你必须以简体中文输出所有评分标准描述。\n\n"

        prompt = (
            f"{lang_directive}"
            f"Generate a 4-level rubric for assessing student work on '{topic}' "
            f"at grade level {grade_level}. "
            f"Evaluate these criteria: {', '.join(criteria)}. "
            f"Levels: 0=Not Yet, 1=Developing, 2=Achieved, 3=Exemplary. "
            f"Output as JSON with keys: rubric_id='{rubric_id}', criteria (list of "
            f"{{name, levels: [{{level:0-3, label, description}}]}})."
        )

        try:
            client = await self._get_ws_client()
            session_id = f"rubric_{int(time.time()*1000)}"
            result = await client.query(
                session_id=session_id,
                content=prompt,
                capability="chat",
                language=lang_code,
                config=None,
            )

            parsed = self._parse_json_block(result.content)
            rubric_data = parsed if isinstance(parsed, dict) else {}

            # Ensure rubric_id is present
            if "rubric_id" not in rubric_data:
                rubric_data["rubric_id"] = rubric_id

            cost_tokens = result.cost_summary.get("total_tokens", 0)

            return {
                "agent": self.AGENT_NAME,
                "capability": "rubric_gen",
                "status": "ok",
                "rubric_id": rubric_data.get("rubric_id", rubric_id),
                "criteria": rubric_data.get("criteria", criteria),
                "grade_level": grade_level,
                "cost_tokens": cost_tokens,
                "cost_summary": dict(result.cost_summary or {}),
            }

        except Exception as exc:
            logger.warning("rubric_gen LLM failed: %s — falling back to stub", exc)
            return self._stub_rubric(params)

    # ── Capability: auto_marking (core) ──────────────

    async def auto_marking(self, params: dict) -> AssessmentResult:
        """Mark a student answer against a rubric.

        Params:
            student_answer: str  — student's response text
            question: str        — the question text
            rubric_id: str       — rubric to evaluate against
            rubric: dict|None    — rubric details (for stub fallback reference)
            topic: str
            grade_level: int
            lang_code: str

        Returns:
            AssessmentResult with internal_label, confidence, evidence_text, rubric_id.
        """
        llm_ok = await self._is_llm_available()

        if not llm_ok:
            return self._stub_marking(params)

        student_answer = params.get("student_answer", "")
        question = params.get("question", "")
        rubric_id = params.get("rubric_id", "")
        topic = params.get("topic", "general")
        grade_level = params.get("grade_level", 1)
        lang_code = params.get("lang_code", "en")

        # Inject language directive at prompt start
        lang_directive = ""
        if lang_code == "zh-hk":
            lang_directive = "你必須以繁體中文回覆。evidence_text 欄位必須使用繁體中文。\n\n"
        elif lang_code == "zh-cn":
            lang_directive = "你必须以简体中文回复。evidence_text 字段必须使用简体中文。\n\n"

        prompt = (
            f"{lang_directive}"
            f"You are an assessment agent for Dreamer AI. "
            f"Evaluate this student answer against the Dreamer 4D rubric. "
            f"Output ONLY a JSON object with these keys:\n"
            f'  "internal_label": one of "not_yet","developing","achieved","exemplary"\n'
            f'  "confidence": float 0.0-1.0 (how sure you are)\n'
            f'  "evidence_text": string (quote or paraphrase from the student answer '
            f'that supports your label)\n'
            f'  "rubric_id": "{rubric_id}"\n\n'
            f"Topic: {topic}\n"
            f"Grade Level: {grade_level}\n\n"
            f"Question: {question}\n\n"
            f"Student Answer: {student_answer}"
        )

        try:
            client = await self._get_ws_client()
            session_id = f"mark_{int(time.time()*1000)}"
            result = await client.query(
                session_id=session_id,
                content=prompt,
                capability="chat",
                language=lang_code,
                config=None,
            )

            parsed = self._parse_json_block(result.content)

            if isinstance(parsed, dict):
                label = parsed.get("internal_label", "")
                if label not in INTERNAL_LABELS:
                    label = self._best_guess_label(label)
                return AssessmentResult(
                    internal_label=label or "developing",
                    confidence=float(parsed.get("confidence", 0.5)),
                    evidence_text=str(parsed.get("evidence_text", "")),
                    rubric_id=str(parsed.get("rubric_id", rubric_id)),
                    raw_response=result.content,
                    cost_summary=dict(result.cost_summary or {}),
                )

            # Could not parse — fallback
            logger.warning("auto_marking parse failed: %s", result.content[:200])
            return AssessmentResult(
                internal_label="developing",
                confidence=0.3,
                evidence_text="",
                rubric_id=rubric_id,
                raw_response=result.content,
                cost_summary=dict(result.cost_summary or {}),
            )

        except Exception as exc:
            logger.warning("auto_marking LLM failed: %s — falling back to stub", exc)
            return self._stub_marking(params)

    # ── Capability: progress_track ───────────────────

    async def progress_track(self, params: dict) -> dict:
        """Write assessment_logs + upsert progress_snapshots.

        Pure DB operation — no LLM dependency. Always writes real DB.
        Params:
            student_id: str
            session_id: str
            topic_id: str
            mode: str            — DIRECT|CONTEXTUAL|HYBRID
            lang_code: str
            internal_label: str
            confidence: float
            rubric_id: str
            evidence_text: str
            agent_used: str      — "assessment"
            cost_tokens: int
            age_band: str
            skip_snapshot: bool   — if True (low confidence), skip upsert
        """
        student_id = params.get("student_id", "")
        session_id = params.get("session_id", "")
        topic_id = params.get("topic_id", "")
        mode = params.get("mode", "DIRECT")
        lang_code = params.get("lang_code", "en")
        internal_label = params.get("internal_label", "")
        confidence_val = float(params.get("confidence", 0.0))
        rubric_id = params.get("rubric_id", "")
        evidence_text = params.get("evidence_text", "")
        agent_used = params.get("agent_used", "assessment")
        cost_tokens = params.get("cost_tokens", 0)
        age_band = params.get("age_band", "P4-P6")
        skip_snapshot = params.get("skip_snapshot", False)

        if confidence_val < DEFAULT_CONFIDENCE_THRESHOLD:
            skip_snapshot = True

        log_id = ""
        snapshot_id = ""

        try:
            # Write to assessment_logs (synchronous — fire DB then return)
            self._ensure_db()
            conn = sqlite3.connect(DB_PATH)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

                cursor = conn.execute(
                    """INSERT INTO assessment_logs
                       (student_id, session_id, topic_id, mode, lang_code,
                        internal_label, confidence, rubric_id, evidence_text,
                        agent_used, cost_tokens, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        student_id, session_id, topic_id, mode, lang_code,
                        internal_label, confidence_val, rubric_id, evidence_text,
                        agent_used, cost_tokens, now_iso,
                    ),
                )
                log_id = f"log_{cursor.lastrowid}"

                # Upsert progress_snapshots
                if not skip_snapshot:
                    mastery_pct = get_mastery_pct(internal_label)

                    # Read current snapshot to compute streak
                    row = conn.execute(
                        """SELECT last_label, streak FROM progress_snapshots
                           WHERE student_id=? AND topic_id=?""",
                        (student_id, topic_id),
                    ).fetchone()

                    if row:
                        prev_label, prev_streak = row[0], int(row[1] or 0)
                        if is_streak_improvement(prev_label, internal_label):
                            new_streak = prev_streak + 1
                        elif prev_label == internal_label:
                            new_streak = prev_streak
                        else:
                            new_streak = 0
                    else:
                        new_streak = 1

                    # D8 (Phase 6): mastery_pct uses rolling average
                    #   new = (prev_mastery * prev_attempts + new_mastery) / (prev_attempts + 1)
                    conn.execute(
                        """INSERT INTO progress_snapshots
                           (student_id, topic_id, mastery_pct, attempt_count,
                            last_label, streak, updated_at)
                           VALUES (?,?,?,1,?,?,?)
                           ON CONFLICT(student_id, topic_id) DO UPDATE SET
                           mastery_pct=(progress_snapshots.mastery_pct *
                                        progress_snapshots.attempt_count +
                                        excluded.mastery_pct) /
                                       (progress_snapshots.attempt_count + 1),
                           attempt_count=progress_snapshots.attempt_count + 1,
                           last_label=excluded.last_label,
                           streak=excluded.streak,
                           updated_at=excluded.updated_at""",
                        (student_id, topic_id, mastery_pct, internal_label,
                         new_streak, now_iso),
                    )
                    snapshot_id = f"snapshot_{student_id}_{topic_id}"

                conn.commit()
            finally:
                conn.close()

            # Kid-facing label
            kid_label = soften_label(internal_label, age_band, lang_code)

            self._log_count += 1

            return {
                "agent": self.AGENT_NAME,
                "capability": "progress_track",
                "status": "ok",
                "log_id": log_id,
                "snapshot_id": snapshot_id,
                "log_count": self._log_count,
                "kid_facing_label": kid_label,
                "mastery_pct": get_mastery_pct(internal_label),
                "skip_snapshot": skip_snapshot,
                "cost_summary": {},
            }

        except Exception as exc:
            logger.warning("progress_track DB write failed: %s", exc)
            return {
                "agent": self.AGENT_NAME,
                "capability": "progress_track",
                "status": "db_error",
                "error": str(exc),
                "skip_snapshot": skip_snapshot,
            }

    # ── execute() entry point (compatible with Hermes) ─

    def execute(self, task_id: str, params: dict) -> dict:
        """Synchronous stub execute for HermesScheduler.route().

        Full async capabilities accessed via async methods above.
        This is the stub contract kept for backward compat with Phase 2 wiring.
        """
        capability = params.get("capability", "")
        if capability == "quiz_gen":
            return self._stub_quiz(params)
        elif capability == "rubric_gen":
            return self._stub_rubric(params)
        elif capability == "auto_marking":
            r = self._stub_marking(params)
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "ok",
                "result": r.to_dict(),
                "mode": params.get("mode", "DIRECT"),
                "grade_level": params.get("grade_level", 1),
            }
        elif capability == "progress_track":
            return self._stub_progress_track(params)
        else:
            return {
                "agent": self.AGENT_NAME,
                "task_id": task_id,
                "status": "ok",
                "result": f"[AssessmentAgent] params={params}",
                "mode": params.get("mode", "DIRECT"),
                "grade_level": params.get("grade_level", 1),
            }

    # ═══════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════

    _log_count = 0
    _db_ensured = False

    @classmethod
    def _ensure_db(cls) -> None:
        """Create tables if not exist."""
        if cls._db_ensured:
            return
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS assessment_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    topic_id TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'DIRECT',
                    lang_code TEXT NOT NULL DEFAULT 'en',
                    internal_label TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    rubric_id TEXT NOT NULL DEFAULT '',
                    evidence_text TEXT NOT NULL DEFAULT '',
                    agent_used TEXT NOT NULL DEFAULT 'assessment',
                    cost_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_logs_student
                    ON assessment_logs(student_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_logs_topic
                    ON assessment_logs(topic_id, created_at);

                CREATE TABLE IF NOT EXISTS progress_snapshots (
                    student_id TEXT NOT NULL,
                    topic_id TEXT NOT NULL,
                    mastery_pct REAL NOT NULL DEFAULT 0.0,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    last_label TEXT NOT NULL DEFAULT '',
                    streak INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (student_id, topic_id)
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_student
                    ON progress_snapshots(student_id);
            """)
            conn.commit()
        finally:
            conn.close()
        cls._db_ensured = True

    @staticmethod
    def _parse_json_block(text: str) -> Any:
        """Extract JSON object or array from LLM output."""
        if not text:
            return None
        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fences
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try finding { ... }  or [ ... ]
        for pattern in [r'\{.*\}', r'\[.*\]']:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue

        return None

    @staticmethod
    def _parse_markdown_questions(text: str) -> list[dict]:
        """Extract questions from markdown prose (deep_question native format).

        Handles formats like:
          ### Question 1
          Emma has 15 stickers... How many does Emma have left?
          - A. 22
          - B. 9
          **Answer:** C
          **Explanation:** ...

        Also handles plain numbered lists (1. ... 2. ...).
        Returns list of {id, question, answer, explanation, type, grade_level}.
        """
        import re

        questions = []

        # Pattern: split on ### Question N / ## Question N / **Question N:**
        # deep_question returns prose with inline headings (no guaranteed newline before ###)
        q_split = re.compile(
            r'(?:#{2,3}\s*)?\*{0,2}Question\s+(\d+)\*{0,2}[:.\s-]*',
            re.IGNORECASE,
        )
        parts = q_split.split(text)
        # parts[0] = preamble, parts[1] = num1, parts[2] = body1, parts[3] = num2, ...
        for i in range(1, len(parts) - 1, 2):
            num = parts[i]
            body = parts[i + 1].strip()
            question_text = body

            # Extract answer
            answer = ""
            ans_m = re.search(r'\*\*Answer:?\*\*\s*(.+?)(?:\n|$)', body)
            if ans_m:
                answer = ans_m.group(1).strip()
                question_text = body[:ans_m.start()].strip()

            # Extract explanation
            explanation = ""
            exp_m = re.search(r'\*\*Explanation:?\*\*\s*(.+?)(?:\n|$)', body)
            if exp_m:
                explanation = exp_m.group(1).strip()

            # Clean up question text: remove MC options lines (- A., - B., etc.)
            question_text = re.sub(r'\n\s*- [A-D][.)]\s*.+', '', question_text)
            question_text = question_text.strip()

            questions.append({
                "id": f"q{num}",
                "question": question_text,
                "answer": answer,
                "explanation": explanation,
                "type": "short_answer",
                "grade_level": 3,
            })

        if questions:
            return questions

        # Fallback: plain numbered list (1. ... 2. ...)
        lines = text.strip().split('\n')
        numbered = re.compile(r'^\s*(\d+)[\.\)]\s+(.+)')
        current_q = None
        for line in lines:
            m = numbered.match(line)
            if m:
                if current_q:
                    questions.append(current_q)
                current_q = {
                    "id": f"q{m.group(1)}",
                    "question": m.group(2).strip(),
                    "answer": "",
                    "explanation": "",
                    "type": "short_answer",
                    "grade_level": 3,
                }
            elif current_q and line.strip():
                current_q["question"] += " " + line.strip()

        if current_q:
            questions.append(current_q)

        return questions

    @staticmethod
    def _best_guess_label(raw: str) -> str:
        """Map a fuzzy label string to one of the four internal labels."""
        raw_lower = raw.lower().strip()
        mapping = {
            "not yet": "not_yet", "not_yet": "not_yet", "0": "not_yet",
            "developing": "developing", "1": "developing",
            "achieved": "achieved", "2": "achieved",
            "exemplary": "exemplary", "3": "exemplary",
        }
        # Partial match
        for key, val in mapping.items():
            if key in raw_lower:
                return val
        return "developing"
