from datetime import date, timedelta
from typing import Any


def _fetch_akshare_supplement_history_close(symbol: str) -> list[float]:
    """从 AKShare 拉取个股日线收盘价序列（最多 2500 天），作为分位计算的补充数据源。

    QMT 历史收盘价不足 250 样本时调用此函数补充。
    """
    try:
        # 动态导入，避免在非 AKShare 环境（如 QMT-only）导入失败
        import akshare as ak
        from services.data.akshare_provider import normalize_symbol, to_prefixed_symbol
    except ImportError:
        return []

    code = normalize_symbol(symbol)
    prefixed = to_prefixed_symbol(symbol)
    end_date = date.today()
    start_date = end_date - timedelta(days=2500)

    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")

    df = None
    # 东财 → 腾讯 → 新浪 fallback
    for source, fetch_fn in [
        ("eastmoney", lambda: ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")),
        ("tencent", lambda: ak.stock_zh_a_hist_tx(symbol=prefixed, start_date=start, end_date=end, adjust="qfq")),
        ("sina", lambda: ak.stock_zh_a_daily(symbol=prefixed, adjust="qfq")),
    ]:
        try:
            result = fetch_fn()
            if result is not None and not result.empty:
                df = result
                break
        except Exception:
            continue

    if df is None:
        return []

    # 兼容中英文列名
    close_col = None
    for col in df.columns:
        if str(col).strip() in ("收盘", "close", "Close"):
            close_col = col
            break
    if close_col is None:
        return []

    closes = [float(v) for v in df[close_col].tolist() if v is not None and float(v) > 0]
    return closes


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _ratio(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if abs(number) > 1.5:
        return number / 100
    return number


def _first_present(row: dict, candidates: list[str]) -> Any:
    lower_map = {str(key).lower(): value for key, value in row.items()}
    for candidate in candidates:
        if candidate in row and row[candidate] not in (None, ""):
            return row[candidate]
        value = lower_map.get(candidate.lower())
        if value not in (None, ""):
            return value
    return None


def _compute_percentile(current: float, historical: list[float]) -> float:
    """Fraction of historical values that are <= current."""
    if not historical:
        return 0.5
    below = sum(1 for v in historical if v <= current)
    return below / len(historical)


def compute_percentiles_from_history(
    current_pe: float | None,
    current_pb: float | None,
    current_ps: float | None,
    history_close: list[float],
    current_close: float,
) -> dict:
    """
    Derive PE/PB/PS percentile from scaled historical price ratios.

    Approximates historical valuation multiples as:
      historical_multiple ≈ current_multiple × (historical_close / current_close)

    This assumes shares and trailing financials are roughly constant — a first-order
    approximation suitable for percentile estimation over multi-year horizons.
    """
    result: dict = {"pe_percentile": None, "pb_percentile": None, "ps_percentile": None}
    if not current_close or not history_close:
        return result

    ratios = [hc / current_close for hc in history_close]

    if current_pe is not None and current_pe > 0:
        pe_series = [current_pe * r for r in ratios]
        pe_series = [p for p in pe_series if 0 < p <= 300]
        if len(pe_series) >= 250:
            result["pe_percentile"] = round(_compute_percentile(current_pe, pe_series), 4)

    if current_pb is not None and current_pb > 0:
        pb_series = [current_pb * r for r in ratios]
        pb_series = [p for p in pb_series if 0 < p <= 50]
        if len(pb_series) >= 250:
            result["pb_percentile"] = round(_compute_percentile(current_pb, pb_series), 4)

    if current_ps is not None and current_ps > 0:
        ps_series = [current_ps * r for r in ratios]
        ps_series = [p for p in ps_series if 0 < p <= 100]
        if len(ps_series) >= 250:
            result["ps_percentile"] = round(_compute_percentile(current_ps, ps_series), 4)

    return result


class ValuationNormalizer:
    def derive_from_qmt(self, asset_data: dict) -> dict:
        price_data = asset_data.get("price_data", {})
        basic_info = asset_data.get("basic_info", {})
        fundamental = asset_data.get("fundamental_data", {})
        close = _to_float(price_data.get("close"))
        total_volume = _to_float(basic_info.get("total_volume") or basic_info.get("TotalVolume"))
        float_volume = _to_float(basic_info.get("float_volume") or basic_info.get("FloatVolume"))

        market_cap = close * total_volume if close and total_volume else None
        float_market_cap = close * float_volume if close and float_volume else None
        net_profit_ttm = _to_float(fundamental.get("net_profit_ttm"))
        revenue_ttm = _to_float(fundamental.get("revenue_ttm"))
        bps = _to_float(fundamental.get("bps"))

        pe_ttm = market_cap / net_profit_ttm if market_cap and net_profit_ttm else None
        ps_ttm = market_cap / revenue_ttm if market_cap and revenue_ttm else None
        pb_mrq = close / bps if close and bps else None

        result = {
            "trade_date": str(asset_data.get("as_of", "")).replace("-", ""),
            "pe_ttm": pe_ttm,
            "pb_mrq": pb_mrq,
            "ps_ttm": ps_ttm,
            "dividend_yield": None,
            "market_cap": market_cap,
            "float_market_cap": float_market_cap,
            "pe_percentile": None,
            "pb_percentile": None,
            "ps_percentile": None,
            "valuation_label": "unavailable" if pe_ttm is None else "derived_no_percentile",
            "valuation_growth_match": "unknown",
            "calculation_method": "derived_from_qmt_price_share_capital_and_financials",
        }

        history_close_list = price_data.get("history_close")
        if history_close_list and close:
            # QMT 主路径：基于 QMT 历史收盘价计算分位
            percentiles = compute_percentiles_from_history(
                current_pe=pe_ttm,
                current_pb=pb_mrq,
                current_ps=ps_ttm,
                history_close=history_close_list,
                current_close=close,
            )
            # AKShare 补充：如果 QMT 历史数据不足 250 样本，尝试从 AKShare 拉取更长历史
            if (percentiles.get("pe_percentile") is None
                    and percentiles.get("pb_percentile") is None
                    and len(history_close_list) < 250):
                ak_close = _fetch_akshare_supplement_history_close(
                    asset_data.get("symbol", "")
                )
                if ak_close and len(ak_close) > len(history_close_list):
                    percentiles = compute_percentiles_from_history(
                        current_pe=pe_ttm,
                        current_pb=pb_mrq,
                        current_ps=ps_ttm,
                        history_close=ak_close,
                        current_close=close,
                    )
                    if percentiles.get("pe_percentile") is not None or percentiles.get("pb_percentile") is not None:
                        result["calculation_method"] = (
                            result["calculation_method"]
                            + " + percentile_from_akshare_price_history"
                        )
                        result["percentile_n_days"] = len(ak_close)

            for key in ("pe_percentile", "pb_percentile", "ps_percentile"):
                if percentiles.get(key) is not None:
                    result[key] = percentiles[key]
            if percentiles.get("pe_percentile") is not None or percentiles.get("pb_percentile") is not None:
                if "percentile_from" not in str(result.get("calculation_method", "")):
                    result["calculation_method"] = (
                        result["calculation_method"]
                        + " + percentile_from_qmt_price_history"
                    )
                    result["percentile_n_days"] = len(history_close_list)

        return result

    def normalize_akshare(self, provider_result: dict) -> dict:
        records = provider_result.get("data", [])
        row = records[0] if records else {}
        normalized = {
            "pe_ttm": _to_float(_first_present(row, ["市盈率TTM", "市盈率(TTM)", "PE(TTM)", "pe_ttm"])),
            "pb_mrq": _to_float(_first_present(row, ["市净率", "PB", "pb_mrq"])),
            "ps_ttm": _to_float(_first_present(row, ["市销率TTM", "市销率(TTM)", "PS(TTM)", "ps_ttm"])),
            "dividend_yield": _ratio(_first_present(row, ["股息率", "股息率TTM", "dividend_yield"])),
        }
        return {key: value for key, value in normalized.items() if value is not None}
