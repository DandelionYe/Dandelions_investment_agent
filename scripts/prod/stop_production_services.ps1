# =============================================================================
# Dandelions Investment Agent - Production Service Stopper
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
    [string[]]$Services = @("all"),
    [switch]$AllowLegacyPid
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $ProjectRoot "storage\runtime\prod"

function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host $Message -ForegroundColor $Color
}

function Stop-ProcessTree {
    param([int]$Pid)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$Pid" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -Pid ([int]$child.ProcessId)
    }

    $proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue
    }
}

function Test-ManagedProcessMatchesMetadata {
    param(
        [System.Diagnostics.Process]$Process,
        [object]$Metadata
    )

    if (-not $Metadata) {
        return $false
    }
    if ($Metadata.project_root -ne $ProjectRoot) {
        return $false
    }
    if ([int]$Metadata.pid -ne [int]$Process.Id) {
        return $false
    }

    try {
        $actualStart = $Process.StartTime.ToUniversalTime()
        $recordedStart = [DateTime]::Parse($Metadata.start_time_utc).ToUniversalTime()
        return ([Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -lt 5)
    } catch {
        return $true
    }
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
    $metaFile = Join-Path $RuntimeDir "$name.json"

    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Status "  [$name] No PID file found. Service may not be running." "Yellow"
        $skipped++
        continue
    }

    $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($pidStr)) {
        Write-Status "  [$name] PID file is empty. Cleaning up." "Yellow"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $metaFile -Force -ErrorAction SilentlyContinue
        $skipped++
        continue
    }

    $pid = [int]$pidStr
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue

    if (-not $proc) {
        Write-Status "  [$name] PID $pid is not running. Cleaning up stale PID metadata." "Yellow"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $metaFile -Force -ErrorAction SilentlyContinue
        $skipped++
        continue
    }

    $metadata = $null
    if (Test-Path -LiteralPath $metaFile) {
        try {
            $metadata = Get-Content -LiteralPath $metaFile -Raw | ConvertFrom-Json
        } catch {
            Write-Status "  [$name] Metadata file is invalid: $_" "Yellow"
        }
    }

    if (-not (Test-ManagedProcessMatchesMetadata -Process $proc -Metadata $metadata)) {
        if (-not $AllowLegacyPid) {
            Write-Status "  [$name] PID $pid is not verified by metadata. Skipping to avoid stopping an unrelated process." "Yellow"
            Write-Status "          Re-run with -AllowLegacyPid only if this PID file was created by the old production launcher." "Yellow"
            $skipped++
            continue
        }
        Write-Status "  [$name] Metadata missing or stale; using -AllowLegacyPid to stop PID $pid." "Yellow"
    }

    Write-Status "  [$name] Stopping managed process tree at PID $pid ($($proc.ProcessName))..."
    try {
        Stop-ProcessTree -Pid $pid
        Start-Sleep -Seconds 2
        $stillRunning = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Write-Status "  [$name] PID $pid did not exit within 2 seconds. Try again or stop manually after checking logs." "Yellow"
            $errors++
        } else {
            Write-Status "  [$name] Stopped." "Green"
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $metaFile -Force -ErrorAction SilentlyContinue
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
Write-Status "  Skipped: $skipped (not running, no PID file, or metadata mismatch)"
if ($errors -gt 0) {
    Write-Status "  Errors:  $errors" "Red"
} else {
    Write-Status "  Errors:  0" "Green"
}

Write-Status ""
Write-Status "Check status: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1"
