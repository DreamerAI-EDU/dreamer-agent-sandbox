# Phase 7 B21 — KB Seed 機制規格 v1.1

> **日期**：2026-08-22（v1.1：Ollama + bge-m3 落地驗證完成，6/6 KB reindex 成功）
> **依據**：phase7-kickoff-plan D6/D8 + 真容器 probe（canary 四步 + mounts 全輸出 + embedding provider 清單 + Ollama 五步全綠 + 全量 reindex 實測）
> **狀態**：機制定案凍結（技術未知數清零，淨返寫 `seed_kb.py`）

---

## 0. Probe 定案摘要（點解係呢個形態）

| 事實 | 來源 | 後果 |
|---|---|---|
| `deeptutor\knowledge_bases` 以 **ro bind mount** 掛入 `/app/data/knowledge_bases` | mounts 全輸出 | 容器永遠寫唔到 host；host 係唯一寫入口 |
| KB 註冊靠中央 `kb_config.json` + 每目錄 `metadata.json`，`configs/sync` 掃描註冊 | canary 深入 probe ① | seed script 要識生成呢兩隻檔 |
| `configs/sync` 要寫 `kb_config.json` 落容器內目錄 → ro 擋死（Errno 30） | probe ② | **API 註冊路唔可用；host 預寫係唯一通道** |
| Host 預寫 config + restart → 註冊成功（count: 1） | probe ③ | 流程驗證可行 |
| 註冊 ≠ 入庫：`raw_documents: 0`，要 reindex | probe ④ | 流程必須包 reindex 步驟 |
| Reindex 被擋：「No embedding model is configured」 | probe ⑤ | embedding profile 係前置 blocker（§4） |
| Reindex 亦被 ro 擋死：DeepTutor 要寫 `kb_config.json` / `.progress.json` / `version-N/` 落 KB root | v1.1 probe ⑥ | **mount 結構修正**（見下） |
| Reindex 要求源文件喺 `KB/raw/` 子目錄 | v1.1 probe ⑦ | **目錄契約修正**（見下） |
| 原方案 C（API upload）被 ro 物理擋死 | 推論 | 唔再考慮 |

**定案流程（v1.1 修正後）**：

```
repo kb/（SoT，入 git）
  → sync 文件落 host deeptutor/knowledge_bases/（ro 側，只讀參考）
  → robocopy 至 deeptutor/kb_runtime/（rw 側，DeepTutor 實際 KB root），md 放入 KB/raw/
  → host 預寫 kb_config.json + 每 KB metadata.json
  → docker restart dreamer-deeptutor
  → 等待 readiness（GET /api/v1/knowledge/health）
  → 觸發 reindex（逐 KB）
  → verify doc counts 對 manifest
  → 出 summary，失敗 exit 1
```

**v1.1 mount 結構修正**（實測發現，詳見 `docs/phase7-kb-config-samples.md` §1）：

```
deeptutor/knowledge_bases/  → /app/data/kb_sot          （ro，SoT 參考）
deeptutor/kb_runtime/       → /app/data/knowledge_bases （rw，DeepTutor KB root）
```

- `DEEPTUTOR_KB_ROOT` 環境變數係 legacy，**DeepTutor 唔讀**；KB root 由 workspace_root 決定（`/app/data/knowledge_bases`），所以只能改 bind mount 目標
- `kb_runtime/` 入 `.gitignore`（生成物），SoT 保持 repo `knowledge_bases/`
- **raw/ 契約**：reindex 只掃 `KB/raw/`（recursive），源文件必須放呢度；`metadata.json` 喺 KB root；`version-N/`、`.progress.json` 係 DeepTutor runtime 產物，唔 sync 返 SoT

---

## 1. 命名裁決（三方打架嘅終局）

**現狀**：代碼用 Plan §12 名（dreamer-maths / dreamer-rubrics / dreamer-prerequisites…），manifest 用 Phase 1 名（dreamer-maths-ai / dreamer-assessment / dreamer-core-kb…），磁碟跟 manifest。交集只有 `dreamer-ethical-ai`。

**裁決：代碼就 manifest。** 理由：
1. Manifest 有可執行管道（export script + 測試）+ 磁碟 + 現有內容掛住；§12 係從未對賬嘅設計文檔（慣例 #5 phantom doc 教訓）
2. B15 原則：export script 係 single source of truth → export script 行 manifest 名 → `topic_metadata.kb_name` 會係 manifest 名
3. **潛伏 bug 實證**：`curriculum_navigator.py` 個 FILTER 用 `dreamer-psd` / `dreamer-life_skills`（§12 名），一旦真有內容入庫，filter 對住 manifest 名嘅 topic_metadata 會 match 唔到任何嘢——唔改名，Navigator 係斷嘅

