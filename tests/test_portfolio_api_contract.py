"""Contract tests for portfolio API — static analysis of router/schema.

Verifies RBAC, endpoint registration, and schema constraints without booting FastAPI.
"""

from pathlib import Path

import pytest

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


class TestAnalyzerNoTradeLanguage:

    def test_analyzer_no_auto_trade(self):
        """Analyzer must not contain auto-trade language."""
        src = ANALYZER_PATH.read_text(encoding="utf-8")
        forbidden = ["自动下单", "自动交易", "交易指令", "auto trade", "auto order"]
        for word in forbidden:
            assert word not in src, f"Forbidden word '{word}' found in analyzer"
