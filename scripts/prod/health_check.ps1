# =============================================================================
# Dandelions Investment Agent — Production Health Check
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
$RuntimeDir = Join-Path $ProjectRoot "storage\prod"

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
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { return $false }
    $result = & $Python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379/0', socket_connect_timeout=2, socket_timeout=2); print(r.ping()); r.close()" 2>&1
    return ($LASTEXITCODE -eq 0 -and ($result | Out-String) -match "True")
}

function Test-ServiceAlive {
    param([string]$Name)
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return $false }
    $pidStr = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue).Trim()
    if ([string]::IsNullOrWhiteSpace($pidStr)) { return $false }
    $proc = Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue
    return ($null -ne $proc)
}

$checks = @()
$allOk = $true

# 1. Redis
$redisOk = Test-RedisPing
$checks += @{ Name = "Redis"; Ok = $redisOk; Detail = "127.0.0.1:6379" }
if (-not $redisOk) { $allOk = $false }

# 2. API health endpoint
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

# 3. Celery worker
$workerOk = Test-ServiceAlive -Name "worker"
$checks += @{ Name = "Celery Worker"; Ok = $workerOk; Detail = if ($workerOk) { "running" } else { "not running" } }
if (-not $workerOk) { $allOk = $false }

# 4. Celery Beat
$beatOk = Test-ServiceAlive -Name "beat"
$checks += @{ Name = "Celery Beat"; Ok = $beatOk; Detail = if ($beatOk) { "running" } else { "not running" } }
if (-not $beatOk) { $allOk = $false }

# 5. Streamlit
$streamlitOk = Test-TcpPort -HostName "127.0.0.1" -Port $StreamlitPort
$checks += @{ Name = "Streamlit"; Ok = $streamlitOk; Detail = if ($streamlitOk) { "port $StreamlitPort listening" } else { "port $StreamlitPort not listening" } }
if (-not $streamlitOk) { $allOk = $false }

# Output
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
