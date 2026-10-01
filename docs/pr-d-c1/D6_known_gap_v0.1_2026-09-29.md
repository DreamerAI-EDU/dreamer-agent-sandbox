# D6 線 Known Gap 與已知限制（v0.1 · 2026-09-29）

- 立項依據：gate 裁決 2 —— ⑤ week 越界接受「部分覆蓋」結案，寫入 runbook known gap；同輪裁決 C —— 本檔入 repo `docs/pr-d-c1/`，走 Tier 0（純 docs）。
- 範圍：D6 窗 ⑤ 覆蓋缺口（Gap ①）＋ 已批 c2 v1 已知限制（Limitation ②）。
- 本檔可直接入 repo `docs/pr-d-c1/`（無水印尾行）。
- 本檔僅記已實測／已批文稿內容（證據座標見各節），未新增未驗證結論。

---

## 1. Known gap ①：⑤ week 越界情境未做實機覆蓋（結案＝部分覆蓋）

| 欄位 | 內容 |
| --- | --- |
| 情境 | D6 窗 smoke ⑤「異常途徑 → band persona」之實機覆蓋 |
| 裁決 | 接受**部分覆蓋**結案 |
| 未覆蓋範圍 | `week_index` 超出 1–8 範圍（即 > `total_weeks` = 8）；同類未覆蓋亦含 badge `locked`、`class_curriculum` 無 active 但有 history 等異常途徑 |
| 未覆蓋原因 | 構造需經 DB 造數（屬 Tier 2 寫入），與本輪風險／成本唔對稱；本輪未改任何 DB 現狀 |
| 替代證據 ①（實機，最常見真實情境） | D8 fail-open：P1 smoke（引擎 session `6842abf2`，登入回應 `badge={"state":"none","week_index":null,"total_weeks":8,...}`）帶 `dibi_mode` flag → **唔入課程模式**，落 `dibi-p1-p3` band persona；回覆為 P1 年齡帶泛化主題、零課程週內容；relay audit id362／368 記 `frame_type=message mode=curriculum slug=dibi-p1-p3`；引擎 session persona `dibi-p1-p3` |
| 替代證據 ②（單元測試，覆蓋邊界） | `tests/test_ws_chat_curriculum_mode.py::test_hc_d_guard_falls_back_to_the_band_persona`：逐項斷言 `state=none`、`state=active week_index=9`（**越界**）、`week_index=None`、未知 state、lookup 拋錯 → 一律 band persona 且唔拋錯；healthy edge `completed week_index=8` → `wk08` |
| 殘留觀察（非缺陷） | relay audit 近 24h slug 分佈曾見 `slug=dibi-s1-s3` 而 `mode=none`（session `b57a9846`）——屬 persona 解析層 fail-open 正常行為（未帶 flag 走 band persona），**非**路由缺陷；D9 期間列持續觀察項 |
| 後續 | D9 觀察期（至 10/6）如真機學生自然行到 `week_index` 越界／badge 異常，順手補 ⑤ 實機證據並回填本節；D10 收口時複核 |
| 證據座標 | `D6_window_routeA_smoke_report_D7-D8_2026-09-29.md` §2 表③④、§3.2、§6.1；`D6_window_closeout_and_D9_baseline_2026-09-29.md` §4.2、收尾結論 5（兩份為 D6 窗工作報告，落 repo 工作目錄 `output/`，該目錄受 `.gitignore` 忽略） |

---

## 2. Known limitation ②：c2 v1 退出課程模式後 session slug cache 殘留

- 來源：`docs/pr-d-c1/PR-D-c2_scope_v0.1_2026-09-29.md` §3.4（已批文稿，原文「v1 接受，寫入 known limitations」）。
- 內容：client 按「Back to normal chat」後停發 `dibi_mode` flag；relay 側 session slug cache 仍留喺該條 WS session，persona 語氣可能延續至該 session 斷線；新 session 建立時 reset。
- 影響邊界：限同一條 WS session 之生命週期；新 session／重新登入即回復。
- 現狀：v1 接受，非本輪修復項；hard check HC-c2-3（退出後停發 flag）不變。
- D9／staging 抽查方式：退出後於同一 session 再對話一句，核對 audit `mode=`／`slug=`、引擎 persona slug 及語氣是否延續。

---

## 3. T2 驗收偏差 2：`dibi_mode` 實測型別與退出語義（口徑修正）

