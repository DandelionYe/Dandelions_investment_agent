"""Live MiniQMT runtime smoke tests.

Requires MiniQMT running locally. Skipped unless RUN_QMT_INTEGRATION=1.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.qmt, pytest.mark.runtime]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def require_qmt_integration():
    if not _env_enabled("RUN_QMT_INTEGRATION"):
        pytest.skip("set RUN_QMT_INTEGRATION=1 to run QMT smoke tests")


def test_xtquant_importable():
    pytest.importorskip("xtquant")


def test_xtdata_connect():
    from xtquant import xtdata  # noqa: PLC0415

    xtdata.connect()
