#!/usr/bin/env bash
# Idempotent setup script for codebuddy-statusline plugin
# Called by SessionStart hook - safe to run multiple times

set -euo pipefail

PLUGIN_ROOT="${CODEBUDDY_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}"
CACHE_BASE="${CODEBUDDY_PLUGIN_DATA:-$HOME/.codebuddy/plugins/data/statusline}"
CACHE_DIR="${CACHE_BASE}/cache"
SETTINGS_FILE="$HOME/.codebuddy/settings.json"

# 1. Check python3
if ! command -v python3 &>/dev/null; then
  echo "WARNING: python3 not found. Statusline requires Python 3." >&2
  exit 0  # Don't block session start
fi

# 2. Create cache directory
mkdir -p "$CACHE_DIR"

# 3. Configure statusLine in settings.json (idempotent)
EXPECTED_CMD="python3 ${PLUGIN_ROOT}/statusline.py"

if [ ! -f "$SETTINGS_FILE" ]; then
  mkdir -p "$(dirname "$SETTINGS_FILE")"
  cat > "$SETTINGS_FILE" <<EOF
{
  "statusLine": {
    "type": "command",
    "command": "$EXPECTED_CMD",
    "padding": 0
  }
}
EOF
else
  python3 -c "
import json, sys

path = '$SETTINGS_FILE'
expected_cmd = '$EXPECTED_CMD'

with open(path) as f:
    settings = json.load(f)

sl = settings.get('statusLine', {})
current_cmd = sl.get('command', '')

if current_cmd == expected_cmd:
    sys.exit(0)  # already configured correctly

settings['statusLine'] = {
    'type': 'command',
    'command': expected_cmd,
    'padding': 0
}

with open(path, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
"
fi
