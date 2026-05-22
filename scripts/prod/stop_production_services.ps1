# =============================================================================
# Dandelions Investment Agent — Production Service Stopper
# =============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1
#
# Stop specific service:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1 -Services api
# =============================================================================

[CmdletBinding()]
param(
    [ValidateSet("api", "worker", "beat", "streamlit", "all")]
    [string[]]$Services = @("all")
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $ProjectRoot "storage\prod"

function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host $Message -ForegroundColor $Color
}

if ($Services -contains "all") {
    $Services = @("api", "worker", "beat", "streamlit")
}

Write-Status "=== Dandelions Production Service Stopper ===" "Cyan"
Write-Status ""

$stopped = 0
$skipped = 0
$errors = 0

foreach ($name in $Services) {
    $pidFile = Join-Path $RuntimeDir "$name.pid"

    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Status "  [$name] No PID file found. Service may not be running." "Yellow"
        $skipped++
        continue
    }

    $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue).Trim()
    if ([string]::IsNullOrWhiteSpace($pidStr)) {
        Write-Status "  [$name] PID file is empty. Cleaning up." "Yellow"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        $skipped++
        continue
    }

    $pid = [int]$pidStr
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue

    if (-not $proc) {
        Write-Status "  [$name] PID $pid is not running. Cleaning up stale PID file." "Yellow"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        $skipped++
        continue
    }

    Write-Status "  [$name] Stopping PID $pid ($($proc.ProcessName))..."
    try {
        Stop-Process -Id $pid -Force -ErrorAction Stop
        # Wait briefly and verify
        Start-Sleep -Seconds 2
        $stillRunning = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Write-Status "  [$name] PID $pid did not exit within 2 seconds. Try again or kill manually." "Yellow"
            $errors++
        } else {
            Write-Status "  [$name] Stopped." "Green"
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    } catch {
        Write-Status "  [$name] Failed to stop PID $pid : $_" "Red"
        $errors++
    }
}

Write-Status ""
Write-Status "=== Summary ===" "Cyan"
Write-Status "  Stopped: $stopped"
Write-Status "  Skipped: $skipped (not running or no PID file)"
if ($errors -gt 0) {
    Write-Status "  Errors:  $errors" "Red"
} else {
    Write-Status "  Errors:  0" "Green"
}

Write-Status ""
Write-Status "Check status: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1"
