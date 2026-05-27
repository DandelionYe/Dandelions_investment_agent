# =============================================================================
# Dandelions Investment Agent - 安装 Windows Task Scheduler 每日新闻质量监控
# =============================================================================
# 创建 Windows 计划任务，每日定时运行 monitor + trend analyzer。
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\install_web_news_quality_task.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\install_web_news_quality_task.ps1 -TaskName "MyTask" -At "09:00"
# =============================================================================

[CmdletBinding()]
param(
    [string]$TaskName = "DandelionsWebNewsQualityDaily",
    [string]$At = "08:30",
    [string]$ProjectRoot = "",
    [string]$Sources = "eastmoney,sina,xinhuanet,hotrank,baidu",
    [int]$Limit = 5,
    [int]$TimeoutSeconds = 8
)

$ErrorActionPreference = "Stop"

# Fix encoding for Windows PowerShell 5.1 (chcp 65001 + UTF-8 I/O)
try { chcp 65001 > $null } catch {}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$ScriptPath = Join-Path $ProjectRoot "scripts\prod\run_web_news_quality_daily.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Host "[FAIL] 脚本不存在: $ScriptPath" -ForegroundColor Red
    exit 1
}

# Parse time
$TimeParts = $At -split ":"
$Hour = [int]$TimeParts[0]
$Minute = [int]$TimeParts[1]

Write-Host "安装 Windows 计划任务" -ForegroundColor Cyan
Write-Host "  Task Name: $TaskName"
Write-Host "  Time: $At (每日)"
Write-Host "  Project Root: $ProjectRoot"
Write-Host "  Script: $ScriptPath"
Write-Host "  Sources: $Sources"
Write-Host "  Limit: $Limit"
Write-Host "  Timeout: ${TimeoutSeconds}s"

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "  移除已有任务..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build action
$ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Sources `"$Sources`" -Limit $Limit -TimeoutSeconds $TimeoutSeconds"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArgs -WorkingDirectory $ProjectRoot

# Build trigger (daily)
$Trigger = New-ScheduledTaskTrigger -Daily -At "${Hour}:${Minute}"

# Build settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# Register task
Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Dandelions 网页新闻/舆情每日质量监控 (monitor + trend analyzer)" `
    -RunLevel Highest

Write-Host "`n[OK] 任务已安装: $TaskName" -ForegroundColor Green
Write-Host "每日 $At 自动运行。"
Write-Host "`n卸载命令:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\uninstall_web_news_quality_task.ps1 -TaskName `"$TaskName`""
