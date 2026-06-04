#!/usr/bin/env bash
# Sync master → public branch and push to GitHub
#
# Usage: bash scripts/sync-public.sh
#
# Creates an orphan public branch from master files, replaces internal URLs
# with github.com, removes internal-only files, and force-pushes as a single
# clean commit to github/main.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

CURRENT_BRANCH=$(git branch --show-current)
echo "=== Syncing master → public → github/main ==="

# Ensure on master
if [ "$CURRENT_BRANCH" != "master" ]; then
  echo "Switching to master..."
  git checkout master
fi

# Create orphan public branch from scratch
echo "[1/3] Creating orphan public branch..."
git branch -D public-tmp 2>/dev/null || true
git checkout --orphan public-tmp
git rm -rf --cached . 2>/dev/null || true
git checkout master -- .

# Replace URLs
echo "[2/3] Prepping for GitHub..."
sed -i '' 's|https://git\.woa\.com/four-harness/codebuddy-statusline\.git|https://github.com/runzhi/codebuddy-statusline.git|g' \
  README.md install.sh install.ps1
rm -f scripts/sync-public.sh

# Commit and push
echo "[3/3] Pushing clean history to GitHub..."
git add -A
git commit -m "CodeBuddy Statusline - public release

A real-time statusline plugin for CodeBuddy Code, displaying context
progress, token usage, tool calls, and cost in your terminal."
git branch -D public 2>/dev/null || true
git branch -m public-tmp public
git push -f github public:main

# Restore
git checkout "$CURRENT_BRANCH"

echo ""
echo "✓ Sync complete: master → public → github/main"
