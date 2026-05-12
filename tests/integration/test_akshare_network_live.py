"""External-network AKShare/CNInfo integration smoke tests.

These tests are skipped unless RUN_AKSHARE_NETWORK=1 is set.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.network]


def test_akshare_stock_smoke_fetches_price_data(
    require_akshare_network: None,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MARKET_DATA_DISABLE_PROXY", "true")

    from services.data.akshare_provider import get_akshare_asset_data

    asset_data = get_akshare_asset_data("600519.SH")

    assert asset_data["data_source"] == "akshare"
    assert asset_data["symbol"] == "600519.SH"
    assert asset_data["price_data"]["close"] > 0
    assert asset_data["source_metadata"]["price_data"]["source"] == "akshare"
    assert any(log["dataset"] == "price_data" for log in asset_data["provider_run_log"])

