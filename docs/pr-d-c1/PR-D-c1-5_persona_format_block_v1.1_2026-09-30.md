# PR-D c1-5 · persona 格式 block 規格 v1.1（2026-09-30）

## 1. 背景（為何要改）

T2 前置驗證中 smoke ① 判 RED：P4 Smoke（mask `2a7870f4`）於 2026-09-30T04:51Z 嘅 turn，回覆列足 8 週課程、夾雜 `###`×2／`**`×36／`- `×11／`---`×3、34 行，違反當時 persona 內嘅 4 條格式規則。

只讀診斷（E1–E4）已釘死根因：

- **slug 正確**：relay audit id 398 `turn_start` 記 `frame_type=message mode=curriculum slug=dibi-curriculum-p4-p6-wk01`；請求側 `dibi_mode=curriculum`、band `P4-P6`、`badge.state=active`、`week_index=1` 四閘全過。
- **注入嘅係對嘅 persona**：回覆內容可逐句溯源到 `dibi-curriculum-p4-p6-wk01`（Super Student Profile／cartoon avatar／bilingual self-introduction／1-minute video／Dream-Discover-Design-Deliver 皆為該週 persona 專有素材；band persona `dibi-p4-p6` 完全無此類素材）。
- **格式 block 當時在位**：`## How I Reply` block mtime 04:38:41Z，早於該 turn 12 分鐘；引擎每回合即時 `read_text` 讀 persona、無內容快取。

→ 結論：**slug 正確但模型不服從格式規則**，屬 persona 內容／prompt 層問題，故以 c1-5 加強格式約束。

## 2. Step 0（只讀）：`completed` 態可達性

| 項目 | 代碼座標 | 結論 |
|---|---|---|
| 狀態常數 | `auth/curriculum.py` L25-30（`STATUS_ACTIVE/LOCKED/COMPLETED`）、`STATE_ACTIVE/STATE_COMPLETED` | `STATE_COMPLETED = "completed"` 存在 |
| 週狀態解析 | `auth/curriculum.py` `_resolve_week_state()`（L≈340） | 8 週 statuses 全為 `completed` 時返 `(8, STATE_COMPLETED)` |
| 推進函數 | `auth/curriculum.py` `advance_week()`（L≈440，經 `_apply_advance`） | 會把完成嘅週標 `completed` 再推進下一週 |
| 消費方 | `auth/ws_chat.py:302/326`（`_CURRICULUM_ROUTE_STATES = (STATE_ACTIVE, STATE_COMPLETED)`）、`api.py`(2251/2275/2399/2752)、`student_auth.py`(343/356) | badge 對 `completed` 返 `{state:"completed", week_index:8}`；路由器接受 `completed` |

**結論：有可達嘅 `completed` 態** → 執行 Step 2（前端進度顯示修正），毋須記 known gap。

## 3. 格式 block v1.1 規格（c1-5）

1. **位置**：檔標題＋band note 之後嘅**第一節**（`## Who I Am` 之前）——prompt 越前越服從；同時刪除 c1-4 插喺 `## How I Run This Week` 之後嘅同一節。
2. **份數**：每檔 `## How I Reply` 恰 1 份（`grep -c 'How I Reply'` = 1）。
3. **四條規則**（原意保留）：① 純文字、禁 markdown 符號、任務用 `1.` `2.` 每行一個；② 只講本週（唔列全 8 週；非要全覽則 ≤5 行）；③ 短回覆——**band 單一數字**：P4-P6 檔 `Under 8 lines per reply`、S1-S3 檔 `Under 12 lines per reply`（唔再並列），收尾問 `Would you like me to continue?`；④ 一次一步、每回覆以一條問題或一個明確下一步收尾。
4. **Worked example**：`Here is an example of how I reply:` 後接 5 行示範（純文字、`1.`/`2.`/`3.` 各一個任務、收尾問句 `Shall we start with task 1?`），示範內**零 markdown 符號**（無 `#`／`*`／`-`／`---`）。
5. **結尾自檢行**：`Before sending, check: no ##, no **, no - bullets, ≤N lines, only this week.`（N = band 數字）。

一致性：P4-P6 8 份互相逐字一致、S1-S3 8 份互相逐字一致；兩組**只差 band 數字**（`Under 8/12 lines` 與自檢行 `≤8/12` 兩行）。

## 4. 16 檔新 hash（c1-5 after 值 · LF sha256）

| 檔 | LF bytes | sha256 |
|---|---|---|
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

（表內 bytes 為 LF 正規化後位元組數，與 `deeptutor/personas/README.md` manifest 逐格一致；c1-4 值見 git 歷史 `2972ccb`。）

## 5. Step 2（前端進度顯示）

`frontend/src/pages/ChatPage.tsx` welcome bubble 算式（單處改動）：

- `badge.state === 'completed'` → 顯示 **100%**；
- 其餘沿用 c1-4 公式 `Math.round((Math.max(0, week_index - 1) / 8) * 100)`（第 1 週仍 = 0%）。

對應 `KidBadge.state: 'none' | 'active' | 'completed'`（`frontend/src/lib/types.ts`）；只改此一處，未動 top-bar badge 與其他顯示邏輯。

## 6. 未做 / 已知邊界

- Plan B（frontend markdown sanitize）**未做**、亦不在本批範圍（備而不用）。
- persona 一律**只加強、不回滾**（新版為老闆批核基準）。
- 引擎 prompt 逐字字串仍不可取（引擎 log 不記 persona；「注入文本＝host 現檔」由 audit slug＋無快取＋容器 sha 吻合＋內容指紋合成之強推論）。
