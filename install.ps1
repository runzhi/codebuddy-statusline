# CodeBuddy Statusline Installer for Windows PowerShell
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [REPO_URL]

$ErrorActionPreference = "Stop"

$PluginDir = Join-Path $env:USERPROFILE ".codebuddy\statusline"
$SettingsFile = Join-Path $env:USERPROFILE ".codebuddy\settings.json"
$CacheDir = Join-Path $env:USERPROFILE ".codebuddy\statusline-cache"
$RepoUrl = if ($args[0]) { $args[0] } else { "https://git.woa.com/origuo/codebuddy-statusbar.git" }

Write-Host "=== CodeBuddy Statusline Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check dependencies
Write-Host "[1/4] Checking dependencies..." -ForegroundColor Yellow

$PythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $result = & $cmd -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = $cmd
            break
        }
    } catch { }
}

if (-not $PythonCmd) {
    Write-Host "Error: No working Python 3 found. Please install Python 3 first." -ForegroundColor Red
    exit 1
}
Write-Host "  python ($PythonCmd): " -NoNewline; Write-Host "OK" -ForegroundColor Green

# 2. Clone / update plugin files
Write-Host ""
Write-Host "[2/4] Installing plugin files..." -ForegroundColor Yellow

if (Test-Path (Join-Path $PluginDir ".git")) {
    Write-Host "  Updating existing installation..."
    Push-Location $PluginDir
    git pull --ff-only
    Pop-Location
} else {
    Write-Host "  Cloning from $RepoUrl ..."
    if (Test-Path $PluginDir) { Remove-Item $PluginDir -Recurse -Force }
    git clone $RepoUrl $PluginDir
}
Write-Host "  " -NoNewline; Write-Host "Done" -ForegroundColor Green

# 3. Create cache directory
Write-Host ""
Write-Host "[3/4] Setting up cache directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
Write-Host "  " -NoNewline; Write-Host "Done" -ForegroundColor Green

# 4. Configure statusline in settings.json
Write-Host ""
Write-Host "[4/4] Configuring statusline in settings.json..." -ForegroundColor Yellow

$ScriptPath = Join-Path $PluginDir "statusline.py"
$StatuslineCmd = "$PythonCmd `"$ScriptPath`""

if (-not (Test-Path $SettingsFile)) {
    $settingsDir = Split-Path $SettingsFile
    if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null }

    $settings = @{
        statusLine = @{
            type = "command"
            command = $StatuslineCmd
            padding = 0
        }
    }
    $settings | ConvertTo-Json -Depth 5 | Set-Content $SettingsFile -Encoding UTF8
    Write-Host "  " -NoNewline; Write-Host "Created settings.json with statusLine config" -ForegroundColor Green
} else {
    # Check if statusLine already configured
    $alreadyConfigured = & $PythonCmd -c @"
import json, sys
with open(r'$SettingsFile') as f:
    s = json.load(f)
sl = s.get('statusLine', {})
cmd = sl.get('command', '')
if 'statusline' in cmd or 'cost-monitor' in cmd:
    sys.exit(0)
sys.exit(1)
"@ 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  " -NoNewline; Write-Host "statusLine already configured, skipping" -ForegroundColor Green
    } else {
        & $PythonCmd -c @"
import json
path = r'$SettingsFile'
with open(path) as f:
    settings = json.load(f)
settings['statusLine'] = {
    'type': 'command',
    'command': r'$StatuslineCmd',
    'padding': 0
}
with open(path, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
"@
        Write-Host "  " -NoNewline; Write-Host "Added statusLine config to existing settings.json" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Installation complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Restart your CodeBuddy Code session to see the statusline."
Write-Host ""
Write-Host "Uninstall:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PluginDir\uninstall.ps1`""