**代碼改動清單**（grep A 實測位置）：
- `assessment_agent.py:97-100`——ownership `dreamer-rubrics` → `dreamer-assessment`；`dreamer-maths/english/computing/science/l2l` → manifest 對應名
- `curriculum_navigator.py:28-29`——FILTER 改 manifest 名
- `subagents.py:24-26`——9 KB ownership list 改 manifest 名
- `portfolio_agent.py:59-60` / `parent_report_agent.py:116`——同上

**映射表**（改名時用呢個，寫入 PR description）：

| §12 名（代碼現狀） | Manifest 名（目標） | 備註 |
|---|---|---|
| dreamer-maths | dreamer-maths-ai | |
| dreamer-computing | dreamer-coding-python + dreamer-game-design + dreamer-coding-ai | 一拆三，按用途歸位 |
| dreamer-rubrics | dreamer-assessment | |
| dreamer-ethical-ai | dreamer-ethical-ai | 唔使改 |
| dreamer-english / science / history / psd / life_skills / l2l | 無直接對應 | 見 §5 新增 KB 決策 |
| dreamer-prerequisites | （新增，見 §5） | |
| dreamer-portfolio | （新增，見 §5） | |

**CI guard（永絕後患）**：新測試 `test_kb_names_in_code_subset_of_manifest`——掃 `agents/` 出現嘅所有 `dreamer-*` 字串，斷言 ⊆ manifest KB 名集合。改名 PR 一併交。

**流程**：一個獨立 PR（唔好溝埋 seed script），commit → CI 全綠 → squash merge，跟慣例 #6；557 測試基線唔准跌。

---

## 2. `scripts/seed_kb.py` 規格

### 2.1 三個模式

| 模式 | 用途 | 動作 |
|---|---|---|
| `--check` | CI / health_monitor（B22）/ 部署後驗收 | 純讀：validate manifest + 查 API 狀態，唔寫任何嘢 |
| `--sync`（預設） | 日常新增內容 / 部署 | 全流程（sync → config → restart → reindex → verify） |
| `--force-rebuild` | KB 結構壞咗 / 重大改版 | 清 config 重建 + 全量 reindex（要 `--confirm` 旗標） |

### 2.2 Manifest（`kb/manifest.yaml`）schema

```yaml
version: 1
knowledge_bases:
  - name: dreamer-maths-ai          # 唯一鍵，= 目錄名
    rag_provider: llamaindex        # O3 定案：全部 KB 用 llamaindex；欄位名與 samples 契約統一為 rag_provider
    docs_dir: maths-ai/              # 相對 repo kb/
    expected_doc_count: 10           # 對返 phase1 manifest total_topics
```

> **v1.2 修正（Review R2）**：實作冇用 per-doc `docs: sha256` 清單——doc hash 由 `seed_kb.py` 自動計算，存於 runtime `kb_runtime/.seed_state.json`（`{kb_name: {file: sha256}}`），hash 不變 = skip。manifest 唔使人手維護 hash，兩者等價但後者唔會 drift。

`expected_doc_count` 同實際 docs 數唔啱 → `--check` 出 WARNING（內容爬坡期唔 fail），但 `count = 0` → **FAIL（B22 fail-loud）**。

### 2.3 Frontmatter validation（`--check` 核心，將內容審查變機器檢查）

每份 md 必須過：

1. 必要欄位齊：`topic_id / subject / topic / modes_allowed / grade_level / kb_name / dreamer_phase`
2. `grade_level` 限三值：`P1-P3 / P4-P6 / S1-S3`（`M1-M3`、`P1-M3` 一律拒收）
3. `modes_allowed` 子集 ⊆ `{contextual, direct, hybrid}`，入庫前正規化做大階
4. `kb_name` 必須存在於 manifest
5. **禁用欄位**：`domain_agent_owner` 出現即 FAIL（phantom 欄位，見 §5）
6. **Label 詞彙檢查**：正文出現 `Emerging / Proficient / Mastering / Exceeds Expectations / Meets Expectations` 等舊 rubric 詞 → WARNING（防 rubric 打架重演）
7. **IB/ATL 檢查**：正文出現 `IB`、`ATL`、`Approaches to Learning` → FAIL（家長可見內容紅線）
8. AIGC metadata 檢查：`ContentProducer` / `内容由AI` → FAIL（慣例 #4）

### 2.4 Config 生成

- `kb_config.json`：由 manifest 全量生成（唔係 merge——manifest 係 SoT，生成嘅檔係 artifact）
- 每 KB 目錄 `metadata.json`：同上，由 manifest 該 KB 條目生成
- 兩者格式以 probe ③ 成功嗰次嘅結構為準（Marvis 將成功樣本存入 `docs/phase7-kb-config-samples.md` 做契約）

### 2.5 Reindex + verify

