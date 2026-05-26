"""Tests for local CSMAR financial statement provider.

Covers:
- Field mapping
- Strict as_of visibility rules
- TTM computation
- Growth calculation
- ROE, gross margin, net margin, operating cashflow quality
- Missing reason tests
"""

from __future__ import annotations

import pytest

from services.data.providers.local_csmar_financial_statement_provider import (
    LocalCSMARFinancialStatementProvider,
    _accper_visibility_date,
    _is_visible,
    _quarter_key,
    is_csmar_financial_enabled,
)


@pytest.fixture(scope="module")
def provider() -> LocalCSMARFinancialStatementProvider:
    return LocalCSMARFinancialStatementProvider()


@pytest.fixture(scope="module")
def is_available() -> bool:
    return is_csmar_financial_enabled()


# ── As-of visibility rules ─────────────────────────────────────

class TestAsOfVisibility:

    def test_annual_report_visible_after_apr30(self):
        """Annual report (12-31) should be visible after next year Apr 30."""
        vis = _accper_visibility_date("2023-12-31")
        assert vis is not None
        assert vis.year == 2024
        assert vis.month == 4
        assert vis.day == 30

    def test_q1_report_visible_after_apr30(self):
        """Q1 report (03-31) should be visible after same year Apr 30."""
        vis = _accper_visibility_date("2023-03-31")
        assert vis is not None
        assert vis.year == 2023
        assert vis.month == 4
        assert vis.day == 30

    def test_half_year_visible_after_aug31(self):
        """Half-year report (06-30) should be visible after same year Aug 31."""
        vis = _accper_visibility_date("2023-06-30")
        assert vis is not None
        assert vis.year == 2023
        assert vis.month == 8
        assert vis.day == 31

    def test_q3_report_visible_after_oct31(self):
        """Q3 report (09-30) should be visible after same year Oct 31."""
        vis = _accper_visibility_date("2023-09-30")
        assert vis is not None
        assert vis.year == 2023
        assert vis.month == 10
        assert vis.day == 31

    def test_initial_period_filtered(self):
        """Accper = YYYY-01-01 should be filtered out (initial period)."""
        vis = _accper_visibility_date("2023-01-01")
        assert vis is None

    def test_annual_not_visible_before_may1(self):
        """Annual report should not be visible before May 1 of next year."""
        assert _is_visible("2023-12-31", "2024-04-29") is False
        assert _is_visible("2023-12-31", "2024-04-30") is True
        assert _is_visible("2023-12-31", "2024-05-01") is True

    def test_q1_not_visible_before_may1(self):
        """Q1 report should not be visible before May 1 of same year."""
        assert _is_visible("2023-03-31", "2023-04-29") is False
        assert _is_visible("2023-03-31", "2023-04-30") is True

    def test_half_year_not_visible_before_sep1(self):
        """Half-year report should not be visible before Sep 1 of same year."""
        assert _is_visible("2023-06-30", "2023-08-30") is False
        assert _is_visible("2023-06-30", "2023-08-31") is True

    def test_q3_not_visible_before_nov1(self):
        """Q3 report should not be visible before Nov 1 of same year."""
        assert _is_visible("2023-09-30", "2023-10-30") is False
        assert _is_visible("2023-09-30", "2023-10-31") is True

    def test_invalid_accper_returns_none(self):
        """Invalid Accper format should return None."""
        assert _accper_visibility_date("invalid") is None
        assert _accper_visibility_date("2023-13-01") is None


# ── Quarter key ────────────────────────────────────────────────

class TestQuarterKey:

    def test_q1(self):
        assert _quarter_key("2023-03-31") == (2023, 0)

    def test_q2(self):
        assert _quarter_key("2023-06-30") == (2023, 1)

    def test_q3(self):
        assert _quarter_key("2023-09-30") == (2023, 2)

    def test_q4(self):
        assert _quarter_key("2023-12-31") == (2023, 3)

    def test_invalid(self):
        assert _quarter_key("2023-01-01") is None
        assert _quarter_key("invalid") is None


# ── Provider integration ──────────────────────────────────────

class TestFinancialProviderIntegration:

    def test_provider_returns_data_for_known_stock(self, provider, is_available):
        """Provider should return data for a well-known stock like 000001.SZ."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("000001.SZ", "2024-06-30")
        assert result.metadata.success is True
        assert isinstance(result.data, dict)

    def test_provider_handles_missing_stock(self, provider, is_available):
        """Provider should handle non-existent stock gracefully."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("999999.SH", "2024-06-30")
        # Should either succeed with empty data or fail gracefully
        assert isinstance(result.data, dict)

    def test_future_date_returns_latest_data(self, provider, is_available):
        """Future date should return the latest available financial data."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("000001.SZ", "2099-12-31")
        # Financial provider returns latest visible records
        # For future dates, this will be the latest available statements
        if result.metadata.success and result.data:
            # Should have some data (debt_ratio, etc.)
            assert isinstance(result.data, dict)

    def test_has_fundamental_fields(self, provider, is_available):
        """Provider should return at least some fundamental fields."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("600519.SH", "2024-06-30")
        if result.metadata.success and result.data:
            # At least one of these should be present
            has_any = any(
                result.data.get(f) is not None
                for f in ["revenue_ttm", "net_profit_ttm", "roe", "gross_margin"]
            )
            assert has_any, f"No fundamental fields found: {result.data.keys()}"

    def test_gross_margin_range(self, provider, is_available):
        """Gross margin should be in reasonable range."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("600519.SH", "2024-06-30")
        if result.metadata.success and result.data.get("gross_margin") is not None:
            gm = result.data["gross_margin"]
            assert -1.0 <= gm <= 1.0, f"gross_margin={gm} out of range"

    def test_roe_range(self, provider, is_available):
        """ROE should be in reasonable range."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("600519.SH", "2024-06-30")
        if result.metadata.success and result.data.get("roe") is not None:
            roe = result.data["roe"]
            assert -1.0 <= roe <= 2.0, f"roe={roe} out of range"

    def test_debt_ratio_range(self, provider, is_available):
        """Debt ratio should be in [0, 1]."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("600519.SH", "2024-06-30")
        if result.metadata.success and result.data.get("debt_ratio") is not None:
            dr = result.data["debt_ratio"]
            assert 0.0 <= dr <= 1.0, f"debt_ratio={dr} out of range"

    def test_boundary_stocks_return_data(self, provider, is_available):
        """Boundary stocks should return data (may have missing fields)."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        # Test a few boundary stocks
        for symbol in ["000002.SZ", "600410.SH", "000711.SZ"]:
            result = provider.get_fundamentals(symbol, "2023-12-31")
            # Should not raise, may have empty data
            assert isinstance(result.data, dict)

    def test_growth_uses_previous_same_period_ttm(self, provider, is_available):
        """Growth should compare current TTM with prior-year same-period TTM."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("000002.SZ", "2021-12-30")
        assert result.metadata.success is True
        assert result.data["revenue_growth"] == pytest.approx(0.165085, abs=0.000001)
        assert result.data["net_profit_growth"] == pytest.approx(-0.05316, abs=0.000001)

    def test_roe_uses_average_parent_equity(self, provider, is_available):
        """ROE should use average parent equity when same-period prior data exists."""
        if not is_available:
            pytest.skip("CSMAR financial statements not available")
        result = provider.get_fundamentals("000002.SZ", "2021-12-30")
        assert result.metadata.success is True
        assert result.data["roe"] == pytest.approx(0.178209, abs=0.000001)