| 欄位 | 內容 |
| --- | --- |
| 偏差 | T2 驗收稿以「`dibi_mode >= 1` 開課程模式、退出時回落 `0`」之數值語義描述；實測與此不符 |
| 實測 ①（型別） | 該 flag 為**字串**值：只有 `"curriculum"` 開課程模式；其餘值（含數值 `1`）一律唔路由，落 band persona |
| 實測 ②（退出語義） | 退出課程模式時 `dibi_mode` **整鍵缺省**（key absent），**非**「值為 `0`」；relay 側以「鍵是否存在」分流 |
| 代碼座標 | `auth/ws_chat.py` L216/218（`_CURRICULUM_MODE_FLAG = "dibi_mode"` ／ `_CURRICULUM_MODE_VALUE = "curriculum"`）；L338（`mode == _CURRICULUM_MODE_VALUE` 才路由週 persona）；L389（鍵缺省 → 走 pre-c1-1 路徑，`persona` 欄由 client 原值決定）；L1226（audit `mode=` 由 `_mode_word(frame.get("dibi_mode"))` 取值，鍵缺省印 `none`） |
| 與 §2 互證 | §2 所述「退出後 client 停發 `dibi_mode` flag」在 relay 側即表現為鍵缺省；`_cached_slug` 於鍵缺省時不清（§3.4 resolve once per session）→ 即已批 Limitation ② |
| 影響邊界 | 純口徑／描述修正：HC-c2-3（退出後停發 flag）與 HC-F（persona 解析）行為不變，無需改碼 |
| 落地說明 | 本節依 gate 裁決，作為 T2 驗收偏差 2（v0.2.1 口徑）之落地段；本輪 c1-4 修復批 C 項落此 |
| 原始驗收座標 | 偏差 2 由 gate 於 c1-4 修復批確認；具體 session／DB 座標於 T2 release 收口時回填 |

---

## 4. T2 release 收口：學生可見回覆「收貨口徑」定案（2026-10-01）

- 定案來源：老闆放行令（T2 release ops）。
- 適用範圍：課程模式（`dibi_mode:"curriculum"`）學生可見回覆之收貨判定；供 D9 觀察期與 D10 收口沿用。

**收貨口徑（老闆原話，定案）**：

1. 學生可見（UI innerText）**零符號**；
2. **≤8/12 行**；
3. **只答當週**；
4. **任務逐行**。

**附註（驗收實測）**：行數口徑因前端壓平換行，**需以原始 frame 為輔證**。T2 真站驗收實測顯示：原始 `result` 幀含 `\n` 與 `**`，而同一輪 UI `innerText` 呈**單行**且無 `**`（browser V13／V14 實測，座標見 `docs/pr-d-c1/D7_handover_remark_v0.1_2026-09-30.md` §10.3）。故：

- 「行數」不可只以 UI `innerText` 行數判讀，須同時核**原始 WS frame 之非空行數**；
- 「任務逐行」同受前端壓平影響，判讀同樣以**原始 frame** 為準；
- 「零符號」以 UI `innerText` 為準（惟須知此係前端剝符之結果，非模型原始輸出無符號）；
- 口徑拆分（T2 驗收實測對應）：P4–P6 帶 ≤8 行、S1–S3 帶 ≤12 行；如與老闆原意有出入，**一律以老闆原話「≤8/12 行」為準**。

**T2 release 收口回填（對應 §3 待回填項）**：

| 欄位 | 內容 |
| --- | --- |
| 回填項 | §3「原始驗收座標 —— 具體 session／DB 座標於 T2 release 收口時回填」 |
| 實測環境 | 真站 `app.dreamer-aiedu.com`（新 bundle `assets/index-CjszE7l-.js`，sha256 `519a81dc…`） |
| 賬號／班級 | 學生 P4 Smoke（`2a7870f4`，band P4–P6，第 1／8 週） |
| session_id | `unified_1790827895632_b9c87954` |
| 課程模式 send 幀 | `message_id = e8ca915c-44b9-4587-a543-3fec4a5e7b49`，頂層帶 `dibi_mode:"curriculum"` |
| 退出後 send 幀 | `message_id = e8a44844-5e82-4c35-8042-a63d910966dd`，**無** `dibi_mode` 鍵 → 鍵缺省，與 §3 實測 ②「退出時整鍵缺省」一致 |
| 採集時間 | 2026-10-01（T2 release 上站後、瀏覽器側 V8–V14） |
