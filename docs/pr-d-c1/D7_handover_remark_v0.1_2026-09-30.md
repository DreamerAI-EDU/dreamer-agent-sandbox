# D7 線 Handover Remark（v0.1 · 2026-09-30）

- 撰寫：Marvis 代寫（非人類簽核）；日期 **2026-09-30**。
- 立項依據：老闆批文 —— L1＋L2＋L3＋L4 四層落地後 smoke 仍紅即**停手**，證據全量寫入本 remark，由老闆裁決階段性放行與否。
- 本檔性質：**純證據照抄**。紅旗照寫、綠燈亦照寫；未美化、未淡化、未推論未驗證結論。
- 本輪動作限制（遵批文）：**不改任何修復內容、不回滾 L1／L2／L3、不做任何 SQL 寫入**；只新增本 docs 檔並單獨一個 docs commit ＋ push。
- 落地層級：Tier 0（純 docs），入 repo `docs/pr-d-c1/`（無水印尾行）。

---

## 1. 已落地狀態（供回滾判斷，本輪未再改動）

| 層 | commit | 內容 |
| --- | --- | --- |
| L1 | `266c58c` | yaml zh＋en 子句降格 |
| L2 | `94f926a` | 16 份 persona 正文去 markdown＋manifest sha256 同步 |
| L3 | `94b9e15` | 剝符改為顯式 opt-in（`stripSymbols` prop），共用件默認還原原樣 |
| A′ | `6b19bca` | L1 非課程路徑回歸 R1/R2 實測結果（取代 known-gap 登記） |

- `HEAD = origin/main = 6b19bca`（本 remark 撰寫前之基線）。
- 遠端 CI run `36750308603`：**全綠** —— 57/57、watermark 50/50、pytest 1100；另披露：`exit-criteria-trials` **首跑 flaky、重跑轉綠**（照寫，不掩）。
- L1 非課程回歸：R1（普通問答）／R2（band persona）**未見格式崩壞、亦未誤觸 course persona**（本輪 R1/R2 寫入 msgs 363–368）。
- host 16 persona 三向 hash **16/16** 一致；窗 #2.5 舊紀錄作廢。
- preview 供版：新 bundle `assets/index-CjszE7l-.js`；備份 `/root/preview_backup_20260930T155409Z`；**舊 bundle 保留，可即時回滾**。

---

## 2. 紅旗實測（preview ＋ 新版 bundle）

執行環境：preview `https://motivated-floral-sheriff-treatment.trycloudflare.com`；登入 join `8E7VH25M` / PIN `6673`（學生 P4 Smoke，第 1/8 週）；課程入口 `mode=curriculum`，發送幀頂層確認 `dibi_mode:"curriculum"`、`language:"zh-hk"`。

### 2.1 Bundle 實供（綠燈部分，照寫）

| 項 | 實測值 | 期望 | 判定 |
| --- | --- | --- | --- |
| `assets/index-CjszE7l-.js` sha256 | `519a81dc5cabfda23ad7fd96d640a1a05537bbfc9751380cd3209a8c88073d5d` | 同 | ✅ |
| 位元組數 | `684344` | 684,344 | ✅ |
| `index.html` 引用新 bundle 次數 | 1 | ≥1 | ✅ |
| `index-CMvrviDp.js`（舊 bundle）被引用次數 | 0 | 0 | ✅ |
| `index.html` sha256 | `9f18e03dead77ebe09928e84ad9a4dd99da696f2a52cc5f6057b72af103fc6e0` | — | 記錄 |

實供 script 標籤：`<script type="module" crossorigin src="/assets/index-CjszE7l-.js"` → 新版 bundle 確由 preview 實際供應。

### 2.2 P4 課程模式輪 2「今個星期我要做咩？」——⚠️ 紅旗

- 時間戳：send `2026-09-30T17:47:09.995Z`／done `2026-09-30T17:47:27.164Z`（本地 2026-10-01 01:47）。
- `turn_id`：`turn_1790790520732_0ab135ce83`；`message_id`：`2b3eb700-d42a-44ea-9224-cde8f37afab0`；user/assistant msg id `369 / 370`；`session_id = unified_1790681683062_c5b23479`。
- **原始模型輸出**（取自 WS `result` 幀 `metadata.response`，逐字未加工；與 §3 DB 原文一致）：

