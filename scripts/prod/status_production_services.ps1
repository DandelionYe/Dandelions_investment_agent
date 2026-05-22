# =============================================================================
# Dandelions Investment Agent — Production Service Status
# =============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1
# =============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $ProjectRoot "storage\prod"

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
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { return $false }
    $result = & $Python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379/0', socket_connect_timeout=2, socket_timeout=2); print(r.ping()); r.close()" 2>&1
    return ($LASTEXITCODE -eq 0 -and ($result | Out-String) -match "True")
}

Write-Host ""
Write-Host "=== Dandelions Production Service Status ===" -ForegroundColor Cyan
Write-Host ""
Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f "Service", "PID", "Running", "Notes")
Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f "-------", "---", "-------", "-----")

$services = @(
    @{ Name = "api";       Port = 8000;  PortLabel = "API" },
    @{ Name = "worker";    Port = $null; PortLabel = "" },
    @{ Name = "beat";      Port = $null; PortLabel = "" },
    @{ Name = "streamlit"; Port = 8501;  PortLabel = "Streamlit" }
)

foreach ($svc in $services) {
    $name = $svc.Name
    $pidFile = Join-Path $RuntimeDir "$name.pid"
    $pid = "-"
    $running = "No"
    $notes = ""

    if (Test-Path -LiteralPath $pidFile) {
        $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue).Trim()
        if (-not [string]::IsNullOrWhiteSpace($pidStr)) {
            $pid = $pidStr
            $proc = Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue
            if ($proc) {
                $running = "Yes"
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

    # Check port if applicable
    if ($svc.Port -and $running -eq "Yes") {
        if (Test-TcpPort -HostName "127.0.0.1" -Port $svc.Port) {
            $notes = "port $($svc.Port) listening"
        } else {
            $notes = "port $($svc.Port) NOT listening"
        }
    }

    Write-Host ("{0,-12} {1,-8} {2,-10} {3}" -f $name, $pid, $running, $notes)
}

# Redis check
Write-Host ""
Write-Host "--- Infrastructure ---" -ForegroundColor Cyan
$redisOk = Test-RedisPing
if ($redisOk) {
    Write-Host "  Redis:  OK (127.0.0.1:6379)" -ForegroundColor Green
} else {
    Write-Host "  Redis:  NOT reachable" -ForegroundColor Red
}

# API health endpoint
if (Test-TcpPort -HostName "127.0.0.1" -Port 8000) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $body = $response.Content | ConvertFrom-Json
        $apiStatus = $body.api.status
        $dbStatus = $body.db.status
        $redisStatus = $body.redis.status
        Write-Host "  API:    $apiStatus | DB: $dbStatus | Redis(via API): $redisStatus"
    } catch {
        Write-Host "  API:    port 8000 listening but health check failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  API:    port 8000 NOT listening" -ForegroundColor Red
}

Write-Host ""
Write-Host "Logs: $(Join-Path $ProjectRoot 'storage\logs\prod')" -ForegroundColor DarkGray
Write-Host "PIDs: $(Join-Path $ProjectRoot 'storage\prod')" -ForegroundColor DarkGray
