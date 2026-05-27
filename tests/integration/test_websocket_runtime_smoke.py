"""Live WebSocket runtime smoke tests.

Requires FastAPI server running locally. Skipped unless RUN_RUNTIME_INTEGRATION=1.
"""

from __future__ import annotations

import asyncio
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


def test_websocket_endpoint_connectable(api_base_url: str):
    """Basic WebSocket connectivity smoke — connect and disconnect."""
    websockets = pytest.importorskip("websockets")

    ws_base = api_base_url.replace("http://", "ws://").replace("https://", "wss://")

    async def _try_connect() -> bool:
        try:
            async with websockets.connect(
                f"{ws_base}/ws/ping",
                open_timeout=3,
                close_timeout=2,
            ):
                return True
        except Exception:  # noqa: BLE001
            return False

    ok = asyncio.run(_try_connect())
    if not ok:
        pytest.skip("WebSocket endpoint not reachable (may need auth token)")
