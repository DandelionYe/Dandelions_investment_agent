# =============================================================================
# Dandelions Investment Agent - Production Service Launcher
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

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$LogsDir = Join-Path $ProjectRoot "storage\logs\prod"
$RuntimeDir = Join-Path $ProjectRoot "storage\runtime\prod"
$ReportsDir = Join-Path $ProjectRoot "storage\reports"
$ArtifactsDir = Join-Path $ProjectRoot "storage\artifacts"
$BackupsDir = Join-Path $ProjectRoot "backups"

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

function Test-RedisReachable {
    param([string]$RedisUrl)

    $Python = Get-VenvTool "python"
    if (-not $Python) { return $false }

    $script = "import os, redis; url=os.environ['DANDELIONS_REDIS_CHECK_URL']; r=redis.from_url(url, socket_connect_timeout=2, socket_timeout=2); print(r.ping()); r.close()"
    $env:DANDELIONS_REDIS_CHECK_URL = $RedisUrl
    try {
        $result = & $Python -c $script 2>&1
        return ($LASTEXITCODE -eq 0 -and ($result | Out-String) -match "True")
    } finally {
        Remove-Item Env:\DANDELIONS_REDIS_CHECK_URL -ErrorAction SilentlyContinue
    }
}

function Stop-ProcessTree {
    param([int]$Pid)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$Pid" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -Pid ([int]$child.ProcessId)
    }

    $proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue
    }
}

function Test-ManagedProcessMatchesMetadata {
    param(
        [System.Diagnostics.Process]$Process,
        [object]$Metadata,
        [string]$ExpectedService
    )

    if (-not $Metadata) {
        return $false
    }
    if ($Metadata.project_root -ne $ProjectRoot) {
        return $false
    }
    if ($Metadata.service -ne $ExpectedService) {
        return $false
    }
    if ([int]$Metadata.pid -ne [int]$Process.Id) {
        return $false
    }

    try {
        $actualStart = $Process.StartTime.ToUniversalTime()
        $recordedStart = [DateTime]::Parse($Metadata.start_time_utc).ToUniversalTime()
        return ([Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -lt 5)
    } catch {
        return $true
    }
}

function Stop-ExistingManagedService {
    param([string]$Name)

    $pidPath = Join-Path $RuntimeDir "$Name.pid"
    $metaPath = Join-Path $RuntimeDir "$Name.json"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return
    }

    $existingPid = (Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($existingPid)) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $metaPath -Force -ErrorAction SilentlyContinue
        return
    }

    $proc = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
    if ($proc) {
        $metadata = $null
        if (Test-Path -LiteralPath $metaPath) {
            try {
                $metadata = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
            } catch {
                Write-Warn "$Name metadata file is invalid: $_"
            }
        }

        if (-not (Test-ManagedProcessMatchesMetadata -Process $proc -Metadata $metadata -ExpectedService $Name)) {
            Write-Error-Exit "$Name PID $existingPid is not verified by metadata. Refusing to stop it automatically. Run stop_production_services.ps1 and inspect the PID files before retrying."
        }

        Write-Warn "$Name is already running (PID $existingPid). Stopping the previous managed process tree first."
        Stop-ProcessTree -Pid ([int]$existingPid)
        Start-Sleep -Seconds 2
    }

    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $metaPath -Force -ErrorAction SilentlyContinue
}

function Start-ManagedService {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$OutLogFileName,
        [string]$ErrLogFileName,
        [hashtable]$Metadata = @{}
    )

    $outLogPath = Join-Path $LogsDir $OutLogFileName
    $errLogPath = Join-Path $LogsDir $ErrLogFileName
    $pidPath = Join-Path $RuntimeDir "$Name.pid"
    $metaPath = Join-Path $RuntimeDir "$Name.json"

    Stop-ExistingManagedService -Name $Name

    Write-Status "  Starting $Name..."
    Write-Status "    Executable: $FilePath"
    Write-Status "    Stdout:     $outLogPath"
    Write-Status "    Stderr:     $errLogPath"
    Write-Status "    PID file:   $pidPath"

    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLogPath `
        -RedirectStandardError $errLogPath `
        -PassThru

    if (-not $process -or -not $process.Id) {
        Write-Warn "  Could not determine PID for $Name. Check logs manually."
        return
    }

    $process.Id | Out-File -FilePath $pidPath -Encoding ascii -Force
    $startTimeUtc = $null
    try {
        $startTimeUtc = (Get-Process -Id $process.Id -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
    } catch {
        $startTimeUtc = (Get-Date).ToUniversalTime().ToString("o")
    }

    $serviceMetadata = @{
        service = $Name
        pid = $process.Id
        start_time_utc = $startTimeUtc
        executable = $FilePath
        arguments = $Arguments
        project_root = $ProjectRoot
    }

    foreach ($key in $Metadata.Keys) {
        $serviceMetadata[$key] = $Metadata[$key]
    }

    $serviceMetadata | ConvertTo-Json -Depth 5 | Out-File -FilePath $metaPath -Encoding utf8 -Force
    Write-Status "    PID: $($process.Id)" "Green"
}

if ($Services -contains "all") {
    $Services = @("api", "worker", "beat", "streamlit")
}

