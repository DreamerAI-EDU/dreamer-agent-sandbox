# D6 persona 定稿包（O-4 已批）· 2026-09-29

- 內容：16 份英文課程 persona（P4-P6 × 8 週＋S1-S3 × 8 週）＋8 份 P1-P3 placeholder stub。
- 格式來源：老闆 Word 檔《Dibi prompt and rubric.docx》（General instructions／Outcomes／Agenda steps 結構）。
- 內容來源：8 份 pinned 課程 md（`curriculum-wk01~08`，LF sha256 gate 已 8/8 復算）；每週嘅 citizenship 主題、任務、outcomes、rubric 0-3 描述符**照錄原文**，冇自由發揮。
- 狀態：**16 份英文 persona 老闆已批（2026-09-29）**，成為 c1-2 嘅呈審基準；本包 hash 即 c1-2 before 值。
- **c1-4 修訂（2026-09-30）**：16 份英文 persona 已於 `How I Run This Week` 之後加入 `How I Reply (Format Rules — Follow Every Time)` block（16 份逐字一致；第 3 條並載 8（P4-P6）／12（S1-S3））。**本 manifest 16 個新 hash 即 c1-4 after 值**；c1-2 before 值見 git 歷史（c1-2 commit 版本）。
- **c1-5 修訂（2026-09-30）**：16 份英文 persona 嘅 `How I Reply (Format Rules — Follow Every Time)` block 由 `How I Run This Week` 之後**移到檔頭**（檔標題＋band note 之後嘅第一節——prompt 越前越服從），並**刪除**原插入位置嘅同一節，故每檔 `## How I Reply` 恰 1 份；第 3 條 band 改載**單一數字**（P4-P6 檔＝8、S1-S3 檔＝12，唔再並列）；新增 `Here is an example of how I reply:` worked example（純文字、5 行、`1.`/`2.`/`3.` 每行一個任務、收尾一句問句、全段零 markdown 符號）＋結尾自檢行`Before sending, check: no ##, no **, no - bullets, ≤N lines, only this week.`。根因依據：smoke ① RED＝slug 正確（relay audit id 398 實發 `dibi-curriculum-p4-p6-wk01`）但模型不服從格式規則，故以「規則前置＋示範＋自檢」三件加強。一致性：P4-P6 8 份互相逐字一致、S1-S3 8 份互相逐字一致，兩組**只差 band 數字**（8／12）。**本 manifest 16 個新 hash 即 c1-5 after 值**（c1-4 值見 git 歷史 2972ccb）。
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
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 5611 | `1ae451a2429ec1999f0fac1f0603af98750f77052391c6be978e3c094f272734` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 5697 | `1adefbeb9c7d48154c8868c146d146c3b6511061949a08ec99cf0056db65940b` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 5944 | `6b0aad6ddd29e59d8b1a80bdaf05112966f8b7b8da6ae7df38d43f74db7f4bd2` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 5759 | `8ac754bfac651d9d0919af32cfc6fa31bc3ca5ee26f6cd1d8ae3b0cd8d386016` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 5498 | `44404b20e103d018b362e50c41c0e788dc7ca85b7f871a2fdfc0906dc8965ca0` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 5835 | `831aa625f4ccb524b2517bda821aeee0457a07815dfd0ec78a2c85c6c2597250` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 5954 | `d1835726c32771c5916d8be20367b969ce12fb96957c5acb4629bc2bf283785b` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 6158 | `8eebce05edc92776278cf46ae1f4c011e0f008182f1168b570af5b42e5fa9596` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 5726 | `329c4db9a0f2284a496e98035d6fb3229b3b8f12f823e42f8723d3e53d0685bf` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 5812 | `62eebf6d65af77155189a1be675197b0e9dd952946eb3440391649c18a8ef171` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 6059 | `d2833593982499ff0917f1c3166df87e233f80554f9387703abacf16ac4dc7aa` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 5874 | `d2a46f88700c04dee5acad9545f034cd64e2db5169c92cec180890f95bebe5a6` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 5613 | `bdaf56dff89bcad5aeae2254aa6bf90d4c13a37b8cd15742001f07e57ddcd09e` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 5950 | `e64bf268d91129424ebb20248b997b5904e38b7b9f186df70a45db2f52d016ce` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 6069 | `df1c099e9287a13d9ef6552e668893daed11d2ba385ef32f42e5dd7cd5400111` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 6273 | `ab632e6633c9eb15aef984d0433829dd2f61a1bade4c0f309e476948f01664dc` |
| `reference/中文參考版.md` | 23511 | `464a58d5bce54031b9723f76498abbe88e90f7c7fe77d1333334ae88bb887e15` |

---
*D6 persona 定稿包 · 2026-09-29 · 16 份英文 persona 老闆已批 · 中文版＝正式課程文件（繁體為準）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
