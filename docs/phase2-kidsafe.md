# Phase 2 — Kid-Safe Output Layer

> **Date:** 2026-08-08
> **Branch:** feature/phase2-kidsafe
> **Coverage:** Phase 2.3
> **Test count:** 197 tests, zero LLM cost

## Architecture Decision: Rule-Based, Not LLM

The kid-safe layer runs on **every student response**. Using an LLM for this path would add ~$0.001 latency and cost per query. A rule-based approach:

- **Zero incremental token cost** — the entire pipeline runs in Python with JSON config
- **Sub-millisecond latency** — pure string/regex operations, no network calls
- **Tune JSON, no code changes** — all tone rules live in `config/kid_safe_tone_rules.json`

## Pipeline Architecture

```
            Student Query
                 │
                 ▼
          ┌──────────────┐
          │ ethical_ai_kb│ ← inject_kb_query() — enriches context
          └──────┬───────┘
                 │
                 ▼
        ┌────────────────┐
        │ KidSafePipeline │
        │  (__init__.py)  │
        └───────┬────────┘
                │
        ┌───────┴───────┐
        ▼               ▼
   error path?      normal path?
        │               │
        ▼               ▼
  error_templates   tone_rewrite
  (bypass all)      │
                    ▼
                 session_wrap
                    │
                    ▼
                label_soften
                    │
                    ▼
              Student Output
```

## Component Summary

| Component | File | Tests | Role |
|-----------|------|-------|------|
| `tone_rewrite` | `agents/kid_safe/tone_rewrite.py` | 35 | 5-step pipeline: strip sarcasm → strip anxiety → keyword replace → word trim → encouragement inject |
| `label_soften` | `agents/kid_safe/label_soften.py` | 68 | Maps internal `not_yet`/`developing`/`achieved`/`exemplary` → age-appropriate kid-facing labels |
| `session_wrap` | `agents/kid_safe/session_wrap.py` | 19 | Session boundary markers, opening/closing templates, streak messages |
| `error_templates` | `agents/kid_safe/error_templates.py` | 20 | Kid-friendly error messages for DeepTutorError / timeout / connection lost |
| `ethical_ai_kb` | `agents/kid_safe/ethical_ai_kb.py` | 12 | Knowledge base queries for age-appropriate content boundaries |
| `KidSafePipeline` | `agents/kid_safe/__init__.py` | 22 | Orchestrator: routes error vs normal, chains middleware |
| Hermes wiring | `agents/hermes_scheduler.py` | 21 | Static methods: `inject_kb_query()`, `kid_safe_wrap()`, `kid_safe_error()` |

## Tone Rewrite Pipeline (5 Steps)

### Step 1: Sarcasm Strip (S1)
Scans for sarcasm patterns from `kid_safe_tone_rules.json → sarcasm_patterns` and removes the clause. **Strip only, no rewrite.**

### Step 2: Anxiety Strip (S2)
Scans for grade-anxiety patterns (e.g. "you'll fail the exam") from `grade_anxiety_patterns`. **Strip only, no rewrite.**

### Step 3: Keyword Replace (S3)
Applies keyword replacements from `keyword_replacements` map. e.g. `"wrong" → "not quite right"`, `"fail" → "not yet"`. **Strip-anxiety-only (S1-S3), no structural rewrite.**

### Step 4: Word Trim (S4)
If the response exceeds `max_words` for the student's age band, trims to fit. Age bands from `kid_safe_tone_rules.json → age_bands`.

### Step 5: Encouragement Inject (S5)
Inserts an encouragement phrase from `encouragement_pool` every N turns (configured by `encouragement_interval`). S1-S3 students get no injections (`interval: 0, pool: []`).

## Label Softening

Maps internal assessment labels to kid-facing labels, age-band-specific:

| Internal | P1-P3 | P4-P6 | S1-S3 |
|----------|-------|-------|-------|
| `not_yet` | Getting Started | Keep Going! | Not Yet |
| `developing` | Making Progress | Almost There! | Developing |
| `achieved` | You've Got It! | Well Done! | Achieved |
| `exemplary` | Amazing Work! | Excellent! | Exemplary |

Parent-facing labels are a separate set, always using neutral educational terminology.

## Configuration

All tone rules externalized to `config/kid_safe_tone_rules.json`:

```json
{
  "age_bands": { "P1-P3": {...}, "P4-P6": {...}, "S1-S3": {...} },
  "keyword_replacements": { "en": {...}, "zh-hk": {...}, "zh-cn": {...} },
  "sarcasm_patterns": { ... },
  "grade_anxiety_patterns": { ... }
}
```

Tune any rule by editing JSON. No Python code changes required.

## Wiring: Hermes Scheduler

Three static methods added to `hermes_scheduler.py`:

- `inject_kb_query(query, age_band, language)` — queries ethical_ai_kb for content guardrails
- `kid_safe_wrap(response, age_band, language, turn_count)` — full pipeline for normal output
- `kid_safe_error(error, age_band, language)` — renders kid-friendly error from error_templates

## Test Suite

```bash
pytest tests/test_tone_rewrite.py tests/test_label_soften.py \
       tests/test_session_wrap.py tests/test_error_templates.py \
       tests/test_ethical_ai_kb.py tests/test_kid_safe_pipeline.py \
       tests/test_kid_safe_wiring.py -v
```

197 tests, 0.19s runtime, zero token cost. All rule-based deterministic assertions.

## Related Files

- `agents/kid_safe/` — all 7 pipeline components
- `agents/hermes_scheduler.py` — wiring static methods
- `config/kid_safe_tone_rules.json` — tone rules (tune JSON, no code change)
- `config/dreamer_progress_levels.json` — label mappings for label_soften
- `docs/phase2-registry.md` — agent ownership + registry design
