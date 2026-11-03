#!/bin/bash
# 首次部署：建仓库 + 推 + 开 Pages（main /docs）
set -euo pipefail
cd /root/free-radar
REPO="${1:-free-radar}"

if [ ! -d .git ]; then
  git init -q
  git -c user.name="freezetheflame" -c user.email="1439921564@qq.com" add -A
  git -c user.name="freezetheflame" -c user.email="1439921564@qq.com" commit -qm "feat: free-radar MVP — 官方页面证据句 + 变更检测"
fi

gh repo create "freezetheflame/$REPO" --public --source=. --remote=origin --push 2>/dev/null || {
  git remote add origin "git@github.com:freezetheflame/$REPO.git" 2>/dev/null || true
  git push -u origin main
}

# 开启 Pages（已开则更新）
gh api -X POST "repos/freezetheflame/$REPO/pages" \
  -f 'source[branch]=main' -f 'source[path]=/docs' 2>/dev/null || \
gh api -X PUT "repos/freezetheflame/$REPO/pages" \
  -f 'source[branch]=main' -f 'source[path]=/docs' 2>/dev/null || true

echo "https://freezetheflame.github.io/$REPO/"
