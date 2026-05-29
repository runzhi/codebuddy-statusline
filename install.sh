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

echo -e "${CYAN}=== CodeBuddy Statusline Installer ===${NC}"
echo ""

# 1. Check dependencies
echo -e "${YELLOW}[1/4]${NC} Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3 first.${NC}"
    exit 1
fi
echo -e "  python3: ${GREEN}OK${NC}"

# 2. Clone / update plugin files
echo ""
echo -e "${YELLOW}[2/4]${NC} Installing plugin files..."

if [ -d "$PLUGIN_DIR/.git" ]; then
    echo "  Updating existing installation..."
    cd "$PLUGIN_DIR" && git pull --ff-only
else
    echo "  Cloning from $REPO_URL ..."
    rm -rf "$PLUGIN_DIR"
    git clone "$REPO_URL" "$PLUGIN_DIR"
fi

chmod +x "$PLUGIN_DIR/statusline.py" "$PLUGIN_DIR/statusline-lite.py" "$PLUGIN_DIR/cost-detail.py"
echo -e "  ${GREEN}Done${NC}"

# 3. Create cache directory
echo ""
echo -e "${YELLOW}[3/4]${NC} Setting up cache directory..."
mkdir -p "$HOME/.codebuddy/statusline-cache"
echo -e "  ${GREEN}Done${NC}"

# 4. Configure statusline in settings.json
echo ""
echo -e "${YELLOW}[4/4]${NC} Configuring statusline in settings.json..."

if [ ! -f "$SETTINGS_FILE" ]; then
    # Create new settings file
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    cat > "$SETTINGS_FILE" <<'SETTINGS'
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.codebuddy/statusline/statusline.py",
    "padding": 0
  }
}
SETTINGS
    echo -e "  ${GREEN}Created settings.json with statusLine config${NC}"
else
    # Check if statusLine already configured
    if python3 -c "
import json, sys
with open('$SETTINGS_FILE') as f:
    s = json.load(f)
sl = s.get('statusLine', {})
cmd = sl.get('command', '')
if 'statusline/statusline' in cmd or 'cost-monitor/statusline' in cmd:
    sys.exit(0)  # already configured
sys.exit(1)
" 2>/dev/null; then
        echo -e "  ${GREEN}statusLine already configured, skipping${NC}"
    else
        # Use python3 to safely merge statusLine into existing settings
        python3 -c "
import json

path = '$SETTINGS_FILE'
with open(path) as f:
    settings = json.load(f)

settings['statusLine'] = {
    'type': 'command',
    'command': 'python3 ~/.codebuddy/statusline/statusline.py',
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
echo -e "${CYAN}Options:${NC}"
echo "  - Switch to lite version (faster, less detail):"
echo "    Edit statusLine.command in settings.json to:"
echo "    python3 ~/.codebuddy/statusline/statusline-lite.py"
echo ""
echo "  - View detailed report anytime:"
echo "    python3 ~/.codebuddy/statusline/cost-detail.py"
echo ""
echo -e "${CYAN}Uninstall:${NC}"
echo "  bash $PLUGIN_DIR/uninstall.sh"
