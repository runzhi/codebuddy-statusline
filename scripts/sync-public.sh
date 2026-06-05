#!/usr/bin/env bash
# Sync master → github/main
#
# Usage: bash scripts/sync-public.sh
#
# Pushes master directly to GitHub, preserving full commit history.
# No URL replacement needed — install scripts auto-detect the repo remote,
# and README lists both internal and external URLs.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

echo "=== Syncing master → github/main ==="
git push github master:main

echo ""
echo "✓ Sync complete: master → github/main (history preserved)"
