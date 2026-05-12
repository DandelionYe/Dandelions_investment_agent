"""Live WebSocket progress integration tests.

These tests require Redis, FastAPI, and a Celery worker started locally. They
are skipped unless RUN_LIVE_INTEGRATION=1 is set.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
import websockets

pytestmark = [pytest.mark.integration, pytest.mark.live]


def test_task_websocket_receives_terminal_progress(
    require_live_integration: None,
    api_base_url: str,
    auth_headers: dict[str, str],
    submit_mock_research: Callable[..., str],
):
    task_id = submit_mock_research(use_graph=True)
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    ws_base = api_base_url.replace("http://", "ws://").replace("https://", "wss://")

    async def _collect() -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        uri = f"{ws_base}/ws/task/{task_id}?token={token}"
        async with websockets.connect(uri, open_timeout=10) as websocket:
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=120)
                message = json.loads(raw)
                messages.append(message)
                if message.get("status") in {"completed", "failed", "cancelled"}:
                    return messages

    received = asyncio.run(_collect())
    terminal = received[-1]

    assert terminal["task_id"] == task_id
    assert terminal["status"] == "completed", received
    assert terminal["type"] == "completed"
    assert terminal["progress"] == 1.0
    assert terminal["score"] is not None
    assert terminal["rating"]
    assert terminal["action"]

