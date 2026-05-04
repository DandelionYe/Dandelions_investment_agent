ACTION_LEVEL = {
    "回避": 0,
    "谨慎观察": 1,
    "观察": 2,
    "回调关注": 2,
    "持有": 3,
    "分批买入": 4,
    "买入": 5,
}


def get_max_allowed_action(score: int, rating: str, risk_level: str | None = None) -> str:
    """
    根据本地评分和风险等级，限制 DeepSeek 最终建议的激进程度。
    """

    if score < 55:
        max_action = "回避"
    elif score < 65:
        max_action = "谨慎观察"
    elif score < 75:
        max_action = "观察"
    elif score < 85:
        max_action = "分批买入"
    else:
        max_action = "买入"

    # 风险官为 high 时，最多只能观察
    if risk_level == "high":
        max_action = "观察"

    # 风险官为 medium 且分数不足 75 时，最多只能观察
    if risk_level == "medium" and score < 75:
        max_action = "观察"

    return max_action


def clamp_action(action: str, max_allowed_action: str) -> str:
    """
    如果 DeepSeek 给出的建议过于激进，则降级。
    """

    action_level = ACTION_LEVEL.get(action, 2)
    max_level = ACTION_LEVEL.get(max_allowed_action, 2)

    if action_level > max_level:
        return max_allowed_action

    return action


def _lower_action_ceiling(current: str, candidate: str) -> str:
    current_level = ACTION_LEVEL.get(current, 2)
    candidate_level = ACTION_LEVEL.get(candidate, 2)
    return candidate if candidate_level < current_level else current


def apply_data_quality_action_limits(result: dict, max_allowed_action: str) -> tuple[str, list[str]]:
    data_quality = result.get("data_quality", {})
    source_metadata = result.get("source_metadata", {})
    event_data = result.get("event_data", {})
    asset_type = result.get("asset_type", "stock")
    guard_reasons: list[str] = []

    if data_quality.get("has_placeholder"):
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")
        guard_reasons.append("存在 placeholder 数据，最高建议限制为观察。")

    blocking_issues = data_quality.get("blocking_issues") or []
    if blocking_issues:
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")
        guard_reasons.append("存在数据质量阻断项，最高建议限制为观察。")

    event_summary = event_data.get("event_summary", {})
    has_critical_event = event_summary.get("critical_count", 0) > 0 or any(
        "critical" in str(issue).lower() or "critical" in str(issue)
        for issue in blocking_issues
    )
    if has_critical_event:
        max_allowed_action = "回避"
        guard_reasons.append("存在 critical 事件，最高建议限制为回避。")

    if asset_type == "stock" and not result.get("valuation_data"):
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")
        guard_reasons.append("valuation_data 缺失，最高建议限制为观察。")

    if asset_type == "stock" and not result.get("fundamental_data"):
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")
        guard_reasons.append("股票 fundamental_data 缺失，最高建议限制为观察。")

    if source_metadata.get("valuation_data", {}).get("source") == "mock_placeholder":
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")
    if asset_type == "stock" and source_metadata.get("fundamental_data", {}).get("source") == "mock_placeholder":
        max_allowed_action = _lower_action_ceiling(max_allowed_action, "观察")

    return max_allowed_action, guard_reasons


def apply_decision_guard(result: dict) -> dict:
    """
    对最终研究结果做安全收敛：
    1. 防止 DeepSeek 给出过激买入建议
    2. 统一 action
    3. 补充 guard 信息
    """

    score = int(result.get("score", 0))
    rating = result.get("rating", "")
    debate_result = result.get("debate_result", {})
    risk_review = debate_result.get("risk_review", {})
    committee = debate_result.get("committee_conclusion", {})

    risk_level = risk_review.get("risk_level")
    llm_action = committee.get("action", result.get("action", "观察"))

    max_allowed_action = get_max_allowed_action(
        score=score,
        rating=rating,
        risk_level=risk_level,
    )
    max_allowed_action, guard_reasons = apply_data_quality_action_limits(
        result,
        max_allowed_action,
    )

    guarded_action = clamp_action(llm_action, max_allowed_action)

    result["action"] = guarded_action

    if committee:
        committee["raw_action"] = llm_action
        committee["action"] = guarded_action

        if guarded_action != llm_action:
            committee["final_opinion"] = (
                committee.get("final_opinion", "")
                + f" 但由于本地评分为{score}分、评级为{rating}，"
                + f"系统将操作建议从“{llm_action}”降级为“{guarded_action}”。"
            )

            result["final_opinion"] = committee["final_opinion"]

    result["decision_guard"] = {
        "enabled": True,
        "score": score,
        "rating": rating,
        "risk_level": risk_level,
        "llm_action": llm_action,
        "max_allowed_action": max_allowed_action,
        "final_action": guarded_action,
        "guard_reasons": guard_reasons,
    }

    return result
