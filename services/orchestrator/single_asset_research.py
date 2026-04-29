from services.data.mock_provider import get_mock_asset_data
from services.data.akshare_provider import get_akshare_asset_data
from services.data.qmt_provider import get_qmt_asset_data
from services.data.supplemental_provider import merge_supplemental_data
from services.research.scoring_engine import score_asset
from services.agents.debate_agent import generate_debate_result
from services.research.decision_guard import apply_decision_guard
from services.protocols.validation import validate_protocol


def _load_asset_data(symbol: str, data_source: str) -> dict:
    if data_source == "mock":
        return get_mock_asset_data(symbol)

    if data_source == "akshare":
        asset_data = get_akshare_asset_data(symbol)
        asset_data["data_source_chain"] = ["akshare"]
        return merge_supplemental_data(asset_data)

    if data_source == "qmt":
        try:
            asset_data = get_qmt_asset_data(symbol)
            asset_data["data_source_chain"] = ["qmt"]
            return merge_supplemental_data(asset_data)
        except Exception as qmt_error:
            fallback_data = get_akshare_asset_data(symbol)
            fallback_data["data_source_chain"] = ["qmt_failed", "akshare_fallback"]
            fallback_data["data_warnings"] = [
                f"QMT 数据源不可用，已回退到 AKShare：{qmt_error}"
            ]
            return merge_supplemental_data(fallback_data)

    raise ValueError(f"不支持的数据源：{data_source}")


def run_single_asset_research(
    symbol: str,
    use_llm: bool = True,
    data_source: str = "mock",
) -> dict:
    """
    单只股票/ETF研究流程。
    当前阶段：
    1. 优先使用 QMT 数据，AKShare 只作为 fallback，mock 用于离线测试
    2. 本地计算评分
    3. 可选调用 DeepSeek 生成多头/空头/风险官/投委会结论
    """

    asset_data = _load_asset_data(symbol, data_source)
    score_result = score_asset(asset_data)

    result = {
        "symbol": asset_data["symbol"],
        "name": asset_data["name"],
        "asset_type": asset_data["asset_type"],
        "as_of": asset_data["as_of"],
        "data_source": asset_data.get("data_source", data_source),
        "data_source_chain": asset_data.get("data_source_chain", [asset_data.get("data_source", data_source)]),
        "data_warnings": asset_data.get("data_warnings", []),

        "price_data": asset_data.get("price_data", {}),
        "fundamental_data": asset_data.get("fundamental_data", {}),
        "valuation_data": asset_data.get("valuation_data", {}),
        "event_data": asset_data.get("event_data", {}),
        "basic_info": asset_data.get("basic_info", {}),
        "source_metadata": asset_data.get("source_metadata", {}),

        "score": score_result["total_score"],
        "rating": score_result["rating"],
        "action": score_result["action"],
        "score_breakdown": score_result["score_breakdown"],

        "bull_case": "基本面质量较高，盈利能力稳定，趋势结构有所改善。",
        "bear_case": "估值分位不低，短期继续上行需要新的催化因素。",
        "risk_review": "整体风险中等，适合观察或小仓位分批参与，不建议重仓追高。",
        "final_opinion": "未来1-3个月谨慎看多，建议回调时分批关注。",
        "max_position": "5%-8%"
    }

    if use_llm:
        debate_result = generate_debate_result(result)

        result["debate_result"] = debate_result

        committee = debate_result.get("committee_conclusion", {})
        risk_review = debate_result.get("risk_review", {})

        result["bull_case"] = debate_result.get("bull_case", {}).get(
            "thesis",
            result["bull_case"],
        )
        result["bear_case"] = debate_result.get("bear_case", {}).get(
            "thesis",
            result["bear_case"],
        )
        result["risk_review"] = risk_review.get(
            "risk_summary",
            result["risk_review"],
        )
        result["final_opinion"] = committee.get(
            "final_opinion",
            result["final_opinion"],
        )
        result["action"] = committee.get("action", result["action"])
        result["max_position"] = risk_review.get(
            "max_position",
            result["max_position"],
        )

    result = apply_decision_guard(result)
    validate_protocol("final_decision", result)

    return result
