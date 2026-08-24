# Phase 2 — WebSocket Protocol & Session Manager

> **Date:** 2026-08-08  
> **Branch:** feature/phase2-websocket  
> **Container:** ghcr.io/hkuds/deeptutor:1.5.8 (ports 3782 + 8001)

## Protocol Discoveries (trial_ws real-container round-trip)

### 1. Server-assigned session_id

The server assigns its own `session_id` (format `unified_xxx`) and **does not echo** the client's `ephemeral_{student_id}_{uuid}`.

- **Event:** `{"type":"session","session_id":"unified_xxx","seq":0}` is the first event after `start_turn`.
- **Implication:** The client-chosen `session_id` is purely a local label. All routing must account for the server-assigned ID appearing in later events (content/done/result/error).
- **Design:** SessionManager maintains `client_id → server_id` mapping via a `listen()` handler that captures the first `session` event.

### 2. Event stream shape

| Order | Event Type | Description |
|-------|-----------|-------------|
| 1 | `session` | Server-assigned session_id (unified_xxx) |
| 2 | `stage_start` | Capability pipeline stage begins |
| 3 | `progress` | Stage transition (e.g. "Exploring") |
| 4 | `content` × N | Streaming LLM response chunks |
| 5 | `stage_end` | Current pipeline stage ends |
| 6 | `result` | Cost summary, citations, metadata |
| 7 | `done` | Terminal event — turn complete |

The `done` event signals turn completion. The `error` event can appear at any point and terminates the turn with `DeepTutorError`.

### 2.1 Top-level `language` field (Day 23 fix)

Outgoing WS payloads carry a top-level `language` field that mirrors Hermes `lang_code`. Allowed values: `"en"`, `"zh-hk"`, `"zh-cn"` (B26: `zh-cn` synced with Hermes enum; B18 tracks remaining doc work). Omit the field when no language is set.

> **Rule:** never add `language` (or any unknown key) to the config dict — DeepTutor silently falls back to stub on unrecognized config keys (handover habit #14).

### 3. 403 → OpenRouter fix (Day 10 critical path)

**Root cause:** Container's `model_catalog.json` had empty profile → default gpt-4o-mini → `api.openai.com` → `unsupported_country_region_territory` (Hong Kong).

**Fix:** Wrote OpenRouter profile into `model_catalog.json`:
```json
{
  "llm": {
    "profiles": [{
      "id": "llm-profile-832251c4",
      "name": "OpenRouter DeepSeek",
      "provider": "openrouter",
      "model_id": "llm-model-34841b0a"
    }],
    "models": [{
      "id": "llm-model-34841b0a",
      "name": "deepseek/deepseek-chat",
      "provider": "openrouter"
    }]
  }
}
```

- `provider_registry` already had `openrouter` (backend=openai_compat, is_gateway=True, detect_by_key_prefix="sk-or-")
- Key sourced from `.env`: `OPENROUTER_API_KEY=sk-or-v1-xxx` ($4.96 headroom)
- Verified: WS → `{"type":"message","capability":"chat","message":"Say hello"}` → streaming deepseek-chat response (no more 403)

### 4. Session Manager Architecture

**Design decision:** One session = one WS connection (one `DeepTutorWSClient` instance). Pool cap 50.

```
┌─────────────────────────────────────────────┐
│              SessionManager                 │
│                                             │
│  sessions: dict[str, SessionInfo]           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  alice   │  │   bob    │  │  charlie │  │
│  │ client ──┼──│ client ──┼──│ client ──┤  │
│  │ server:  │  │ server:  │  │ server:  │  │
│  │unified_a │  │unified_b │  │unified_c │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │        │
│    WS conn 1      WS conn 2     WS conn 3   │
└───────┼──────────────┼──────────────┼────────┘
        │              │              │
   DeepTutor        DeepTutor      DeepTutor
   Container        Container      Container
```

**Rationale:**
- Single-connection-per-session eliminates cross-session dispatch in the WS client
- Pool cap 50 matches `POOL_MAX_SIZE` in `DeepTutorWSClient`
- Server-assigned `session_id` is captured by `listen()` handler, stored in `SessionInfo.server_id` for debug/tracing only
- `SessionManager.query()` delegates to the session's `DeepTutorWSClient.query()`
- `SessionManager.end_session()` closes the connection and frees a pool slot

### 5. Test Coverage (2026-08-08)

| File | Cases | Status |
|------|-------|--------|
| `tests/test_ws_client.py` | 14 | 14/14 PASS |
| `tests/test_session_manager.py` | 11 | 11/11 PASS |
| `tests/test_concurrent.py` | 10 | 10/10 PASS |

**SessionManager tests:**
1. create_session basic — SessionInfo populated, client attached
2. pool exhausted — PoolExhaustedError at capacity
3. query delegation — returns QueryResult from bound client
4. server_id capture — session event → SessionInfo.server_id
5. concurrent isolation — two sessions, separate clients+queues, correct content each
6. end_session — frees pool slot
7. shutdown — all sessions closed
8. end nonexistent — safe no-op
9. idempotent create — same client_id returns existing
10. unknown query — KeyError
11. pool cap — POOL_MAX_SIZE enforced

### 6. Open Items

All items closed — Day 10 gate ✅ (2026-08-08).

- [x] `test_concurrent.py` — 10 concurrent stress test, 10/10 PASS
- [x] Trial WS re-run: verified `done` / `result` / `cost_summary` / UTF-8 round-trip
- [x] Day 10 gate materials: trial output, test pass log, this doc
