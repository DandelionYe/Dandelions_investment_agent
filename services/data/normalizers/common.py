"""Normalizer 公共工具函数。

提供跨 normalizer 复用的类型转换与数据提取函数，消除重复实现。
"""

from typing import Any


def _is_missing(value: Any) -> bool:
    """判断值是否为空/缺失。"""
    if value in (None, ""):
        return True
    try:
        import math
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def _to_float(value: Any) -> float | None:
    """安全转换为 float，处理逗号、百分号、NaN。"""
    if _is_missing(value):
        return None
    try:
        import math
        number = float(str(value).replace(",", "").replace("%", ""))
        if math.isnan(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _ratio(value: Any, threshold: float = 1.0) -> float | None:
    """将可能是百分比的数值统一转为小数比率。

    大于 threshold 的值视为百分比，除以 100。
    """
    number = _to_float(value)
    if number is None:
        return None
    if abs(number) > threshold:
        return number / 100
    return number


def _first_present(row: dict, candidates: list[str]) -> Any:
    """从 row 的一组候选键中返回第一个存在的（非空）值。大小写不敏感。"""
    lower_map = {str(key).lower(): value for key, value in row.items()}
    for candidate in candidates:
        if candidate in row and not _is_missing(row[candidate]):
            return row[candidate]
        value = lower_map.get(candidate.lower())
        if not _is_missing(value):
            return value
    return None
