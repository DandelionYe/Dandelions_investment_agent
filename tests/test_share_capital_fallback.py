"""Tests for share capital fallback: provider, valuation engine, peer loader, preflight."""

import pandas as pd
import pytest

from services.data.providers.akshare_share_capital_provider import (
    AKShareShareCapitalProvider,
    _extract_field,
    _parse_cn_number,
    _symbol_to_eastmoney_code,
    get_share_capital_fallback_max_symbols,
    is_share_capital_fallback_enabled,
    resolve_share_capital_fallback,
)

# ---------------------------------------------------------------------------
# _parse_cn_number
# ---------------------------------------------------------------------------

class TestParseCnNumber:
    def test_none_returns_none(self):
        assert _parse_cn_number(None) is None

    def test_int_passthrough(self):
        assert _parse_cn_number(1000) == 1000.0

    def test_float_passthrough(self):
        assert _parse_cn_number(3.14) == pytest.approx(3.14)

    def test_nan_returns_none(self):
        assert _parse_cn_number(float("nan")) is None

    def test_string_number(self):
        assert _parse_cn_number("12345") == pytest.approx(12345.0)

    def test_string_with_comma(self):
        assert _parse_cn_number("12,345") == pytest.approx(12345.0)

    def test_yi_unit(self):
        assert _parse_cn_number("15.36亿") == pytest.approx(1.536e9)

    def test_wan_unit(self):
        assert _parse_cn_number("8000万") == pytest.approx(8e7)

    def test_yi_with_space(self):
        assert _parse_cn_number(" 3.5 亿 ") == pytest.approx(3.5e8)

    def test_dash_returns_none(self):
        assert _parse_cn_number("--") is None

    def test_empty_string_returns_none(self):
        assert _parse_cn_number("") is None


# ---------------------------------------------------------------------------
# _extract_field
# ---------------------------------------------------------------------------

class TestExtractField:
    def test_extracts_total_volume(self):
        df = pd.DataFrame({
            "item": ["股票代码", "总股本", "流通股"],
            "value": ["601728", "809.32亿股", "672.35亿股"],
        })
        assert _extract_field(df, "总股本") == pytest.approx(8.0932e10)

    def test_extracts_market_cap(self):
        df = pd.DataFrame({
            "item": ["总市值", "流通市值"],
            "value": ["5403.25亿", "4501.12亿"],
        })
        assert _extract_field(df, "总市值") == pytest.approx(5.40325e11)

    def test_missing_field_returns_none(self):
        df = pd.DataFrame({
            "item": ["股票代码"],
            "value": ["601728"],
        })
        assert _extract_field(df, "总股本") is None

    def test_none_df_returns_none(self):
        assert _extract_field(None, "总股本") is None

    def test_empty_df_returns_none(self):
        assert _extract_field(pd.DataFrame(), "总股本") is None

    def test_numeric_value(self):
        df = pd.DataFrame({
            "item": ["总股本"],
            "value": [8093200000],
        })
        assert _extract_field(df, "总股本") == pytest.approx(8.0932e9)


# ---------------------------------------------------------------------------
# _symbol_to_eastmoney_code
# ---------------------------------------------------------------------------

def test_symbol_to_eastmoney_code():
    assert _symbol_to_eastmoney_code("601728.SH") == "601728"
    assert _symbol_to_eastmoney_code("000001.SZ") == "000001"
    assert _symbol_to_eastmoney_code("430047.BJ") == "430047"


# ---------------------------------------------------------------------------
# AKShareShareCapitalProvider
# ---------------------------------------------------------------------------

