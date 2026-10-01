# 窗 #2 收尾 Closeout 紀錄（v1.0 · 2026-10-01）

- 撰寫：Marvis 代寫（非人類簽核）；日期 **2026-10-01**（UTC）。
- 立項依據：老闆收尾令 —— 「呢度收尾、trial 窗開新 chat」；①–⑤ 收尾包已跑完、全綠，另追認 `class_curriculum` 8 行寫入。
- 本檔性質：**窗 #2（T2 release 窗）收尾之最終紀錄**。涵蓋 ①–⑤ 全項紅綠、`class_curriculum` 8 行追認、本輪 smoke 痕跡清理座標與備份、D9 觀察現狀、c1-6 交付包核對、紅線核查、待簽核項。
- 落地層級：**Tier 0（純 docs）**，入 repo `docs/pr-d-c1/`；單獨一個 docs-only commit ＋ push（無水印尾行）。
- 本窗動作限制（遵老闆收尾令）：**唔做 c1-6 repo swap、唔改 host／DB、唔改前端**。c1-6 repo swap 留待 trial 窗（窗 #3）第一步。

---

## 1. 窗 #2 收尾包 —— 全項紅綠

| 格 | 內容 | 結果 | 關鍵證據 |
| --- | --- | --- | --- |
| ① | persona 重換（8 份 P1–P3，zip 修訂版**原樣**部署；其餘 16 份零郁） | 🟢 | repo commit `27a0bd611e245becc58c967d5c31f45015e07a50`（9 檔：8 × `dibi-curriculum-p1-p3-wk01..08/PERSONA.md` ＋ `deeptutor/personas/README.md`，`+56 / −32`）；CI run **`36858251252`** conclusion **success**（7/7 jobs：phase2-tests／aigc-watermark-guard／trial／ci-manifest-guard／frontend-build／exit-criteria-trials／docker-push）；host 備份 `/root/dreamer_personas_backup_20261001T115729Z/`；host 複製 **`ok=8 / mismatch=0`**；容器內 slug **24** 全讀得、stub 殘留 **0**；**`other16_changed=0`** |
| ② | 清 P1 Smoke 舊 server session（收尾前第一次清理） | 🟢 | engine `messages` 4 行 ＋ relay `ws_chat_session_map` 1 行（舊 engine session `unified_1790682265892_e886e0e1`）；備份 `/root/win2f2_purge_backup_20261001T112213Z/`；24 表對照**僅** `ws_chat_session_map` 4→3；engine `sessions`1／`turns`2／`turn_events`2 孤兒行 ＋ relay audit **保留未動** |
| ③ | c1-3 前端 release（un-hide 課程模式入口） | 🟢 | 由 repo main 以 `VITE_BACKEND=ws` 重建 bundle `assets/index-Cww5adv7.js`（sha `6227279…`）；grep gate 5/5；原子切換 ＋ Cloudflare purge（id `599ab4c9`）；**6/6 content-type PASS**；備份 `/root/dreamer-web-backup/20261001T113848Z/` |
| ④ | D6–D8 smoke 重跑（英文輸入 ＋ 默認英文驗收） | 🟢 **10/10** | 全新 profile 載入新 bundle；**實際撳「My AI Course」**入模式（URL `…&mode=curriculum`）；首幀 `session_id=""` ＋ `dibi_mode="curriculum"`；a（wk01 內容）／b（細路句 ＋ `Grown-up:`）／c（cue cards 五問）／d 四項（零符號／≤8 行／只答當週／任務逐行，**以原始 frame 為準**）／e（exit 後幀無 `dibi_mode`）全綠；NEW5 默認英文 ＋ 中文提問先解釋後返英文 |
| ⑤ | 收尾：登出清 client session | 🟢 | 登出後回 `/student/login`；localStorage 三鍵（`dreamer.ws_chat.session.6842abf2`／`dreamer.ui.lang`／`welcome_shown_v1_6842abf2`）清至 `[]`；cookie 登出即空，另 `cookies clear` 兜底 |
| 追加 A | ①-b `class_curriculum` 8 行寫入 —— 老闆追認（唔回滾） | 🟢 | 見 §2 |
| 追加 B | ②-b 本輪 smoke 新痕跡清理（第二次清理，本輪實測完成） | 🟢 | 見 §3 |

