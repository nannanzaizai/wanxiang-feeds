#!/usr/bin/env bash
# 万象 · 一键推送到 GitHub（自动跑凭据门禁，过不了就不推）
#
# 用法：
#   bash push-to-github.sh <你的GitHub用户名>
# 例：
#   bash push-to-github.sh nannanzaizai
#
# 前提：你已经在 GitHub 建好**公开**仓库 wanxiang-feeds，且三项 Initialize 都没勾。
set -euo pipefail

GH_USER="${1:-}"
if [ -z "$GH_USER" ]; then
  echo "用法: bash push-to-github.sh <你的GitHub用户名>" >&2
  echo "例:   bash push-to-github.sh nannanzaizai" >&2
  exit 1
fi

REPO="wanxiang-feeds"
PY="${PYTHON:-python3}"

echo "══════════════════════════════════════════"
echo " 万象 · 推送到 GitHub（含凭据门禁）"
echo " 目标: https://github.com/${GH_USER}/${REPO}"
echo "══════════════════════════════════════════"
echo

echo "① 门禁自检（工具本身可信吗）"
"$PY" scripts/scan-secrets.py --selftest || { echo "❌ 自检失败，中止"; exit 1; }
echo

echo "② 初始化并暂存"
[ -d .git ] || git init -q
git add -A
echo "   暂存 $(git diff --cached --name-only | wc -l | tr -d ' ') 个文件"
echo

echo "③ 门禁扫描（先 add 再扫，否则新增文件会被漏掉）"
if ! "$PY" scripts/scan-secrets.py . --tracked; then
  echo
  echo "❌ 门禁未过：上面标 🔴 的内容会被 git 跟踪，必须先处理。"
  echo "   处理完再跑一次本脚本即可。"
  exit 1
fi
echo

echo "④ 提交"
if git diff --cached --quiet; then
  echo "   无新变化，跳过提交"
else
  git -c user.name="wanxiang-bot" \
      -c user.email="wanxiang-bot@users.noreply.github.com" \
      commit -q -m "init: 万象信息源构建（GitHub Actions 定时抓取 → JSON Feed）"
  echo "   已提交: $(git log --oneline | head -1)"
fi
echo

echo "⑤ 关联远程并推送"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GH_USER}/${REPO}.git"
echo "   远程: $(git remote get-url origin)"
echo "   推送中（首次可能要求登录，用 Personal Access Token 当密码）..."
git push -u origin main
echo
echo "══════════════════════════════════════════"
echo "✅ 推送完成"
echo
echo "接下来去仓库跑一次验证："
echo "  https://github.com/${GH_USER}/${REPO}/actions"
echo "  左侧选「更新万象信息源」→ 右侧 Run workflow"
echo "  约 3~6 分钟后 feeds/ 目录会被更新"
echo "══════════════════════════════════════════"
