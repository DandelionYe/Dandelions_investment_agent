from typing import Any

from services.data.normalizers.common import _to_float, _first_present, _ratio as _base_ratio


def _ratio(value: Any) -> float | None:
    return _base_ratio(value, threshold=1.5)


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
