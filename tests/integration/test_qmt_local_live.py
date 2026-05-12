"""Local QMT integration smoke tests.

These tests require XtMiniQMT/xtquant running locally. They are skipped unless
RUN_QMT_INTEGRATION=1 is set.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.qmt]


def test_qmt_can_connect_and_load_minimal_asset_data(
    require_qmt_integration: None,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("QMT_HISTORY_DAYS", "120")
    monkeypatch.setenv("QMT_AUTO_DOWNLOAD", "false")
    monkeypatch.setenv("QMT_FINANCIAL_AUTO_DOWNLOAD", "false")
    monkeypatch.setenv("QMT_INDUSTRY_AUTO_DOWNLOAD", "false")
    monkeypatch.setenv("QMT_INDUSTRY_FINANCIAL_AUTO_DOWNLOAD", "false")

    from services.data.qmt_provider import get_qmt_asset_data

    asset_data = get_qmt_asset_data("600519.SH")

    assert asset_data["data_source"] == "qmt"
    assert asset_data["symbol"] == "600519.SH"
    assert asset_data["name"]
    assert asset_data["price_data"]["close"] > 0
    assert asset_data["source_metadata"]["qmt_status"]["connected"] is True
    assert asset_data["source_metadata"]["qmt_status"]["row_count"] >= 60
    assert asset_data["provider_run_log"][0]["status"] == "success"

