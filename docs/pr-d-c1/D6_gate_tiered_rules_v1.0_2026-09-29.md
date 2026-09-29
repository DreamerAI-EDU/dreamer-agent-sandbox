# D6 線 Gate 分級規矩（v1.0 · 2026-09-29，老闆批准）

- 生效日期：2026-09-29（老闆批「yes, go for it」）
- 目的：gate 審批集中喺機器守唔到嘅位；日常開發唔再排隊等全量審
- 本檔可直接入 repo `docs/pr-d-c1/`（無水印尾行）

## 1. 三級制

| 級別 | 適用範圍 | 流程 | 例子 |
| --- | --- | --- | --- |
| **Tier 0：CI-only** | 純 docs、測試檔、畀 guard 全自動覆蓋嘅改動；唔觸任何紅線 | 本地 CI（56 測試檔＋三道 guard）全綠 → 直接 push；gate 事後抽樣 | README、測試補充、manifest 類 |
| **Tier 1：異步審** | 一般前後端代碼；**唔觸** frame 合約、persona 內容、DB、部署、安全 | Marvis 跑完 §2 自查清單＋本地 CI 綠 → push；gate 24 小時內審 diff，有問題開 revert；**唔阻塞**下一步非依賴工作 | PR-D-c2 前端按鈕開發期間嘅 commit |
| **Tier 2：全停** | 生產部署窗；DB 寫入；relay frame 合約／欄位改動；persona 內容／manifest 改動；新部署路徑；安全相關 | 維持逐格呈批、先稿後碼、老闆簽核 | D6 窗、c2 release（10/12）、未來 curriculum 內容更新 |

## 2. Tier 1 自查清單（Marvis push 前必跑，缺一不可）

- [ ] 本地全量 CI 綠（56 測試檔＋ci-manifest／watermark guard）
- [ ] 改動範圍確認**唔觸** Tier 2 清單（逐項對過）
- [ ] 新檔案無 AIGC 水印尾行
- [ ] 紅線 8 自查：冇新增任何寫 student_id 去 log／audit／frame 嘅路徑
- [ ] commit message 載明：屬於邊條 PR、Tier 幾、自查清單已跑
- [ ] 呈報 gate（一份簡報：diff 摘要＋自查結果），唔使等批覆先繼續

## 3. 任何級別都唔放鬆

1. 八條紅線（含 red-line 8：student_id 唔出 relay）。
2. 生產窗 hard check（G-1–G-6，hard check 即停）。
3. 部署必簽：任何上生產動作（image tag bump／host 檔案／compose）一律 Tier 2。
4. watermark／manifest guard 唔准繞過、唔准改 guard SoT。
5. `dibi-curriculum-p1-p3-*` stub 永遠唔上 host。
6. deeptutor image pin v1.5.8，升版屬 Tier 2。

## 4. 簽核格式（加速用）

- 全綠呈批：老闆覆「**ok**」即簽，唔使睇長文（長文 gate 負責睇）。
- 有 red／有疑問：gate 標明「**停**」＋一個原因，老闆先需要睇細節。

## 5. Gate SLA

- Tier 1 呈報後 **24 小時內** gate 完成 diff 審；逾期未審＝默認通過，但 revert 權保留。
- Tier 0 抽樣：每 10 個 Tier 0 commit 抽 1 個覆核。

## 6. 報告模板（所有級別通用，一段式）

```
線別／Tier：
commit(s)：
改動一句講晒：
自查結果：（Tier 0/1 用 §2 清單；Tier 2 用守衛格逐項）
誠實附註：（任何偏差／疑問，唔准隱瞞——隱瞞即降返全停制）
```
