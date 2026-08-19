# Phase 6 Output Schemas (locked 2026-08-19)

> 開工第一天鎖死嘅兩個 agent output schema。所有 code 對住 schema 寫。
> 依據：Phase 6 Kickoff Checklist §1.3 / §2.3（Marvis 拍板 2026-08-19）。

## 0. 共同約束

- 兩個 agent 嘅 response 都對齊七欄位思維：`content / mode / lang_code / age_band / kid_label / citations / cost_summary`
- Parent Report **唔經 mode dispatch**，但 `mode` 欄位出固定值 `"parent_report"` 保持 schema 一致
- Portfolio **student-facing**，`content` 必須過 Kid-Safe Output Layer（tone_rewrite + session_wrap）
- 禁止前端自行翻譯 label——parent-facing / kid-facing label 一律後端出

---

## 1. Parent Report Agent — output schema

```json
{
  "content": "（narrative 總結段，parent-facing tone）",
  "mode": "parent_report",
  "lang_code": "zh-hk",
  "age_band": null,
  "kid_label": null,
  "citations": [],
  "cost_summary": {"status": "...", "total_tokens": 0},
  "report": {
    "student_id": "...",
    "variant": "first_steps | standard",
    "period": {"type": "weekly | cycle | journey", "from": "...", "to": "...", "days": 56},
    "summary": {
      "session_count": 0,
      "total_duration_seconds": 0,
      "topics_touched": 0,
      "mode_distribution": {"DIRECT": 0, "CONTEXTUAL": 0, "HYBRID": 0}
    },
    "topics": [
      {
        "topic_id": "...",
        "subject": "...",
        "mastery_pct": 0.0,
        "mastery_delta": 0.0,
        "attempt_count": 0,
        "last_label_internal": "achieved",
        "last_label_parent": "已達標",
        "streak": 0,
        "recent_evidence": [{"date": "...", "label_parent": "...", "evidence_text": "..."}]
      }
    ],
    "activity_timeline": [{"date": "...", "sessions": 0, "modes": ["..."]}],
    "baseline": null,
    "roadmap": null,
    "portfolio_highlights": []
  }
}
```

### 要點

| 欄位 / 規則 | 說明 |
|---|---|
| `variant` | `first_steps`（首週 / 首 3–5 sessions）或 `standard`（≥2 週或 ≥5 sessions） |
| `baseline` / `roadmap` | `first_steps` 時填入（baseline=首次 DIRECT session 嘅 auto_marking 結果做起始水平；roadmap=Curriculum Navigator prerequisite chain 嘅下一步建議）；`standard` 時出 `null` |
| `mastery_delta` | 期初 vs 期末（依賴 D8 rolling average） |
| `portfolio_highlights` | cycle report cross-link 學生期內嘅 portfolio items（id + title 級別，唔倒內容） |
| `evidence_text` | 截斷 ≤200 字 |
| `last_label_parent` | 後端出（D3 mapping，唔准前端翻譯） |
| 新學生零 session | 出 `variant=first_steps` + 空 `topics: []` + 歡迎式 content，**唔准報錯** |

### D3 parent-facing label mapping（鎖死）

| internal_label | parent-facing（zh-hk） | parent-facing（en） |
|---|---|---|
| not_yet | 建立基礎中 | Building Foundations |
| developing | 發展中 | Developing |
| achieved | 已達標 | Achieved |
| exemplary | 卓越表現 | Exemplary |

> 紅線：唔用「尚未達標 / Not Yet Achieved」——deficit-framing，同去成績表化定位矛盾。

---

## 2. Portfolio Agent — output schema

```json
{
  "content": "（kid-facing，過 Kid-Safe tone_rewrite + session_wrap）",
  "mode": "CONTEXTUAL",
  "lang_code": "zh-hk",
  "age_band": "P4-P6",
  "kid_label": "做得好！",
  "citations": [],
  "cost_summary": {},
  "portfolio": {
    "student_id": "...",
    "items": [
      {
        "item_id": "...",
        "topic_id": "...",
        "subject": "...",
        "title": "...",
        "description": "...",
        "evidence_excerpt": "（截斷版）",
        "competencies_4d": ["design", "deliver"],
        "growth_note": "...",
        "kid_label": "非常出色！",
        "achieved_at": "...",
        "linked_project_id": null
      }
    ],
    "share_card": {
      "display_name": "（first name only）",
      "item_id": "...",
      "title": "...",
      "artifact_summary": "...",
      "competencies_4d": ["design", "deliver"],
      "kid_label": "非常出色！",
      "brand": "Dreamer AI",
      "generated_at": "..."
    }
  }
}
```

### 要點

| 欄位 / 規則 | 說明 |
|---|---|
| `content` | **必須**過 Kid-Safe Output Layer；label 用 kid-facing mapping（label_soften），唔係 parent-facing |
| `share_card` | 每 item 一份自足 payload，Phase 7 前端直接 render；**唔准出現 student_id / 全名 / 學校**（P5 PDPO 紅線） |
| `competencies_4d` | Dream / Discover / Design / Deliver badge 陣列 |
| `growth_note` | 對比早期作品一句進步描述，由 progress_snapshots derive |
| `age_band` | 必填；Kid-Safe tone rules 按佢揀 config |

### share_card 私隱欄位黑名單（audit 可加 check）

- `student_id` — 永遠唔入
- 全名 / 姓氏 — 只出 first name
- 學校 / 班級 / 地區 — 永遠唔入
- internal_label / confidence / rubric_id — 永遠唔 render

---

## 3. 數據源

| Agent | 數據表 |
|---|---|
| Parent Report | `assessment_logs` / `progress_snapshots` / `session_logs` / `obs_events`（直查 Dreamer DB，唔經 DeepTutor） |
| Portfolio | `portfolio_items`（新表，Phase 6 建）+ `assessment_logs` / `progress_snapshots`（候選 item 來源） |

## 4. 版本記錄

- 2026-08-19：初版鎖死（D1–D8 / P1–P5 全部拍板後）
