# D6 persona 定稿包（O-4 已批）· 2026-09-29

- 內容：24 份課程 persona —— 16 份英文（P4-P6 × 8 週＋S1-S3 × 8 週）＋8 份 P1-P3。**c1-7 起全部 24 份英文 only**（見下）。
- 格式來源：老闆 Word 檔《Dibi prompt and rubric.docx》（General instructions／Outcomes／Agenda steps 結構）。
- 內容來源：8 份 pinned 課程 md（`curriculum-wk01~08`，LF sha256 gate 已 8/8 復算）；每週嘅 citizenship 主題、任務、outcomes、rubric 0-3 描述符**照錄原文**，冇自由發揮。
- 狀態：**16 份英文 persona 老闆已批（2026-09-29）**，成為 c1-2 嘅呈審基準；8 份 P1-P3 正稿（`2026-10-01` 閘門起草）由 c1-3 落地 repo，**待老闆簽批**。
- **c1-7 修訂（2026-10-02）· 英文專線（老闆三指令）**：24 份 persona 全量修訂 ——
  1. **English ONLY**：廢除 c1-6 語言刷新嘅「English first → 繁體中文翻譯 → 返英文」條款（規則第 5 條、band 註腳、自檢行、教學法第 3/4 點同步）；新第 5 條＝`English only, always.`（學生用中文輸入或話唔明，都只用更簡單英文再講，永遠唔轉語言）。**評審缺口 1 修復（v2）**：第 5 條加入唯一例外條款——每週 Chinese writing task 嘅中文句子／模板／標籤保持中文（學生要抄嘅產出），其餘全部英文；band 註腳、自檢行同步（自檢行＝`English only (Chinese writing task excepted)`）。**裁決 #1（中文助手功能）隨 c1-7 作廢；如再有真衝突，先至移除中文助手**。
  2. **P1-P3 去除 grown-up 對話場景**：8 份 P1-P3 廢除雙受眾設計（細路一句＋`Grown-up:` 一句）；所有 `Grown-up types/reads/asks...` 改為學生視角（Dibi 直接向細路講；typing/材料指向 teacher／mission sheet）；`How I Run` 第 3 點「cue cards stay offline」保留（cue card 實體材料本來就屬線下課）；Boundary 5 改為「Typing is for the offline lesson」；grown-up 僅存於(a) band 註腳「grown-up's part — offline」、(b) 安全規則「tell your grown-up right now」。**裁決 #3（P1-P3 雙受眾）隨 c1-7 作廢**。
  3. **長回覆唔截斷**：廢除「≤N 行截斷＋Would you like me to continue?」條款；新第 3 條＝內容多可 split 最多 3 段（空行分隔）、point-form 每點新行；第 4 條 one task per turn / one task per line 保留（可讀性，唔再掛行數上限）；自檢行同步（冇 `≤N lines`）。**評審缺口 2 修復（v2）**：P1-P3 採專屬第 3 條——`Short replies that never cut content`（每回覆幾句極簡單、細路可以複述嘅行；內容多就分段，但永遠唔截內容），解決同 band 註腳「keep every reply short」＋規則 4 嘅對撞；16 份 band 檔維持通用版。**裁決 #4 行數上限條款修訂**。
