from datetime import date, timedelta
from typing import Any

import pandas as pd

from services.data.market_data_utils import (
    build_price_data_from_frame,
    build_price_source_metadata,
    guess_asset_type,
    normalize_symbol,
)


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise RuntimeError(
            "QMT/xtquant 不可用。请确认已在 Windows 环境安装 QMT 客户端和 xtquant。"
        ) from exc

    return xtdata


def _format_qmt_time(value: date) -> str:
    return value.strftime("%Y%m%d")


def _load_qmt_daily_history(symbol: str) -> pd.DataFrame:
    """
    Load daily K-line data from local QMT.

    Expected fields are close and amount. Different xtquant versions may return
    either a dict of DataFrames or a field-indexed object, so this function is
    deliberately defensive.
    """
    xtdata = _import_xtdata()

    end_date = date.today()
    start_date = end_date - timedelta(days=420)

    raw = xtdata.get_market_data_ex(
        field_list=["time", "close", "amount", "volume"],
        stock_list=[symbol],
        period="1d",
        start_time=_format_qmt_time(start_date),
        end_time=_format_qmt_time(end_date),
        count=-1,
        dividend_type="front",
        fill_data=True,
    )

    if isinstance(raw, dict):
        if symbol in raw:
            df = raw[symbol]
        elif raw:
            df = next(iter(raw.values()))
        else:
            raise RuntimeError(f"QMT 未返回行情数据：{symbol}")
    else:
        df = raw

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    if df.empty:
        raise RuntimeError(f"QMT 行情数据为空：{symbol}")

    df = df.copy()
    df["data_vendor"] = "qmt"
    return df


def _load_qmt_instrument_detail(symbol: str) -> dict[str, Any]:
    xtdata = _import_xtdata()

    try:
        detail = xtdata.get_instrument_detail(symbol)
    except Exception:
        detail = None

    if not isinstance(detail, dict):
        return {}

    return detail


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_columns = {str(column).lower(): column for column in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_columns:
            return lower_columns[candidate.lower()]

    return None


def get_qmt_asset_data(symbol: str) -> dict:
    """
    Primary data provider for production research.

    The first version connects daily K-line data, basic instrument details and
    turnover amount. Fundamental, valuation and event data are intentionally not
    fabricated here; the orchestrator adds low-confidence placeholders until
    real QMT/fundamental feeds are connected.
    """
    asset_type = guess_asset_type(symbol)
    df = _load_qmt_daily_history(symbol)
    detail = _load_qmt_instrument_detail(symbol)

    close_col = _find_column(df, ["close", "收盘"])
    if not close_col:
        raise RuntimeError(f"QMT 行情数据缺少 close 字段，当前字段：{list(df.columns)}")

    amount_col = _find_column(df, ["amount", "成交额"])

    price_data = build_price_data_from_frame(
        df=df,
        close_col=close_col,
        amount_col=amount_col,
        data_vendor="qmt",
    )

    name = (
        detail.get("InstrumentName")
        or detail.get("instrument_name")
        or detail.get("name")
        or (f"{normalize_symbol(symbol)} ETF" if asset_type == "etf" else symbol)
    )

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "name": name,
        "as_of": str(date.today()),
        "data_source": "qmt",
        "price_data": price_data,
        "basic_info": {
            "exchange_id": detail.get("ExchangeID") or detail.get("exchange_id"),
            "product_id": detail.get("ProductID") or detail.get("product_id"),
            "instrument_id": detail.get("InstrumentID") or detail.get("instrument_id"),
        },
        "source_metadata": {
            "price_data": build_price_source_metadata(
                source="qmt",
                confidence=0.95,
                vendor="qmt",
            ),
            "basic_info": {
                "source": "qmt",
                "confidence": 0.9 if detail else 0.0,
                "as_of": str(date.today()),
            },
        },
    }
