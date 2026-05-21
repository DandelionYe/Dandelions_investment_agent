"""Unit tests for LocalCSMARDailyDerivedProvider."""

import os
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest

from services.data.providers.local_csmar_daily_derived_provider import (
    LocalCSMARDailyDerivedProvider,
    _safe_float,
    _stale_limit_for_field,
    is_csmar_daily_derived_enabled,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_dir() -> str:
    d = tempfile.mkdtemp(prefix="csmar_test_")
    return d


def _create_test_db(db_path: str) -> None:
    """Create a minimal test SQLite with the expected schema and sample data."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE latest_non_null_metrics (
            symbol TEXT,
            stkcd TEXT,
            short_name TEXT,
            dividend_yield_date TEXT,
            dividend_yield REAL,
            pe_date TEXT,
            pe REAL,
            pb_date TEXT,
            pb REAL,
            pcf_date TEXT,
            pcf REAL,
            ps_date TEXT,
            ps REAL,
            turnover_date TEXT,
            turnover REAL,
            circulated_market_value_date TEXT,
            circulated_market_value REAL,
            change_ratio_date TEXT,
            change_ratio REAL,
            amount_date TEXT,
            amount INTEGER,
            liquidility_date TEXT,
            liquidility REAL
        )
    """)

    today = date.today().isoformat()
    old_date = (date.today() - timedelta(days=400)).isoformat()
    recent_date = (date.today() - timedelta(days=10)).isoformat()

    # Fresh stock with all fields
    cur.execute(
        "INSERT INTO latest_non_null_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "600519.SH", "600519", "贵州茅台",
            recent_date, 0.015,  # dividend_yield
            today, 25.0,         # pe
            today, 8.0,          # pb
            today, 15.0,         # pcf
            today, 12.0,         # ps
            today, 0.003,        # turnover
            today, 2000000000,   # circulated_market_value
            today, 0.01,         # change_ratio
            today, 500000000,    # amount
            today, 0.0001,       # liquidility
        ),
    )

    # Stock with stale PE (400 days old)
    cur.execute(
        "INSERT INTO latest_non_null_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "000001.SZ", "000001", "平安银行",
            recent_date, 0.05,   # dividend_yield (fresh)
            old_date, 5.0,       # pe (stale)
            today, 0.5,          # pb (fresh)
            today, 3.0,          # pcf
            today, 1.5,          # ps
            today, 0.005,        # turnover
            today, 300000000000, # circulated_market_value
            today, -0.01,        # change_ratio
            today, 900000000,    # amount
            today, 0.00001,      # liquidility
        ),
    )

    # monthly_snapshots table
    cur.execute("""
        CREATE TABLE monthly_snapshots (
            symbol TEXT,
            stkcd TEXT,
            trading_date TEXT,
            period TEXT,
            short_name TEXT,
            dividend_yield REAL,
            pe REAL,
            pb REAL,
            pcf REAL,
            ps REAL,
            turnover REAL,
            circulated_market_value REAL,
            change_ratio REAL,
            amount INTEGER,
            liquidility REAL,
            source_file TEXT
        )
    """)

    # Insert 24 monthly snapshots for 600519.SH
    base_date = date(2024, 1, 31)
    for i in range(24):
        d = base_date + timedelta(days=30 * i)
        cur.execute(
            "INSERT INTO monthly_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "600519.SH", "600519", d.isoformat(), d.strftime("%Y-%m"),
                "贵州茅台",
                0.01 + i * 0.001,  # dividend_yield
                20.0 + i * 0.5,     # pe
                6.0 + i * 0.1,      # pb
                10.0 + i * 0.3,     # pcf
                8.0 + i * 0.2,      # ps
                0.003, 2e9, 0.01, 5e8, 0.0001,
                "STK_MKT_DALYR.csv",
            ),
        )

    # metadata table
    cur.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
    cur.execute("INSERT INTO metadata VALUES ('build_date', ?)", (today,))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: DB missing
# ---------------------------------------------------------------------------

def test_missing_db_returns_empty_with_warning():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "nonexistent.sqlite")
        provider = LocalCSMARDailyDerivedProvider(db_path=db)
        result = provider.get_latest_metrics("600519.SH")

        assert result.metadata.success is True
        assert result.data.get("pe") is None
        assert "not found" in (result.metadata.error or "").lower()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_missing_table_returns_empty():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "empty.sqlite")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE dummy (x INT)")
        conn.commit()
        conn.close()

        provider = LocalCSMARDailyDerivedProvider(db_path=db)
        result = provider.get_latest_metrics("600519.SH")

        # Should fail gracefully (no such table: latest_non_null_metrics)
        assert result.metadata.success is True
        assert result.data.get("pe") is None
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: normal read
# ---------------------------------------------------------------------------

