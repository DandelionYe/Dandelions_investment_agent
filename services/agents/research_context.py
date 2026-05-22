"""Utilities for building compact, LLM-safe research context.

All agent prompts must use :func:`compact_research_result_for_llm` instead of
raw ``json.dumps(research_result)``.  This prevents large internal fields
(full peer lists, provider_run_log, raw provider payloads, etc.) from leaking
into LLM context windows and audit artefacts.
"""

from __future__ import annotations

from typing import Any

# ── Allowlists ────────────────────────────────────────────────────────

_TOP_LEVEL_KEYS = frozenset({
    "symbol",
    "name",
    "asset_type",
    "as_of",
    "data_source",
    "data_source_chain",
    "data_warnings",
    "score",
    "rating",
    "action",
    "max_position",
    "score_breakdown",
})

_PRICE_KEYS = frozenset({
    "close",
    "change_20d",
    "change_60d",
    "ma20_position",
    "ma60_position",
    "max_drawdown_60d",
    "volatility_60d",
    "avg_turnover_20d",
    "data_vendor",
    "latest_trade_date",
    "price_is_stale",
    "latest_price_source",
    "price_history_source",
    "price_uses_intraday_tick",
})

_FUNDAMENTAL_KEYS = frozenset({
    "roe",
    "gross_margin",
    "revenue_growth",
    "net_profit_growth",
    "debt_ratio",
    "operating_cashflow_quality",
})

_VALUATION_KEYS = frozenset({
    "market_cap",
    "pe_ttm",
    "pb_mrq",
    "ps_ttm",
    "pe_percentile",
    "pb_percentile",
    "ps_percentile",
    "dividend_yield",
    "valuation_label",
    # missing reasons
    "pe_ttm_missing_reason",
    "pb_mrq_missing_reason",
    "ps_ttm_missing_reason",
    "market_cap_missing_reason",
    "dividend_yield_missing_reason",
    # industry
    "industry_name",
    "industry_level",
    "industry_peer_count",
    "industry_valid_peer_count",
    "industry_valid_peer_count_pe",
    "industry_valid_peer_count_pb",
    "industry_valid_peer_count_ps",
    "industry_pe_percentile",
    "industry_pb_percentile",
    "industry_ps_percentile",
    "industry_valuation_label",
    "industry_valuation_source",
    "industry_valuation_warnings",
    "industry_percentile_missing_reason",
    "industry_pe_percentile_missing_reason",
    "industry_pb_percentile_missing_reason",
    "industry_ps_percentile_missing_reason",
})

_EVIDENCE_ITEM_KEYS = frozenset({
    "evidence_id",
    "category",
    "title",
    "display_value",
    "source",
    "source_date",
    "confidence",
    "url",
})

_EVENT_ITEM_KEYS = frozenset({
    "title",
    "summary",
    "severity",
    "sentiment",
    "source",
    "publish_time",
    "url",
})

_EVENT_DATA_KEYS = frozenset({
    "recent_news_sentiment",
    "policy_risk",
    "major_event",
})

_MAX_EVIDENCE_ITEMS = 20
_MAX_EVENT_ITEMS = 3


# ── Helpers ───────────────────────────────────────────────────────────

def _pick(mapping: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    """Return a new dict with only the specified keys from *mapping*."""
    return {k: v for k, v in mapping.items() if k in keys}


def _trim_evidence(bundle: dict[str, Any]) -> dict[str, Any]:
    items = bundle.get("items") or []
    trimmed = []
    for item in items[:_MAX_EVIDENCE_ITEMS]:
        trimmed.append(_pick(item, _EVIDENCE_ITEM_KEYS))
    return {
        "bundle_id": bundle.get("bundle_id"),
        "symbol": bundle.get("symbol"),
        "as_of": bundle.get("as_of"),
        "items": trimmed,
    }


def _trim_events(event_data: dict[str, Any]) -> dict[str, Any]:
    events = event_data.get("events") or []
    trimmed = []
    for event in events[:_MAX_EVENT_ITEMS]:
        if isinstance(event, dict):
            trimmed.append(_pick(event, _EVENT_ITEM_KEYS))
    result = _pick(event_data, _EVENT_DATA_KEYS)
    result["events"] = trimmed
    return result


# ── Public API ────────────────────────────────────────────────────────

def compact_research_result_for_llm(research_result: dict[str, Any]) -> dict[str, Any]:
    """Return a slimmed copy of *research_result* safe for LLM prompts.

    Removes:
    - ``provider_run_log``
    - ``industry_peer_inputs`` / ``peer_inputs`` / ``industry_members``
    - ``raw`` / ``raw_data`` fields inside any nested dict
    - Keys starting with ``_`` (internal bookkeeping)
    - Full ``source_metadata`` (too verbose for LLM)
    - ``basic_info``, ``symbol_info``, ``fundamental_analysis``, ``etf_data``
    - Full ``data_quality`` (kept as-is only if small; block fields stripped)

    Keeps only the summary fields listed in the module-level allowlists.
    """
    result: dict[str, Any] = {}

    # Top-level scalar / small dict keys
    for key in _TOP_LEVEL_KEYS:
        if key in research_result:
            result[key] = research_result[key]

    # Nested summary dicts
    price = research_result.get("price_data")
    if isinstance(price, dict):
        result["price_data"] = _pick(price, _PRICE_KEYS)

    fund = research_result.get("fundamental_data")
    if isinstance(fund, dict):
        result["fundamental_data"] = _pick(fund, _FUNDAMENTAL_KEYS)

    val = research_result.get("valuation_data")
    if isinstance(val, dict):
        result["valuation_data"] = _pick(val, _VALUATION_KEYS)

    event = research_result.get("event_data")
    if isinstance(event, dict):
        result["event_data"] = _trim_events(event)

    bundle = research_result.get("evidence_bundle")
    if isinstance(bundle, dict):
        result["evidence_bundle"] = _trim_evidence(bundle)

    # data_quality: keep a compact version
    dq = research_result.get("data_quality")
    if isinstance(dq, dict):
        result["data_quality"] = {
            "overall_confidence": dq.get("overall_confidence"),
            "has_placeholder": dq.get("has_placeholder"),
            "blocking_issues": dq.get("blocking_issues", []),
            "warnings": dq.get("warnings", []),
        }

    return result
