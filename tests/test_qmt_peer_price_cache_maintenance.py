import pytest

from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight
from services.data.providers.qmt_peer_price_cache_maintenance import (
    QMTPeerPriceCacheMaintenance,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeIndustryProvider:
    """Returns configurable industry members per target symbol."""

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = mapping

    def resolve_industry(self, symbol: str, level: str = "CSMAR_ZX", as_of=None):
        members = self.mapping.get(symbol)
        if members is None:
            return ProviderResult(
                provider="local_csmar",
                dataset="industry_sector",
                symbol=symbol,
                as_of=as_of or "2026-05-20",
                data={},
                raw={},
                metadata=ProviderMetadata(success=False, error=f"Unknown symbol: {symbol}"),
            )
        return ProviderResult(
            provider="local_csmar",
            dataset="industry_sector",
            symbol=symbol,
            as_of=as_of or "2026-05-20",
            data={
                "industry_level": level,
                "industry_code": "C15",
                "industry_name": "Test Industry",
                "industry_members": members,
                "peer_count": len(members),
            },
            raw={},
            metadata=ProviderMetadata(success=True),
        )


class _FakePreflight:
    """Returns configurable preflight results."""

    def __init__(self, missing_close: list[str] | None = None) -> None:
        self.missing_close = missing_close or []
        self.check_calls: list[dict] = []

    def check(self, symbols, as_of=None, threshold=None, include_missing_symbols=False):
        total = len(symbols)
        close_missing = [s for s in symbols if s in set(self.missing_close)]
        close_count = total - len(close_missing)
        result = {
            "checked_count": total,
            "finance_ready": True,
            "price_ready": len(close_missing) == 0,
            "share_capital_ready": True,
            "ready": len(close_missing) == 0,
            "threshold": threshold or 0.8,
            "coverage": {
                "close": close_count / total if total else 0,
                "total_volume": 1.0,
                "net_profit_ttm": 1.0,
                "revenue_ttm": 1.0,
                "bps": 1.0,
                "peer_valuation_complete": close_count / total if total else 0,
            },
            "counts": {
                "close": close_count,
                "total_volume": total,
                "net_profit_ttm": total,
                "revenue_ttm": total,
                "bps": total,
                "peer_valuation_complete": close_count,
            },
            "warnings": ["qmt_peer_price_cache_insufficient"] if close_missing else [],
            "sample_missing": {
                "close": close_missing[:10],
                "total_volume": [],
                "net_profit_ttm": [],
                "revenue_ttm": [],
                "bps": [],
            },
        }
        if include_missing_symbols:
            result["missing_symbols"] = {
                "close": close_missing,
                "total_volume": [],
                "net_profit_ttm": [],
                "revenue_ttm": [],
                "bps": [],
            }
        self.check_calls.append({"symbols": symbols, "include_missing_symbols": include_missing_symbols})
        return result


class _FakeXtData:
    """Records download_history_data calls."""

    def __init__(self) -> None:
        self.download_calls: list[tuple] = []

    def download_history_data(self, symbol, period, start, end, incrementally=True):
        self.download_calls.append((symbol, period, start, end))


# ---------------------------------------------------------------------------
# Tests: build_peer_universe
# ---------------------------------------------------------------------------

def test_build_peer_universe_from_target_symbols():
    provider = _FakeIndustryProvider({
        "600519.SH": ["600519.SH", "000858.SZ", "000568.SZ"],
        "000858.SZ": ["600519.SH", "000858.SZ", "000568.SZ"],
    })
    maintenance = QMTPeerPriceCacheMaintenance(industry_provider=provider)

    result = maintenance.build_peer_universe(target_symbols=["600519.SH", "000858.SZ"])

    assert result["target_symbols"] == ["600519.SH", "000858.SZ"]
    # Same industry, so dedup
    assert result["peer_symbols"] == sorted(["600519.SH", "000858.SZ", "000568.SZ"])
    assert len(result["industries"]) == 2


def test_build_peer_universe_from_peer_symbols_only():
    provider = _FakeIndustryProvider({})
    maintenance = QMTPeerPriceCacheMaintenance(industry_provider=provider)

    result = maintenance.build_peer_universe(peer_symbols=["A.SH", "B.SH", "A.SH"])

    assert result["target_symbols"] == []
    assert result["peer_symbols"] == ["A.SH", "B.SH"]


def test_build_peer_universe_union():
    provider = _FakeIndustryProvider({
        "600519.SH": ["600519.SH", "000858.SZ"],
    })
    maintenance = QMTPeerPriceCacheMaintenance(industry_provider=provider)

    result = maintenance.build_peer_universe(
        target_symbols=["600519.SH"],
        peer_symbols=["000568.SZ", "000001.SZ"],
    )

    assert set(result["peer_symbols"]) == {"000001.SZ", "000568.SZ", "000858.SZ", "600519.SH"}


def test_build_peer_universe_requires_at_least_one():
    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    with pytest.raises(ValueError, match="At least one"):
        maintenance.build_peer_universe()


# ---------------------------------------------------------------------------
# Tests: check_price_cache
# ---------------------------------------------------------------------------

def test_check_price_cache_delegates_to_preflight():
    preflight = _FakePreflight(missing_close=["A.SH"])
    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
        preflight=preflight,
    )

    result = maintenance.check_price_cache(peer_symbols=["A.SH", "B.SH"], threshold=0.9)

    assert result["price_ready"] is False
    assert "A.SH" in result["missing_symbols"]["close"]
    assert preflight.check_calls[0]["include_missing_symbols"] is True


