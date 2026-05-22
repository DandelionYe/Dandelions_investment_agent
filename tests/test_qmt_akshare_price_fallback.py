"""QMT AKShare price history fallback tests (layer 3 price fix).

All tests monkeypatch xtdata and AKShare so no real QMT environment or
network is needed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from services.data import akshare_provider as ak_mod
from services.data import qmt_provider as qmt_mod
from services.data.qmt_provider import (
    QMTSettings,
    get_qmt_asset_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_daily_df(
    dates: list[str],
    closes: list[float],
    amounts: list[float] | None = None,
) -> pd.DataFrame:
    """Build a minimal QMT-style daily DataFrame."""
    n = len(dates)
    if amounts is None:
        amounts = [1e9] * n
    df = pd.DataFrame(
        {"close": closes, "amount": amounts, "volume": [1e6] * n},
        index=dates,
    )
    df.index.name = None
    return df


def _make_akshare_df(
    dates: list[str],
    closes: list[float],
    amounts: list[float] | None = None,
    vendor: str = "eastmoney",
) -> pd.DataFrame:
    """Build a minimal AKShare-style daily DataFrame with Chinese column names."""
    n = len(dates)
    if amounts is None:
        amounts = [1e9] * n
    df = pd.DataFrame({
        "日期": dates,
        "收盘": closes,
        "成交额": amounts,
    })
    df["data_vendor"] = vendor
    return df


def _fake_xtdata_kline(df: pd.DataFrame, tick_data: dict | None = None):
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
        use_full_tick_for_stale=False,  # disable tick to simplify fallback tests
    )
    defaults.update(overrides)
    return QMTSettings(**defaults)


def _patch_akshare(monkeypatch, ak_result: dict | None = None, exc: Exception | None = None):
    """Monkeypatch akshare_provider.get_akshare_asset_data."""

    def _fake(symbol: str):
        if exc is not None:
            raise exc
        return ak_result

    monkeypatch.setattr(ak_mod, "get_akshare_asset_data", _fake)


def _build_akshare_result(
    dates: list[str],
    closes: list[float],
    amounts: list[float] | None = None,
    vendor: str = "eastmoney",
) -> dict:
    """Build a fake get_akshare_asset_data return dict."""
    from services.data.market_data_utils import build_price_data_from_frame

    df = _make_akshare_df(dates, closes, amounts, vendor)
    price_data = build_price_data_from_frame(
        df=df,
        close_col="收盘",
        amount_col="成交额",
        data_vendor=vendor,
    )
    # Add latest_trade_date from the 日期 column
    price_data["latest_trade_date"] = dates[-1] if dates else None
    price_data["price_is_stale"] = False
    price_data["price_history_source"] = "akshare"
    price_data["price_uses_intraday_tick"] = False
    price_data["latest_price_source"] = "akshare"
    return {
        "symbol": "600519.SH",
        "asset_type": "stock",
        "name": "600519.SH",
        "as_of": str(date.today()),
        "data_source": "akshare",
        "price_data": price_data,
        "source_metadata": {
            "price_data": {"source": "akshare", "vendor": vendor},
        },
        "provider_run_log": [],
    }


# ---------------------------------------------------------------------------
# Test: QMT fresh → no fallback attempted
# ---------------------------------------------------------------------------


class TestFreshQmtNoFallback:
    def test_fresh_qmt_skips_akshare(self, monkeypatch):
        """QMT data fresh → AKShare fallback not attempted."""
        today = date.today()
        dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        closes = [100.0 + i * 0.1 for i in range(100)]
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata_kline(df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert result["price_data"]["price_is_stale"] is False
        assert qs["akshare_price_fallback_attempted"] is False
        assert qs["akshare_price_fallback_applied"] is False
        assert result["price_data"]["latest_price_source"] == "qmt_kline"
        assert result["price_data"]["price_history_source"] == "qmt"


# ---------------------------------------------------------------------------
# Test: QMT stale, fallback disabled
# ---------------------------------------------------------------------------


class TestFallbackDisabled:
    def test_disabled_skips_akshare(self, monkeypatch):
        """QMT_PRICE_AKSHARE_FALLBACK=false → no attempt, reason=disabled."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        closes = [100.0] * 99
        df = _make_daily_df(dates, closes)

        fake = _fake_xtdata_kline(df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())
        monkeypatch.setenv("QMT_PRICE_AKSHARE_FALLBACK", "false")

        # AKShare should not be called at all
        _patch_akshare(monkeypatch, exc=AssertionError("should not be called"))

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert result["price_data"]["price_is_stale"] is True
        assert qs["akshare_price_fallback_enabled"] is False
        assert qs["akshare_price_fallback_attempted"] is False
        assert qs["akshare_price_fallback_reason"] == "disabled"
        assert any("过期" in w for w in result["data_warnings"])


