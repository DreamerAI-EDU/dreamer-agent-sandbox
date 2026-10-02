# D6 persona 定稿包（O-4 已批）· 2026-09-29

- 內容：24 份課程 persona —— 16 份英文（P4-P6 × 8 週＋S1-S3 × 8 週）＋8 份 P1-P3（雙受眾：細路識複述嘅一句＋`Grown-up:` 一句；內含中文示例句，屬設計一部分）。
- 格式來源：老闆 Word 檔《Dibi prompt and rubric.docx》（General instructions／Outcomes／Agenda steps 結構）。
- 內容來源：8 份 pinned 課程 md（`curriculum-wk01~08`，LF sha256 gate 已 8/8 復算）；每週嘅 citizenship 主題、任務、outcomes、rubric 0-3 描述符**照錄原文**，冇自由發揮。
- 狀態：**16 份英文 persona 老闆已批（2026-09-29）**，成為 c1-2 嘅呈審基準；8 份 P1-P3 正稿（`2026-10-01` 閘門起草）由 c1-3 落地 repo，**待老闆簽批**。
- **c1-4 修訂（2026-09-30）**：16 份英文 persona 已於 `How I Run This Week` 之後加入 `How I Reply (Format Rules — Follow Every Time)` block（16 份逐字一致；第 3 條並載 8（P4-P6）／12（S1-S3））。**本 manifest 16 個新 hash 即 c1-4 after 值**；c1-2 before 值見 git 歷史（c1-2 commit 版本）。
- **c1-5 修訂（2026-09-30）**：16 份英文 persona 嘅 `How I Reply (Format Rules — Follow Every Time)` block 由 `How I Run This Week` 之後**移到檔頭**（檔標題＋band note 之後嘅第一節——prompt 越前越服從），並**刪除**原插入位置嘅同一節，故每檔 `## How I Reply` 恰 1 份；第 3 條 band 改載**單一數字**（P4-P6 檔＝8、S1-S3 檔＝12，唔再並列）；新增 `Here is an example of how I reply:` worked example（純文字、5 行、`1.`/`2.`/`3.` 每行一個任務、收尾一句問句、全段零 markdown 符號）＋結尾自檢行`Before sending, check: no ##, no **, no - bullets, ≤N lines, only this week.`。根因依據：smoke ① RED＝slug 正確（relay audit id 398 實發 `dibi-curriculum-p4-p6-wk01`）但模型不服從格式規則，故以「規則前置＋示範＋自檢」三件加強。一致性：P4-P6 8 份互相逐字一致、S1-S3 8 份互相逐字一致，兩組**只差 band 數字**（8／12）。**本 manifest 16 個新 hash 即 c1-5 after 值**（c1-4 值見 git 歷史 2972ccb）。
- **c1-6 修訂（2026-09-30）· L2 正文去 markdown**：16 份英文 persona 嘅**正文**（`Who I Am` 之後全部，即 `## Who I Am` 至檔尾）去 markdown——`**bold**` 去星號、`##`/`###` 標題改純文字行、`- ` bullet 改 `1.` `2.` 編號行（rubric 項目改 `3 — …` 純文字）、`---` 移除、`*italic*` 去星號；**資訊零刪減**（以「去標記正規化內容」逐檔對比 pre-L2 備份，16/16 零漂移；行數逐檔不變）。順手修 L37/L26 行文矛盾：`How I Run This Week` 第 2 步改寫為「one task per turn（一個 turn 一個 task、一行一個 task）＋等學生答＋問該 task 反思問題」，並明寫 `One task per turn and one task per line are what keep the reply inside the N-line limit`（P4-P6 檔＝8、S1-S3 檔＝12），與檔頭第 3 條行數上限自洽。**檔頭格式 block（`## How I Reply`＋worked example＋自檢行）逐字凍結**，只 band 數字（8／12）。改後正文符號計數：`**`＝0、`## `＝0、`- `＝0、`---`＝0；全檔僅餘檔頭 block 自身 1 個 `## ` 標題（必要）＋2 個 `**`（規則 1 與自檢行嘅符號舉例，屬規則文字本身）。**本 manifest 16 個新 hash 即 c1-6 after 值**（c1-5 值見 git 歷史）。
- **c1-6 語言刷新（2026-10-01）· English-first（trial 窗部署）**：24 份 persona 全量替換 —— 16 份（P4-P6／S1-S3）規則加第 5 條 `English first, always`（學生唔明先以繁體中文（香港）翻譯／解釋，之後返英文）＋band 註腳、自檢行、教學法第 3 點同步；8 份 P1-P3 第 5 條 `Chinese` → `Traditional Chinese (Hong Kong)`。**本 manifest 24 個 hash 即 c1-6 語言刷新 after 值**（16 前值見 c1-6 L2、8 前值見 c1-3）。
- 中文版（`reference/中文參考版.md`）：老闆裁決（2026-09-29）——**做正式課程文件**（繁體為準；簡體中國市場要用時再轉）。粵語版唔需要，已移除。
- **c1-3 修訂（2026-10-01）**：8 份 P1-P3 正稿（`dibi-curriculum-p1-p3-wk01..08`）由閘門交付包 `P1-P3_persona_draft_2026-10-01` **全文替換** c1-3 前嘅佔位內容（每檔 74–75 行；雙受眾設計＝先一句細路識複述嘅簡單英文，再一句 `Grown-up:` 指示大人；檔頭格式規則 ≤8 行、逐行編號、只講當週、結尾一條問題；每週任務掛 cue card）。本 band **內容含中文示例句（設計如此）**，故「英文 only」內容 pin 只適用 P4-P6／S1-S3，本 band 內容 pin＝hash。同批：relay 接線（`_CURRICULUM_ROUTE_BANDS` 加 `p1-p3`，slug 白名單 16→24）＋前端解除「My AI Course」掣遮蔽。**本 manifest 8 個新 hash 即 c1-3 after 值**（舊值見 git 歷史）。
- P1-P3 佔位檔（v0.3 §4.5）已於 c1-3 退役：本目錄唔再持有任何未填內容檔。

