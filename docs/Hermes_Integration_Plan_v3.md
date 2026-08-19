# Hermes Integration Plan — Dreamer AI Education

**Version:** Draft 3 (10 Fixes Applied)  
**Date:** 2026-08-03  
**Owner:** Marvis (Product Owner)

---

## 1. Architecture Overview

```
                  ┌────────────────────────────────────┐
                  │       Marvis — Product Owner        │
                  │   Approve / Reject / Edit / Audit   │
                  └────────────────┬───────────────────┘
                                   │ orchestrates
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Hermes — Project Manager                           │
│                    Engine: DeepSeek V4 Flash                          │
│                                                                      │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│   │  Plan    │  │  Route   │  │  Sync    │  │  Merge   │           │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│   ┌──────────┐  ┌──────────────────────────────────────┐           │
│   │  Gate    │  │    Deterministic Mode Router          │           │
│   └──────────┘  │  DIRECT │ CONTEXTUAL │ HYBRID        │           │
│                 │  en + zh-hk keyword tables            │           │
│                 └──────────────────────────────────────┘           │
│                                                                      │
│   Inputs:                                                            │
│   ┌──────────────────────┐    ┌──────────────────────┐              │
│   │   Knowledge Graph    │    │    Policy Engine      │              │
│   │  Curriculum+Comp     │    │  Rules+Safety+        │              │
│   │  Rubric+Assessment   │    │  Compliance           │              │
│   └──────────────────────┘    └──────────────────────┘              │
│                                                                      │
│   Metadata Index: ┌──────────────────────────────────┐              │
│                   │  SQLite: topic_id → mode_allow,  │              │
│                   │  prereqs, grade_level, projects  │              │
│                   └──────────────────────────────────┘              │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ delegate_subagent
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│Curriculum Agent │   │Assessment Agent │   │ Portfolio Agent │
│    (Teal)       │   │    (Green)      │   │   (Purple)      │
│                 │   │                 │   │                 │
│ Syllabus        │   │ Tests           │   │ Student Work    │
│ Lesson Plans    │   │ Rubrics         │   │ Showcase        │
│                 │   │ Grading         │   │                 │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         ▼                     ▼                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      DeepTutor Layer                                  │
│                                                                       │
│  Invocation: Async WebSocket (unified_ws.py) + Python SDK             │
│  Session: Per-request ephemeral sessions (no persistent Memory)      │
│                                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │  Chat    │ │deep_quest│ │deep_solve│ │deep_res. │ │Visualize │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Knowledge Bases (versioned, multi-engine)        │   │
│  │  Each document: YAML frontmatter metadata                     │   │
│  │  ┌─────────┐┌─────────┐┌──────────┐┌─────────┐              │   │
│  │  │LlamaIdx ││PageIdx  ││ GraphRAG ││LightRAG │              │   │
│  │  └─────────┘└─────────┘└──────────┘└─────────┘              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  Reserved for v2: Memory (L1/L2/L3), Mastery Path capability         │
└──────────────────────────────────────────────────────────────────────┘
         │                                               │
         ▼                                               ▼
┌─────────────────┐                           ┌─────────────────┐
│Parent Rpt Agent │                           │ Marketing Agent │
│    (Red)        │                           │   (Orange)      │
│                 │                           │                 │
│ Queries Dreamer │                           │ Social          │
│ DB, not         │                           │ Content         │
│ DeepTutor       │                           │                 │
│ Memory          │                           │                 │
└────────┬────────┘                           └─────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Dreamer DB                                         │
│                                                                       │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐     │
│  │ assessment_logs  │ │ progress_snaps   │ │ session_logs     │     │
│  │ (grade + label + │ │ (topic mastery   │ │ (mode + duration │     │
│  │  topic + ts)     │ │  % + ts)         │ │  + agent_used)   │     │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘

         All outputs pass through:
┌──────────────────────────────────────────────────────────────────────┐
│                   Dreamer Kid-Safe Output Layer                       │
│  Config: en / zh-hk / zh-cn tone rules per age band                  │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Tone Rewrite │  │ Label Soften │  │Session Wrap  │               │
│  │ (age + lang  │  │ (IB terms →  │  │ (friendly     │               │
│  │  appropriate)│  │  kid-facing) │  │ 7-turn end)   │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Fix #1 — Deterministic Keyword Engine (No ML)

No ML classifier. A keyword table that Hermes evaluates at `Plan` phase. Keyword sets externalized to JSON config for zero-code tuning.

| Mode | What It Means | English Triggers | Cantonese Triggers (zh-hk) |
|---|---|---|---|
| **DIRECT** | Academic tutoring, exam revision, homework help | "exam", "test", "revision", "quiz me", "homework", "school test", "help me study" | "測驗", "考試", "溫書", "做功課", "練習", "補習", "默書" |
| **CONTEXTUAL** | AI literacy projects, creative exploration | "I want to make a game", "build a project", "create", "design", "how does AI" | "我想整", "創造", "設計", "AI係點", "整遊戲" |
| **HYBRID** | Using AI tools for school work | "use AI to revise", "can AI help me", "generate using AI" | "用AI溫", "AI幫我", "AI做功課" |

### Language Code Standard

| Code | Language | Script | Market |
|---|---|---|---|
| `en` | English | Latin | International |
| `zh-hk` | Cantonese | Traditional Chinese | Hong Kong (primary) |
| `zh-cn` | Mandarin | Simplified Chinese | Mainland expansion |

### Routing Rules

```
1. Detect language from input → set lang_code
2. If message contains DIRECT triggers → mode = DIRECT → Assessment Agent active
3. If message contains CONTEXTUAL triggers → mode = CONTEXTUAL → Curriculum Agent active
4. If message contains both → mode = HYBRID → both Agents, Curriculum Agent leads
5. If message contains none → default = CONTEXTUAL
6. Explicit override: "exam mode" / "測驗模式" → DIRECT; "project mode" / "項目模式" → CONTEXTUAL
```

### Mode KB Behaviour Matrix

| KB | CONTEXTUAL mode | DIRECT mode | HYBRID mode |
|---|---|---|---|
| dreamer-maths | Game coordinates, data viz, cryptography in context | Fractions, algebra, geometry, practice sets | "Use AI to visualise and practise fractions" |
| dreamer-english | Prompt writing, technical reading, AI ethics essays | Grammar, reading comprehension, writing frameworks | "Use AI to analyse my essay structure" |
| dreamer-computing | AI literacy core (primary mode) | Scratch/Python debugging, algorithmic thinking | "Build an AI quiz app to test my coding" |
| dreamer-science | Sensor data, scientific method in AI training | Physics, chemistry, biology revision | "Use AI to simulate this experiment" |
| dreamer-psd | AI ethics discussions, team collaboration | Not available in DIRECT | "Discuss AI fairness in group work" |
| dreamer-life_skills | Project management, AI project planning | Not available in DIRECT | "Plan my AI project timeline" |
| dreamer-l2l | Metacognition, learning how to learn with AI | Exam techniques, memory strategies | "Use AI to build my revision schedule" |
| dreamer-history | Contextual use in cross-disciplinary projects | Available on demand | "Research historical AI milestones" |
| dreamer-ethical-ai | Available in all modes, always | Available in all modes, always | Available in all modes, always |

---

## 3. Fix #2 — WebSocket API, Not Subprocess (BLOCKER)

DeepTutor provides two production-grade invocation paths. Subprocess is not one of them.

### 3.1 WebSocket API (Primary)

```python
# Hermes Domain Agent calls DeepTutor via async WebSocket
import asyncio
import websockets
import json

