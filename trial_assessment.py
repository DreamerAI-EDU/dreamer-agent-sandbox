"""
trial_assessment.py — Phase 3 Assessment Agent: real-container end-to-end trial.

Flow:
  1. quiz_gen   → generate 3 questions on Basic Arithmetic (grade 3)
  2. Simulate student answers
  3. auto_marking → mark each answer
  4. progress_track → write assessment_logs + progress_snapshots
  5. Verify kid-facing label via label_soften
  6. Verify DB records exist

Pre-req: DeepTutor container running, OPENROUTER_API_KEY set.
Fallback: container unreachable → stub mode (outputs ok_stub).
"""

import asyncio
import os
import sys
import json
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.assessment_agent import (
    AssessmentAgent,
    AssessmentResult,
    DB_PATH,
)

# ── Simulated student answers ──────────────────────────

STUDENT_ANSWERS = [
    {
        "question": "What is 25 + 17?",
        "answer": "42",
    },
    {
        "question": "If you have 3 groups of 8 apples, how many in total?",
        "answer": "24",
    },
    {
        "question": "What is 100 minus 67?",
        "answer": "33",
    },
]


async def trial():
    agent = AssessmentAgent()

    student_id = f"trial_stu_{int(time.time())}"
    session_id = f"trial_sess_{int(time.time())}"
    topic_id = "maths_basic_arithmetic"
    rubric_id = ""

    print("=" * 60)
    print("Phase 3 Trial — Assessment Agent")
    print(f"Student: {student_id}")
    print(f"Session: {session_id}")
    print("=" * 60)

    # ── Step 1: quiz_gen ─────────────────────────────
    print("\n[1/5] quiz_gen — generate quiz ...")
    quiz = await agent.quiz_gen({
        "topic": "Basic Arithmetic",
        "grade_level": 3,
        "count": 3,
        "question_type": "short_answer",
        "lang_code": "en",
        "age_band": "P1-P3",
    })
    print(f"  Status: {quiz['status']}")
    questions = quiz.get("questions", [])
    if isinstance(questions, list):
        print(f"  Questions generated: {len(questions)}")
        for q in questions[:3]:
            print(f"    - {q.get('question', q.get('id', '?'))}")

    # ── Step 2: rubric_gen ──────────────────────────
    print("\n[2/5] rubric_gen — generate rubric ...")
    rubric = await agent.rubric_gen({
        "topic": "Basic Arithmetic",
        "grade_level": 3,
        "criteria": ["accuracy", "working_steps", "clarity"],
        "lang_code": "en",
    })
    rubric_id = rubric.get("rubric_id", "rubric_stub_000")
    print(f"  Status: {rubric['status']}")
    print(f"  Rubric ID: {rubric_id}")

    # ── Step 3: auto_marking × 3 ────────────────────
    print("\n[3/5] auto_marking — mark 3 answers ...")
    marks = []
    for i, entry in enumerate(STUDENT_ANSWERS):
        result = await agent.auto_marking({
            "student_answer": entry["answer"],
            "question": entry["question"],
            "rubric_id": rubric_id,
            "topic": "Basic Arithmetic",
            "grade_level": 3,
            "lang_code": "en",
        })
        marks.append(result)
        kid_label = _kid_facing(result.internal_label, "P1-P3", "en")
        print(f"  Answer {i+1}: label={result.internal_label} "
              f"(conf={result.confidence:.2f}) → kid: {kid_label}")
        if result.evidence_text:
            print(f"    evidence: {result.evidence_text[:80]}")

    # ── Step 4: progress_track × 3 ──────────────────
    print("\n[4/5] progress_track — write DB ...")
    total_cost = 0
    for i, mark in enumerate(marks):
        track = await agent.progress_track({
            "student_id": student_id,
            "session_id": session_id,
            "topic_id": topic_id,
            "mode": "DIRECT",
            "lang_code": "en",
            "internal_label": mark.internal_label,
            "confidence": mark.confidence,
            "rubric_id": mark.rubric_id,
            "evidence_text": mark.evidence_text,
            "agent_used": "assessment",
            "cost_tokens": quiz.get("cost_tokens", 0) + rubric.get("cost_tokens", 0),
            "age_band": "P1-P3",
            "skip_snapshot": not mark.is_confident(),
        })
        total_cost += quiz.get("cost_tokens", 0)
        status = track.get("status", "?")
        snapshot_id = track.get("snapshot_id", "N/A")
        skip = track.get("skip_snapshot", False)
        print(f"  Mark {i+1}: status={status}, snapshot={snapshot_id}, skip={skip}")
        if "kid_facing_label" in track:
            print(f"    kid-facing: {track['kid_facing_label']}")

    # ── Step 5: verify DB ──────────────────────────
    print("\n[5/5] verify DB records ...")
    try:
        db = sqlite3.connect(DB_PATH)
        rows = db.execute(
            "SELECT COUNT(*) FROM assessment_logs WHERE student_id=?",
            (student_id,)
        ).fetchone()
        print(f"  assessment_logs for student: {rows[0]} records")

        snap = db.execute(
            "SELECT * FROM progress_snapshots WHERE student_id=? AND topic_id=?",
            (student_id, topic_id)
        ).fetchone()
        if snap:
            print(f"  progress_snapshot: mastery={snap[2]:.2f}, "
                  f"attempts={snap[3]}, label={snap[4]}, streak={snap[5]}")
        else:
            print("  progress_snapshot: NOT FOUND (possibly low confidence skip)")

        db.close()
    except Exception as e:
        print(f"  DB verify error: {e}")

    # ── Summary ────────────────────────────────────
    print("\n" + "=" * 60)
    print("Trial complete.")
    if quiz["status"] == "ok":
        print("LLM backend: connected (real)")
    else:
        print("LLM backend: stub (container unreachable)")
    print(f"Total assessments: {len(marks)}")
    print(f"Estimated token cost: ~{total_cost}")
    print("=" * 60)


def _kid_facing(internal_label: str, age_band: str, lang_code: str) -> str:
    from agents.kid_safe.label_soften import soften_label
    return soften_label(internal_label, age_band, lang_code)


if __name__ == "__main__":
    asyncio.run(trial())
