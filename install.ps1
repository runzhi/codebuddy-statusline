# CodeBuddy Statusline Installer for Windows PowerShell
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [REPO_URL]

$ErrorActionPreference = "Stop"

$PluginDir = Join-Path $env:USERPROFILE ".codebuddy\statusline"
$SettingsFile = Join-Path $env:USERPROFILE ".codebuddy\settings.json"
$CacheDir = Join-Path $env:USERPROFILE ".codebuddy\statusline-cache"
$RepoUrl = if ($args[0]) { $args[0] } elseif (Test-Path (Join-Path $PluginDir ".git")) { try { git -C $PluginDir remote get-url origin 2>$null } catch { "" } } else { "" }
if (-not $RepoUrl) { $RepoUrl = "https://github.com/runzhi/codebuddy-statusline.git" }

Write-Host "=== CodeBuddy Statusline Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check dependencies
Write-Host "[1/4] Checking dependencies..." -ForegroundColor Yellow

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

Write-Host ""
Write-Host "=== Installation complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Statusline is now active - takes effect immediately."
Write-Host ""
Write-Host "Uninstall:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PluginDir\uninstall.ps1`""
