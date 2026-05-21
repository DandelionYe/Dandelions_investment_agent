"""Build EVA_Structure reference SQLite from raw CSMAR CSV.

Reads data/raw/csmar/EVA_Structure.csv and produces:
  - storage/reference/csmar_eva_structure.sqlite
  - storage/reference/csmar_eva_structure_build_report.md

Tables:
  eva_structure_history  (all cleaned rows)
  eva_structure_latest   (one row per symbol, latest EndDate)
  metadata               (build stats)
"""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RAW_CSV = "data/raw/csmar/EVA_Structure.csv"
OUTPUT_DB = "storage/reference/csmar_eva_structure.sqlite"
OUTPUT_REPORT = "storage/reference/csmar_eva_structure_build_report.md"
INDUSTRY_DB = "storage/reference/csmar_industry.sqlite"


def _symbol_to_stkcd(raw: str) -> str:
    """Normalize raw CSMAR Symbol to 6-digit stock code."""
    return raw.strip().zfill(6)


def _stkcd_to_qmt(stkcd: str) -> str | None:
    """Convert 6-digit code to QMT format (600519.SH / 002624.SZ).

    Returns None for codes that don't map to SH/SZ/BJ stocks.
    """
    if len(stkcd) != 6 or not stkcd.isdigit():
        return None
    prefix = stkcd[:1]
    prefix2 = stkcd[:2]
    prefix3 = stkcd[:3]

    # SH: 60xxxx, 68xxxx, 900xxx (B股)
    if prefix == "6":
        return f"{stkcd}.SH"
    # SZ: 00xxxx, 30xxxx, 002xxx, 200xxx (B股)
    if prefix in ("0", "3", "2"):
        return f"{stkcd}.SZ"
    # BJ: 43xxxx, 83xxxx, 87xxxx, 92xxxx
    if prefix2 in ("43", "83", "87") or prefix3 == "920":
        return f"{stkcd}.BJ"

    return None


def _safe_float(value: str) -> float | None:
    """Parse a numeric string, returning None for empty/invalid."""
    text = value.strip() if value else ""
    if not text or text in ("--", "-", "nan", "None", ""):
        return None
    try:
        result = float(text)
    except (ValueError, TypeError):
        return None
    # Reject scientific notation that pandas may produce for very large numbers
    # but still accept normal floats
    return result


def _parse_end_date(raw: str) -> str | None:
    """Parse '2026/3/31' -> '2026-03-31' ISO format."""
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y/%m/%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None


