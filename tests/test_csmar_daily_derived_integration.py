"""Integration tests for CSMAR daily-derived fallback in valuation pipeline."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest

from services.data.normalizers.valuation_normalizer import (
    ValuationNormalizer,
    _compute_percentile_from_values,
)
from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.data.providers.local_csmar_daily_derived_provider import (
    LocalCSMARDailyDerivedProvider,
)
from services.research.valuation_engine import ValuationService

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _StubNormalizer:
    """Normalizer that returns a configurable valuation dict."""

    def __init__(self, data: dict | None = None):
        self._data = data or {
            "pe_ttm": 10.0,
            "pb_mrq": 2.0,
            "ps_ttm": 3.0,
            "market_cap": 1000.0,
            "valuation_label": "derived_no_percentile",
        }

    def derive_from_qmt(self, asset_data: dict) -> dict:
        return dict(self._data)

    def normalize_akshare(self, provider_result: dict) -> dict:
        return {}


class _StubAkshareProvider:
    """AKShare provider that returns no data."""

    def fetch_valuation(self, symbol_info: dict) -> ProviderResult:
        return ProviderResult(
            provider="akshare",
            dataset="stock_zh_valuation_comparison_em",
            symbol=symbol_info.get("normalized_symbol", ""),
            as_of=str(date.today()),
            data=[],
            raw=None,
            metadata=ProviderMetadata(
                success=False,
                error="no data",
            ),
        )


class _StubIndustryService:
    """Industry service that returns empty."""

    def build(self, asset_data: dict, valuation_data: dict) -> dict:
        return {"fields": {}, "provider_run_log": []}


class _CSMARSpy:
    """Spy wrapper around LocalCSMARDailyDerivedProvider to track calls."""

    provider = "local_csmar_daily_derived"

    def __init__(self, provider: LocalCSMARDailyDerivedProvider):
        self._provider = provider
        self.latest_calls: list[str] = []
        self.monthly_calls: list[tuple] = []

    def get_latest_metrics(self, symbol: str) -> ProviderResult:
        self.latest_calls.append(symbol)
        return self._provider.get_latest_metrics(symbol)

    def get_monthly_history(self, symbols, metrics, start_date=None, end_date=None):
        self.monthly_calls.append((list(symbols), list(metrics)))
        return self._provider.get_monthly_history(symbols, metrics, start_date, end_date)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_dir() -> str:
    return tempfile.mkdtemp(prefix="csmar_integ_")


def _create_csmar_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE latest_non_null_metrics (
            symbol TEXT, stkcd TEXT, short_name TEXT,
            dividend_yield_date TEXT, dividend_yield REAL,
            pe_date TEXT, pe REAL,
            pb_date TEXT, pb REAL,
            pcf_date TEXT, pcf REAL,
            ps_date TEXT, ps REAL,
            turnover_date TEXT, turnover REAL,
            circulated_market_value_date TEXT, circulated_market_value REAL,
            change_ratio_date TEXT, change_ratio REAL,
            amount_date TEXT, amount INTEGER,
            liquidility_date TEXT, liquidility REAL
        )
    """)

    today = date.today().isoformat()
    recent = (date.today() - timedelta(days=10)).isoformat()

    # Stock with all fields fresh
    cur.execute(
        "INSERT INTO latest_non_null_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("600519.SH", "600519", "贵州茅台",
         recent, 0.015, today, 25.0, today, 8.0, today, 15.0, today, 12.0,
         today, 0.003, today, 2e9, today, 0.01, today, 5e8, today, 0.0001),
    )

    # Stock with only dividend_yield
    cur.execute(
        "INSERT INTO latest_non_null_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("000002.SZ", "000002", "万科A",
         recent, 0.03, None, None, None, None, None, None, None, None,
         None, None, None, None, None, None, None, None, None, None),
    )

    # monthly_snapshots
    cur.execute("""
        CREATE TABLE monthly_snapshots (
            symbol TEXT, stkcd TEXT, trading_date TEXT, period TEXT,
            short_name TEXT, dividend_yield REAL, pe REAL, pb REAL,
            pcf REAL, ps REAL, turnover REAL, circulated_market_value REAL,
            change_ratio REAL, amount INTEGER, liquidility REAL, source_file TEXT
        )
    """)

    base = date(2024, 1, 31)
    for i in range(36):
        d = base + timedelta(days=30 * i)
        cur.execute(
            "INSERT INTO monthly_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("600519.SH", "600519", d.isoformat(), d.strftime("%Y-%m"),
             "贵州茅台", 0.01 + i * 0.001,
             20.0 + i * 0.5, 6.0 + i * 0.1, 10.0 + i * 0.3, 8.0 + i * 0.2,
             0.003, 2e9, 0.01, 5e8, 0.0001, "STK_MKT_DALYR.csv"),
        )

    cur.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
    cur.execute("INSERT INTO metadata VALUES ('build_date', ?)", (today,))
    conn.commit()
    conn.close()


