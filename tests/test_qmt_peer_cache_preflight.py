import pandas as pd
import pytest

from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight
from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader

_ALL_FINANCE_FIELDS = {"revenue", "net_profit", "bps"}


class _FakeXtData:
    """Fake xtdata that returns configurable coverage for preflight tests."""

    def __init__(
        self,
        *,
        missing_close: set[str] | None = None,
        zero_volume: set[str] | None = None,
        missing_finance: set[str] | None = None,
        missing_fields_per_symbol: dict[str, set[str]] | None = None,
    ) -> None:
        self.missing_close = missing_close or set()
        self.zero_volume = zero_volume or set()
        # missing_finance: symbols where ALL finance fields are missing
        self.missing_finance = missing_finance or set()
        # missing_fields_per_symbol: per-symbol set of field names to omit
        self.missing_fields_per_symbol = missing_fields_per_symbol or {}

    def get_market_data_ex(self, field_list, stock_list, period, start_time, end_time, count, dividend_type, fill_data):
        result = {}
        for symbol in stock_list:
            if symbol in self.missing_close:
                result[symbol] = pd.DataFrame()
            else:
                result[symbol] = pd.DataFrame([{"time": end_time, "close": 15.0}])
        return result

    def get_instrument_detail(self, symbol: str):
        if symbol in self.zero_volume:
            return {"InstrumentName": f"Name {symbol}", "TotalVolume": 0, "FloatVolume": 0}
        return {"InstrumentName": f"Name {symbol}", "TotalVolume": 100, "FloatVolume": 80}

    def get_financial_data(self, symbols, tables, start, end, report_type):
        result = {}
        for symbol in symbols:
            # Merge per-symbol missing fields with bulk missing_finance
            if symbol in self.missing_finance:
                fields_missing = _ALL_FINANCE_FIELDS
            else:
                fields_missing = self.missing_fields_per_symbol.get(symbol, set())

            income_data = {"m_timetag": "20251231"}
            if "revenue" not in fields_missing:
                income_data["revenue"] = 500
            if "net_profit" not in fields_missing:
                income_data["net_profit"] = 100

            pershare_data = {"m_timetag": "20251231"}
            if "bps" not in fields_missing:
                pershare_data["bps"] = 5

            result[symbol] = {
                "Income": pd.DataFrame([income_data]),
                "PershareIndex": pd.DataFrame([pershare_data]),
            }
        return result


@pytest.fixture(autouse=True)
def _patch_qmt(monkeypatch):
    """Ensure _import_xtdata and connect_qmt are available as module attrs
    so _make_loader can patch them without polluting other tests."""
    monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
    import services.data.providers.qmt_peer_cache_preflight as mod
    # Keep original references so they're restored after each test
    monkeypatch.setattr(mod, "_import_xtdata", mod._import_xtdata, raising=False)
    monkeypatch.setattr(mod, "connect_qmt", mod.connect_qmt, raising=False)


def _make_loader(fake_xtdata, monkeypatch) -> QMTPeerValuationLoader:
    loader = QMTPeerValuationLoader()
    import services.data.providers.qmt_peer_cache_preflight as mod
    monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(mod, "connect_qmt", lambda: None)
    return loader


def test_empty_symbols_returns_not_ready():
    preflight = QMTPeerCachePreflight()
    result = preflight.check(symbols=[], threshold=0.8)
    assert result["ready"] is False
    assert result["checked_count"] == 0
    assert any("No symbols" in w for w in result["warnings"])


def test_all_fields_above_threshold_ready(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(20)]
    fake = _FakeXtData()
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.8)
    assert result["ready"] is True
    assert result["finance_ready"] is True
    assert result["price_ready"] is True
    assert result["share_capital_ready"] is True
    assert result["coverage"]["close"] == 1.0
    assert result["coverage"]["total_volume"] == 1.0
    assert result["coverage"]["net_profit_ttm"] == 1.0
    assert result["coverage"]["revenue_ttm"] == 1.0
    assert result["coverage"]["bps"] == 1.0
    assert result["coverage"]["peer_valuation_complete"] == 1.0
    assert result["counts"]["close"] == 20
    assert result["counts"]["peer_valuation_complete"] == 20


