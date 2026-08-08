---

# Phase 2 Kickoff Checklist — Hermes Subagent Registry + WebSocket + Kid-Safe Layer

**Plan Reference:** `docs/Hermes_Integration_Plan_v3.md` §13  
**Timeline:** Days 8–15 (8 working days)  
**Phase 1 Baseline Commit:** `1d0cb6d` (CI green, agents/ migrated, import guard active)  
**Generated:** 2026-08-07

---

## Pre-Flight Checks (Day 8 morning)

- [ ] `git checkout main && git pull` (PR #3 merged; feature/phase1-core-modules is history)
- [ ] `trial_run.py` 3/3 PASS locally with `.env` loaded
- [ ] `trial_security.py` 3/3 PASS locally
- [ ] CI last run green (all jobs: Phase 2 Trial + Exit Criteria Trials + Import Guard)
- [ ] Create feature branch `feature/phase2-registry-ws-kidsafe` from main latest
- [ ] **Strip AIGC metadata from committed files**: this checklist and all `docs/` files must not carry the auto-generated YAML frontmatter block (`Label`/`ProduceID`/`ReservedCode`). Check `docs/Hermes_Integration_Plan_v3.md`, `docs/security-agent-todos.md`, `docs/dreamer-4d-alignment-matrix.md`, and any new Phase 2 docs. Strip before commit — internal IDs have no place in git history.
- [ ] **Pre-flight: DeepTutor container up** — pull pre-built image `ghcr.io/hkuds/deeptutor:1.5.8` (tag 無 v 前綴；GHCR 非 Docker Hub)。用 `docker compose -f docker-compose.ghcr.yml up -d` 或直接 `docker run`：publish port 3782（frontend）+ **8001（backend API/WS，Hermes 直連必需）**。Day 10 gate item #1 改以原生 endpoint 替代，見下文。
- [ ] Confirm DeepTutor container accessible (or mock endpoint for development)
- [ ] **Confirm OpenRouter API key valid + budget headroom for stress test**: Day 10 gate runs 10 concurrent sessions against real DeepSeek tokens. Verify key in `.env` works (`curl` a simple auth check) and budget has headroom above the $5 cap shared with CI. If tight, use CI-only key with higher cap or mock WS endpoint for concurrency test.

---

## Phase 2.1 — Hermes Subagent Registry (Day 8–9)

### 2.1.1 Registry Core (`agents/registry.py`)
- [ ] Create `SubagentRegistry` class
  - `register(name, agent_class, kb_ownership, capabilities, mode_allowlist=None)` method
  - `get(name)` → agent instance lookup
  - `list_by_mode(mode)` → filter agents by mode (DIRECT / CONTEXTUAL / HYBRID)
  - `list_by_kb(kb_name)` → filter agents by KB ownership
  - `list_all()` → all registered agents
- [ ] **Design note — `mode_allowlist` semantics**: DIRECT/CONTEXTUAL/HYBRID are student-query concepts. Only student-facing agents (Curriculum, Assessment, Portfolio) use `mode_allowlist`. Non-student-facing agents (ParentReport, Marketing) register with `mode_allowlist=None` and use different invocation paths (DB queries, content generation). `list_by_mode()` returns only agents with non-None allowlists.
- [ ] Thread-safe: use `threading.RLock` for concurrent registration
- [ ] Lazy init: agents instantiated on first `get()` call, not at register time

### 2.1.2 Agent Stub Classes (`agents/subagents.py`)
- [ ] `CurriculumAgent` — KB owner: dreamer-maths/english/computing/science/psd/life_skills/l2l/history + **dreamer-prerequisites** (Curriculum Navigator sub-role per Plan §12); active in CONTEXTUAL/HYBRID
- [ ] `AssessmentAgent` — KB reader: dreamer-maths/english/computing/science/l2l; active in DIRECT/HYBRID; owner of dreamer-rubrics
- [ ] `PortfolioAgent` — KB reader: dreamer-psd/life_skills; owner of dreamer-portfolio; active in CONTEXTUAL
- [ ] `ParentReportAgent` — queries Dreamer DB only (not DeepTutor); read-only on portfolio KB; mode_allowlist=None, no student-query routing
- [ ] `MarketingAgent` — KB reader: dreamer-computing/science; social content only; mode_allowlist=None, no student-query routing

> Stubs return placeholder responses in Phase 2.1; full LLM integration in Phase 4 (Mode Routing).

### 2.1.3 Registry Wiring (`agents/hermes_scheduler.py`)
- [ ] Inject `SubagentRegistry` singleton into `HermesScheduler.__init__`
- [ ] `plan()` phase: use `registry.list_by_mode(mode)` to select candidate agents
- [ ] `route()` phase: delegate to selected agent via registry
- [ ] Update `trial_run.py` to verify registry wired correctly (mock agent → scheduler → plan → route)

### 2.1.4 Unit Tests
- [ ] `tests/test_registry.py` — register, get, list_by_mode, list_by_kb, duplicate name rejection, thread safety
- [ ] `tests/test_subagents.py` — stub returns expected placeholder, mode permissions enforced

---

## Phase 2.2 — WebSocket Integration (Day 9–15, with Day 10 gate)

### 2.2.1 WS Client (`agents/deeptutor_ws.py`)

> **Naming**: server-side is `unified_ws.py`; client is `deeptutor_ws.py` to avoid collision in logs/debugging.

Reference: `Hermes_Integration_Plan_v3.md` §3.1

- [ ] `DeepTutorWSClient` class
  - `async connect(host, port)` → establish ws connection
  - `async query(session_id, capability, message, kb_list, config)` → send + stream response
  - Response types: `chunk` (accumulate), `done` (return full result + `cost_summary` + `citations`), `error` (raise)
  - Config dict: `{"mode", "grade_level", "language"}`
- [ ] **Cost tracking**: capture `cost_summary` from `done` event; write to `session_logs` table (Dreamer DB schema already defined in Phase 0, §7). If this adds risk to Day 10 gate, explicitly defer to Phase 5 (Observability) — record the final decision in `docs/phase2-websocket.md` (Phase 2.4.2 deliverable) so Phase 5 can find it.
- [ ] Connection pool: max 50 concurrent, overflow → 503
- [ ] Reconnection: exponential backoff (1s → 2s → 4s → 8s, max 3 retries)
- [ ] UTF-8 enforced on both ends
- [ ] Health check: `GET /` (liveness, 30s poll, backend process 存活即 200) + `GET /api/v1/knowledge/health` (readiness, KB 子系統狀態)；alert on 3 consecutive failures

### 2.2.2 Session Manager (`agents/session_manager.py`)
- [ ] Ephemeral session ID: `f"ephemeral_{student_id}_{uuid4().hex[:8]}"`
- [ ] Session lifecycle: create → use → close (per-request)
- [ ] No cross-student session reuse
- [ ] Workspace cleanup: after 24 hours (v1 ephemeral policy)

### 2.2.3 HermesScheduler Integration
- [ ] Replace placeholder DeepTutor calls with `DeepTutorWSClient.query()`
- [ ] Wire `session_id` generation into `HermesScheduler.route()`
- [ ] **Error handling**: on WS error, HermesScheduler returns a structured `DeepTutorError` dict (error_type, raw_message, lang_code, grade_level). This dict is handed to KidSafePipeline's error template logic (**not** raw text to student). See §2.3.3 for kid-safe error templates.

### 2.2.4 Day 10 Connectivity Gate (BLOCKER)

> Per `Hermes_Integration_Plan_v3.md` §9: ALL must pass before proceeding.

- [ ] DeepTutor container healthy: liveness `GET /` → 200 + readiness `GET /api/v1/knowledge/health` → status ok（以原生 endpoint 替代，無需 shim）
- [ ] Single WebSocket connection → 1 capability call → valid response (end-to-end)
- [ ] 10 concurrent ephemeral sessions, no collisions, no dropped connections
- [ ] Connection pool monitoring dashboard up (or log-based observable)
- [ ] UTF-8 encoding test: Cantonese characters round-trip cleanly
- [ ] **If ALL pass → proceed. If ANY fail → escalate, do not proceed to kid-safe layer.**

### 2.2.5 WS Integration Tests
- [ ] `tests/test_ws_client.py` — connect, single query, streaming chunks, error handling, reconnect
- [ ] `tests/test_session_manager.py` — ephemeral ID uniqueness, concurrent session isolation
- [ ] `tests/test_concurrent.py` — 10 concurrent sessions stress test (Day 10 gate item)

---

## Phase 2.3 — Kid-Safe Output Layer (Day 11–14)

Reference: `Hermes_Integration_Plan_v3.md` §6.2

### 2.3.1 Middleware Pipeline (`agents/kid_safe/`)
- [ ] `__init__.py` — KidSafePipeline class (chains ToneRewrite → LabelSoften → SessionWrap)
- [ ] `tone_rewrite.py` — age-band + language appropriate tone rules
  - P1-P3: ≤10 words, encouragement every 2 turns, no sarcasm
  - P4-P6: ≤15 words, positive framing, avoid "wrong"
  - S1-S3: full sentences, constructive critique, no grade anxiety
- [ ] `label_soften.py` — Dreamer internal labels → kid-facing labels
  - Use existing `config/dreamer_progress_levels.json`
  - Not Yet → Getting Started / Keep Going / Not Yet (by age band)
  - Developing → Making Progress / Almost There / Developing
  - Achieved → You've Got It / Well Done / Achieved
  - Exemplary → Amazing Work / Excellent / Exemplary
- [ ] `session_wrap.py` — 7-turn friendly session end
  - Trilingual wrap-up messages (en/zh-hk/zh-cn)
  - Include topic progress summary
- [ ] **Error templates** (`error_templates.py`) — per age band × language, student-facing error messages
  - Errors do NOT go through ToneRewrite (no softening of technical errors)
  - But raw error messages are NEVER shown to students
  - P1-P3: zh-hk「哎呀，我諗唔到答案，試下再問過？」/ zh-cn「哎呀，我没想出来答案，再问问看？」/ en "Oops, I couldn't figure that out — try asking again?"
  - P4-P6: zh-hk「呢題有啲難，不如試下第二個問法？」/ zh-cn「这题有点难，换个问法试试？」/ en "That was tricky — maybe try asking differently?"
  - S1-S3: zh-hk「暫時處理唔到呢個問題，試下換個角度再問？」/ zh-cn「暂时处理不了这个问题，换个角度再问？」/ en "I ran into trouble with that — try rephrasing?"
  - Each template logs raw error internally for debugging

### 2.3.2 Ethical AI KB Universal Append
- [ ] Confirm `dreamer-ethical-ai` KB is always appended to every query
- [ ] Content coverage: fairness, safety, privacy, bias, consent, environment, transparency, accountability

### 2.3.3 Wiring into HermesScheduler
- [ ] Insert `KidSafePipeline` as middleware between DeepTutor response and student-facing output
- [ ] `lang_code` and `grade_level` passed through from Hermes route phase
- [ ] **Error path**: errors are NOT processed by ToneRewrite/LabelSoften/SessionWrap. `KidSafePipeline` routes error dicts directly to `error_templates.py` → student-facing message. Raw error logged internally, never surfaced to student.
- [ ] Normal responses: full pipeline (ToneRewrite → LabelSoften → SessionWrap)

### 2.3.4 Kid-Safe Tests
- [ ] `tests/test_tone_rewrite.py` — each age band + language combo, edge cases
- [ ] `tests/test_label_soften.py` — all 4 Dreamer labels × 3 age bands × 3 languages (en/zh-hk/zh-cn) = 36 test cases
- [ ] `tests/test_session_wrap.py` — wrap message includes topic, correct language
- [ ] `tests/test_error_templates.py` — 3 age bands × 3 languages = 9 error template assertions
- [ ] `tests/test_ethical_ai_kb.py` — verify ethical-ai KB appended to all queries

---

## Phase 2.4 — Config & Docs (Day 15)

### 2.4.1 Configuration
- [ ] `config/ws_client.yaml` — host, port, pool size, retry config, health check interval
- [ ] `config/kid_safe_tone_rules.json` — age band rules (externalized, zero-code tuning)
- [ ] Confirm `config/cantonese_keyword_config.json` and `config/dreamer_progress_levels.json` are up to date

### 2.4.2 Documentation
- [ ] Update `README.md` with Phase 2 architecture diagram
- [ ] `docs/phase2-registry.md` — registry design, agent ownership matrix
- [ ] `docs/phase2-websocket.md` — WS protocol, session lifecycle, error codes
- [ ] `docs/phase2-kidsafe.md` — middleware pipeline, tone rules, label mapping

### 2.4.3 CI Update
- [ ] Add `phase2-tests` job to `.github/workflows/ci.yml`
- [ ] Include WS mock in CI (use `pytest-asyncio` + mock WS server)
- [ ] Kid-safe pipeline unit tests in CI

---

## Phase 2 Deliverables (End of Day 15)

| # | Deliverable | Path |
|---|---|---|
| 1 | Subagent Registry | `agents/registry.py` |
| 2 | Agent Stubs (5 agents) | `agents/subagents.py` |
| 3 | WebSocket Client | `agents/deeptutor_ws.py` |
| 4 | Session Manager | `agents/session_manager.py` |
| 5 | Kid-Safe Pipeline | `agents/kid_safe/` (5 files: `__init__.py`, `tone_rewrite.py`, `label_soften.py`, `session_wrap.py`, `error_templates.py`) |
| 6 | WS Config | `config/ws_client.yaml` |
| 7 | Tone Rules Config | `config/kid_safe_tone_rules.json` |
| 8 | Unit Tests | `tests/` (10 test files) |
| 9 | Phase 2 Docs | `docs/phase2-*.md` (3 docs) |
| 10 | Updated CI | `.github/workflows/ci.yml` (new job) |

---

## Risk Watchlist

| Risk | Watch Signal | Action if triggered |
|---|---|---|
| WebSocket connection pool exhaustion | >40 concurrent connections | Scale pool or add queue |
| DeepTutor container unreachable | 3 consecutive health check failures | Escalate; mock fallback for dev |
| `/health` endpoint missing on Day 8 | — | Resolved: 以原生 `GET /` (liveness) + `GET /api/v1/knowledge/health` (readiness) 替代，無需 shim |
| Kid-safe tone rules miss edge cases | Cantonese mixed-code input garbled | Tune JSON config, no code change |
| Subagent registry key errors at runtime | `KeyError` on agent lookup | Add strict init-time validation |
| Cost tracking forgotten (Phase 5 gap) | No `cost_summary` field in session_logs by Phase 3 | Phase 2.2 decision: either capture now or add explicit TODO comment in `deeptutor_ws.py` referencing Phase 5 |
| Error template gaps for edge cases | 500/503/timeout not covered by templates | Add generic fallback template per language in `error_templates.py` |

---

## Phase 3 Handoff Notes

Phase 3 (Days 17–18, Assessment Skills + Dreamer Progress Levels) depends on:
- Subagent Registry operational (Phase 2.1)
- WebSocket working (Phase 2.2, Day 10 gate passed)
- Kid-Safe middleware returning clean output (Phase 2.3)

Phase 2 does NOT include:
- Mode routing keyword engine (Phase 4)
- Observability / OTEL pipeline (Phase 5)
- Parent Report Agent DB queries (Phase 6)