def _asset_data(symbol: str = "600519.SH") -> dict:
    return {
        "symbol": symbol,
        "name": "Test Stock",
        "asset_type": "stock",
        "data_source": "qmt",
        "as_of": str(date.today()),
        "symbol_info": {"qmt_code": symbol},
        "price_data": {"close": 10},
        "basic_info": {"total_volume": 100},
        "fundamental_data": {
            "net_profit_ttm": 100,
            "revenue_ttm": 300,
            "bps": 5,
        },
    }


# ---------------------------------------------------------------------------
# Test: existing data not overwritten
# ---------------------------------------------------------------------------

def test_csmar_overwrites_pe_ttm_but_preserves_pb():
    """CSMAR overrides pe_ttm (QMT cross-table mismatch risk), preserves pb_mrq."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer({
                "pe_ttm": 15.0,  # QMT provides this
                "pb_mrq": 3.0,   # QMT provides this
                "ps_ttm": None,  # QMT missing
                "market_cap": 1000.0,
                "valuation_label": "derived_no_percentile",
            }),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("600519.SH"))
        v = result["data"]["valuation_data"]

        # pe_ttm: CSMAR overrides QMT (cross-table report_period mismatch risk)
        assert v["pe_ttm"] == pytest.approx(25.0)
        assert v.get("pe_ttm_source") == "local_csmar_daily_derived"
        # pb_mrq: CSMAR does not overwrite (no cross-table risk)
        assert v["pb_mrq"] == 3.0
        # CSMAR should fill ps_ttm (was None)
        assert v["ps_ttm"] == pytest.approx(12.0)
        assert v.get("ps_ttm_source") == "local_csmar_daily_derived"
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: dividend_yield fallback
# ---------------------------------------------------------------------------

def test_dividend_yield_filled_from_csmar_when_missing():
    """dividend_yield should come from CSMAR when QMT doesn't provide it."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("600519.SH"))
        v = result["data"]["valuation_data"]

        assert v["dividend_yield"] == pytest.approx(0.015)
        assert v.get("dividend_yield_source") == "local_csmar_daily_derived"
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: pe/pb/ps fallback with source tracking
# ---------------------------------------------------------------------------

