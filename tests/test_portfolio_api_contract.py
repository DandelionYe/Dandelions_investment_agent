"""Contract tests for portfolio API — static analysis of router/schema.

Verifies RBAC, endpoint registration, and schema constraints without booting FastAPI.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.portfolio import PortfolioAnalyzeRequest

ROUTER_PATH = Path(__file__).resolve().parents[1] / "apps" / "api" / "routers" / "portfolio.py"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "apps" / "api" / "schemas" / "portfolio.py"
MAIN_PATH = Path(__file__).resolve().parents[1] / "apps" / "api" / "main.py"
ANALYZER_PATH = Path(__file__).resolve().parents[1] / "services" / "portfolio" / "portfolio_analyzer.py"


class TestPortfolioRouterContract:

    def test_router_uses_auth(self):
        """Router must use get_current_user dependency."""
        src = ROUTER_PATH.read_text(encoding="utf-8")
        assert "get_current_user" in src

    def test_router_uses_rbac(self):
        """Router must use RBAC helpers."""
        src = ROUTER_PATH.read_text(encoding="utf-8")
        assert "scope_username" in src
        assert "is_admin" in src

    def test_router_endpoint_exists(self):
        """POST /api/v1/portfolio/analyze endpoint must exist."""
        src = ROUTER_PATH.read_text(encoding="utf-8")
        assert "/api/v1/portfolio/analyze" in src

    def test_router_registered_in_main(self):
        """Portfolio router must be registered in main.py."""
        src = MAIN_PATH.read_text(encoding="utf-8")
        assert "portfolio" in src
        assert "include_router" in src

    def test_router_loads_from_watchlist(self):
        """Router must support loading positions from watchlist."""
        src = ROUTER_PATH.read_text(encoding="utf-8")
        assert "watchlist_folder_id" in src or "use_watchlist_all" in src

    def test_router_loads_research_results(self):
        """Router must load research results for symbols."""
        src = ROUTER_PATH.read_text(encoding="utf-8")
        assert "research" in src.lower()
        assert "result" in src.lower() or "json" in src.lower()


class TestPortfolioSchemaContract:

    def test_request_has_risk_profile(self):
        """Request model must have risk_profile field."""
        src = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "risk_profile" in src

    def test_request_has_constraints(self):
        """Request model must have weight constraint fields."""
        src = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "max_single_weight" in src
        assert "max_industry_weight" in src
        assert "min_cash_weight" in src

    def test_response_has_holdings(self):
        """Response model must have holdings list."""
        src = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "holdings" in src

    def test_response_has_exposures(self):
        """Response model must have industry and asset type exposures."""
        src = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "industry_exposure" in src
        assert "asset_type_exposure" in src

    def test_response_has_artifact_paths(self):
        """Response model must have artifact_paths."""
        src = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "artifact_paths" in src


class TestPortfolioSchemaValidation:

    def test_watchlist_folder_id_rejects_blank_string(self):
        """Blank whitespace string must be rejected — strip_whitespace + min_length."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(watchlist_folder_id="   ")

    def test_watchlist_folder_id_strips_whitespace(self):
        """Leading/trailing whitespace must be stripped."""
        r = PortfolioAnalyzeRequest(watchlist_folder_id="  abc  ")
        assert r.watchlist_folder_id == "abc"

    def test_watchlist_folder_id_accepts_valid(self):
        """Valid folder ID must be accepted."""
        r = PortfolioAnalyzeRequest(watchlist_folder_id="folder_123")
        assert r.watchlist_folder_id == "folder_123"

    def test_watchlist_folder_id_accepts_none(self):
        """None must be accepted (field is optional)."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "A.SH"}])
        assert r.watchlist_folder_id is None

    def test_current_weight_total_over_100_rejected(self):
        """Total current_weight exceeding 100% must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[
                {"symbol": "A.SH", "current_weight": 0.8},
                {"symbol": "B.SH", "current_weight": 0.7},
            ])

    def test_current_weight_total_exactly_100_accepted(self):
        """Total current_weight exactly 100% must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[
            {"symbol": "A.SH", "current_weight": 0.6},
            {"symbol": "B.SH", "current_weight": 0.4},
        ])
        assert len(r.positions) == 2

    def test_current_weight_total_under_100_accepted(self):
        """Total current_weight under 100% must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[
            {"symbol": "A.SH", "current_weight": 0.5},
            {"symbol": "B.SH", "current_weight": 0.3},
        ])
        assert len(r.positions) == 2

    def test_current_weight_none_positions_accepted(self):
        """Positions without current_weight must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[
            {"symbol": "A.SH"},
            {"symbol": "B.SH"},
        ])
        assert len(r.positions) == 2

    def test_current_weight_mixed_none_and_specified(self):
        """Mix of specified and unspecified weights — only specified ones are summed."""
        r = PortfolioAnalyzeRequest(positions=[
            {"symbol": "A.SH", "current_weight": 0.5},
            {"symbol": "B.SH"},  # None → excluded from sum
        ])
        assert len(r.positions) == 2

    def test_current_weight_mixed_over_100_rejected(self):
        """Mixed weights where specified ones exceed 100% must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[
                {"symbol": "A.SH", "current_weight": 0.6},
                {"symbol": "B.SH", "current_weight": 0.5},
                {"symbol": "C.SH"},  # None → excluded
            ])


class TestSymbolNormalization:
    """Test symbol format validation and normalization."""

    def test_symbol_strips_whitespace(self):
        """Leading/trailing whitespace must be stripped."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "  600519.SH  "}])
        assert r.positions[0].symbol == "600519.SH"

    def test_symbol_uppercases(self):
        """Lowercase suffix must be uppercased."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "600519.sh"}])
        assert r.positions[0].symbol == "600519.SH"

    def test_symbol_uppercases_mixed_case(self):
        """Mixed case suffix must be uppercased."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "600519.Sh"}])
        assert r.positions[0].symbol == "600519.SH"

    def test_symbol_accepts_valid_format(self):
        """Valid symbol format must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "600519.SH"}])
        assert r.positions[0].symbol == "600519.SH"

    def test_symbol_accepts_etf_format(self):
        """ETF symbol format must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "510300.SH"}])
        assert r.positions[0].symbol == "510300.SH"

    def test_symbol_accepts_sz_format(self):
        """Shenzhen symbol format must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "000001.SZ"}])
        assert r.positions[0].symbol == "000001.SZ"

    def test_symbol_accepts_bj_format(self):
        """Beijing symbol format must be accepted."""
        r = PortfolioAnalyzeRequest(positions=[{"symbol": "830799.BJ"}])
        assert r.positions[0].symbol == "830799.BJ"

    def test_symbol_rejects_empty_string(self):
        """Empty string must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[{"symbol": ""}])

    def test_symbol_rejects_blank_string(self):
        """Blank whitespace string must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[{"symbol": "   "}])

    def test_symbol_rejects_invalid_characters(self):
        """Symbol with invalid characters must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[{"symbol": "600519@SH"}])

    def test_symbol_rejects_chinese_characters(self):
        """Symbol with Chinese characters must be rejected."""
        with pytest.raises(ValidationError):
            PortfolioAnalyzeRequest(positions=[{"symbol": "贵州茅台"}])


class TestAnalyzerNoTradeLanguage:

    def test_analyzer_no_auto_trade(self):
        """Analyzer must not contain auto-trade language."""
        src = ANALYZER_PATH.read_text(encoding="utf-8")
        forbidden = ["自动下单", "自动交易", "交易指令", "auto trade", "auto order"]
        for word in forbidden:
            assert word not in src, f"Forbidden word '{word}' found in analyzer"
