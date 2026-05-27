"""Live Streamlit runtime smoke tests.

Requires Streamlit server running locally. Skipped unless RUN_STREAMLIT_INTEGRATION=1.
"""

from __future__ import annotations

import os
import socket

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.streamlit, pytest.mark.runtime]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def require_streamlit_integration():
    if not _env_enabled("RUN_STREAMLIT_INTEGRATION"):
        pytest.skip("set RUN_STREAMLIT_INTEGRATION=1 to run Streamlit smoke tests")


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def test_streamlit_port_reachable():
    port = int(os.getenv("STREAMLIT_PORT", "8501"))
    assert _port_open("127.0.0.1", port), f"Streamlit port {port} not reachable"
