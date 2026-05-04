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


class ETFNormalizer:
    def normalize_akshare_info(self, provider_result: dict) -> dict:
        records = provider_result.get("data", [])
        row = records[-1] if records else {}
        return {
            "fund_size": _to_float(_first_present(row, [
                "基金规模", "fund_size", "基金份额", "流通份额",
            ])),
            "management_fee": _ratio(_first_present(row, [
                "管理费率", "management_fee", "管理费",
            ])),
            "custodian_fee": _ratio(_first_present(row, [
                "托管费率", "custodian_fee", "托管费",
            ])),
        }

    def normalize_akshare_spot(self, provider_result: dict) -> dict:
        records = provider_result.get("data", [])
        row = records[0] if records else {}
        nav = _to_float(_first_present(row, ["单位净值", "IOPV", "净值", "nav"]))
        market_price = _to_float(_first_present(row, [
            "最新价", "当前价", "price", "现价",
        ]))
        premium_discount = None
        if nav and market_price and nav > 0:
            premium_discount = (market_price - nav) / nav

        return {
            "nav": nav,
            "premium_discount": premium_discount
            if premium_discount is not None
            else _ratio(_first_present(row, ["折溢价率", "折溢价", "premium_rate"])),
        }
