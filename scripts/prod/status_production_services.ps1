# =============================================================================
# Dandelions Investment Agent - Production Service Status
# =============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1
# =============================================================================

[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$StreamlitPort = 8501
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $ProjectRoot "storage\runtime\prod"

function Get-DotEnvValue {
    param(
        [string]$Content,
        [string]$Name
    )

    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$"
    $match = [regex]::Match($Content, $pattern)
    if (-not $match.Success) {
        return $null
    }

    $value = $match.Groups[1].Value.Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"')) {
        return $value.Substring(1, $value.Length - 2)
    }
    if ($value.StartsWith("'") -and $value.EndsWith("'")) {
        return $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Get-RedisUrl {
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $null
    }
    $envContent = Get-Content -LiteralPath $envFile -Raw -ErrorAction SilentlyContinue
    return Get-DotEnvValue -Content $envContent -Name "CELERY_BROKER_URL"
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000)
    $Client = New-Object System.Net.Sockets.TcpClient
    try {
        $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $Async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $Client.EndConnect($Async)
        return $true
    } catch {
        return $false
    } finally {
        $Client.Close()
    }
}

function Test-RedisPing {
    param([string]$RedisUrl)

    if (-not $RedisUrl) { return $false }
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { return $false }

    $script = "import os, redis; url=os.environ['DANDELIONS_REDIS_CHECK_URL']; r=redis.from_url(url, socket_connect_timeout=2, socket_timeout=2); print(r.ping()); r.close()"
    $env:DANDELIONS_REDIS_CHECK_URL = $RedisUrl
    try {
        $result = & $Python -c $script 2>&1
        return ($LASTEXITCODE -eq 0 -and ($result | Out-String) -match "True")
    } finally {
        Remove-Item Env:\DANDELIONS_REDIS_CHECK_URL -ErrorAction SilentlyContinue
    }
}

function Get-ServiceMetadata {
    param([string]$Name)

    $metaFile = Join-Path $RuntimeDir "$Name.json"
    if (-not (Test-Path -LiteralPath $metaFile)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $metaFile -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

Write-Host ""
Write-Host "=== Dandelions Production Service Status ===" -ForegroundColor Cyan
Write-Host ""
Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f "Service", "PID", "Running", "Notes")
Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f "-------", "---", "-------", "-----")

$services = @(
    @{ Name = "api";       Port = $ApiPort;       PortLabel = "API" },
    @{ Name = "worker";    Port = $null;          PortLabel = "" },
    @{ Name = "beat";      Port = $null;          PortLabel = "" },
    @{ Name = "streamlit"; Port = $StreamlitPort; PortLabel = "Streamlit" }
)

foreach ($svc in $services) {
    $name = $svc.Name
    $pidFile = Join-Path $RuntimeDir "$name.pid"
    $metadata = Get-ServiceMetadata -Name $name
    $port = $svc.Port
    if ($metadata -and $metadata.port) {
        $port = [int]$metadata.port
    }

    $pid = "-"
    $running = "No"
    $notes = ""

    if (Test-Path -LiteralPath $pidFile) {
        $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if (-not [string]::IsNullOrWhiteSpace($pidStr)) {
            $pid = $pidStr
            $proc = Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue
            if ($proc) {
                $running = "Yes"
                if (-not $metadata) {
                    $notes = "running; missing metadata"
                }
            } else {
                $running = "No"
                $notes = "stale PID file"
            }
        } else {
            $notes = "empty PID file"
        }
    } else {
        $notes = "no PID file"
    }

    if ($port -and $running -eq "Yes") {
        if (Test-TcpPort -HostName "127.0.0.1" -Port $port) {
            $notes = "port $port listening"
        } else {
            $notes = "port $port NOT listening"
        }
    }

    Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f $name, $pid, $running, $notes)
}

Write-Host ""
Write-Host "--- Infrastructure ---" -ForegroundColor Cyan
$redisUrl = Get-RedisUrl
$redisOk = Test-RedisPing -RedisUrl $redisUrl
if ($redisOk) {
    Write-Host "  Redis:  OK (from CELERY_BROKER_URL)" -ForegroundColor Green
} else {
    Write-Host "  Redis:  NOT reachable via CELERY_BROKER_URL" -ForegroundColor Red
}

if (Test-TcpPort -HostName "127.0.0.1" -Port $ApiPort) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $body = $response.Content | ConvertFrom-Json
        $apiStatus = $body.api.status
        $dbStatus = $body.db.status
        $redisStatus = $body.redis.status
        Write-Host "  API:    $apiStatus | DB: $dbStatus | Redis(via API): $redisStatus"
    } catch {
        Write-Host "  API:    port $ApiPort listening but health check failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  API:    port $ApiPort NOT listening" -ForegroundColor Red
}

Write-Host ""
Write-Host "Logs: $(Join-Path $ProjectRoot 'storage\logs\prod')" -ForegroundColor DarkGray
Write-Host "PIDs: $(Join-Path $ProjectRoot 'storage\runtime\prod')" -ForegroundColor DarkGray
