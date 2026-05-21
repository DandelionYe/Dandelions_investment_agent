"""QMT full tick overlay tests (layer 2 price fix).

All tests monkeypatch xtdata so no real QMT environment is needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

from services.data import qmt_provider as qmt_mod
from services.data.qmt_provider import (
    QMTSettings,
    _apply_intraday_tick_bar,
    _parse_tick_trade_date,
    _query_qmt_full_tick,
    get_qmt_asset_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_daily_df(
    dates: list[str],
    closes: list[float],
    amounts: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    """Build a minimal QMT-style daily DataFrame."""
    n = len(dates)
    if amounts is None:
        amounts = [1e9] * n
    if volumes is None:
        volumes = [1e6] * n
    df = pd.DataFrame(
        {"close": closes, "amount": amounts, "volume": volumes},
        index=dates,
    )
    df.index.name = None
    return df


def _make_tick(
    last_price: float = 14.00,
    prev_close: float = 13.47,
    amount: float = 5e8,
    volume: float = 3e6,
    timetag: str | None = "20260522 15:00:00",
    time_val: Any = None,
    stock_status: int = 0,
) -> dict:
    """Build a fake tick dict as returned by _query_qmt_full_tick."""
    tick_trade_date = _parse_tick_trade_date(timetag, time_val)
    return {
        "last_price": last_price if last_price > 0 else None,
        "prev_close": prev_close if prev_close and prev_close > 0 else None,
        "amount": amount if amount and amount > 0 else None,
        "volume": volume if volume and volume > 0 else None,
        "tick_time": time_val,
        "tick_time_tag": str(timetag) if timetag is not None else None,
        "tick_trade_date": tick_trade_date,
        "stock_status": stock_status,
        "source": "qmt_full_tick",
    }


def _fake_xtdata_kline(
    df: pd.DataFrame,
    *,
    download_called: list[bool] | None = None,
    tick_data: dict | None = None,
):
    """Return a fake xtdata with kline + optional tick."""

    class _Fake:
        enable_hello = True

        def connect(self):
            return True

        def get_data_dir(self):
            return "/fake/dir"

        def get_market_data_ex(self, **kwargs):
            return {"600519.SH": df}

        def download_history_data(self, symbol, period, start, end):
            if download_called is not None:
                download_called.append(True)
            return True

        def get_full_tick(self, symbols):
            if tick_data is None:
                return {}
            return tick_data

    return _Fake()


def _patch_xtdata(monkeypatch, fake):
    monkeypatch.setattr(qmt_mod, "_import_xtdata", lambda: fake)


def _settings(**overrides) -> QMTSettings:
    defaults = dict(
        period="1d",
        history_days=1500,
        auto_download=True,
        dividend_type="front",
        suppress_hello=True,
        max_stale_days=3,
        stale_refresh_days=90,
        use_full_tick_for_stale=True,
    )
    defaults.update(overrides)
    return QMTSettings(**defaults)


# ---------------------------------------------------------------------------
# _parse_tick_trade_date
# ---------------------------------------------------------------------------


class TestParseTickTradeDate:
    def test_timetag_yyyymmdd(self):
        assert _parse_tick_trade_date("20260522 15:00:00", None) == date(2026, 5, 22)

    def test_timetag_yyyy_mm_dd(self):
        assert _parse_tick_trade_date("2026-05-22 15:00:00", None) == date(2026, 5, 22)

    def test_time_ms_fallback(self):
        ts_ms = int(pd.Timestamp("2026-05-22").timestamp() * 1000)
        assert _parse_tick_trade_date(None, ts_ms) == date(2026, 5, 22)

    def test_both_none(self):
        assert _parse_tick_trade_date(None, None) is None

    def test_unparseable_timetag(self):
        assert _parse_tick_trade_date("not-a-date", None) is None


# ---------------------------------------------------------------------------
# _query_qmt_full_tick
# ---------------------------------------------------------------------------


class TestQueryQmtFullTick:
    def test_valid_tick(self, monkeypatch):
        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.0,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "time": 1779436800000,
                "timetag": "20260522 15:00:00",
                "stockStatus": 0,
            }
        }

        class _Fake:
            enable_hello = True
            def get_full_tick(self, symbols):
                return tick_raw

        monkeypatch.setattr(qmt_mod, "_import_xtdata", lambda: _Fake())
        result = _query_qmt_full_tick("600519.SH")

        assert result is not None
        assert result["last_price"] == 14.0
        assert result["tick_trade_date"] == date(2026, 5, 22)
        assert result["source"] == "qmt_full_tick"

    def test_missing_symbol(self, monkeypatch):
        class _Fake:
            enable_hello = True
            def get_full_tick(self, symbols):
                return {}

        monkeypatch.setattr(qmt_mod, "_import_xtdata", lambda: _Fake())
        assert _query_qmt_full_tick("600519.SH") is None

    def test_zero_price(self, monkeypatch):
        tick_raw = {
            "600519.SH": {
                "lastPrice": 0,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": "20260522 15:00:00",
            }
        }

        class _Fake:
            enable_hello = True
            def get_full_tick(self, symbols):
                return tick_raw

        monkeypatch.setattr(qmt_mod, "_import_xtdata", lambda: _Fake())
        result = _query_qmt_full_tick("600519.SH")
        assert result is not None
        assert result["last_price"] is None


# ---------------------------------------------------------------------------
# _apply_intraday_tick_bar
# ---------------------------------------------------------------------------


class TestApplyIntradayTickBar:
    def test_append_new_day(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=14.00, timetag="20260522 15:00:00")

        new_df, reason = _apply_intraday_tick_bar(
            df, tick, date(2026, 5, 19),
        )

        assert reason is None
        assert len(new_df) == 4
        assert float(new_df["close"].iloc[-1]) == pytest.approx(14.00)

    def test_update_same_day(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=14.00, timetag="20260519 15:00:00")

        new_df, reason = _apply_intraday_tick_bar(
            df, tick, date(2026, 5, 19),
        )

        assert reason is None
        assert len(new_df) == 3  # no new row appended
        assert float(new_df["close"].iloc[-1]) == pytest.approx(14.00)

    def test_tick_earlier_than_kline(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=14.00, timetag="20260514 15:00:00")

        new_df, reason = _apply_intraday_tick_bar(
            df, tick, date(2026, 5, 19),
        )

        assert reason == "tick_date_earlier_than_kline"
        assert len(new_df) == 3  # unchanged

    def test_tick_price_zero(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=0, timetag="20260522 15:00:00")

        new_df, reason = _apply_intraday_tick_bar(
            df, tick, date(2026, 5, 19),
        )

        assert reason == "tick_last_price_invalid"

    def test_tick_date_unparseable(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=14.00, timetag=None, time_val=None)
        # Force tick_trade_date to None
        tick["tick_trade_date"] = None

        new_df, reason = _apply_intraday_tick_bar(
            df, tick, date(2026, 5, 19),
        )

        assert reason == "tick_date_unparseable"

    def test_kline_latest_date_unknown(self):
        dates = ["20260515", "20260516", "20260519"]
        closes = [100.0, 101.0, 102.0]
        df = _make_daily_df(dates, closes)
        tick = _make_tick(last_price=14.00, timetag="20260522 15:00:00")

        new_df, reason = _apply_intraday_tick_bar(df, tick, None)

        assert reason == "kline_latest_date_unknown"


# ---------------------------------------------------------------------------
# Full integration: get_qmt_asset_data with tick overlay
# ---------------------------------------------------------------------------


class TestGetQmtAssetDataTickOverlay:
    """End-to-end tests for tick overlay through get_qmt_asset_data."""

    def test_fresh_kline_no_tick_needed(self, monkeypatch):
        """K-line fresh → tick not attempted, price_source=qmt_kline."""
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata_kline(df, tick_data=None)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_attempted"] is False
        assert qs["price_source"] == "qmt_kline"
        assert result["price_data"]["price_is_stale"] is False
        assert result["price_data"]["price_uses_intraday_tick"] is False
        assert result["price_data"]["latest_price_source"] == "qmt_kline"

    def test_stale_kline_tick_appends_bar(self, monkeypatch):
        """K-line stale, tick date later → append bar, all indicators recomputed."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99  # flat at 13.47
        df = _make_daily_df(dates, closes)

        tick_date_str = today.strftime("%Y%m%d") + " 15:00:00"
        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": tick_date_str,
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]
        qs = result["source_metadata"]["qmt_status"]

        # Tick applied
        assert qs["full_tick_applied"] is True
        assert qs["price_source"] == "qmt_kline+full_tick"
        assert pd_["price_uses_intraday_tick"] is True
        assert pd_["latest_price_source"] == "qmt_full_tick_overlay"
        assert pd_["price_is_stale"] is False

        # close is from tick, not old kline
        assert pd_["close"] == pytest.approx(14.00)
        # history_close last value is from tick
        assert pd_["history_close"][-1] == pytest.approx(14.00)

        # change_20d should be ~0 since all closes were 13.47 and last is 14.00
        # (close[-1] / close[-21] - 1) = 14.00 / 13.47 - 1 ≈ 0.0393
        assert pd_["change_20d"] == pytest.approx(14.0 / 13.47 - 1, abs=0.001)

        # All closes except last are 13.47 → ma20 < 14.00 → above
        assert pd_["ma20_position"] == "above"

    def test_stale_kline_tick_updates_same_day(self, monkeypatch):
        """K-line stale, tick date equals kline latest → update same row."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        # Include stale_date itself as the last kline bar
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(98, -1, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_date_str = stale_date.strftime("%Y%m%d") + " 15:00:00"
        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": tick_date_str,
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_applied"] is True
        # Row count unchanged (update, not append)
        assert qs["row_count"] == 99
        assert pd_["close"] == pytest.approx(14.00)
        assert pd_["history_close"][-1] == pytest.approx(14.00)
        # Updating an old same-day bar does not make stale data fresh.
        assert pd_["price_is_stale"] is True
        assert any("可能过期" in warning for warning in result["data_warnings"])

    def test_tick_invalid_price_no_overlay(self, monkeypatch):
        """Tick lastPrice=0 → not applied, stale warning preserved."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_raw = {
            "600519.SH": {
                "lastPrice": 0,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": today.strftime("%Y%m%d") + " 15:00:00",
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_applied"] is False
        assert pd_["price_is_stale"] is True
        assert pd_["latest_price_source"] == "qmt_kline"
        assert any("过期" in w for w in result["data_warnings"])

    def test_tick_unparseable_date_no_overlay(self, monkeypatch):
        """Tick with no parseable date → not applied, warning recorded."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": None,
                "time": None,
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_applied"] is False
        assert qs["full_tick_reason"] == "tick_date_unparseable"
        assert any("tick" in w.lower() for w in result["data_warnings"])

    def test_use_full_tick_disabled(self, monkeypatch):
        """Config disables tick → no tick attempt even if stale."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": today.strftime("%Y%m%d") + " 15:00:00",
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        # Patch load_qmt_settings to return use_full_tick_for_stale=False
        monkeypatch.setattr(
            qmt_mod, "load_qmt_settings",
            lambda: _settings(use_full_tick_for_stale=False),
        )

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_attempted"] is False
        assert result["price_data"]["price_is_stale"] is True
        assert result["price_data"]["latest_price_source"] == "qmt_kline"

    def test_tick_earlier_than_kline_no_overlay(self, monkeypatch):
        """Tick date earlier than kline latest → not applied."""
        today = date.today()
        # K-line is stale but has data up to stale_date
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        # Tick is from even earlier
        earlier = stale_date - timedelta(days=2)
        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": earlier.strftime("%Y%m%d") + " 15:00:00",
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_applied"] is False
        assert qs["full_tick_reason"] == "tick_date_earlier_than_kline"

    def test_tick_query_failure_no_overlay(self, monkeypatch):
        """get_full_tick returns None → not applied, success=False."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        # tick_data=None makes get_full_tick return {}
        fake = _fake_xtdata_kline(df, tick_data=None)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["full_tick_attempted"] is True
        assert qs["full_tick_success"] is False
        assert qs["full_tick_applied"] is False
        assert qs["full_tick_reason"] == "tick_query_failed"


# ---------------------------------------------------------------------------
# qmt_status and provider_run_log completeness
# ---------------------------------------------------------------------------


class TestTickMetadataCompleteness:
    def test_qmt_status_has_all_tick_fields(self, monkeypatch):
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata_kline(df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        required = [
            "full_tick_attempted", "full_tick_success", "full_tick_applied",
            "full_tick_reason", "full_tick_trade_date", "full_tick_time_tag",
            "full_tick_last_price", "price_source",
        ]
        for key in required:
            assert key in qs, f"qmt_status missing: {key}"

    def test_run_log_has_tick_fields(self, monkeypatch):
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata_kline(df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        log = result["provider_run_log"][0]

        required = [
            "full_tick_attempted", "full_tick_applied",
            "full_tick_trade_date", "latest_price_source",
        ]
        for key in required:
            assert key in log, f"provider_run_log missing: {key}"


# ---------------------------------------------------------------------------
# Indicator recomputation verification
# ---------------------------------------------------------------------------


class TestIndicatorRecomputation:
    """Verify all indicators come from the tick-augmented sequence, not partial overrides."""

    def test_all_indicators_from_augmented_df(self, monkeypatch):
        """Construct old df with flat close=13.47, tick=14.00.

        After overlay: close=14.00, history_close[-1]=14.00,
        change_20d ≈ 14/13.47-1, ma20 < 14 → above, volatility > 0.
        """
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": today.strftime("%Y%m%d") + " 15:00:00",
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]

        # Core: close is from tick
        assert pd_["close"] == pytest.approx(14.00)

        # history_close ends with tick price
        assert pd_["history_close"][-1] == pytest.approx(14.00)
        # history_close has 100 entries (99 old + 1 tick)
        assert len(pd_["history_close"]) == 100

        # change_20d = close[-1]/close[-21] - 1 = 14.0/13.47 - 1
        assert pd_["change_20d"] == pytest.approx(14.0 / 13.47 - 1, abs=0.001)

        # change_60d = close[-1]/close[-61] - 1 = 14.0/13.47 - 1
        assert pd_["change_60d"] == pytest.approx(14.0 / 13.47 - 1, abs=0.001)

        # ma20: 19 values at 13.47 + 1 at 14.0 → mean < 14.0
        assert pd_["ma20_position"] == "above"  # 14.0 > ma20

        # max_drawdown_60d: all 13.47 except last 14.0 → no drawdown (monotonic up at end)
        assert pd_["max_drawdown_60d"] >= -0.01  # near zero

        # volatility_60d: mostly flat + one spike → small but > 0
        assert pd_["volatility_60d"] > 0

        # avg_turnover_20d: 19 values at 1e9 + 1 at 5e8
        expected_avg = (19 * 1e9 + 5e8) / 20
        assert pd_["avg_turnover_20d"] == pytest.approx(expected_avg, rel=0.01)

    def test_old_close_not_preserved_after_tick(self, monkeypatch):
        """Ensure old close=13.47 does NOT appear as final close after tick=14.00."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [13.47] * 99
        df = _make_daily_df(dates, closes)

        tick_raw = {
            "600519.SH": {
                "lastPrice": 14.00,
                "lastClose": 13.47,
                "amount": 5e8,
                "volume": 3e6,
                "timetag": today.strftime("%Y%m%d") + " 15:00:00",
            }
        }
        fake = _fake_xtdata_kline(df, tick_data=tick_raw)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")

        # The old close 13.47 must NOT be the final close
        assert result["price_data"]["close"] != 13.47
        assert result["price_data"]["close"] == pytest.approx(14.00)