async def consult_deep_tutor(
    student_id: str, query: str, mode: str, kb_list: list[str],
    capability: str, lang_code: str, grade_level: str, session_id: str
):
    uri = f"ws://{DEEPTUTOR_HOST}:{DEEPTUTOR_PORT}/api/v1/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "session_id": session_id,
            "capability": capability,
            "message": query,
            "kb": kb_list,
            "config": {
                "mode": mode,
                "grade_level": grade_level,
                "language": lang_code
            },
            "workspace": f"student_{student_id}"
        }))
        full_response = []
        async for raw in ws:
            event = json.loads(raw)
            if event["type"] == "chunk":
                full_response.append(event["content"])
            elif event["type"] == "done":
                break
            elif event["type"] == "error":
                raise DeepTutorError(event["message"])
        return {
            "content": "".join(full_response),
            "cost_summary": event.get("cost_summary", {}),
            "citations": event.get("citations", [])
        }
```

### 3.2 Python SDK (Alternative)

```python
from deeptutor import DeepTutorApp

app = DeepTutorApp(workspace=f"student_{student_id}")
result = app.run(
    capability=capability, message=query,
    kb=kb_list,
    config={"mode": mode, "grade_level": grade_level, "language": lang_code},
    session=session_id
)
```

### Why This Matters

| Aspect | Subprocess (rejected) | WebSocket (Fix #2) |
|---|---|---|
| Latency per request | 500ms+ (process spawn) | <50ms (persistent connection) |
| Concurrent students | No scaling | Async, handles N connections |
| Streaming | Fragile NDJSON through stdout | Native NDJSON over WS |
| Error handling | Parse exit codes | Structured error events |
| DeepTutor intent | Workaround | Designed server architecture (`unified_ws.py`) |

**Effort: +2 days (Phase 2)**

---

## 4. Fix #3 — KB Metadata: YAML Frontmatter + SQLite Index

### 4.1 Per-Document YAML Frontmatter (Inside DeepTutor KB)

```yaml
---
topic_id: maths-fractions-01
subject: maths
topic: Fractions
ai_literacy_context: "Used in game balance calculations, probability ratios, resource distribution in game design"
modes_allowed: [contextual, direct, hybrid]
grade_level: P4-P6
prerequisites:
  - maths-division-01
  - maths-multiplication-02
