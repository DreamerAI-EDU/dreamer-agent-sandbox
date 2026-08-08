# Phase 2 — Kid-Safe Output Layer

> **Date:** 2026-08-08
> **Branch:** feature/phase2-kidsafe
> **Coverage:** Phase 2.3 + Phase 2.5 (Input Guard)
> **Test count:** 197 + 55 (input_guard) = 252 tests, zero LLM cost

## Architecture Decision: Rule-Based, Not LLM

The kid-safe layer runs on **every student response**. Using an LLM for this path would add ~$0.001 latency and cost per query. A rule-based approach:

- **Zero incremental token cost** — the entire pipeline runs in Python with JSON config
- **Sub-millisecond latency** — pure string/regex operations, no network calls
- **Tune JSON, no code changes** — all tone rules live in `config/kid_safe_tone_rules.json`

## Phase 2.5: Input Guard — Pre-Generation Safety Filter

### Position in Pipeline

```
student input → input_guard → inject_kb_query → DeepTutor → kid_safe_wrap → output
```

Input guard runs **before** DeepTutor. If a query is blocked, it never reaches the LLM — saving tokens and preventing harmful content generation.

### Three Filter Layers + Welfare Path

| Layer | Priority | Action |
|---|---|---|
| Welfare (self-harm/crisis) | Highest | Warm supportive message + safety_events log + async webhook alert. **NOT** a generic block message. |
| Prompt Injection | Medium | Detect jailbreak/instruction-override patterns (3 langs). Block redirect with friendly message. |
| Age-Inappropriate | Low | Keyword blocklist per age band (P1-P3 strictest, S1-S3 loosest). Context whitelist prevents false positives. |

### Key Design: Async Alert, Not Real-Time Blocking

Welfare detection triggers a warm response immediately (zero delay for student) while firing a background webhook alert to `SAFETY_WEBHOOK_URL`. The human gate is an alert + review queue — the student is never left waiting for approval.

### Context Whitelist (False Positive Prevention)

Each blocked keyword has `allow_if_contains` terms. Example:
- `"kill"` with `"process"` or `"task"` → allowed (computing context)
- `"blood"` with `"biology"` or `"circulation"` → allowed (science context)
- `"gun"` with `"history"` or `"world war"` → allowed (history context)

### Normalization (Bypass Prevention)

Before matching, all input is normalized: lowercase, strip spaces, strip punctuation. This defeats bypass attempts like `"i g n o r e   p r e v i o u s"`.

### Configuration

All rules externalized to `config/input_guard_rules.json`:

```json
{
  "injection_patterns": { "en": [...], "zh-hk": [...], "zh-cn": [...] },
  "age_inappropriate": { "P1-P3": {...}, "P4-P6": {...}, "S1-S3": {...} },
  "context_whitelist": { "kill": ["process", "task"], ... },
  "block_messages": { "P1-P3": {"en": "", "zh-hk": "", "zh-cn": ""}, ... },
  "welfare": {
    "patterns": { ... },
    "messages": { ... },
    "alert": { "enabled": true, "webhook_env": "SAFETY_WEBHOOK_URL" }
  }
}
```

### Webhook Notifier

Welfare events fire a `POST` to `SAFETY_WEBHOOK_URL` (env var) with payload: `student_id`, `severity`, `matched_rule`, `age_band`, `lang_code`, `timestamp`. Fire-and-forget — webhook failure does not affect student response. `raw_input` (PDPO sensitive) is excluded from webhook payload; written only to `safety_events` DB.

### Audit Trail

Every block/welfare event writes to `safety_events` table:

| Column | Description |
|---|---|
| `id` | UUID primary key |
| `student_id` | Student identifier |
| `event_type` | welfare / injection / age_inappropriate |
| `severity` | high / medium / low |
| `raw_input` | Original query (PDPO: 90-day retention, then anonymize) |
| `matched_rule` | Which keyword/pattern triggered |
| `reviewed` | Human review flag (default FALSE) |

### Risk Register Additions

- **PDPO Retention:** `raw_input` in `safety_events` contains potentially identifiable data. Policy: anonymize after 90 days (automated cleanup job).
- **B2C Consent:** Parental consent clause for safety monitoring to be added to B2C T&C (pending legal review).
- **Helpline Numbers:** Welfare messages for S1-S3 include `[TBC]` hotline placeholders. **Must be human-verified before production deployment.**

## Pipeline Architecture

Two independent paths:

### Normal Response Path

```
DeepTutor response
       │
       ▼
  tone_rewrite (5-step: sarcasm→anxiety→keyword→trim→encouragement)
       │
       ▼
  session_wrap (session boundaries, opening/closing, streaks)
       │
       ▼
  Student Output
```

### Error Path

```
DeepTutor error / timeout / connection lost
       │
       ▼
  error_templates (bypasses all middleware)
       │
       ▼
  Student-friendly error message
```

### Separate Component: Label Softening

`label_soften` is **not part of the streaming response pipeline**. It operates on assessment progress labels independently — mapping internal levels (`not_yet`, `developing`, `achieved`, `exemplary`) to age-appropriate kid-facing labels. Invoked separately by the Assessment agent when rendering progress reports and quiz results.

## Component Summary

| Component | File | Tests | Role |
|-----------|------|-------|------|
| `input_guard` | `agents/kid_safe/input_guard.py` | 55 | Pre-generation safety filter: injection detection, welfare alert, age-inappropriate blocklist with context whitelist |
| `tone_rewrite` | `agents/kid_safe/tone_rewrite.py` | 35 | 5-step pipeline: strip sarcasm → strip anxiety → keyword replace → word trim → encouragement inject |
| `label_soften` | `agents/kid_safe/label_soften.py` | 68 | Maps internal assessment labels → age-appropriate kid-facing labels (separate from response pipeline) |
| `session_wrap` | `agents/kid_safe/session_wrap.py` | 19 | Session boundary markers, opening/closing templates, streak messages |
| `error_templates` | `agents/kid_safe/error_templates.py` | 20 | Kid-friendly error messages for DeepTutorError / timeout / connection lost |
| `ethical_ai_kb` | `agents/kid_safe/ethical_ai_kb.py` | 12 | Knowledge base queries for age-appropriate content boundaries |
| `KidSafePipeline` | `agents/kid_safe/__init__.py` | 22 | Orchestrator: routes error vs normal, chains tone_rewrite + session_wrap |
| Hermes wiring | `agents/hermes_scheduler.py` | 21 | Static methods: `kid_safe_input()`, `inject_kb_query()`, `kid_safe_wrap()`, `kid_safe_error()` |

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

## Label Softening (Independent Component)

Not part of the streaming response pipeline. Maps internal assessment labels to kid-facing labels, age-band-specific:

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
       tests/test_kid_safe_wiring.py tests/test_input_guard.py -v
```

252 tests, sub-millisecond runtime, zero token cost. All rule-based deterministic assertions.

## Related Files

- `agents/kid_safe/` — all 8 pipeline components (incl. input_guard)
- `agents/hermes_scheduler.py` — wiring static methods
- `config/kid_safe_tone_rules.json` — tone rules (tune JSON, no code change)
- `config/input_guard_rules.json` — input guard rules (tune JSON, no code change)
- `config/dreamer_progress_levels.json` — label mappings for label_soften
- `migrations/phase2.5_safety_events.sql` — safety_events DB schema
- `docs/phase2-registry.md` — agent ownership + registry design
