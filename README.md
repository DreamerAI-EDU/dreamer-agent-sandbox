# dreamer-agent-sandbox

Hermes × DeepTutor integration — multi-agent AI tutoring platform for Hong Kong students.

## Phase 2 Architecture

```
                          User Query
                               │
                               ▼
                    ┌─────────────────────┐
                    │   cantonese_kw.json │── intent classification (Direct / Contextual / Exploratory)
                    └────────┬────────────┘
                             │
                             ▼
                    ┌─────────────────────┐
                    │  Hermes Scheduler   │
                    │ hermes_scheduler.py │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────────┐
        │TutorAgent│  │SafetyAgent│  │KnowledgeAgent│  ... SubagentRegistry
        └────┬─────┘  └────┬─────┘  └──────┬───────┘
             │              │               │
             └──────────────┼───────────────┘
                            │
                            ▼
                   ┌────────────────────┐
                   │  DeepTutor (WS)    │  WebSocket protocol (config/ws_client.yaml)
                   │  deeptutor_ws.py   │
                   └────────┬───────────┘
                            │
                            ▼
                   ┌────────────────────┐
                   │  KidSafePipeline   │  Zero-LLM rule-based middleware
                   │  agents/kid_safe/  │
                   │  ┌──────────────┐  │
                   │  │ tone_rewrite │  │  S1: sarcasm strip → S2: anxiety strip
                   │  │ label_soften │  │  S3: keyword replace → S4: word trim
                   │  │ session_wrap │  │  S5: encouragement inject
                   │  │error_templates│ │
                   │  │ ethical_ai_kb│  │
                   │  └──────────────┘  │
                   └────────┬───────────┘
                            │
                            ▼
                    Student-Facing Output
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Kid-safe is rule-based, not LLM | Every student response passes through this layer. LLM cost/latency would compound per session. |
| WebSocket for DeepTutor transport | True streaming, server-side session management, event-driven protocol. |
| Lazy-load SubagentRegistry | Cold-start latency stays low; agents imported on first dispatch. |
| All config externalized (JSON/YAML) | Tune tone rules, intent keywords, progress labels without code changes. |

## Component Docs

| Doc | Coverage |
|-----|----------|
| [docs/phase2-websocket.md](docs/phase2-websocket.md) | WebSocket protocol, trial discoveries, SessionManager |
| [docs/phase2-registry.md](docs/phase2-registry.md) | SubagentRegistry design, agent ownership matrix |
| [docs/phase2-kidsafe.md](docs/phase2-kidsafe.md) | KidSafePipeline architecture, tone rules, label mapping |
| [docs/Hermes_Integration_Plan_v3.md](docs/Hermes_Integration_Plan_v3.md) | Full integration plan reference |

## Config Files

| Config | Purpose |
|--------|---------|
| `config/ws_client.yaml` | DeepTutor WebSocket connection pool, reconnect, health check |
| `config/kid_safe_tone_rules.json` | Tone rewrite rules: keyword replacements, sarcasm/anxiety patterns, age bands |
| `config/cantonese_keyword_config.json` | Intent classification keywords (Direct / Contextual / Exploratory) |
| `config/dreamer_progress_levels.json` | 4D progress labels: kid-facing (by age band), parent-facing, mastery mapping |

## Test Suite

```bash
# All 253 tests (Phase 1 + Phase 2)
pytest tests/ -q

# Phase 2 specific (197 tests)
pytest tests/test_deeptutor_ws.py tests/test_session_manager.py \
       tests/test_kid_safe_pipeline.py tests/test_kid_safe_wiring.py \
       tests/test_tone_rewrite.py tests/test_label_soften.py \
       tests/test_session_wrap.py tests/test_error_templates.py \
       tests/test_ethical_ai_kb.py -q
```

## CI

- **ci.yml** — trial_run + exit criteria + phase2-tests (pytest)
- Runs on push to main and PRs
