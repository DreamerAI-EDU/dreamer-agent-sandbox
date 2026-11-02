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

## 8001 被 deeptutor 容器占用时

`dreamer-deeptutor` 容器常驻并映射 `127.0.0.1:8000-8001`，此时 PR-5 后端无法占用 8001。
后端端口由 `scripts/pr5_start_local.ps1` 的 `-Port` 控制（优先级：`-Port` > `$env:PR5_PORT` > `8001`），
前端代理目标由 `frontend/vite.config.ts` 读 `VITE_PROXY_TARGET`（默认仍是 `http://localhost:8001`，
不设该变量时行为与以往完全一致）。两边都要改，缺一边代理就会打到容器上去：

```powershell
# ① 后端换到 8002（沿用现有 DB，不加 -Seed 就不会重跑种子）
powershell -ExecutionPolicy Bypass -File scripts\pr5_start_local.ps1 -Backend -Port 8002

# ② 另开窗口：先把代理指到 8002，再起前端
$env:VITE_PROXY_TARGET = 'http://127.0.0.1:8002'
powershell -ExecutionPolicy Bypass -File scripts\pr5_start_local.ps1 -Frontend
```

验证代理确实打到 PR-5 后端而不是容器：未登入时经 3000 端口访问受保护接口应得 401，
若拿到容器的响应就说明 `VITE_PROXY_TARGET` 没生效（Vite 只在启动时读一次该变量，改完必须重启 dev server）。

```powershell
Invoke-WebRequest http://localhost:3000/api/teacher/reports -SkipHttpErrorCheck |
    Select-Object StatusCode
```

也可以一次性把两端都起在同一窗口（前端为前台阻塞，`Ctrl+C` 结束）：

```powershell
$env:VITE_PROXY_TARGET = 'http://127.0.0.1:8002'
powershell -ExecutionPolicy Bypass -File scripts\pr5_start_local.ps1 -Port 8002
```


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
