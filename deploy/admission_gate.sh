#!/usr/bin/env bash
# deploy/admission_gate.sh — 新鏡像准入閘門 v1.0（P1）
# 用途：部署前比對實際 image id 與 deploy/image-whitelist.txt；不符即 exit 90。
# 安全：本腳本只做「讀取 + 比對 + 退出碼」，不含任何 build / push / docker load 動作。
#
# 用法：
#   ./deploy/admission_gate.sh verify  <image_ref>        # image_ref 例：ghcr.io/dreamerai-edu/dreamer-api:d8-1
#   ./deploy/admission_gate.sh list                       # 列出白名單生效行
#   ./deploy/admission_gate.sh record <commit> <image_ref> <image_tar_sha256> <signed_by>
#                                                         # 只印出待貼入的兩行（不寫檔、不開 PR）
#
# 退出碼：0 通過 / 90 image id 不在白名單 / 91 白名單格式異常 / 92 缺前置條件

set -uo pipefail

WHITELIST="$(dirname "$0")/image-whitelist.txt"
EXIT_GATE=90
EXIT_FORMAT=91
EXIT_PRECOND=92

die() { echo "[GATE] FAIL: $2" >&2; exit "$1"; }
ok()  { echo "[GATE] OK: $1"; }

active_lines() {
  # 跳過註解與空行
  grep -vE '^[[:space:]]*(#|$)' "$WHITELIST"
}

cmd_list() {
  [ -f "$WHITELIST" ] || die $EXIT_PRECOND "白名單檔不存在：$WHITELIST"
  active_lines | awk '{printf "%-10s %s %s\n", $1, $2, $3}'
}

cmd_verify() {
  local ref="${1:-}"
  [ -n "$ref" ] || die $EXIT_PRECOND "用法：admission_gate.sh verify <image_ref>"
  [ -f "$WHITELIST" ] || die $EXIT_PRECOND "白名單檔不存在：$WHITELIST"
  command -v docker >/dev/null 2>&1 || die $EXIT_PRECOND "找不到 docker"

  local actual
  actual="$(docker inspect --format '{{.Id}}' "$ref" 2>/dev/null)"
  [ -n "$actual" ] || die $EXIT_PRECOND "無法取得 image id：$ref（image 未載入？）"

  if active_lines | awk '{print $2}' | grep -Fxq "$actual"; then
    ok "image id $actual 已於白名單，准予部署（ref=$ref）"
    return 0
  fi

  echo "[GATE] 白名單生效行：" >&2
  active_lines | awk '{print "  " $1, $2, $3}' >&2
  die $EXIT_GATE "image id $actual 不在白名單，停止部署（ref=$ref）"
}

cmd_record() {
  local commit="${1:-}" ref="${2:-}" tarsha="${3:-}" signer="${4:-}"
  [ -n "$commit" ] && [ -n "$ref" ] && [ -n "$tarsha" ] && [ -n "$signer" ] \
    || die $EXIT_PRECOND "用法：admission_gate.sh record <commit> <image_ref> <image_tar_sha256> <signed_by>"

  local image_id base_digest utc
  image_id="$(docker inspect --format '{{.Id}}' "$ref" 2>/dev/null)"
  [ -n "$image_id" ] || die $EXIT_PRECOND "無法取得 image id：$ref"
  base_digest="$(docker image inspect --format '{{index .Config.Labels "base.digest"}}' "$ref" 2>/dev/null)"
  [ -n "$base_digest" ] || base_digest="<需由 CI 記錄；禁 :latest>"
  utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  echo "# 貼入 deploy/image-whitelist.txt（只增一行）：" >&2
  echo "$commit  $image_id  $ref  $utc  $signer" >&2
  echo "# 貼入 deploy/IMAGE_ALLOWLIST.md 准入記錄表（只增一行）：" >&2
  echo "| v?-? | $commit | $base_digest | $image_id | $tarsha | $signer | $utc |" >&2
  echo "[GATE] 本命令未寫入任何檔案，需人工走 PR。" >&2
}

case "${1:-}" in
  verify) shift; cmd_verify "$@" ;;
  list)   cmd_list ;;
  record) shift; cmd_record "$@" ;;
  *) echo "用法：$0 {verify <image_ref>|list|record <commit> <image_ref> <image_tar_sha256> <signed_by>}" >&2; exit $EXIT_PRECOND ;;
esac