def test_pe_pb_ps_filled_from_csmar_with_source():
    """pe/pb/ps from CSMAR should have source tracking."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer({
                "pe_ttm": None,
                "pb_mrq": None,
                "ps_ttm": None,
                "market_cap": 1000.0,
            }),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("600519.SH"))
        v = result["data"]["valuation_data"]

        assert v["pe_ttm"] == pytest.approx(25.0)
        assert v["pb_mrq"] == pytest.approx(8.0)
        assert v["ps_ttm"] == pytest.approx(12.0)
        assert v.get("pe_ttm_source") == "local_csmar_daily_derived"
        assert v.get("pb_mrq_source") == "local_csmar_daily_derived"
        assert v.get("ps_ttm_source") == "local_csmar_daily_derived"
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: CSMAR provider failure is non-blocking
# ---------------------------------------------------------------------------

def test_csmar_failure_does_not_crash_pipeline():
    """If CSMAR DB is missing, the pipeline should still complete."""
    csmar_provider = LocalCSMARDailyDerivedProvider(db_path="/nonexistent/path.sqlite")

    service = ValuationService(
        normalizer=_StubNormalizer(),
        akshare_provider=_StubAkshareProvider(),
        industry_service=_StubIndustryService(),
        csmar_provider=csmar_provider,
    )

    result = service.build(_asset_data("600519.SH"))
    v = result["data"]["valuation_data"]

    # Pipeline should complete with QMT-derived data
    assert v["pe_ttm"] == 10.0
    assert v["pb_mrq"] == 2.0
    # No CSMAR source should be recorded
    assert "csmar" not in str(v.get("pe_ttm_source", ""))


# ---------------------------------------------------------------------------
# Test: CSMAR logged in provider_run_log
# ---------------------------------------------------------------------------

def test_csmar_appears_in_provider_run_log():
    """CSMAR fallback should be recorded in provider_run_log."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer({
                "pe_ttm": None, "pb_mrq": None, "ps_ttm": None, "market_cap": 1000.0,
            }),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("600519.SH"))
        log = result["provider_run_log"]

        csmar_entries = [e for e in log if e["provider"] == "local_csmar_daily_derived"]
        assert len(csmar_entries) >= 1
        assert csmar_entries[0]["symbol"] == "600519.SH"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_csmar_run_log_success_when_only_dividend_yield_applied():
    """CSMAR run log should not require PE to mark usable fallback data."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("000002.SZ"))
        v = result["data"]["valuation_data"]
        log = result["provider_run_log"]

        assert v["dividend_yield"] == pytest.approx(0.03)
        csmar_entries = [e for e in log if e["provider"] == "local_csmar_daily_derived"]
        assert csmar_entries[0]["status"] == "success"
        assert csmar_entries[0]["fields_available"] == ["dividend_yield"]
        assert csmar_entries[0]["fields_applied"] == ["dividend_yield"]
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: calculation_method includes CSMAR
# ---------------------------------------------------------------------------

def test_calculation_method_mentions_csmar():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer({
                "pe_ttm": None, "pb_mrq": None, "ps_ttm": None, "market_cap": 1000.0,
            }),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("600519.SH"))
        meta = result["source_metadata"]["valuation_data"]

        assert "csmar_daily_derived" in meta.get("calculation_method", "")
        assert "csmar" in meta.get("source", "")
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: percentile fallback from CSMAR monthly history
# ---------------------------------------------------------------------------

def test_csmar_percentile_fallback_fills_pe_percentile(monkeypatch):
    """When QMT/AKShare history is insufficient, CSMAR monthly history
    should provide PE/PB/PS percentiles."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)

        normalizer = ValuationNormalizer()

        # Build asset_data with no history_close (forces percentile fallback)
        asset_data = {
            "symbol": "600519.SH",
            "as_of": str(date.today()),
            "price_data": {"close": 100},
            "basic_info": {"total_volume": 1000},
            "fundamental_data": {
                "net_profit_ttm": 2500,
                "revenue_ttm": 8333,
                "bps": 12.5,
            },
        }

        result = normalizer.derive_from_qmt(asset_data)

        # Without history_close, percentiles should come from CSMAR fallback
        assert result.get("pe_percentile") is not None
        assert result.get("pb_percentile") is not None
        assert "csmar_monthly_history" in result.get("calculation_method", "")
        assert result.get("percentile_source") == "local_csmar_daily_derived"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_csmar_percentile_fallback_fills_missing_fields_individually(monkeypatch):
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)

        normalizer = ValuationNormalizer()
        result = {
            "pe_percentile": 0.42,
            "pb_percentile": None,
            "ps_percentile": None,
            "calculation_method": "derived_from_qmt_price_share_capital_and_financials",
        }

        normalizer._try_csmar_percentile_fallback(
            result=result,
            symbol="600519.SH",
            current_pe=25.0,
            current_pb=8.0,
            current_ps=12.0,
        )

        assert result["pe_percentile"] == pytest.approx(0.42)
        assert result["pb_percentile"] is not None
        assert result["ps_percentile"] is not None
        assert result["percentile_fields_from_csmar"] == ["pb_percentile", "ps_percentile"]
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_csmar_percentile_fallback_is_recorded_in_run_log(monkeypatch):
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=LocalCSMARDailyDerivedProvider(db_path=db),
        )

        result = service.build(_asset_data("600519.SH"))
        csmar_monthly_entries = [
            entry
            for entry in result["provider_run_log"]
            if entry["provider"] == "local_csmar_daily_derived"
            and entry["dataset"] == "monthly_snapshots"
        ]

        assert csmar_monthly_entries
        assert csmar_monthly_entries[0]["status"] == "success"
        assert csmar_monthly_entries[0]["fields_applied"]
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: percentile_midrank with CSMAR values
# ---------------------------------------------------------------------------

def test_compute_percentile_from_values():
    assert _compute_percentile_from_values(10, [5, 10, 15]) == pytest.approx(2 / 3)
    assert _compute_percentile_from_values(1, [5, 10, 15]) == pytest.approx(0.0)
    assert _compute_percentile_from_values(20, [5, 10, 15]) == pytest.approx(1.0)
    assert _compute_percentile_from_values(10, []) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test: symbol not in CSMAR -> pipeline continues
# ---------------------------------------------------------------------------

def test_symbol_not_in_csmar_pipeline_continues():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "csmar.sqlite")
        _create_csmar_db(db)
        csmar_provider = _CSMARSpy(LocalCSMARDailyDerivedProvider(db_path=db))

        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=csmar_provider,
        )

        result = service.build(_asset_data("999999.SH"))
        v = result["data"]["valuation_data"]

        # Pipeline should complete normally
        assert v["pe_ttm"] == 10.0
        # CSMAR should have been called but produced no data
        assert csmar_provider.latest_calls == ["999999.SH"]
        assert "csmar" not in str(v.get("dividend_yield_source", ""))
    finally:
        shutil.rmtree(td, ignore_errors=True)
