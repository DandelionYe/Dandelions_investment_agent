from typing import Any


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

        return {
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
