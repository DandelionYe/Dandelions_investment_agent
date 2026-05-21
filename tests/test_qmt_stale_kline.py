"""QMT stale K-line detection and forced re-download tests.

All tests monkeypatch xtdata so no real QMT environment is needed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from services.data import qmt_provider as qmt_mod
from services.data.provider_contracts import ProviderUnavailableError
from services.data.qmt_provider import (
    QMTSettings,
    _extract_latest_trade_date,
    _is_qmt_history_stale,
    _load_qmt_daily_history,
    _parse_timestamp_like,
    get_qmt_asset_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daily_df(
    dates: list[str],
    closes: list[float],
    *,
    use_time_col: bool = False,
    time_format: str = "YYYYMMDD",
) -> pd.DataFrame:
    """Build a minimal QMT-style daily DataFrame."""
    df = pd.DataFrame({"close": closes, "amount": [1e9] * len(closes)}, index=dates)
    df.index.name = None

    if use_time_col:
        if time_format == "ms":
            df["time"] = [
                int(pd.Timestamp(d).timestamp() * 1000) for d in dates
            ]
        elif time_format == "YYYYMMDD":
            df["time"] = [d.replace("-", "") for d in dates]
        else:
            df["time"] = dates

    return df


def _fake_xtdata(
    query_results: list[pd.DataFrame],
    *,
    download_called: list[bool] | None = None,
):
    """Return a fake xtdata module whose get_market_data_ex cycles through *query_results*."""
    call_idx = {"n": 0}

    class _Fake:
        enable_hello = True

        def connect(self):
            return True

        def get_data_dir(self):
            return "/fake/dir"

        def get_market_data_ex(self, **kwargs):
            idx = min(call_idx["n"], len(query_results) - 1)
            call_idx["n"] += 1
            return {"600519.SH": query_results[idx]}

        def download_history_data(self, symbol, period, start, end):
            if download_called is not None:
                download_called.append(True)
            return True

    return _Fake()


def _patch_xtdata(monkeypatch, fake_xtdata):
    monkeypatch.setattr(qmt_mod, "_import_xtdata", lambda: fake_xtdata)


# ---------------------------------------------------------------------------
# _parse_timestamp_like
# ---------------------------------------------------------------------------

class TestParseTimestampLike:
    def test_millisecond_timestamp(self):
        # 2026-05-19 00:00:00 UTC ≈ 1779235200000 ms
        ts = int(pd.Timestamp("2026-05-19").timestamp() * 1000)
        assert _parse_timestamp_like(ts) == date(2026, 5, 19)

    def test_second_timestamp(self):
        ts = int(pd.Timestamp("2026-05-19").timestamp())
        assert _parse_timestamp_like(ts) == date(2026, 5, 19)

    def test_yyyymmdd_int(self):
        assert _parse_timestamp_like(20260519) == date(2026, 5, 19)

    def test_yyyymmdd_str(self):
        assert _parse_timestamp_like("20260519") == date(2026, 5, 19)

    def test_yyyy_mm_dd_str(self):
        assert _parse_timestamp_like("2026-05-19") == date(2026, 5, 19)

    def test_pandas_timestamp(self):
        assert _parse_timestamp_like(pd.Timestamp("2026-05-19")) == date(2026, 5, 19)

    def test_none_returns_none(self):
        assert _parse_timestamp_like(None) is None

    def test_unparseable_returns_none(self):
        assert _parse_timestamp_like("not-a-date") is None


# ---------------------------------------------------------------------------
# _extract_latest_trade_date
# ---------------------------------------------------------------------------

class TestExtractLatestTradeDate:
    def test_from_time_col_milliseconds(self):
        dates = ["2026-05-15", "2026-05-16", "2026-05-19"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes, use_time_col=True, time_format="ms")
        assert _extract_latest_trade_date(df) == date(2026, 5, 19)

    def test_from_index_yyyymmdd(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        assert _extract_latest_trade_date(df) == date(2026, 5, 19)

    def test_skips_nan_close_rows(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, float("nan")]
        df = _make_daily_df(dates, closes)
        # Last valid close is at index 20260516
        assert _extract_latest_trade_date(df) == date(2026, 5, 16)

    def test_all_close_nan_returns_none(self):
        dates = ["20260515", "20260516"]
        closes = [float("nan"), float("nan")]
        df = _make_daily_df(dates, closes)
        assert _extract_latest_trade_date(df) is None

    def test_empty_df_returns_none(self):
        assert _extract_latest_trade_date(pd.DataFrame()) is None

    def test_none_df_returns_none(self):
        assert _extract_latest_trade_date(None) is None


# ---------------------------------------------------------------------------
# _is_qmt_history_stale
# ---------------------------------------------------------------------------

class TestIsQmtHistoryStale:
    def test_not_stale(self):
        today = date(2026, 5, 21)
        assert _is_qmt_history_stale(date(2026, 5, 20), today, 3) is False

    def test_stale(self):
        today = date(2026, 5, 21)
        assert _is_qmt_history_stale(date(2026, 5, 15), today, 3) is True

    def test_none_is_stale(self):
        assert _is_qmt_history_stale(None, date(2026, 5, 21), 3) is True

    def test_exactly_at_threshold_not_stale(self):
        today = date(2026, 5, 21)
        # 2026-05-18 → 3 days diff → NOT stale (threshold is > 3)
        assert _is_qmt_history_stale(date(2026, 5, 18), today, 3) is False

    def test_one_past_threshold_is_stale(self):
        today = date(2026, 5, 21)
        # 2026-05-17 → 4 days diff → stale
        assert _is_qmt_history_stale(date(2026, 5, 17), today, 3) is True


# ---------------------------------------------------------------------------
# _load_qmt_daily_history integration
# ---------------------------------------------------------------------------

def _settings(**overrides) -> QMTSettings:
    defaults = dict(
        period="1d",
        history_days=1500,
        auto_download=True,
        dividend_type="front",
        suppress_hello=True,
        max_stale_days=3,
        stale_refresh_days=90,
    )
    defaults.update(overrides)
    return QMTSettings(**defaults)


class TestLoadQmtDailyHistory:
    """Integration-level tests for _load_qmt_daily_history with monkeypatched xtdata."""

    def test_fresh_data_no_download(self, monkeypatch):
        """df non-empty and latest date not stale → no download triggered."""
        today = date.today()
        recent = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(recent, closes)

        download_flag: list[bool] = []
        fake = _fake_xtdata([df], download_called=download_flag)
        _patch_xtdata(monkeypatch, fake)

        result_df, status = _load_qmt_daily_history("600519.SH", _settings())

        assert len(result_df) == 100
        assert status["download_attempted"] is False
        assert status["download_reason"] is None
        assert status["price_stale_before_download"] is False
        assert download_flag == []

    def test_stale_triggers_download(self, monkeypatch):
        """df non-empty but stale → download triggered, df refreshed."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        stale_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        stale_closes = [100.0 + i * 0.1 for i in range(99)]
        stale_df = _make_daily_df(stale_dates, stale_closes)

        fresh_dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        fresh_closes = [200.0 + i * 0.1 for i in range(100)]
        fresh_df = _make_daily_df(fresh_dates, fresh_closes)

        download_flag: list[bool] = []
        fake = _fake_xtdata([stale_df, fresh_df], download_called=download_flag)
        _patch_xtdata(monkeypatch, fake)

        result_df, status = _load_qmt_daily_history("600519.SH", _settings())

        assert download_flag == [True]
        assert status["download_attempted"] is True
        assert status["download_reason"] == "stale"
        assert status["price_stale_before_download"] is True
        assert status["price_stale_after_download"] is False
        # Result should be the fresh df (close ≈ 200)
        assert result_df["close"].iloc[-1] == pytest.approx(200.0 + 99 * 0.1)

    def test_stale_after_download_no_exception(self, monkeypatch):
        """Stale before and after download → no exception, status recorded."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        stale_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        stale_closes = [100.0 + i * 0.1 for i in range(99)]
        stale_df = _make_daily_df(stale_dates, stale_closes)

        # Second query also returns stale data
        fake = _fake_xtdata([stale_df, stale_df])
        _patch_xtdata(monkeypatch, fake)

        result_df, status = _load_qmt_daily_history("600519.SH", _settings())

        assert status["download_attempted"] is True
        assert status["price_stale_after_download"] is True
        assert len(result_df) == 99

    def test_empty_df_auto_download(self, monkeypatch):
        """df empty + auto_download=true → download, then re-query succeeds."""
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        filled_df = _make_daily_df(dates, closes)

        fake = _fake_xtdata([pd.DataFrame(), filled_df])
        _patch_xtdata(monkeypatch, fake)

        result_df, status = _load_qmt_daily_history("600519.SH", _settings())

        assert status["download_attempted"] is True
        assert status["download_reason"] == "empty"
        assert len(result_df) == 100

    def test_empty_df_no_auto_download_raises(self, monkeypatch):
        """df empty + auto_download=false → ProviderUnavailableError."""
        fake = _fake_xtdata([pd.DataFrame()])
        _patch_xtdata(monkeypatch, fake)

        with pytest.raises(ProviderUnavailableError):
            _load_qmt_daily_history("600519.SH", _settings(auto_download=False))


# ---------------------------------------------------------------------------
# price_data fields from get_qmt_asset_data
# ---------------------------------------------------------------------------

class TestGetQmtAssetDataStaleFields:
    """Verify stale info propagates into price_data, data_warnings, run_log."""

    def test_fresh_price_data_fields(self, monkeypatch):
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata([df])
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")

        assert result["price_data"]["latest_trade_date"] is not None
        assert result["price_data"]["price_is_stale"] is False
        assert result["data_warnings"] == []
        log = result["provider_run_log"][0]
        assert log["price_stale"] is False
        assert log["download_attempted"] is False

    def test_stale_price_data_warning(self, monkeypatch):
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(99)]
        stale_df = _make_daily_df(dates, closes)

        # Download returns same stale data
        fake = _fake_xtdata([stale_df, stale_df])
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")

        assert result["price_data"]["price_is_stale"] is True
        assert any("可能过期" in warning for warning in result["data_warnings"])

    def test_build_price_uses_refreshed_df(self, monkeypatch):
        """MA/涨跌幅 must come from the post-download df, not the stale one."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        stale_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        stale_closes = [100.0] * 99
        stale_df = _make_daily_df(stale_dates, stale_closes)

        fresh_dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        fresh_closes = [200.0] * 100
        fresh_df = _make_daily_df(fresh_dates, fresh_closes)

        fake = _fake_xtdata([stale_df, fresh_df])
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")

        # close should be 200.0 from fresh df, not 100.0 from stale df
        assert result["price_data"]["close"] == pytest.approx(200.0)
        assert result["price_data"]["ma20_position"] in ("above", "below")
        # change_20d should be ~0 since all closes are 200
        assert abs(result["price_data"]["change_20d"]) < 0.01


# ---------------------------------------------------------------------------
# qmt_status fields completeness
# ---------------------------------------------------------------------------

class TestQmtStatusFields:
    def test_all_required_fields_present(self, monkeypatch):
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata([df])
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        required_keys = [
            "connected", "auto_download", "history_start", "history_end",
            "period", "data_dir", "row_count",
            "latest_trade_date", "latest_trade_date_before_download",
            "latest_trade_date_after_download",
            "price_stale_before_download", "price_stale_after_download",
            "price_max_stale_days", "stale_refresh_days",
            "download_reason", "download_attempted", "download_success",
        ]
        for key in required_keys:
            assert key in qs, f"qmt_status missing key: {key}"