## 結構

```
personas/
  dibi-curriculum-p4-p6-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-s1-s3-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-p1-p3-wk01..wk08/PERSONA.md   ← c1-3 上线（8，已接线）
```

## 每檔統一骨架

1. **Who I Am**（身份＋band 聲線：P4-P6 簡單短句多鼓勵；S1-S3 同輩式、追問深度、連社會時事）
2. **How I Run This Week**（Citizenship Minute → 任務逐個 → 雙語設計 → F2F 交接 → rubric 0-3 意識）
3. **This Week's Mission**（Goal＋4 任務一行式＋指向該週 mission sheet 取 exact prompt templates）
4. **Outcomes**
5. **Weekly Rubric (0-3)**（原文照錄）
6. **Boundaries — Never Break These**（只教本週／唔准幻補／Dreamer language only（IB 字眼禁止）／私隱／AI 可以錯／band 特定紀律）

## 老闆審稿紀錄（2026-09-29）

- ✅ 16 份英文 persona **已批**（本包 hash 為 c1-2 呈審 before 基準，任何後續改動即觸發 HC-F 雙 hash）。
- ✅ 中文版＝正式課程文件（繁體為準；簡體轉換屆時一鍵處理）。
- ⏳ 8 份 P1-P3 正稿（c1-3，`2026-10-01` 閘門起草）**待簽批**。
- 設計備註：S1-S3 版按年齡調校（聲線／oral 1-3 分鐘／中文 100-150 字／追問式）；Week 4-8 任務詳細 prompt template 喺各週 mission sheet（pinned md）度，persona 指向佢哋而唔內嵌。

## 檔案 manifest（LF sha256）

