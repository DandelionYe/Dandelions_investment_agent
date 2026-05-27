# =============================================================================
# Dandelions Investment Agent - Offline CI Script
# =============================================================================
# Runs the same offline checks as the default GitHub Actions CI workflow.
# Does NOT start/stop any services. Does NOT require QMT/Redis/Celery/Streamlit.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_offline_ci.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_offline_ci.ps1 -SkipRuff
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_offline_ci.ps1 -SkipPytest
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_offline_ci.ps1 -OutputDir storage\artifacts\verification\offline_ci
# =============================================================================

[CmdletBinding()]
param(
    [switch]$SkipRuff,
    [switch]$SkipPytest,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Continue"

# Fix encoding for Windows PowerShell 5.1 (chcp 65001 + UTF-8 I/O)
try { chcp 65001 > $null } catch {}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[FAIL] Python venv not found: $VenvPython" -ForegroundColor Red
    exit 1
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot "storage\artifacts\verification\offline_ci"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunDir = Join-Path $OutputDir $Timestamp

# Ensure output directories exist
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

# Force Python child processes to use UTF-8
$env:PYTHONIOENCODING = "utf-8"

# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------

$RuffPassed = $true
$PytestRuntimePassed = $true
$PytestOfflinePassed = $true
$StepsRun = 0
$StepsPassed = 0

# ---------------------------------------------------------------------------
# Ruff check
# ---------------------------------------------------------------------------

if (-not $SkipRuff) {
    Write-Host ""
    Write-Host "=== Step 1/3: Ruff Lint ===" -ForegroundColor Cyan
    $StepsRun++

    $ruffOutputFile = Join-Path $RunDir "ruff_output.txt"

    # Scope ruff to CI-related and core stable files only.
    # The full repo has pre-existing lint issues that are out of scope for CI gating.
    $ruffTargets = @(
        "scripts\run_runtime_verification.py",
        "tests\test_ci_workflow_contract.py",
        "tests\integration\test_runtime_matrix_contract.py",
        "main.py",
        "services\orchestrator\single_asset_research.py",
        "services\research\scoring_engine.py",
        "services\research\decision_guard.py"
    )

    $ruffArgs = @("-m", "ruff", "check") + $ruffTargets
    & $VenvPython @ruffArgs 2>&1 | Tee-Object -Variable ruffResult
    $ruffExitCode = $LASTEXITCODE

    # Save ruff output
    ($ruffResult | Out-String) | Out-File -FilePath $ruffOutputFile -Encoding utf8

    if ($ruffExitCode -ne 0) {
        Write-Host "[WARN] Ruff check reported issues (exit $ruffExitCode)" -ForegroundColor Yellow
        $RuffPassed = $false
    } else {
        Write-Host "[PASS] Ruff check clean" -ForegroundColor Green
        $StepsPassed++
    }
} else {
    Write-Host ""
    Write-Host "=== Step 1/3: Ruff Lint (SKIPPED) ===" -ForegroundColor DarkGray
    "Skipped by user request" | Out-File -FilePath (Join-Path $RunDir "ruff_output.txt") -Encoding utf8
}

# ---------------------------------------------------------------------------
# Runtime matrix contract tests
# ---------------------------------------------------------------------------

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== Step 2/3: Runtime Matrix Contract Tests ===" -ForegroundColor Cyan
    $StepsRun++

    $runtimeContractFile = Join-Path $RunDir "pytest_runtime_contract.txt"
    $pytestRuntimeArgs = @(
        "-m", "pytest",
        "tests\integration\test_runtime_matrix_contract.py",
        "-q", "-p", "no:cacheprovider"
    )
    & $VenvPython @pytestRuntimeArgs 2>&1 | Tee-Object -Variable runtimeResult
    $runtimeExitCode = $LASTEXITCODE

    ($runtimeResult | Out-String) | Out-File -FilePath $runtimeContractFile -Encoding utf8

    if ($runtimeExitCode -ne 0) {
        Write-Host "[WARN] Runtime contract tests failed (exit $runtimeExitCode)" -ForegroundColor Yellow
        $PytestRuntimePassed = $false
    } else {
        Write-Host "[PASS] Runtime contract tests passed" -ForegroundColor Green
        $StepsPassed++
    }
} else {
    Write-Host ""
    Write-Host "=== Step 2/3: Runtime Matrix Contract Tests (SKIPPED) ===" -ForegroundColor DarkGray
    "Skipped by user request" | Out-File -FilePath (Join-Path $RunDir "pytest_runtime_contract.txt") -Encoding utf8
}

