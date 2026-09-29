# PR-D-c2 Scope 稿（v0.1 · 2026-09-29）—— O-3 前端按鈕

- 立項依據：老闆批核（2026-09-29）——v1 最細版本（掣唔顯示週數）、Marvis 單人做
- 上游依賴：PR-D-c1（relay 路由已入 remote main `c9dc7d8`；部署跟 D6 窗 runbook）
- 本檔可直接入 repo `docs/pr-d-c1/`（無水印尾行）

## 1. 目標

學生 Welcome page 加一個掣，按入去即進入課程模式：client 喺 WS chat frame **頂層**帶 `dibi_mode:"curriculum"`，其餘全部 server 做（week 解析、slug 路由、fail-open 都已喺 relay 度）。

## 2. 合約（client ↔ relay）

- frame 頂層加一個 key：`"dibi_mode": "curriculum"`。
- **只能放頂層**——config layer 有 `extra="forbid"`，放錯層成個 turn 被拒（F-2 已核實）。
- 值白名單：淨係 `"curriculum"` 一個值；**唔准帶 week／slug／任何 id**（HC-c2-1／HC-c2-2）。
- 後端未部署／舊版 relay：頂層新 key 被引擎靜默忽略（F-1 已核實）——即係 c2 可以先於 D6 窗上 staging，唔會炸。

## 3. UI 行為（v1 範圍）

1. Welcome page 加掣「**My AI Course**」（文案暫定，老闆可改；英文，因學生用英文上課）。
2. 按掣 → 進入課程模式 chat：頭頂有 mode 標示（如 badge「Dreamer Course」），學生知道自己喺邊個模式。
3. 課程模式期間**每個 frame 都帶 flag**——relay 每 turn 重解析（有 slug cache，badge 唔變就 cache hit；老師改週都即時跟上）。
4. 退出掣（「Back to normal chat」）→ client 停發 flag。注意：session slug cache 會留喺該 WS session（persona 語氣可能延續），新 session 會 reset——v1 接受，寫入 known limitations。
5. 打招呼 short-circuit 沿用現有行為，c2 唔郁。

## 4. 邊界（v1 唔做）

- 掣顯示「Week N」（要 read-only API，落 v2）。
- P1-P3：v1 掣**照出**，fail-open 行 band persona（安全）。如果 frontend 拿到 band，遮住 P1-P3 係一行 if——有就做，冇就照出（記入實施備註）。
- 家長端掣、課程進度頁、任何 DB 寫入。

## 5. Hard checks（c2 自己嘅 gate）

| # | 檢查 |
| --- | --- |
| HC-c2-1 | flag 值只可以係 `"curriculum"`；無第二個值 |
| HC-c2-2 | flag 喺 frame 頂層，唔入 config layer；唔帶 week／slug／student_id |
| HC-c2-3 | 退出後停發 flag（mode 唔會黐住） |
| HC-c2-4 | 無 flag 嘅普通聊天零改動（回歸） |
| HC-c2-5 | 新增前端測試檔入 ci.yml manifest（跟 repo guard 規矩） |

## 6. 測試計劃

- 單測：flag 注入／退出／白名單（frontend 測試框架跟 repo 現有）。
- Staging 整合（等 D6 窗收口後）：P4-P6 帳號按掣 → 回覆係 wk01 persona 語氣；S1-S3 同測；退出 → band persona；P1-P3（如有帳號）→ fail-open band persona。
- 呈報：截圖＋frame dump（遮蓋真實 student_id）＋audit 字眼 `mode=curriculum, slug=…`。

## 7. 時間表（已批，見 D6 窗 runbook §9）

- 9/30–10/9 開發（約 5 工作天）→ 10/7–10/9 對上線 backend 整合 → **10/12 老闆簽 release**。

## 8. 紅線（繼承 D6 線）

- 先稿後碼：本 scope 老闊批咗先寫 code。
- 唔郁 backend／relay／compose；frame 欄位名 `dibi_mode` 同 relay 常量 `_CURRICULUM_MODE_FLAG` 對死，改任何一邊要 gate 批。
- watermark guard：新檔案唔准帶 AIGC 尾行。
