"""Tests for valuation missing_reason fields (P1: 报告层暂无原因披露)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest

from services.data.normalizers.valuation_normalizer import ValuationNormalizer
from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.report.markdown_builder import (
    _MISSING_REASON_CODES,
    _build_industry_valuation_table,
    _build_missing_reason_cell,
    _build_valuation_summary_table,
    build_markdown_report,
)
from services.research.valuation_engine import (
    ValuationService,
    _compute_missing_reasons,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _StubNormalizer:
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
    def fetch_valuation(self, symbol_info: dict) -> ProviderResult:
        return ProviderResult(
            provider="akshare",
            dataset="stock_zh_valuation_comparison_em",
            symbol=symbol_info.get("normalized_symbol", ""),
            as_of=str(date.today()),
            data=[],
            raw=None,
            metadata=ProviderMetadata(success=False, error="no data"),
        )


class _StubCSMARProvider:
    provider = "local_csmar_daily_derived"
    dataset = "latest_non_null_metrics"

    def __init__(self, *, data: dict, raw: dict | None = None, error: str | None = None):
        self._data = data
        self._raw = raw
        self._error = error

    def get_latest_metrics(self, symbol: str) -> ProviderResult:
        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data=self._data,
            raw=self._raw,
            metadata=ProviderMetadata(success=True, error=self._error),
        )


class _StubIndustryService:
    def build(self, asset_data: dict, valuation_data: dict) -> dict:
        return {"fields": {}, "provider_run_log": []}


def _asset_data(**overrides) -> dict:
    base = {
        "symbol": "600519.SH",
        "name": "Test Stock",
        "asset_type": "stock",
        "data_source": "qmt",
        "as_of": str(date.today()),
        "symbol_info": {"qmt_code": "600519.SH"},
        "price_data": {"close": 100},
        "basic_info": {"total_volume": 1000},
        "fundamental_data": {
            "net_profit_ttm": 500,
            "revenue_ttm": 2000,
            "bps": 10,
        },
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. PE missing_reason tests
# ===========================================================================

class TestPEMissingReason:
    def test_market_cap_missing_propagates_to_pe(self):
        vd = {
            "pe_ttm": None,
            "market_cap": None,
            "_close_ref": 100,
            "_total_volume_ref": None,
            "_net_profit_ttm_ref": 500,
        }
        _compute_missing_reasons(vd)
        assert vd["market_cap_missing_reason"] == "missing_total_volume"
        assert vd["pe_ttm_missing_reason"] == "missing_total_volume"

    def test_net_profit_ttm_missing(self):
        vd = {
            "pe_ttm": None,
            "market_cap": 10000,
            "_net_profit_ttm_ref": None,
        }
        _compute_missing_reasons(vd)
        assert vd["pe_ttm_missing_reason"] == "missing_net_profit_ttm"

    def test_loss_making(self):
        vd = {
            "pe_ttm": None,
            "market_cap": 10000,
            "_net_profit_ttm_ref": -100,
        }
        _compute_missing_reasons(vd)
        assert vd["pe_ttm_missing_reason"] == "loss_making_or_invalid_pe"

    def test_pe_has_value_no_reason(self):
        vd = {"pe_ttm": 20.0}
        _compute_missing_reasons(vd)
        assert "pe_ttm_missing_reason" not in vd

    def test_full_pipeline_pe_reason_market_cap_missing(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        asset = _asset_data(
            price_data={"close": 100},
            basic_info={"total_volume": 0},
            fundamental_data={"net_profit_ttm": 500, "revenue_ttm": 2000, "bps": 10},
        )
        result = service.build(asset)
        v = result["data"]["valuation_data"]

        assert v["pe_ttm"] is None
        assert v["pe_ttm_missing_reason"] == "missing_total_volume"
        assert "market_cap_missing_reason" in v


# ===========================================================================
# 2. PB missing_reason tests
# ===========================================================================

class TestPBMissingReason:
    def test_close_missing(self):
        vd = {"pb_mrq": None, "_close_ref": None, "_bps_ref": 5.0}
        _compute_missing_reasons(vd)
        assert vd["pb_mrq_missing_reason"] == "missing_close"

    def test_bps_missing(self):
        vd = {"pb_mrq": None, "_close_ref": 100, "_bps_ref": None}
        _compute_missing_reasons(vd)
        assert vd["pb_mrq_missing_reason"] == "missing_bps"

    def test_bps_invalid(self):
        vd = {"pb_mrq": None, "_close_ref": 100, "_bps_ref": -5}
        _compute_missing_reasons(vd)
        assert vd["pb_mrq_missing_reason"] == "invalid_bps"

    def test_pb_has_value_no_reason(self):
        vd = {"pb_mrq": 2.5}
        _compute_missing_reasons(vd)
        assert "pb_mrq_missing_reason" not in vd

    def test_full_pipeline_pb_reason_bps_missing(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        asset = _asset_data(
            price_data={"close": 100},
            basic_info={"total_volume": 1000},
            fundamental_data={"net_profit_ttm": 500, "revenue_ttm": 2000, "bps": None},
        )
        result = service.build(asset)
        v = result["data"]["valuation_data"]

        assert v["pb_mrq"] is None
        assert v["pb_mrq_missing_reason"] == "missing_bps"


# ===========================================================================
# 3. PS missing_reason tests
# ===========================================================================

class TestPSMissingReason:
    def test_market_cap_missing_propagates_to_ps(self):
        vd = {
            "ps_ttm": None,
            "market_cap": None,
            "_close_ref": 100,
            "_total_volume_ref": None,
            "_revenue_ttm_ref": 2000,
        }
        _compute_missing_reasons(vd)
        assert vd["ps_ttm_missing_reason"] == "missing_total_volume"

    def test_revenue_ttm_missing(self):
        vd = {
            "ps_ttm": None,
            "market_cap": 10000,
            "_revenue_ttm_ref": None,
        }
        _compute_missing_reasons(vd)
        assert vd["ps_ttm_missing_reason"] == "missing_revenue_ttm"

    def test_revenue_ttm_invalid(self):
        vd = {
            "ps_ttm": None,
            "market_cap": 10000,
            "_revenue_ttm_ref": -100,
        }
        _compute_missing_reasons(vd)
        assert vd["ps_ttm_missing_reason"] == "invalid_revenue_ttm"

    def test_ps_has_value_no_reason(self):
        vd = {"ps_ttm": 5.0}
        _compute_missing_reasons(vd)
        assert "ps_ttm_missing_reason" not in vd

    def test_full_pipeline_ps_reason_market_cap_missing(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=ValuationNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        asset = _asset_data(
            price_data={"close": 100},
            basic_info={"total_volume": 0},
            fundamental_data={"net_profit_ttm": 500, "revenue_ttm": 2000, "bps": 10},
        )
        result = service.build(asset)
        v = result["data"]["valuation_data"]

        assert v["ps_ttm"] is None
        assert v["ps_ttm_missing_reason"] == "missing_total_volume"


# ===========================================================================
# 4. dividend_yield missing_reason tests
# ===========================================================================

class TestDividendYieldMissingReason:
    def test_csmar_disabled(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        result = service.build(_asset_data())
        v = result["data"]["valuation_data"]

        assert v.get("dividend_yield") is None
        assert v["dividend_yield_missing_reason"] == "provider_disabled"

    def test_csmar_no_data_for_symbol(self, monkeypatch):
        td = tempfile.mkdtemp(prefix="test_dy_")
        try:
            db = os.path.join(td, "csmar.sqlite")
            conn = sqlite3.connect(db)
            conn.execute("""
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
            conn.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            conn.execute("INSERT INTO metadata VALUES ('build_date', ?)", (date.today().isoformat(),))
            conn.commit()
            conn.close()

            monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
            monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)
            monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
            monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

            service = ValuationService(
                normalizer=_StubNormalizer(),
                akshare_provider=_StubAkshareProvider(),
                industry_service=_StubIndustryService(),
            )
            result = service.build(_asset_data())
            v = result["data"]["valuation_data"]

            assert v.get("dividend_yield") is None
            assert v["dividend_yield_missing_reason"] == "missing_dividend_yield_source"
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_csmar_provides_dividend_yield(self, monkeypatch):
        td = tempfile.mkdtemp(prefix="test_dy_ok_")
        try:
            db = os.path.join(td, "csmar.sqlite")
            conn = sqlite3.connect(db)
            conn.execute("""
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
            conn.execute(
                "INSERT INTO latest_non_null_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("600519.SH", "600519", "Test",
                 today, 0.025, None, None, None, None, None, None,
                 None, None, None, None, None, None, None, None, None, None, None, None),
            )
            conn.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            conn.execute("INSERT INTO metadata VALUES ('build_date', ?)", (today,))
            conn.commit()
            conn.close()

            monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
            monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)
            monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
            monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

            service = ValuationService(
                normalizer=_StubNormalizer(),
                akshare_provider=_StubAkshareProvider(),
                industry_service=_StubIndustryService(),
            )
            result = service.build(_asset_data())
            v = result["data"]["valuation_data"]

            assert v["dividend_yield"] == pytest.approx(0.025)
            assert "dividend_yield_missing_reason" not in v
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_stale_csmar_dividend_yield_reason(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        old_date = (date.today() - timedelta(days=400)).isoformat()
        warning = (
            f"dividend_yield is 400 days old (limit 370), last updated {old_date}"
        )
        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
            csmar_provider=_StubCSMARProvider(
                data={
                    "symbol": "600519.SH",
                    "source": "local_csmar_daily_derived",
                    "warnings": [warning],
                },
                raw={"symbol": "600519.SH"},
                error=warning,
            ),
        )
        result = service.build(_asset_data())
        v = result["data"]["valuation_data"]

        assert v.get("dividend_yield") is None
        assert (
            v["dividend_yield_missing_reason"]
            == "stale_local_csmar_daily_derived"
        )


# ===========================================================================
# 5. Industry percentile missing_reason tests
# ===========================================================================

class TestIndustryPercentileMissingReason:
    def test_preflight_failed(self):
        vd = {
            "industry_pe_percentile": None,
            "industry_pb_percentile": None,
            "industry_ps_percentile": None,
            "industry_cache_preflight": {"ready": False},
            "industry_valuation_warnings": [],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_pe_percentile_missing_reason"] == "peer_cache_preflight_failed"
        assert vd["industry_pb_percentile_missing_reason"] == "peer_cache_preflight_failed"
        assert vd["industry_ps_percentile_missing_reason"] == "peer_cache_preflight_failed"
        assert vd["industry_percentile_missing_reason"] == "peer_cache_preflight_failed"

    def test_missing_peer_close(self):
        vd = {
            "industry_pe_percentile": None,
            "industry_valuation_warnings": ["qmt_peer_price_cache_insufficient"],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_pe_percentile_missing_reason"] == "missing_peer_close"

    def test_missing_peer_finance(self):
        vd = {
            "industry_pb_percentile": None,
            "industry_valuation_warnings": ["qmt_finance_cache_insufficient_for_peer_valuation"],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_pb_percentile_missing_reason"] == "missing_peer_finance"

    def test_missing_peer_share_capital(self):
        vd = {
            "industry_ps_percentile": None,
            "industry_valuation_warnings": ["qmt_peer_share_capital_insufficient"],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_ps_percentile_missing_reason"] == "missing_peer_share_capital"

    def test_insufficient_peer_samples(self):
        vd = {
            "industry_pe_percentile": None,
            "industry_valuation_warnings": ["Industry PE valid peer count 5 is below 20."],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_pe_percentile_missing_reason"] == "insufficient_peer_samples"

    def test_target_not_in_peer_inputs(self):
        vd = {
            "industry_pe_percentile": None,
            "industry_valuation_warnings": ["Target symbol 600001.SH is not in valid peer inputs."],
        }
        _compute_missing_reasons(vd)
        assert vd["industry_pe_percentile_missing_reason"] == "target_not_in_peer_inputs"

    def test_industry_has_value_no_reason(self):
        vd = {
            "industry_pe_percentile": 0.30,
            "industry_pb_percentile": 0.40,
            "industry_ps_percentile": 0.50,
        }
        _compute_missing_reasons(vd)
        assert "industry_pe_percentile_missing_reason" not in vd
        assert "industry_percentile_missing_reason" not in vd

    def test_aggregate_picks_up_any_individual_reason(self):
        vd = {
            "industry_pe_percentile": 0.30,  # has value
            "industry_pb_percentile": None,
            "industry_ps_percentile": None,
            "industry_valuation_warnings": ["qmt_finance_cache_insufficient_for_peer_valuation"],
        }
        _compute_missing_reasons(vd)
        assert "industry_pe_percentile_missing_reason" not in vd
        assert vd["industry_pb_percentile_missing_reason"] == "missing_peer_finance"
        assert vd["industry_percentile_missing_reason"] == "missing_peer_finance"

    def test_no_industry_fields_no_reason(self):
        vd = {}
        _compute_missing_reasons(vd)
        assert "industry_percentile_missing_reason" not in vd


# ===========================================================================
# 6. market_cap missing_reason tests
# ===========================================================================

class TestMarketCapMissingReason:
    def test_missing_close(self):
        vd = {
            "market_cap": None,
            "_close_ref": None,
            "_total_volume_ref": 1000,
        }
        _compute_missing_reasons(vd)
        assert vd["market_cap_missing_reason"] == "missing_close"

    def test_missing_total_volume(self):
        vd = {
            "market_cap": None,
            "_close_ref": 100,
            "_total_volume_ref": None,
        }
        _compute_missing_reasons(vd)
        assert vd["market_cap_missing_reason"] == "missing_total_volume"

    def test_fallback_unavailable(self):
        vd = {
            "market_cap": None,
            "_close_ref": 100,
            "_total_volume_ref": 0,
        }
        _compute_missing_reasons(vd)
        assert vd["market_cap_missing_reason"] == "missing_total_volume"

    def test_market_cap_has_value_no_reason(self):
        vd = {"market_cap": 100000}
        _compute_missing_reasons(vd)
        assert "market_cap_missing_reason" not in vd


# ===========================================================================
# 7. Historical percentile missing_reason tests
# ===========================================================================

class TestHistoricalPercentileMissingReason:
    def test_missing_current_multiple_propagates_to_percentile(self):
        vd = {
            "pe_ttm": None,
            "pe_percentile": None,
            "pe_ttm_missing_reason": "missing_net_profit_ttm",
        }
        _compute_missing_reasons(vd)
        assert vd["pe_percentile_missing_reason"] == "missing_net_profit_ttm"

    def test_invalid_current_multiple_for_percentile(self):
        vd = {
            "pe_ttm": -3.0,
            "pe_percentile": None,
            "pb_mrq": 0,
            "pb_percentile": None,
            "ps_ttm": -1.0,
            "ps_percentile": None,
        }
        _compute_missing_reasons(vd)
        assert vd["pe_percentile_missing_reason"] == "loss_making_or_invalid_pe"
        assert vd["pb_percentile_missing_reason"] == "invalid_bps"
        assert vd["ps_percentile_missing_reason"] == "invalid_revenue_ttm"

    def test_insufficient_history_warning_for_percentile(self):
        vd = {
            "pe_ttm": 20.0,
            "pe_percentile": None,
            "percentile_warnings": ["csmar_monthly_history_insufficient_pe_samples: 5 < 12"],
        }
        _compute_missing_reasons(vd)
        assert vd["pe_percentile_missing_reason"] == "insufficient_history_samples"

    def test_percentile_has_value_no_reason(self):
        vd = {"pe_ttm": 20.0, "pe_percentile": 0.42}
        _compute_missing_reasons(vd)
        assert "pe_percentile_missing_reason" not in vd


# ===========================================================================
# 8. Report layer display tests
# ===========================================================================

class TestReportLayerDisplay:
    def test_field_with_value_no_reason_shown(self):
        cell = _build_missing_reason_cell(
            20.5, {}, "pe_ttm_missing_reason", lambda v: f"{v:.1f}"
        )
        assert cell == "20.5"
        assert "原因" not in cell

    def test_field_none_with_reason_shows_chinese(self):
        vd = {"pe_ttm_missing_reason": "loss_making_or_invalid_pe"}
        cell = _build_missing_reason_cell(None, vd, "pe_ttm_missing_reason", lambda v: "N/A")
        assert "暂无" in cell
        assert "亏损或PE无效" in cell

    def test_field_none_without_reason_shows_default(self):
        cell = _build_missing_reason_cell(None, {}, "pe_ttm_missing_reason", lambda v: "暂无")
        assert cell == "暂无"

    def test_valuation_summary_table_shows_reasons(self):
        vd = {
            "pe_ttm": None,
            "pb_mrq": 2.5,
            "ps_ttm": None,
            "market_cap": None,
            "pe_percentile": None,
            "pb_percentile": 0.4,
            "ps_percentile": None,
            "dividend_yield": None,
            "valuation_label": "unavailable",
            "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
            "market_cap_missing_reason": "missing_total_volume",
            "ps_ttm_missing_reason": "missing_total_volume",
            "pe_percentile_missing_reason": "insufficient_history_samples",
            "ps_percentile_missing_reason": "insufficient_history_samples",
            "dividend_yield_missing_reason": "provider_disabled",
        }
        table = _build_valuation_summary_table(vd)
        assert "亏损或PE无效" in table
        assert "股本数据缺失" in table
        assert "历史样本不足" in table
        assert "数据源未启用" in table
        # PB has value, should not show reason
        assert "2.5" in table

    def test_industry_table_shows_reasons(self):
        vd = {
            "industry_name": "SW1食品饮料",
            "industry_level": "SW1",
            "industry_peer_count": 35,
            "industry_valid_peer_count": 5,
            "industry_valid_peer_count_pe": 5,
            "industry_valid_peer_count_pb": 5,
            "industry_valid_peer_count_ps": 5,
            "industry_pe_percentile": None,
            "industry_pb_percentile": None,
            "industry_ps_percentile": None,
            "industry_valuation_label": "industry_insufficient_peers",
            "industry_valuation_source": "local_csmar+qmt_financial+qmt_price",
            "industry_pe_percentile_missing_reason": "insufficient_peer_samples",
            "industry_pb_percentile_missing_reason": "insufficient_peer_samples",
            "industry_ps_percentile_missing_reason": "insufficient_peer_samples",
        }
        table = _build_industry_valuation_table(vd)
        assert "行业有效样本不足" in table
        assert "SW1食品饮料" in table

    def test_all_reason_codes_have_chinese_mapping(self):
        all_codes = [
            "missing_close",
            "missing_total_volume",
            "missing_market_cap",
            "share_capital_fallback_unavailable",
            "missing_net_profit_ttm",
            "loss_making_or_invalid_pe",
            "missing_bps",
            "invalid_bps",
            "missing_revenue_ttm",
            "invalid_revenue_ttm",
            "provider_disabled",
            "missing_dividend_yield_source",
            "stale_local_csmar_daily_derived",
            "peer_cache_preflight_failed",
            "missing_peer_close",
            "missing_peer_finance",
            "missing_peer_share_capital",
            "insufficient_peer_samples",
            "insufficient_history_samples",
            "target_not_in_peer_inputs",
            "field_not_supported",
            "provider_unavailable",
            "unknown",
        ]
        for code in all_codes:
            assert code in _MISSING_REASON_CODES, f"Missing mapping for {code}"

    def test_markdown_report_contains_missing_reason(self):
        result = {
            "symbol": "600519.SH",
            "name": "测试标的",
            "asset_type": "stock",
            "as_of": "2026-05-21",
            "data_source": "qmt",
            "score": 50,
            "rating": "C",
            "action": "观察",
            "max_position": "5%",
            "final_opinion": "测试观点",
            "score_breakdown": {},
            "price_data": {"data_vendor": "qmt"},
            "valuation_data": {
                "pe_ttm": None,
                "pb_mrq": None,
                "ps_ttm": None,
                "market_cap": None,
                "pe_percentile": None,
                "pb_percentile": None,
                "ps_percentile": None,
                "dividend_yield": None,
                "valuation_label": "unavailable",
                "pe_ttm_missing_reason": "missing_total_volume",
                "pb_mrq_missing_reason": "missing_bps",
                "ps_ttm_missing_reason": "missing_total_volume",
                "market_cap_missing_reason": "missing_total_volume",
                "dividend_yield_missing_reason": "provider_disabled",
            },
            "data_quality": {
                "overall_confidence": 0.3,
                "has_placeholder": False,
                "blocking_issues": [],
                "warnings": [],
                "field_quality": {},
            },
            "evidence_bundle": {"items": []},
            "decision_guard": {"enabled": False},
        }
        md = build_markdown_report(result)
        assert "股本数据缺失" in md
        assert "每股净资产缺失" in md
        assert "数据源未启用" in md

    def test_markdown_report_field_with_value_no_reason_in_report(self):
        result = {
            "symbol": "600519.SH",
            "name": "测试标的",
            "asset_type": "stock",
            "as_of": "2026-05-21",
            "data_source": "qmt",
            "score": 80,
            "rating": "B+",
            "action": "买入",
            "max_position": "10%",
            "final_opinion": "测试",
            "score_breakdown": {},
            "price_data": {"data_vendor": "qmt"},
            "valuation_data": {
                "pe_ttm": 20.0,
                "pb_mrq": 5.0,
                "ps_ttm": 8.0,
                "market_cap": 1e12,
                "pe_percentile": 0.42,
                "pb_percentile": 0.51,
                "ps_percentile": 0.47,
                "dividend_yield": 0.02,
                "valuation_label": "reasonable",
            },
            "data_quality": {
                "overall_confidence": 0.85,
                "has_placeholder": False,
                "blocking_issues": [],
                "warnings": [],
                "field_quality": {},
            },
            "evidence_bundle": {"items": []},
            "decision_guard": {"enabled": False},
        }
        table = _build_valuation_summary_table(result["valuation_data"])
        assert "原因" not in table


# ===========================================================================
# 8. Integration: internal fields are cleaned up
# ===========================================================================

class TestInternalFieldsCleanup:
    def test_placeholder_path_preserves_missing_reasons(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=_StubNormalizer(
                {
                    "pe_ttm": None,
                    "pb_mrq": None,
                    "ps_ttm": None,
                    "market_cap": None,
                    "pe_percentile": None,
                    "pb_percentile": None,
                    "ps_percentile": None,
                    "valuation_label": "unavailable",
                }
            ),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        result = service.build(
            _asset_data(
                price_data={"close": 100},
                basic_info={"total_volume": 0},
                fundamental_data={
                    "net_profit_ttm": 500,
                    "revenue_ttm": 2000,
                    "bps": None,
                },
            )
        )
        v = result["data"]["valuation_data"]

        assert v["market_cap_missing_reason"] == "missing_total_volume"
        assert v["pe_ttm_missing_reason"] == "missing_total_volume"
        assert v["pb_mrq_missing_reason"] == "missing_bps"
        assert v["ps_ttm_missing_reason"] == "missing_total_volume"
        assert v["ps_percentile_missing_reason"] == "missing_total_volume"
        assert "dividend_yield_missing_reason" not in v
        for key in v:
            assert not key.startswith("_"), f"Internal field {key} leaked into output"

    def test_internal_ref_fields_not_in_output(self, monkeypatch):
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

        service = ValuationService(
            normalizer=_StubNormalizer(),
            akshare_provider=_StubAkshareProvider(),
            industry_service=_StubIndustryService(),
        )
        result = service.build(_asset_data())
        v = result["data"]["valuation_data"]

        for key in v:
            assert not key.startswith("_"), f"Internal field {key} leaked into output"

    def test_csmar_flag_not_in_output(self, monkeypatch):
        td = tempfile.mkdtemp(prefix="test_cleanup_")
        try:
            db = os.path.join(td, "csmar.sqlite")
            conn = sqlite3.connect(db)
            conn.execute("""
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
            conn.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            conn.execute("INSERT INTO metadata VALUES ('build_date', ?)", (date.today().isoformat(),))
            conn.commit()
            conn.close()

            monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "true")
            monkeypatch.setenv("CSMAR_DAILY_DERIVED_DB", db)
            monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
            monkeypatch.setenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "disabled")

            service = ValuationService(
                normalizer=_StubNormalizer(),
                akshare_provider=_StubAkshareProvider(),
                industry_service=_StubIndustryService(),
            )
            result = service.build(_asset_data())
            v = result["data"]["valuation_data"]

            for key in v:
                assert not key.startswith("_"), f"Internal field {key} leaked into output"
            assert "_csmar_enabled" not in v
            assert "_csmar_no_data" not in v
        finally:
            shutil.rmtree(td, ignore_errors=True)