```
今個星期嘅學習主題係 **「This is Me!」**（「這就是我！」），係 Dreamer AI 課程嘅第一週，屬於 **Dream 階段**，主要培養你嘅 **創意思維** 技能！🎨✨

### 今個星期嘅任務：
1. **AI 訪問（英文寫作）**  
   - 我會扮成一個友善嘅記者，問你 5 條有趣嘅問題，關於你嘅興趣同愛好。你要逐條回答我！

2. **我的頭像（創意設計）**  
   - 用 Canva Magic Media 設計一個卡通頭像，穿著香港校服，仲要拎住你最鍾意嘅興趣物品！記得只寫你嘅英文名。

3. **我的中文故事（中文寫作）**  
   - 用 AI 幫手寫一段約 50 字嘅自我介紹，要用小學生嘅語氣！

4. **自我介紹！（英文口語）**  
   - 錄一段 1 分鐘嘅短片，用你設計嘅海報介紹自己。

### 完成後你會得到：
- 一個獨特嘅頭像海報 + 中英文自我介紹 + 1 分鐘短片（課程嘅第一個成果！🎉）
- 學識點樣保護自己嘅私隱，明白 AI 唔係秘密守護者。

### 準備好開始未？  
我哋先做 **「公民一分鐘」**，學吓點樣保護私隱，然後就開始第一個任務！💪  

你想而家開始，定係有咩問題先？ 😊
```

- **原始輸出符號計數（WS 幀口徑）**：`**` 12 處、`###` 3 處、頂格 `- ` 2 處、縮進 `   - ` 4 處；非空行 **約 16 行**；**一次倒 4 個任務**。
  - ※ 與 §3 DB 逐字重算之 `**` 計數（16 個 `**` 記號 ＝ 8 對粗體）**不一致**，差異照寫、不裁決、不美化，見 §3.3。
- **三條收貨口徑全部未達**：零 markdown ❌（原始輸出帶完整 markdown）、≤8 行 ❌（約 16 非空行）、一 turn 一 task ❌（一次列 4 個任務）。
- UI 顯示層（L3 剝符後）實測：`**` **0**、`##` **0**、`---` **0**、數字清單 `1.–4.` 保留、**縮進 `   - ` 仍有 4 處外露**（與 §6 bundle 內 `/^[-*]\s+/` 不匹配縮進一致）→ UI 睇落「乾淨」係剝符造成，**唔可以當綠燈**。
- 答錯週次：否（只講第 1 週）；course persona：生效（`dibi_mode=curriculum`、內容圍繞課程第 1 週）。
- 輪 3「我完成了第一個任務」**未執行** —— 命中紅旗後按口徑停手。
- Gloria 輪（`NXY4VGF9`/`7464`，S1–S3，≤12 行口徑）**未跑**，未採集。

### 2.3 P4 輪 1「Hi」（綠，但附註疑慮）

- 時間戳：send `2026-09-30T17:45:01.459Z`／content `17:45:01.714Z`／done `17:45:01.715Z`。
- `message_id`：`06a392d4-8dce-4942-8859-bec6cbf7ef5a`；`turn_id` **未取得**（首輪 recv 為簡化幀，無該欄位）。
- 原文：`哈囉！我係你嘅 AI 學習夥伴，今日想學啲咩呀？` —— 行數 **1**、`**`0／`##`0／`- `0／`---`0、無一次倒多 task、只答當週 → 未見紅旗。
- **疑慮標明**：輪 1 之單行短回覆有可能屬**前端靜態歡迎氣泡**而非真模型回合；DB 側未見對應 assistant 行（§3 msg 369 之前無新增 assistant 訊息），故本 remark **不視其為 L1／L2 有效之正面證據**。

### 2.4 首訪 welcome 氣泡（口徑②，綠）

- 學生主頁 `/student` 無氣泡（僅「第 1 / 8」）；進入 chat 首訪氣泡原文：`P4 Smoke，你好呀！你而家喺第 1 週，課程完成咗 0%。今日有咩想問 Dibi？` → **0%** ✅。
- 首訪後 localStorage 寫入：`welcome_shown_v1_2a7870f4=1`、`dreamer.ui.lang=hk`（清理核實為零後重新生成，符合預期）。