- 逐 KB 觸發 reindex（endpoint 名以 openapi.json 為準）
- **v1.2（Review R1 實測發現）**：DeepTutor v1.5.8 嘅 reindex 喺「active embedding config 已有 index」時係 **no-op**（回 `already has an index...no reindex needed`），唔感知 raw/ 內容變化——即新 md 入 raw/ 後直接 reindex 唔會入索引（實測：raw_documents=2 但 index 得舊 doc）。因此 `--sync` 喺 reindex 前對 changed KB **先刪 `version-*` 目錄**（`clear_kb_index`）再觸發 reindex，確保真重建。
- Verify 分兩層：① 每 KB `raw_documents` count == manifest `expected_doc_count`；② **索引內容核對**——讀 `version-*/bm25_retriever/corpus.jsonl` 嘅 `file_name` 集合，同 manifest 預期 md 集對比，缺檔 → FAIL（`index missing docs`）。第②層先會抓到「raw 有但 index 冇」嘅沉默失敗。
- 失敗處理：某 KB 失敗唔阻其他 KB；summary 列明邊個 FAIL，exit 1

### 2.6 冪等

重跑 `--sync`：hash 不變嘅 doc skip；KB 已存在且 config 一致 → 唔 restart 唔 reindex（出「no-op」summary）。**判斷點**：config 有變先 restart；doc hash 有變先 reindex 該 KB。

### 2.7 Exit codes

`0` 全綠 / `1` 任何 KB verify 失敗或 count=0 / `2` manifest validation 失敗 / `3` DeepTutor 唔 ready

### 2.8 Known limitations

- **Orphan KB**：KB 由 manifest 刪走後，config 會跟（manifest 全量生成），但 runtime `kb_runtime/` 目錄（含 index）會留低。現靠 `--force-rebuild` 一次過清；長期可加 `--prune` flag（backlog）。

---

## 3. B22 對接（health_monitor）

`health_monitor.py` 加 `--check-kb`：背後 call `seed_kb.py --check` + `GET /api/v1/knowledge/health`。
Fail-loud 條件：KB count = 0、任何 KB `raw_documents` = 0、embedding profile 缺失（`/api/v1/system/test/embeddings` 失敗）。三者任一 → exit 1。

---

## 4. Embedding profile（定案：Ollama + bge-m3）

**決策**：本地 Ollama 行 bge-m3（1024d）。

| 考量 | 結論 |
|---|---|
| 中英雙語（zh-hk + en） | bge-m3 多語表現係開源第一梯隊 |
| 成本 | 零 API 費 |
| 香港網絡 | 本地行，冇地區限制（OpenAI 403 前科唔再關事） |
| DeepTutor 支援 | `ollama` 係原生 `is_local=True` adapter，唔檢查 API key |
| 冇原生 HF adapter | `huggingface`/`openai_compatible` 都 alias 去 `custom`，要自己起 endpoint——Ollama 平一站 |

**配置路徑**：host 裝 Ollama → `ollama pull bge-m3` → 預寫 `model_catalog.json`（`deeptutor\settings` rw mount）：`binding=ollama`、`base_url=http://host.docker.internal:11434/api/embed`、`model=bge-m3`、`dim=1024`，設 `active_profile_id` + `active_model_id` → restart → `POST /api/v1/system/test/embeddings` 驗證 → 試一個 KB reindex。

**✅ 已實測驗證（2026-08-22）**：Ollama 0.32.15 + bge-m3（1024d）落地，五步全綠（version / pull / api/tags / host.docker.internal 容器通 / test-embeddings success）；6/6 KB reindex 成功（status=ready，active_match=true，index version-1 全部 binding=ollama / model=bge-m3 / dim=1024）。樣本格式見 `docs/phase7-kb-config-samples.md` §4。

**VPS RAM 影響（§7 聯動）**：bge-m3 落地後 VPS spec 建議 8GB → **16GB**（或 Ollama q4 量化）。

**Fallback**：若 bge-m3 本地效能唔得（reindex 太慢 / 記憶體爆），改 SiliconFlow remote（keywords 本身包 bge-m3）——但注意 HK 出口同私隱（學生相關文本出外），要 PDPO 評估先入 W6。

**容器→host 網絡**：容器要通 `host.docker.internal:11434`——Docker Desktop（Windows）預設支援；Linux VPS 要 `--add-host` 或 Ollama 直接行喺 compose（見 §7）。

---

## 5. Manifest 修正 + phantom 欄位剝除

**剝除範圍**（grep C 實測）：
- `config/phase1_kb_manifest.yaml`：12 處 `domain_agent_owner`
- 12 份 md（6×2 拷貝）：各 1 行
- `pipeline/phase1_kb_export.py`：233 / 250 / 267 行（SQLite schema 欄位 + insert 讀取）——**schema 改咗，topic_metadata 表要 migration 或重建**（本地 DB 重建就得，未上線冇遷移負擔）
- 測試：grep 冇直接命中，但 export script 測試可能斷言 schema——行全量確認

