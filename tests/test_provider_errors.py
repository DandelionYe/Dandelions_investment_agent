import sqlite3

import pandas as pd
import pytest

from services.data.cache.sqlite_cache import ResearchDataCache
from services.data.provider_contracts import (
    ProviderSchemaError,
    ProviderUnavailableError,
)
from services.data.providers.qmt_financial_provider import QMTFinancialProvider
from services.data.qmt_provider import get_qmt_asset_data
from services.orchestrator.single_asset_research import _load_asset_data


class _PassthroughAggregator:
    def enrich(self, asset_data: dict) -> dict:
        return asset_data


def _minimal_akshare_asset(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "asset_type": "stock",
        "name": symbol,
        "as_of": "2026-05-11",
        "data_source": "akshare",
        "price_data": {"close": 100.0},
        "source_metadata": {},
        "provider_run_log": [
            {
                "provider": "akshare",
                "dataset": "price_data",
                "symbol": symbol,
                "status": "success",
                "rows": 1,
                "error": None,
                "error_type": None,
                "as_of": "2026-05-11",
            }
        ],
    }


def test_qmt_unavailable_falls_back_to_akshare_with_error_type(monkeypatch):
    def raise_unavailable(symbol: str) -> dict:
        raise ProviderUnavailableError("qmt is offline")

    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.get_qmt_asset_data",
        raise_unavailable,
    )
    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.get_akshare_asset_data",
        _minimal_akshare_asset,
    )
    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.ResearchDataAggregator",
        _PassthroughAggregator,
    )

    asset_data = _load_asset_data("600519.SH", "qmt")

    assert asset_data["data_source"] == "akshare"
    assert asset_data["data_source_chain"] == ["qmt_failed", "akshare_fallback"]
    assert asset_data["provider_run_log"][0]["provider"] == "qmt"
    assert asset_data["provider_run_log"][0]["status"] == "failed"
    assert asset_data["provider_run_log"][0]["error_type"] == "provider_unavailable"
    assert asset_data["provider_run_log"][1]["provider"] == "akshare"


def test_qmt_schema_error_does_not_fall_back_to_akshare(monkeypatch):
    def raise_schema_error(symbol: str) -> dict:
        raise ProviderSchemaError("missing close field")

    def fail_if_called(symbol: str) -> dict:
        raise AssertionError("AKShare fallback should not be called for schema errors")

    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.get_qmt_asset_data",
        raise_schema_error,
    )
    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.get_akshare_asset_data",
        fail_if_called,
    )

    with pytest.raises(ProviderSchemaError):
        _load_asset_data("600519.SH", "qmt")


def test_qmt_empty_daily_history_is_provider_unavailable(monkeypatch):
    class FakeXtData:
        def __init__(self):
            self.download_called = False

        def connect(self):
            return object()

        def get_data_dir(self):
            return "fake-qmt-datadir"

        def get_market_data_ex(self, **kwargs):
            return {"600519.SH": pd.DataFrame()}

        def download_history_data(self, stock_code, period, start_time="", end_time=""):
            self.download_called = True
            return True

    fake_xtdata = FakeXtData()

    monkeypatch.setattr(
        "services.data.qmt_provider._import_xtdata",
        lambda: fake_xtdata,
    )
    monkeypatch.setenv("QMT_AUTO_DOWNLOAD", "true")

    with pytest.raises(ProviderUnavailableError):
        get_qmt_asset_data("600519.SH")

    assert fake_xtdata.download_called is True


def test_qmt_missing_close_field_is_provider_schema_error(monkeypatch):
    history_df = pd.DataFrame(
        {
            "time": [1, 2],
            "amount": [1000.0, 2000.0],
            "volume": [10.0, 20.0],
        }
    )

    monkeypatch.setattr(
        "services.data.qmt_provider._load_qmt_daily_history",
        lambda symbol, settings: (history_df, {"row_count": len(history_df)}),
    )
    monkeypatch.setattr(
        "services.data.qmt_provider._load_qmt_instrument_detail",
        lambda symbol: {},
    )

    with pytest.raises(ProviderSchemaError):
        get_qmt_asset_data("600519.SH")


def test_qmt_financial_unavailable_result_includes_error_type(monkeypatch):
    def raise_unavailable():
        raise ProviderUnavailableError("xtquant missing")

    monkeypatch.setattr(
        "services.data.providers.qmt_financial_provider._import_xtdata",
        raise_unavailable,
    )

    result = QMTFinancialProvider().fetch_fundamental({"qmt_code": "600519.SH"})

    assert result.metadata.success is False
    assert result.metadata.error_type == "provider_unavailable"


def test_provider_run_log_cache_keeps_error_type():
    conn = sqlite3.connect(":memory:")
    cache = ResearchDataCache()
    cache._init_schema(conn)
    cache._insert_provider_logs(
        conn,
        "run-1",
        {
            "symbol": "600519.SH",
            "provider_run_log": [
                {
                    "provider": "qmt",
                    "dataset": "price_data",
                    "status": "failed",
                    "error": "offline",
                    "error_type": "provider_unavailable",
                    "rows": 0,
                    "as_of": "2026-05-11",
                }
            ],
        },
    )

    row = conn.execute(
        "select error_type from provider_run_log where run_id = ?",
        ("run-1",),
    ).fetchone()

    assert row == ("provider_unavailable",)
