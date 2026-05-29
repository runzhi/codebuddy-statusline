#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PLUGIN_DIR="$HOME/.codebuddy/cost-monitor"
CACHE_DIR="$HOME/.codebuddy/cost-monitor-cache"
SETTINGS_FILE="$HOME/.codebuddy/settings.json"

echo -e "${CYAN}=== CodeBuddy Cost Monitor Uninstaller ===${NC}"
echo ""

# 1. Remove statusLine from settings.json
echo -e "${YELLOW}[1/3]${NC} Removing statusLine config from settings.json..."
if [ -f "$SETTINGS_FILE" ]; then
    python3 -c "
import json
path = '$SETTINGS_FILE'
with open(path) as f:
    settings = json.load(f)
if 'statusLine' in settings:
    cmd = settings['statusLine'].get('command', '')
    if 'cost-monitor' in cmd:
        del settings['statusLine']
        with open(path, 'w') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print('  Removed statusLine config')
    else:
        print('  statusLine exists but not cost-monitor, skipping')
else:
    print('  No statusLine config found, skipping')
" 2>/dev/null
fi

# 2. Remove plugin files
echo -e "${YELLOW}[2/3]${NC} Removing plugin files..."
rm -rf "$PLUGIN_DIR"
echo "  Done"

# 3. Remove cache
echo -e "${YELLOW}[3/3]${NC} Removing cache..."
rm -rf "$CACHE_DIR"
echo "  Done"

echo ""
echo -e "${GREEN}=== Uninstallation complete! ===${NC}"
