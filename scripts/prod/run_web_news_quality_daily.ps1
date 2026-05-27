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

# Fix encoding for Windows PowerShell 5.1 (chcp 65001 + UTF-8 I/O)
try { chcp 65001 > $null } catch {}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

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

# Force Python child processes to use UTF-8 for stdout/stderr
$env:PYTHONIOENCODING = "utf-8"

Write-Log "=== 网页新闻/舆情每日质量监控开始 ==="
Write-Log "Project Root: $ProjectRoot"
Write-Log "Sources: $Sources"
Write-Log "Limit: $Limit"
Write-Log "Timeout: ${TimeoutSeconds}s"

# Step 1: Run monitor
Write-Log "--- Step 1: 运行 news quality monitor ---"
$monitorStdout = "$LogsDir\monitor_stdout_$DateStr.log"
$monitorStderr = "$LogsDir\monitor_stderr_$DateStr.log"

try {
    $monitorOutput = & $VenvPython `
        (Join-Path $ProjectRoot "scripts\run_web_news_quality_monitor.py") `
        "--sources" $Sources `
        "--limit" $Limit `
        "--timeout-seconds" $TimeoutSeconds `
        "--output-dir" (Join-Path $ProjectRoot "storage\artifacts\web_news_quality\live") `
        2>&1
    $monitorExit = $LASTEXITCODE
    $monitorOutput | Out-File -FilePath $monitorStdout -Encoding UTF8
} catch {
    $_ | Out-File -FilePath $monitorStderr -Encoding UTF8
    $monitorExit = 1
}
Write-Log "Monitor exit code: $monitorExit"

# Step 2: Run trend analyzer
Write-Log "--- Step 2: 运行 trend analyzer ---"
$trendStdout = "$LogsDir\trend_stdout_$DateStr.log"
$trendStderr = "$LogsDir\trend_stderr_$DateStr.log"

try {
    $trendOutput = & $VenvPython `
        (Join-Path $ProjectRoot "scripts\analyze_web_news_quality_trends.py") `
        "--window-days" $WindowDays `
        "--min-runs" $MinRuns `
        "--output-dir" (Join-Path $ProjectRoot "storage\artifacts\web_news_quality\live") `
        2>&1
    $trendExit = $LASTEXITCODE
    $trendOutput | Out-File -FilePath $trendStdout -Encoding UTF8
} catch {
    $_ | Out-File -FilePath $trendStderr -Encoding UTF8
    $trendExit = 1
}
Write-Log "Trend analyzer exit code: $trendExit"

# Determine overall exit code
$overallExit = if ($monitorExit -ne 0 -or $trendExit -ne 0) { 1 } else { 0 }
Write-Log "=== 完成 (overall exit code: $overallExit) ==="

exit $overallExit
