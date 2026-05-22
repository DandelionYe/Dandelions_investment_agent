# =============================================================================
# Dandelions Investment Agent — Cleanup Runtime Data
# =============================================================================
# DEFAULT: dry-run mode. Only prints what would be deleted.
# To actually delete, pass -Execute.
#
# Usage (dry-run):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1
#
# Usage (execute):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1 -Execute
#
# Custom log retention:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1 -Execute -LogRetentionDays 7
# =============================================================================

[CmdletBinding()]
param(
    [switch]$Execute,
    [int]$LogRetentionDays = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host $Message -ForegroundColor $Color
}

function Test-PathInsideProject {
    param([string]$Path)
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue)
    if (-not $resolved) { return $false }
    return $resolved.Path.StartsWith($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Remove-SafeItem {
    param(
        [string]$Path,
        [string]$Label,
        [switch]$IsDirectory,
        [switch]$Recurse
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    # Safety: ensure path is inside project
    if (-not (Test-PathInsideProject $Path)) {
        Write-Status "  [SKIP] $Label — path is outside project root" "Red"
        return
    }

    if ($Execute) {
        if ($IsDirectory) {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        }
        Write-Status "  [DELETED] $Label" "Yellow"
    } else {
        Write-Status "  [WOULD DELETE] $Label" "DarkYellow"
    }
}

Write-Status "=== Dandelions Cleanup ===" "Cyan"
Write-Status "Project root: $ProjectRoot"

if ($Execute) {
    Write-Status "Mode: EXECUTE (items will be deleted)" "Red"
} else {
    Write-Status "Mode: DRY-RUN (nothing will be deleted)" "Green"
}
Write-Status ""

$deleteCount = 0

# --- __pycache__ directories ---
Write-Status "--- Python cache directories ---"
$pycacheDirs = Get-ChildItem -LiteralPath $ProjectRoot -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue
foreach ($dir in $pycacheDirs) {
    if (Test-PathInsideProject $dir.FullName) {
        Remove-SafeItem -Path $dir.FullName -Label "__pycache__: $($dir.FullName)" -IsDirectory
        $deleteCount++
    }
}

# --- .pytest_cache directories ---
Write-Status "--- Pytest cache directories ---"
$pytestDirs = Get-ChildItem -LiteralPath $ProjectRoot -Directory -Recurse -Filter ".pytest_cache" -ErrorAction SilentlyContinue
foreach ($dir in $pytestDirs) {
    if (Test-PathInsideProject $dir.FullName) {
        Remove-SafeItem -Path $dir.FullName -Label ".pytest_cache: $($dir.FullName)" -IsDirectory
        $deleteCount++
    }
}

# --- .ruff_cache directories ---
Write-Status "--- Ruff cache directories ---"
$ruffDirs = Get-ChildItem -LiteralPath $ProjectRoot -Directory -Recurse -Filter ".ruff_cache" -ErrorAction SilentlyContinue
foreach ($dir in $ruffDirs) {
    if (Test-PathInsideProject $dir.FullName) {
        Remove-SafeItem -Path $dir.FullName -Label ".ruff_cache: $($dir.FullName)" -IsDirectory
        $deleteCount++
    }
}

# --- Old production log files ---
Write-Status "--- Old production log files (>$LogRetentionDays days) ---"
$logsDir = Join-Path $ProjectRoot "storage\logs\prod"
if (Test-Path -LiteralPath $logsDir) {
    $cutoff = (Get-Date).AddDays(-$LogRetentionDays)
    $oldLogs = Get-ChildItem -LiteralPath $logsDir -File -Filter "*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff }
    foreach ($log in $oldLogs) {
        Remove-SafeItem -Path $log.FullName -Label "Old log: $($log.Name) (last modified $($log.LastWriteTime.ToString('yyyy-MM-dd')))"
        $deleteCount++
    }
}

# --- Stale PID files ---
Write-Status "--- Stale PID files ---"
$prodDir = Join-Path $ProjectRoot "storage\prod"
if (Test-Path -LiteralPath $prodDir) {
    $pidFiles = Get-ChildItem -LiteralPath $prodDir -File -Filter "*.pid" -ErrorAction SilentlyContinue
    foreach ($pf in $pidFiles) {
        $pidStr = (Get-Content -LiteralPath $pf.FullName -ErrorAction SilentlyContinue).Trim()
        $isStale = $true
        if (-not [string]::IsNullOrWhiteSpace($pidStr)) {
            $proc = Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue
            if ($proc) { $isStale = $false }
        }
        if ($isStale) {
            Remove-SafeItem -Path $pf.FullName -Label "Stale PID: $($pf.Name)"
            $deleteCount++
        }
    }
}

Write-Status ""
if ($Execute) {
    Write-Status "=== Cleanup Complete ===" "Green"
    Write-Status "  Processed $deleteCount items."
} else {
    Write-Status "=== Dry-Run Complete ===" "Green"
    Write-Status "  Would process $deleteCount items."
    Write-Status "  Re-run with -Execute to actually delete."
}

Write-Status ""
Write-Status "NOT deleted (require explicit backup/restore strategy):"
Write-Status "  storage/cache/research_data.sqlite  (research cache DB)"
Write-Status "  storage/reference/                  (CSMAR/EVA reference DBs)"
Write-Status "  storage/reports/                    (generated reports)"
Write-Status "  storage/tasks.db                    (task/watchlist DB)"
Write-Status "  storage/watchlist.json              (watchlist data)"
Write-Status "  .env                                (configuration)"
