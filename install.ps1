# CodeBuddy Statusline Installer for Windows PowerShell
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [REPO_URL]

$ErrorActionPreference = "Stop"

# Resolve CodeBuddy config dir. The running process may set CODEBUDDY_CONFIG_DIR
# (e.g. ~/.workbuddy); fall back to ~/.codebuddy. All user-facing paths below
# are derived from this so the plugin lands in the same dir CodeBuddy reads from.
if ($env:CODEBUDDY_CONFIG_DIR) {
    $ConfigDir = $env:CODEBUDDY_CONFIG_DIR
} else {
    $ConfigDir = Join-Path $env:USERPROFILE ".codebuddy"
}
$PluginDir = Join-Path $ConfigDir "statusline"
$SettingsFile = Join-Path $ConfigDir "settings.json"
$CacheDir = Join-Path $ConfigDir "plugins\data\statusline\cache"
$RepoUrl = if ($args[0]) { $args[0] } elseif (Test-Path (Join-Path $PluginDir ".git")) { try { git -C $PluginDir remote get-url origin 2>$null } catch { "" } } else { "" }
if (-not $RepoUrl) { $RepoUrl = "https://github.com/runzhi/codebuddy-statusline.git" }

Write-Host "=== CodeBuddy Statusline Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check dependencies
Write-Host "[1/5] Checking dependencies..." -ForegroundColor Yellow

$PythonCmd = $null
$PythonVersion = $null
$FoundVersions = @()
foreach ($cmd in @("python3", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
    try {
        # Verify command runs AND meets minimum version (3.6+)
        $versionOutput = & $cmd -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $versionOutput) {
            $FoundVersions += "$cmd (not runnable)"
            continue
        }
        $parts = $versionOutput -split '\.', 2
        $major = 0; $minor = 0
        $parseOk = [int]::TryParse($parts[0], [ref]$major) -and
                   ($parts.Count -lt 2 -or [int]::TryParse($parts[1], [ref]$minor))
        if (-not $parseOk) {
            $FoundVersions += "$cmd (unparseable version '$versionOutput')"
            continue
        }
        $versionStr = "$major.$minor"
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 6)) {
            $PythonCmd = $cmd
            $PythonVersion = $versionStr
            break
        }
        $FoundVersions += "$cmd $versionStr (need 3.6+)"
    } catch {
        $FoundVersions += "$cmd (error: $_)"
    }
}

if (-not $PythonCmd) {
    Write-Host "Error: Python 3.6+ is required but was not found." -ForegroundColor Red
    if ($FoundVersions.Count -gt 0) {
        Write-Host "  Found: $($FoundVersions -join '; ')" -ForegroundColor Red
    }
    Write-Host "Please install Python 3.6 or newer (https://www.python.org/downloads/)." -ForegroundColor Red
    exit 1
}
Write-Host "  python ($PythonCmd $PythonVersion): " -NoNewline; Write-Host "OK" -ForegroundColor Green

# 2. Clone / update plugin files
Write-Host ""
Write-Host "[2/5] Installing plugin files..." -ForegroundColor Yellow

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
Write-Host "[3/5] Setting up cache directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
Write-Host "  " -NoNewline; Write-Host "Done" -ForegroundColor Green

# 4. Configure statusline in settings.json
Write-Host ""
Write-Host "[4/5] Configuring statusline in settings.json..." -ForegroundColor Yellow

$ScriptPath = Join-Path $PluginDir "statusline.py"
$StatuslineCmd = "$PythonCmd `"$ScriptPath`""

# Write a helper script to a temp file to avoid embedding paths into
# Python -c snippets (which would be vulnerable to injection if the
# path contains characters that break the string literal).
$helperPath = [System.IO.Path]::Combine(
    [System.IO.Path]::GetTempPath(),
    "codebuddy-statusline-merge-$PID.py"
)
@'
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
'@ | Set-Content -Path $helperPath -Encoding UTF8

try {
    $status = & $PythonCmd $helperPath $SettingsFile $StatuslineCmd 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Python helper exited with code $LASTEXITCODE"
    }
    switch ($status) {
        'configured' { Write-Host "  " -NoNewline; Write-Host "statusLine already configured, skipping" -ForegroundColor Green }
        'created'    { Write-Host "  " -NoNewline; Write-Host "Created settings.json with statusLine config" -ForegroundColor Green }
        'added'      { Write-Host "  " -NoNewline; Write-Host "Added statusLine config to existing settings.json" -ForegroundColor Green }
        default      { throw "Unexpected helper output: '$status'" }
    }
} finally {
    Remove-Item $helperPath -ErrorAction SilentlyContinue
}

# 5. Link slash commands into the user-level commands dir
#    CodeBuddy discovers commands from <config-dir>\commands\<ns>\<name>.md as
#    /<ns>:<name>, so commands\config.md -> /statusline:config. This makes the
#    commands available in any project under git-clone install (in plugin mode
#    they are auto-discovered from the plugin's commands/ dir).
Write-Host ""
Write-Host "[5/5] Linking slash commands..." -ForegroundColor Yellow

$CmdDest = Join-Path $ConfigDir "commands\statusline"
New-Item -ItemType Directory -Path $CmdDest -Force | Out-Null
$CmdSrc = Join-Path $PluginDir "commands"
if (Test-Path $CmdSrc) {
    foreach ($cmdFile in Get-ChildItem -Path $CmdSrc -Filter *.md) {
        $dest = Join-Path $CmdDest $cmdFile.Name
        # Overwrite any existing link/file (copy; symlinks need admin on Windows)
        Copy-Item -Path $cmdFile.FullName -Destination $dest -Force
    }
    Write-Host "  " -NoNewline; Write-Host "Done (e.g. /statusline:config, /statusline:cost-detail)" -ForegroundColor Green
} else {
    Write-Host "  " -NoNewline; Write-Host "No commands dir found, skipped" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Installation complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Statusline is now active - takes effect immediately."
Write-Host ""
Write-Host "Uninstall:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PluginDir\uninstall.ps1`""