> 收尾包執行期間**零紅線觸碰**：未改 relay／Caddy／compose／deeptutor image tag，未動其餘 16 份 persona，未跑未授權寫入。

---

## 2. ①-b `class_curriculum` 8 行寫入 —— 老闆追認，唔回滾

### 2.1 寫入座標（已落地，本輪未再改動）

| 欄位 | 內容 |
| --- | --- |
| 庫／表 | relay `/data/dreamer.db` → **`class_curriculum`（唯一變動表）** |
| 班 | `class_id = b114f760-e69f-41a6-a397-d2f27a2f108e`（P-band Smoke P1，grade_band P1-P3） |
| SQL 原文 | `INSERT INTO class_curriculum (class_id, topic_id, week_no, status, activated_at, created_at) VALUES (?, ?, ?, ?, ?, ?);` × 8（參數化；`BEGIN IMMEDIATE` … `COMMIT` 單事務） |
| 寫入內容 | wk01 `active`（`activated_at=2026-10-01T10:31:40.489302Z`）＋ wk02–wk08 `locked`（`activated_at=NULL`） |
| 影響行數 | 合計 **8**（rowcount 逐條 = 1）；`class_curriculum` **24 → 32**（added 8 / removed 0） |
| 未執行動作 | **不執行** `UPDATE classes.curriculum_id`（該班 `curriculum_id` 保持 `NULL`） |
| 落庫時間 | `2026-10-01T10:31:40.489302Z` |

### 2.2 為何是 8 行（而非指令字面「一條」）

前置核驗發現「只寫 1 行 wk01」會令 `student_week_badge()` 落到 `state=none`（persona 退回 band，第 ③ 格必失敗）。已停機垂詢並由老闆裁決為 **8 行齊寫**，據此執行。此為已知偏差 1，如實記錄。

### 2.3 驗證證據

- `student_week_badge('6842abf2-…-6e11')` = `{"state":"active","week_index":1,"total_weeks":8,"unit_title":"This is Me! — …"}`。
- 路由鏈實測：`age_band='P1-P3'` → `_band_for_student()`→`p1-p3` → `_curriculum_slug(p1-p3,1)`=`dibi-curriculum-p1-p3-wk01`（∈ 凍結 24 slug 集合）→ `_PersonaRouter(...).slug_for('curriculum')` = `dibi-curriculum-p1-p3-wk01`。
- 24 表 before/after 對照：**唯一差異行 `class_curriculum 24 → 32`**；其餘 23 表 Δ = 0。
- `PRAGMA integrity_check` = **ok**；`schema_version` 70（不變）；`page_count` 103。
- 完整性／回滾演練：一次性副本 `/tmp/f2_drill.db` 上「寫 3 行後強制 ROLLBACK」、「第 9 次 INSERT 觸發 `UNIQUE(class_id, topic_id)` → ROLLBACK」，兩者班內行數均回 0；**未觸碰生產庫**。

### 2.4 偏差與留痕（如實）

1. 寫入行數 **8 ≠ 指令字面「一條」**（原因見 §2.2；已垂詢、老闆裁決 8 行）。
2. `audit_log.jsonl` **未新增行**（168 行、sha 不變）—— 本次經 `docker exec` 直連 SQLite 寫入，**不經 app 層審計鈎子**。替代留痕：`write_receipt.json`（含 SQL 原文、8 組參數、rowcount、before/after 快照 sha、badge 結果）落於備份目錄，sha256 `ab2f5605827cf4c92fe459feeea48644553105ca97bfb3d2e188131bdd35886c`。
3. 附帶發現（非本次寫入所致）：`PRAGMA foreign_key_check` 存在 1 條**既存**違規 `('classes', 2, 'users', 0)`，before／after 完全一致。

### 2.5 回滾座標（僅備用，**已追認唔回滾**）

| 對象 | 座標 | sha256 |
| --- | --- | --- |
| 一致性快照（before） | `/backup/win2f-20261001T102027Z/dreamer.db` | `935f937ac52efe25090489f2f42df4f1caa20be81b0a09ebf5b94696db6223bb` |
| 一致性快照（after） | `/backup/win2f-20261001T102027Z/dreamer.db.after` | `24dc1b73d1d6f6a05e63b9056d0f1526fb14edea2aedcf8a10091722b5a81739` |
| 寫入收據 | `/backup/win2f-20261001T102027Z/write_receipt.json` | `ab2f5605827cf4c92fe459feeea48644553105ca97bfb3d2e188131bdd35886c` |

