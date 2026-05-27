# =============================================================================
# Dandelions Investment Agent - 卸载 Windows Task Scheduler 每日新闻质量监控
# =============================================================================
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\uninstall_web_news_quality_task.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\uninstall_web_news_quality_task.ps1 -TaskName "MyTask"
# =============================================================================

[CmdletBinding()]
param(
    [string]$TaskName = "DandelionsWebNewsQualityDaily"
)

$ErrorActionPreference = "Stop"

# Fix encoding for Windows PowerShell 5.1 (chcp 65001 + UTF-8 I/O)
try { chcp 65001 > $null } catch {}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existingTask) {
    Write-Host "[INFO] 任务不存在: $TaskName" -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] 任务已卸载: $TaskName" -ForegroundColor Green
