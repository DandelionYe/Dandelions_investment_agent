# Dandelions investment agent local development launcher.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dev_services.ps1
#
# Starts Redis first, then opens independent PowerShell windows for:
#   FastAPI, Celery worker, Celery Beat, and Streamlit.

[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$StreamlitPort = 8501,
    [int]$CeleryConcurrency = 2,
    [int]$RedisWaitSeconds = 5,
    [switch]$SkipRedis,
    [switch]$SkipBeat
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$RuntimeDir = Join-Path $ProjectRoot "storage\runtime"

function Quote-PSLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-ToolInvocation {
    param([Parameter(Mandatory = $true)][string]$ToolName)

    $VenvTool = Join-Path $ProjectRoot ".venv\Scripts\$ToolName.exe"
    if (Test-Path -LiteralPath $VenvTool) {
        return "& " + (Quote-PSLiteral $VenvTool)
    }

    return $ToolName
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMs = 1000
    )

    $Client = New-Object System.Net.Sockets.TcpClient
    try {
        $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $Async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $Client.EndConnect($Async)
        return $true
    } catch {
        return $false
    } finally {
        $Client.Close()
    }
}

function Start-ServiceWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$Command
    )

    $RootLiteral = Quote-PSLiteral $ProjectRoot
    $WindowTitle = $Title.Replace("'", "''")
    $WindowCommand = @"
`$Host.UI.RawUI.WindowTitle = '$WindowTitle'
Set-Location -LiteralPath $RootLiteral
$Command
"@

    Start-Process `
        -FilePath $PowerShellExe `
        -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $WindowCommand) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Normal
}

Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

Write-Host "Dandelions local development launcher" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor DarkGray

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    Write-Host "[WARN] .env was not found. Copy .env.example to .env before using authenticated API flows." -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".venv"))) {
    Write-Host "[WARN] .venv was not found. Falling back to tools available on PATH." -ForegroundColor Yellow
}

if (-not $SkipRedis) {
    $RedisScript = Join-Path $PSScriptRoot "start_redis.ps1"
    if (-not (Test-Path -LiteralPath $RedisScript)) {
        throw "Redis launcher not found: $RedisScript"
    }

    Write-Host "`n[1/5] Checking Redis..." -ForegroundColor Cyan
    if (Test-TcpPort -HostName "127.0.0.1" -Port 6379) {
        Write-Host "  [OK] Redis is already reachable at 127.0.0.1:6379" -ForegroundColor Green
    } else {
        Write-Host "  Redis is not reachable; opening scripts\start_redis.ps1 in a separate window..." -ForegroundColor Yellow
        $RedisCommand = "& " + (Quote-PSLiteral $PowerShellExe) + " -NoProfile -ExecutionPolicy Bypass -File " + (Quote-PSLiteral $RedisScript)
        Start-ServiceWindow -Title "Dandelions Redis" -Command $RedisCommand

        if ($RedisWaitSeconds -gt 0) {
            Write-Host "  Waiting up to $RedisWaitSeconds seconds for Redis to become reachable..." -ForegroundColor DarkGray
            $RedisReady = $false
            for ($i = 0; $i -lt $RedisWaitSeconds; $i++) {
                Start-Sleep -Seconds 1
                if (Test-TcpPort -HostName "127.0.0.1" -Port 6379) {
                    $RedisReady = $true
                    break
                }
            }

            if ($RedisReady) {
                Write-Host "  [OK] Redis is reachable at 127.0.0.1:6379" -ForegroundColor Green
            } else {
                Write-Host "  [WARN] Redis is still not reachable. If the Redis window asks for a WSL sudo password, enter it there." -ForegroundColor Yellow
                Write-Host "         Continuing to open the other service windows; FastAPI/Celery may wait or log Redis errors until Redis is ready." -ForegroundColor Yellow
            }
        }
    }
} else {
    Write-Host "`n[1/5] Skipping Redis startup." -ForegroundColor Yellow
}

$Uvicorn = Get-ToolInvocation "uvicorn"
$Celery = Get-ToolInvocation "celery"
$Streamlit = Get-ToolInvocation "streamlit"

Write-Host "`n[2/5] Opening FastAPI window..." -ForegroundColor Cyan
Start-ServiceWindow `
    -Title "Dandelions FastAPI :$ApiPort" `
    -Command "$Uvicorn apps.api.main:app --host 0.0.0.0 --port $ApiPort --reload"

Start-Sleep -Seconds 1

Write-Host "[3/5] Opening Celery worker window..." -ForegroundColor Cyan
Start-ServiceWindow `
    -Title "Dandelions Celery worker" `
    -Command "$Celery -A apps.api.celery_app worker --loglevel=info --concurrency=$CeleryConcurrency"

if (-not $SkipBeat) {
    Start-Sleep -Seconds 1
    Write-Host "[4/5] Opening Celery Beat window..." -ForegroundColor Cyan
    Start-ServiceWindow `
        -Title "Dandelions Celery Beat" `
        -Command "$Celery -A apps.api.celery_app beat --loglevel=info --schedule storage/runtime/celerybeat-schedule"
} else {
    Write-Host "[4/5] Skipping Celery Beat." -ForegroundColor Yellow
}

Start-Sleep -Seconds 1

Write-Host "[5/5] Opening Streamlit dashboard window..." -ForegroundColor Cyan
Start-ServiceWindow `
    -Title "Dandelions Streamlit :$StreamlitPort" `
    -Command "$Streamlit run apps/dashboard/Home.py --server.port $StreamlitPort"

Write-Host "`nStarted service windows." -ForegroundColor Green
Write-Host "FastAPI:   http://127.0.0.1:$ApiPort/docs"
Write-Host "Streamlit: http://127.0.0.1:$StreamlitPort"
Write-Host "Close each service window with Ctrl+C when testing is finished."
