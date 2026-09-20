#!/usr/bin/env bash
# 万象 · 一键发布到 GitHub（薄包装）
#
# 真正的逻辑在同目录的 push-to-github.py —— 它做完整流程：
#   验证 token → 建仓（API，不用点网页）→ 凭据门禁 → 推送 → 触发 Actions → 验证产物
#
# 用法（两种等价）：
#   python3 push-to-github.py
#   bash push-to-github.sh
#
# 常用参数：
#   bash push-to-github.sh --dry-run      # 只检查环境/仓库/门禁，不写任何东西
#   bash push-to-github.sh --skip-verify  # 推完就走，不等待 Actions 结果
#
# ⚠️ 不再需要传「GitHub 用户名」—— 账号名由 token 自动识别。
#    旧写法 `bash push-to-github.sh nannanzaizai` 里的用户名请去掉。
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "❌ 未找到 $PY" >&2
  echo "   可显式指定：PYTHON=/Users/liying/miniforge3/bin/python3 bash push-to-github.sh" >&2
  exit 1
fi

# 兼容旧用法：把用户名当第一个位置参数传了进来
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  echo "⚠️  现在不需要传用户名（由 token 自动识别账号），已忽略参数：$1"
  shift
fi

exec "$PY" push-to-github.py "$@"
