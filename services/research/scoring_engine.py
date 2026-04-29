from services.protocols.validation import validate_protocol


def _section_source(asset_data: dict, section: str) -> str | None:
    return asset_data.get("source_metadata", {}).get(section, {}).get("source")


def _cap_placeholder_score(asset_data: dict, section: str, score: int, cap: int) -> int:
    if _section_source(asset_data, section) == "mock_placeholder":
        return min(score, cap)
    return score


def score_asset(asset_data: dict) -> dict:
    """
    根据模拟数据计算一个简化版投研评分。
    第一版先不追求严谨，只验证流程。
    """

    price = asset_data["price_data"]
    fundamental = asset_data["fundamental_data"]
    valuation = asset_data["valuation_data"]
    event = asset_data["event_data"]

    # 1. 趋势动量：20分
    trend_score = 0
    if price["change_20d"] > 0:
        trend_score += 6
    if price["change_60d"] > 0:
        trend_score += 6
    if price["ma20_position"] == "above":
        trend_score += 4
    if price["ma60_position"] == "above":
        trend_score += 4

    # 2. 流动性：15分
    liquidity_score = 13 if price["avg_turnover_20d"] > 500000000 else 8

    # 3. 基本面质量：20分
    fundamental_score = 0
    if fundamental["roe"] > 0.15:
        fundamental_score += 6
    if fundamental["gross_margin"] > 0.4:
        fundamental_score += 4
    if fundamental["net_profit_growth"] > 0:
        fundamental_score += 4
    if fundamental["revenue_growth"] > 0:
        fundamental_score += 3
    if fundamental["debt_ratio"] < 0.5:
        fundamental_score += 3
    fundamental_score = _cap_placeholder_score(
        asset_data,
        "fundamental_data",
        fundamental_score,
        8,
    )

    # 4. 估值性价比：15分
    valuation_score = 15
    if valuation["pe_percentile"] > 0.8:
        valuation_score -= 5
    elif valuation["pe_percentile"] > 0.6:
        valuation_score -= 3

    if valuation["pb_percentile"] > 0.8:
        valuation_score -= 3
    elif valuation["pb_percentile"] > 0.6:
        valuation_score -= 1
    valuation_score = _cap_placeholder_score(
        asset_data,
        "valuation_data",
        valuation_score,
        6,
    )

    # 5. 风险控制：20分
    risk_score = 20
    if price["max_drawdown_60d"] < -0.15:
        risk_score -= 6
    elif price["max_drawdown_60d"] < -0.10:
        risk_score -= 3

    if price["volatility_60d"] > 0.30:
        risk_score -= 5
    elif price["volatility_60d"] > 0.20:
        risk_score -= 2

    # 6. 事件/政策：10分
    event_score = 6
    if event["recent_news_sentiment"] == "neutral_positive":
        event_score += 2
    if event["policy_risk"] == "low":
        event_score += 2
    event_score = _cap_placeholder_score(
        asset_data,
        "event_data",
        event_score,
        4,
    )

    total_score = (
        trend_score
        + liquidity_score
        + fundamental_score
        + valuation_score
        + risk_score
        + event_score
    )

    if total_score >= 90:
        rating = "A"
        action = "分批买入"
    elif total_score >= 80:
        rating = "B+"
        action = "回调关注"
    elif total_score >= 70:
        rating = "B"
        action = "观察"
    elif total_score >= 60:
        rating = "C"
        action = "谨慎观察"
    else:
        rating = "D"
        action = "回避"

    result = {
        "total_score": total_score,
        "rating": rating,
        "action": action,
        "score_breakdown": {
            "trend_momentum": trend_score,
            "liquidity": liquidity_score,
            "fundamental_quality": fundamental_score,
            "valuation": valuation_score,
            "risk_control": risk_score,
            "event_policy": event_score
        }
    }

    validate_protocol("factor_score", result)
    return result
