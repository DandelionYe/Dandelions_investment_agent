# =============================================================================
# Dandelions Investment Agent — Backup Runtime Data
# =============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\backup_runtime_data.ps1
#
# Include logs in backup:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\backup_runtime_data.ps1 -IncludeLogs
# =============================================================================

[CmdletBinding()]
param(
    [switch]$IncludeLogs
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackupsDir = Join-Path $ProjectRoot "backups"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $BackupsDir $Timestamp

function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host $Message -ForegroundColor $Color
}

Write-Status "=== Dandelions Backup ===" "Cyan"
Write-Status "Project root: $ProjectRoot"
Write-Status "Backup dir:   $BackupDir"
Write-Status ""

# Create backup directory
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

# Define backup targets
$mustBackup = @(
    @{ Source = ".env";                                        Label = "Environment config" },
    @{ Source = "storage\tasks.db";                            Label = "Task database" },
    @{ Source = "storage\watchlist.json";                      Label = "Watchlist data" },
    @{ Source = "storage\cache\research_data.sqlite";          Label = "Research cache DB" },
    @{ Source = "storage\reference";                           Label = "Reference databases (CSMAR/EVA)" },
    @{ Source = "storage\reports";                             Label = "Generated reports" },
    @{ Source = "storage\artifacts";                           Label = "Artifacts" }
)

$manifest = @{
    "timestamp"   = $Timestamp
    "project_root" = $ProjectRoot
    "backup_dir"   = $BackupDir
    "include_logs" = $IncludeLogs.IsPresent
    "items"        = @()
}

$totalCopied = 0
$totalSkipped = 0

foreach ($target in $mustBackup) {
    $src = Join-Path $ProjectRoot $target.Source
    $dstName = $target.Source -replace '\\', '_'
    $dstName = $dstName -replace '^\.\.?', ''
    $dstName = $dstName.TrimStart('_')
    if ([string]::IsNullOrWhiteSpace($dstName)) { $dstName = Split-Path $target.Source -Leaf }
    $dst = Join-Path $BackupDir $dstName

    $item = @{
        "source" = $target.Source
        "label"  = $target.Label
        "status" = "unknown"
    }

    if (Test-Path -LiteralPath $src) {
        $isDir = (Get-Item -LiteralPath $src).PSIsContainer
        if ($isDir) {
            # Check if directory has content
            $children = Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue
            if ($children) {
                Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
                $item["status"] = "copied"
                $item["files"] = ($children | Measure-Object).Count
                $totalCopied++
            } else {
                $item["status"] = "skipped_empty"
                $totalSkipped++
            }
        } else {
            Copy-Item -LiteralPath $src -Destination $dst -Force
            $item["status"] = "copied"
            $item["size_bytes"] = (Get-Item -LiteralPath $dst).Length
            $totalCopied++
        }
    } else {
        $item["status"] = "skipped_not_found"
        $totalSkipped++
    }

    Write-Status "  [$($item['status'])] $($target.Label) ($($target.Source))"
    $manifest["items"] += $item
}

# Optional: include logs
if ($IncludeLogs) {
    $logsDir = Join-Path $ProjectRoot "storage\logs\prod"
    if (Test-Path -LiteralPath $logsDir) {
        $logFiles = Get-ChildItem -LiteralPath $logsDir -File -ErrorAction SilentlyContinue
        if ($logFiles) {
            $logsDst = Join-Path $BackupDir "logs_prod"
            Copy-Item -LiteralPath $logsDir -Destination $logsDst -Recurse -Force
            Write-Status "  [copied] Production logs"
            $manifest["items"] += @{
                "source" = "storage\logs\prod"
                "label"  = "Production logs"
                "status" = "copied"
                "files"  = ($logFiles | Measure-Object).Count
            }
            $totalCopied++
        }
    }
}

# Write manifest
$manifest["total_copied"] = $totalCopied
$manifest["total_skipped"] = $totalSkipped
$manifestPath = Join-Path $BackupDir "manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Out-File -FilePath $manifestPath -Encoding utf8

Write-Status ""
Write-Status "=== Backup Complete ===" "Green"
Write-Status "  Copied:  $totalCopied items"
Write-Status "  Skipped: $totalSkipped items (not found or empty)"
Write-Status "  Manifest: $manifestPath"
Write-Status "  Backup:   $BackupDir"
