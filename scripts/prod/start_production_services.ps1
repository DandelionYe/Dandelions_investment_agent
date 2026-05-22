# =============================================================================
# Dandelions Investment Agent — Production Service Launcher
# =============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1
#
# Start specific services only:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services api,worker
#
# Custom ports:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -ApiPort 9000 -StreamlitPort 9501
# =============================================================================

[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$StreamlitPort = 8501,
    [int]$CeleryConcurrency = 2,
    [ValidateSet("api", "worker", "beat", "streamlit", "all")]
    [string[]]$Services = @("all")
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# --- Resolve project root ---
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$LogsDir = Join-Path $ProjectRoot "storage\logs\prod"
$RuntimeDir = Join-Path $ProjectRoot "storage\prod"
$ReportsDir = Join-Path $ProjectRoot "storage\reports"
$ArtifactsDir = Join-Path $ProjectRoot "storage\artifacts"
$BackupsDir = Join-Path $ProjectRoot "backups"

# --- Helper functions ---

function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host $Message -ForegroundColor $Color
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Exit {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Get-VenvTool {
    param([string]$ToolName)
    $tool = Join-Path $VenvDir "Scripts\$ToolName.exe"
    if (Test-Path -LiteralPath $tool) {
        return $tool
    }
    return $null
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

function Test-RedisReachable {
    $Python = Get-VenvTool "python"
    if (-not $Python) { return $false }
    $result = & $Python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379/0', socket_connect_timeout=2, socket_timeout=2); print(r.ping()); r.close()" 2>&1
    return ($LASTEXITCODE -eq 0 -and ($result | Out-String) -match "True")
}

function Start-BackgroundService {
    param(
        [string]$Name,
        [string]$Command,
        [string]$LogFileName
    )

    $logPath = Join-Path $LogsDir $LogFileName
    $pidPath = Join-Path $RuntimeDir "$Name.pid"

    # Stop existing PID if still running
    if (Test-Path -LiteralPath $pidPath) {
        $existingPid = Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue
        if ($existingPid) {
            $proc = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Warn "$Name is already running (PID $existingPid). Stopping first..."
                Stop-Process -Id ([int]$existingPid) -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    }

    Write-Status "  Starting $Name..."
    Write-Status "    Log: $logPath"
    Write-Status "    PID file: $pidPath"

    $scriptBlock = [scriptblock]::Create($Command)
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "Set-Location -LiteralPath '$ProjectRoot'; `$Host.UI.RawUI.WindowTitle = 'Dandelions Prod - $Name'; $Command 2>&1 | Tee-Object -FilePath '$logPath'"
    ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru

    if ($process -and $process.Id) {
        $process.Id | Out-File -FilePath $pidPath -Encoding ascii -Force
        Write-Status "    PID: $($process.Id)" "Green"
    } else {
        Write-Warn "  Could not determine PID for $Name. Check log manually."
    }
}

# --- Expand 'all' to individual services ---
if ($Services -contains "all") {
    $Services = @("api", "worker", "beat", "streamlit")
}

# --- Create directories ---
Write-Status "=== Dandelions Production Service Launcher ===" "Cyan"
Write-Status "Project root: $ProjectRoot"
Write-Status ""

foreach ($dir in @($LogsDir, $RuntimeDir, $ReportsDir, $ArtifactsDir, $BackupsDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

# --- Preflight checks ---
Write-Status "--- Preflight Checks ---" "Cyan"
$preflightFailed = $false

# 1. .env exists
$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Error-Exit ".env not found. Copy .env.production.example to .env and configure it."
}
Write-Status "  [OK] .env exists" "Green"

# 2. .venv exists
if (-not (Test-Path -LiteralPath $VenvDir)) {
    Write-Error-Exit ".venv not found. Create it with: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
}
Write-Status "  [OK] .venv exists" "Green"

# 3. Check JWT_SECRET is not the example value
$envContent = Get-Content -LiteralPath $envFile -Raw -ErrorAction SilentlyContinue
if ($envContent -match 'JWT_SECRET\s*=\s*(.+)') {
    $jwtVal = $Matches[1].Trim()
    if ($jwtVal -eq "change-me-use-secrets-token-urlsafe-48-or-longer" -or $jwtVal.Length -lt 32) {
        Write-Warn "JWT_SECRET appears to be the example value or is shorter than 32 characters."
        Write-Warn "Generate a secure one: python -c `"import secrets; print(secrets.token_urlsafe(48))`""
        $preflightFailed = $true
    } else {
        Write-Status "  [OK] JWT_SECRET is set (length=$($jwtVal.Length))" "Green"
    }
} else {
    Write-Warn "JWT_SECRET not found in .env"
    $preflightFailed = $true
}

# 4. Check AUTH_ADMIN_PASS
if ($envContent -match 'AUTH_ADMIN_PASS\s*=\s*(.+)') {
    $adminPass = $Matches[1].Trim()
    if ($adminPass -eq "dandelions2026" -or $adminPass -eq "__REPLACE_WITH_STRONG_ADMIN_PASSWORD__" -or [string]::IsNullOrWhiteSpace($adminPass)) {
        Write-Warn "AUTH_ADMIN_PASS appears to be the example/placeholder value."
        Write-Warn "Set a strong password for production."
        $preflightFailed = $true
    } else {
        Write-Status "  [OK] AUTH_ADMIN_PASS is set" "Green"
    }
} else {
    Write-Warn "AUTH_ADMIN_PASS not found in .env"
    $preflightFailed = $true
}

# 5. Check CELERY_BROKER_URL and CELERY_RESULT_BACKEND
if ($envContent -match 'CELERY_BROKER_URL\s*=\s*(.+)') {
    Write-Status "  [OK] CELERY_BROKER_URL is set" "Green"
} else {
    Write-Warn "CELERY_BROKER_URL not found in .env"
    $preflightFailed = $true
}

if ($envContent -match 'CELERY_RESULT_BACKEND\s*=\s*(.+)') {
    Write-Status "  [OK] CELERY_RESULT_BACKEND is set" "Green"
} else {
    Write-Warn "CELERY_RESULT_BACKEND not found in .env"
    $preflightFailed = $true
}

# 6. Check Redis connectivity
Write-Status "  Checking Redis at 127.0.0.1:6379..."
if (Test-RedisReachable) {
    Write-Status "  [OK] Redis is reachable" "Green"
} else {
    Write-Warn "Redis is NOT reachable at 127.0.0.1:6379."
    Write-Warn "Start Redis before services: docker compose up -d redis"
    Write-Warn "Or: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1"
    Write-Warn "See docs/production_operations.md for Redis persistence requirements."
    $preflightFailed = $true
}

# 7. QMT status (non-blocking)
$Python = Get-VenvTool "python"
if ($Python) {
    $qmtCheck = & $Python -c "
try:
    from xtquant import xtdata
    xtdata.connect()
    print('ok')
except Exception as e:
    print(f'not_ready: {e}')
" 2>&1
    $qmtStr = ($qmtCheck | Out-String).Trim()
    if ($qmtStr -match "^ok$") {
        Write-Status "  [OK] QMT/xtquant is connected" "Green"
    } else {
        Write-Warn "QMT/xtquant is not ready: $qmtStr"
        Write-Warn "QMT is not required for all services, but research tasks will fail without it."
        Write-Warn "See docs/production_operations.md for QMT setup instructions."
    }
}

Write-Status ""

if ($preflightFailed) {
    Write-Error-Exit "Preflight checks failed. Fix the issues above before starting services."
}

# --- Build tool paths ---
$Uvicorn = Get-VenvTool "uvicorn"
$Celery = Get-VenvTool "celery"
$Streamlit = Get-VenvTool "streamlit"

if (-not $Uvicorn) { Write-Error-Exit "uvicorn not found in .venv\Scripts" }
if (-not $Celery) { Write-Error-Exit "celery not found in .venv\Scripts" }
if (-not $Streamlit) { Write-Error-Exit "streamlit not found in .venv\Scripts" }

# --- Start services ---
Write-Status "--- Starting Services ---" "Cyan"

if ($Services -contains "api") {
    Start-BackgroundService -Name "api" `
        -Command "& '$Uvicorn' apps.api.main:app --host 127.0.0.1 --port $ApiPort --workers 2 --log-level info" `
        -LogFileName "api.log"
}

if ($Services -contains "worker") {
    Start-BackgroundService -Name "worker" `
        -Command "& '$Celery' -A apps.api.celery_app worker --loglevel=info --concurrency=$CeleryConcurrency" `
        -LogFileName "celery-worker.log"
}

if ($Services -contains "beat") {
    Start-BackgroundService -Name "beat" `
        -Command "& '$Celery' -A apps.api.celery_app beat --loglevel=info --schedule '$RuntimeDir\celerybeat-schedule'" `
        -LogFileName "celery-beat.log"
}

if ($Services -contains "streamlit") {
    Start-BackgroundService -Name "streamlit" `
        -Command "& '$Streamlit' run apps/dashboard/Home.py --server.address 127.0.0.1 --server.port $StreamlitPort --server.headless true" `
        -LogFileName "streamlit.log"
}

Write-Status ""
Write-Status "=== Services Started ===" "Green"
Write-Status "  API:       http://127.0.0.1:$ApiPort/docs"
Write-Status "  Streamlit: http://127.0.0.1:$StreamlitPort"
Write-Status ""
Write-Status "Logs:   $LogsDir"
Write-Status "PIDs:   $RuntimeDir"
Write-Status ""
Write-Status "Check status:  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1"
Write-Status "Stop services: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1"