# ===========================================================================
# 9. Existing success paths not broken
# ===========================================================================

class TestExistingSuccessPathsNotBroken:
    def test_all_fields_present_no_reasons_added(self):
        vd = {
            "pe_ttm": 20.0,
            "pb_mrq": 5.0,
            "ps_ttm": 8.0,
            "market_cap": 1e12,
            "dividend_yield": 0.02,
            "industry_pe_percentile": 0.30,
            "industry_pb_percentile": 0.40,
            "industry_ps_percentile": 0.50,
        }
        _compute_missing_reasons(vd)
        assert "pe_ttm_missing_reason" not in vd
        assert "pb_mrq_missing_reason" not in vd
        assert "ps_ttm_missing_reason" not in vd
        assert "market_cap_missing_reason" not in vd
        assert "dividend_yield_missing_reason" not in vd
        assert "industry_percentile_missing_reason" not in vd

    def test_partial_fields_some_reasons(self):
        vd = {
            "pe_ttm": 20.0,
            "pb_mrq": None,
            "ps_ttm": 8.0,
            "market_cap": 1e12,
            "dividend_yield": None,
            "_close_ref": 100,
            "_bps_ref": None,
            "_csmar_enabled": True,
            "_csmar_no_data": True,
        }
        _compute_missing_reasons(vd)
        assert "pe_ttm_missing_reason" not in vd
        assert "ps_ttm_missing_reason" not in vd
        assert vd["pb_mrq_missing_reason"] == "missing_bps"
        assert vd["dividend_yield_missing_reason"] == "missing_dividend_yield_source"
