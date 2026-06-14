#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

PLUGIN_DIR="$HOME/.codebuddy/statusline"
CACHE_DIR="$HOME/.codebuddy/statusline-cache"
SETTINGS_FILE="$HOME/.codebuddy/settings.json"

# Resolve python command — must verify it actually runs
_resolve_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON=$(_resolve_python)

# Detect platform
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    IS_WINDOWS=1
    SETTINGS_PATH=$(cygpath -w "$SETTINGS_FILE" 2>/dev/null || echo "$SETTINGS_FILE")
else
    IS_WINDOWS=0
    SETTINGS_PATH="$SETTINGS_FILE"
fi

echo -e "${CYAN}=== CodeBuddy Statusline Uninstaller ===${NC}"
echo ""

# 1. Remove statusLine from settings.json
echo -e "${YELLOW}[1/3]${NC} Removing statusLine config from settings.json..."
if [ -f "$SETTINGS_FILE" ]; then
    if [ -z "$PYTHON" ]; then
        echo -e "  ${RED}No working Python found, cannot clean settings.json automatically${NC}"
    else
        # Use a temp helper script + sys.argv to avoid interpolating shell
        # variables into Python string literals (injection risk if the path
        # contains quotes/backslashes).
        _UNINSTALL_HELPER=$(mktemp -t codebuddy-statusline-uninst.XXXXXX)
        trap 'rm -f "$_UNINSTALL_HELPER"' EXIT
        cat > "$_UNINSTALL_HELPER" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    settings = json.load(f)
if 'statusLine' in settings:
    cmd = settings['statusLine'].get('command', '')
    if 'statusline' in cmd or 'cost-monitor' in cmd:
        del settings['statusLine']
        with open(path, 'w') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print('removed')
    else:
        print('foreign')
else:
    print('absent')
PY

        case "$("$PYTHON" "$_UNINSTALL_HELPER" "$SETTINGS_PATH" 2>/dev/null)" in
            removed)  echo -e "  ${GREEN}Removed statusLine config${NC}" ;;
            foreign)  echo -e "  ${YELLOW}statusLine exists but not ours, skipping${NC}" ;;
            absent)   echo -e "  No statusLine config found, skipping" ;;
            *)        echo -e "  ${YELLOW}Unexpected helper output${NC}" ;;
        esac
    fi
fi

# 2. Remove plugin files
echo -e "${YELLOW}[2/3]${NC} Removing plugin files..."
rm -rf "$PLUGIN_DIR"
# Also clean up old cost-monitor directory if present
rm -rf "$HOME/.codebuddy/cost-monitor"
echo "  Done"

# 3. Remove cache
echo -e "${YELLOW}[3/3]${NC} Removing cache..."
rm -rf "$CACHE_DIR"
rm -rf "$HOME/.codebuddy/cost-monitor-cache"
echo "  Done"

echo ""
echo -e "${GREEN}=== Uninstallation complete! ===${NC}"
