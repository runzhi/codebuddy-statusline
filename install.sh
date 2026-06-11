#!/usr/bin/env bash
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

PLUGIN_DIR="$HOME/.codebuddy/statusline"
SETTINGS_FILE="$HOME/.codebuddy/settings.json"
REPO_URL="${1:-}"
if [ -z "$REPO_URL" ] && [ -d "$PLUGIN_DIR/.git" ]; then
    REPO_URL=$(git -C "$PLUGIN_DIR" remote get-url origin 2>/dev/null || echo "")
fi
: "${REPO_URL:=https://github.com/runzhi/codebuddy-statusline.git}"

# Resolve python command — must verify it actually runs
# (Windows Store 'python3' stub exists but exits with code 49 without running)
# Also enforce Python 3.6+ (required by statusline.py).
# Prints two lines on success: <command> and <major.minor version>
_resolve_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>/dev/null) || continue
            local major=${ver%% *}
            local minor=${ver##* }
            # Require >= 3.6 (Python 4+ is fine)
            if [ "${major:-0}" -ge 4 ] 2>/dev/null || { [ "$major" = 3 ] && [ "${minor:-0}" -ge 6 ]; }; then
                echo "$cmd"
                echo "$major.$minor"
                return 0
            fi
        fi
    done
    return 1
}

if _py_out=$(_resolve_python); then
    PYTHON=$(printf '%s' "$_py_out" | sed -n '1p')
    PYTHON_VERSION=$(printf '%s' "$_py_out" | sed -n '2p')
    unset _py_out
else
    echo -e "${RED}Error: Python 3.6+ is required but was not found.${NC}" >&2
    echo -e "${RED}Please install Python 3.6 or newer (https://www.python.org/downloads/).${NC}" >&2
    exit 1
fi

# Detect platform
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    IS_WINDOWS=1
else
    IS_WINDOWS=0
fi

echo -e "${CYAN}=== CodeBuddy Statusline Installer ===${NC}"
echo ""

# 1. Check dependencies
echo -e "${YELLOW}[1/4]${NC} Checking dependencies..."
echo -e "  python ($PYTHON $PYTHON_VERSION): ${GREEN}OK${NC}"

# 2. Clone / update plugin files
echo ""
echo -e "${YELLOW}[2/4]${NC} Installing plugin files..."

if [ -d "$PLUGIN_DIR/.git" ]; then
    echo "  Updating existing installation..."
    cd "$PLUGIN_DIR" && git pull --ff-only
else
    echo "  Cloning from $REPO_URL ..."
    rm -rf "$PLUGIN_DIR" 2>/dev/null || true
    git clone "$REPO_URL" "$PLUGIN_DIR"
fi

# chmod is a no-op on Windows but won't error; skip silently there
if [ "$IS_WINDOWS" != "1" ]; then
    chmod +x "$PLUGIN_DIR/statusline.py" "$PLUGIN_DIR/cost-detail.py"
fi
echo -e "  ${GREEN}Done${NC}"

# 3. Create cache directory
echo ""
echo -e "${YELLOW}[3/4]${NC} Setting up cache directory..."
mkdir -p "$HOME/.codebuddy/statusline-cache"
echo -e "  ${GREEN}Done${NC}"

# 4. Configure statusline in settings.json
echo ""
echo -e "${YELLOW}[4/4]${NC} Configuring statusline in settings.json..."

# Build the statusline command with the correct python binary and path format
if [ "$IS_WINDOWS" = "1" ]; then
    # Use Windows-style path for the command so CodeBuddy can execute it
    WIN_PLUGIN_DIR=$(cygpath -w "$HOME/.codebuddy/statusline")
    STATUSLINE_CMD="$PYTHON \"${WIN_PLUGIN_DIR}\\statusline.py\""
    # Python on Windows needs Windows-style paths, not MSYS /c/... paths
    SETTINGS_PATH=$(cygpath -w "$SETTINGS_FILE")
else
    STATUSLINE_CMD="$PYTHON ~/.codebuddy/statusline/statusline.py"
    SETTINGS_PATH="$SETTINGS_FILE"
fi

if [ ! -f "$SETTINGS_FILE" ]; then
    # Create new settings file
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    cat > "$SETTINGS_FILE" <<SETTINGS
{
  "statusLine": {
    "type": "command",
    "command": "$STATUSLINE_CMD",
    "padding": 0
  }
}
SETTINGS
    echo -e "  ${GREEN}Created settings.json with statusLine config${NC}"
else
    # Check if statusLine already configured — use a temp helper to avoid
    # interpolating shell variables into Python -c snippets (injection risk).
    _SETTINGS_HELPER=$(mktemp -t codebuddy-statusline.XXXXXX)
    trap 'rm -f "$_SETTINGS_HELPER"' EXIT
    cat > "$_SETTINGS_HELPER" <<'PY'
import json, os, sys
path = sys.argv[1]
status_cmd = sys.argv[2]
is_new = not os.path.exists(path)
s = {}
if not is_new:
    with open(path) as f:
        s = json.load(f)
sl = s.get('statusLine', {})
existing = sl.get('command', '')
if 'statusline' in existing or 'cost-monitor' in existing:
    print('configured')
else:
    s['statusLine'] = {
        'type': 'command',
        'command': status_cmd,
        'padding': 0,
    }
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print('created' if is_new else 'added')
PY

    if _status=$("$PYTHON" "$_SETTINGS_HELPER" "$SETTINGS_PATH" "$STATUSLINE_CMD" 2>/dev/null); then
        case "$_status" in
            configured) echo -e "  ${GREEN}statusLine already configured, skipping${NC}" ;;
            created)    echo -e "  ${GREEN}Created settings.json with statusLine config${NC}" ;;
            added)      echo -e "  ${GREEN}Added statusLine config to existing settings.json${NC}" ;;
            *)          echo -e "  ${YELLOW}Unexpected helper output: '$_status'${NC}" ;;
        esac
    else
        echo -e "  ${RED}Failed to update settings.json${NC}" >&2
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}=== Installation complete! ===${NC}"
echo ""
echo "Statusline is now active — takes effect immediately."
echo ""
echo -e "${CYAN}What you'll see:${NC}"
echo "  GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K | In:2.4M Out:10.7K | Req:29 | Cost:\$0.023 | Credits:67.20 | Time:45s | +156/-23"
echo "  ✓ Bash×15 ✓ Read×2 ✓ Edit×2 ✓ Write"
echo ""
echo -e "${CYAN}Uninstall:${NC}"
echo "  bash $PLUGIN_DIR/uninstall.sh"
