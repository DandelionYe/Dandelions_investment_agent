# Dandelions investment agent Redis launcher.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1
#
# This script starts Redis inside WSL and keeps this PowerShell window open as
# a small monitor. Leave it running while FastAPI/Celery async mode is in use.

[CmdletBinding()]
param(
    [string]$Distro = $env:WSL_REDIS_DISTRO,
    [int]$Port = 6379,
    [int]$MonitorIntervalSeconds = 5
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

if ([string]::IsNullOrWhiteSpace($Distro)) {
    $Distro = "Ubuntu"
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

function Get-ProjectPython {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }
    return "python"
}

function Test-PythonRedis {
    $Python = Get-ProjectPython
    $pyResult = & $Python -c "import redis; r=redis.from_url('redis://127.0.0.1:$Port/0', socket_connect_timeout=1, socket_timeout=1); print(r.ping()); r.close()" 2>&1
    return ($LASTEXITCODE -eq 0 -and $pyResult -match "True")
}

function Start-WslRedis {
    Write-Host "Starting Redis via WSL distro '$Distro'..." -ForegroundColor Cyan

    & wsl -d $Distro -- bash -lc "command -v redis-server >/dev/null 2>&1"
    if ($LASTEXITCODE -eq 0) {
        $cmd = "redis-cli -p $Port shutdown nosave >/dev/null 2>&1 || true; redis-server --port $Port --bind 0.0.0.0 --protected-mode no --save '' --appendonly no --daemonize yes --logfile /tmp/dandelions-redis.log"
        & wsl -d $Distro -- bash -lc $cmd
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        Write-Host "  [WARN] redis-server daemon startup failed; falling back to service startup." -ForegroundColor Yellow
    } else {
        Write-Host "  [WARN] redis-server was not found in WSL PATH; falling back to service startup." -ForegroundColor Yellow
    }

    Write-Host "If sudo asks for a password, enter your WSL password in this window." -ForegroundColor Yellow
    & wsl -d $Distro -- sudo service redis-server start
    return ($LASTEXITCODE -eq 0)
}

function Wait-RedisReady {
    param([int]$TimeoutSeconds = 30)

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        Start-Sleep -Seconds 1
        if ((Test-TcpPort -HostName "127.0.0.1" -Port $Port) -and (Test-PythonRedis)) {
            return $true
        }
    }
    return $false
}

Write-Host "Checking Redis at 127.0.0.1:$Port..." -ForegroundColor Cyan
if ((Test-TcpPort -HostName "127.0.0.1" -Port $Port) -and (Test-PythonRedis)) {
    Write-Host "  [OK] Redis is already reachable (127.0.0.1:$Port)" -ForegroundColor Green
} else {
    if (-not (Start-WslRedis)) {
        Write-Host "  [FAIL] Could not start Redis through WSL distro '$Distro'." -ForegroundColor Red
        Write-Host "         Set WSL_REDIS_DISTRO to your installed distro name, or start Redis manually." -ForegroundColor Yellow
        Write-Host "         Example: `$env:WSL_REDIS_DISTRO='Ubuntu-22.04'" -ForegroundColor Yellow
        exit 1
    }

    if (Wait-RedisReady -TimeoutSeconds 30) {
        Write-Host "  [OK] Redis is running and Python connectivity is verified." -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] Redis start command completed, but 127.0.0.1:$Port is not usable from Windows Python." -ForegroundColor Red
        Write-Host "         Check WSL log: wsl -d $Distro -- tail -n 80 /tmp/dandelions-redis.log" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Monitoring Redis every $MonitorIntervalSeconds seconds. Keep this window open." -ForegroundColor Cyan
while ($true) {
    Start-Sleep -Seconds $MonitorIntervalSeconds
    if ((Test-TcpPort -HostName "127.0.0.1" -Port $Port) -and (Test-PythonRedis)) {
        continue
    }

    Write-Host "  [WARN] Redis is not reachable. Restarting..." -ForegroundColor Yellow
    if ((Start-WslRedis) -and (Wait-RedisReady -TimeoutSeconds 30)) {
        Write-Host "  [OK] Redis restarted." -ForegroundColor Green
    } else {
        Write-Host "  [WARN] Redis restart failed; will retry in $MonitorIntervalSeconds seconds." -ForegroundColor Yellow
    }
}
