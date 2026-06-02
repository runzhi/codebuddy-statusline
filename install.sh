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
REPO_URL="${1:-https://git.woa.com/origuo/codebuddy-statusbar.git}"

# Resolve python command — must verify it actually runs
# (Windows Store 'python3' stub exists but exits with code 49 without running)
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
if [ -z "$PYTHON" ]; then
    echo -e "${RED}Error: No working Python 3 found. Please install Python 3 first.${NC}"
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
echo -e "  python ($PYTHON): ${GREEN}OK${NC}"

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
    # Check if statusLine already configured
    if $PYTHON -c "
import json, sys
with open(r'$SETTINGS_PATH') as f:
    s = json.load(f)
sl = s.get('statusLine', {})
cmd = sl.get('command', '')
if 'statusline' in cmd or 'cost-monitor' in cmd:
    sys.exit(0)  # already configured
sys.exit(1)
" 2>/dev/null; then
        echo -e "  ${GREEN}statusLine already configured, skipping${NC}"
    else
        # Use python to safely merge statusLine into existing settings
        $PYTHON -c "
import json

path = r'$SETTINGS_PATH'
with open(path) as f:
    settings = json.load(f)

settings['statusLine'] = {
    'type': 'command',
    'command': r'$STATUSLINE_CMD',
    'padding': 0
}

with open(path, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
"
        echo -e "  ${GREEN}Added statusLine config to existing settings.json${NC}"
    fi
fi

echo ""
echo -e "${GREEN}=== Installation complete! ===${NC}"
echo ""
echo "Restart your CodeBuddy Code session to see the statusline."
echo ""
echo -e "${CYAN}What you'll see:${NC}"
echo "  GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K | In:2.4M Out:10.7K | Req:29 | Cost:\$0.023 | Credits:67.20 | Time:45s | +156/-23"
echo "  ✓ Bash×15 ✓ Read×2 ✓ Edit×2 ✓ Write"
echo ""
echo -e "${CYAN}Uninstall:${NC}"
echo "  bash $PLUGIN_DIR/uninstall.sh"