def test_insufficient_close_price_not_ready(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(20)]
    missing_close = {f"600{i:03d}.SH" for i in range(18)}
    fake = _FakeXtData(missing_close=missing_close)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.8)
    assert result["ready"] is False
    assert result["price_ready"] is False
    assert result["finance_ready"] is True
    assert result["share_capital_ready"] is True
    assert result["coverage"]["close"] == pytest.approx(0.1)
    assert len(result["sample_missing"]["close"]) == 10
    assert "qmt_peer_price_cache_insufficient" in result["warnings"]


def test_zero_total_volume_treated_as_missing(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(20)]
    zero_volume = {f"600{i:03d}.SH" for i in range(18)}
    fake = _FakeXtData(zero_volume=zero_volume)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.8)
    assert result["ready"] is False
    assert result["share_capital_ready"] is False
    assert result["coverage"]["total_volume"] == pytest.approx(0.1)
    assert "qmt_peer_share_capital_insufficient" in result["warnings"]


def test_finance_field_insufficient(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(20)]
    missing_finance = {f"600{i:03d}.SH" for i in range(18)}
    fake = _FakeXtData(missing_finance=missing_finance)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.8)
    assert result["ready"] is False
    assert result["finance_ready"] is False
    assert result["coverage"]["net_profit_ttm"] == pytest.approx(0.1)
    assert result["coverage"]["revenue_ttm"] == pytest.approx(0.1)
    assert result["coverage"]["bps"] == pytest.approx(0.1)
    assert "qmt_finance_cache_insufficient_for_peer_valuation" in result["warnings"]


def test_partial_finance_field_insufficient(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(20)]
    missing_fields = {
        f"600{i:03d}.SH": {"bps"} for i in range(18)
    }
    fake = _FakeXtData(missing_fields_per_symbol=missing_fields)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.8)
    assert result["ready"] is False
    assert result["finance_ready"] is False
    assert result["coverage"]["net_profit_ttm"] == 1.0
    assert result["coverage"]["revenue_ttm"] == 1.0
    assert result["coverage"]["bps"] == pytest.approx(0.1)


def test_threshold_from_env(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(10)]
    fake = _FakeXtData()
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    monkeypatch.setenv("QMT_PEER_CACHE_MIN_COVERAGE", "0.5")
    result = preflight.check(symbols=symbols)
    assert result["threshold"] == 0.5
    assert result["ready"] is True


def test_peer_valuation_complete_counts(monkeypatch):
    symbols = ["A.SH", "B.SH", "C.SH"]
    missing_fields = {"C.SH": {"bps"}}
    fake = _FakeXtData(missing_close={"B.SH"}, missing_fields_per_symbol=missing_fields)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.5)
    # A is complete, B missing close, C missing bps -> 1/3 complete
    assert result["counts"]["peer_valuation_complete"] == 1
    assert result["coverage"]["peer_valuation_complete"] == pytest.approx(1 / 3)


def test_default_check_no_missing_symbols(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(10)]
    missing_close = {f"600{i:03d}.SH" for i in range(5)}
    fake = _FakeXtData(missing_close=missing_close)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.5)
    assert "missing_symbols" not in result


def test_include_missing_symbols_returns_full_list(monkeypatch):
    symbols = [f"600{i:03d}.SH" for i in range(12)]
    missing_close = {f"600{i:03d}.SH" for i in range(11)}  # 11 > SAMPLE_LIMIT
    fake = _FakeXtData(missing_close=missing_close)
    loader = _make_loader(fake, monkeypatch)
    preflight = QMTPeerCachePreflight(loader=loader)

    result = preflight.check(symbols=symbols, threshold=0.5, include_missing_symbols=True)
    assert "missing_symbols" in result
    assert len(result["missing_symbols"]["close"]) == 11
    # sample_missing still capped at 10
    assert len(result["sample_missing"]["close"]) == 10


def test_include_missing_symbols_empty_symbols():
    preflight = QMTPeerCachePreflight()
    result = preflight.check(symbols=[], threshold=0.8, include_missing_symbols=True)
    assert "missing_symbols" in result
    assert result["missing_symbols"]["close"] == []
