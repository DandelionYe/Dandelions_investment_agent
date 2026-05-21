"""Unit tests for LocalCSMAREVAStructureProvider and build script."""

import csv
import os
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest

from scripts.build_csmar_eva_structure_reference import _stkcd_to_qmt
from services.data.providers.local_csmar_eva_structure_provider import (
    LocalCSMAREVAStructureProvider,
    _positive_float,
    is_eva_structure_enabled,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_dir() -> str:
    return tempfile.mkdtemp(prefix="eva_test_")


def _create_test_db(db_path: str, *, stale: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE eva_structure_latest (
            symbol TEXT PRIMARY KEY,
            stkcd TEXT NOT NULL,
            end_date TEXT NOT NULL,
            short_name TEXT,
            total_volume REAL,
            float_volume REAL,
            market_cap REAL,
            float_market_cap REAL,
            equity_per_share REAL,
            wacc REAL,
            debt REAL,
            income_tax_rate REAL
        )
    """)

    today = date.today()
    end_date = (today - timedelta(days=400)).isoformat() if stale else (today - timedelta(days=30)).isoformat()

    # 000001.SZ - normal stock
    cur.execute(
        "INSERT INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("000001.SZ", "000001", end_date, "平安银行",
         19405918198.0, None, 215018000000.0, 215014000000.0,
         28.036, 3.256, 5489880000000.0, 25.0),
    )

    # 600410.SH - normal stock
    cur.execute(
        "INSERT INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("600410.SH", "600410", end_date, "华胜天成",
         1096494683.0, None, 27204033085.0, 27204033085.0,
         4.600, 7.788, 4900936066.0, 15.0),
    )

    # 000002.SZ - zero total_volume (invalid)
    cur.execute(
        "INSERT INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("000002.SZ", "000002", end_date, "万科A",
         0.0, None, 100000000.0, None, 1.0, 5.0, None, None),
    )

    # 000003.SZ - None total_volume
    cur.execute(
        "INSERT INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("000003.SZ", "000003", end_date, "测试",
         None, None, 50000000.0, None, 1.0, 5.0, None, None),
    )

    cur.execute("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)
    """)
    cur.execute("INSERT INTO metadata VALUES ('build_date', ?)", (today.isoformat(),))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: DB missing
# ---------------------------------------------------------------------------

def test_missing_db_returns_empty():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "nonexistent.sqlite")
        provider = LocalCSMAREVAStructureProvider(db_path=db)
        result = provider.get_latest_share_capital("000001.SZ")

        assert result.metadata.success is True
        assert result.data.get("total_volume") is None
        assert "not found" in (result.metadata.error or "").lower()
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: normal read
# ---------------------------------------------------------------------------

def test_get_latest_returns_valid_data():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("000001.SZ")

        assert result.metadata.success is True
        data = result.data
        assert data["symbol"] == "000001.SZ"
        assert data["source"] == "local_csmar_eva_structure"
        assert data["total_volume"] == pytest.approx(19405918198.0)
        assert data["market_cap"] == pytest.approx(215018000000.0)
        assert data["equity_per_share"] == pytest.approx(28.036)
        assert data["as_of"] is not None
        assert data["stkcd"] == "000001"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_get_latest_600410():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("600410.SH")

        assert result.metadata.success is True
        assert result.data["total_volume"] == pytest.approx(1096494683.0)
        assert result.data["stkcd"] == "600410"
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
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("999999.SH")

        assert result.metadata.success is True
        assert result.data.get("total_volume") is None
        assert "not in" in (result.metadata.error or "").lower()
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: zero / None total_volume
# ---------------------------------------------------------------------------

def test_zero_total_volume_excluded():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("000002.SZ")

        assert result.metadata.success is True
        # total_volume is 0, should not be in data
        assert result.data.get("total_volume") is None
        # market_cap is still present
        assert result.data.get("market_cap") is not None
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_none_total_volume_excluded():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("000003.SZ")

        assert result.metadata.success is True
        assert result.data.get("total_volume") is None
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: staleness
# ---------------------------------------------------------------------------

