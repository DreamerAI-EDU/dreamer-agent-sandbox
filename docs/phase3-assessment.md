# Phase 3 — Assessment Agent (Dreamer Progress Levels)

**Merge:** Fix #6 (plan §7) + Days 17-18 (plan §13)
**Branch:** `feature/phase3-assessment`

## Deliverable Summary

| File | Purpose |
|---|---|
| `agents/assessment_agent.py` | Real AssessmentAgent: quiz_gen, rubric_gen, auto_marking, progress_track |
| `migrations/phase3_assessment.sql` | DB schema: `assessment_logs` + `progress_snapshots` |
| `tests/test_assessment_agent.py` | 21 unit tests (capabilities, label_soften wiring, stub fallback, JSON parse) |
| `tests/test_assessment_db.py` | 11 DB tests (insert, upsert, streak, low-confidence skip, multi-student) |
| `trial_assessment.py` | End-to-end trial script (real container) |
| `agents/subagents.py` | AssessmentAgentStub → AssessmentAgent (wire real agent) |
| `agents/__init__.py` | Import AssessmentAgent from assessment_agent module |
| `tests/test_subagents.py` | Updated to test AssessmentAgent (not stub) |
| `.github/workflows/ci.yml` | Phase 2 → Phase 3; added 2 new test files |

## Architecture

```
student input → kid_safe_input() → mode dispatch → AssessmentAgent
    │
    ├─ quiz_gen     ──→ DeepTutorWSClient (deep_question)    → quiz JSON
    ├─ rubric_gen   ──→ DeepTutorWSClient (deep_question)    → 4-level rubric
    ├─ auto_marking ──→ DeepTutorWSClient (chat)             → AssessmentResult
    │   │                                                       {label, confidence,
    │   │                                                        evidence, rubric_id}
    │   └─→ label_soften → kid-facing label
    │   └─→ kid_safe_wrap() (tone → wrap)
    │
    └─ progress_track → SQLite (assessment_logs INSERT + progress_snapshots UPSERT)
                          async fire-and-forget, eventual consistency
```

## Four Capabilities

### quiz_gen
- LLM: DeepTutorWSClient `deep_question` → DeepSeek chat
- Params: topic, grade_level, count (≤10), question_type, lang_code
- Output: `[{id, question, type, grade_level}]`
- Fallback: stub generates `count` placeholder questions

### rubric_gen
- LLM: DeepTutorWSClient `deep_question` → DeepSeek chat
- Output: 4 levels (0=Not Yet, 1=Developing, 2=Achieved, 3=Exemplary) × per-criterion descriptors
- rubric_id: timestamp-based unique identifier

### auto_marking (core)
- LLM: DeepTutorWSClient `chat` → DeepSeek chat
- Returns `AssessmentResult {internal_label, confidence, evidence_text, rubric_id}`
- Confidence below 0.45 → progress_snapshots not written (assessment_logs still written)
- Fallback: stub returns `developing` with 0.6 confidence

### progress_track
- Writes `assessment_logs` (one row per marking, append-only audit trail)
- Upserts `progress_snapshots` (per student × topic, mastery_pct + streak)
- Streak: increments on label improvement, resets on regression, unchanged on same label
- All writes synchronous within the async handler (fast — SQLite WAL mode)

## label_soften Wiring

```
auto_marking.internal_label → soften_label(label, age_band, lang_code)
    → kid-facing string (e.g. "achieved" → "Great job! ★★★" for P1-P3 zh-hk)
    → kid_safe_wrap() (tone_rewrite → session_wrap)
    → failure → kid_safe_error()
```

## DB Schema

- `assessment_logs`: id, student_id, session_id, topic_id, mode, lang_code, internal_label, confidence, rubric_id, evidence_text, agent_used, cost_tokens, created_at
- `progress_snapshots`: student_id + topic_id (PK), mastery_pct, attempt_count, last_label, streak, updated_at

## LLM Fallback

`AssessmentAgent._is_llm_available()` checks DeepTutor container connectivity. When unavailable:
- quiz_gen/rubric_gen/auto_marking → stub outputs with `ok_stub` status
- progress_track → stub output (no DB writes)
- This keeps CI green without a real container

## Tests

340 total (308 Phase 2 + 32 new):
- `test_assessment_agent.py` (21): capabilities, AssessmentResult, label_soften wiring, JSON parse, stub execute
- `test_assessment_db.py` (11): assessment_logs insert, snapshots upsert, streak increment/reset/unchanged, low-confidence skip, multi-student

## Watch Items

| Risk | Mitigation |
|---|---|
| LLM label instability | rubric_id + evidence_text always included; confidence threshold prevents low-quality snapshots |
| No mode routing (Phase 4) | Trial calls AssessmentAgent directly; documented |
| Token cost | ~2 LLM calls per assessment flow (quiz + marking), DeepSeek ~$0.05/day |

## Phase 2 Regression Check

All 308 Phase 2 tests pass (kid_safe, ws/session, registry/subagents, input_guard). No Phase 2 code modified except subagents.py AssessmentAgentStub → AssessmentAgent wiring.