- 根因：T-4 smoke 發現「解釋完返英文」紅＋T-4x 發現觸發不穩定 —— 老闆裁定方向錯（T-4y 停止），改行 c1-7 直接廢除中文助手功能。T-4/T-4x 兩紅隨功能移除而關閉。
- **本 manifest 24 個 hash 即 c1-10 值**（2026-10-03 tone pack 後重凍；c1-7 v3／v2／v1、c1-6 值見 git 歷史）。
- **c1-7 v3 補記（2026-10-02）**：script pin 後重凍，隨 `73d769a` 落地——24 檔每檔 +48 bytes（檔案尾 append script pin 行）；handover 漏記，c1-11 補返文件鏈。
- **c1-10 修訂（2026-10-03）· tone pack**：24 份 curriculum persona 校準回饋語氣同週次儀式——A 第 6 條 feedback sandwich（P1-P3 用 Praise sandwich 版）／B `Here is an example of how I reply:` 之後加回饋示範小例／C 自檢行追加 `feedback sandwich when work is shared`／D `How I Run This Week` 加 3 點（Open the week warmly、coach by modelling not correcting、Close the week）。manifest 重凍為 c1-10 值（老闆 2026-10-03 批，commit `9b31436f`）。
- **c1-4 修訂（2026-09-30）**：16 份英文 persona 已於 `How I Run This Week` 之後加入 `How I Reply (Format Rules — Follow Every Time)` block（16 份逐字一致；第 3 條並載 8（P4-P6）／12（S1-S3））。**c1-4 after 值**已過期，見 git 歷史。
- **c1-5 修訂（2026-09-30）**：16 份英文 persona 嘅 `How I Reply (Format Rules — Follow Every Time)` block 由 `How I Run This Week` 之後**移到檔頭**，並**刪除**原插入位置嘅同一節；第 3 條 band 改載**單一數字**（P4-P6＝8、S1-S3＝12）；新增 `Here is an example of how I reply:` worked example＋結尾自檢行。根因：smoke ① RED＝slug 正確但模型不服從格式規則。已過期，見 git 歷史。
- **c1-6 修訂（2026-09-30）· L2 正文去 markdown**：16 份英文 persona 正文去 markdown（資訊零刪減；**檔頭格式 block 逐字凍結**）。已過期，見 git 歷史。
- **c1-6 語言刷新（2026-10-01）· English-first**：24 份規則第 5 條 English first（唔明先繁體中文翻譯/解釋再返英文）。**已於 c1-7 全數廢除**（老闆 2026-10-02 指令：English only, always）。
- 中文版（`reference/中文參考版.md`）：老闆裁決（2026-09-29）——**做正式課程文件**（繁體為準；簡體中國市場要用時再轉）。粵語版唔需要，已移除。
- **c1-3 修訂（2026-10-01）**：8 份 P1-P3 正稿落地 repo（雙受眾設計）。**c1-7 已改為單受眾（學生）**，雙受眾版本見 git 歷史。
- P1-P3 佔位檔（v0.3 §4.5）已於 c1-3 退役。

## 結構

```
personas/
  dibi-curriculum-p4-p6-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-s1-s3-wk01..wk08/PERSONA.md   ← v1 上线（8）
  dibi-curriculum-p1-p3-wk01..wk08/PERSONA.md   ← c1-3 上线；c1-7 改單受眾英文專線（8，已接线）
```

## 每檔統一骨架

1. **Who I Am**（身份＋band 聲線）
2. **How I Reply (Format Rules — Follow Every Time)**（檔頭：格式＋English only＋分段規則＋worked example＋自檢行）
3. **How I Run This Week**（Citizenship Minute → 任務逐個 → 中文產出設計 → F2F 交接 → rubric 0-3 意識）
4. **This Week's Mission**（Goal＋4 任務＋指向該週 mission sheet 取 exact prompt templates）
5. **Outcomes**
6. **Weekly Rubric (0-3)**（原文照錄）
7. **Boundaries — Never Break These**（只教本週／唔准幻補／Dreamer language only／私隱／AI 可以錯／offline typing／安全）

## 老闆審稿紀錄（2026-09-29）

- ✅ 16 份英文 persona **已批**（c1-2 呈審基準；後續改動觸發 HC-F 雙 hash）。
- ✅ 中文版＝正式課程文件（繁體為準）。
- ⏳ 8 份 P1-P3 正稿 **待簽批**。
- 設計備註：S1-S3 版按年齡調校（聲線／oral 1-3 分鐘／中文 100-150 字／追問式）；Week 4-8 任務詳細 prompt template 喺各週 mission sheet（pinned md）度。

## 檔案 manifest（LF sha256）· c1-10 值（2026-10-03，tone pack 後重凍）