> 老闆 2026-10-01 裁定：**追認 8 行寫入（24→32），唔回滾**。本節僅存證。

---

## 3. ②-b 本輪 smoke 痕跡清理 —— 座標與備份（本輪實測完成）

### 3.1 清理對象（老闆簽「ok」指定）

| 目標 | 座標 | 性質 |
| --- | --- | --- |
| engine `messages` | `WHERE session_id = 'unified_1790856541144_c5eaee76'`（engine 庫 `/app/data/user/chat_history.db`） | 本輪 D6–D8 smoke 第 ④ 格產生之新 session |
| relay `ws_chat_session_map` | `WHERE student_id = '6842abf2-1419-4baf-b9db-a74c07656e11'`（relay 庫 `/data/dreamer.db`） | 同上 session 對應映射行 |
| **禁刪範圍（保留）** | engine `sessions` / `turns` / `turn_events` 之孤兒行；relay `ws_chat_relay_audit` | 依老闆令「保留、唔准郁」 |

### 3.2 備份（**先行**，時戳 `20261001T131626Z`）

備份目錄：**`/root/win2_closeout_purge_backup_20261001T131626Z/`**

| 檔案 | 內容 | sha256 |
| --- | --- | --- |
| `engine_chat_history.pre.db` | engine 一致性快照（sqlite backup API，15,163,392 B） | `422d0312f710b1794649113591a7055521440d5f7c846b201e9dd63159c33b0f` |
| `engine_chat_history.raw.pre.db` | engine 原始檔副本（15,163,392 B） | `c73e274a05071bfc560f6be4ebaa28b1f70cbfe89ff7480b4c08f43f628332cf` |
| `relay_dreamer.pre.db` | relay 一致性快照（421,888 B） | `6ee7915a14fa39c6844fcf34bc62912bd1f615512e8384fc0e39fa206584c4c0` |
| `pre_state_engine.txt` / `pre_state_relay.txt` / `BACKUP_COORDS.txt` | 前置狀態清單 | — |

備份完整性：engine `integrity_check = ok`（`messages_total = 348`）；relay `integrity_check = ok`（`map_rows = 4`、`audit_rows = 441`）。

### 3.3 實測結果（DELETE 影響行數 ＋ 前後對照）

| 動作 | 前置守衛 | `changes()` | 後置 |
| --- | --- | --- | --- |
| engine `DELETE FROM messages WHERE session_id = 'unified_1790856541144_c5eaee76'` | 目標 messages = **8** | **8** | 目標 messages = **0**；`messages_total` **348 → 340** |
| relay `DELETE FROM ws_chat_session_map WHERE student_id = '6842abf2-…-6e11'` | 目標 map 行 = **1**（`engine_session = unified_1790856541144_c5eaee76`） | **1** | 目標 map 行 = **0**；`map_total` **4 → 3** |

**engine 後置總量**：`messages=340`、`sessions=128`、`turns=200`、`turn_events=16798`；`max_id = 386`；目標 messages = 0。
**保留項實測**：engine `sessions` 孤兒行 **1**、`turns` 保留 **4** 行；relay `ws_chat_relay_audit = 441`（未動）。

**relay 24 表（後置）關鍵值**：`class_curriculum = 32`、`classes = 5`、`students = 6`、`ws_chat_session_map = 3`、`ws_chat_relay_audit = 441`；`integrity_check = ok`；`foreign_key_check` = 1 行（`classes → users` **既存**違規，與 pre-backup 相同）。
**relay `ws_chat_session_map` 殘餘 3 行**（目標生 P1 Smoke 已不在內）：`76c90737…`／`2a7870f4…`／`b57a9846…`。

### 3.4 後置 live sha256

| 對象 | sha256 |
| --- | --- |
| engine `/app/data/user/chat_history.db` | `acf328fe9ba916fe1c23b5ccf9713191f8c34dfa489f7f24bf26963e4938ddab` |
| relay `/data/dreamer.db` | `8f3f5a5f664c2e5e26d843741ac80a1ad88d6abf39203f4a35ae34e01e8004ec` |

