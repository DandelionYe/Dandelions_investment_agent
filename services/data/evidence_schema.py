"""数据证据结构统一层。

为关键字段提供统一结构：
{
    "value": ...,
    "source": "qmt|akshare|local_csmar|web_news|mock|unknown",
    "as_of": "YYYY-MM-DD or ISO string or None",
    "quality": {
        "available": bool,
        "confidence": float | None,
        "freshness": "fresh|stale|unknown|not_applicable",
        "missing_reason": str | None,
    },
    "warnings": list[str],
}

本模块提供并行证据视图，不影响现有评分引擎和报告 builder 读取裸值。
"""

from __future__ import annotations

from typing import Any

_VALID_SOURCES = frozenset({
    "qmt", "akshare", "local_csmar", "web_news", "mock", "unknown",
    "eastmoney", "csmar", "eva", "cninfo",
})

_VALID_FRESHNESS = frozenset({
    "fresh", "stale", "unknown", "not_applicable",
})


def make_evidence_field(
    value: Any,
    source: str = "unknown",
    as_of: str | None = None,
    confidence: float | None = None,
    freshness: str = "unknown",
    missing_reason: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """构造标准化证据字段。

    Parameters
    ----------
    value : Any
        原始值。None 表示缺失。
    source : str
        数据来源标识。
    as_of : str | None
        数据日期，ISO 格式。
    confidence : float | None
        置信度，0-1 范围。None 表示未评估。
    freshness : str
        新鲜度：fresh / stale / unknown / not_applicable。
    missing_reason : str | None
        缺失原因（仅 value 为 None 时有意义）。
    warnings : list[str] | None
        警告列表。
    """
    if source not in _VALID_SOURCES:
        source = "unknown"
    if freshness not in _VALID_FRESHNESS:
        freshness = "unknown"
    if confidence is not None:
        confidence = max(0.0, min(1.0, float(confidence)))
    available = value is not None
    return {
        "value": value,
        "source": source,
        "as_of": as_of,
        "quality": {
            "available": available,
            "confidence": confidence,
            "freshness": freshness,
            "missing_reason": missing_reason if not available else None,
        },
        "warnings": list(warnings) if warnings else [],
    }


def is_evidence_field(obj: Any) -> bool:
    """判断对象是否为标准化证据字段。

    检查是否包含 value/source/quality 三个核心 key。
    """
    if not isinstance(obj, dict):
        return False
    return (
        "value" in obj
        and "source" in obj
        and "quality" in obj
        and isinstance(obj.get("quality"), dict)
    )


def normalize_evidence_field(
    raw: Any,
    *,
    default_source: str = "unknown",
    default_as_of: str | None = None,
) -> dict:
    """将裸值或已有证据字段标准化。

    - 已是 evidence field → 幂等返回（补齐缺失 key）。
    - 裸值 → 包装为 evidence field。
    """
    if is_evidence_field(raw):
        q = raw.get("quality", {})
        if not isinstance(q, dict):
            q = {}
        return {
            "value": raw.get("value"),
            "source": raw.get("source", default_source),
            "as_of": raw.get("as_of", default_as_of),
            "quality": {
                "available": q.get("available", raw.get("value") is not None),
                "confidence": q.get("confidence"),
                "freshness": q.get("freshness", "unknown"),
                "missing_reason": q.get("missing_reason"),
            },
            "warnings": list(raw.get("warnings", [])),
        }
    return make_evidence_field(raw, source=default_source, as_of=default_as_of)


def extract_display_value(field_or_raw: Any) -> Any:
    """从证据字段或裸值中提取可显示的值。

    - evidence field → 返回 value
    - 裸值 → 直接返回
    """
    if is_evidence_field(field_or_raw):
        return field_or_raw.get("value")
    return field_or_raw


def _get_nested(d: dict, dotpath: str) -> Any:
    """按点路径获取嵌套 dict 值。"""
    parts = dotpath.split(".")
    cur = d
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _get_source_for_field(source_metadata: dict, section: str) -> str:
    """从 source_metadata 中提取某 section 的 source 标识。"""
    meta = source_metadata.get(section, {})
    if isinstance(meta, dict):
        src = meta.get("source", "unknown")
        if src == "mock_placeholder":
            return "mock"
        return str(src) if src else "unknown"
    return "unknown"


def _get_confidence_for_field(
    data_quality: dict, section: str
) -> float | None:
    """从 data_quality.field_quality 中提取置信度。"""
    fq = data_quality.get("field_quality", {})
    section_quality = fq.get(section, {})
    if isinstance(section_quality, dict):
        return section_quality.get("confidence")
    return None


def _get_freshness_for_field(
    data_quality: dict, section: str
) -> str:
    """从 data_quality.field_quality 中提取新鲜度。"""
    fq = data_quality.get("field_quality", {})
    section_quality = fq.get(section, {})
    if isinstance(section_quality, dict):
        return section_quality.get("freshness", "unknown")
    return "unknown"


# 需要统一的字段路径 → (section, 默认 missing_reason)
_KEY_FIELD_MAP: list[tuple[str, str, str]] = [
    # (dotpath, source_metadata section, default_missing_reason)
    ("price_data.close", "price_data", "missing_close"),
    ("price_data.change_20d", "price_data", "missing_close"),
    ("price_data.change_60d", "price_data", "missing_close"),
    ("price_data.avg_turnover_20d", "price_data", "missing_close"),
    ("valuation_data.pe_ttm", "valuation_data", "missing_net_profit_ttm"),
    ("valuation_data.pb_mrq", "valuation_data", "missing_bps"),
    ("valuation_data.ps_ttm", "valuation_data", "missing_revenue_ttm"),
    ("valuation_data.pe_percentile", "valuation_data", "insufficient_history_samples"),
    ("valuation_data.pb_percentile", "valuation_data", "insufficient_history_samples"),
    ("valuation_data.ps_percentile", "valuation_data", "insufficient_history_samples"),
    ("valuation_data.industry_pe_percentile", "valuation_data", "insufficient_peer_samples"),
    ("valuation_data.industry_pb_percentile", "valuation_data", "insufficient_peer_samples"),
    ("valuation_data.industry_ps_percentile", "valuation_data", "insufficient_peer_samples"),
    ("fundamental_data.roe", "fundamental_data", "field_not_supported"),
    ("fundamental_data.gross_margin", "fundamental_data", "field_not_supported"),
    ("fundamental_data.net_profit_growth", "fundamental_data", "field_not_supported"),
    ("event_data.major_event", "event_data", "field_not_supported"),
]


def normalize_key_fields(result: dict) -> dict:
    """将 result 中的关键字段提取为统一证据结构，写入 result["evidence_fields"]。

    不修改 result 中的原始裸值。返回 result（原地修改并返回）。
    """
    source_metadata = result.get("source_metadata", {})
    data_quality = result.get("data_quality", {})
    evidence_fields: dict[str, dict] = {}

    for dotpath, section, default_missing_reason in _KEY_FIELD_MAP:
        raw_value = _get_nested(result, dotpath)

        # 尝试从 valuation_data 的 *_missing_reason 获取具体原因
        missing_reason = default_missing_reason
        if raw_value is None and section == "valuation_data":
            parts = dotpath.split(".")
            field_name = parts[-1]
            reason_key = f"{field_name}_missing_reason"
            vd = result.get("valuation_data", {})
            if isinstance(vd, dict) and reason_key in vd:
                missing_reason = vd[reason_key]

        source = _get_source_for_field(source_metadata, section)
        confidence = _get_confidence_for_field(data_quality, section)
        freshness = _get_freshness_for_field(data_quality, section)

        as_of = result.get("as_of")

        ev = make_evidence_field(
            value=raw_value,
            source=source,
            as_of=as_of,
            confidence=confidence,
            freshness=freshness,
            missing_reason=missing_reason if raw_value is None else None,
        )
        evidence_fields[dotpath] = ev

    result["evidence_fields"] = evidence_fields
    return result
