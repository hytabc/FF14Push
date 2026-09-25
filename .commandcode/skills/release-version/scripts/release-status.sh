#!/usr/bin/env sh
# 发布前状态速览：当前版本标题、未提交 git 的更新日志条目、各版本号字段。
# 用法：sh .commandcode/skills/release-version/scripts/release-status.sh
set -e
root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$root"

echo "== CHANGELOG 版本标题（最新在上）=="
grep -n '^## ' CHANGELOG.md | head -5

echo
echo "== 未提交的更新日志条目（应移动到新版本下）=="
{ git diff -U0 -- CHANGELOG.md; git diff --cached -U0 -- CHANGELOG.md; } 2>/dev/null \
  | grep -E '^\+-[^+]' \
  || echo "（无未提交条目）"

echo
echo "== 当前版本号字段 =="
grep -n '"version"' package.json frontend/package.json
grep -n '^version' backend/pyproject.toml
grep -n 'version="[0-9]' backend/app/main.py
