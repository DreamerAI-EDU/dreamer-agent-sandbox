#!/usr/bin/env bash
# ops/alert/alert_send.sh — 告警發信 v1.0（P2）
# 安全設計：未接通時 dry-run，不外發、不裝套件、不讀取任何未顯式提供的憑證。
#
# 用法：
#   ALERT_SMTP_READY=1 ./alert_send.sh --subject "主題" --body "正文" [--to a@b.com]
#   未設 ALERT_SMTP_READY=1 或 /etc/msmtprc 不存在 → dry-run，退出碼 3。
#
# 退出碼：0 已交寄 / 2 交寄失敗 / 3 dry-run（未接通）/ 4 參數錯

set -uo pipefail

TO="${ALERT_TO:-}"
SUBJECT=""
BODY=""
MSMTP_CONF="/etc/msmtprc"
MAIL_BIN="$(command -v msmtp || true)"

while [ $# -gt 0 ]; do
  case "$1" in
    --to)      TO="${2:-}"; shift 2 ;;
    --subject) SUBJECT="${2:-}"; shift 2 ;;
    --body)    BODY="${2:-}"; shift 2 ;;
    *) echo "未知參數：$1" >&2; exit 4 ;;
  esac
done

[ -n "$SUBJECT" ] || { echo "缺少 --subject" >&2; exit 4; }
[ -n "$BODY" ] || BODY="(無正文)"
[ -n "$TO" ] || { echo "缺少收件人（--to 或 ALERT_TO）" >&2; exit 4; }

NOW_HKT="$(TZ=Asia/Hong_Kong date '+%Y-%m-%dT%H:%M:%S%z')"
HOST="$(hostname)"

render() {
cat <<EOF
From: dreamer-alert <${ALERT_FROM:-alert@localhost}>
To: ${TO}
Subject: [Dreamer ${HOST}] ${SUBJECT}
Date: $(date -R)
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8

時間(HKT): ${NOW_HKT}
主機: ${HOST}
檢查項: ${ALERT_CHECK:-n/a}
預期: ${ALERT_EXPECT:-n/a}
實際: ${ALERT_ACTUAL:-n/a}
最近成功: ${ALERT_LAST_OK:-n/a}

${BODY}
EOF
}

if [ "${ALERT_SMTP_READY:-0}" != "1" ] || [ ! -f "$MSMTP_CONF" ] || [ -z "$MAIL_BIN" ]; then
  echo "[ALERT] DRY-RUN（未接通：ALERT_SMTP_READY / $MSMTP_CONF / msmtp 任一缺失）" >&2
  render
  exit 3
fi

if render | "$MAIL_BIN" -a default -f "${ALERT_FROM:-}" "$TO"; then
  echo "[ALERT] SENT to $TO" >&2
  exit 0
fi
echo "[ALERT] SEND FAILED to $TO" >&2
exit 2
