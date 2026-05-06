"""QMT 实时行情查询 — 供观察池条件触发器使用。

策略：QMT get_full_tick() 实时行情优先 → get_market_data_ex() 最近 2 日日线 fallback。
"""

from datetime import date, timedelta


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise RuntimeError("QMT/xtquant 不可用。请确认已在 Windows 环境安装 QMT 客户端和 xtquant。") from exc
    return xtdata


def get_latest_price_data(symbol: str) -> dict | None:
    """获取单个标的最新行情数据。

    Returns:
        {"close": float, "prev_close": float, "volume": float,
         "change_pct": float, "volume_ratio": float} 或 None（QMT 不可用）
    """
    xtdata = _import_xtdata()

    # 1. 尝试 get_full_tick() 实时行情
    try:
        tick = xtdata.get_full_tick([symbol])
        if tick and symbol in tick:
            data = tick[symbol]
            last_price = data.get("lastPrice", 0)
            last_close = data.get("lastClose", 0)
            volume = data.get("volume", 0)
            if last_price and last_close and last_close > 0:
                return {
                    "close": float(last_price),
                    "prev_close": float(last_close),
                    "volume": float(volume) if volume else 0,
                    "change_pct": (float(last_price) / float(last_close) - 1) * 100,
                    "volume_ratio": 1.0,  # get_full_tick 不含历史均量
                }
    except Exception:
        pass

    # 2. Fallback: 取最近 2 日日线
    try:
        today = date.today()
        start = (today - timedelta(days=10)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        raw = xtdata.get_market_data_ex(
            field_list=["time", "close", "volume"],
            stock_list=[symbol],
            period="1d",
            start_time=start,
            end_time=end,
            count=-1,
            dividend_type="front",
            fill_data=True,
        )
        if symbol not in raw:
            return None
        df = raw[symbol]
        if df is None or len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        latest_close = float(latest["close"])
        prev_close = float(prev["close"])
        latest_vol = float(latest["volume"]) if "volume" in latest else 0
        prev_vol = float(prev["volume"]) if "volume" in prev else 1
        if prev_close <= 0:
            return None
        change_pct = (latest_close / prev_close - 1) * 100
        vol_ratio = latest_vol / prev_vol if prev_vol > 0 else 1.0
        return {
            "close": latest_close,
            "prev_close": prev_close,
            "volume": latest_vol,
            "change_pct": change_pct,
            "volume_ratio": vol_ratio,
        }
    except Exception:
        return None
