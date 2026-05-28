"""Contract tests for portfolio dashboard page — static analysis.

Verifies page exists, uses auth, and follows conventions without booting Streamlit.
"""

from pathlib import Path

import pytest

PAGE_PATH = Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "pages" / "5_组合分析.py"


class TestPortfolioDashboardContract:

    def test_page_exists(self):
        """Portfolio dashboard page must exist."""
        assert PAGE_PATH.exists(), f"Page not found: {PAGE_PATH}"

    def test_page_uses_require_login(self):
        """Page must call require_login()."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        assert "require_login" in src

    def test_page_uses_authenticated_request(self):
        """Page must use authenticated_request for API calls."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        assert "authenticated_request" in src

    def test_page_no_direct_db_access(self):
        """Page must not access SQLite directly — must go through API."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        assert "sqlite3" not in src
        assert "get_task_store" not in src
        assert "get_watchlist_store" not in src

    def test_page_no_trade_language(self):
        """Page must not contain auto-trade language (except disclaimers)."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        # Disclaimers are allowed — check that no POSITIVE trade instructions exist
        # "不会自动下单" is a disclaimer (OK), "自动下单功能" would be a feature (bad)
        positive_forbidden = ["自动下单功能", "自动交易功能", "交易指令下达", "auto trade execute"]
        for word in positive_forbidden:
            assert word not in src, f"Positive trade instruction '{word}' found in page"

    def test_page_has_disclaimer(self):
        """Page must include research disclaimer."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        assert "研究建议" in src or "不构成交易指令" in src

    def test_page_uses_streamlit(self):
        """Page must use Streamlit framework."""
        src = PAGE_PATH.read_text(encoding="utf-8")
        assert "import streamlit" in src
        assert "st.set_page_config" in src
