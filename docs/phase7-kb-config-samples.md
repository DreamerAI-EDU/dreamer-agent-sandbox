# Phase 7 B21 — KB Config 樣本契約（O2）

> **日期**：2026-08-22
> **狀態**：已由真容器 reindex 驗證（6/6 KB ready）
> **用途**：`seed_kb.py` 生成 `kb_config.json` / `metadata.json` 嘅目標格式契約。生成結果必須同以下樣本結構一致（值會隨內容變化）。

---

## 0. 目錄結構契約（重要修正）

DeepTutor 1.5.8 嘅 KB 目錄契約：**源文件必須放喺 `raw/` 子目錄**，`reindex` 只掃 `raw/`（recursive）。KB root 放 `metadata.json`，index 產物（`version-N/`）由 DeepTutor 寫入 KB root。

```
kb_runtime/                          # 容器 KB root（rw bind mount，見 §1）
├── kb_config.json                   # 中央註冊 + runtime 狀態
├── dreamer-ethical-ai/
│   ├── metadata.json                # 每 KB 註冊資訊
│   ├── raw/
│   │   └── ethical-ai-bias-01.md    # 源文件（reindex 掃呢度）
│   └── version-1/                   # DeepTutor 寫入嘅 index（唔好手動改）
└── dreamer-maths-ai/
    ├── metadata.json
    ├── raw/
    │   └── maths-fractions-01.md
    └── version-1/
```

**注意**：reindex 進行中 DeepTutor 會喺 KB root 同 `raw/` 寫入 `.progress.json`（runtime 產物，唔好 sync 返 SoT）。

---

## 1. 容器 mount 結構（v1.1 修正）

probe 發現：`DEEPTUTOR_KB_ROOT` 環境變數**冇被 DeepTutor 讀取**（legacy env）；KB root 實際由 `workspace_root/knowledge_bases` 決定（即 `/app/data/knowledge_bases`）。而 DeepTutor 會喺 KB root 寫 `kb_config.json`、每 KB `metadata.json`、`.progress.json` 同 `version-N/` index——**ro mount 會擋死成個 reindex**（Errno 30），唔單止 `configs/sync`。

**修正後 compose volumes**（`deeptutor/docker-compose.yml`；compose 檔案喺 `deeptutor/` 下，相對路徑以佢為基準）：

```yaml
    volumes:
      # Shared KBs (read-only) — SoT sync source, immutable to the container.
      # Compose file lives in deeptutor/, so repo-root SoT is ../knowledge_bases.
      - ../knowledge_bases:/app/data/kb_sot:ro
      # KB root (writable): kb_config.json, metadata.json, provider indexes.
      # Single-direction discipline: host SoT -> robocopy -> kb_runtime.
      - ./kb_runtime:/app/data/knowledge_bases
```

- `knowledge_bases/`（repo 根 SoT；由 `0b7c164` consolidation 遷移，compose 用 `../knowledge_bases`）→ 容器 `/app/data/kb_sot`（**ro**，容器永遠寫唔到）
- `deeptutor/kb_runtime/`（生成物，gitignore）→ 容器 `/app/data/knowledge_bases`（**rw**，DeepTutor 正常運作）
- 單向紀律：repo 根 SoT → robocopy → kb_runtime → 容器；`kb_runtime/` 已入 `.gitignore`
- 分叉修正記錄：`0b7c164` 遷移 SoT 時漏清 `deeptutor/knowledge_bases/` 舊副本（6 個 tracked md，含 `domain_agent_owner` 禁字段）兼漏改本 mount；2026-09-05 watermark PR 刪舊檔並將 mount 指回真 SoT

---

## 2. `kb_config.json` 樣本（reindex 成功後，實際值）