class TestAKShareShareCapitalProvider:
    def test_fetch_success(self, monkeypatch):
        fake_df = pd.DataFrame({
            "item": ["股票代码", "总股本", "流通股", "总市值", "流通市值"],
            "value": ["601728", "809.32亿股", "672.35亿股", "5403.25亿", "4501.12亿"],
        })

        import services.data.providers.akshare_share_capital_provider as mod

        def fake_disable():
            pass

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return fake_df

        monkeypatch.setattr(mod, "disable_proxy_for_current_process", fake_disable)

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        provider = AKShareShareCapitalProvider()
        result = provider.fetch_share_capital("601728.SH")

        assert result.metadata.success is True
        assert result.data["total_volume"] == pytest.approx(8.0932e10)
        assert result.data["float_volume"] == pytest.approx(6.7235e10)
        assert result.data["market_cap"] == pytest.approx(5.40325e11)
        assert result.data["float_market_cap"] == pytest.approx(4.50112e11)

    def test_fetch_failure_returns_error(self, monkeypatch):
        import services.data.providers.akshare_share_capital_provider as mod

        def fake_disable():
            pass

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                raise ConnectionError("Network error")

        monkeypatch.setattr(mod, "disable_proxy_for_current_process", fake_disable)

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        provider = AKShareShareCapitalProvider()
        result = provider.fetch_share_capital("601728.SH")

        assert result.metadata.success is False
        assert "Network error" in result.metadata.error
        assert result.data == {}

    def test_fetch_empty_data_returns_failure(self, monkeypatch):
        import services.data.providers.akshare_share_capital_provider as mod

        def fake_disable():
            pass

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return pd.DataFrame({"item": ["股票代码"], "value": ["601728"]})

        monkeypatch.setattr(mod, "disable_proxy_for_current_process", fake_disable)

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        provider = AKShareShareCapitalProvider()
        result = provider.fetch_share_capital("601728.SH")

        assert result.metadata.success is False


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def test_is_share_capital_fallback_enabled_default(monkeypatch):
    monkeypatch.delenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", raising=False)
    assert is_share_capital_fallback_enabled() is True


def test_is_share_capital_fallback_enabled_disabled(monkeypatch):
    monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")
    assert is_share_capital_fallback_enabled() is False


def test_get_share_capital_fallback_max_symbols_default(monkeypatch):
    monkeypatch.delenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", raising=False)
    assert get_share_capital_fallback_max_symbols() == 50


def test_get_share_capital_fallback_max_symbols_custom(monkeypatch):
    monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "100")
    assert get_share_capital_fallback_max_symbols() == 100


def test_resolve_share_capital_fallback_reports_skipped_symbols(monkeypatch):
    monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")

    class FakeProvider:
        def fetch_share_capital(self, symbol):
            return type("R", (), {
                "data": {"total_volume": 100},
                "metadata": type("M", (), {
                    "success": True,
                    "error": None,
                    "error_type": None,
                })(),
            })()

    result = resolve_share_capital_fallback(
        ["A.SH", "B.SH", "C.SH"],
        provider=FakeProvider(),
        max_symbols=2,
    )

    assert result["attempted_symbols"] == ["A.SH", "B.SH"]
    assert result["skipped_symbols"] == ["C.SH"]
    assert result["skipped_count"] == 1
    assert set(result["values"]) == {"A.SH", "B.SH"}


def test_resolve_share_capital_fallback_disabled_has_no_limit_skip(monkeypatch):
    monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

    result = resolve_share_capital_fallback(["A.SH", "B.SH"], max_symbols=1)

    assert result["enabled"] is False
    assert result["attempted_symbols"] == []
    assert result["skipped_symbols"] == []
    assert result["skipped_count"] == 0


# ---------------------------------------------------------------------------
# Valuation engine integration
# ---------------------------------------------------------------------------

