"""Live WebSocket runtime smoke tests.

Requires FastAPI server running locally. Skipped unless RUN_RUNTIME_INTEGRATION=1
and AUTH_ADMIN_PASS is set.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.websocket, pytest.mark.runtime]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def require_runtime_integration():
    if not _env_enabled("RUN_RUNTIME_INTEGRATION"):
        pytest.skip("set RUN_RUNTIME_INTEGRATION=1 to run runtime smoke tests")


@pytest.fixture
def api_base_url() -> str:
    return os.getenv("DANDELIONS_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture
def access_token(api_base_url: str) -> str:
    """Get an access token for WebSocket auth. Skips if no credentials."""
    import requests

    username = os.getenv("AUTH_ADMIN_USER", "admin")
    password = os.getenv("AUTH_ADMIN_PASS")
    if not password:
        pytest.skip("AUTH_ADMIN_PASS is required for WebSocket smoke test")

    session = requests.Session()
    session.trust_env = False
    resp = session.post(
        f"{api_base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Auth login failed (HTTP {resp.status_code})")
    token = resp.json().get("access_token")
    if not token:
        pytest.skip("No access_token in login response")
    return token


def test_websocket_auth_and_route(api_base_url: str, access_token: str):
    """Connect to a task WebSocket with auth token, expect 'task not found' error."""
    websockets = pytest.importorskip("websockets")

    ws_base = api_base_url.replace("http://", "ws://").replace("https://", "wss://")

    async def _try_connect() -> tuple[bool, str]:
        try:
            async with websockets.connect(
                f"{ws_base}/ws/task/runtime_smoke_check?token={access_token}",
                open_timeout=5,
                close_timeout=3,
            ) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(msg)
                if data.get("type") == "error" and "不存在" in data.get("detail", ""):
                    return True, "WebSocket + auth + route verified"
                return False, f"Unexpected response: {msg[:200]}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    ok, detail = asyncio.run(_try_connect())
    if not ok:
        pytest.fail(f"WebSocket smoke failed: {detail}")
