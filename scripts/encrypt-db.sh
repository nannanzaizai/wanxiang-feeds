#!/usr/bin/env bash
# 万象 · wewe-rss 登录态加密工具
#
# 为什么需要它：
#   wewe-rss 的 data/wewe-rss.db 里存着「微信读书」登录 cookie —— 这是敏感数据，
#   直接提交到公开仓库等于把登录态公开。本脚本把它加密成 .db.enc 后才入库，
#   Actions 里再用 GitHub Secret 里的口令解密（明文只在运行时存在，不落仓库）。
#
# 用法：
#   ./scripts/encrypt-db.sh ~/wewe-rss/data/wewe-rss.db
#   ./scripts/encrypt-db.sh ~/wewe-rss/data/wewe-rss.db data/wewe-rss.db.enc
#
# 口令要求：12 位以上，建议纯字母数字（中文输入法全角符号易导致解密失败）。
#           同一口令要配到 GitHub 仓库的 Secret `WEWE_DB_PASS`。
set -euo pipefail

SRC="${1:-}"
OUT="${2:-data/wewe-rss.db.enc}"

if [ -z "$SRC" ]; then
  echo "用法: $0 <明文的 wewe-rss.db 路径> [输出 .enc 路径]" >&2
  echo "示例: $0 ~/wewe-rss/data/wewe-rss.db" >&2
  exit 1
fi
[ -f "$SRC" ] || { echo "❌ 找不到明文数据库: $SRC" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || { echo "❌ 未找到 openssl" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"

cat <<'TIP'
──────────────────────────────────────────────
即将加密 wewe-rss 登录态。请按提示输入两遍口令。
  口令要求：12 位以上，建议纯字母数字
  之后要把同一口令配到 GitHub Secret: WEWE_DB_PASS
──────────────────────────────────────────────
TIP

openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt -in "$SRC" -out "$OUT"

echo
ls -lh "$OUT" | awk '{print "  产物:", $9, $5}'
echo "✅ 加密完成。接下来："
echo "   git add $OUT"
echo "   git commit -m 'add: wewe-rss 登录态（加密）'"
echo "   git push"
echo
echo "   注意：明文 *.db 已被 .gitignore 挡住，不会被提交。"
