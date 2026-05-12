"""Live FastAPI research flow tests.

These tests require Redis, FastAPI, and a Celery worker started locally.
They are skipped unless RUN_LIVE_INTEGRATION=1 is set.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.live]


def test_health_and_auth_boundaries(
    require_live_integration: None,
    api_base_url: str,
    api_session: requests.Session,
    auth_headers: dict[str, str],
):
    health = api_session.get(f"{api_base_url}/api/v1/health", timeout=10)
    assert health.status_code == 200
    checks = health.json()
    assert checks["api"]["status"] == "ok"
    assert checks["db"]["status"] == "ok"
    assert checks["redis"]["status"] == "ok"

    unauthorized = api_session.get(f"{api_base_url}/api/v1/research/history", timeout=10)
    assert unauthorized.status_code == 401

    authorized = api_session.get(
        f"{api_base_url}/api/v1/research/history",
        headers=auth_headers,
        timeout=10,
    )
    assert authorized.status_code == 200
    assert "tasks" in authorized.json()


def test_mock_research_task_generates_result_and_reports(
    require_live_integration: None,
    api_base_url: str,
    api_session: requests.Session,
    auth_headers: dict[str, str],
    submit_mock_research: Callable[..., str],
    poll_task: Callable[[str, float], dict[str, Any]],
):
    task_id = submit_mock_research(use_graph=True)

    status = poll_task(task_id, timeout_seconds=120)
    assert status["status"] == "completed", status
    assert status["score"] is not None
    assert status["rating"]
    assert status["action"]

    result_response = api_session.get(
        f"{api_base_url}/api/v1/research/{task_id}/result",
        headers=auth_headers,
        timeout=10,
    )
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["symbol"] == "600519.SH"
    assert result["data_source"] == "mock"
    assert result["analysis_mode"] == "template_no_llm"
    assert result["decision_guard"]["enabled"] is True

    report_response = api_session.get(
        f"{api_base_url}/api/v1/reports/{task_id}/info",
        headers=auth_headers,
        timeout=10,
    )
    assert report_response.status_code == 200
    report_info = report_response.json()
    assert {"json", "markdown", "html"}.issubset(set(report_info["formats"]))