### 3.5 清理後 P1 Smoke 狀態判定

- engine 側：本輪 smoke 之 8 條對話訊息已清 → 該 session **無可見對話殘留**；`sessions`/`turns`/`turn_events` 孤兒行（各 1/4/…）依令保留。
- relay 側：`ws_chat_session_map` 該生映射行已清 → 下次登入將建**全新** session（不再復用 `unified_1790856541144_c5eaee76`）。
- relay `ws_chat_relay_audit` 441 行保留 → **P1 Smoke 帳號非「零痕跡」**，audit 仍可追溯本輪 smoke（屬既定保留範圍）。

---

## 4. ③ closeout —— 窗 #2 完結狀態

窗 #2（T2 release 窗）至此**收口完結**：

| 項 | 狀態 |
| --- | --- |
| persona 重換（8 份 P1–P3） | 已上 repo（`27a0bd6`）＋ 已上 host（`ok=8 / mismatch=0`），CI 全綠 |
| relay DB 寫入 | `class_curriculum` 8 行（24→32）已落地，老闆追認唔回滾 |
| 前端 release | bundle `index-Cww5adv7.js` 已上真站（6/6 content-type PASS），CF 已 purge |
| smoke | D6–D8 重跑 10/10 綠（含 NEW5 默認英文） |
| 痕跡 | 舊 session（第一次）＋ 本輪 smoke session（第二次）均已清，備份齊備 |
| repo 狀態 | 本檔為窗 #2 最後一個 docs-only commit，HEAD 於 push 後見 §10 |
| 未做（依令） | c1-6 repo swap、host 24 份 persona 全量換版、manifest 同步 —— 全部留待窗 #3 |
| 口徑 | 「push ≠ 部署」不變；本窗所有 repo 動作未觸發任何 host 部署 |

---

## 5. D9 觀察現狀

**觀察期**：2026-09-30 起至 **2026-10-06**（來源：`docs/pr-d-c1/D6_known_gap_v0.1_2026-09-29.md`；D10 收口時複核）。

### 5.1 觀察項與本輪（2026-10-01）現狀

| # | 觀察項 | 基線（2026-09-29） | 本輪現狀（2026-10-01） | 判定 |
| --- | --- | --- | --- | --- |
| D9-1 | `week_index` 越界（> total_weeks）等異常途徑 | 未做實機覆蓋（Gap ①，接受部分覆蓋結案） | 本輪 smoke 為**正常路徑**（week_index=1），**未自然出現越界個案**；單元測試覆蓋邊界仍為替代證據 | 觀察中，未觸發 |
| D9-2 | relay audit 見 `slug=dibi-s1-s3` 而 `mode=none`（fail-open） | 曾見（session `b57a9846`），列持續觀察 | 本輪**未新增**同類；relay audit 累計至 **441** 行，本輪增量（8 行）全部屬 P1 smoke 正常 turn 事件 | 非缺陷，續觀察 |
| D9-3 | 退出課程模式後 session slug cache 殘留（Limitation ②） | 已批 v1 接受；限同一 WS session 生命週期 | 本輪 smoke exit 後 send 幀**鍵缺省**（無 `dibi_mode`），與 §3 口徑一致；同 session 再對話 slug 延續仍屬**已知限制**，未修復、未關閉 | 已知限制，續觀察 |
| D9-4 | 收貨口徑（零符號／≤8-12 行／只答當週／任務逐行） | 2026-10-01 T2 收口定案（以原始 frame 為輔證） | 本輪 D6–D8 smoke 以**原始 frame** 判讀：d-1～d-4 全綠 | 口徑有效 |

### 5.2 本輪未複測項（如實披露）

- relay 側 **error 級日誌計數**（基線 api 0／deeptutor 1）、近 24h slug 分佈全量統計：本輪**未重跑**，不作結論。
- 已複測且有據者：engine／relay `integrity_check = ok`；`foreign_key_check` engine 空、relay 1 行（**既存** `classes→users`，before 同）。

### 5.3 D9 收口待辦（→ 窗 #3）

- 觀察期內如真機學生自然行到 `week_index` 越界／badge 異常，順手補 Gap ① 實機證據並回填 `D6_known_gap_v0.1` §1。
- 續跑至 **10/6**，由 D10 收口複核 Limitation ② 是否可關閉。

