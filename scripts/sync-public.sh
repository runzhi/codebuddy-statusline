#!/usr/bin/env bash
# Sync master → public branch and push to GitHub
#
# Usage: bash scripts/sync-public.sh
#
# This script:
# 1. Recreates public branch from master
# 2. Replaces git.woa.com URLs → github.com URLs
# 3. Removes internal-only files (this script itself)
# 4. Force-pushes public → github/main as a single clean commit

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

CURRENT_BRANCH=$(git branch --show-current)
echo "=== Syncing master → public → github/main ==="

# Ensure master is up to date
if [ "$CURRENT_BRANCH" != "master" ]; then
  echo "Switching to master..."
  git checkout master
fi

# Delete old public branch and recreate
echo "[1/4] Recreating public branch from master..."
git branch -D public 2>/dev/null || true
git checkout -b public

# Replace URLs
echo "[2/4] Replacing URLs for GitHub..."
sed -i '' 's|https://git\.woa\.com/four-harness/codebuddy-statusline\.git|https://github.com/runzhi/codebuddy-statusline.git|g' \
  README.md install.sh install.ps1

# Remove internal-only files
echo "[3/4] Removing internal-only files..."
if [ -f scripts/sync-public.sh ]; then
  rm -f scripts/sync-public.sh
fi

# Amend the initial commit with all changes
echo "[4/4] Pushing clean history to GitHub..."
git add -A
git commit --amend -m "CodeBuddy Statusline - public release

A real-time statusline plugin for CodeBuddy Code, displaying context
progress, token usage, tool calls, and cost in your terminal."
git push -f github public:main

# Restore original branch
git checkout "$CURRENT_BRANCH"

echo ""
echo "✓ Sync complete: master → public → github/main"