class TestValuationEngineShareCapitalFallback:
    def test_qmt_total_volume_zero_fallback_provides_total_volume(self, monkeypatch):
        """When QMT total_volume=0, fallback provides total_volume, market_cap/pe/ps are computed."""
        from services.data.normalizers.valuation_normalizer import ValuationNormalizer
        from services.research.valuation_engine import ValuationService

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")

        fake_sc_result = type("R", (), {
            "provider": "akshare",
            "dataset": "stock_individual_info_em",
            "data": {
                "total_volume": 1e10,
                "float_volume": 8e9,
                "market_cap": 6.67e10,
            },
            "metadata": type("M", (), {
                "success": True, "error": None, "error_type": None,
            })(),
        })()

        class FakeSCProvider:
            def fetch_share_capital(self, symbol):
                return fake_sc_result

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            share_capital_provider=FakeSCProvider(),
        )

        asset_data = {
            "symbol": "601728.SH",
            "asset_type": "stock",
            "as_of": "2026-05-20",
            "data_source": "qmt",
            "price_data": {"close": 6.67},
            "basic_info": {"total_volume": 0, "float_volume": 0},
            "fundamental_data": {"net_profit_ttm": 300, "revenue_ttm": 5000, "bps": 5},
        }

        result = service.build(asset_data)
        valuation = result["data"]["valuation_data"]

        assert valuation["market_cap"] is not None
        assert valuation["float_market_cap"] is not None
        assert valuation["market_cap"] > 0
        assert valuation["pe_ttm"] is not None
        assert valuation["ps_ttm"] is not None
        assert asset_data["basic_info"]["float_volume"] == pytest.approx(8e9)
        assert result["source_metadata"]["valuation_data"]["source"] == "qmt_derived+share_capital_fallback"
        assert (
            result["source_metadata"]["valuation_data"]["calculation_method"]
            == valuation["calculation_method"]
        )
        assert any(
            "share_capital_from_akshare" in str(r.get("calculation_method", ""))
            for r in [valuation]
        )
        assert any(
            log["dataset"] == "stock_individual_info_em" and log["status"] == "success"
            for log in result["provider_run_log"]
        )

    def test_qmt_total_volume_positive_skips_fallback(self, monkeypatch):
        """When QMT total_volume > 0, fallback is NOT called."""
        from services.data.normalizers.valuation_normalizer import ValuationNormalizer
        from services.research.valuation_engine import ValuationService

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")

        class FakeSCProvider:
            def __init__(self):
                self.called = False

            def fetch_share_capital(self, symbol):
                self.called = True
                raise AssertionError("Should not be called when QMT total_volume > 0")

        sc_provider = FakeSCProvider()
        service = ValuationService(
            normalizer=ValuationNormalizer(),
            share_capital_provider=sc_provider,
        )

        asset_data = {
            "symbol": "600519.SH",
            "asset_type": "stock",
            "as_of": "2026-05-20",
            "data_source": "qmt",
            "price_data": {"close": 100.0},
            "basic_info": {"total_volume": 1e9, "float_volume": 8e8},
            "fundamental_data": {"net_profit_ttm": 500, "revenue_ttm": 2000, "bps": 40},
        }

        result = service.build(asset_data)
        assert sc_provider.called is False
        assert result["source_metadata"]["valuation_data"]["source"] == "qmt_derived"

    def test_fallback_market_cap_only_infers_total_volume(self, monkeypatch):
        """When fallback only provides market_cap, total_volume = market_cap / close."""
        from services.data.normalizers.valuation_normalizer import ValuationNormalizer
        from services.research.valuation_engine import ValuationService

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")

        fake_sc_result = type("R", (), {
            "provider": "akshare",
            "dataset": "stock_individual_info_em",
            "data": {"market_cap": 6.67e10},  # no total_volume
            "metadata": type("M", (), {
                "success": True, "error": None, "error_type": None,
            })(),
        })()

        class FakeSCProvider:
            def fetch_share_capital(self, symbol):
                return fake_sc_result

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            share_capital_provider=FakeSCProvider(),
        )

        asset_data = {
            "symbol": "601728.SH",
            "asset_type": "stock",
            "as_of": "2026-05-20",
            "data_source": "qmt",
            "price_data": {"close": 6.67},
            "basic_info": {"total_volume": 0, "float_volume": 0},
            "fundamental_data": {"net_profit_ttm": 300, "revenue_ttm": 5000, "bps": 5},
        }

        result = service.build(asset_data)
        valuation = result["data"]["valuation_data"]

        # market_cap / close = 6.67e10 / 6.67 = 1e10
        assert valuation["market_cap"] is not None
        assert valuation["pe_ttm"] is not None

    def test_fallback_failure_does_not_block(self, monkeypatch):
        """When fallback fails, main flow continues. pb_mrq is still available via close/bps."""
        from services.data.normalizers.valuation_normalizer import ValuationNormalizer
        from services.research.valuation_engine import ValuationService

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")

        fake_sc_result = type("R", (), {
            "provider": "akshare",
            "dataset": "stock_individual_info_em",
            "data": {},
            "metadata": type("M", (), {
                "success": False, "error": "Network error", "error_type": "provider_unavailable",
            })(),
        })()

        class FakeSCProvider:
            def fetch_share_capital(self, symbol):
                return fake_sc_result

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            share_capital_provider=FakeSCProvider(),
        )

        asset_data = {
            "symbol": "601728.SH",
            "asset_type": "stock",
            "as_of": "2026-05-20",
            "data_source": "qmt",
            "price_data": {"close": 6.67},
            "basic_info": {"total_volume": 0, "float_volume": 0},
            "fundamental_data": {"net_profit_ttm": 300, "revenue_ttm": 5000, "bps": 5},
        }

        result = service.build(asset_data)
        valuation = result["data"]["valuation_data"]

        # pb_mrq is still available (close/bps), so _has_core_fields passes
        # and AKShare valuation fallback is NOT triggered
        assert valuation["pb_mrq"] == pytest.approx(6.67 / 5)
        # pe_ttm is None because market_cap requires total_volume
        assert valuation["pe_ttm"] is None
        assert valuation["market_cap"] is None
        # The fallback failure is recorded in the run log
        assert any(
            log["dataset"] == "stock_individual_info_em" and log["status"] == "failed"
            for log in result["provider_run_log"]
        )

    def test_fallback_disabled_skips_entirely(self, monkeypatch):
        from services.data.normalizers.valuation_normalizer import ValuationNormalizer
        from services.research.valuation_engine import ValuationService

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        class FakeSCProvider:
            def __init__(self):
                self.called = False

            def fetch_share_capital(self, symbol):
                self.called = True
                raise AssertionError("Should not be called when disabled")

        sc_provider = FakeSCProvider()
        service = ValuationService(
            normalizer=ValuationNormalizer(),
            share_capital_provider=sc_provider,
        )

        asset_data = {
            "symbol": "601728.SH",
            "asset_type": "stock",
            "as_of": "2026-05-20",
            "data_source": "qmt",
            "price_data": {"close": 6.67},
            "basic_info": {"total_volume": 0, "float_volume": 0},
            "fundamental_data": {"net_profit_ttm": 300, "revenue_ttm": 5000, "bps": 5},
        }

        service.build(asset_data)
        assert sc_provider.called is False