### 2.5 截圖（存 workspace 中間產物夾 `…\temp\`）

`l4-01-home-welcome.png`、`l4-02-chat-welcome.png`、`l4-03-p4-turn1.png`、`l4-04-p4-turn2.png`
路徑前綴：`C:\Users\user1\AppData\Roaming\Tencent\Marvis\User\oAN1i2XPgc8VZ8q4ZUucBejayo_A\workspace\conv_c509520e2ac04506ada5d704cb73b250\temp\`

---

## 3. DB 只讀交叉核實（msg 369／370）

### 3.1 查詢方式（只讀，`mode=ro`）

- DB：`/opt/dreamer/deeptutor/user_data/chat_history.db`。
- 方式：遠端主機 **無 `sqlite3` CLI**（實測報 `sqlite3: command not found`），故改用 Python 標準庫 `sqlite3` 以 **URI 唯讀模式**開啟：`sqlite3.connect('file:/opt/dreamer/deeptutor/user_data/chat_history.db?mode=ro', uri=True)`；全程 **零寫入**、未開交易、未建表。
- 取數語句：
  - `SELECT content FROM messages WHERE id=370;`
  - `SELECT id, role, session_id, content FROM messages WHERE session_id='unified_1790681683062_c5b23479' AND id BETWEEN 340 AND 372 ORDER BY id;`
  - `SELECT id, content FROM messages WHERE session_id='unified_1790681683062_c5b23479' AND role='assistant' ORDER BY id;`（統計 ≥15 非空行者）
  - `SELECT MAX(id) FROM messages;`
- 探針腳本（中間產物，非交付物）：`…\conv_c509520e2ac04506ada5d704cb73b250\temp\db_probe2.py`、`db_probe3.py`。

### 3.2 核實結果（與 WS 幀一致性）

| 項 | DB 實測 | WS 幀口徑 | 一致 |
| --- | --- | --- | --- |
| msg 369 role／content | `user`／`今個星期我要做咩？` | 同 | ✅ |
| msg 370 role | `assistant` | 同 | ✅ |
| session_id | `unified_1790681683062_c5b23479` | 同 | ✅ |
| parent 鏈 | 367→368→369→370（`parent_message_id` 連續） | 「緊接歷史」 | ✅ |
| turn | `turn_1790790520732_0ab135ce83`，`status=completed`，`created 1790790520.732`→`finished 1790790537.683` | 同 turn_id | ✅ |
| 非空行 | **16** | 約 16 | ✅ |
| `###` 處數 | **3** | 3 | ✅ |
| 頂格 `- ` 行數 | **2** | 2 | ✅ |
| 縮進 `   - ` 行數 | **4** | 4 | ✅ |
| `---` 行數 | **0** | 未提 | — |
| `**` 處數 | **16 個記號（＝8 對粗體）** | **12 處** | ❌ **不一致（照寫）** |
| content 位元數 | 538 chars | — | 記錄 |
| content sha256 | `92ece52e219afebfc1168d94999c9b9580630ed57a3dada72341bc283e2c316b` | — | 記錄 |

- 其他：`SELECT MAX(id) FROM messages` ＝ **370** → 本輪 smoke **未新增任何新 session／新訊息**（全庫最大 id 即 370）。

### 3.3 差異披露（不美化、不裁決）

- `**` 計數 WS 幀 12 處 vs DB 16 個記號（8 對）。兩者取自不同採集路徑（WS 串流幀 vs DB 落庫原文）；本 remark **只照寫兩個數字與各自來源**，不在本輪查明成因，留待老闆裁決後另開查證。
- 除該項外，行數與 `###`／頂格／縮進計數**兩路一致**，紅旗結論不受影響。

---

## 4. L4 隔離前提失效（關鍵發現，須顯著看待）

