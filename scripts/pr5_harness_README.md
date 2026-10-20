# PR-5 本地三语 harness

供老板按设计书 §8.3 关卡「CI ＋ 本地人工过三语」亲眼看一遍老师台与家长端。
全部数据写进一次性 SQLite（`.pr5_harness/pr5_harness.db`），**生产库零写入**。

## 两条启动命令

```powershell
# ① 重建演示数据并起后端（http://127.0.0.1:8001，Vite 代理已指向此端口）
powershell -ExecutionPolicy Bypass -File scripts/pr5_start_local.ps1 -Seed

# ② 另开一个窗口起前端（http://localhost:3000；node_modules 缺失时自动 npm ci）
powershell -ExecutionPolicy Bypass -File scripts/pr5_start_local.ps1 -Frontend
```

不带参数运行 `scripts/pr5_start_local.ps1` 等于同时起后端与前端，但**不会**重跑种子（沿用现有 DB）。

## 种子里有什么

| 项 | 值 |
|---|---|
| 老师 | `teacher@pr5.local` / `Pr5Harness!2026` |
| 家长 | `parent@pr5.local` / `Pr5Harness!2026` |
| 学生 | 陳小明（band `P4-P6`，`lang_code=zh-hk`），家长 PIN `1234` |
| 班 | PR-5 三語示範班（join code `PR5DEMO1`，P4-P6） |
| 评分 | 第 1–3 周 × 4D（DREAM / DISCOVER / DESIGN / DELIVER），0–3 ＋一句证据 |

三份报告走的是与正式 API 完全相同的代码路径（生成 → 剥内部字段 → 挂 descriptor →
建 pending → 老师批准），**week 1 = en、week 2 = zh-hk、week 3 = zh-cn**。
周区间故意各不相同：同一 (学生, 班, 周区间) 的第二份批准会 supersede 第一份（设计书 §4.1），
家长端就只剩一种语言可看。

## 走查路由

老师台（A1–A6）：`/teacher/login` → `/teacher/scores` → `/teacher/reports` →
`/teacher/reports/{report_id}`（审阅/批准/驳回） → `/teacher/crosswalk`

家长端（B1–B2）：`/parent/reports` → 点进单份只读视图；三份报告分别是 en / zh-hk / zh-cn，
切换语言即切换报告。

## 产物与清理

* 数据库：`.pr5_harness/pr5_harness.db`
* 三份已批准报告 JSON ＋ `seed_summary.json`：`.pr5_harness/reports/`
* 需要重来：再跑一次带 `-Seed` 的命令；旧 DB 会被改名成 `*.bak-时间戳` 留在原地，不删除。

## 常用参数

```powershell
.venv\Scripts\python.exe scripts/pr5_seed_local.py --help
.venv\Scripts\python.exe scripts/pr5_seed_local.py --db .pr5_harness/other.db --out .pr5_harness/other_reports
```