---

## 6. c1-6 交付包核對結果（**只核對，未 swap**）

來源：本輪 workspace `output/c1-6_manifest_2026-10-01.md`（交付包 `c1-6_persona_refresh_2026-10-01/`，內容 24 × `PERSONA.md` ＋ 1 × `README.md`）。

| 核對項 | 結果 |
| --- | --- |
| 來源 zip | `Kimi_Agent_25. Dreamer AI system upgrade.zip`（最後寫入 `2026-10-01 21:00:23`） |
| 包內 README.md sha256 | `746ec648bf0c03a2…`（與桌面 `README (1).md` 逐位元一致） |
| 檔案數 | **24** `PERSONA.md` ＋ 1 `README.md` |
| 語言 gate | **24/24** 含 `English-first` ＋ `Traditional Chinese (Hong Kong)`；`Bilingual by design` 殘留 **0** |
| 與 repo HEAD `27a0bd6` 逐檔比對 | **24/24 逐檔不同**（swap 需 24 檔全換） |
| 本輪 repo 動作 | **零**（未 swap、未 commit、未 push） |

### 6.1 24 slug ＋ sha256（交付包清單）

| # | slug | bytes | sha256 |
| --- | --- | --- | --- |
| 1 | `dibi-curriculum-p1-p3-wk01` | 7611 | `c912a0804cb7ff1f0bd6c554a54374a4ddbd7cf0ec685a5330ad804d2909593f` |
| 2 | `dibi-curriculum-p1-p3-wk02` | 7689 | `1ab8679ebd6a753959e5ba57274a8fc9c298cd6a9ab884f1f4ef98dcf5da79a1` |
| 3 | `dibi-curriculum-p1-p3-wk03` | 7893 | `ce3917e931a34e6286cfe0c89625ec8cb00a29d949dd17d9f5d7f559a3735563` |
| 4 | `dibi-curriculum-p1-p3-wk04` | 7733 | `e5d4deba125b2df81c46c2051dc5d3c6f6009a2b8ba10a2a914740e19d3d726e` |
| 5 | `dibi-curriculum-p1-p3-wk05` | 7850 | `9017582a4c07042fe31bef20a66da980adfb3c69f7d14be2ea4c22d3f61b8f30` |
| 6 | `dibi-curriculum-p1-p3-wk06` | 8065 | `c6ef7802ea14fb1d5683623672662163d1f79238698e3b101fac4bb7419411d0` |
| 7 | `dibi-curriculum-p1-p3-wk07` | 8560 | `63b94fee7e89daa4a6320c3c66ca16c45be49eae0281006504377eee3b1177d6` |
| 8 | `dibi-curriculum-p1-p3-wk08` | 8118 | `59c0d764074e8fe8bec49a0d25bafefd3959caff8b440359477257ad21634f63` |
| 9 | `dibi-curriculum-p4-p6-wk01` | 6198 | `965889799f31038f93a5639d60c9956b7f3bcd2647961032fefb72d9ae380fc0` |
| 10 | `dibi-curriculum-p4-p6-wk02` | 6284 | `63b77b7429537cea459fbcb6d5df512ba22d7dbd30695df9b594d63b743dca36` |
| 11 | `dibi-curriculum-p4-p6-wk03` | 6531 | `e0ef4280fffe12aac542a21aadba8ca83491b4d11d1b62603bb5decdcc8960fa` |
| 12 | `dibi-curriculum-p4-p6-wk04` | 6346 | `ad17894a9bdb58fa3e46c3de19a025379981249f9c13ae4e606f8a6195986d44` |
| 13 | `dibi-curriculum-p4-p6-wk05` | 6091 | `79d42f06ed95998f2638721ac864951a9a199f0506bd0adfe525598fbbcbb7e0` |
| 14 | `dibi-curriculum-p4-p6-wk06` | 6422 | `57ffe2c15afa53361ce9da03a834ce282933476a419a0590fbf588e4d1e87c18` |
| 15 | `dibi-curriculum-p4-p6-wk07` | 6541 | `de5101641aca6c468ead2e3926b9c6f7e2424a3e8648e9602eca36de58fe00b8` |
| 16 | `dibi-curriculum-p4-p6-wk08` | 6745 | `dbd50b7608c2d53d1aebca805492d7099d35c1996519c9ae9cd6ed876e35780f` |
| 17 | `dibi-curriculum-s1-s3-wk01` | 6314 | `6e0366aa98452fddac4c2c2d05184e76c60b2ca68e3a7593b4248f27e387ffe7` |
| 18 | `dibi-curriculum-s1-s3-wk02` | 6400 | `66396a85cc5d6257e5a7cd2abb14e6978858c4ee49eda2346fce6a378a10ecb0` |
| 19 | `dibi-curriculum-s1-s3-wk03` | 6647 | `f2a513ef6864fd9bd213bbfe2fd5aaa816d9d2ed56707f47603f4ebfb6d363e9` |
| 20 | `dibi-curriculum-s1-s3-wk04` | 6462 | `f43096693b19e108d460313d542f28b27cae447323421a5520c4b009253703dd` |
| 21 | `dibi-curriculum-s1-s3-wk05` | 6207 | `a21fff8c6e13e9a5b88f243bafddc915806b879515ad4cfceea96c026072dd12` |
| 22 | `dibi-curriculum-s1-s3-wk06` | 6538 | `8fe69704ec4ff50b491a3576a6cb3d6f2d298d95fff187fa378786be650ed172` |
| 23 | `dibi-curriculum-s1-s3-wk07` | 6657 | `0d11c382497bc507503ce7c044f25fc42ac619d2a7f3cd3853141be3aa1f4d2a` |
| 24 | `dibi-curriculum-s1-s3-wk08` | 6861 | `48ee09bfcc658a51ae518fafa48ad57598c88828a908d8002b5088af8a55cff4` |

