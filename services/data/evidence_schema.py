"""数据证据结构统一层。

为关键字段提供统一结构：
{
    "value": ...,
    "source": "qmt_xtdata|local_csmar_daily_derived|local_csmar_financial_statements|..."
              "akshare|web_news|derived|missing|mock|unknown",
    "as_of": "YYYY-MM-DD or ISO string or None",
    "quality": {
        "available": bool,
        "confidence": float | None,
        "freshness": "fresh|stale|historical|estimated|missing|unknown|not_applicable",
        "missing_reason": str | None,
    },
    "warnings": list[str],
}

本模块提供并行证据视图，不影响现有评分引擎和报告 builder 读取裸值。
"""

from __future__ import annotations

from typing import Any

# ── Valid values ────────────────────────────────────────────────────

_VALID_SOURCES = frozenset({
    "qmt", "qmt_xtdata", "akshare", "local_csmar", "web_news", "mock", "unknown",
    "eastmoney", "csmar", "eva", "cninfo",
    "local_csmar_daily_derived", "local_csmar_financial_statements",
    "local_csmar_industry", "local_csmar_industry_history",
    "local_csmar_industry_non_strict",
    "local_csmar_industry_history_non_strict",
    "local_csmar_eva_structure_partial", "local_csmar_eva_structure",
    "derived", "missing", "event_provider",
})

_VALID_FRESHNESS = frozenset({
    "fresh", "stale", "historical", "estimated", "missing",
    "unknown", "not_applicable",
})

# ── Source hierarchy: which source labels count as "strict" ────────

NON_STRICT_SOURCES = frozenset({
    None, "", "missing", "non_strict", "latest_snapshot_fallback",
    "local_csmar_industry_non_strict", "local_csmar_industry_history_non_strict",
    "local_csmar_eva_structure_partial", "mock", "unknown",
})

_FLAT_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "price_data": ("price_source",),
    "valuation_data": ("valuation_source",),
    "fundamental_data": ("fundamental_source",),
    "capital_structure": ("capital_structure_source",),
    "industry": ("industry_source",),
    "event_data": ("event_source", "event_data_source"),
}


def is_strict_source(source: str | None) -> bool:
    """Return True if *source* is a strict/provenanced data source."""
    return source not in NON_STRICT_SOURCES