**KB 清單補完**：manifest 加兩個條目——`dreamer-portfolio`（Portfolio Agent ownership 對齊）同 `dreamer-prerequisites`（先修圖落腳位，os-taxonomy mapping 嘅目的地）。兩者初期可以 `expected_doc_count: 0` + 註明「結構性 KB，唔經 seed 文件流程」，或另立機制——開放項 O1。

---

## 6. 內容線 MVP 清單

**現狀**：95 planned topics，6 份（6.3%）。

**Launch gate（~31 份）**：

| KB | 目標 | 備註 |
|---|---|---|
| dreamer-ethical-ai | 6/6 | Universal guardrail，冇得拗。現有 bias-01 + 補 5 個 module（safety / privacy-consent / responsible-use / dreamer-principles / 待命名）——**8 週課嘅 Citizenship Minute 係現成原材料** |
| dreamer-assessment | 5/5 | rubrics-01 改寫做凍結四級（Not Yet/Developing/Achieved/Exemplary）+ 補分齡變體 |
| dreamer-core-kb | 8/8 | 入門 pathway，新學生第一站 |
| game-design 弧（maths-ai + coding-python + game-design） | ~12 份 | 完成現有 4D 弧 |
| **8 週課程轉換** | 8 週 × 2–3 份 | **最快路徑**：wk1–4 xlsx 係成熟原材料，每週轉 2–3 份 KB 文件（mission sheet + citizenship minute + rubric 已係 Dreamer 格式）；等 wk5–8（2026-08-29 前） |

**v1.1**：storytelling / music-art / language-ai / coding-ai / data-science / project-ideation（其中 project-ideation + prompt literacy 最低消費 2 份，開放問題支架，launch 前補）。

**語言**：英文為主（D 決策），zh-hk 做 bonus——內容線唔排翻譯 pass，但 audit 保留 zh-hk case 防 rust。

---

## 7. 雲部署差異（VPS）

- VPS（Linux）冇 Docker Desktop 嘅 `host.docker.internal` 預設——兩個做法：(a) compose 加 `extra_hosts: host.docker.internal:host-gateway`，Ollama 行 host；(b) **Ollama 直接做 compose 服務**（推薦——成個 stack 一個 compose 檔搞掂，備份/重建一致）
- **RAM 影響**：bge-m3 量化後約 1–2GB；deeptutor + db + redis + web + ollama 齊行，8GB 會緊——server spec 建議上調去 **16GB** 起步（HK VPS 價差有限），或 Ollama 用 q4 量化
- Repo SoT → host 同步喺 VPS 上 = `git pull` + `seed_kb.py --sync`，部署 runbook 一條龍

---

## 8. 驗收標準（trial_b21）

1. 乾淨狀態（KB count 0）行 `--sync` → 全部現有 KB 註冊 + reindex + verify 通過
2. 重跑 `--sync` → no-op summary，exit 0（冪等）
3. 改一份 md → `--sync` → 只該 KB reindex
4. 真 query 測試：問一條新入庫內容嘅問題 → **retrieval 真係抽得到**（唔止 list 到）
5. `--check` 喺 KB count = 0 時 exit 1（B22）
6. `--check` 對住一份壞 frontmatter（M1-M3 / phantom 欄位 / ATL 字樣）→ 正確 FAIL 原因
7. 全程喺真容器行（慣例 #7：mock 綠唔算數）

---

## 9. 開放項

| # | 項目 | 狀態 |
|---|---|---|
| O1 | portfolio / prerequisites 兩個結構性 KB 入唔入 seed 文件流程 | 待定 |
| O2 | kb_config.json / metadata.json 嘅確切 schema | **✅ 已閉環**：`docs/phase7-kb-config-samples.md`（含 raw/ 契約、mount 結構、embedding profile、實測 6/6 驗證表） |
| O3 | 每 KB 用邊個 engine（openapi 確認後填 manifest） | **✅ 已閉環**：全部 llamaindex（現狀即定案）；欄位名統一為 `rag_provider`（§2.2 已改） |
| O4 | 內容線分工同節奏（等 wk5–8 到齊後排） | 待 wk5–8（8/29） |

---

## 10. v1.1 凍結後待辦

1. **寫 `scripts/seed_kb.py`**（§2 規格已齊；config 生成格式以 `docs/phase7-kb-config-samples.md` 為契約）
2. 命名統一 PR（§1：改 5 個 agent 檔 + CI guard test）
3. rubric v2 凍結四級 + `grade_level: P1-S3` 跨度例外落入 `--check` 規則（agent 內部 KB：dreamer-assessment / dreamer-ethical-ai 可用跨度值）
4. 內容線 MVP 製作（§6，wk5–8 到齊後排）
