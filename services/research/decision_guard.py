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
    }

    return result