```json
{
  "knowledge_bases": {
    "dreamer-ethical-ai": {
      "rag_provider": "llamaindex",
      "status": "ready",
      "updated_at": "2026-08-22T07:57:15.405824",
      "index_versions": [
        {
          "version": "version-1",
          "signature": "7510e9dfbc32ac55",
          "binding": "ollama",
          "model": "bge-m3",
          "dimension": 1024,
          "base_url": "http://host.docker.internal:11434/api/embed",
          "api_version": "",
          "layout": "flat",
          "created_at": "2026-08-22T07:57:15.163022Z",
          "ready": true,
          "storage_path": "/app/data/knowledge_bases/dreamer-ethical-ai/version-1",
          "version_path": "/app/data/knowledge_bases/dreamer-ethical-ai/version-1",
          "doc_count": 4,
          "probe_diagnostics": {
            "vector_stores": [
              "default__vector_store.json",
              "image__vector_store.json"
            ]
          }
        }
      ],
      "last_completed_at": "2026-08-22T07:57:15.167277",
      "last_indexed_at": "2026-08-22T07:57:15.167277",
      "last_indexed_count": 2,
      "last_indexed_action": "reindex",
      "embedding_model": "bge-m3",
      "embedding_dim": 1024,
      "embedding_signature": "7510e9dfbc32ac55",
      "needs_reindex": false
    }
  }
}
```

**seed 生成時注意**：
- `status` 初始寫 `registered`（或 `needs_reindex`），reindex 完成後 DeepTutor 會改做 `ready`
- `index_versions` / `last_indexed_*` / `embedding_*` 由 DeepTutor 喺 reindex 後寫入——seed 唔使預寫，但 `--check` 要用呢啲欄位 verify
- `updated_at` 用 ISO8601（T 分隔），`created_at` 喺 index version 入面係帶 Z 嘅 UTC

---

## 3. `metadata.json` 樣本（每 KB 一份，KB root）

```json
{
  "name": "dreamer-ethical-ai",
  "created_at": "2026-08-22 15:48:14",
  "description": "Knowledge base: dreamer-ethical-ai",
  "version": "1.0",
  "rag_provider": "llamaindex",
  "needs_reindex": false,
  "last_updated": "2026-08-22T07:57:15.167277",
  "last_indexed_at": "2026-08-22T07:57:15.167277",
  "last_indexed_count": 2,
  "last_indexed_action": "reindex"
}
```

**seed 生成時注意**：
- 最少欄位：`name`（= 目錄名 = manifest 名）+ `rag_provider`（`llamaindex`）
- `created_at` 格式係 `YYYY-MM-DD HH:MM:SS`（空格分隔），同 `last_updated`/`last_indexed_at`（ISO8601 T 分隔）**唔同格式**——跟樣本，唔好統一
- reindex 後 `last_*` 欄位由 DeepTutor 更新；`description` 可自訂，預設 `Knowledge base: <name>`

---

## 4. Embedding profile（`deeptutor/settings/model_catalog.json`，rw mount 預寫）

```json
{
  "version": 1,
  "services": {
    "embedding": {
      "active_profile_id": "ollama-bge-m3",
      "active_model_id": "bge-m3",
      "profiles": [
        {
          "id": "ollama-bge-m3",
          "name": "Ollama bge-m3",
          "provider": "ollama",
          "binding": "ollama",
          "api_key": "",
          "base_url": "http://host.docker.internal:11434/api/embed",
          "models": [
            { "id": "bge-m3", "model": "bge-m3", "name": "bge-m3" }
          ],
          "api_version": "",
          "extra_headers": {}
        }
      ]
    }
  }
}
```

- 修改後 `docker restart dreamer-deeptutor` 生效
- 驗證：`POST /api/v1/system/test/embeddings` → success；`GET /api/v1/knowledge/rag-pipelines/model-options` → embedding.active = ollama-bge-m3
- 同一個檔案 `services.llm` 保持 OpenRouter profile（deepseek-chat）唔郁

---

## 5. 驗證結果（2026-08-22 實測）

| KB | status | raw_documents | index | model/dim | active_match |
|---|---|---|---|---|---|
| dreamer-assessment | ready | 1 | version-1 | bge-m3/1024 | true |
| dreamer-coding-python | ready | 1 | version-1 | bge-m3/1024 | true |
| dreamer-core-kb | ready | 1 | version-1 | bge-m3/1024 | true |
| dreamer-ethical-ai | ready | 1 | version-1 | bge-m3/1024 | true |
| dreamer-game-design | ready | 1 | version-1 | bge-m3/1024 | true |
| dreamer-maths-ai | ready | 1 | version-1 | bge-m3/1024 | true |
