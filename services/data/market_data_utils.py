from datetime import date

import pandas as pd


def normalize_symbol(symbol: str) -> str:
    return symbol.split(".")[0]


def guess_asset_type(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if code.startswith(("51", "56", "58", "15", "16", "18")):
        return "etf"
    return "stock"


def to_prefixed_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)

    if symbol.endswith(".SH"):
        return f"sh{code}"
    if symbol.endswith(".SZ"):
        return f"sz{code}"
    if symbol.endswith(".BJ"):
        return f"bj{code}"

    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"

    return code


def calc_max_drawdown(close_series: pd.Series) -> float:
    rolling_max = close_series.cummax()
    drawdown = close_series / rolling_max - 1
    return float(drawdown.min())


def build_price_data_from_frame(
    df: pd.DataFrame,
    close_col: str,
    amount_col: str | None,
    data_vendor: str,
) -> dict:
    data = df.copy()
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")

    if amount_col:
        data[amount_col] = pd.to_numeric(data[amount_col], errors="coerce")

    data = data.dropna(subset=[close_col])

    if len(data) < 60:
        raise RuntimeError("行情数据不足 60 个交易日")

    close = data[close_col]
    returns = close.pct_change().dropna()
    latest_close = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())

    avg_turnover_20d = 0.0
    if amount_col:
        avg_turnover_20d = float(data[amount_col].tail(20).mean())

    return {
        "close": latest_close,
        "change_20d": float(close.iloc[-1] / close.iloc[-21] - 1),
        "change_60d": float(close.iloc[-1] / close.iloc[-61] - 1),
        "ma20_position": "above" if latest_close >= ma20 else "below",
        "ma60_position": "above" if latest_close >= ma60 else "below",
        "max_drawdown_60d": calc_max_drawdown(close.tail(60)),
        "volatility_60d": float(returns.tail(60).std() * (252 ** 0.5)),
        "avg_turnover_20d": avg_turnover_20d,
        "data_vendor": data_vendor,
        "history_close": [float(v) for v in close.tolist() if pd.notna(v)],
    }


def build_price_source_metadata(source: str, confidence: float, vendor: str) -> dict:
    return {
        "source": source,
        "confidence": confidence,
        "as_of": str(date.today()),
        "vendor": vendor,
    }
