from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "Stkcd",
    "Stknme",
    "Listdt",
    "Conme",
    "Nnindcd",
    "Nnindnme",
    "IndcdZX",
    "IndnmeZX",
    "PROVINCE",
    "CITY",
    "OWNERSHIPTYPE",
    "Curtrd",
    "Sctcd",
    "Statco",
    "Statdt",
    "Markettype",
}

MARKET_TYPES = {
    "sh_sz": {"1", "4", "16", "32"},
    "sh_sz_bj": {"1", "4", "16", "32", "64"},
}

EXCHANGE_BY_SCTCD = {
    "1": "SH",
    "2": "SZ",
    "3": "BJ",
}

BOARD_BY_MARKET_TYPE = {
    "1": "sh_main",
    "4": "sz_main",
    "16": "chinext",
    "32": "star",
    "64": "bj",
}

SECTION_NAMES = {
    "A": "agriculture",
    "B": "mining",
    "C": "manufacturing",
    "D": "utilities",
    "E": "construction",
    "F": "wholesale_retail",
    "G": "transport_storage_post",
    "H": "lodging_catering",
    "I": "information_technology",
    "J": "finance",
    "K": "real_estate",
    "L": "leasing_business_services",
    "M": "science_technology_services",
    "N": "water_environment_public_facilities",
    "O": "resident_services",
    "P": "education",
    "Q": "health_social_work",
    "R": "culture_sports_entertainment",
    "S": "composite",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local CSMAR TRD_Co industry reference SQLite database."
    )
    parser.add_argument(
        "--input",
        default="data/raw/csmar/TRD_Co.csv",
        help="Path to TRD_Co.csv.",
    )
    parser.add_argument(
        "--output",
        default="storage/reference/csmar_industry.sqlite",
        help="Output SQLite path.",
    )
    parser.add_argument(
        "--report",
        default="storage/reference/csmar_industry_build_report.md",
        help="Output build report path.",
    )
    parser.add_argument(
        "--universe",
        choices=sorted(MARKET_TYPES),
        default="sh_sz_bj",
        help="A-share universe to keep.",
    )
    parser.add_argument(
        "--include-status",
        default="A,N",
        help="Comma-separated Statco values to keep. Default keeps active and special active records.",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_code(value: object) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        text = str(int(float(text)))
    except ValueError:
        text = text.strip()
    return text.zfill(6)


def normalize_discrete(value: object) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def build_symbol(stkcd: str | None, sctcd: str | None) -> str | None:
    if stkcd is None:
        return None
    exchange = EXCHANGE_BY_SCTCD.get(str(sctcd))
    if exchange is None:
        return None
    return f"{stkcd}.{exchange}"


def row_hash(row: pd.Series) -> str:
    values = ["" if pd.isna(value) else str(value) for value in row.tolist()]
    return hashlib.sha1("|".join(values).encode("utf-8")).hexdigest()


def load_and_clean(
    input_path: Path,
    universe: str,
    include_status: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    raw = pd.read_csv(input_path, encoding="utf-8-sig", dtype=str)
    missing = sorted(REQUIRED_COLUMNS - set(raw.columns))
    if missing:
        raise SystemExit(f"TRD_Co.csv missing required columns: {', '.join(missing)}")

    source_hash = file_sha256(input_path)
    snapshot_date = date.today().isoformat()
    df = raw.copy()

    df["_stkcd"] = df["Stkcd"].map(normalize_code)
    df["_sctcd"] = df["Sctcd"].map(normalize_discrete)
    df["_market_type"] = df["Markettype"].map(normalize_discrete)
    df["_status_code"] = df["Statco"].map(normalize_text)
    df["_curtrd"] = df["Curtrd"].map(normalize_text)
    df["_symbol"] = [
        build_symbol(stkcd, sctcd)
        for stkcd, sctcd in zip(df["_stkcd"], df["_sctcd"], strict=False)
    ]
    df["_exchange"] = df["_sctcd"].map(EXCHANGE_BY_SCTCD)
    df["_primary_code"] = df["IndcdZX"].map(normalize_text)
    df["_primary_name"] = df["IndnmeZX"].map(normalize_text)
    df["_alt_code"] = df["Nnindcd"].map(normalize_text)
    df["_alt_name"] = df["Nnindnme"].map(normalize_text)
    df["_section_code"] = df["_primary_code"].map(
        lambda value: value[0].upper() if isinstance(value, str) and value else None
    )
    df["_section_name"] = df["_section_code"].map(SECTION_NAMES)

    market_types = MARKET_TYPES[universe]
    is_a_share = df["_curtrd"].eq("CNY") & df["_market_type"].isin(market_types)
    is_active = df["_status_code"].isin(include_status)
    cleaned = df.loc[is_a_share & is_active & df["_symbol"].notna()].copy()

    cleaned["source_row_hash"] = cleaned[raw.columns].apply(row_hash, axis=1)
    cleaned["is_st_name"] = cleaned["Stknme"].fillna("").str.upper().str.contains("ST")
    cleaned["is_delisted"] = cleaned["_status_code"].eq("D")
    cleaned["is_active"] = cleaned["_status_code"].isin(include_status)
    cleaned["is_a_share"] = True

    securities = pd.DataFrame(
        {
            "symbol": cleaned["_symbol"],
            "symbol_qmt": cleaned["_symbol"],
            "stkcd": cleaned["_stkcd"],
            "exchange": cleaned["_exchange"],
            "market_type": cleaned["_market_type"],
            "board": cleaned["_market_type"].map(BOARD_BY_MARKET_TYPE),
            "short_name": cleaned["Stknme"].map(normalize_text),
            "company_name": cleaned["Conme"].map(normalize_text),
            "list_date": cleaned["Listdt"].map(normalize_text),
            "status_code": cleaned["_status_code"],
            "status_date": cleaned["Statdt"].map(normalize_text),
            "is_active": cleaned["is_active"].astype(int),
            "is_delisted": cleaned["is_delisted"].astype(int),
            "is_a_share": cleaned["is_a_share"].astype(int),
            "is_st_name": cleaned["is_st_name"].astype(int),
            "primary_industry_code": cleaned["_primary_code"],
            "primary_industry_name": cleaned["_primary_name"],
            "alt_industry_code": cleaned["_alt_code"],
            "alt_industry_name": cleaned["_alt_name"],
            "industry_section_code": cleaned["_section_code"],
            "industry_section_name": cleaned["_section_name"],
            "province": cleaned["PROVINCE"].map(normalize_text),
            "city": cleaned["CITY"].map(normalize_text),
            "ownership_type": cleaned["OWNERSHIPTYPE"].map(normalize_text),
            "source_file": input_path.name,
            "source_hash": source_hash,
            "source_row_hash": cleaned["source_row_hash"],
            "snapshot_date": snapshot_date,
        }
    )

    zx_members = securities.loc[
        securities["primary_industry_code"].notna(),
        [
            "symbol",
            "short_name",
            "is_active",
            "is_st_name",
            "board",
            "primary_industry_code",
            "primary_industry_name",
        ],
    ].rename(
        columns={
            "primary_industry_code": "industry_code",
            "primary_industry_name": "industry_name",
        }
    )
    zx_members.insert(0, "industry_level", "CSMAR_ZX")

    section_members = securities.loc[
        securities["industry_section_code"].notna(),
        [
            "symbol",
            "short_name",
            "is_active",
            "is_st_name",
            "board",
            "industry_section_code",
            "industry_section_name",
        ],
    ].rename(
        columns={
            "industry_section_code": "industry_code",
            "industry_section_name": "industry_name",
        }
    )
    section_members.insert(0, "industry_level", "CSMAR_SECTION")

    industry_members = pd.concat([zx_members, section_members], ignore_index=True)

    metadata = {
        "source_file": str(input_path),
        "source_hash": source_hash,
        "build_date": snapshot_date,
        "raw_rows": str(len(raw)),
        "active_a_share_rows": str(len(securities)),
        "industry_count": str(securities["primary_industry_code"].nunique()),
        "section_count": str(securities["industry_section_code"].nunique()),
        "universe": universe,
        "include_status": ",".join(sorted(include_status)),
        "missing_primary_industry_rows": str(securities["primary_industry_code"].isna().sum()),
        "missing_section_rows": str(securities["industry_section_code"].isna().sum()),
    }

    stats = {
        "metadata": metadata,
        "status_counts": raw["Statco"].fillna("<NA>").value_counts().to_dict(),
        "market_counts": raw["Markettype"].fillna("<NA>").value_counts().to_dict(),
    }
    return securities, industry_members, stats


def write_sqlite(output_path: Path, securities: pd.DataFrame, industry_members: pd.DataFrame, metadata: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with sqlite3.connect(output_path) as connection:
        securities.to_sql("securities", connection, index=False)
        industry_members.to_sql("industry_members", connection, index=False)
        pd.DataFrame(
            [{"key": key, "value": value} for key, value in metadata.items()]
        ).to_sql("metadata", connection, index=False)
        connection.execute("CREATE UNIQUE INDEX idx_securities_symbol ON securities(symbol)")
        connection.execute(
            "CREATE INDEX idx_industry_members_level_code ON industry_members(industry_level, industry_code)"
        )
        connection.execute("CREATE INDEX idx_industry_members_symbol ON industry_members(symbol)")


def write_report(report_path: Path, output_path: Path, stats: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = stats["metadata"]
    lines = [
        "# CSMAR Industry Reference Build Report",
        "",
        f"- output: `{output_path}`",
        f"- source_file: `{metadata['source_file']}`",
        f"- source_hash: `{metadata['source_hash']}`",
        f"- build_date: `{metadata['build_date']}`",
        f"- raw_rows: {metadata['raw_rows']}",
        f"- active_a_share_rows: {metadata['active_a_share_rows']}",
        f"- industry_count: {metadata['industry_count']}",
        f"- section_count: {metadata['section_count']}",
        f"- universe: {metadata['universe']}",
        f"- include_status: {metadata['include_status']}",
        f"- missing_primary_industry_rows: {metadata['missing_primary_industry_rows']}",
        "",
        "## Statco Counts",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in stats["status_counts"].items())
    lines.extend(["", "## Markettype Counts", ""])
    lines.extend(f"- {key}: {value}" for key, value in stats["market_counts"].items())
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report)
    include_status = {
        item.strip()
        for item in args.include_status.split(",")
        if item.strip()
    }

    securities, industry_members, stats = load_and_clean(
        input_path=input_path,
        universe=args.universe,
        include_status=include_status,
    )
    write_sqlite(output_path, securities, industry_members, stats["metadata"])
    write_report(report_path, output_path, stats)
    print(f"Built {output_path} with {len(securities)} securities")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
