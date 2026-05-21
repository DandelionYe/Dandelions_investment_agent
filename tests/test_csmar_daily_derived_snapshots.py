import sqlite3

import pandas as pd

from scripts.build_csmar_daily_derived_snapshots import (
    RAW_COLUMNS,
    collect_snapshot_dates,
    discover_csv_files,
    infer_symbol,
    load_symbol_map,
    normalize_stkcd,
    write_snapshots,
)


def test_normalize_and_infer_symbol() -> None:
    symbol_map = {"600410": "600410.SH"}

    assert normalize_stkcd("600410.0") == "600410"
    assert normalize_stkcd(419) == "000419"
    assert infer_symbol("600410", symbol_map) == "600410.SH"
    assert infer_symbol("000419", symbol_map) == "000419.SZ"


def test_build_snapshots_keeps_month_end_and_latest_non_null_metrics(tmp_path) -> None:
    input_root = tmp_path / "raw"
    raw_folder = input_root / "个股日交易衍生指标_sample"
    raw_folder.mkdir(parents=True)
    csv_path = raw_folder / "STK_MKT_DALYR.csv"
    pd.DataFrame(
        [
            {
                "TradingDate": "2024-12-30",
                "Symbol": "600410",
                "ShortName": "华胜天成",
                "Ret": "",
                "PE": "10",
                "PB": "1.1",
                "PCF": "2.1",
                "PS": "3.1",
                "Turnover": "0.1",
                "CirculatedMarketValue": "1000",
                "ChangeRatio": "0.01",
                "Amount": "100",
                "Liquidility": "5",
            },
            {
                "TradingDate": "2024-12-31",
                "Symbol": "600410",
                "ShortName": "华胜天成",
                "Ret": "2.5",
                "PE": "11",
                "PB": "1.2",
                "PCF": "2.2",
                "PS": "3.2",
                "Turnover": "0.2",
                "CirculatedMarketValue": "1100",
                "ChangeRatio": "0.02",
                "Amount": "110",
                "Liquidility": "6",
            },
            {
                "TradingDate": "2025-01-03",
                "Symbol": "600410",
                "ShortName": "华胜天成",
                "Ret": "",
                "PE": "12",
                "PB": "1.3",
                "PCF": "2.3",
                "PS": "3.3",
                "Turnover": "0.3",
                "CirculatedMarketValue": "1200",
                "ChangeRatio": "0.03",
                "Amount": "120",
                "Liquidility": "7",
            },
            {
                "TradingDate": "2025-01-02",
                "Symbol": "000419",
                "ShortName": "通程控股",
                "Ret": "1.2",
                "PE": "8",
                "PB": "0.8",
                "PCF": "1.8",
                "PS": "2.8",
                "Turnover": "0.4",
                "CirculatedMarketValue": "900",
                "ChangeRatio": "0.04",
                "Amount": "90",
                "Liquidility": "4",
            },
        ],
        columns=RAW_COLUMNS,
    ).to_csv(csv_path, index=False, encoding="utf-8-sig")

    industry_db = tmp_path / "industry.sqlite"
    with sqlite3.connect(industry_db) as conn:
        conn.execute(
            "CREATE TABLE securities (stkcd TEXT, symbol_qmt TEXT, is_a_share INTEGER)"
        )
        conn.executemany(
            "INSERT INTO securities VALUES (?, ?, 1)",
            [("600410", "600410.SH"), ("000419", "000419.SZ")],
        )

    files = discover_csv_files(input_root)
    symbol_map = load_symbol_map(industry_db)
    monthly_dates, latest_dates, _stats = collect_snapshot_dates(
        files,
        symbol_map=symbol_map,
        allowed_symbols=set(symbol_map.values()),
        chunksize=2,
    )

    output_db = tmp_path / "snapshots.sqlite"
    latest_output = tmp_path / "latest.csv"
    latest_metrics_output = tmp_path / "latest_metrics.csv"
    write_stats = write_snapshots(
        files,
        output_db=output_db,
        latest_output=latest_output,
        latest_metrics_output=latest_metrics_output,
        monthly_dates=monthly_dates,
        latest_dates=latest_dates,
        symbol_map=symbol_map,
        allowed_symbols=set(symbol_map.values()),
        chunksize=2,
    )

    assert write_stats["monthly_rows"] == 3
    assert write_stats["latest_rows"] == 2
    assert write_stats["latest_metrics_rows"] == 2
    assert latest_output.exists()
    assert latest_metrics_output.exists()

    with sqlite3.connect(output_db) as conn:
        monthly_rows = conn.execute(
            "SELECT symbol, period, trading_date FROM monthly_snapshots "
            "ORDER BY symbol, period"
        ).fetchall()
        latest_metric = conn.execute(
            "SELECT dividend_yield, dividend_yield_date, pe, pe_date "
            "FROM latest_non_null_metrics WHERE symbol = '600410.SH'"
        ).fetchone()

    assert monthly_rows == [
        ("000419.SZ", "2025-01", "2025-01-02"),
        ("600410.SH", "2024-12", "2024-12-31"),
        ("600410.SH", "2025-01", "2025-01-03"),
    ]
    assert latest_metric == (0.025, "2024-12-31", 12.0, "2025-01-03")