| 檔 | bytes | sha256 |
|---|---|---|
| `personas/dibi-curriculum-p1-p3-wk01/PERSONA.md` | 7611 | `c912a0804cb7ff1f0bd6c554a54374a4ddbd7cf0ec685a5330ad804d2909593f` |
| `personas/dibi-curriculum-p1-p3-wk02/PERSONA.md` | 7689 | `1ab8679ebd6a753959e5ba57274a8fc9c298cd6a9ab884f1f4ef98dcf5da79a1` |
| `personas/dibi-curriculum-p1-p3-wk03/PERSONA.md` | 7893 | `ce3917e931a34e6286cfe0c89625ec8cb00a29d949dd17d9f5d7f559a3735563` |
| `personas/dibi-curriculum-p1-p3-wk04/PERSONA.md` | 7733 | `e5d4deba125b2df81c46c2051dc5d3c6f6009a2b8ba10a2a914740e19d3d726e` |
| `personas/dibi-curriculum-p1-p3-wk05/PERSONA.md` | 7850 | `9017582a4c07042fe31bef20a66da980adfb3c69f7d14be2ea4c22d3f61b8f30` |
| `personas/dibi-curriculum-p1-p3-wk06/PERSONA.md` | 8065 | `c6ef7802ea14fb1d5683623672662163d1f79238698e3b101fac4bb7419411d0` |
| `personas/dibi-curriculum-p1-p3-wk07/PERSONA.md` | 8560 | `63b94fee7e89daa4a6320c3c66ca16c45be49eae0281006504377eee3b1177d6` |
| `personas/dibi-curriculum-p1-p3-wk08/PERSONA.md` | 8118 | `59c0d764074e8fe8bec49a0d25bafefd3959caff8b440359477257ad21634f63` |
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 6198 | `965889799f31038f93a5639d60c9956b7f3bcd2647961032fefb72d9ae380fc0` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 6284 | `63b77b7429537cea459fbcb6d5df512ba22d7dbd30695df9b594d63b743dca36` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 6531 | `e0ef4280fffe12aac542a21aadba8ca83491b4d11d1b62603bb5decdcc8960fa` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 6346 | `ad17894a9bdb58fa3e46c3de19a025379981249f9c13ae4e606f8a6195986d44` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 6091 | `79d42f06ed95998f2638721ac864951a9a199f0506bd0adfe525598fbbcbb7e0` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 6422 | `57ffe2c15afa53361ce9da03a834ce282933476a419a0590fbf588e4d1e87c18` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 6541 | `de5101641aca6c468ead2e3926b9c6f7e2424a3e8648e9602eca36de58fe00b8` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 6745 | `dbd50b7608c2d53d1aebca805492d7099d35c1996519c9ae9cd6ed876e35780f` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 6314 | `6e0366aa98452fddac4c2c2d05184e76c60b2ca68e3a7593b4248f27e387ffe7` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 6400 | `66396a85cc5d6257e5a7cd2abb14e6978858c4ee49eda2346fce6a378a10ecb0` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 6647 | `f2a513ef6864fd9bd213bbfe2fd5aaa816d9d2ed56707f47603f4ebfb6d363e9` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 6462 | `f43096693b19e108d460313d542f28b27cae447323421a5520c4b009253703dd` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 6207 | `a21fff8c6e13e9a5b88f243bafddc915806b879515ad4cfceea96c026072dd12` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 6538 | `8fe69704ec4ff50b491a3576a6cb3d6f2d298d95fff187fa378786be650ed172` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 6657 | `0d11c382497bc507503ce7c044f25fc42ac619d2a7f3cd3853141be3aa1f4d2a` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 6861 | `48ee09bfcc658a51ae518fafa48ad57598c88828a908d8002b5088af8a55cff4` |
| `reference/中文參考版.md` | 23511 | `464a58d5bce54031b9723f76498abbe88e90f7c7fe77d1333334ae88bb887e15` |

---
*D6 persona 定稿包 · 2026-09-29 · 16 份英文 persona 老闆已批 · 中文版＝正式課程文件（繁體為準）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
