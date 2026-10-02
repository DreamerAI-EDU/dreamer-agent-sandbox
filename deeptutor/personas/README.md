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
- **本 manifest 24 個 hash 即 c1-7 v2 after 值**（2026-10-02 評審後重凍；c1-7 v1／c1-6 值見 git 歷史）。
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

## 檔案 manifest（LF sha256）· c1-7 **v3** 值（2026-10-02，script pin 後重凍）

| 檔 | bytes | sha256 |
|---|---|---|
| `personas/dibi-curriculum-p1-p3-wk01/PERSONA.md` | 7765 | `a895162ac583da73b4856ad45c06e4b713be473f8054d86f7b57e67ecb9f49f9` |
| `personas/dibi-curriculum-p1-p3-wk02/PERSONA.md` | 7932 | `638abdbf066c1a19618cb529052ee6a66a0c9f82a51f5c8027f309b8818cacfc` |
| `personas/dibi-curriculum-p1-p3-wk03/PERSONA.md` | 8040 | `77d0de6a2e886cf7aa451e1a802c36e58ab2fca4796ce5da54670c93d501026e` |
| `personas/dibi-curriculum-p1-p3-wk04/PERSONA.md` | 7952 | `0bdfe3c4abe447a33fe4728fe173588150291ed0adba8ada5da5238e124ebac2` |
| `personas/dibi-curriculum-p1-p3-wk05/PERSONA.md` | 8104 | `f21ce1369e60d7eabee95f5af5e6c385557eadc4c55b882429e9fa2e469cb492` |
| `personas/dibi-curriculum-p1-p3-wk06/PERSONA.md` | 8254 | `94e5a13ba1df5a9bba7589667e34bc11709f86f0b6ef3cbe6cff1dae59fb4c3e` |
| `personas/dibi-curriculum-p1-p3-wk07/PERSONA.md` | 8704 | `b8d79fb9f43b3a109f0ca6dbeb9bb5b6e4550c9de57477b476bd7f529f48bcb6` |
| `personas/dibi-curriculum-p1-p3-wk08/PERSONA.md` | 8364 | `e0d5e38ddd3e3d747c9773697a950b314d461c9c79ebf9d869853382482bedbe` |
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 6549 | `2d6e9f39b8c4ba56c781bf65608799a63f1dade4ab68a47f69d1c054fee2b94f` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 6635 | `37bf882cf41b45b778e93ce25673ecc1ecdbf1a056332a54f01711d4a0e1a416` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 6882 | `45ea0ddccb2294bf35064afe916266049a6a6a0768e3fae67c7120dff5f157f6` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 6697 | `0c1719b28955c07ab0261ae221b9109c670203a05f0f6168628a08f20e63555d` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 6442 | `f46f97da613069a1b6b6fc0acd37e0f2e947404d9c9cc2f7a23e6f85e2d4cd55` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 6773 | `5f27e1f7631e0971c3695361158e7703d0c6468dc6d4e080782fc2d7108e0ba3` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 6892 | `4af0ef971645b7cf6038e8c0504a22036b37dcfee674519e99a937cf70c6a926` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 7096 | `105e811542ccbfd42b2c80745e7c0728b905c3566aa56239c56e9d6fefe661e7` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 6662 | `2dc31f37b7e86dcc2a44d1b03aebe5c788ae95f3a2b9c053f95a385bd89eecdf` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 6748 | `169dfbf7c9baf4ffdebc9bfa8312387c4ccf26373dbfd1476c9440474e3647a6` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 6995 | `2f464a2c6f487d382b6ca01c92a28494543894c340b0bab59ab90bd31eba32a7` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 6810 | `38e9eb681044913b4199d70c92ad66a15b9924910c713d856656e494d7f637ea` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 6555 | `f60813686ae7fb86ec8d576ef7ba809b3d0df03e38e03a0207166ceac4b02141` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 6886 | `933693fc04183159fb0647eb5ac1e816078bb2d8b65147932b47a9702a022106` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 7005 | `9a0291b007483a928109457431b4081e2effcee10cc3010df97c2856d13de387` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 7209 | `530ea7808d5041b58ea94876fb713f7c3b43740ecdbdc04709196dd88dbede5f` |
| `reference/中文參考版.md` | 23511 | `464a58d5bce54031b9723f76498abbe88e90f7c7fe77d1333334ae88bb887e15` |

---
*D6 persona 定稿包 · 2026-09-29 · c1-7 英文專線修訂 2026-10-02（老闆三指令）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