linked_projects:
  - game-design-01
  - data-viz-02
dreamer_phase: Discover          # Teaching mainline — Dreamer 4D axis
ib_atl_skills:                   # Cross-reference tag (internal; school alignment only)
  - thinking-critical
  - thinking-transfer
ethical_ai_tags:
  - fairness
  - data-bias
---
```

### 4.2 SQLite Index (Hermes-Side)

```sql
CREATE TABLE topic_metadata (
    topic_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    ai_literacy_context TEXT,
    modes_allowed TEXT NOT NULL,
    grade_level TEXT NOT NULL,
    prerequisites TEXT,
    linked_projects TEXT,
    ib_atl_skills TEXT,
    dreamer_phase TEXT,
    ethical_ai_tags TEXT,
    kb_name TEXT NOT NULL,
    document_path TEXT NOT NULL
);
-- indexes omitted for brevity
```

**Effort: +1 day (Phase 1)**

---

## 5. Fix #4 — Session Isolation: Ephemeral (v1)

Per-request ephemeral sessions. All progress data lives in Dreamer DB, not DeepTutor Memory. Workspace cleanup after 90 days inactivity.

```python
session_id = f"ephemeral_{student_id}_{uuid4().hex[:8]}"
```

**Effort: +1 day (Phase 0)**

---

## 6. Fix #5 — Ethical AI KB + Kid-Safe Output Layer

### 6.1 `dreamer-ethical-ai` KB (Universal, always appended)

| Module | Topics |
|---|---|
| AI Fairness | Bias in training data, algorithmic fairness, representation |
| AI Safety | Prompt safety, deepfakes, misinformation detection |
| AI Ethics | Privacy, consent, intellectual property, environmental impact |
| Responsible Use | Age-appropriate AI use, digital citizenship, when NOT to use AI |
| Dreamer Principles | Company values, student rights, parent transparency |

### 6.2 Kid-Safe Output Layer (Dreamer Backend Middleware)

Three sub-components with bilingual (en + zh-hk + zh-cn) config per age band.

**Effort: +1 day (Phase 2)**

---

## 7. Fix #6 — Dreamer Progress Levels (IB-referenced) (HIGH)

Dreamer AI uses its proprietary Dreamer 4D framework as the pedagogical spine. Progress levels and rubrics are informed by international curricula (including IB ATL skills) as internal cross-reference only.

### Complete Label Mapping (All 4 Layers, All 4 Age Bands)

| Internal (DeepTutor) | Kid-Facing P1-P3 (en) | Kid-Facing P1-P3 (zh-hk) | Kid-Facing P4-P6 (en) | Kid-Facing P4-P6 (zh-hk) | Kid-Facing S1-S3 (en) | Kid-Facing S1-S3 (zh-hk) | Parent-Facing (en) | Parent-Facing (zh-hk) |
|---|---|---|---|---|---|---|---|---|
| **Not Yet** | Getting Started | 開始緊啦！ | Keep Going! | 繼續努力！ | Not Yet | 仍需努力 | Building Foundations | 建立基礎中 |
| **Developing** | Making Progress | 進步中！ | Almost There! | 就快得啦！ | Developing | 發展中 | Developing | 發展中 |
| **Achieved** | You've Got It! | 你做到啦！ | Well Done! | 做得好！ | Achieved | 已達標 | Achieved | 已達標 |
| **Exemplary** | Amazing Work! | 好犀利呀！ | Excellent! | 非常出色！ | Exemplary | 卓越表現 | Exemplary | 卓越表現 |

### Cantonese Session Wrap-Up Messages

| Language | Message |
|---|---|
| en | "Great session! You've made progress on [topic]. Come back anytime — I'll be here!" |
| zh-hk | 「今日學得好叻呀！[topic] 進步咗好多。隨時返嚟搵我啦！」 |
| zh-cn | 「今天学得很棒！[topic] 进步了很多。随时回来找我吧！」 |

**Effort: +0.5 day (Phase 3 — config update)**

---

## 8. Fix #7 — Dreamer DB Schema for Progress (HIGH)

Parent Report Agent and Portfolio Agent cannot rely on DeepTutor Memory (ephemeral sessions in v1). All progress data is stored in Dreamer's own database.

### Schema

```sql
-- Core assessment log: every DeepTutor grading event
CREATE TABLE assessment_logs (
    id UUID PRIMARY KEY,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    mode TEXT NOT NULL,                -- DIRECT / CONTEXTUAL / HYBRID
    lang_code TEXT NOT NULL,           -- en / zh-hk / zh-cn
    internal_label TEXT NOT NULL,      -- Not Yet / Developing / Achieved / Exemplary
    confidence REAL,
    rubric_id TEXT,
    evidence_text TEXT,
    agent_used TEXT,                   -- Assessment Agent / Curriculum Agent
    cost_tokens INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Progress snapshots: aggregated per student per topic
CREATE TABLE progress_snapshots (
    id UUID PRIMARY KEY,
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    mastery_pct REAL NOT NULL,         -- 0.0 to 1.0
    attempt_count INTEGER DEFAULT 0,
    last_label TEXT,                   -- Most recent IB label
    streak INTEGER DEFAULT 0,          -- Consecutive improvements
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(student_id, topic_id)
);

-- Session logs: audit trail for parent transparency
CREATE TABLE session_logs (
    id UUID PRIMARY KEY,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    lang_code TEXT NOT NULL,
    agent_list TEXT NOT NULL,          -- JSON array of agents used
    topic_ids TEXT NOT NULL,           -- JSON array
    duration_seconds INTEGER,
    turn_count INTEGER,
    exit_reason TEXT,                  -- completed / timeout / student_left
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_assess_student ON assessment_logs(student_id, created_at DESC);
CREATE INDEX idx_snapshot_student ON progress_snapshots(student_id);
CREATE INDEX idx_session_student ON session_logs(student_id, created_at DESC);
```

### Data Flow

```
Student interaction → Hermes → DeepTutor → Response
                              ↓ (sync write)
                        Dreamer DB:
                          - assessment_logs (every grade event)
                          - progress_snapshots (upsert per topic)
                          - session_logs (per session)
                              ↑
                    Parent Report Agent queries Dreamer DB
                    Portfolio Agent queries Dreamer DB
```

**Effort: +1 day (Phase 0 — schema + migration + Agent wiring)**

---

## 9. Fix #8 — Buffer Days + Checkpoint (MEDIUM)

### Day 10 Checkpoint: WebSocket Connectivity Gate

```
Day 10 Go/No-Go criteria:
  [ ] DeepTutor container healthy (health check endpoint passing)
  [ ] Single WebSocket connection → 1 capability call → valid response
  [ ] 10 concurrent ephemeral sessions, no collisions, no dropped connections
  [ ] Connection pool monitoring dashboard up
  [ ] If ALL pass → proceed. If ANY fail → escalate, do not proceed to kid-safe layer
```

### Buffer Days (Day 26-27)

- Day 26: End-to-end integration test (student login → inquiry → response → DB write → parent report)
- Day 27: Bug fixes, PR review, final regression testing

**Effort: +2 days (buffer)**

---

## 10. Fix #9 — Cantonese / Bilingual Support (MEDIUM)

### 10.1 Language Detection + Keyword Tables (Externalized)

Mode detection keywords and tone rules live in a JSON config file, not hardcoded. No code changes needed to tune.

```json
{
  "languages": {
    "en": { "script": "Latin", "market": "international" },
    "zh-hk": { "script": "traditional", "market": "hong_kong", "default": true },
    "zh-cn": { "script": "simplified", "market": "mainland" }
  },
  "mode_keywords": {
    "direct": {
      "en": ["exam", "test", "revision", "quiz me", "homework", "school test", "help me study"],
      "zh-hk": ["測驗", "考試", "溫書", "做功課", "練習", "補習", "默書"],
      "zh-cn": ["测验", "考试", "复习", "做功课", "练习", "补习", "默写"]
    },
    "contextual": {
      "en": ["make a game", "build a project", "create", "design", "how does AI"],
      "zh-hk": ["我想整", "創造", "設計", "AI係點", "整遊戲"],
      "zh-cn": ["我想做", "创造", "设计", "AI是什么", "做游戏"]
    },
    "hybrid": {
      "en": ["use AI to", "can AI help me", "generate using AI"],
      "zh-hk": ["用AI溫", "AI幫我", "AI做功課"],
      "zh-cn": ["用AI复习", "AI帮我", "AI做功课"]
    }
  }
}
```

### 10.2 Cantonese Tone Rules (Kid-Safe Layer Config)

| Age Band | Rule | en Example | zh-hk Example |
|---|---|---|---|
| P1-P3 | Short sentences (≤10 words); encouragement every 2 turns; no sarcasm | "You did it!" | 「你做到啦！好叻呀！」 |
| P4-P6 | Medium sentences (≤15 words); positive framing; avoid "wrong" | "Almost — let's try a different way" | 「差少少咋，試下另一個方法？」 |
| S1-S3 | Full sentences; constructive critique OK; no grade anxiety language | "Here's what to strengthen" | 「呢度可以再加強，一齊睇下？」 |

**Effort: +1 day (Phase 2.5 — config + Cantonese testing)**

---

## 11. Fix #10 — Mastery Path Documentation (LOW)

### Explicit Decision

DeepTutor's Mastery Path capability is **not used in v1**. Rationale:

1. Prerequisite navigation is handled by Hermes Curriculum Navigator querying the SQLite metadata index (`prerequisites` field) — this is deterministic and auditable
2. Mastery Path relies on DeepTutor Memory (L2/L3), which is not persisted in v1's ephemeral session model
3. The SQLite index approach gives teachers and parents a transparent, inspectable prerequisite chain — Mastery Path is probabilistic and harder to explain

### Status

| Capability | v1 Status | v1 Substitute | v2 Plan |
|---|---|---|---|
| Chat | Active | — | — |
| deep_question | Active | — | — |
| deep_solve | Active | — | — |
| deep_research | Active | — | — |
| visualize | Active | — | — |
| Book Engine | Active | — | — |
| **Mastery Path** | **Not used** | Hermes Curriculum Navigator + SQLite prerequisites | Evaluate when persistent Memory is added (v2) |

**Effort: 0 days (documentation only)**

---

## 12. Updated Agent-to-KB Ownership Matrix

| KB | Curriculum Agent | Assessment Agent | Portfolio Agent | Parent Report Agent | Marketing Agent | Ethical AI |
|---|---|---|---|---|---|---|
| dreamer-maths | **Owner** | Read | — | — | — | All Read |
| dreamer-english | **Owner** | Read | — | — | — | All Read |
| dreamer-computing | **Owner** | Read | — | — | Read | All Read |
| dreamer-science | **Owner** | Read | — | — | Read | All Read |
| dreamer-psd | **Owner** | — | Read | — | — | All Read |
| dreamer-life_skills | **Owner** | — | Read | — | — | All Read |
| dreamer-l2l | **Owner** | Read | — | — | — | All Read |
| dreamer-history | **Owner** | — | — | — | — | All Read |
| dreamer-ethical-ai | — | — | — | — | — | **Universal** |
| dreamer-prerequisites | **Curriculum Navigator (sub)** | — | — | — | — | — |
| dreamer-rubrics | — | **Owner** | — | — | — | — |
| dreamer-portfolio | — | — | **Owner** | Read | — | — |

---

## 13. Final Timeline (All 10 Fixes Applied)

| Phase | What | Days | When | Key Fix Applied |
|---|---|---|---|---|
| 0 | Prep + Ephemeral Sessions + Dreamer DB Schema | 3 | Days 1–3 | #4 session isolation; #7 DB for progress |
| 1 | KB Export + YAML Frontmatter + SQLite Index | 4 | Days 4–7 | #3 metadata index |
| 2 | Hermes Subagent Registry + WebSocket + Kid-Safe Layer | 8 | Days 8–15 | #2 WebSocket; #5 ethical KB + output layer |
| — | **Checkpoint Day 10: WebSocket connectivity gate** | — | Day 10 | #8 buffer plan |
| 2.5 | Input Safety + Bilingual Config (en/zh-hk/zh-cn) | 1 | Day 16 | #9 Cantonese keywords + tone rules |
| 3 | Assessment Skills + Dreamer Progress Levels | 2 | Days 17–18 | #6 IB label mapping |
| 4 | Curriculum Navigator + Mode Routing (keyword engine) | 3 | Days 19–21 | #1 deterministic routing |
| 5 | Observability + Quality Audit Pipeline | 2 | Days 22–23 | — |
| 6 | Parent Report (Dreamer DB) + Portfolio Agent | 2 | Days 24–25 | #7 Dreamer DB queries |
| Buffer | Integration Testing + Bug Fixes | 2 | Days 26–27 | #8 contingency |

**Production-ready core: 27 days (vs. original 19)**

---

## 14. Fix Impact Summary

| # | Fix | Severity | Effort | What Changed |
|---|---|---|---|---|
| #1 | Deterministic keyword engine | — | 0 days (design) | ML → keyword table; added HYBRID mode |
| #2 | WebSocket, not subprocess | BLOCKER | +2 days | Latency 500ms→50ms, async concurrency |
| #3 | YAML frontmatter + SQLite index | HIGH | +1 day | Queryable metadata for Hermes filtering |
| #4 | Ephemeral session isolation | HIGH | +1 day | Per-request sessions, zero cross-student risk |
| #5 | Ethical AI KB + kid-safe output layer | MEDIUM | +1 day | Universal ethical guardrail + tone/label/session middleware |
| #6 | Dreamer Progress Levels (IB-referenced) | HIGH | +0.5 day | HKDSE terms → IB PYP/MYP (Not Yet / Developing / Achieved / Exemplary) |
| #7 | Dreamer DB for progress | HIGH | +1 day | Parent Report Agent no longer blocked; queries Dreamer DB, not DeepTutor Memory |
| #8 | Buffer days + Day 10 checkpoint | MEDIUM | +2 days | 2-day contingency; WebSocket connectivity gate before Phase 2 continues |
| #9 | Cantonese/bilingual support | MEDIUM | +1 day | zh-hk keyword triggers, tone rules, session messages; externalized JSON config |
| #10 | Mastery Path explicit non-use | LOW | 0 days | Documented; Hermes Curriculum Navigator substitutes via SQLite prerequisites |

**Total added: +8 days (19 → 27)**

---

## 15. Non-Blocking Recommendations

1. **Health check endpoint**: `GET /health` on DeepTutor container, polled every 30 seconds with alert on 3 consecutive failures
2. **Workspace cleanup policy**: Ephemeral workspaces deleted after 24 hours; persistent workspaces (v2) after 90 days inactivity
3. **Controlled vocabulary for `ethical_ai_tags`**: `fairness`, `safety`, `privacy`, `bias`, `consent`, `environment`, `transparency`, `accountability`
4. **Keyword config externalized**: All mode detection keywords in JSON/YAML — no code changes to tune triggers
5. **Cost tracking**: Per-session LLM API cost (DeepSeek tokens) + DeepTutor compute seconds, logged to `session_logs`
6. **Mastery Path**: Explicitly noted as reserved for v2 evaluation

---

## 16. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| WebSocket connection pool exhaustion | Service degradation | Pool max 50 concurrent; overflow → 503; Day 10 checkpoint |
| SQLite metadata index drift from KB docs | Wrong mode routing | Export script is single source of truth; CI validates on every export |
| Dreamer DB write latency affects response time | Student sees lag | Async write (fire-and-forget); eventual consistency acceptable |
| Keyword engine false negatives for mixed code | Wrong mode routing | Bilingual trigger tables (en + zh-hk); fallback = CONTEXTUAL; JSON config for rapid tuning |
| Cantonese character encoding mismatch in WS | Garbled output | UTF-8 enforced on both ends; pre-flight encoding test in Day 10 checkpoint |
| `dreamer-ethical-ai` KB content quality insufficient | Weak ethical guardrails | Content curated by pedagogy team; review cycle before Phase 1 export |
