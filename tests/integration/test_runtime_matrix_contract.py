"""Contract tests for the runtime verification matrix.

These tests verify static properties of the verification infrastructure:
scripts exist, markers are registered, artifact schema is valid, etc.
They run by default without any external dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "scripts"
INTEGRATION = PROJECT_ROOT / "tests" / "integration"


# ---------------------------------------------------------------------------
# Script existence
# ---------------------------------------------------------------------------


class TestVerificationScriptsExist:
    def test_python_runner_exists(self):
        assert (SCRIPTS / "run_runtime_verification.py").is_file()

    def test_powershell_entry_exists(self):
        assert (SCRIPTS / "verify_runtime_matrix.ps1").is_file()

    def test_start_dev_services_exists(self):
        assert (SCRIPTS / "start_dev_services.ps1").is_file()


# ---------------------------------------------------------------------------
# Pytest markers registered
# ---------------------------------------------------------------------------


class TestMarkersRegistered:
    EXPECTED_MARKERS = [
        "integration",
        "live",
        "qmt",
        "network",
        "data_quality",
        "api",
        "redis",
        "celery",
        "websocket",
        "streamlit",
        "pdf",
        "runtime",
        "slow",
    ]

    def test_pyproject_has_all_markers(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for marker in self.EXPECTED_MARKERS:
            assert f'"{marker}:' in pyproject or f"'{marker}:" in pyproject, (
                f"Marker '{marker}' not found in pyproject.toml markers"
            )


# ---------------------------------------------------------------------------
# Artifact schema validation
# ---------------------------------------------------------------------------


class TestArtifactSchema:
    """Validate the structure of verification artifact JSON."""

    def _make_minimal_report(self) -> dict:
        return {
            "run_id": "test123",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "overall_status": "pass",
            "strict": False,
            "checks": [
                {
                    "name": "test_check",
                    "category": "env",
                    "status": "pass",
                    "severity": "blocker",
                    "message": "ok",
                    "details": {},
                }
            ],
            "summary": {"pass": 1, "warning": 0, "fail": 0, "skipped": 0},
            "environment": {
                "python_version": "3.13.0",
                "platform": "test",
                "project_root": "/tmp",
                "executable": "/tmp/python",
            },
        }

    def test_schema_has_required_top_level_keys(self):
        report = self._make_minimal_report()
        required = {"run_id", "generated_at", "overall_status", "strict", "checks", "summary", "environment"}
        assert required == set(report.keys())

    def test_overall_status_values(self):
        for status in ("pass", "warning", "fail"):
            report = self._make_minimal_report()
            report["overall_status"] = status
            assert report["overall_status"] in ("pass", "warning", "fail")

    def test_check_has_required_fields(self):
        check = self._make_minimal_report()["checks"][0]
        required = {"name", "category", "status", "severity", "message", "details"}
        assert required == set(check.keys())

    def test_check_status_values(self):
        for status in ("pass", "fail", "warning", "skipped"):
            check = self._make_minimal_report()["checks"][0]
            check["status"] = status
            assert check["status"] in ("pass", "fail", "warning", "skipped")

    def test_check_severity_values(self):
        for severity in ("blocker", "warning", "watch"):
            check = self._make_minimal_report()["checks"][0]
            check["severity"] = severity
            assert check["severity"] in ("blocker", "warning", "watch")

    def test_summary_counts_match_checks(self):
        report = self._make_minimal_report()
        assert sum(report["summary"].values()) == len(report["checks"])


# ---------------------------------------------------------------------------
# Python runner importability
# ---------------------------------------------------------------------------


class TestRunnerImportable:
    def test_runner_can_be_imported(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            import scripts.run_runtime_verification as mod  # noqa: F401
        finally:
            sys.path.pop(0)

    def test_runner_has_main(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            from scripts.run_runtime_verification import main  # noqa: F401
        finally:
            sys.path.pop(0)

    def test_runner_has_run_verification(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            from scripts.run_runtime_verification import run_verification  # noqa: F401
        finally:
            sys.path.pop(0)


class TestRuntimeSemantics:
    def test_fastapi_partial_health_is_blocker_failure(self, monkeypatch):
        """A 200 response with unhealthy internals must fail the blocker check."""
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            import scripts.run_runtime_verification as mod

            monkeypatch.setattr(mod, "_tcp_port_open", lambda *_args, **_kwargs: True)
            monkeypatch.setattr(
                mod,
                "_http_get",
                lambda *_args, **_kwargs: (
                    200,
                    json.dumps({
                        "api": {"status": "ok"},
                        "db": {"status": "error"},
                        "redis": {"status": "ok"},
                    }),
                ),
            )

            result = mod.check_fastapi_health()
        finally:
            sys.path.pop(0)

        assert result.status == "fail"
        assert result.severity == "blocker"


# ---------------------------------------------------------------------------
# Integration test files exist
# ---------------------------------------------------------------------------


class TestSmokeTestFilesExist:
    EXPECTED_FILES = [
        "test_runtime_matrix_contract.py",
        "test_api_runtime_smoke.py",
        "test_redis_celery_runtime_smoke.py",
        "test_websocket_runtime_smoke.py",
        "test_streamlit_runtime_smoke.py",
        "test_qmt_runtime_smoke.py",
    ]

    def test_all_smoke_test_files_exist(self):
        for name in self.EXPECTED_FILES:
            assert (INTEGRATION / name).is_file(), f"Missing integration test: {name}"


# ---------------------------------------------------------------------------
# Environment variable gates
# ---------------------------------------------------------------------------


class TestEnvVarGates:
    """Verify that smoke tests respect environment variable gating."""

    def test_conftest_has_env_gate_helpers(self):
        conftest = (INTEGRATION / "conftest.py").read_text(encoding="utf-8")
        assert "RUN_LIVE_INTEGRATION" in conftest
        assert "RUN_QMT_INTEGRATION" in conftest
