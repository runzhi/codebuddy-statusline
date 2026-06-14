# CodeBuddy Statusline Uninstaller for Windows PowerShell

$ErrorActionPreference = "Stop"

$PluginDir = Join-Path $env:USERPROFILE ".codebuddy\statusline"
$CacheDir = Join-Path $env:USERPROFILE ".codebuddy\statusline-cache"
$SettingsFile = Join-Path $env:USERPROFILE ".codebuddy\settings.json"

# Resolve python command
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

Write-Host "=== CodeBuddy Statusline Uninstaller ===" -ForegroundColor Cyan
Write-Host ""

# 1. Remove statusLine from settings.json
Write-Host "[1/3] Removing statusLine config from settings.json..." -ForegroundColor Yellow
if (Test-Path $SettingsFile) {
    if (-not $PythonCmd) {
        Write-Host "  No working Python found, cannot clean settings.json automatically" -ForegroundColor Red
    } else {
        # Use a temp helper script + sys.argv to avoid embedding the path
        # into a Python string literal (injection risk).
        $helperPath = [System.IO.Path]::Combine(
            [System.IO.Path]::GetTempPath(),
            "codebuddy-statusline-uninst-$PID.py"
        )
        @'
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
'@ | Set-Content -Path $helperPath -Encoding UTF8

        try {
            $status = & $PythonCmd $helperPath $SettingsFile 2>$null
            switch ($status) {
                'removed' { Write-Host "  Removed statusLine config" -ForegroundColor Green }
                'foreign' { Write-Host "  statusLine exists but not ours, skipping" -ForegroundColor Yellow }
                'absent'  { Write-Host "  No statusLine config found, skipping" }
                default   { Write-Host "  Unexpected helper output: '$status'" -ForegroundColor Yellow }
            }
        } finally {
            Remove-Item $helperPath -ErrorAction SilentlyContinue
        }
    }
}

# 2. Remove plugin files
Write-Host "[2/3] Removing plugin files..." -ForegroundColor Yellow
if (Test-Path $PluginDir) { Remove-Item $PluginDir -Recurse -Force }
$OldDir = Join-Path $env:USERPROFILE ".codebuddy\cost-monitor"
if (Test-Path $OldDir) { Remove-Item $OldDir -Recurse -Force }
Write-Host "  Done"

# 3. Remove cache
Write-Host "[3/3] Removing cache..." -ForegroundColor Yellow
if (Test-Path $CacheDir) { Remove-Item $CacheDir -Recurse -Force }
$OldCache = Join-Path $env:USERPROFILE ".codebuddy\cost-monitor-cache"
if (Test-Path $OldCache) { Remove-Item $OldCache -Recurse -Force }
Write-Host "  Done"

Write-Host ""
Write-Host "=== Uninstallation complete! ===" -ForegroundColor Green
