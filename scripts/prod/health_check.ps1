# =============================================================================
# Dandelions Investment Agent - Production Health Check
# =============================================================================
# Designed for scheduled tasks or manual verification.
# Returns exit code 0 on success, non-zero on failure.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\health_check.ps1
#   echo $LASTEXITCODE
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
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000)
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

function Test-ServiceAlive {
    param([string]$Name)
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return $false }
    $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($pidStr)) { return $false }
    $proc = Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue
    return ($null -ne $proc)
}

$checks = @()
$allOk = $true

$redisUrl = Get-RedisUrl
$redisOk = Test-RedisPing -RedisUrl $redisUrl
$checks += @{ Name = "Redis"; Ok = $redisOk; Detail = "from CELERY_BROKER_URL" }
if (-not $redisOk) { $allOk = $false }

$apiOk = $false
$apiDetail = ""
if (Test-TcpPort -HostName "127.0.0.1" -Port $ApiPort) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $body = $response.Content | ConvertFrom-Json
        $apiOk = ($body.api.status -eq "ok")
        $apiDetail = "api=$($body.api.status) db=$($body.db.status) redis=$($body.redis.status)"
    } catch {
        $apiDetail = "health endpoint error: $_"
    }
} else {
    $apiDetail = "port $ApiPort not listening"
}
$checks += @{ Name = "API"; Ok = $apiOk; Detail = $apiDetail }
if (-not $apiOk) { $allOk = $false }

$workerOk = Test-ServiceAlive -Name "worker"
$checks += @{ Name = "Celery Worker"; Ok = $workerOk; Detail = if ($workerOk) { "running" } else { "not running" } }
if (-not $workerOk) { $allOk = $false }

$beatOk = Test-ServiceAlive -Name "beat"
$checks += @{ Name = "Celery Beat"; Ok = $beatOk; Detail = if ($beatOk) { "running" } else { "not running" } }
if (-not $beatOk) { $allOk = $false }

$streamlitOk = Test-TcpPort -HostName "127.0.0.1" -Port $StreamlitPort
$checks += @{ Name = "Streamlit"; Ok = $streamlitOk; Detail = if ($streamlitOk) { "port $StreamlitPort listening" } else { "port $StreamlitPort not listening" } }
if (-not $streamlitOk) { $allOk = $false }

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$timestamp] Dandelions Health Check" -ForegroundColor Cyan
foreach ($c in $checks) {
    $icon = if ($c.Ok) { "OK" } else { "FAIL" }
    $color = if ($c.Ok) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1,-16} {2}" -f $icon, $c.Name, $c.Detail) -ForegroundColor $color
}

if ($allOk) {
    Write-Host ""
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "One or more checks FAILED." -ForegroundColor Red
    exit 1
}
