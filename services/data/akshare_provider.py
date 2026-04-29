from datetime import date, timedelta

from services.network.proxy_policy import disable_proxy_for_current_process

disable_proxy_for_current_process()

import akshare as ak
import pandas as pd

from services.data.market_data_utils import (
    build_price_data_from_frame,
    build_price_source_metadata,
    guess_asset_type,
    normalize_symbol,
    to_prefixed_symbol,
)


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
    code = normalize_symbol(symbol)
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

    name = f"{normalize_symbol(symbol)} ETF" if asset_type == "etf" else symbol

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
    }
