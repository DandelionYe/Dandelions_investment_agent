"""Centralized condition trigger evaluator for watchlist items.

Single source of truth for trigger evaluation logic.
Used by both Celery scheduler and verification scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerEvaluationResult:
    triggered: bool = False
    reasons: list[str] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)
    categories_evaluated: list[str] = field(default_factory=list)


def evaluate_condition_triggers(
    item: dict,
    quote: dict[str, Any] | None = None,
    latest_result: dict[str, Any] | None = None,
) -> TriggerEvaluationResult:
    """Evaluate all condition triggers for a watchlist item.

    Args:
        item: Watchlist item dict (must contain schedule_config.condition_triggers)
        quote: Real-time quote data with keys: close, prev_close, volume, change_pct, volume_ratio
        latest_result: Latest research result snapshot with keys: valuation_data, risk_review, event_data, score

    Returns:
        TriggerEvaluationResult with triggered flag, reasons, missing_reasons, categories_evaluated
    """
    result = TriggerEvaluationResult()
    sc = item.get("schedule_config") or {}
    ct = sc.get("condition_triggers") or {}

    if not ct:
        return result

    # Check if any trigger is configured (is not None, not empty list)
    has_any = any(v is not None and v != [] for v in ct.values())
    if not has_any:
        return result

    # ── Price change trigger ──────────────────────────────────
    if ct.get("price_change_pct") is not None:
        result.categories_evaluated.append("price_change_pct")
        threshold = ct["price_change_pct"]
        if quote and "change_pct" in quote:
            if abs(quote["change_pct"]) >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% >= 阈值 {threshold}%"
                )
            else:
                result.reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% < 阈值 {threshold}%"
                )
        elif quote and "error" in quote:
            result.missing_reasons.append(f"price: 行情获取失败: {quote['error']}")
        else:
            result.missing_reasons.append("price: 行情数据不可用")

    # ── Volume spike trigger ──────────────────────────────────
    if ct.get("volume_spike_ratio") is not None:
        result.categories_evaluated.append("volume_spike_ratio")
        threshold = ct["volume_spike_ratio"]
        if quote and "volume_ratio" in quote:
            if quote["volume_ratio"] >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} >= 阈值 {threshold}"
                )
            else:
                result.reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} < 阈值 {threshold}"
                )
        elif quote and "error" in quote:
            result.missing_reasons.append(f"volume: 行情获取失败: {quote['error']}")
        else:
            result.missing_reasons.append("volume: 行情数据不可用")

    # ── Score threshold trigger ───────────────────────────────
    if ct.get("score_threshold") is not None:
        result.categories_evaluated.append("score_threshold")
        threshold = ct["score_threshold"]
        last_score = item.get("last_score")
        if last_score is not None:
            if last_score >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"评分 {last_score:.1f} >= 阈值 {threshold}"
                )
            else:
                result.reasons.append(
                    f"评分 {last_score:.1f} < 阈值 {threshold}"
                )
        else:
            result.missing_reasons.append("score: 无历史评分（首次扫描前无法触发）")

    # ── PE-TTM trigger ────────────────────────────────────────
    if ct.get("pe_ttm_max") is not None:
        result.categories_evaluated.append("pe_ttm_max")
        threshold = ct["pe_ttm_max"]
        val_data = _get_valuation_data(latest_result)
        pe = val_data.get("pe_ttm") if val_data else None
        if pe is not None:
            if pe <= threshold:
                result.triggered = True
                result.reasons.append(f"PE-TTM {pe:.2f} <= 阈值 {threshold}")
            else:
                result.reasons.append(f"PE-TTM {pe:.2f} > 阈值 {threshold}")
        else:
            result.missing_reasons.append("pe_ttm: 估值数据不可用")

    # ── PB-MRQ trigger ────────────────────────────────────────
    if ct.get("pb_mrq_max") is not None:
        result.categories_evaluated.append("pb_mrq_max")
        threshold = ct["pb_mrq_max"]
        val_data = _get_valuation_data(latest_result)
        pb = val_data.get("pb_mrq") if val_data else None
        if pb is not None:
            if pb <= threshold:
                result.triggered = True
                result.reasons.append(f"PB-MRQ {pb:.2f} <= 阈值 {threshold}")
            else:
                result.reasons.append(f"PB-MRQ {pb:.2f} > 阈值 {threshold}")
        else:
            result.missing_reasons.append("pb_mrq: 估值数据不可用")

    # ── Valuation percentile trigger ──────────────────────────
    if ct.get("valuation_percentile_max") is not None:
        result.categories_evaluated.append("valuation_percentile_max")
        threshold = ct["valuation_percentile_max"]
        val_data = _get_valuation_data(latest_result)
        pct = val_data.get("valuation_percentile") if val_data else None
        if pct is not None:
            if pct <= threshold:
                result.triggered = True
                result.reasons.append(f"估值分位 {pct:.1f}% <= 阈值 {threshold}%")
            else:
                result.reasons.append(f"估值分位 {pct:.1f}% > 阈值 {threshold}%")
        else:
            result.missing_reasons.append("valuation_percentile: 估值分位数据不可用")

    # ── Risk level trigger ────────────────────────────────────
    if ct.get("risk_level_min") is not None:
        result.categories_evaluated.append("risk_level_min")
        threshold = ct["risk_level_min"]
        risk_data = _get_risk_review(latest_result)
        level = risk_data.get("risk_level") if risk_data else None
        if level is not None:
            if _level_gte(level, threshold):
                result.triggered = True
                result.reasons.append(f"风险等级 {level} >= 阈值 {threshold}")
            else:
                result.reasons.append(f"风险等级 {level} < 阈值 {threshold}")
        else:
            result.missing_reasons.append("risk_level: 风险评估数据不可用")

    # ── Event severity trigger ────────────────────────────────
    if ct.get("event_severity_min") is not None:
        result.categories_evaluated.append("event_severity_min")
        threshold = ct["event_severity_min"]
        event_data = _get_event_data(latest_result)
        severity = event_data.get("max_severity") if event_data else None
        if severity is not None:
            if _level_gte(severity, threshold):
                result.triggered = True
                result.reasons.append(f"事件严重性 {severity} >= 阈值 {threshold}")
            else:
                result.reasons.append(f"事件严重性 {severity} < 阈值 {threshold}")
        else:
            result.missing_reasons.append("event_severity: 事件数据不可用")

    # ── Event keywords trigger ────────────────────────────────
    keywords = ct.get("event_keywords") or []
    if keywords:
        result.categories_evaluated.append("event_keywords")
        event_data = _get_event_data(latest_result)
        if event_data:
            matched = _match_event_keywords(event_data, keywords)
            if matched:
                result.triggered = True
                result.reasons.append(f"事件关键词匹配: {', '.join(matched)}")
            else:
                result.reasons.append(f"事件关键词未匹配: {', '.join(keywords)}")
        else:
            result.missing_reasons.append("event_keywords: 事件数据不可用")

    return result


# ── Internal helpers ──────────────────────────────────────────


def _get_valuation_data(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("valuation_data")


def _get_risk_review(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("risk_review")


def _get_event_data(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("event_data")


_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


def _level_gte(actual: str, threshold: str) -> bool:
    """Return True if actual level >= threshold level."""
    return _LEVEL_ORDER.get(actual, -1) >= _LEVEL_ORDER.get(threshold, -1)


def _match_event_keywords(event_data: dict, keywords: list[str]) -> list[str]:
    """Return list of matched keywords from event announcement titles."""
    matched = []
    announcements = event_data.get("announcements") or event_data.get("events") or []
    for ann in announcements:
        title = ann.get("title") or ann.get("name") or ""
        for kw in keywords:
            if kw.lower() in title.lower():
                if kw not in matched:
                    matched.append(kw)
    return matched
