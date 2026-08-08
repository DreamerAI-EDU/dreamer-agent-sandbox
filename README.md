# dreamer-agent-sandbox

Hermes × DeepTutor integration — multi-agent AI tutoring platform for Hong Kong students.

## Phase 2 Architecture

```
                          User Query
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
        │curriculum│  │assessment│  │  portfolio   │  ... SubagentRegistry
        └────┬─────┘  └────┬─────┘  └──────┬───────┘  (student-facing)
             │              │               │         DIRECT / CONTEXTUAL / HYBRID
             │              │               │
      ┌──────┴──────┐                              ┌──────────────┐
      │parent_report│ (non-student-facing,         │  marketing   │
      └─────────────┘  mode_allowlist=None)         └──────────────┘
             │
             └──────────────┼───────────────────────┘
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
                   │  │ session_wrap │  │  S3: keyword replace → S4: word trim
                   │  │error_templates│ │  S5: encouragement inject
                   │  │ ethical_ai_kb│  │
                   │  │ label_soften │  │  (standalone: assessment labels)
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
| Non-student-facing agents excluded from mode routing | ParentReport and Marketing use `mode_allowlist=None`, skipped by `list_by_mode()`. |

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
| `config/cantonese_keyword_config.json` | Intent classification keywords (Phase 4 — mode routing) |
| `config/dreamer_progress_levels.json` | 4D progress labels: kid-facing (by age band), parent-facing, mastery mapping |

## Test Suite

```bash
# All 253 tests (Phase 1 + Phase 2)
pytest tests/ -q

# Phase 2 breakdown: 197 kid-safe + 25 ws/session + 31 registry/subagents = 253
pytest tests/test_deeptutor_ws.py tests/test_session_manager.py \
       tests/test_kid_safe_pipeline.py tests/test_kid_safe_wiring.py \
       tests/test_tone_rewrite.py tests/test_label_soften.py \
       tests/test_session_wrap.py tests/test_error_templates.py \
       tests/test_ethical_ai_kb.py tests/test_registry.py \
       tests/test_subagents.py -q
```

## CI

- **ci.yml** — trial_run + exit criteria + phase2-tests (pytest)
- Runs on push to main and PRs
