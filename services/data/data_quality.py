from typing import Any


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def to_display_text(value: Any, default: str = "暂无") -> str:
    """
    把任意值转换为适合报告展示的文本。
    """
    if _is_empty(value):
        return default

    return str(value)


def localize_asset_type(value: Any) -> str:
    """
    资产类型中文化。
    """
    mapping = {
        "stock": "股票",
        "etf": "ETF",
        "fund": "基金",
        "index": "指数",
        "sector": "板块",
        "convertible_bond": "可转债",
        "futures": "期货",
        "option": "期权",
    }

    return mapping.get(str(value).lower(), to_display_text(value))


def localize_data_source(value: Any) -> str:
    """
    数据来源中文化。
    """
    mapping = {
        "mock": "模拟数据",
        "akshare": "AKShare",
        "qmt": "QMT",
        "web": "网页补充",
    }

    return mapping.get(str(value).lower(), to_display_text(value))


def localize_data_vendor(value: Any) -> str:
    """
    行情供应商中文化。
    """
    mapping = {
        "eastmoney": "东方财富",
        "tencent": "腾讯",
        "sina": "新浪",
        "qmt": "QMT",
        "unknown": "未知",
    }

    return mapping.get(str(value).lower(), to_display_text(value))


def localize_ma_position(value: Any) -> str:
    """
    均线位置中文化。
    """
    mapping = {
        "above": "高于均线",
        "below": "低于均线",
        "equal": "接近均线",
        "near": "接近均线",
    }

    return mapping.get(str(value).lower(), to_display_text(value))


def localize_risk_level(value: Any) -> str:
    """
    风险等级中文化。
    """
    if _is_empty(value):
        return "暂无"

    mapping = {
        "low": "低",
        "medium": "中等",
        "high": "高",
        "critical": "极高",
    }

    return mapping.get(str(value).lower(), to_display_text(value))


def localize_bool(value: Any) -> str:
    """
    布尔值中文化。
    """
    if isinstance(value, bool):
        return "是" if value else "否"

    if _is_empty(value):
        return "暂无"

    value_str = str(value).strip().lower()

    if value_str in {"true", "1", "yes", "y"}:
        return "是"

    if value_str in {"false", "0", "no", "n"}:
        return "否"

    return str(value)


def format_confidence(value: Any) -> str:
    """
    格式化置信度。
    """
    if _is_empty(value):
        return "暂无"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if 0 <= number <= 1:
        return f"{number:.0%}"

    return str(value)


def format_percent(value: Any) -> str:
    """
    把小数格式化为百分比。
    例如 0.05 -> 5.00%
    """
    if _is_empty(value):
        return "暂无"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    return f"{number:.2%}"


def format_number(value: Any, digits: int = 2) -> str:
    """
    格式化普通数字。
    """
    if _is_empty(value):
        return "暂无"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    return f"{number:.{digits}f}"


def format_money_like_value(value: Any, data_vendor: str | None = None) -> str:
    """
    格式化金额/成交额类字段。

    注意：
    - 东方财富接口的“成交额”通常可以按金额理解。
    - 腾讯备用接口返回字段可能存在单位差异。
    - 因此腾讯来源先按“原始值”展示，避免误导。
    """
    if _is_empty(value):
        return "暂无"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    vendor = str(data_vendor or "").lower()

    if vendor == "tencent":
        return f"{number:.2f}（原始值，单位待校验）"

    if number >= 100000000:
        return f"{number / 100000000:.2f} 亿"

    if number >= 10000:
        return f"{number / 10000:.2f} 万"

    return f"{number:.2f}"


def build_data_quality_notes(price_data: dict) -> list[str]:
    """
    根据行情字段生成数据质量提示。
    """
    notes: list[str] = []

    data_vendor = str(price_data.get("data_vendor", "")).lower()

    if data_vendor == "tencent":
        notes.append(
            "当前行情来自 AKShare 的腾讯备用接口。该接口的成交额/成交量字段单位可能与东方财富或 QMT 不完全一致，报告中暂按原始值展示。"
        )

    if price_data.get("avg_turnover_20d") in (None, "", 0, 0.0):
        notes.append(
            "当前缺少可靠的近20日成交额字段，流动性评分仅作临时参考。"
        )

    if price_data.get("ma20_position") == "below" and price_data.get("ma60_position") == "below":
        notes.append(
            "当前价格同时低于 MA20 和 MA60，短中期趋势仍偏弱。"
        )

    try:
        volatility = float(price_data.get("volatility_60d"))
        if volatility >= 0.30:
            notes.append(
                "近60日年化波动率较高，仓位建议应保持保守。"
            )
    except (TypeError, ValueError):
        pass

    try:
        max_drawdown = float(price_data.get("max_drawdown_60d"))
        if max_drawdown <= -0.10:
            notes.append(
                "近60日最大回撤超过10%，需重点关注下行风险。"
            )
    except (TypeError, ValueError):
        pass

    if not notes:
        notes.append("当前行情字段未发现明显数据质量异常。")

    return notes