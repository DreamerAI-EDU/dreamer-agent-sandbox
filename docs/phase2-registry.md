# Phase 2 — Subagent Registry & Ownership Matrix

> **Date:** 2026-08-08
> **Branch:** feature/phase2-registry-ws-kidsafe
> **Coverage:** Phase 2.1

## Architecture

```
Hermes Scheduler
       │
       ▼
SubagentRegistry (agents/registry.py)
       │
       ├── curriculum (student-facing, CONTEXTUAL + HYBRID)
       ├── assessment (student-facing, DIRECT + HYBRID)
       ├── portfolio   (student-facing, CONTEXTUAL)
       ├── parent_report (non-student-facing, mode_allowlist=None)
       └── marketing     (non-student-facing, mode_allowlist=None)
```

## Registry Design (`agents/registry.py`)

### Core API

| Method | Purpose |
|--------|---------|
| `register(name, agent_class, kb_ownership, capabilities, mode_allowlist)` | Register an agent stub with metadata |
| `get(name)` | Lazy-instantiate and return agent instance |
| `list_all()` | All registered agent names |
| `list_by_kb(kb_name)` | Agents that own/control a specific KB |
| `list_by_mode(mode)` | Student-facing agents for a given query mode |

### Key Design Decisions

1. **Lazy-load** — agent instances created on first `get()`, not at register time. Keeps cold-start latency low.
2. **Thread-safe** — `threading.RLock` guards all registry mutations and reads.
3. **`mode_allowlist=None`** — semantic marker for non-student-facing agents. `list_by_mode()` skips them. This avoids mixing ParentReport/Marketing into student-query dispatch.
4. **Phase 2.1 scope** — agent stubs only. Full LLM integration deferred to Phase 4 (Mode Routing).
5. **No intent classification in Phase 2.1** — that lives in Phase 4 and uses `config/cantonese_keyword_config.json`.

## Agent Inventory (`agents/subagents.py`)

### Student-Facing Agents

| Agent | Stub Class | Modes | KB Ownership | Capabilities |
|-------|-----------|-------|-------------|-------------|
| `curriculum` | `CurriculumAgentStub` | CONTEXTUAL, HYBRID | dreamer-maths, dreamer-english, dreamer-computing, dreamer-science, dreamer-psd, dreamer-life_skills, dreamer-l2l, dreamer-history, dreamer-prerequisites | lesson_plan, curriculum_nav, topic_design, prerequisite_check |
| `assessment` | `AssessmentAgentStub` | DIRECT, HYBRID | dreamer-rubrics | quiz_gen, rubric_gen, auto_marking, progress_track |
| `portfolio` | `PortfolioAgentStub` | CONTEXTUAL | dreamer-portfolio | portfolio_mgmt, reflection_prompt, artifact_curate |

### Non-Student-Facing Agents

| Agent | Stub Class | mode_allowlist | Purpose |
|-------|-----------|---------------|---------|
| `parent_report` | `ParentReportAgentStub` | None | Generates parent-facing progress reports. Queries Dreamer DB only (not DeepTutor). |
| `marketing` | `MarketingAgentStub` | None | Generates social media / marketing content. |

## KB Ownership Matrix

| Knowledge Base | Owner Agent | Reader Agents |
|---------------|------------|---------------|
| `dreamer-maths` | curriculum | assessment |
| `dreamer-english` | curriculum | assessment |
| `dreamer-computing` | curriculum | assessment, marketing |
| `dreamer-science` | curriculum | assessment, marketing |
| `dreamer-psd` | curriculum | portfolio |
| `dreamer-life_skills` | curriculum | portfolio |
| `dreamer-l2l` | curriculum | assessment |
| `dreamer-history` | curriculum | — |
| `dreamer-prerequisites` | curriculum | — |
| `dreamer-rubrics` | assessment | — |
| `dreamer-portfolio` | portfolio | parent_report |

## Query Modes

| Mode | Description | Served By |
|------|------------|-----------|
| `DIRECT` | Exam prep, quiz, direct instruction | assessment |
| `CONTEXTUAL` | Project-based, exploration, discovery | curriculum, portfolio |
| `HYBRID` | Mix of direct instruction and exploration | curriculum, assessment |

Non-student-facing agents (ParentReport, Marketing) have `mode_allowlist=None` and are excluded from `list_by_mode()`. They use separate invocation paths outside the student-query dispatch.

## Kid-Safe Wrap (Phase 2.3)

All agent output passes through `KidSafePipeline` before reaching the student:

```
Agent response → tone_rewrite → session_wrap → student output
```

Error path bypasses all middleware and uses `error_templates` directly. Implemented in `agents/kid_safe/`, wired into `hermes_scheduler.py` via `kid_safe_wrap()` and `kid_safe_error()` static methods.

## Related Files

- `agents/registry.py` — SubagentRegistry implementation (125 lines)
- `agents/subagents.py` — 5 agent stubs + `register_all()` (179 lines)
- `tests/test_registry.py` — 16 unit tests
- `tests/test_subagents.py` — 15 unit tests
- `config/cantonese_keyword_config.json` — intent keywords (Phase 4 use)
- `docs/phase2-kidsafe.md` — kid-safe pipeline details