# ---------------------------------------------------------------------------
# Test: QMT stale, AKShare fresh and newer → adopted
# ---------------------------------------------------------------------------


class TestFallbackAdopted:
    def test_akshare_fresh_and_newer(self, monkeypatch):
        """QMT stale, AKShare non-stale and newer → AKShare price_data adopted."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        # QMT stale data: 99 bars, flat at 13.47
        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_closes = [13.47] * 99
        qmt_df = _make_daily_df(qmt_dates, qmt_closes)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare fresh data: 100 bars, mostly 10.0, last is 14.0
        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_closes = [10.0] * 99 + [14.0]
        ak_result = _build_akshare_result(ak_dates, ak_closes)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]
        qs = result["source_metadata"]["qmt_status"]

        # AKShare adopted
        assert qs["akshare_price_fallback_attempted"] is True
        assert qs["akshare_price_fallback_applied"] is True
        assert qs["akshare_price_fallback_reason"] == "applied"
        assert qs["akshare_price_vendor"] == "eastmoney"

        # price_data from AKShare full sequence
        assert pd_["price_is_stale"] is False
        assert pd_["close"] == pytest.approx(14.0)
        assert pd_["history_close"][-1] == pytest.approx(14.0)
        assert pd_["latest_price_source"] == "akshare_price_history_fallback"
        assert pd_["price_history_source"] == "akshare"
        assert pd_["price_uses_intraday_tick"] is False

        # Indicators recomputed from AKShare full sequence
        assert pd_["change_20d"] == pytest.approx(14.0 / 10.0 - 1, abs=0.001)
        assert pd_["ma20_position"] == "above"  # 14 > mean of [10*19 + 14]
        assert pd_["volatility_60d"] > 0

        # Run log has AKShare entry
        assert len(result["provider_run_log"]) == 2
        ak_log = result["provider_run_log"][1]
        assert ak_log["provider"] == "akshare"
        assert ak_log["applied"] is True
        assert ak_log["reason"] == "applied"
        assert ak_log["status"] == "success"

        # QMT run log has fallback fields
        qmt_log = result["provider_run_log"][0]
        assert qmt_log["akshare_price_fallback_attempted"] is True
        assert qmt_log["akshare_price_fallback_applied"] is True

        # Effective price metadata must follow the adopted price sequence.
        price_meta = result["source_metadata"]["price_data"]
        assert price_meta["source"] == "akshare"
        assert price_meta["vendor"] == "eastmoney"

    def test_real_akshare_provider_shape_can_be_adopted(self, monkeypatch):
        """Fallback works with the real get_akshare_asset_data() return shape."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [
            (stale_date - timedelta(days=i)).strftime("%Y%m%d")
            for i in range(99, 0, -1)
        ]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        ak_start = today - timedelta(days=100)
        ak_dates = [(ak_start + timedelta(days=i)).isoformat() for i in range(100)]
        ak_df = pd.DataFrame(
            {
                "\u65e5\u671f": ak_dates,
                "\u6536\u76d8": [10.0] * 99 + [14.0],
                "\u6210\u4ea4\u989d": [1e9] * 100,
                "data_vendor": ["eastmoney"] * 100,
            }
        )
        monkeypatch.setattr(ak_mod, "_load_price_history", lambda symbol, asset_type: ak_df)

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]
        qs = result["source_metadata"]["qmt_status"]

        assert qs["akshare_price_fallback_attempted"] is True
        assert qs["akshare_price_fallback_applied"] is True
        assert qs["akshare_price_fallback_reason"] == "applied"
        assert qs["akshare_price_latest_trade_date"] == ak_dates[-1]
        assert pd_["latest_trade_date"] == ak_dates[-1]
        assert pd_["close"] == pytest.approx(14.0)
        assert pd_["price_history_source"] == "akshare"
        assert result["source_metadata"]["price_data"]["source"] == "akshare"


# ---------------------------------------------------------------------------
# Test: adopted price_data has all required fields from full sequence
# ---------------------------------------------------------------------------