# ---------------------------------------------------------------------------
# Peer valuation loader integration
# ---------------------------------------------------------------------------

class TestPeerLoaderShareCapitalFallback:
    def test_peer_total_volume_zero_fallback_applied(self, monkeypatch):
        """When peer total_volume=0 from QMT, AKShare fallback fills it in."""
        import pandas as pd

        from services.data.providers import qmt_peer_valuation_loader as mod
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "10")

        class FakeXtData:
            enable_hello = True
            def connect(self): return None
            def get_data_dir(self): return "fake"
            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}
            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}
            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda settings=None: None)

        # Mock akshare
        fake_df = pd.DataFrame({
            "item": ["总股本", "流通股"],
            "value": ["100亿股", "80亿股"],
        })

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return fake_df

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        import services.data.providers.akshare_share_capital_provider as sc_mod
        monkeypatch.setattr(sc_mod, "disable_proxy_for_current_process", lambda: None)

        loader = QMTPeerValuationLoader()
        peers = loader.load_peer_inputs(["600001.SH", "600002.SH"], as_of="2026-05-20")

        assert len(peers) == 2
        # After fallback, total_volume should be filled
        assert peers[0]["total_volume"] == pytest.approx(1e10)
        assert peers[1]["total_volume"] == pytest.approx(1e10)
        assert peers[0]["float_volume"] == pytest.approx(8e9)
        assert peers[1]["float_volume"] == pytest.approx(8e9)
        assert loader.last_share_capital_fallback["filled_count"] == 2

    def test_peer_fallback_does_not_clear_suspended_state(self, monkeypatch):
        """Share-capital fallback must not turn price-missing peers into tradable peers."""
        import pandas as pd

        from services.data.providers import qmt_peer_valuation_loader as mod
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "10")

        class FakeXtData:
            enable_hello = True

            def connect(self):
                return None

            def get_data_dir(self):
                return "fake"

            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame() for s in kw["stock_list"]}

            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}

            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda settings=None: None)

        fake_df = pd.DataFrame({
            "item": ["总股本"],
            "value": ["100亿股"],
        })

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return fake_df

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        import services.data.providers.akshare_share_capital_provider as sc_mod
        monkeypatch.setattr(sc_mod, "disable_proxy_for_current_process", lambda: None)

        loader = QMTPeerValuationLoader()
        peers = loader.load_peer_inputs(["600001.SH"], as_of="2026-05-20")

        assert peers[0]["total_volume"] == pytest.approx(1e10)
        assert peers[0]["close"] is None
        assert peers[0]["is_suspended"] is True

    def test_peer_total_volume_positive_skips_fallback(self, monkeypatch):
        """When QMT total_volume > 0, fallback is NOT called."""
        import pandas as pd

        from services.data.providers import qmt_peer_valuation_loader as mod
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")

        class FakeXtData:
            enable_hello = True
            def connect(self): return None
            def get_data_dir(self): return "fake"
            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}
            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 1000, "FloatVolume": 800}
            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda settings=None: None)

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                raise AssertionError("Should not be called")

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        loader = QMTPeerValuationLoader()
        peers = loader.load_peer_inputs(["600001.SH"], as_of="2026-05-20")

        assert peers[0]["total_volume"] == 1000

    def test_max_symbols_limit_skips_excess(self, monkeypatch):
        """When missing peers exceed MAX_SYMBOLS, only first N are queried."""
        import pandas as pd

        from services.data.providers import qmt_peer_valuation_loader as mod
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "2")

        symbols = [f"60000{i}.SH" for i in range(5)]

        class FakeXtData:
            enable_hello = True
            def connect(self): return None
            def get_data_dir(self): return "fake"
            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}
            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}
            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda settings=None: None)

        call_count = {"n": 0}

        fake_df = pd.DataFrame({
            "item": ["总股本"],
            "value": ["100亿股"],
        })

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                call_count["n"] += 1
                return fake_df

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        import services.data.providers.akshare_share_capital_provider as sc_mod
        monkeypatch.setattr(sc_mod, "disable_proxy_for_current_process", lambda: None)

        loader = QMTPeerValuationLoader()
        peers = loader.load_peer_inputs(symbols, as_of="2026-05-20")

        # Only 2 out of 5 should have been queried
        assert call_count["n"] == 2
        # First 2 should have total_volume filled
        assert peers[0]["total_volume"] == pytest.approx(1e10)
        assert peers[1]["total_volume"] == pytest.approx(1e10)
        # Rest should still be 0
        assert peers[2]["total_volume"] == 0
        assert peers[3]["total_volume"] == 0
        assert peers[4]["total_volume"] == 0
        assert loader.last_share_capital_fallback["skipped_count"] == 3
        assert peers[2]["share_capital_fallback_status"] == "skipped_by_limit"

    def test_fallback_disabled_skips_entirely(self, monkeypatch):
        import pandas as pd

        from services.data.providers import qmt_peer_valuation_loader as mod
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        class FakeXtData:
            enable_hello = True
            def connect(self): return None
            def get_data_dir(self): return "fake"
            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}
            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}
            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda settings=None: None)

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                raise AssertionError("Should not be called when disabled")

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        loader = QMTPeerValuationLoader()
        peers = loader.load_peer_inputs(["600001.SH"], as_of="2026-05-20")

        assert peers[0]["total_volume"] == 0


