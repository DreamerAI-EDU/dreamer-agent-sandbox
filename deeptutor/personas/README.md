# D6 persona 定稿包（O-4 已批）· 2026-09-29

- 內容：16 份英文課程 persona（P4-P6 × 8 週＋S1-S3 × 8 週）＋8 份 P1-P3 placeholder stub。
- 格式來源：老闆 Word 檔《Dibi prompt and rubric.docx》（General instructions／Outcomes／Agenda steps 結構）。
- 內容來源：8 份 pinned 課程 md（`curriculum-wk01~08`，LF sha256 gate 已 8/8 復算）；每週嘅 citizenship 主題、任務、outcomes、rubric 0-3 描述符**照錄原文**，冇自由發揮。
- 狀態：**16 份英文 persona 老闆已批（2026-09-29）**，成為 c1-2 嘅呈審基準；本包 hash 即 c1-2 before 值。
- **c1-4 修訂（2026-09-30）**：16 份英文 persona 已於 `How I Run This Week` 之後加入 `How I Reply (Format Rules — Follow Every Time)` block（16 份逐字一致；第 3 條並載 8（P4-P6）／12（S1-S3））。**本 manifest 16 個新 hash 即 c1-4 after 值**；c1-2 before 值見 git 歷史（c1-2 commit 版本）。
- **c1-5 修訂（2026-09-30）**：16 份英文 persona 嘅 `How I Reply (Format Rules — Follow Every Time)` block 由 `How I Run This Week` 之後**移到檔頭**（檔標題＋band note 之後嘅第一節——prompt 越前越服從），並**刪除**原插入位置嘅同一節，故每檔 `## How I Reply` 恰 1 份；第 3 條 band 改載**單一數字**（P4-P6 檔＝8、S1-S3 檔＝12，唔再並列）；新增 `Here is an example of how I reply:` worked example（純文字、5 行、`1.`/`2.`/`3.` 每行一個任務、收尾一句問句、全段零 markdown 符號）＋結尾自檢行`Before sending, check: no ##, no **, no - bullets, ≤N lines, only this week.`。根因依據：smoke ① RED＝slug 正確（relay audit id 398 實發 `dibi-curriculum-p4-p6-wk01`）但模型不服從格式規則，故以「規則前置＋示範＋自檢」三件加強。一致性：P4-P6 8 份互相逐字一致、S1-S3 8 份互相逐字一致，兩組**只差 band 數字**（8／12）。**本 manifest 16 個新 hash 即 c1-5 after 值**（c1-4 值見 git 歷史 2972ccb）。
- **c1-6 修訂（2026-09-30）· L2 正文去 markdown**：16 份英文 persona 嘅**正文**（`Who I Am` 之後全部，即 `## Who I Am` 至檔尾）去 markdown——`**bold**` 去星號、`##`/`###` 標題改純文字行、`- ` bullet 改 `1.` `2.` 編號行（rubric 項目改 `3 — …` 純文字）、`---` 移除、`*italic*` 去星號；**資訊零刪減**（以「去標記正規化內容」逐檔對比 pre-L2 備份，16/16 零漂移；行數逐檔不變）。順手修 L37/L26 行文矛盾：`How I Run This Week` 第 2 步改寫為「one task per turn（一個 turn 一個 task、一行一個 task）＋等學生答＋問該 task 反思問題」，並明寫 `One task per turn and one task per line are what keep the reply inside the N-line limit`（P4-P6 檔＝8、S1-S3 檔＝12），與檔頭第 3 條行數上限自洽。**檔頭格式 block（`## How I Reply`＋worked example＋自檢行）逐字凍結**，只 band 數字（8／12）。改後正文符號計數：`**`＝0、`## `＝0、`- `＝0、`---`＝0；全檔僅餘檔頭 block 自身 1 個 `## ` 標題（必要）＋2 個 `**`（規則 1 與自檢行嘅符號舉例，屬規則文字本身）。**本 manifest 16 個新 hash 即 c1-6 after 值**（c1-5 值見 git 歷史）。
- 中文版（`reference/中文參考版.md`）：老闆裁決（2026-09-29）——**做正式課程文件**（繁體為準；簡體中國市場要用時再轉）。粵語版唔需要，已移除。
- P1-P3 stub 按 v0.3 §4.5：佔位、**relay 不接线**、內容 TO BE AUTHORED。

## 結構

