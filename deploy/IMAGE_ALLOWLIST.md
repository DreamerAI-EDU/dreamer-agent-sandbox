# IMAGE ALLOWLIST — 准入記錄（P1，GHCR ＋ 細粒度 PAT）

狀態：**規格定稿 v1.0；未接通**（GHCR push 憑證未到位，見「待接通行」）
生效日：2026-11-15　依據：令_走查GO與並行軌三選型_把關人_20261115

## 一、白名單實檔

- 路徑：`deploy/image-whitelist.txt`（repo 根相對）
- 語義：**只增不改**；`b7c42d9` 為回滾錨點，永不除名
- 校驗入口：`deploy/admission_gate.sh verify`（部署前必跑，不符 `exit 90`）

## 二、新鏡像五步准入（缺一不得部署）

| 步 | 動作 | 產出 | 卡點 |
|---|---|---|---|
| 1 build | 以 `git rev-parse --short HEAD` 對應 commit 於 CI 構建，**禁止**本地 `docker build` 直推生產 | CI run URL + commit | 本地構建一律視為未准入 |
| 2 可復現 | 同 commit 二次構建，記錄 build args、base image **digest 釘死**（禁 `:latest`）、兩次產出 image ID 對照 | 對照表，兩次 image ID 必須一致 | 不一致即退回，不得進入第 3 步 |
| 3 簽 sha | `docker save` → `sha256sum` → `image.tar.sha256` | `image_tar_sha256` | 簽署人與 UTC 必須同時記錄 |
| 4 加白 | PR 新增 `deploy/image-whitelist.txt` 一行 + 本檔准入記錄一行 | PR 連結 | PR 描述必附第 3 步 sha 與第 1 步 commit |
| 5 部署比對 | 部署腳本 `docker load`/`pull` 後比對 `docker inspect --format '{{.Id}}'` 與白名單 | 部署記錄回寫實際 image ID | **不符 `exit 90`，不得啟動** |

## 三、准入記錄（append-only）

| version | commit | base_digest | image_id | image_tar_sha256 | signed_by | utc |
|---|---|---|---|---|---|---|
| v0.1-bootstrap | b7c42d9 | python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f | sha256:e59c0e763b3b104a673e6701fe466b3a8121adc54d934a70f310b6bc13fd57aa | （bootstrap 錨點，未經五步流程，僅作回滾基線） | 把關人 | 2026-11-15T07:45:00Z |

## 四、D8-1 首個適用

D8-1 新鏡像 = 本流程的第一個真實案例。**D8-1 部署之前 P1 必須落地**，否則閘門自鎖。
D8-1 准入時第 3 步的 `image_tar_sha256` 由 CI 產出，第 4 步 PR 由老板或授權代簽人簽署。

## 五、待接通行（硬依賴）

1. **fine-grained PAT**：scope 僅 `write:packages`，僅指向 repo `ghcr.io/dreamerai-edu/dreamer-api`；有效期建議 90 天並記錄到期日。
2. 現有 GHCR 倉庫已存在且已有多 tag（b7c42d9 / 6ac2576 / e6c162c …），無需新建倉庫，只需推送憑證。
3. 未接通前：本軌只寫流程與腳本，**不執行任何 push、不改 compose 引用來源**。