# ── Core constructors ──────────────────────────────────────────────

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
        新鲜度：fresh / stale / historical / estimated / missing / unknown / not_applicable。
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
    quality = obj.get("quality")
    if not isinstance(quality, dict):
        return False
    return (
        "value" in obj
        and "source" in obj
        and "as_of" in obj
        and "quality" in obj
        and "warnings" in obj
        and isinstance(obj.get("warnings"), list)
        and "available" in quality
        and "confidence" in quality
        and "freshness" in quality
        and "missing_reason" in quality
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
    if is_evidence_field(raw) or (
        isinstance(raw, dict)
        and "value" in raw
        and "source" in raw
        and "quality" in raw
    ):
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


# ── Nested access helpers ──────────────────────────────────────────

def _get_nested(d: dict, dotpath: str) -> Any:
    """按点路径获取嵌套 dict 值。"""
    parts = dotpath.split(".")
    cur = d
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur

def _normalize_source_label(source: Any) -> str:
    if source == "mock_placeholder":
        return "mock"
    return str(source) if source else "unknown"


def _get_source_for_field(source_metadata: dict, section: str) -> str:
    """从 source_metadata 中提取某 section 的 source 标识。"""
    if not isinstance(source_metadata, dict):
        return "unknown"

    meta = source_metadata.get(section, {})
    if isinstance(meta, dict):
        src = meta.get("source", "unknown")
        source = _normalize_source_label(src)
        if source != "unknown":
            return source
    elif meta:
        return _normalize_source_label(meta)

    for flat_key in _FLAT_SOURCE_KEYS.get(section, ()):
        if flat_key in source_metadata:
            return _normalize_source_label(source_metadata.get(flat_key))

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


# ── Key field mapping ──────────────────────────────────────────────
#
# Each entry: (dotpath, source_section, default_missing_reason)
#
# The source_section is used for source_metadata lookup.
# Special sections with custom source derivation are handled in
# normalize_key_fields().

_KEY_FIELD_MAP: list[tuple[str, str, str]] = [
    # price_data
    ("price_data.close", "price_data", "missing_close"),
    ("price_data.change_20d", "price_data", "missing_close"),
    ("price_data.change_60d", "price_data", "missing_close"),
    ("price_data.ma20_position", "price_data", "missing_close"),
    ("price_data.ma60_position", "price_data", "missing_close"),
    ("price_data.max_drawdown_60d", "price_data", "missing_close"),
    ("price_data.volatility_60d", "price_data", "missing_close"),
    ("price_data.avg_turnover_20d", "price_data", "missing_close"),

    # valuation_data — core multiples
    ("valuation_data.pe_ttm", "valuation_data", "missing_net_profit_ttm"),
    ("valuation_data.pb_mrq", "valuation_data", "missing_bps"),
    ("valuation_data.ps_ttm", "valuation_data", "missing_revenue_ttm"),
    ("valuation_data.dividend_yield", "valuation_data", "missing_dividend_yield_source"),
    ("valuation_data.market_cap", "valuation_data", "missing_market_cap"),

    # valuation_data — historical percentiles
    ("valuation_data.pe_percentile", "valuation_data", "insufficient_history_samples"),
    ("valuation_data.pb_percentile", "valuation_data", "insufficient_history_samples"),
    ("valuation_data.ps_percentile", "valuation_data", "insufficient_history_samples"),

    # valuation_data — industry percentiles (special source derivation)
    ("valuation_data.industry_pe_percentile", "valuation_data_industry", "insufficient_peer_samples"),
    ("valuation_data.industry_pb_percentile", "valuation_data_industry", "insufficient_peer_samples"),
    ("valuation_data.industry_ps_percentile", "valuation_data_industry", "insufficient_peer_samples"),

    # fundamental_data — profitability quality
    ("fundamental_data.roe", "fundamental_data", "field_not_supported"),
    ("fundamental_data.gross_margin", "fundamental_data", "field_not_supported"),
    ("fundamental_data.net_margin", "fundamental_data", "field_not_supported"),
    ("fundamental_data.revenue_ttm", "fundamental_data", "field_not_supported"),
    ("fundamental_data.net_profit_ttm", "fundamental_data", "field_not_supported"),
    ("fundamental_data.revenue_growth", "fundamental_data", "field_not_supported"),
    ("fundamental_data.net_profit_growth", "fundamental_data", "field_not_supported"),
    ("fundamental_data.debt_ratio", "fundamental_data", "field_not_supported"),
    ("fundamental_data.operating_cashflow_quality", "fundamental_data", "field_not_supported"),

    # fundamental_data — capital structure (EVA)
    ("fundamental_data.total_volume", "capital_structure", "missing_total_volume"),
    ("fundamental_data.float_volume", "capital_structure", "missing_total_volume"),
    ("fundamental_data.bps", "capital_structure", "missing_bps"),

    # industry
    ("industry.industry_code", "industry", "industry_data_missing"),
    ("industry.industry_name", "industry", "industry_data_missing"),
    ("industry.classification_system", "industry", "industry_data_missing"),
    ("industry.peer_count", "industry", "industry_data_missing"),
    ("industry.valid_peer_count_pe", "industry", "industry_data_missing"),
    ("industry.valid_peer_count_pb", "industry", "industry_data_missing"),
    ("industry.valid_peer_count_ps", "industry", "industry_data_missing"),

    # event_data
    ("event_data.recent_news_sentiment", "event_data", "field_not_supported"),
    ("event_data.policy_risk", "event_data", "field_not_supported"),
]


# ── Source / quality derivation helpers ────────────────────────────

def _derive_industry_percentile_evidence(
    result: dict, dotpath: str, default_missing_reason: str,
) -> dict:
    """Build evidence for industry percentile fields with strict source rules.

    Industry percentiles must use valuation_data.industry_percentile_source
    as the source, and only local_csmar_industry_history qualifies as strict.
    """
    raw_value = _get_nested(result, dotpath)
    valuation_data = result.get("valuation_data", {})
    source_metadata = result.get("source_metadata", {})
    data_quality = result.get("data_quality", {})

    percentile_source = valuation_data.get("industry_percentile_source", "missing")
    industry_source = source_metadata.get("industry_source", "missing")

    # Determine effective source: prefer percentile_source, fallback to industry_source
    if percentile_source and percentile_source != "missing":
        source = percentile_source
    elif industry_source and industry_source != "missing":
        source = industry_source
    else:
        source = "missing"

    # Strictness: only local_csmar_industry_history is strict
    is_strict = source == "local_csmar_industry_history"

    # Confidence and freshness
    confidence = _get_confidence_for_field(data_quality, "valuation_data")
    freshness = _get_freshness_for_field(data_quality, "valuation_data")

    as_of = result.get("as_of")

    warnings: list[str] = []
    if not is_strict and raw_value is not None:
        warnings.append(
            f"行业分位来源 {source} 非 strict，置信度受限"
        )

    # Missing reason
    missing_reason = default_missing_reason
    if raw_value is None:
        field_name = dotpath.split(".")[-1]
        reason_key = f"{field_name}_missing_reason"
        if isinstance(valuation_data, dict) and reason_key in valuation_data:
            missing_reason = valuation_data[reason_key]

    ev = make_evidence_field(
        value=raw_value,
        source=source,
        as_of=as_of,
        confidence=confidence,
        freshness=freshness if raw_value is not None else ("missing" if raw_value is None else freshness),
        missing_reason=missing_reason if raw_value is None else None,
        warnings=warnings,
    )
    return ev


def _derive_fundamental_source(
    source_metadata: dict, field_name: str, raw_value: Any,
) -> tuple[str, float | None, str]:
    """Derive source, confidence, freshness for a fundamental field.

    Profitability fields (roe, gross_margin, net_profit_growth, etc.) must
    come from fundamental_data source.  Capital structure fields (total_volume,
    float_volume, bps) can come from capital_structure_source.

    Handles both flat key format (from historical samples) and nested dict
    format (from aggregator): ``{"fundamental_data": {"source": "..."}}``.
    """
    capital_structure_fields = {"total_volume", "float_volume", "market_cap",
                                "float_market_cap", "bps"}

    if field_name in capital_structure_fields:
        sm_source = source_metadata.get("capital_structure_source", "missing")
        if sm_source == "local_csmar_eva_structure_partial":
            return sm_source, 0.6, "historical"
        return sm_source, None, "unknown"

    # Profitability fields — try flat key first, then nested dict
    sm_source = source_metadata.get("fundamental_source", "")
    if not sm_source:
        nested = source_metadata.get("fundamental_data", {})
        if isinstance(nested, dict):
            sm_source = nested.get("source", "missing")
        else:
            sm_source = "missing"
    if sm_source == "local_csmar_financial_statements":
        return sm_source, 0.9, "historical"
    return sm_source or "missing", None, "unknown"


# ── normalize_key_fields ──────────────────────────────────────────

def normalize_key_fields(result: dict) -> dict:
    """将 result 中的关键字段提取为统一证据结构，写入 result["evidence_fields"]。

    不修改 result 中的原始裸值。返回 result（原地修改并返回）。
    """
    source_metadata = result.get("source_metadata", {})
    data_quality = result.get("data_quality", {})
    valuation_data = result.get("valuation_data", {})
    evidence_fields: dict[str, dict] = {}

    for dotpath, section, default_missing_reason in _KEY_FIELD_MAP:
        # Industry percentile fields have custom derivation
        if section == "valuation_data_industry":
            ev = _derive_industry_percentile_evidence(result, dotpath, default_missing_reason)
            evidence_fields[dotpath] = ev
            continue

        raw_value = _get_nested(result, dotpath)

        # Missing reason
        missing_reason = default_missing_reason
        if raw_value is None:
            # Try section-specific missing reason
            if section == "valuation_data" and isinstance(valuation_data, dict):
                field_name = dotpath.split(".")[-1]
                reason_key = f"{field_name}_missing_reason"
                if reason_key in valuation_data:
                    missing_reason = valuation_data[reason_key]

        # Source derivation
        if section == "fundamental_data" or section == "capital_structure":
            field_name = dotpath.split(".")[-1]
            source, extra_conf, extra_fresh = _derive_fundamental_source(
                source_metadata, field_name, raw_value,
            )
            confidence = _get_confidence_for_field(data_quality, "fundamental_data")
            if confidence is None and extra_conf is not None:
                confidence = extra_conf
            freshness = _get_freshness_for_field(data_quality, "fundamental_data")
            if freshness == "unknown" and extra_fresh != "unknown":
                freshness = extra_fresh
        elif section == "industry":
            source = source_metadata.get("industry_source", "missing")
            confidence = _get_confidence_for_field(data_quality, section)
            freshness = _get_freshness_for_field(data_quality, section)
            # Non-strict industry source warnings
            if source in {"local_csmar_industry_non_strict",
                          "local_csmar_industry_history_non_strict"}:
                freshness = "estimated"
        else:
            source = _get_source_for_field(source_metadata, section)
            confidence = _get_confidence_for_field(data_quality, section)
            freshness = _get_freshness_for_field(data_quality, section)

        as_of = result.get("as_of")

        # Build warnings
        warnings: list[str] = []
        if section == "industry" and source in {
            "local_csmar_industry_non_strict",
            "local_csmar_industry_history_non_strict",
        }:
            warnings.append(f"行业来源 {source} 非 strict，置信度受限")

        ev = make_evidence_field(
            value=raw_value,
            source=source,
            as_of=as_of,
            confidence=confidence,
            freshness=freshness,
            missing_reason=missing_reason if raw_value is None else None,
            warnings=warnings,
        )
        evidence_fields[dotpath] = ev

    result["evidence_fields"] = evidence_fields
    return result


# ── validate_evidence_fields ──────────────────────────────────────

def validate_evidence_fields(
    result: dict,
    required_paths: list[str] | None = None,
) -> list[dict[str, str]]:
    """Validate evidence_fields in result, returning structured error list.

    Each error is {"path": str, "error": str, "detail": str}.
    """
    evidence_fields = result.get("evidence_fields")
    if evidence_fields is None or not isinstance(evidence_fields, dict):
        return [{"path": "(root)", "error": "missing_evidence_fields",
                 "detail": "result 不存在 evidence_fields 或不是 dict"}]

    paths = required_paths or [e for e in _KEY_FIELD_MAP]
    if required_paths is None:
        paths = [dotpath for dotpath, _, _ in _KEY_FIELD_MAP]
    else:
        paths = required_paths

    errors: list[dict[str, str]] = []

    for path in paths:
        ev = evidence_fields.get(path)
        if ev is None:
            errors.append({
                "path": path,
                "error": "missing_field",
                "detail": f"evidence_fields 中缺少 {path}",
            })
            continue

        if not isinstance(ev, dict):
            errors.append({
                "path": path,
                "error": "not_dict",
                "detail": f"{path} 不是 dict",
            })
            continue

        # Check required keys
        for key in ("value", "source", "as_of", "quality", "warnings"):
            if key not in ev:
                errors.append({
                    "path": path,
                    "error": f"missing_key_{key}",
                    "detail": f"{path} 缺少 {key}",
                })

        # Check source is not empty
        source = ev.get("source", "")
        if not source or source == "":
            errors.append({
                "path": path,
                "error": "empty_source",
                "detail": f"{path} source 为空",
            })
        elif source not in _VALID_SOURCES:
            errors.append({
                "path": path,
                "error": "invalid_source",
                "detail": f"{path} source={source} 不在标准 source 集合",
            })

        # Check quality structure
        quality = ev.get("quality")
        if isinstance(quality, dict):
            for key in ("available", "confidence", "freshness", "missing_reason"):
                if key not in quality:
                    errors.append({
                        "path": path,
                        "error": f"missing_quality_key_{key}",
                        "detail": f"{path} quality 缺少 {key}",
                    })
            freshness = quality.get("freshness")
            if freshness not in _VALID_FRESHNESS:
                errors.append({
                    "path": path,
                    "error": "invalid_freshness",
                    "detail": f"{path} freshness={freshness} 不在标准 freshness 集合",
                })
            # Check confidence bounds
            conf = quality.get("confidence")
            if conf is not None:
                try:
                    conf_f = float(conf)
                    if conf_f < 0.0 or conf_f > 1.0:
                        errors.append({
                            "path": path,
                            "error": "confidence_out_of_range",
                            "detail": f"{path} confidence={conf} 超出 [0,1]",
                        })
                except (TypeError, ValueError):
                    errors.append({
                        "path": path,
                        "error": "confidence_not_numeric",
                        "detail": f"{path} confidence={conf} 不是数字",
                    })

            # Check available vs missing_reason consistency
            available = quality.get("available")
            missing_reason = quality.get("missing_reason")
            if available is False and missing_reason is None:
                # Not strictly an error, but a warning — missing fields should explain why
                pass
            if available is True and missing_reason is not None:
                errors.append({
                    "path": path,
                    "error": "inconsistent_available_missing_reason",
                    "detail": f"{path} available=true 但 missing_reason={missing_reason}",
                })
        elif quality is not None:
            errors.append({
                "path": path,
                "error": "quality_not_dict",
                "detail": f"{path} quality 不是 dict",
            })

        # Check warnings is list
        warnings = ev.get("warnings")
        if warnings is not None and not isinstance(warnings, list):
            errors.append({
                "path": path,
                "error": "warnings_not_list",
                "detail": f"{path} warnings 不是 list",
            })

    return errors


# ── summarize_evidence_coverage ────────────────────────────────────

def summarize_evidence_coverage(
    result: dict,
    required_paths: list[str] | None = None,
) -> dict:
    """Summarize evidence coverage for a research result.

    Returns:
        total_required, covered, missing, coverage_rate,
        by_source, by_quality, missing_reasons
    """
    if "evidence_fields" not in result and any("." in str(k) for k in result):
        evidence_fields = result
    else:
        evidence_fields = result.get("evidence_fields", {})
        if not isinstance(evidence_fields, dict):
            evidence_fields = {}

    paths = required_paths or [dotpath for dotpath, _, _ in _KEY_FIELD_MAP]

    total = len(paths)
    covered = 0
    missing = 0
    by_source: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    missing_reasons: dict[str, int] = {}

    for path in paths:
        ev = evidence_fields.get(path)
        if ev is None or not isinstance(ev, dict):
            missing += 1
            missing_reasons["evidence_field_absent"] = missing_reasons.get("evidence_field_absent", 0) + 1
            continue

        source = ev.get("source", "unknown")
        quality = ev.get("quality", {})
        available = quality.get("available", False) if isinstance(quality, dict) else False

        if available:
            covered += 1
        else:
            missing += 1
            mr = quality.get("missing_reason", "unknown") if isinstance(quality, dict) else "unknown"
            missing_reasons[mr] = missing_reasons.get(mr, 0) + 1

        by_source[source] = by_source.get(source, 0) + 1

        freshness = quality.get("freshness", "unknown") if isinstance(quality, dict) else "unknown"
        by_quality[freshness] = by_quality.get(freshness, 0) + 1

    return {
        "total_required": total,
        "covered": covered,
        "missing": missing,
        "coverage_rate": round(covered / total, 4) if total > 0 else 0.0,
        "by_source": by_source,
        "by_quality": by_quality,
        "missing_reasons": missing_reasons,
    }
