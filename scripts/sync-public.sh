#!/usr/bin/env bash
# Sync master → public branch and push to GitHub
#
# Usage: bash scripts/sync-public.sh
#
# This script:
# 1. Rebase public on top of master
# 2. Replace git.woa.com URLs → github.com URLs
# 3. Push public to GitHub

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

CURRENT_BRANCH=$(git branch --show-current)
echo "=== Syncing master → public ==="

# Stash any uncommitted changes
if ! git diff-index --quiet HEAD --; then
  echo "Stashing uncommitted changes..."
  git stash push -m "sync-public auto stash"
  STASHED=true
fi

# Switch to public and rebase on master
echo "[1/3] Rebasing public on master..."
git checkout public
git rebase master

# Replace URLs
echo "[2/3] Replacing URLs for GitHub..."
sed -i '' 's|https://git\.woa\.com/four-harness/codebuddy-statusline\.git|https://github.com/runzhi/codebuddy-statusline.git|g' \
  README.md install.sh install.ps1

# Check if there are changes to commit
if git diff --quiet; then
  echo "  URL already up-to-date, skipping commit."
else
  git add README.md install.sh install.ps1
  git commit -m "Public: github.com URLs" --allow-empty
fi

# Push
echo "[3/3] Pushing public to GitHub..."
git push github public

# Restore original branch
git checkout "$CURRENT_BRANCH"
if [ "$STASHED" = true ]; then
  git stash pop
fi

echo ""
echo "✓ Sync complete: master → public → github.com"
