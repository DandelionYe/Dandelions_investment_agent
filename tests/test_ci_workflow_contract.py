"""Contract tests for the CI workflow configuration.

Verifies that .github/workflows/ci.yml meets the project's CI contract:
- Uses windows-latest
- Uses Python 3.13
- Does NOT set live integration environment variables
- Does NOT start/stop services
- Runs runtime matrix contract tests
- Runs stable offline tests
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


class TestCIWorkflowExists:
    def test_ci_yml_exists(self):
        assert CI_WORKFLOW.is_file(), ".github/workflows/ci.yml not found"


class TestCIWorkflowPlatform:
    def test_uses_windows_latest(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "windows-latest" in content, "CI must use windows-latest"

    def test_uses_python_313(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert 'python-version: "3.13"' in content, "CI must use Python 3.13"


class TestCIWorkflowNoLiveEnvVars:
    """CI must NOT set live integration opt-in environment variables."""

    FORBIDDEN_ENV_VARS = [
        "RUN_QMT_INTEGRATION",
        "RUN_NETWORK_INTEGRATION",
        "RUN_STREAMLIT_INTEGRATION",
        "RUN_RUNTIME_INTEGRATION",
        "RUN_LIVE_INTEGRATION",
        "RUN_AKSHARE_NETWORK",
        "RUN_WEB_NEWS_NETWORK",
    ]

    def test_no_live_env_vars(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        for var in self.FORBIDDEN_ENV_VARS:
            assert var not in content, f"CI must not set {var}"


class TestCIWorkflowNoServiceStartup:
    """CI must NOT start or stop services."""

    def test_no_start_dev_services(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "start_dev_services" not in content, "CI must not call start_dev_services.ps1"

    def test_no_verify_runtime_matrix_live(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        # verify_runtime_matrix.ps1 is for live verification, not CI
        assert "verify_runtime_matrix.ps1" not in content, (
            "CI must not call verify_runtime_matrix.ps1 (live verification)"
        )


class TestCIWorkflowRunsContractTests:
    """CI must run the runtime matrix contract tests."""

    def test_runs_runtime_matrix_contract(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "test_runtime_matrix_contract.py" in content, (
            "CI must run tests/integration/test_runtime_matrix_contract.py"
        )


class TestCIWorkflowRunsStableOfflineTests:
    """CI must run a curated set of stable offline tests."""

    REQUIRED_TEST_FILES = [
        "test_cli.py",
        "test_llm_json_guard.py",
        "test_security_config.py",
        "test_scoring_engine.py",
        "test_decision_guard.py",
        "test_auth.py",
    ]

    def test_runs_stable_tests(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        for test_file in self.REQUIRED_TEST_FILES:
            assert test_file in content, f"CI must run {test_file}"


class TestCIWorkflowLint:
    """CI must include linting via ruff."""

    def test_runs_ruff(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "ruff" in content.lower(), "CI must include ruff lint step"


class TestOfflineCIScriptExists:
    """The local offline CI script must exist."""

    def test_script_exists(self):
        script = PROJECT_ROOT / "scripts" / "run_offline_ci.ps1"
        assert script.is_file(), "scripts/run_offline_ci.ps1 not found"
