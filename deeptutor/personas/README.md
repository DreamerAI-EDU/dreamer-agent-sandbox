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
- **本 manifest 24 個 hash 即 c1-12 值**（2026-10-03 wk01 scope＋welcome trigger＋fix list＋pacing 後重凍；c1-10／c1-7 v3／v2／v1、c1-6 值見 git 歷史）。
- **c1-7 v3 補記（2026-10-02）**：script pin 後重凍，隨 `73d769a` 落地——24 檔每檔 +48 bytes（檔案尾 append script pin 行）；handover 漏記，c1-11 補返文件鏈。
- **c1-10 修訂（2026-10-03）· tone pack**：24 份 curriculum persona 校準回饋語氣同週次儀式——A 第 6 條 feedback sandwich（P1-P3 用 Praise sandwich 版）／B `Here is an example of how I reply:` 之後加回饋示範小例／C 自檢行追加 `feedback sandwich when work is shared`／D `How I Run This Week` 加 3 點（Open the week warmly、coach by modelling not correcting、Close the week）。manifest 重凍為 c1-10 值（老闆 2026-10-03 批，commit `9b31436f`）。
- **c1-12 修訂（2026-10-03）· 4 組編輯（老闆簽批）**：**(1) wk01 Task 1 範圍還原＋時長**（`p4-p6-wk01`／`s1-s3-wk01`：加 `, 60 min.`，話題由 hobbies 擴為 hobbies／favourite food／future job，並加句 `only these three topics, never invent new ones.`）；**(2) Welcome page 觸發**（24 檔 `How I Run This Week` 第 6 點全行換為 `Open with a welcome page`，含「本對話未見本週 welcome 就先出、已見就 skip」邏輯；三 band 各自措辭）；**(3) 糾錯列表**（16 檔 `How I Run This Week` 第 7 點句尾追加 `You wrote: ... — Try: ...` 逐行格式，上限 5 行，外層保留 feedback sandwich）；**(4) 時間預算**（16 檔：30 條任務行插入 `, N min.`＋第 2 點句尾追加 pacing 句）。**P1-P3 八檔只做編輯 2**。manifest 重凍為 c1-12 值。
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

## 檔案 manifest（LF sha256）· c1-13a 值（2026-10-04，工具名更新＋Task 1 起跑＋誠實邊界＋唔重複提示 後重凍）

