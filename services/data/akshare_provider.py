import numbers
from datetime import date, datetime, timedelta

import pandas as pd

from services.data.market_data_utils import (
    build_price_data_from_frame,
    build_price_source_metadata,
    guess_asset_type,
    strip_exchange_suffix,
    to_prefixed_symbol,
)
from services.network.proxy_policy import disable_proxy_for_current_process

disable_proxy_for_current_process()


def get_company_name_akshare(symbol: str) -> str | None:
    """通过 AKShare stock_individual_info_em 获取公司名称。

    Args:
        symbol: 股票代码，如 600519.SH

    Returns:
        公司名称字符串，获取失败返回 None
    """
    try:
        import akshare as ak
        code = symbol.split(".")[0]
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return None
        # DataFrame 有 item/value 两列，查找"股票简称"或"名称"行
        item_col = None
        value_col = None
        for col in df.columns:
            col_str = str(col).strip().lower()
            if col_str in ("item", "项目", "指标"):
                item_col = col
            elif col_str in ("value", "值", "数值"):
                value_col = col
        if item_col is None or value_col is None:
            return None
        for _, row in df.iterrows():
            item = str(row[item_col]).strip()
            if item in ("股票简称", "证券简称", "名称", "简称"):
                return str(row[value_col]).strip()
        return None
    except Exception:
        return None

import akshare as ak  # noqa: E402  # Proxy policy must be applied before importing akshare.


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_columns = {str(column).lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_columns:
            return lower_columns[candidate.lower()]
    return None


def _parse_trade_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, numbers.Integral):
        raw_int = int(value)
        if 1990_01_01 <= raw_int <= 2099_12_31:
            try:
                return datetime.strptime(str(raw_int), "%Y%m%d").date()
            except ValueError:
                return None
    if isinstance(value, str):
        value = value.strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    try:
        timestamp = pd.Timestamp(value)
        if timestamp is not pd.NaT:
            return timestamp.date()
    except Exception:
        return None
    return None


def _extract_latest_trade_date(df: pd.DataFrame, close_col: str) -> date | None:
    if df.empty or close_col not in df.columns:
        return None

    valid = df[df[close_col].notna()]
    if valid.empty:
        return None

    date_col = _find_column(df, ["time", "\u65e5\u671f", "date", "trade_date"])
    if date_col and date_col in valid.columns:
        parsed = _parse_trade_date(valid[date_col].iloc[-1])
        if parsed is not None:
            return parsed

    return _parse_trade_date(valid.index[-1])


def _load_price_history(symbol: str, asset_type: str) -> pd.DataFrame:
    """
    从 AKShare 获取最近约一年的日线行情。

    股票：
    1. 优先东财 stock_zh_a_hist
    2. 失败后用腾讯 stock_zh_a_hist_tx
    3. 再失败用新浪 stock_zh_a_daily

    ETF：
    暂时仍使用 fund_etf_hist_em
    """
    code = strip_exchange_suffix(symbol)
    prefixed_symbol = to_prefixed_symbol(symbol)

    end_date = date.today()
    start_date = end_date - timedelta(days=420)

    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")

    if asset_type == "etf":
        return ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )

    errors = []

    # 1. 东财接口
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            df["data_vendor"] = "eastmoney"
            return df
    except Exception as exc:
        errors.append(f"eastmoney stock_zh_a_hist failed: {exc}")

    # 2. 腾讯接口
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=prefixed_symbol,
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            df["data_vendor"] = "tencent"
            return df
    except Exception as exc:
        errors.append(f"tencent stock_zh_a_hist_tx failed: {exc}")

    # 3. 新浪接口
    try:
        df = ak.stock_zh_a_daily(
            symbol=prefixed_symbol,
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            df["data_vendor"] = "sina"
            return df
    except Exception as exc:
        errors.append(f"sina stock_zh_a_daily failed: {exc}")

    raise RuntimeError(
        "AKShare 所有股票行情接口均获取失败：\n" + "\n".join(errors)
    )


def get_akshare_asset_data(symbol: str) -> dict:
    """
    使用 AKShare 获取公开行情。
    AKShare 在当前设计里只作为 QMT 不可用时的 fallback 或离线开发数据源。
    基本面、估值、事件数据不在这里伪造，由 orchestrator 单独补低置信度占位数据。
    """

    asset_type = guess_asset_type(symbol)
    df = _load_price_history(symbol, asset_type)

    # AKShare 东财接口通常是中文列名
    df = df.copy()

    if "收盘" in df.columns:
        close_col = "收盘"
    elif "close" in df.columns:
        close_col = "close"
    else:
        raise RuntimeError(f"行情数据缺少收盘价字段，当前字段：{list(df.columns)}")

    if "成交额" in df.columns:
        amount_col = "成交额"
    elif "amount" in df.columns:
        amount_col = "amount"
    else:
        amount_col = None

    data_vendor = str(df["data_vendor"].iloc[0]) if "data_vendor" in df.columns else "unknown"
    price_data = build_price_data_from_frame(
        df=df,
        close_col=close_col,
        amount_col=amount_col,
        data_vendor=data_vendor,
    )
    latest_trade_date = _extract_latest_trade_date(df, close_col)
    price_data["latest_trade_date"] = (
        str(latest_trade_date) if latest_trade_date else None
    )
    price_data["latest_price_source"] = "akshare"
    price_data["price_history_source"] = "akshare"
    price_data["price_uses_intraday_tick"] = False

    name = f"{strip_exchange_suffix(symbol)} ETF" if asset_type == "etf" else symbol

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "name": name,
        "as_of": str(date.today()),
        "data_source": "akshare",
        "price_data": price_data,
        "source_metadata": {
            "price_data": build_price_source_metadata(
                source="akshare",
                confidence=0.7,
                vendor=data_vendor,
            )
        },
        "provider_run_log": [
            {
                "provider": "akshare",
                "dataset": "price_data",
                "symbol": symbol,
                "status": "success",
                "rows": len(df),
                "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
                "error": None,
                "error_type": None,
                "as_of": str(date.today()),
            }
        ],
    }