# ---------------------------------------------------------------------------
# Preflight integration
# ---------------------------------------------------------------------------

class TestPreflightShareCapitalFallback:
    def test_preflight_fallback_improves_coverage(self, monkeypatch):
        """When QMT total_volume=0 but AKShare provides it, preflight reports higher coverage."""
        import pandas as pd

        from services.data.providers import qmt_peer_cache_preflight as mod
        from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "50")

        symbols = [f"60000{i}.SH" for i in range(10)]

        class FakeXtData:
            enable_hello = True
            def connect(self): return None
            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}
            def get_instrument_detail(self, symbol):
                # All have zero total_volume
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}
            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda: None)

        fake_df = pd.DataFrame({
            "item": ["总股本"],
            "value": ["100亿股"],
        })

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return fake_df

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        import services.data.providers.akshare_share_capital_provider as sc_mod
        monkeypatch.setattr(sc_mod, "disable_proxy_for_current_process", lambda: None)

        loader = QMTPeerValuationLoader()
        preflight = QMTPeerCachePreflight(loader=loader)

        result = preflight.check(symbols=symbols, threshold=0.8)

        # Without fallback, share_capital_ready would be False (all zero)
        # With fallback, it should be True (all filled)
        assert result["share_capital_ready"] is True
        assert result["coverage"]["total_volume"] == 1.0

    def test_preflight_reports_share_capital_fallback_skipped_by_limit(self, monkeypatch):
        import pandas as pd

        from services.data.providers import qmt_peer_cache_preflight as mod
        from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight
        from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "2")

        symbols = [f"60000{i}.SH" for i in range(5)]

        class FakeXtData:
            enable_hello = True

            def connect(self):
                return None

            def get_market_data_ex(self, **kw):
                return {s: pd.DataFrame([{"time": "20260520", "close": 10.0}]) for s in kw["stock_list"]}

            def get_instrument_detail(self, symbol):
                return {"InstrumentName": "Test", "TotalVolume": 0, "FloatVolume": 0}

            def get_financial_data(self, symbols, tables, start, end, report_type):
                return {s: {
                    "Income": pd.DataFrame([{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]),
                    "PershareIndex": pd.DataFrame([{"m_timetag": "20251231", "bps": 5}]),
                } for s in symbols}

        fake_xtdata = FakeXtData()
        monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
        monkeypatch.setattr(mod, "connect_qmt", lambda: None)

        fake_df = pd.DataFrame({
            "item": ["总股本"],
            "value": ["100亿股"],
        })

        class FakeAk:
            @staticmethod
            def stock_individual_info_em(symbol):
                return fake_df

        import sys
        monkeypatch.setitem(sys.modules, "akshare", FakeAk())

        import services.data.providers.akshare_share_capital_provider as sc_mod
        monkeypatch.setattr(sc_mod, "disable_proxy_for_current_process", lambda: None)

        loader = QMTPeerValuationLoader()
        preflight = QMTPeerCachePreflight(loader=loader)

        result = preflight.check(symbols=symbols, threshold=0.8)

        assert result["share_capital_fallback"]["skipped_count"] == 3
        assert result["coverage"]["total_volume"] == pytest.approx(0.4)
        assert any(
            warning.startswith("qmt_peer_share_capital_fallback_skipped_by_limit")
            for warning in result["warnings"]
        )