| 檔 | bytes | sha256 |
|---|---|---|
| `personas/dibi-curriculum-p1-p3-wk01/PERSONA.md` | 10442 | `6d35ee49488f035862faa31ffcc77765ecd1351b07b678e94aad4e02717d7ca3` |
| `personas/dibi-curriculum-p1-p3-wk02/PERSONA.md` | 10618 | `edc21e188beab00168884a255ffc56639f3651e96714ad6c98ede28d4f5fa5e0` |
| `personas/dibi-curriculum-p1-p3-wk03/PERSONA.md` | 10726 | `d70df8a09320554b1a6e0a4f03f5eb0971620dac02893665dd31d1984a64752a` |
| `personas/dibi-curriculum-p1-p3-wk04/PERSONA.md` | 10638 | `547ba7971c86af4ff4941de27a56a454d44e03af07f899df0936ca85b09d6cb7` |
| `personas/dibi-curriculum-p1-p3-wk05/PERSONA.md` | 10781 | `32a1248a241caeea1038c0fae3c62ae9d04c2a81c2eaba2f9b6878e24bf3d640` |
| `personas/dibi-curriculum-p1-p3-wk06/PERSONA.md` | 10940 | `aa4b282703aa48d2cee90260ade4141648acbddc7b18602ef12da267cfab2450` |
| `personas/dibi-curriculum-p1-p3-wk07/PERSONA.md` | 11381 | `b9e253f9fafd1cff78e8f9a55b3155b6b103bfb7fb35d678f56b0c67fd8152c0` |
| `personas/dibi-curriculum-p1-p3-wk08/PERSONA.md` | 11050 | `6cf78784660584f706bfc4350aed429b3b3da86acc33158f7dfff8279e61f61d` |
| `personas/dibi-curriculum-p4-p6-wk01/PERSONA.md` | 10053 | `37dda3aea9e14a03839fdc20098f32f2e2326930cb21ca00260b60ed97455ef1` |
| `personas/dibi-curriculum-p4-p6-wk02/PERSONA.md` | 10018 | `4bc54ffd8b5c47e8d9faf808df826b1248332d64773d2f7320df8daf3e1ca8e0` |
| `personas/dibi-curriculum-p4-p6-wk03/PERSONA.md` | 10265 | `c635064098be6c9528d840e7dd411eb1a47d541cc08f95a9037439e2a7241fa1` |
| `personas/dibi-curriculum-p4-p6-wk04/PERSONA.md` | 10081 | `a3cc69471e854b7912fbbfae0d6da442c9734d433251fb4b03d845874eb0d1af` |
| `personas/dibi-curriculum-p4-p6-wk05/PERSONA.md` | 9817 | `0d258215f370190b29cc776e8f43610f7f011750cc7aec6b80e51b5f8b1e1240` |
| `personas/dibi-curriculum-p4-p6-wk06/PERSONA.md` | 10156 | `f6119db31dc41d3eaec2123ddc7c57ed61b140e8765015e867ff19dfb16701b5` |
| `personas/dibi-curriculum-p4-p6-wk07/PERSONA.md` | 10275 | `ec394f31b757c8d97c52afd352fdcd5370d8ef3e7cb0591bc26287d0b9ac9682` |
| `personas/dibi-curriculum-p4-p6-wk08/PERSONA.md` | 10479 | `73d7b8ee84997c8536628274c968ed63f6d769934f3bf1ca059f1610afca97f5` |
| `personas/dibi-curriculum-s1-s3-wk01/PERSONA.md` | 9855 | `2c0aeaea5ebec2260fe3b425bd13c8a3aeb31883442c66ddaa7814d65231a1b6` |
| `personas/dibi-curriculum-s1-s3-wk02/PERSONA.md` | 9820 | `f1ca07a9dcaa7aebc1cb299c663342b350b84908569692d720909701ae8e0c75` |
| `personas/dibi-curriculum-s1-s3-wk03/PERSONA.md` | 10067 | `31e8974d76aecf45225df67a3f6e2a51493b98d0afaededd3ccb595288fbdf68` |
| `personas/dibi-curriculum-s1-s3-wk04/PERSONA.md` | 9883 | `c182940f10df9db7d7997e4b8145c6b1a1b4f9696ac0049004f48b3adc13a3ba` |
| `personas/dibi-curriculum-s1-s3-wk05/PERSONA.md` | 9619 | `acd2ca1fbdaa6a7537be333d205c3b6bf7d8382f852582563f63a7f4ac16d74d` |
| `personas/dibi-curriculum-s1-s3-wk06/PERSONA.md` | 9958 | `122cda2bea5489f3bd4dd7330045983a817120fd1f7a9e9c8e295811ddf48f29` |
| `personas/dibi-curriculum-s1-s3-wk07/PERSONA.md` | 10077 | `8dc2bf3c95eb6149ca358ad8c97614421f9564a30abc75bef77ef8249fef3db5` |
| `personas/dibi-curriculum-s1-s3-wk08/PERSONA.md` | 10281 | `a0665950fe9e95a0c3b961bc2359f840cfee1d67c1a42ae17eb9a8b5499e8273` |
| `docs/pr-d-c1/中文參考版.md` | 23493 | `d30bfb66a0dce588571fcb8cf806ba92de29387b774235f9efc9092d184f672b` |

---
*D6 persona 定稿包 · 2026-09-29 · c1-7 英文專線修訂 2026-10-02（老闆三指令）· 依據 v0.3 §4＋老闆 Word 格式＋8 份 pinned 課程 md*