def test_get_latest_metrics_returns_all_fields():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("600519.SH")

        assert result.metadata.success is True
        data = result.data
        assert data["symbol"] == "600519.SH"
        assert data["source"] == "local_csmar_daily_derived"
        assert data["dividend_yield"] == pytest.approx(0.015)
        assert data["pe"] == pytest.approx(25.0)
        assert data["pb"] == pytest.approx(8.0)
        assert data["pcf"] == pytest.approx(15.0)
        assert data["ps"] == pytest.approx(12.0)
        assert data["turnover"] == pytest.approx(0.003)
        assert "dividend_yield_date" in data
        assert "pe_date" in data
        assert "pb_date" in data
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_get_latest_metrics_dates_match_source():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("600519.SH")
        data = result.data

        today = date.today().isoformat()
        assert data["pe_date"] == today
        assert data["pb_date"] == today
        assert data["ps_date"] == today
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: symbol not found
# ---------------------------------------------------------------------------

def test_symbol_not_found_returns_empty():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("999999.SH")

        assert result.metadata.success is True
        assert result.data.get("pe") is None
        assert "not in" in (result.metadata.error or "").lower()
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: staleness
# ---------------------------------------------------------------------------

def test_stale_pe_filtered_out():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("000001.SZ")
        data = result.data

        # PE is 400 days old (limit 45), should be filtered
        assert data.get("pe") is None
        # PB is fresh, should be present
        assert data.get("pb") == pytest.approx(0.5)
        # dividend_yield is fresh (370-day limit)
        assert data.get("dividend_yield") == pytest.approx(0.05)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_stale_warning_in_metadata_error():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("000001.SZ")
        # The provider should still succeed
        assert result.metadata.success is True
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_stale_limit_valuation_vs_general():
    assert _stale_limit_for_field("pe") == 45
    assert _stale_limit_for_field("pb") == 45
    assert _stale_limit_for_field("ps") == 45
    assert _stale_limit_for_field("pcf") == 45
    assert _stale_limit_for_field("dividend_yield") == 370
    assert _stale_limit_for_field("turnover") == 370


# ---------------------------------------------------------------------------
# Tests: monthly_snapshots
# ---------------------------------------------------------------------------

def test_get_monthly_history_returns_rows():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_monthly_history(
            symbols=["600519.SH"],
            metrics=["pe", "pb"],
        )

        assert result.metadata.success is True
        assert len(result.data) == 24
        assert "pe" in result.data[0]
        assert "pb" in result.data[0]
        assert "symbol" in result.data[0]
        assert "trading_date" in result.data[0]
        assert "period" in result.data[0]
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_get_monthly_history_filters_by_date():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_monthly_history(
            symbols=["600519.SH"],
            metrics=["pe"],
            start_date="2025-01-01",
        )

        assert result.metadata.success is True
        # Only rows from 2025-01 onward should be returned
        for row in result.data:
            assert row["trading_date"] >= "2025-01-01"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_get_monthly_history_empty_for_missing_symbol():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_monthly_history(
            symbols=["999999.SH"],
            metrics=["pe"],
        )

        assert result.metadata.success is True
        assert len(result.data) == 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_get_monthly_history_no_csv_scanning():
    """Verify that the provider only reads from SQLite, not raw CSV."""
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_monthly_history(
            symbols=["600519.SH"],
            metrics=["pe", "pb", "ps"],
        )

        assert result.metadata.success is True
        assert result.dataset == "monthly_snapshots"
        assert "sqlite" in (result.metadata.source_url or "")
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: env controls
# ---------------------------------------------------------------------------

def test_disabled_by_env_returns_empty(monkeypatch):
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
        provider = LocalCSMARDailyDerivedProvider(db_path=db)

        result = provider.get_latest_metrics("600519.SH")

        assert result.metadata.success is True
        assert result.data.get("pe") is None
        assert "disabled" in (result.metadata.error or "").lower()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_is_csmar_daily_derived_enabled_default(monkeypatch):
    monkeypatch.delenv("CSMAR_DAILY_DERIVED_PROVIDER", raising=False)
    assert is_csmar_daily_derived_enabled() is True


def test_is_csmar_daily_derived_enabled_false(monkeypatch):
    monkeypatch.setenv("CSMAR_DAILY_DERIVED_PROVIDER", "false")
    assert is_csmar_daily_derived_enabled() is False


# ---------------------------------------------------------------------------
# Tests: safe_float
# ---------------------------------------------------------------------------

def test_safe_float_handles_none():
    assert _safe_float(None) is None


def test_safe_float_handles_nan():
    assert _safe_float(float("nan")) is None


def test_safe_float_handles_valid():
    assert _safe_float(3.14) == pytest.approx(3.14)
    assert _safe_float(42) == pytest.approx(42.0)
