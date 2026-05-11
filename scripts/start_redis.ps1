# Dandelions investment agent — Redis launcher
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

Write-Host "Starting Redis via WSL..." -ForegroundColor Cyan

# 1. Start Redis (WSL VM auto-starts if not running)
$null = wsl -d Ubuntu -- sudo service redis-server start 2>&1

# 2. Verify Redis inside WSL
$pingResult = (wsl -d Ubuntu -- redis-cli ping 2>&1 | Out-String).Trim()
if ($pingResult -eq "PONG") {
    Write-Host "  [OK] Redis is running (127.0.0.1:6379)" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Redis did not start: $pingResult" -ForegroundColor Red
    exit 1
}

# 3. Verify from Windows Python
$pyResult = python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379/0'); print(r.ping()); r.close()" 2>&1
if ($LASTEXITCODE -eq 0 -and $pyResult -match "True") {
    Write-Host "  [OK] Windows-side Redis connectivity verified" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Python connectivity check failed (FastAPI may still need restart)" -ForegroundColor Yellow
    Write-Host "         $pyResult" -ForegroundColor Yellow
}

Write-Host "`nNext: restart uvicorn, then run .\scripts\API_Test.ps1" -ForegroundColor Cyan
