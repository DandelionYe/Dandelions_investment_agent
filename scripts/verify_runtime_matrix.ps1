# =============================================================================
# Dandelions Investment Agent - Runtime Verification Matrix
# =============================================================================
# Unified local smoke entry point. Checks current running state of all services
# without starting or stopping anything.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_runtime_matrix.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_runtime_matrix.ps1 -Strict
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_runtime_matrix.ps1 -IncludeQmt -IncludeStreamlit
# =============================================================================

[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [switch]$Strict,
    [switch]$IncludeQmt,
    [switch]$IncludeStreamlit,
    [switch]$IncludeWebsocket
)

$ErrorActionPreference = "Continue"

# Fix encoding for Windows PowerShell 5.1 (chcp 65001 + UTF-8 I/O)
try { chcp 65001 > $null } catch {}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[FAIL] Python venv not found: $VenvPython" -ForegroundColor Red
    exit 1
}

# Build Python args
$pyArgs = @(
    (Join-Path $ProjectRoot "scripts\run_runtime_verification.py")
)

if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot "storage\artifacts\verification"
}
$pyArgs += "--output-dir", $OutputDir

if ($Strict) {
    $pyArgs += "--strict"
}
if ($IncludeQmt) {
    $pyArgs += "--include-qmt"
}
if ($IncludeStreamlit) {
    $pyArgs += "--include-streamlit"
}
if ($IncludeWebsocket) {
    $pyArgs += "--include-websocket"
}

# Force Python child processes to use UTF-8
$env:PYTHONIOENCODING = "utf-8"

# Run verification
& $VenvPython @pyArgs
$exitCode = $LASTEXITCODE

exit $exitCode
