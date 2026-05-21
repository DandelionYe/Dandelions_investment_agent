"""Build compact CSMAR daily-derived valuation snapshots.

The raw "个股日交易衍生指标" exports are daily files and can be very large.
This script keeps one last-available trading row per stock per calendar month,
plus a latest snapshot table, so downstream valuation code can query PE/PB/PS,
dividend yield, turnover, market value, and liquidity without scanning raw CSVs.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

RAW_COLUMNS = [
    "TradingDate",
    "Symbol",
    "ShortName",
    "Ret",
    "PE",
    "PB",
    "PCF",
    "PS",
    "Turnover",
    "CirculatedMarketValue",
    "ChangeRatio",
    "Amount",
    "Liquidility",
]

OUTPUT_COLUMNS = [
    "symbol",
    "stkcd",
    "trading_date",
    "period",
    "short_name",
    "dividend_yield",
    "pe",
    "pb",
    "pcf",
    "ps",
    "turnover",
    "circulated_market_value",
    "change_ratio",
    "amount",
    "liquidility",
    "source_file",
]

METRIC_COLUMNS = [
    "dividend_yield",
    "pe",
    "pb",
    "pcf",
    "ps",
    "turnover",
    "circulated_market_value",
    "change_ratio",
    "amount",
    "liquidility",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compact CSMAR daily-derived indicator CSVs into SQLite snapshots.",
    )
    parser.add_argument(
        "--input-root",
        default="data/raw/csmar",
        help="Directory containing 个股日交易衍生指标* folders.",
    )
    parser.add_argument(
        "--industry-db",
        default="storage/reference/csmar_industry.sqlite",
        help="Optional local industry SQLite used to map 6-digit codes to QMT symbols.",
    )
    parser.add_argument(
        "--output-db",
        default="storage/reference/csmar_daily_derived_snapshots.sqlite",
        help="SQLite output path.",
    )
    parser.add_argument(
        "--latest-output",
        default="storage/reference/csmar_daily_derived_latest.csv",
        help="Latest snapshot CSV output path.",
    )
    parser.add_argument(
        "--latest-metrics-output",
        default="storage/reference/csmar_daily_derived_latest_metrics.csv",
        help="Latest non-null metrics CSV output path.",
    )
    parser.add_argument(
        "--report-output",
        default="storage/reference/csmar_daily_derived_build_report.md",
        help="Markdown build report path.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=250_000,
        help="CSV read chunksize.",
    )
    return parser.parse_args()


def discover_csv_files(input_root: Path) -> list[Path]:
    files: list[Path] = []
    for folder in sorted(input_root.glob("个股日交易衍生指标*")):
        if not folder.is_dir():
            continue
        files.extend(sorted(folder.glob("STK_MKT_DALYR*.csv"), key=_csv_sort_key))
    if not files:
        raise SystemExit(f"No STK_MKT_DALYR*.csv files found under {input_root}")
    return files


def _csv_sort_key(path: Path) -> tuple[str, int]:
    stem = path.stem
    suffix = stem.replace("STK_MKT_DALYR", "")
    return (path.parent.name, int(suffix or "0"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_symbol_map(industry_db: Path) -> dict[str, str]:
    if not industry_db.exists():
        return {}
    with sqlite3.connect(industry_db) as conn:
        try:
            rows = conn.execute(
                "SELECT stkcd, symbol_qmt FROM securities WHERE is_a_share = 1"
            ).fetchall()
        except sqlite3.Error:
            return {}
    return {str(stkcd).zfill(6): symbol for stkcd, symbol in rows if stkcd and symbol}


def normalize_stkcd(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        text = str(int(float(text)))
    except ValueError:
        text = text.split(".")[0]
    return text.zfill(6)


def infer_symbol(stkcd: str, symbol_map: dict[str, str]) -> str | None:
    if stkcd in symbol_map:
        return symbol_map[stkcd]
    if stkcd.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{stkcd}.SH"
    if stkcd.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{stkcd}.SZ"
    if stkcd.startswith(("430", "8", "920")):
        return f"{stkcd}.BJ"
    return None


def iter_csv_chunks(files: Iterable[Path], chunksize: int, usecols: list[str]):
    for path in files:
        for chunk in pd.read_csv(
            path,
            encoding="utf-8-sig",
            usecols=usecols,
            chunksize=chunksize,
            low_memory=False,
        ):
            yield path, chunk


def add_normalized_keys(
    chunk: pd.DataFrame,
    symbol_map: dict[str, str],
    allowed_symbols: set[str] | None,
) -> pd.DataFrame:
    frame = chunk.copy()
    frame["stkcd"] = frame["Symbol"].map(normalize_stkcd)
    frame["symbol"] = frame["stkcd"].map(lambda value: infer_symbol(value, symbol_map) if value else None)
    frame["trading_date"] = pd.to_datetime(frame["TradingDate"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "trading_date"])
    if allowed_symbols is not None:
        frame = frame[frame["symbol"].isin(allowed_symbols)]
    if frame.empty:
        return frame
    frame["trading_date_str"] = frame["trading_date"].dt.strftime("%Y-%m-%d")
    frame["period"] = frame["trading_date"].dt.strftime("%Y-%m")
    return frame


def collect_snapshot_dates(
    files: list[Path],
    *,
    symbol_map: dict[str, str],
    allowed_symbols: set[str] | None,
    chunksize: int,
) -> tuple[dict[tuple[str, str], str], dict[str, str], dict]:
    monthly: dict[tuple[str, str], str] = {}
    latest: dict[str, str] = {}
    stats = {
        "raw_rows": 0,
        "kept_rows_seen": 0,
        "raw_min_date": None,
        "raw_max_date": None,
        "raw_symbols": set(),
        "kept_symbols": set(),
    }

    for _path, chunk in iter_csv_chunks(files, chunksize, ["TradingDate", "Symbol"]):
        stats["raw_rows"] += len(chunk)
        raw_codes = chunk["Symbol"].map(normalize_stkcd).dropna()
        stats["raw_symbols"].update(raw_codes.unique().tolist())

        frame = add_normalized_keys(chunk, symbol_map, allowed_symbols)
        if frame.empty:
            continue
        stats["kept_rows_seen"] += len(frame)
        stats["kept_symbols"].update(frame["symbol"].unique().tolist())

        min_date = frame["trading_date_str"].min()
        max_date = frame["trading_date_str"].max()
        stats["raw_min_date"] = min_date if stats["raw_min_date"] is None else min(stats["raw_min_date"], min_date)
        stats["raw_max_date"] = max_date if stats["raw_max_date"] is None else max(stats["raw_max_date"], max_date)

        for row in frame[["symbol", "period", "trading_date_str"]].itertuples(index=False):
            key = (row.symbol, row.period)
            if row.trading_date_str > monthly.get(key, ""):
                monthly[key] = row.trading_date_str
            if row.trading_date_str > latest.get(row.symbol, ""):
                latest[row.symbol] = row.trading_date_str

    return monthly, latest, stats


def transform_output_frame(frame: pd.DataFrame, source_file: str) -> pd.DataFrame:
    output = pd.DataFrame({
        "symbol": frame["symbol"],
        "stkcd": frame["stkcd"],
        "trading_date": frame["trading_date_str"],
        "period": frame["period"],
        "short_name": frame["ShortName"],
        "dividend_yield": pd.to_numeric(frame["Ret"], errors="coerce") / 100.0,
        "pe": pd.to_numeric(frame["PE"], errors="coerce"),
        "pb": pd.to_numeric(frame["PB"], errors="coerce"),
        "pcf": pd.to_numeric(frame["PCF"], errors="coerce"),
        "ps": pd.to_numeric(frame["PS"], errors="coerce"),
        "turnover": pd.to_numeric(frame["Turnover"], errors="coerce"),
        "circulated_market_value": pd.to_numeric(frame["CirculatedMarketValue"], errors="coerce"),
        "change_ratio": pd.to_numeric(frame["ChangeRatio"], errors="coerce"),
        "amount": pd.to_numeric(frame["Amount"], errors="coerce"),
        "liquidility": pd.to_numeric(frame["Liquidility"], errors="coerce"),
        "source_file": source_file,
    })
    return output[OUTPUT_COLUMNS]


def write_snapshots(
    files: list[Path],
    *,
    output_db: Path,
    latest_output: Path,
    latest_metrics_output: Path,
    monthly_dates: dict[tuple[str, str], str],
    latest_dates: dict[str, str],
    symbol_map: dict[str, str],
    allowed_symbols: set[str] | None,
    chunksize: int,
) -> dict:
    output_db.parent.mkdir(parents=True, exist_ok=True)
    latest_output.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        output_db.unlink()

    monthly_inserted = 0
    latest_frames: list[pd.DataFrame] = []
    written_monthly_keys: set[tuple[str, str]] = set()

    with sqlite3.connect(output_db) as conn:
        for path, chunk in iter_csv_chunks(files, chunksize, RAW_COLUMNS):
            frame = add_normalized_keys(chunk, symbol_map, allowed_symbols)
            if frame.empty:
                continue

            monthly_mask = [
                monthly_dates.get((symbol, period)) == trading_date
                for symbol, period, trading_date in frame[["symbol", "period", "trading_date_str"]].itertuples(index=False)
            ]
            monthly_frame = frame.loc[monthly_mask]
            if not monthly_frame.empty:
                output = transform_output_frame(monthly_frame, path.name)
                output = output.drop_duplicates(subset=["symbol", "period"], keep="last")
                keys = list(output[["symbol", "period"]].itertuples(index=False, name=None))
                keep_mask = [key not in written_monthly_keys for key in keys]
                output = output.loc[keep_mask]
                written_monthly_keys.update(keys[index] for index, keep in enumerate(keep_mask) if keep)
            if not monthly_frame.empty and not output.empty:
                output.to_sql("monthly_snapshots", conn, if_exists="append", index=False)
                monthly_inserted += len(output)

            latest_mask = [
                latest_dates.get(symbol) == trading_date
                for symbol, trading_date in frame[["symbol", "trading_date_str"]].itertuples(index=False)
            ]
            latest_frame = frame.loc[latest_mask]
            if not latest_frame.empty:
                latest_frames.append(transform_output_frame(latest_frame, path.name))

        if latest_frames:
            latest_output_frame = (
                pd.concat(latest_frames, ignore_index=True)
                .sort_values(["symbol", "trading_date"])
                .drop_duplicates(subset=["symbol"], keep="last")
                .reset_index(drop=True)
            )
        else:
            latest_output_frame = pd.DataFrame(columns=OUTPUT_COLUMNS)

        latest_output_frame.to_sql("latest_snapshot", conn, if_exists="replace", index=False)
        latest_output_frame.to_csv(latest_output, index=False, encoding="utf-8-sig")
        latest_metrics_stats = write_latest_non_null_metrics(conn, latest_metrics_output)
        write_metadata(
            conn,
            files,
            monthly_inserted,
            len(latest_output_frame),
            latest_metrics_stats["rows"],
        )
        create_indexes(conn)

    return {
        "monthly_rows": monthly_inserted,
        "latest_rows": len(latest_output_frame),
        "latest_min_date": latest_output_frame["trading_date"].min() if not latest_output_frame.empty else None,
        "latest_max_date": latest_output_frame["trading_date"].max() if not latest_output_frame.empty else None,
        "latest_metrics_rows": latest_metrics_stats["rows"],
        "latest_metrics_dividend_yield_rows": latest_metrics_stats["dividend_yield_rows"],
    }


def write_latest_non_null_metrics(
    conn: sqlite3.Connection,
    latest_metrics_output: Path,
) -> dict:
    latest_base = pd.read_sql_query(
        "SELECT symbol, stkcd, short_name FROM latest_snapshot ORDER BY symbol",
        conn,
    )
    if latest_base.empty:
        latest_base.to_sql("latest_non_null_metrics", conn, if_exists="replace", index=False)
        latest_base.to_csv(latest_metrics_output, index=False, encoding="utf-8-sig")
        return {"rows": 0, "dividend_yield_rows": 0}

    result = latest_base.copy()
    for metric in METRIC_COLUMNS:
        metric_rows = pd.read_sql_query(
            f"""
            SELECT symbol, trading_date AS {metric}_date, {metric}
            FROM monthly_snapshots
            WHERE {metric} IS NOT NULL
            ORDER BY symbol, trading_date
            """,
            conn,
        )
        if metric_rows.empty:
            result[metric] = pd.NA
            result[f"{metric}_date"] = pd.NA
            continue
        latest_metric = metric_rows.groupby("symbol", as_index=False).tail(1)
        result = result.merge(latest_metric, on="symbol", how="left")

    result.to_sql("latest_non_null_metrics", conn, if_exists="replace", index=False)
    latest_metrics_output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(latest_metrics_output, index=False, encoding="utf-8-sig")

    return {
        "rows": len(result),
        "dividend_yield_rows": int(result["dividend_yield"].notna().sum()),
    }


def write_metadata(
    conn: sqlite3.Connection,
    files: list[Path],
    monthly_rows: int,
    latest_rows: int,
    latest_metrics_rows: int,
) -> None:
    metadata = pd.DataFrame(
        [
            {"key": "build_date", "value": date.today().isoformat()},
            {"key": "monthly_rows", "value": str(monthly_rows)},
            {"key": "latest_rows", "value": str(latest_rows)},
            {"key": "latest_metrics_rows", "value": str(latest_metrics_rows)},
            {"key": "source_file_count", "value": str(len(files))},
            {
                "key": "source_files",
                "value": ";".join(str(path) for path in files),
            },
        ]
    )
    metadata.to_sql("metadata", conn, if_exists="replace", index=False)


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_monthly_symbol_date "
        "ON monthly_snapshots(symbol, trading_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_monthly_symbol_period "
        "ON monthly_snapshots(symbol, period)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_latest_symbol "
        "ON latest_snapshot(symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_latest_metrics_symbol "
        "ON latest_non_null_metrics(symbol)"
    )


def write_report(
    report_output: Path,
    *,
    input_root: Path,
    output_db: Path,
    latest_output: Path,
    latest_metrics_output: Path,
    files: list[Path],
    stats: dict,
    write_stats: dict,
    monthly_dates: dict[tuple[str, str], str],
    latest_dates: dict[str, str],
) -> None:
    report_output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CSMAR Daily Derived Snapshot Build Report",
        "",
        f"- build_date: {date.today().isoformat()}",
        f"- input_root: `{input_root}`",
        f"- output_db: `{output_db}`",
        f"- latest_output: `{latest_output}`",
        f"- latest_metrics_output: `{latest_metrics_output}`",
        f"- source_file_count: {len(files)}",
        f"- raw_rows_scanned: {stats['raw_rows']}",
        f"- raw_symbol_count: {len(stats['raw_symbols'])}",
        f"- kept_rows_seen: {stats['kept_rows_seen']}",
        f"- kept_symbol_count: {len(stats['kept_symbols'])}",
        f"- raw_min_date: {stats['raw_min_date']}",
        f"- raw_max_date: {stats['raw_max_date']}",
        f"- monthly_snapshot_keys: {len(monthly_dates)}",
        f"- latest_snapshot_keys: {len(latest_dates)}",
        f"- monthly_rows_written: {write_stats['monthly_rows']}",
        f"- latest_rows_written: {write_stats['latest_rows']}",
        f"- latest_metrics_rows_written: {write_stats['latest_metrics_rows']}",
        f"- latest_metrics_dividend_yield_rows: {write_stats['latest_metrics_dividend_yield_rows']}",
        f"- latest_min_date: {write_stats['latest_min_date']}",
        f"- latest_max_date: {write_stats['latest_max_date']}",
        "",
        "## Tables",
        "",
        "- `monthly_snapshots`: one last-available trading row per symbol per calendar month.",
        "- `latest_snapshot`: latest available row per symbol.",
        "- `latest_non_null_metrics`: latest non-null value and value date for each metric per symbol.",
        "- `metadata`: build metadata.",
        "",
        "## Field Notes",
        "",
        "- `dividend_yield` is stored as a decimal ratio. Raw CSMAR `Ret` is percent and is divided by 100.",
        "- `pe`, `pb`, `pcf`, and `ps` are raw CSMAR multiples.",
        "- `CirculatedMarketValue` is stored as `circulated_market_value`.",
    ]
    report_output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root)
    output_db = Path(args.output_db)
    latest_output = Path(args.latest_output)
    latest_metrics_output = Path(args.latest_metrics_output)
    report_output = Path(args.report_output)
    industry_db = Path(args.industry_db)

    files = discover_csv_files(input_root)
    symbol_map = load_symbol_map(industry_db)
    allowed_symbols = set(symbol_map.values()) if symbol_map else None

    monthly_dates, latest_dates, stats = collect_snapshot_dates(
        files,
        symbol_map=symbol_map,
        allowed_symbols=allowed_symbols,
        chunksize=args.chunksize,
    )
    write_stats = write_snapshots(
        files,
        output_db=output_db,
        latest_output=latest_output,
        latest_metrics_output=latest_metrics_output,
        monthly_dates=monthly_dates,
        latest_dates=latest_dates,
        symbol_map=symbol_map,
        allowed_symbols=allowed_symbols,
        chunksize=args.chunksize,
    )
    write_report(
        report_output,
        input_root=input_root,
        output_db=output_db,
        latest_output=latest_output,
        latest_metrics_output=latest_metrics_output,
        files=files,
        stats=stats,
        write_stats=write_stats,
        monthly_dates=monthly_dates,
        latest_dates=latest_dates,
    )

    print(f"Built {output_db}")
    print(f"Latest CSV: {latest_output}")
    print(f"Latest metrics CSV: {latest_metrics_output}")
    print(f"Report: {report_output}")
    print(
        f"monthly_rows={write_stats['monthly_rows']} "
        f"latest_rows={write_stats['latest_rows']} "
        f"latest_metrics_rows={write_stats['latest_metrics_rows']}"
    )


if __name__ == "__main__":
    main()
