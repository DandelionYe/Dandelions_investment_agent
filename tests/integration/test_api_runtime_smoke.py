"""Live API runtime smoke tests.

Requires FastAPI server running locally. Skipped unless RUN_RUNTIME_INTEGRATION=1.
"""

from __future__ import annotations

import os

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.api, pytest.mark.runtime]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def require_runtime_integration():
    if not _env_enabled("RUN_RUNTIME_INTEGRATION"):
        pytest.skip("set RUN_RUNTIME_INTEGRATION=1 to run runtime smoke tests")


@pytest.fixture
def api_base_url() -> str:
    return os.getenv("DANDELIONS_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def test_api_health_returns_ok(api_base_url: str):
    resp = requests.get(f"{api_base_url}/api/v1/health", timeout=10, trust_env=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data["api"]["status"] == "ok"


def test_api_health_redis_ok(api_base_url: str):
    resp = requests.get(f"{api_base_url}/api/v1/health", timeout=10, trust_env=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis"]["status"] == "ok"


def test_api_health_db_ok(api_base_url: str):
    resp = requests.get(f"{api_base_url}/api/v1/health", timeout=10, trust_env=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"]["status"] == "ok"


def test_api_unauthenticated_returns_401(api_base_url: str):
    resp = requests.get(f"{api_base_url}/api/v1/research/history", timeout=10, trust_env=False)
    assert resp.status_code == 401
