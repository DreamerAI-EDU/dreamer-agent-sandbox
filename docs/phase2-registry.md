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
       ├── Agent A (e.g. TutorAgent)
       ├── Agent B (e.g. SafetyAgent)
       ├── Agent C (e.g. SearchAgent)
       └── Agent D (e.g. KnowledgeAgent)
```

## Registry Design (`agents/registry.py`)

### Core Data Structures

| Structure | Purpose |
|-----------|---------|
| `AgentEntry` | Agent metadata: name, class_path, capabilities, fallback priority |
| `SubagentRegistry` | Singleton registry with lazy-load and capability-based routing |

### Key Design Decisions

1. **Lazy-load by default** — agents are imported on first dispatch, not at startup. Keeps cold-start latency low.
2. **Capability-based routing** — Hermes sends a `capability` field (e.g. `"tutoring"`, `"safety"`, `"search"`) and the registry picks the best-fit agent.
3. **Fallback chain** — if the primary agent returns `NOT_MY_JOB`, the registry tries the next candidate in priority order.
4. **Zero LLM overhead** — routing is pure Python `dict`/`set` lookup. No LLM calls in the registry path.

### Agent Stubs (Phase 2.1)

| Agent | File | Capabilities |
|-------|------|-------------|
| `TutorAgent` | `agents/tutor_agent.py` | `tutoring`, `homework_help`, `explain`, `quiz` |
| `SafetyAgent` | `agents/safety_agent.py` | `safety`, `content_filter`, `kid_safe` |
| `SearchAgent` | `agents/search_agent.py` | `search`, `research`, `web_lookup` |
| `KnowledgeAgent` | `agents/knowledge_agent.py` | `knowledge_graph`, `curriculum`, `prerequisite` |
| `FallbackAgent` | `agents/fallback_agent.py` | `catch_all` (lowest priority, always available) |

## Agent Ownership Matrix

### Dispatch Logic (Hermes → Registry → Agent)

```
User Message → intent_classifier (mode_keywords from cantonese_keyword_config.json)
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
      DIRECT         CONTEXTUAL      EXPLORATORY
         │              │              │
         ▼              ▼              ▼
    TutorAgent     TutorAgent      KnowledgeAgent
    (priority 1)   (priority 1)    (priority 1)
         │              │              │
         ▼              ▼              ▼
    SafetyAgent    SearchAgent     SearchAgent
    (priority 2)   (priority 2)    (priority 2)
```

### Ownership by Intent

| Intent | Primary Agent | Secondary | Rationale |
|--------|--------------|-----------|-----------|
| Homework help / exam prep | TutorAgent | SafetyAgent | Safety wraps output; tutor handles content |
| Creative / project | TutorAgent | SearchAgent | Search enriches context; tutor guides |
| "How does AI work?" / explore | KnowledgeAgent | SearchAgent | Knowledge graph first; web as supplement |
| Toxic / unsafe input | SafetyAgent | FallbackAgent | Safety handles gracefully; fallback if confounded |

### Kid-Safe Wrap (Phase 2.3)

All agent output passes through `KidSafePipeline` **before** reaching the student:

```
Agent response → KidSafePipeline
                   ├── error path? → error_templates (bypass all middleware)
                   └── normal path? → tone_rewrite → session_wrap → label_soften → output
```

The pipeline is implemented in `agents/kid_safe/` and wired into `hermes_scheduler.py` via three static methods:
- `inject_kb_query()` — enriches context with ethical_ai_kb lookup
- `kid_safe_wrap()` — applies full pipeline to normal responses
- `kid_safe_error()` — renders kid-friendly error messages

## Related Files

- `agents/registry.py` — SubagentRegistry implementation
- `agents/hermes_scheduler.py` — wiring + kid-safe static methods
- `config/cantonese_keyword_config.json` — intent keyword definitions
- `docs/phase2-kidsafe.md` — kid-safe pipeline details