def build() -> None:
    raw_path = RAW_CSV
    if not Path(raw_path).exists():
        logger.error("Source CSV not found: %s", raw_path)
        return

    # Ensure output directory exists
    Path(OUTPUT_DB).parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB
    if Path(OUTPUT_DB).exists():
        os.remove(OUTPUT_DB)
        logger.info("Removed existing %s", OUTPUT_DB)

    conn = sqlite3.connect(OUTPUT_DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE eva_structure_history (
            symbol TEXT NOT NULL,
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
            income_tax_rate REAL,
            PRIMARY KEY (symbol, end_date)
        )
    """)
    cur.execute("CREATE INDEX idx_eva_history_stkcd ON eva_structure_history(stkcd)")

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

    cur.execute("""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Read and process CSV
    raw_count = 0
    clean_count = 0
    latest_map: dict[str, tuple] = {}  # symbol -> (end_date, row_data)
    end_date_counter: Counter = Counter()

    with open(raw_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_count += 1
            raw_symbol = row["Symbol"].strip()
            stkcd = _symbol_to_stkcd(raw_symbol)
            symbol = _stkcd_to_qmt(stkcd)
            if symbol is None:
                continue

            end_date = _parse_end_date(row["EndDate"])
            if end_date is None:
                continue

            total_volume = _safe_float(row.get("TotalShares"))
            float_volume = _safe_float(row.get("NegotiableShares"))
            market_cap = _safe_float(row.get("MarketValue"))
            float_market_cap = _safe_float(row.get("CirculatedMarketValue"))
            equity_per_share = _safe_float(row.get("EquityPerShare"))
            wacc = _safe_float(row.get("WACC"))
            debt = _safe_float(row.get("Debt"))
            income_tax_rate = _safe_float(row.get("IncomeTaxRate"))
            short_name = (row.get("ShortName") or "").strip()

            cur.execute(
                "INSERT OR REPLACE INTO eva_structure_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, stkcd, end_date, short_name,
                 total_volume, float_volume, market_cap, float_market_cap,
                 equity_per_share, wacc, debt, income_tax_rate),
            )
            clean_count += 1

            # Track latest per symbol
            prev = latest_map.get(symbol)
            if prev is None or end_date > prev[0]:
                latest_map[symbol] = (end_date, (
                    symbol, stkcd, end_date, short_name,
                    total_volume, float_volume, market_cap, float_market_cap,
                    equity_per_share, wacc, debt, income_tax_rate,
                ))

            year = end_date[:4]
            end_date_counter[year] += 1

    # Insert latest rows
    for _symbol, (_ed, row_data) in latest_map.items():
        cur.execute("INSERT OR REPLACE INTO eva_structure_latest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row_data)

    latest_count = len(latest_map)
    symbol_count = len(latest_map)

    # Compute stats from latest table
    ts_positive = 0
    mv_positive = 0
    for _symbol, (_ed, row_data) in latest_map.items():
        if row_data[4] is not None and row_data[4] > 0:  # total_volume
            ts_positive += 1
        if row_data[6] is not None and row_data[6] > 0:  # market_cap
            mv_positive += 1

    latest_end_date = max(ed for ed, _ in latest_map.values()) if latest_map else "N/A"

    # Metadata
    meta = {
        "build_date": datetime.now().strftime("%Y-%m-%d"),
        "source_file": RAW_CSV,
        "raw_row_count": str(raw_count),
        "clean_row_count": str(clean_count),
        "symbol_count": str(symbol_count),
        "latest_end_date": latest_end_date,
        "latest_table_rows": str(latest_count),
        "total_volume_positive": str(ts_positive),
        "market_cap_positive": str(mv_positive),
    }
    for key, value in meta.items():
        cur.execute("INSERT INTO metadata VALUES (?, ?)", (key, value))

    conn.commit()

    # Industry DB coverage
    industry_coverage = "N/A"
    if Path(INDUSTRY_DB).exists():
        try:
            iconn = sqlite3.connect(INDUSTRY_DB)
            icur = iconn.cursor()
            icur.execute("SELECT DISTINCT symbol FROM securities")
            industry_symbols = {row[0] for row in icur.fetchall()}
            iconn.close()
            eva_symbols = set(latest_map.keys())
            overlap = eva_symbols & industry_symbols
            if industry_symbols:
                pct = len(overlap) / len(industry_symbols) * 100
                industry_coverage = f"{len(overlap)}/{len(industry_symbols)} ({pct:.1f}%)"
        except Exception as exc:
            industry_coverage = f"error reading {INDUSTRY_DB}: {exc}"

    conn.close()

    # Build report
    report_lines = [
        "# EVA_Structure Build Report",
        "",
        f"- Build date: {meta['build_date']}",
        f"- Source: `{RAW_CSV}`",
        f"- Output: `{OUTPUT_DB}`",
        "",
        "## Data Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Raw rows | {raw_count:,} |",
        f"| Clean rows | {clean_count:,} |",
        f"| Unique symbols | {symbol_count:,} |",
        f"| Latest EndDate | {latest_end_date} |",
        f"| Latest table rows | {latest_count:,} |",
        f"| TotalShares > 0 | {ts_positive:,} |",
        f"| MarketValue > 0 | {mv_positive:,} |",
        f"| Industry DB coverage | {industry_coverage} |",
        "",
        "## Latest EndDate Distribution (top years)",
        "",
    ]
    for year, count in end_date_counter.most_common(5):
        report_lines.append(f"- {year}: {count:,} rows")

    report_text = "\n".join(report_lines) + "\n"
    Path(OUTPUT_REPORT).write_text(report_text, encoding="utf-8")
    logger.info("Build report written to %s", OUTPUT_REPORT)

    logger.info(
        "Done: %d raw -> %d clean rows, %d symbols, latest=%s",
        raw_count, clean_count, symbol_count, latest_end_date,
    )


if __name__ == "__main__":
    build()
