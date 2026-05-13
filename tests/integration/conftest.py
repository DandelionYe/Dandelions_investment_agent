"""Shared helpers for opt-in live integration tests."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture
def require_live_integration() -> None:
    if not _env_enabled("RUN_LIVE_INTEGRATION"):
        pytest.skip("set RUN_LIVE_INTEGRATION=1 to run live service integration tests")


@pytest.fixture
def require_qmt_integration() -> None:
    if not _env_enabled("RUN_QMT_INTEGRATION"):
        pytest.skip("set RUN_QMT_INTEGRATION=1 to run local QMT integration tests")


@pytest.fixture
def require_akshare_network() -> None:
    if not _env_enabled("RUN_AKSHARE_NETWORK"):
        pytest.skip("set RUN_AKSHARE_NETWORK=1 to run network data-source tests")


@pytest.fixture
def require_web_news_network() -> None:
    if not _env_enabled("RUN_WEB_NEWS_NETWORK"):
        pytest.skip("set RUN_WEB_NEWS_NETWORK=1 to run web news network tests")


@pytest.fixture
def api_base_url() -> str:
    return os.getenv("DANDELIONS_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture
def api_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


@pytest.fixture
def auth_headers(
    require_live_integration: None,
    api_base_url: str,
    api_session: requests.Session,
) -> dict[str, str]:
    username = os.getenv("AUTH_ADMIN_USER", "admin")
    password = os.getenv("AUTH_ADMIN_PASS")
    if not password:
        pytest.skip("AUTH_ADMIN_PASS is required for live authenticated API tests")

    response = api_session.post(
        f"{api_base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def poll_task(
    api_base_url: str,
    api_session: requests.Session,
    auth_headers: dict[str, str],
) -> Callable[[str, float], dict[str, Any]]:
    def _poll(task_id: str, timeout_seconds: float = 90.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = api_session.get(
                f"{api_base_url}/api/v1/research/{task_id}",
                headers=auth_headers,
                timeout=10,
            )
            response.raise_for_status()
            last_status = response.json()
            if last_status["status"] in {"completed", "failed", "cancelled"}:
                return last_status
            time.sleep(1)

        raise AssertionError(f"task {task_id} did not finish in time; last_status={last_status}")

    return _poll


@pytest.fixture
def submit_mock_research(
    api_base_url: str,
    api_session: requests.Session,
    auth_headers: dict[str, str],
) -> Callable[..., str]:
    def _submit(*, use_graph: bool = True) -> str:
        response = api_session.post(
            f"{api_base_url}/api/v1/research/single",
            json={
                "symbol": "600519.SH",
                "data_source": "mock",
                "use_llm": False,
                "max_debate_rounds": 2,
                "use_graph": use_graph,
            },
            headers=auth_headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["task_id"]
        return payload["task_id"]

    return _submit