### 6.2 **關鍵提示**：c1-6 之 8 份 P1–P3 ≠ 本窗 ① 已部署版本

- ①（本窗）部署的是 zip 內 `P1-P3_persona_draft_2026-10-01` 版本；c1-6 交付包之 8 份 P1–P3 為**再修訂**（規則第 5 條由泛稱 Chinese 改為 **`Traditional Chinese (Hong Kong)`**）。
- 逐檔證據：`wk01` 本窗部署版 7,587 B／sha `3c8dc852…` vs 交付包 7,611 B／sha `c912a080…`（其餘 7 份同型，size／sha 皆不同）。
- 故窗 #3 之 repo swap ＋ host 同步，會**覆蓋** ① 已部署之 8 份 → 屬預期（老闆已批方向），**但須計入 manifest 同步與 host 換版範圍**。

---

## 7. 紅線核查（窗 #2 全程）

| 紅線 | 狀態 | 證據 |
| --- | --- | --- |
| 唔做 c1-6 repo swap | ✅ | 本窗 repo 動作僅 ①（8 份 P1–P3 ＋ README manifest）與本 closeout docs；c1-6 交付包 24 檔**未入 repo** |
| 唔改 host（除 ① 授權 persona 複製） | ✅ | host 僅複製 8 份 P1–P3；`other16_changed=0`；16 份 mtime 仍 `2026-09-30 14:18:36 UTC` |
| 唔改 DB（除 `class_curriculum` 8 行授權寫入 ＋ 授權清理） | ✅ | DB 寫入僅 `class_curriculum` 24→32；DELETE 僅 2 條（engine `messages` 8 行／relay `ws_chat_session_map` 1 行，先備份） |
| 唔碰 relay 部署／Caddy／compose／image tag | ✅ | `/etc/caddy/Caddyfile` 未寫入；`docker-compose.yml` mtime 仍 `2026-09-14 11:59:58 UTC`；deeptutor 仍 `hkuds/deeptutor:v1.5.8`（未重建） |
| 唔碰 KB／別 band persona | ✅ | 未動 `topic_metadata`／`knowledge_base`；未動其餘 16 份 persona |
| 禁刪範圍未動 | ✅ | engine `sessions`/`turns`/`turn_events` 孤兒行、relay `ws_chat_relay_audit` 均保留（§3） |
| push ≠ 部署 | ✅ | 所有 repo push 未觸發 host 部署；前端 release 為獨立授權動作 |
| 本 closeout commit docs-only | ✅ | 僅新增本 docs 檔，無 code／persona／config 變更（見 §10 commit stat） |

---

## 8. 待老闆簽核項（窗 #2 結束時仍未結）