class TestAdoptedIndicatorsFromFullSequence:
    def test_all_indicators_from_akshare(self, monkeypatch):
        """Adopted AKShare data must have close/history_close/change/MA/drawdown/vol."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare: 100 bars, last=14.0, rest=10.0
        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_closes = [10.0] * 99 + [14.0]
        ak_result = _build_akshare_result(ak_dates, ak_closes)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        pd_ = result["price_data"]

        # All these must exist and come from AKShare full sequence
        assert pd_["close"] == pytest.approx(14.0)
        assert len(pd_["history_close"]) == 100
        assert pd_["history_close"][-1] == pytest.approx(14.0)
        assert "change_20d" in pd_
        assert "change_60d" in pd_
        assert pd_["ma20_position"] in ("above", "below")
        assert pd_["ma60_position"] in ("above", "below")
        assert "max_drawdown_60d" in pd_
        assert pd_["volatility_60d"] > 0
        assert "avg_turnover_20d" in pd_


# ---------------------------------------------------------------------------
# Test: AKShare date same as or older than QMT → not adopted
# ---------------------------------------------------------------------------


class TestNotNewer:
    def test_akshare_same_stale_date_as_qmt(self, monkeypatch):
        """AKShare same stale date as QMT → rejected by stale check first."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare: same stale date as QMT → hits stale check before "not newer"
        ak_dates = [(stale_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(99, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [13.47] * 99)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["akshare_price_fallback_applied"] is False
        assert qs["akshare_price_fallback_reason"] == "akshare_stale"
        assert result["price_data"]["latest_price_source"] == "qmt_kline"
        assert result["price_data"]["price_is_stale"] is True

    def test_akshare_older_stale_date(self, monkeypatch):
        """AKShare older than QMT (both stale) → rejected by stale check."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        even_older = today - timedelta(days=15)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare: even older → stale check triggers first
        ak_dates = [(even_older - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(99, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [13.47] * 99)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["akshare_price_fallback_applied"] is False
        assert qs["akshare_price_fallback_reason"] == "akshare_stale"

    def test_akshare_fresh_but_not_newer_than_fresh_qmt(self, monkeypatch):
        """QMT fresh, AKShare fresh but older → fallback not attempted (QMT not stale)."""
        today = date.today()

        # QMT fresh data
        qmt_dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(100, 0, -1)]
        qmt_closes = [100.0 + i * 0.1 for i in range(100)]
        qmt_df = _make_daily_df(qmt_dates, qmt_closes)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare should not be called since QMT is fresh
        _patch_akshare(monkeypatch, exc=AssertionError("should not be called"))

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert result["price_data"]["price_is_stale"] is False
        assert qs["akshare_price_fallback_attempted"] is False


# ---------------------------------------------------------------------------
# Test: AKShare newer but still stale → not adopted (conservative)
# ---------------------------------------------------------------------------


class TestAkshareStaleNotAdopted:
    def test_akshare_stale_not_adopted(self, monkeypatch):
        """AKShare newer than QMT but still stale → not adopted."""
        today = date.today()
        stale_date = today - timedelta(days=10)
        ak_date = today - timedelta(days=5)  # newer than QMT but > max_stale_days=3

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # AKShare: newer than QMT but still stale (5 days > max_stale_days=3)
        ak_dates = [(ak_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(99, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 99)
        # Override latest_trade_date to reflect the ak_date
        ak_result["price_data"]["latest_trade_date"] = str(ak_date)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["akshare_price_fallback_applied"] is False
        assert qs["akshare_price_fallback_reason"] == "akshare_stale"
        assert result["price_data"]["price_is_stale"] is True


# ---------------------------------------------------------------------------
# Test: AKShare exception → not adopted, QMT preserved
# ---------------------------------------------------------------------------


class TestAkshareException:
    def test_akshare_exception_preserves_qmt(self, monkeypatch):
        """AKShare raises → QMT price_data preserved, warning recorded."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        _patch_akshare(monkeypatch, exc=RuntimeError("AKShare all APIs failed"))

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        # QMT preserved
        assert result["price_data"]["close"] == pytest.approx(13.47)
        assert result["price_data"]["price_is_stale"] is True
        assert result["price_data"]["latest_price_source"] == "qmt_kline"

        # AKShare failure recorded
        assert qs["akshare_price_fallback_attempted"] is True
        assert qs["akshare_price_fallback_success"] is False
        assert qs["akshare_price_fallback_applied"] is False
        assert qs["akshare_price_fallback_reason"] == "akshare_unavailable"

        # Warning includes reason
        assert any("akshare_unavailable" in w for w in result["data_warnings"])

        # Run log has AKShare failure entry
        ak_log = result["provider_run_log"][1]
        assert ak_log["provider"] == "akshare"
        assert ak_log["applied"] is False
        assert ak_log["reason"] == "akshare_unavailable"
        assert ak_log["error"] is not None


# ---------------------------------------------------------------------------
# Test: AKShare date unparseable → not adopted
# ---------------------------------------------------------------------------


class TestAkshareDateUnparseable:
    def test_akshare_date_unparseable(self, monkeypatch):
        """AKShare returns no parseable latest_trade_date → not adopted."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        # Build AKShare result with no latest_trade_date
        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 100)
        ak_result["price_data"]["latest_trade_date"] = None
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        assert qs["akshare_price_fallback_applied"] is False
        assert qs["akshare_price_fallback_reason"] == "akshare_date_unparseable"


# ---------------------------------------------------------------------------
# Test: qmt_status fields completeness
# ---------------------------------------------------------------------------


class TestQmtStatusFields:
    def test_all_akshare_fallback_fields_present(self, monkeypatch):
        """qmt_status has all AKShare fallback fields."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 100)
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qs = result["source_metadata"]["qmt_status"]

        required = [
            "akshare_price_fallback_enabled",
            "akshare_price_fallback_attempted",
            "akshare_price_fallback_success",
            "akshare_price_fallback_applied",
            "akshare_price_fallback_reason",
            "akshare_price_latest_trade_date",
            "akshare_price_vendor",
        ]
        for key in required:
            assert key in qs, f"qmt_status missing: {key}"


# ---------------------------------------------------------------------------
# Test: basic_info preserved after fallback
# ---------------------------------------------------------------------------


class TestBasicInfoPreserved:
    def test_basic_info_not_lost(self, monkeypatch):
        """QMT basic_info is preserved even when AKShare fallback is adopted."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)

        detail = {
            "InstrumentName": "贵州茅台",
            "ExchangeID": "SH",
            "TotalVolume": 1256197800,
        }
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: detail)
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 99 + [14.0])
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")

        # basic_info from QMT preserved
        assert result["basic_info"]["instrument_name"] == "贵州茅台"
        assert result["basic_info"]["exchange_id"] == "SH"
        assert result["basic_info"]["total_volume"] == 1256197800

        # data_source still qmt
        assert result["data_source"] == "qmt"

        # source_metadata.qmt_status still present
        assert "qmt_status" in result["source_metadata"]

        # price_data is from AKShare
        assert result["price_data"]["close"] == pytest.approx(14.0)
        assert result["price_data"]["latest_price_source"] == "akshare_price_history_fallback"


# ---------------------------------------------------------------------------
# Test: provider_run_log completeness
# ---------------------------------------------------------------------------


class TestProviderRunLog:
    def test_success_log_has_akshare_fields(self, monkeypatch):
        """QMT run log has AKShare fallback fields."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 99 + [14.0])
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")
        qmt_log = result["provider_run_log"][0]

        assert "akshare_price_fallback_attempted" in qmt_log
        assert "akshare_price_fallback_applied" in qmt_log
        assert "akshare_price_latest_trade_date" in qmt_log

    def test_failure_log_has_akshare_entry(self, monkeypatch):
        """Failed AKShare fallback produces run_log entry with applied=false."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        _patch_akshare(monkeypatch, exc=RuntimeError("network error"))

        result = get_qmt_asset_data("600519.SH")

        assert len(result["provider_run_log"]) == 2
        ak_log = result["provider_run_log"][1]
        assert ak_log["provider"] == "akshare"
        assert ak_log["applied"] is False
        assert ak_log["reason"] == "akshare_unavailable"
        assert ak_log["status"] == "failed"


# ---------------------------------------------------------------------------
# Test: data_warnings content
# ---------------------------------------------------------------------------


class TestDataWarnings:
    def test_applied_warning(self, monkeypatch):
        """Successful fallback → info warning about AKShare adoption."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        ak_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(100, 0, -1)]
        ak_result = _build_akshare_result(ak_dates, [10.0] * 99 + [14.0])
        _patch_akshare(monkeypatch, ak_result)

        result = get_qmt_asset_data("600519.SH")

        # When AKShare is adopted and not stale, no stale warning
        assert not any("过期" in w for w in result["data_warnings"])

    def test_failed_fallback_warning(self, monkeypatch):
        """Failed fallback → warning with reason."""
        today = date.today()
        stale_date = today - timedelta(days=10)

        qmt_dates = [(stale_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(99, 0, -1)]
        qmt_df = _make_daily_df(qmt_dates, [13.47] * 99)

        fake = _fake_xtdata_kline(qmt_df)
        _patch_xtdata(monkeypatch, fake)
        monkeypatch.setattr(qmt_mod, "_load_qmt_instrument_detail", lambda s: {})
        monkeypatch.setattr(qmt_mod, "load_qmt_settings", lambda: _settings())

        _patch_akshare(monkeypatch, exc=RuntimeError("fail"))

        result = get_qmt_asset_data("600519.SH")

        assert any("akshare_unavailable" in w for w in result["data_warnings"])