Write-Status "=== Dandelions Production Service Launcher ===" "Cyan"
Write-Status "Project root: $ProjectRoot"
Write-Status ""

foreach ($dir in @($LogsDir, $RuntimeDir, $ReportsDir, $ArtifactsDir, $BackupsDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Status "--- Preflight Checks ---" "Cyan"
$preflightFailed = $false

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Error-Exit ".env not found. Copy .env.production.example to .env and configure it."
}
Write-Status "  [OK] .env exists" "Green"

if (-not (Test-Path -LiteralPath $VenvDir)) {
    Write-Error-Exit ".venv not found. Create it with: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
}
Write-Status "  [OK] .venv exists" "Green"

$envContent = Get-Content -LiteralPath $envFile -Raw -ErrorAction SilentlyContinue

$jwtVal = Get-DotEnvValue -Content $envContent -Name "JWT_SECRET"
if ($jwtVal) {
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

$adminPass = Get-DotEnvValue -Content $envContent -Name "AUTH_ADMIN_PASS"
if ($adminPass) {
    if ($adminPass -eq "dandelions2026" -or $adminPass -eq "__REPLACE_WITH_STRONG_ADMIN_PASSWORD__") {
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

$CeleryBrokerUrl = Get-DotEnvValue -Content $envContent -Name "CELERY_BROKER_URL"
if ($CeleryBrokerUrl) {
    Write-Status "  [OK] CELERY_BROKER_URL is set" "Green"
} else {
    Write-Warn "CELERY_BROKER_URL not found in .env"
    $preflightFailed = $true
}

$CeleryResultBackend = Get-DotEnvValue -Content $envContent -Name "CELERY_RESULT_BACKEND"
if ($CeleryResultBackend) {
    Write-Status "  [OK] CELERY_RESULT_BACKEND is set" "Green"
} else {
    Write-Warn "CELERY_RESULT_BACKEND not found in .env"
    $preflightFailed = $true
}

if ($CeleryBrokerUrl) {
    Write-Status "  Checking Redis via CELERY_BROKER_URL..."
    if (Test-RedisReachable -RedisUrl $CeleryBrokerUrl) {
        Write-Status "  [OK] Redis is reachable" "Green"
    } else {
        Write-Warn "Redis is NOT reachable via CELERY_BROKER_URL."
        Write-Warn "Start Redis before services: docker compose up -d redis"
        Write-Warn "Or use a WSL Redis instance with persistence enabled as documented."
        Write-Warn "See docs/production_operations.md for Redis persistence requirements."
        $preflightFailed = $true
    }
}

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

$Uvicorn = Get-VenvTool "uvicorn"
$Celery = Get-VenvTool "celery"
$Streamlit = Get-VenvTool "streamlit"

if (-not $Uvicorn) { Write-Error-Exit "uvicorn not found in .venv\Scripts" }
if (-not $Celery) { Write-Error-Exit "celery not found in .venv\Scripts" }
if (-not $Streamlit) { Write-Error-Exit "streamlit not found in .venv\Scripts" }

Write-Status "--- Starting Services ---" "Cyan"

if ($Services -contains "api") {
    Start-ManagedService -Name "api" `
        -FilePath $Uvicorn `
        -Arguments @("apps.api.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--workers", "2", "--log-level", "info") `
        -OutLogFileName "api.out.log" `
        -ErrLogFileName "api.err.log" `
        -Metadata @{ port = $ApiPort }
}

if ($Services -contains "worker") {
    Start-ManagedService -Name "worker" `
        -FilePath $Celery `
        -Arguments @("-A", "apps.api.celery_app", "worker", "--loglevel=info", "--concurrency=$CeleryConcurrency") `
        -OutLogFileName "celery-worker.out.log" `
        -ErrLogFileName "celery-worker.err.log" `
        -Metadata @{ concurrency = $CeleryConcurrency }
}

if ($Services -contains "beat") {
    $schedulePath = Join-Path $RuntimeDir "celerybeat-schedule"
    Start-ManagedService -Name "beat" `
        -FilePath $Celery `
        -Arguments @("-A", "apps.api.celery_app", "beat", "--loglevel=info", "--schedule", $schedulePath) `
        -OutLogFileName "celery-beat.out.log" `
        -ErrLogFileName "celery-beat.err.log" `
        -Metadata @{ schedule = $schedulePath }
}

if ($Services -contains "streamlit") {
    Start-ManagedService -Name "streamlit" `
        -FilePath $Streamlit `
        -Arguments @("run", "apps/dashboard/Home.py", "--server.address", "127.0.0.1", "--server.port", "$StreamlitPort", "--server.headless", "true") `
        -OutLogFileName "streamlit.out.log" `
        -ErrLogFileName "streamlit.err.log" `
        -Metadata @{ port = $StreamlitPort }
}

Write-Status ""
Write-Status "=== Services Started ===" "Green"
Write-Status "  API:       http://127.0.0.1:$ApiPort/docs"
Write-Status "  Streamlit: http://127.0.0.1:$StreamlitPort"
Write-Status ""
Write-Status "Logs:   $LogsDir"
Write-Status "PIDs:   $RuntimeDir"
Write-Status ""
Write-Status "Check status:  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1 -ApiPort $ApiPort -StreamlitPort $StreamlitPort"
Write-Status "Stop services: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1"
