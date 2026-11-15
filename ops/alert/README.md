---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 78373afc8115dcc55e8ceaf91b4b85d2_671da9a9e0c811f1913b525400393706
    ReservedCode1: q9egyFLYO1vbP8mEdnYfYCQjtao2i1WbCNKyrAV42neufrFaDKWFDuZeXGYjPd2yfWpy8aOdNkck1Xq2TEPhTYJNbtSxANAGVkOd5QsPaqSUS17SCFB/Zy81GHizxAIHCwM3rizAYEUISomDAa2TqZ3TgxfUjhXCOyshPmjXCFyj1yuNIfGBMA9EVY8=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 78373afc8115dcc55e8ceaf91b4b85d2_671da9a9e0c811f1913b525400393706
    ReservedCode2: q9egyFLYO1vbP8mEdnYfYCQjtao2i1WbCNKyrAV42neufrFaDKWFDuZeXGYjPd2yfWpy8aOdNkck1Xq2TEPhTYJNbtSxANAGVkOd5QsPaqSUS17SCFB/Zy81GHizxAIHCwM3rizAYEUISomDAa2TqZ3TgxfUjhXCOyshPmjXCFyj1yuNIfGBMA9EVY8=
---

# P2 告警 Email（msmtp）— 規格 v1.0（未接通）

狀態：**規格與腳本就緒；VPS 未安裝 msmtp，未寫入任何憑證**
依據：令_走查GO與並行軌三選型_把關人_20261115
接通條件：老板提供一組**低權限發件賬密**（Gmail app password 或 Resend SMTP 憑證）

## 一、為什麼不是自建 MTA

自建 postfix 需 PTR / SPF / DKIM / DMARC 全套，且與 `dreamer-aiedu.com`（Cloudflare DNS）郵件信譽綁定，
一旦被列黑會波及註冊驗證信與邀請通知信（同一域名）。故取「外部 SMTP 中繼 + msmtp」最短路徑。

## 二、落地步驟（凭證到位後執行，逐條留證）

| # | 動作 | 命令/檔案 | 驗收 |
|---|---|---|---|
| 1 | 安裝 msmtp | `apt-get install -y msmtp msmtp-mta ca-certificates` | `msmtp --version` 有輸出 |
| 2 | 憑證落位 | `/etc/msmtprc`（root:root 600），由 `msmtprc.template` 渲染 | `ls -l /etc/msmtprc` 權限 600 |
| 3 | 別名 | `/etc/aliases`：`root: alert@…`，`newaliases` | `echo test \| mail -s t root` 可收 |
| 4 | 冒煙 | `alert_send.sh --subject "SMTP 冒煙" --body "probe"` | 收件箱實收一封 |
| 5 | 接入 | `health_monitor_cron.sh` 的失敗分支調 `alert_send.sh` | 人為觸發一次 FAIL 能收到信 |

## 三、發件賬號最小權限要求

- **不得**使用 `deeptutor` 服務帳號、`root`、或任何與 GHCR / Cloudflare 共用之帳密。
- Gmail 路線：需先開 2FA，用 app password；From 固定為該 Gmail 地址（否則會被 SPF 拒）。
- Resend 路線：用 API key 生成的 SMTP 憑證（host `smtp.resend.com`，port 587，user `resend`），
  From 必須是已在 Resend 驗證的域名（建議 `alerts.dreamer-aiedu.com`，與主域隔離信譽）。
- 建議單獨開一個 `alert@` 用途帳號，只授予發信權。

## 四、告警內容口徑（避免假綠）

- 告警必須帶：時間（UTC+8）、檢查項、預期值、實際值、最近一次成功時間。
- 明確禁止：以 `/health` 200 作為「服務健康」的唯一判據（歷史假綠之鑑，`/health` 由靜態前端承載）。
- 真實健康判據：`/api/auth/me` 匿名應 **401**、`/api/classes` 匿名應 **401**、DB 可讀且 27 表 counts 可取。

## 五、未接通前

`alert_send.sh` 在無 `/etc/msmtprc` 或無 `ALERT_SMTP_READY=1` 時一律 **dry-run**（打印郵件全文、退出碼 3），
不會嘗試任何網絡外發，也不會在 VPS 安裝任何套件。
*（内容由AI生成，仅供参考）*