| # | 事項 | 現狀 | 待辦 |
| --- | --- | --- | --- |
| S-1 | c1-6 repo swap（24 檔）＋ manifest 同步 | 交付包已核對完成，**未執行** | 老闆原方向「已批」，惟**動手指令**留待窗 #3；動手指令＋Tier 1 async push 授權 |
| S-2 | host 24 份 persona 換版（含覆蓋 ① 之 8 份 P1–P3） | 未執行 | 隨 S-1 同步；需 gate 後執行 |
| S-3 | P1 Smoke 帳號「非零痕跡」狀態（relay audit 441 行仍引本輪 smoke） | 已如實披露 | 如要歸零，須另行簽核（本窗未動 audit） |
| S-4 | engine 孤兒行（`sessions` 1／`turns` 4 等）是否清 | 依令保留 | 如要清，另行簽核 |
| S-5 | 中文輔助段為**簡體普通話書面**（UI 語言 zh-hk） | 非紅備註；c1-6 已改為 `Traditional Chinese (Hong Kong)` 指定 | 由 c1-6 swap 覆蓋解決，無需另立修復 |
| S-6 | 非紅：`PRAGMA foreign_key_check` 既存違規 `classes→users` 1 行 | 與本窗寫入無關，before/after 一致 | 是否納入 D10 技術債清理，待裁 |

---

## 9. 交接（→ 窗 #3 trial 窗）

窗 #2 至此收口。窗 #3 之 trial 窗動作清單、證據座標、紅線繼承與首條指令範本，見本輪交付之
`win3_newchat_handover_2026-10-01.md`（output 單一 md，供開新 chat 接手）。

---

## 10. 證據座標匯總

### 10.1 repo 座標

| 項目 | 值 |
| --- | --- |
| repo | `C:\Users\DreamerAIEdu\Github\dreamer-agent-sandbox`（branch `main`） |
| 前期 docs 追加 | commit `024a0f8`（Tier 0 docs：D7 append §10 ＋ D6 known gap 回填） |
| ① persona 重換 | commit `27a0bd611e245becc58c967d5c31f45015e07a50`；CI run **`36858251252`**（success，7/7） |
| 本 closeout | 本檔 commit（見 push 回報：`docs: window2 closeout v1.0`） |
| CI（本 closeout） | 見 push 後回報之 run id／結論 |

### 10.2 host 備份座標

| 用途 | 座標 |
| --- | --- |
| ① persona 重換（before） | `/root/dreamer_personas_backup_20261001T115729Z/`（24 行 before sha ＋ 目錄快照 ＋ 8 份 .bak） |
| ② 第一次清 session | `/root/win2f2_purge_backup_20261001T112213Z/` |
| ③ 前端 release（before） | `/root/dreamer-web-backup/20261001T113848Z/` |
| ①-b DB 寫入（before/after） | `/backup/win2f-20261001T102027Z/`（`dreamer.db`、`dreamer.db.after`、`write_receipt.json`、`shas.txt`） |
| ②-b 本輪 smoke 清理 | `/root/win2_closeout_purge_backup_20261001T131626Z/`（engine／relay pre 快照 ＋ sha ＋ pre_state_*.txt） |

### 10.3 工作報告座標（workspace `output/`，受 `.gitignore` 忽略）

- `win2_closeout_c2c3_report_20261001.md`（②③ 格）
- `win2_c13_persona_swap_A_B_report_2026-10-01.md`（① 格 A/B 全鏈）
- `win2_D678_round2_report_20261001.md` ＋ `win2_D678_r2_frames.txt` ＋ 4 張截圖（④⑤ 格）
- `win2_final_DB_write_report_20261001.md`（①-b DB 寫入段）
- `c1-6_manifest_2026-10-01.md`（c1-6 交付包 24 slug ＋ sha256）

### 10.4 伺服器座標

- VPS `188.34.199.238`（root）；relay 容器 `dreamer-api`（庫 `/data/dreamer.db`）；engine 容器 `dreamer-deeptutor`（image `hkuds/deeptutor:v1.5.8`，庫 `/app/data/user/chat_history.db`）；host personas `/opt/dreamer/deeptutor/user_data/workspace/personas/`。

*（本檔為窗 #2 收尾紀錄，Tier 0 docs-only。）*