```
personas/
  dibi-curriculum-p4-p6-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-s1-s3-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-p1-p3-wk01..wk08/PERSONA.md   ← placeholder（8，不接线）
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
- 設計備註：S1-S3 版按年齡調校（聲線／oral 1-3 分鐘／中文 100-150 字／追問式）；Week 4-8 任務詳細 prompt template 喺各週 mission sheet（pinned md）度，persona 指向佢哋而唔內嵌。

## 檔案 manifest（LF sha256）

| 檔 | bytes | sha256 |
|---|---|---|
| `personas/dibi-curriculum-p1-p3-wk01/PERSONA.md` | 910 | `5bc8acc5e2932954e4131f7d540c3c22f308abc25d64cbd7f1b863b0c77e233a` |
| `personas/dibi-curriculum-p1-p3-wk02/PERSONA.md` | 910 | `5ccd3cb245cb720651b8913e040100ed0025fe9cec629cfdd1097c1b99fd3be9` |
| `personas/dibi-curriculum-p1-p3-wk03/PERSONA.md` | 910 | `03befa13c466dc79701829567467dccf4417e432df57c0a0eb39f76a12dbb406` |
| `personas/dibi-curriculum-p1-p3-wk04/PERSONA.md` | 910 | `d04a0fc95c1dd2e8e31c943167e3fbfbafbcf71ce3d56c989841ea78b816ac5c` |
| `personas/dibi-curriculum-p1-p3-wk05/PERSONA.md` | 910 | `54fe56c366e008ba1a6eeb01d8fee001a8e8a1bd62c002a020496658b355c646` |
| `personas/dibi-curriculum-p1-p3-wk06/PERSONA.md` | 910 | `9564c15ef8d093f7e33e045f41ec71843fc694f8f7a69cf586d34b5030b260bb` |
| `personas/dibi-curriculum-p1-p3-wk07/PERSONA.md` | 910 | `05869ee7b3299385e86ff78c38120bbe9de5e9c9bf9e467c95f668f15bfcdad0` |
| `personas/dibi-curriculum-p1-p3-wk08/PERSONA.md` | 910 | `9cbc5af51a179789d1ffdfab9dd63caed1373beacd3f9947b7911e7706547989` |
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 5638 | `570e00af4acd9ceae396a2832989e686013d0036ffc660981086065d2eddd723` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 5724 | `6b58951fc16d4938efec58a4895a847cf6d6d8e1eb74326175c97674645d7d8b` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 5971 | `f6cbaef0c528101f62a0626a3f547f45e13703aeb23b9c3aad3a081f440cae0c` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 5786 | `7806423d52dc51a1d4445fb8e6f760722425a459ad6d436ce327885c97600854` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 5531 | `ae9f0eeb03691dcd8b4cfda22d30c1fe651b2c646c4401fd67485d9fd2159fc0` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 5862 | `9d1b6e41f9e9beeff0b6e68ebfad6c1bfb35eee223282c372deceb68b86fcc34` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 5981 | `96eb6603397f7f8c9cdf97174e90b13905415738f8db8fd254a6c00d4709778a` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 6185 | `dbed75c93fc67e847843c8628c8d306262c2124de445fd58d9ffe3df49f1cbf7` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 5754 | `b346db9a2e5ee8fcf0d035d657cc38ef1dec238055b9e5277aff0b964f8485c6` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 5840 | `12d4715360346da594789c6f016592933f91958f7f2df2ed2d07c0d72c1696c9` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 6087 | `50e7790e3c24438c8239b22d6c32eedbe61c1c3afb9fc3c634bcb4b8f5990181` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 5902 | `56e5feabe12b25a9bd3f115966ab3ca8ebd2ccb9390a5a72ca7673f3df626477` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 5647 | `57624b5e45c0bcb6aab93663830d9099cbd5367e1a62f1f8b9def2c9d13d0223` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 5978 | `1bf921e7d379c19098b1799f27f5b5d24667999f8edc830cfe987ed140be39aa` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 6097 | `74b030ff97612d7187385f19e4427d7ff3ea6a81f1478d4b28d355dd229d5256` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 6301 | `2262e409ecc984334648e08ea93de4fe2169578541607fa20c92ca78ef22793e` |
| `reference/中文參考版.md` | 23511 | `464a58d5bce54031b9723f76498abbe88e90f7c7fe77d1333334ae88bb887e15` |

---
*D6 persona 定稿包 · 2026-09-29 · 16 份英文 persona 老闆已批 · 中文版＝正式課程文件（繁體為準）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
