from services.protocols.validation import validate_protocol


def _section_source(asset_data: dict, section: str) -> str | None:
    return asset_data.get("source_metadata", {}).get(section, {}).get("source")


def _cap_placeholder_score(asset_data: dict, section: str, score: int, cap: int) -> int:
    if _section_source(asset_data, section) == "mock_placeholder":
        return min(score, cap)
    return score


def _rating_action(total_score: int) -> tuple[str, str]:
    if total_score >= 90:
        return "A", "分批买入"
    if total_score >= 80:
        return "B+", "回调关注"
    if total_score >= 70:
        return "B", "观察"
    if total_score >= 60:
        return "C", "谨慎观察"
    return "D", "回避"


def _event_policy_score(asset_data: dict) -> int:
    event = asset_data.get("event_data", {})
    summary = event.get("event_summary", {})
    events = event.get("events", [])

    if summary.get("critical_count", 0) > 0 or any(item.get("severity") == "critical" for item in events):
        return 0

    event_score = 6
    high_count = summary.get("high_severity_count", 0) or sum(
        1 for item in events if item.get("severity") == "high"
    )
    negative_count = summary.get("negative_count", 0) or sum(
        1 for item in events if item.get("sentiment") == "negative"
    )
    positive_catalysts = sum(
        1
        for item in events
        if item.get("event_type") in {"buyback", "dividend", "earnings_forecast", "major_contract"}
        and item.get("sentiment") in {"positive", "neutral_positive"}
    )

    event_score += min(3, positive_catalysts)
    event_score -= min(4, high_count * 2)
    event_score -= min(3, negative_count * 2)

    if event.get("recent_news_sentiment") == "neutral_positive":
        event_score += 1
    if event.get("policy_risk") == "low":
        event_score += 1

    event_score = max(0, min(10, event_score))
    return _cap_placeholder_score(asset_data, "event_data", event_score, 4)


def _price_scores(price: dict) -> tuple[int, int, int]:
    trend_score = 0
    if price.get("change_20d", 0) > 0:
        trend_score += 6
    if price.get("change_60d", 0) > 0:
        trend_score += 6
    if price.get("ma20_position") == "above":
        trend_score += 4
    if price.get("ma60_position") == "above":
        trend_score += 4

    liquidity_score = 13 if price.get("avg_turnover_20d", 0) > 500000000 else 8

    risk_score = 20
    if price.get("max_drawdown_60d", 0) < -0.15:
        risk_score -= 6
    elif price.get("max_drawdown_60d", 0) < -0.10:
        risk_score -= 3

    if price.get("volatility_60d", 0) > 0.30:
        risk_score -= 5
    elif price.get("volatility_60d", 0) > 0.20:
        risk_score -= 2

    return trend_score, liquidity_score, risk_score


def _score_stock(asset_data: dict) -> dict:
    price = asset_data["price_data"]
    fundamental = asset_data.get("fundamental_data", {})
    valuation = asset_data.get("valuation_data", {})

    trend_score, liquidity_score, risk_score = _price_scores(price)

    fundamental_score = 0
    if (fundamental.get("roe") or 0) > 0.15:
        fundamental_score += 6
    if (fundamental.get("gross_margin") or 0) > 0.4:
        fundamental_score += 4
    if (fundamental.get("net_profit_growth") or 0) > 0:
        fundamental_score += 4
    if (fundamental.get("revenue_growth") or 0) > 0:
        fundamental_score += 3
    debt_ratio = fundamental.get("debt_ratio")
    if debt_ratio is not None and debt_ratio < 0.5:
        fundamental_score += 3
    fundamental_score = _cap_placeholder_score(asset_data, "fundamental_data", fundamental_score, 8)

    valuation_score = 15
    pe_percentile = valuation.get("pe_percentile")
    pb_percentile = valuation.get("pb_percentile")
    pe_ttm = valuation.get("pe_ttm")
    if pe_ttm is not None and pe_ttm <= 0:
        valuation_score = 4
    elif pe_percentile is None and pb_percentile is None:
        valuation_score = 8
    else:
        if pe_percentile is not None and pe_percentile > 0.8:
            valuation_score -= 5
        elif pe_percentile is not None and pe_percentile > 0.6:
            valuation_score -= 3

        if pb_percentile is not None and pb_percentile > 0.8:
            valuation_score -= 3
        elif pb_percentile is not None and pb_percentile > 0.6:
            valuation_score -= 1
    valuation_score = _cap_placeholder_score(asset_data, "valuation_data", valuation_score, 6)

    event_score = _event_policy_score(asset_data)

    return {
        "trend_momentum": trend_score,
        "liquidity": liquidity_score,
        "fundamental_quality": fundamental_score,
        "valuation": valuation_score,
        "risk_control": risk_score,
        "event_policy": event_score,
    }


def _score_etf(asset_data: dict) -> dict:
    price = asset_data["price_data"]
    etf_data = asset_data.get("etf_data", {})
    trend_score, liquidity_base, risk_score = _price_scores(price)

    liquidity_score = 20 if price.get("avg_turnover_20d", 0) > 500000000 else 12
    premium_discount = etf_data.get("premium_discount")
    if premium_discount is None:
        premium_score = 8
    elif abs(premium_discount) <= 0.003:
        premium_score = 15
    elif abs(premium_discount) <= 0.01:
        premium_score = 11
    else:
        premium_score = 6

    scale_score = 8
    fund_size = etf_data.get("fund_size")
    if fund_size is not None:
        if fund_size >= 10_000_000_000:
            scale_score = 15
        elif fund_size >= 2_000_000_000:
            scale_score = 11

    event_score = _event_policy_score(asset_data)

    # Keep protocol-compatible keys while using ETF semantics.
    return {
        "trend_momentum": min(trend_score, 20),
        "liquidity": min(liquidity_score, 15),
        "fundamental_quality": min(scale_score, 20),
        "valuation": min(premium_score, 15),
        "risk_control": risk_score,
        "event_policy": event_score,
    }


def score_asset(asset_data: dict) -> dict:
    if asset_data.get("asset_type") == "etf":
        score_breakdown = _score_etf(asset_data)
    else:
        score_breakdown = _score_stock(asset_data)

    total_score = sum(score_breakdown.values())
    rating, action = _rating_action(total_score)
    result = {
        "total_score": total_score,
        "rating": rating,
        "action": action,
        "score_breakdown": score_breakdown,
    }

    validate_protocol("factor_score", result)
    return result