| 項 | 實測 |
| --- | --- |
| 全新 profile | `…\conv_c509520e2ac04506ada5d704cb73b250\temp\l4-profile-20261001-013335`（新建時 `CHILD_COUNT=0`，全新空目錄） |
| 登入前 localStorage 清理 | `localStorage.clear()` 後核實：`beforeCount=0, afterCount=0, sessionStorageKeys=[], cookieLen=0` → **確為零** |
| **服務端 session** | **舊 session 原樣復用**：第 2 輪 WS 幀仍帶 `session_id = unified_1790681683062_c5b23479`；訊息序號緊接歷史（365/366、367/368 → **369/370**） |

**結論**：清空瀏覽器側 localStorage／cookie **換唔到新 session**——服務端按 **student 維度**復用舊會話（會話上下文於 DB 內延續）。即：在「**唔准 SQL 寫入**」前提下，L4 所要求之「乾淨樣本」**客觀上做不到**；此「不符」本身即已觸發停手條件。

---

## 5. 因此未證偽之 confound（直接影響決策，不准漏）

- 舊 session `unified_1790681683062_c5b23479`（title：`This is Me learning week tasks`，created_at `1790681683.06`）內積累大量 **long-form markdown few-shot**，實測同一 session 內 **≥15 非空行之 assistant 訊息共 10 條**：
  `msg 326(16)、332(22)、336(15)、350(21)、354(18)、356(18)、358(24)、360(18)、362(25)、370(16)`。
  其中 msgs 358／360／362（18／18／25 行，含 `###`、`**`、`---`、縮進清單）緊貼本輪 366／368／370 之前，msg 360 內容即為「Week 1: This is Me! / 4 fun tasks」之 18 行格式範例。
- 即：模型可能是**被上下文內 few-shot 帶偏**，而唔係 yaml／persona 子句完全無效。
- **故 L1 假設「未被乾淨地否證」**，只係「在污染條件下（本 session）無效」。此點直接影響老闆決策，照實列出。

---

## 6. L3 安全網能力邊界（同閘門定位一致）

- 實測 L3 只剝到**頂格**符號：`**`、`###`、頂格 `- `、`---`。
- **縮進 `   - ` 剝唔到** —— bundle 內正則為 `/^[-*]\s+/`，**不匹配行首縮進**；本輪 msg 370 UI 層仍見 4 處縮進 `- ` 外露，即為此邊界之實證。
- 結論：**前端剝符不可當作達標手段**（只能視為 UI 呈現層緩解），與閘門定位一致。

---

## 7. 結論與待老闆裁決選項

**結論（照閘門裁決原意）**：L1＋L2＋L3 已落地，**smoke 仍紅** → **文字提示層無法硬性保證格式**；要硬性保證，只有 **engine 層輸出後處理** 或 **D7 自有 agent** 兩條路。

待裁決選項：

- **(a) 授權一次性清 P4 session**（屬 DB 寫入）：取得真正乾淨樣本後重測，方可判定 L1 有效／無效（並同時解掉 §5 confound）。
- **(b) 接受現狀紅**：直接按 D7 路線推進（放棄「文字層硬保證格式」路線）。
- **(c) 只回滾 L1／L2／L3 某一層**：依 §1 commit 座標逐層回退，其餘不動。

---

## 8. 未取得項與方法披露（照實）

1. **未取得**：P4 輪 3、Gloria 輪（命中紅旗後停手）；P4 輪 1 之 `turn_id`（首輪 recv 為簡化幀）。
2. **WS 原文採集方法**：頁面內注入 `window.WebSocket` 包裝記錄 `send`／`recv` 全幀至 `window.__l4frames`，再以 `eval` 讀出；**未改任何前端碼**，僅供核對。
3. **登入方式披露**：獨立 Chromium 下 `fill` 寫入受控 input 未進入 React state（首次提交無效），改用真實鍵盤鍵入（click 聚焦 ＋ `keyboard type`）後登入成功；屬工具行為，與產品無關。
4. **DB 端**：`sqlite3` CLI 缺失（改 Python `sqlite3` `mode=ro`）；本輪**零 SQL 寫入**。
5. **未碰**：主站；任何 engine 碼；任何修復內容。

---

## 9. 本輪（寫本 remark）未做之事

- 未改任何修復內容、未回滾 L1／L2／L3、未做任何 SQL 寫入。
- 只新增本檔一個 docs commit 並 push；其餘檔案一律未動。