# ---------------------------------------------------------------------------
# Tests: warm_missing_price_cache
# ---------------------------------------------------------------------------

def test_warm_empty_symbols():
    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    result = maintenance.warm_missing_price_cache(missing_symbols=[])
    assert result["attempted"] == 0


def test_warm_exceeds_max_downloads_raises():
    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    symbols = [f"600{i:03d}.SH" for i in range(50)]
    with pytest.raises(ValueError, match="exceeds max_downloads"):
        maintenance.warm_missing_price_cache(
            missing_symbols=symbols, max_downloads=10,
        )


def test_warm_allow_large_permits_download(monkeypatch):
    fake_xtdata = _FakeXtData()
    import services.data.providers.qmt_peer_price_cache_maintenance as mod
    monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(mod, "connect_qmt", lambda: None)

    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    symbols = [f"600{i:03d}.SH" for i in range(50)]
    result = maintenance.warm_missing_price_cache(
        missing_symbols=symbols,
        max_downloads=10,
        allow_large=True,
        as_of="2026-05-20",
        history_days=7,
    )
    assert result["attempted"] == 50
    assert result["succeeded"] == 50
    assert len(fake_xtdata.download_calls) == 50


def test_warm_calls_download_history_data(monkeypatch):
    fake_xtdata = _FakeXtData()
    import services.data.providers.qmt_peer_price_cache_maintenance as mod
    monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(mod, "connect_qmt", lambda: None)

    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    result = maintenance.warm_missing_price_cache(
        missing_symbols=["A.SH", "B.SH"],
        as_of="2026-05-20",
        history_days=30,
        period="1d",
    )

    assert result["attempted"] == 2
    assert result["succeeded"] == 2
    assert result["period"] == "1d"
    assert result["start"] == "20260420"
    assert result["end"] == "20260520"
    assert len(fake_xtdata.download_calls) == 2
    # Verify download_history_data was called with correct args
    assert fake_xtdata.download_calls[0] == ("A.SH", "1d", "20260420", "20260520")


def test_warm_only_targets_missing_close(monkeypatch):
    """warm_missing_price_cache only receives missing close symbols,
    not total_volume or finance missing ones."""
    fake_xtdata = _FakeXtData()
    import services.data.providers.qmt_peer_price_cache_maintenance as mod
    monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(mod, "connect_qmt", lambda: None)

    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    # Only pass symbols missing close, not those missing finance
    result = maintenance.warm_missing_price_cache(
        missing_symbols=["MISSING_CLOSE_1.SH", "MISSING_CLOSE_2.SH"],
        as_of="2026-05-20",
    )
    assert result["attempted"] == 2
    assert len(fake_xtdata.download_calls) == 2
    downloaded_symbols = {call[0] for call in fake_xtdata.download_calls}
    assert downloaded_symbols == {"MISSING_CLOSE_1.SH", "MISSING_CLOSE_2.SH"}


def test_warm_records_errors(monkeypatch):
    def _fail_download(symbol, period, start, end, incrementally=True):
        raise RuntimeError(f"Network error for {symbol}")

    import services.data.providers.qmt_peer_price_cache_maintenance as mod
    fake_xtdata = _FakeXtData()
    fake_xtdata.download_history_data = _fail_download
    monkeypatch.setattr(mod, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(mod, "connect_qmt", lambda: None)

    maintenance = QMTPeerPriceCacheMaintenance(
        industry_provider=_FakeIndustryProvider({}),
    )
    result = maintenance.warm_missing_price_cache(
        missing_symbols=["A.SH", "B.SH"],
        as_of="2026-05-20",
    )
    assert result["attempted"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert len(result["errors"]) == 2


def test_preflight_include_missing_symbols(monkeypatch):
    """Verify preflight include_missing_symbols returns full list."""
    from tests.test_qmt_peer_cache_preflight import _FakeXtData as PreflightFakeXtData

    missing = {"A.SH", "B.SH", "C.SH", "D.SH", "E.SH", "F.SH", "G.SH", "H.SH", "I.SH", "J.SH", "K.SH"}
    fake = PreflightFakeXtData(missing_close=missing)

    import services.data.providers.qmt_peer_cache_preflight as preflight_mod
    monkeypatch.setattr(preflight_mod, "_import_xtdata", lambda: fake)
    monkeypatch.setattr(preflight_mod, "connect_qmt", lambda: None)

    from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader
    loader = QMTPeerValuationLoader()
    preflight = QMTPeerCachePreflight(loader=loader)
    symbols = [chr(ord("A") + i) + ".SH" for i in range(15)]  # A.SH through O.SH

    result = preflight.check(symbols=symbols, threshold=0.5, include_missing_symbols=True)
    assert "missing_symbols" in result
    assert len(result["missing_symbols"]["close"]) == 11
    # sample_missing should still be capped at 10
    assert len(result["sample_missing"]["close"]) == 10

    result_no_flag = preflight.check(symbols=symbols, threshold=0.5, include_missing_symbols=False)
    assert "missing_symbols" not in result_no_flag