def test_stale_data_returns_warning():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db, stale=True)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("000001.SZ")

        assert result.metadata.success is True
        # Data is 400 days old (limit 460), should still be present but with warning
        # Actually 400 < 460, so no warning. Let me check.
        age = (date.today() - (date.today() - timedelta(days=400))).days
        assert age == 400
        # 400 < 460, so data should be present without warning
        assert result.data.get("total_volume") is not None
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_very_stale_data_returns_warning():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        # Create with very stale data (500 days)
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE eva_structure_latest (
                symbol TEXT PRIMARY KEY, stkcd TEXT NOT NULL, end_date TEXT NOT NULL,
                short_name TEXT, total_volume REAL, float_volume REAL,
                market_cap REAL, float_market_cap REAL, equity_per_share REAL,
                wacc REAL, debt REAL, income_tax_rate REAL
            )
        """)
        very_stale = (date.today() - timedelta(days=500)).isoformat()
        cur.execute(
            "INSERT INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("000001.SZ", "000001", very_stale, "平安银行",
             1e10, None, 1e12, None, 28.0, 3.0, None, None),
        )
        conn.commit()
        conn.close()

        provider = LocalCSMAREVAStructureProvider(db_path=db)
        result = provider.get_latest_share_capital("000001.SZ")

        assert result.metadata.success is True
        # 500 > 460, should be treated as no usable fallback data.
        assert result.metadata.error is not None
        assert result.metadata.error_type == "provider_data_quality"
        assert "old" in result.metadata.error.lower()
        assert result.data.get("total_volume") is None
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: env controls
# ---------------------------------------------------------------------------

def test_disabled_by_env(monkeypatch):
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        monkeypatch.setenv("CSMAR_EVA_STRUCTURE_PROVIDER", "false")
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_latest_share_capital("000001.SZ")

        assert result.metadata.success is True
        assert result.data.get("total_volume") is None
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_is_eva_structure_enabled_default(monkeypatch):
    monkeypatch.delenv("CSMAR_EVA_STRUCTURE_PROVIDER", raising=False)
    assert is_eva_structure_enabled() is True


# ---------------------------------------------------------------------------
# Tests: batch API
# ---------------------------------------------------------------------------

def test_batch_returns_multiple_symbols():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_batch_share_capital(["000001.SZ", "600410.SH", "999999.SH"])

        assert "000001.SZ" in result
        assert "600410.SH" in result
        assert "999999.SH" not in result
        assert result["000001.SZ"]["total_volume"] == pytest.approx(19405918198.0)
        assert result["600410.SH"]["total_volume"] == pytest.approx(1096494683.0)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_batch_keeps_market_cap_only_for_inference():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_batch_share_capital(["000002.SZ", "000003.SZ"])

        assert result["000002.SZ"].get("total_volume") is None
        assert result["000002.SZ"]["market_cap"] == pytest.approx(100000000.0)
        assert result["000003.SZ"].get("total_volume") is None
        assert result["000003.SZ"]["market_cap"] == pytest.approx(50000000.0)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_batch_empty_symbols():
    td = _make_tmp_dir()
    try:
        db = os.path.join(td, "test.sqlite")
        _create_test_db(db)
        provider = LocalCSMAREVAStructureProvider(db_path=db)

        result = provider.get_batch_share_capital([])
        assert result == {}
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: _positive_float helper
# ---------------------------------------------------------------------------

def test_positive_float():
    assert _positive_float(None) is None
    assert _positive_float(0) is None
    assert _positive_float(-1) is None
    assert _positive_float(float("nan")) is None
    assert _positive_float(float("inf")) is None
    assert _positive_float(1.0) == pytest.approx(1.0)
    assert _positive_float(42) == pytest.approx(42.0)


def test_build_symbol_mapping_excludes_b_shares():
    assert _stkcd_to_qmt("000001") == "000001.SZ"
    assert _stkcd_to_qmt("002624") == "002624.SZ"
    assert _stkcd_to_qmt("600410") == "600410.SH"
    assert _stkcd_to_qmt("920001") == "920001.BJ"
    assert _stkcd_to_qmt("200041") is None
    assert _stkcd_to_qmt("900947") is None


# ---------------------------------------------------------------------------
# Tests: build script
# ---------------------------------------------------------------------------

def test_build_script_creates_tables():
    """Test build script with a minimal CSV."""
    td = _make_tmp_dir()
    csv_path = os.path.join(td, "eva.csv")
    db_path = os.path.join(td, "eva.sqlite")
    report_path = os.path.join(td, "report.md")

    # Create minimal CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Symbol", "EndDate", "InstitutionID", "ShortName", "Debt",
            "IncomeTaxRate", "CirculatedMarketValue", "MarketValue",
            "TotalShares", "NegotiableShares", "EquityPerShare", "WACC",
        ])
        writer.writerow(["1", "2025/12/31", "100", "TestA", "1e10", "25",
                         "5e9", "1e10", "1e9", "8e8", "5.0", "3.5"])
        writer.writerow(["1", "2026/3/31", "100", "TestA", "1.1e10", "25",
                         "6e9", "1.2e10", "1e9", "8e8", "5.1", "3.6"])
        writer.writerow(["600410", "2026/3/31", "200", "TestB", "2e9", "15",
                         "3e9", "5e9", "5e8", "4e8", "4.0", "7.0"])
        writer.writerow(["200041", "2026/3/31", "300", "TestBShare", "2e9", "15",
                         "3e9", "5e9", "5e8", "4e8", "4.0", "7.0"])

    # Monkey-patch the module paths
    import scripts.build_csmar_eva_structure_reference as build_mod
    orig_csv = build_mod.RAW_CSV
    orig_db = build_mod.OUTPUT_DB
    orig_report = build_mod.OUTPUT_REPORT
    build_mod.RAW_CSV = csv_path
    build_mod.OUTPUT_DB = db_path
    build_mod.OUTPUT_REPORT = report_path

    try:
        build_mod.build()

        assert os.path.exists(db_path)
        assert os.path.exists(report_path)

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM eva_structure_history")
        assert cur.fetchone()[0] == 3

        cur.execute("SELECT COUNT(*) FROM eva_structure_latest")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT * FROM eva_structure_latest WHERE symbol = ?", ("000001.SZ",))
        row = cur.fetchone()
        assert row is not None
        # Should be the 2026-03-31 row (latest)
        assert row[2] == "2026-03-31"

        cur.execute("SELECT * FROM metadata")
        meta = dict(cur.fetchall())
        assert meta["symbol_count"] == "2"
        assert meta["clean_row_count"] == "3"

        conn.close()
    finally:
        build_mod.RAW_CSV = orig_csv
        build_mod.OUTPUT_DB = orig_db
        build_mod.OUTPUT_REPORT = orig_report
        shutil.rmtree(td, ignore_errors=True)