| 檔 | bytes | sha256 |
|---|---|---|
| `personas/dibi-curriculum-p1-p3-wk01/PERSONA.md` | 9330 | `9b03228c986d6b7ed20c5511a9d27a985fe520b50dd7a8e7e708f6794dfbe0ac` |
| `personas/dibi-curriculum-p1-p3-wk02/PERSONA.md` | 9497 | `992246d1b2f5dcb1a6be8d6eb32ed7fe89b193ac40fc4707ee5b46384b6f7c6e` |
| `personas/dibi-curriculum-p1-p3-wk03/PERSONA.md` | 9605 | `3e890babfb966e39317c9e3059d1525ae8a10bbe09f308237fc1aef775498c2d` |
| `personas/dibi-curriculum-p1-p3-wk04/PERSONA.md` | 9517 | `c9131930bf0420f8a6b5af18faf221248d5ccf24e78f3a1f3628e5fb058508d2` |
| `personas/dibi-curriculum-p1-p3-wk05/PERSONA.md` | 9669 | `e22c4a4bce33972b9197625ebdf6b21b28c7af0844eedc060fab4f262cb53bbc` |
| `personas/dibi-curriculum-p1-p3-wk06/PERSONA.md` | 9819 | `9c17ea5bd392e371104fab8dc4e204730b90d22ea03057387826c6bcf69c780d` |
| `personas/dibi-curriculum-p1-p3-wk07/PERSONA.md` | 10269 | `22d743a8d4a9f698a624b51c9945c48cff1b1507fc195bb6333895846b45a8b8` |
| `personas/dibi-curriculum-p1-p3-wk08/PERSONA.md` | 9929 | `f694912ec485ed1579ed0330050221b068fedaa091d70bef22dabdbc3ef59a04` |
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 8361 | `98ad52b38956882c81c6c22bece7aea0c0c14c0e2a5a9a3e07273ecc0856819e` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 8447 | `31320196cd9a70bc446e66f58c40be4f7bf0a54dc4c9d11fa32f97b414cfa5d9` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 8694 | `84fe31f5f16fb880fb4ad8f49f1d705949702b27a2d3a3a6c0319d5f56c33738` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 8509 | `93669fc0b7594a3a519686c69392f7bffbe273693535048e858dc78705fd87ab` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 8254 | `bf7fbb75006c4deab1830925e03948a92ec8cbea714f4a468641537de827040a` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 8585 | `b6fca7822c6f89bac4c6ad0d281c311c477d4bbcd3767739fd048f014d99c7eb` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 8704 | `00bd6353b8f147d1c4e517571870db0358e10b56e4331a5318ce7250552973ed` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 8908 | `0a31ade24c51d37d4a1b08a0def68b701c89f29dfeb9e51b70af014421f7051f` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 8193 | `7498da2b33262c77fbab46027167ecec242528f7e5bf686cdd00acb6c53c6218` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 8279 | `a512a53898841e4fd359f5c9d4c511d2c55f7c55f22e2d072d18db7784929640` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 8526 | `48f9a559909e7c5590133e175ece2f7b4b4eb92e31e3f2314402f5a323272d25` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 8341 | `1a6e13529b94820c3a32e4eee92d693df99996f13fafe4cdc710497851114945` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 8086 | `114f4e686bce603ee1d624e65e7992a36de47e105ef7d452ddf588d8f7d94498` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 8417 | `bd4e941a49b1f4c48aa0c4b059c93cbd97e9973e4fd22d5f0472bfd6a1e42597` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 8536 | `5ebce008bb6e5601868858c8a41cea813283c4b6aa3dad3a9eb0047b0dc066b6` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 8740 | `54cfdb8607558f22af6b10e1d3cd5c5ea0cdd03b009c3156ebe53d125943e9a1` |
| `reference/中文參考版.md` | 23511 | `464a58d5bce54031b9723f76498abbe88e90f7c7fe77d1333334ae88bb887e15` |

---
*D6 persona 定稿包 · 2026-09-29 · c1-7 英文專線修訂 2026-10-02（老闆三指令）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
