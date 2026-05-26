# =============================================================================
# Dandelions Investment Agent - 网页新闻/舆情每日质量监控
# =============================================================================
# 运行 monitor + trend analyzer，输出日志到 storage/logs/web_news_quality/
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\run_web_news_quality_daily.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\run_web_news_quality_daily.ps1 -Sources eastmoney,sina -Limit 5
# =============================================================================

[CmdletBinding()]
param(
    [string]$Sources = "eastmoney,sina,xinhuanet,hotrank,baidu",
    [int]$Limit = 5,
    [int]$TimeoutSeconds = 8,
    [int]$WindowDays = 7,
    [int]$MinRuns = 3
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogsDir = Join-Path $ProjectRoot "storage\logs\web_news_quality"
$DateStr = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogsDir "run_$DateStr.log"

# Ensure directories
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== 网页新闻/舆情每日质量监控开始 ==="
Write-Log "Project Root: $ProjectRoot"
Write-Log "Sources: $Sources"
Write-Log "Limit: $Limit"
Write-Log "Timeout: ${TimeoutSeconds}s"

# Step 1: Run monitor
Write-Log "--- Step 1: 运行 news quality monitor ---"
$monitorArgs = @(
    (Join-Path $ProjectRoot "scripts\run_web_news_quality_monitor.py"),
    "--sources", $Sources,
    "--limit", $Limit,
    "--timeout-seconds", $TimeoutSeconds,
    "--output-dir", (Join-Path $ProjectRoot "storage\artifacts\web_news_quality\live")
)

$monitorProcess = Start-Process -FilePath $VenvPython -ArgumentList $monitorArgs `
    -WorkingDirectory $ProjectRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$LogsDir\monitor_stdout_$DateStr.log" -RedirectStandardError "$LogsDir\monitor_stderr_$DateStr.log"

$monitorExit = $monitorProcess.ExitCode
Write-Log "Monitor exit code: $monitorExit"

# Step 2: Run trend analyzer
Write-Log "--- Step 2: 运行 trend analyzer ---"
$trendArgs = @(
    (Join-Path $ProjectRoot "scripts\analyze_web_news_quality_trends.py"),
    "--window-days", $WindowDays,
    "--min-runs", $MinRuns,
    "--output-dir", (Join-Path $ProjectRoot "storage\artifacts\web_news_quality\live")
)

$trendProcess = Start-Process -FilePath $VenvPython -ArgumentList $trendArgs `
    -WorkingDirectory $ProjectRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$LogsDir\trend_stdout_$DateStr.log" -RedirectStandardError "$LogsDir\trend_stderr_$DateStr.log"

$trendExit = $trendProcess.ExitCode
Write-Log "Trend analyzer exit code: $trendExit"

# Determine overall exit code
$overallExit = if ($monitorExit -ne 0 -or $trendExit -ne 0) { 1 } else { 0 }
Write-Log "=== 完成 (overall exit code: $overallExit) ==="

exit $overallExit