# ---------------------------------------------------------------------------
# Stable offline tests
# ---------------------------------------------------------------------------

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== Step 3/3: Stable Offline Tests ===" -ForegroundColor Cyan
    $StepsRun++

    $offlineFile = Join-Path $RunDir "pytest_offline.txt"
    $stableTests = @(
        "tests\test_cli.py",
        "tests\test_llm_json_guard.py",
        "tests\test_security_config.py",
        "tests\test_celery_schedule.py",
        "tests\test_provider_errors.py",
        "tests\test_web_news_provider.py",
        "tests\test_report_pipeline.py",
        "tests\test_valuation_percentile.py",
        "tests\test_scoring_engine.py",
        "tests\test_decision_guard.py",
        "tests\test_evidence_schema_contract.py",
        "tests\test_data_quality_regression_contract.py",
        "tests\test_production_operations_contract.py",
        "tests\test_historical_samples_contract.py",
        "tests\test_research_quality_baseline_contract.py",
        "tests\test_auth.py",
        "tests\test_rbac_auth_admin.py",
        "tests\test_rbac_report_access.py",
        "tests\test_rbac_task_access.py",
        "tests\test_rbac_watchlist_access.py",
        "tests\test_dashboard_rbac_contract.py",
        "tests\test_dashboard_auth_client.py",
        "tests\test_langgraph_orchestrator.py",
        "tests\test_watchlist_store.py",
        "tests\test_ci_workflow_contract.py"
    )

    # Deselect test_report_pipeline.py::test_qmt_industry_valuation_reaches_pipeline_evidence_and_reports
    # because it uses tmp_path which triggers PermissionError on some Windows machines
    # (C:\Users\admin\AppData\Local\Temp\pytest-of-admin). This is a local env issue, not a test bug.
    # GitHub Actions windows-latest does not have this issue.
    $pytestOfflineArgs = @("-m", "pytest") + $stableTests + @(
        "--deselect", "tests/test_report_pipeline.py::test_qmt_industry_valuation_reaches_pipeline_evidence_and_reports",
        "-q", "-p", "no:cacheprovider"
    )
    & $VenvPython @pytestOfflineArgs 2>&1 | Tee-Object -Variable offlineResult
    $offlineExitCode = $LASTEXITCODE

    ($offlineResult | Out-String) | Out-File -FilePath $offlineFile -Encoding utf8

    if ($offlineExitCode -ne 0) {
        Write-Host "[WARN] Some offline tests failed (exit $offlineExitCode)" -ForegroundColor Yellow
        $PytestOfflinePassed = $false
    } else {
        Write-Host "[PASS] All offline tests passed" -ForegroundColor Green
        $StepsPassed++
    }
} else {
    Write-Host ""
    Write-Host "=== Step 3/3: Stable Offline Tests (SKIPPED) ===" -ForegroundColor DarkGray
    "Skipped by user request" | Out-File -FilePath (Join-Path $RunDir "pytest_offline.txt") -Encoding utf8
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

$OverallPassed = $RuffPassed -and $PytestRuntimePassed -and $PytestOfflinePassed

$summary = @{
    timestamp       = $Timestamp
    overall_status  = if ($OverallPassed) { "pass" } else { "fail" }
    steps_run       = $StepsRun
    steps_passed    = $StepsPassed
    ruff            = if ($SkipRuff) { "skipped" } elseif ($RuffPassed) { "pass" } else { "fail" }
    runtime_contract= if ($SkipPytest) { "skipped" } elseif ($PytestRuntimePassed) { "pass" } else { "fail" }
    offline_tests   = if ($SkipPytest) { "skipped" } elseif ($PytestOfflinePassed) { "pass" } else { "fail" }
    artifact_dir    = $RunDir
}

$summaryJson = $summary | ConvertTo-Json -Depth 3
$summaryJson | Out-File -FilePath (Join-Path $RunDir "summary.json") -Encoding utf8

# Generate summary.md
$mdLines = @(
    "# Offline CI Report",
    "",
    "- **Timestamp**: $Timestamp",
    "- **Overall**: $($summary.overall_status)",
    "- **Steps run**: $StepsRun / 3",
    "- **Steps passed**: $StepsPassed / $StepsRun",
    "",
    "## Results",
    "",
    "| Step | Status |",
    "|------|--------|",
    "| Ruff lint | $($summary.ruff) |",
    "| Runtime contract tests | $($summary.runtime_contract) |",
    "| Stable offline tests | $($summary.offline_tests) |",
    "",
    "## Artifact files",
    "",
    "- ``ruff_output.txt``",
    "- ``pytest_runtime_contract.txt``",
    "- ``pytest_offline.txt``",
    "- ``summary.json``",
    "- ``summary.md``",
    ""
)
($mdLines -join "`n") | Out-File -FilePath (Join-Path $RunDir "summary.md") -Encoding utf8

# Copy to latest.json / latest.md
Copy-Item (Join-Path $RunDir "summary.json") (Join-Path $OutputDir "latest.json") -Force
Copy-Item (Join-Path $RunDir "summary.md") (Join-Path $OutputDir "latest.md") -Force

# Console summary
Write-Host ""
Write-Host "============================================" -ForegroundColor $(if ($OverallPassed) { "Green" } else { "Red" })
if ($OverallPassed) {
    Write-Host "  OFFLINE CI: ALL PASSED ($StepsPassed/$StepsRun)" -ForegroundColor Green
} else {
    Write-Host "  OFFLINE CI: FAILED ($StepsPassed/$StepsRun passed)" -ForegroundColor Red
}
Write-Host "============================================" -ForegroundColor $(if ($OverallPassed) { "Green" } else { "Red" })
Write-Host ""
Write-Host "Artifact dir: $RunDir"
Write-Host "Latest:       $(Join-Path $OutputDir 'latest.json')"
Write-Host ""

if ($OverallPassed) {
    exit 0
} else {
    exit 1
}
