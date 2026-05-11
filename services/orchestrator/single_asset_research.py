import uuid
from datetime import date

from services.data.mock_provider import get_mock_asset_data
from services.data.akshare_provider import get_akshare_asset_data
from services.data.qmt_provider import get_qmt_asset_data
from services.data.aggregator.research_data_aggregator import ResearchDataAggregator
from services.data.provider_contracts import (
    ProviderUnavailableError,
    get_provider_error_type,
)
from services.research.scoring_engine import score_asset
from services.agents.debate_agent import generate_debate_result
from services.llm.json_guard import LLMJsonError
from services.research.decision_guard import apply_decision_guard
from services.protocols.validation import validate_protocol


NO_LLM_TEMPLATE_WARNING = (
    "本报告为无 LLM 模式生成，观点部分为规则/模板化输出，"
    "不构成完整投研分析。"
)
LLM_JSON_FALLBACK_WARNING = (
    "LLM JSON 输出解析或校验失败，已回退到无 LLM 模板化观点。"
)


def _load_asset_data(symbol: str, data_source: str) -> dict:
    if data_source == "mock":
        return ResearchDataAggregator().enrich(get_mock_asset_data(symbol))

    if data_source == "akshare":
        asset_data = get_akshare_asset_data(symbol)
        asset_data["data_source_chain"] = ["akshare"]
        return ResearchDataAggregator().enrich(asset_data)

    if data_source == "qmt":
        try:
            asset_data = get_qmt_asset_data(symbol)
            asset_data["data_source_chain"] = ["qmt"]
            return ResearchDataAggregator().enrich(asset_data)
        except ProviderUnavailableError as qmt_error:
            fallback_data = get_akshare_asset_data(symbol)
            fallback_data["data_source_chain"] = ["qmt_failed", "akshare_fallback"]
            fallback_data["data_warnings"] = [
                f"QMT 数据源不可用，已回退到 AKShare：{qmt_error}"
            ]
            fallback_data["provider_run_log"] = [
                {
                    "provider": "qmt",
                    "dataset": "price_data",
                    "symbol": symbol,
                    "status": "failed",
                    "rows": 0,
                    "error": str(qmt_error),
                    "error_type": get_provider_error_type(qmt_error),
                    "as_of": str(date.today()),
                },
                *fallback_data.get("provider_run_log", []),
            ]
            return ResearchDataAggregator().enrich(fallback_data)

    raise ValueError(f"不支持的数据源：{data_source}")


def _build_partial_result(asset_data: dict, data_source: str, score_result: dict) -> dict:
    """构建评分阶段的 partial result（不含 debate_result 和 decision_guard）。"""
    return {
        "symbol": asset_data["symbol"],
        "name": asset_data["name"],
        "asset_type": asset_data["asset_type"],
        "as_of": asset_data["as_of"],
        "data_source": asset_data.get("data_source", data_source),
        "data_source_chain": asset_data.get(
            "data_source_chain",
            [asset_data.get("data_source", data_source)],
        ),
        "data_warnings": asset_data.get("data_warnings", []),
        "price_data": asset_data.get("price_data", {}),
        "fundamental_data": asset_data.get("fundamental_data", {}),
        "valuation_data": asset_data.get("valuation_data", {}),
        "event_data": asset_data.get("event_data", {}),
        "basic_info": asset_data.get("basic_info", {}),
        "source_metadata": asset_data.get("source_metadata", {}),
        "symbol_info": asset_data.get("symbol_info", {}),
        "fundamental_analysis": asset_data.get("fundamental_analysis", {}),
        "etf_data": asset_data.get("etf_data", {}),
        "data_quality": asset_data.get("data_quality", {}),
        "evidence_bundle": asset_data.get("evidence_bundle", {}),
        "provider_run_log": asset_data.get("provider_run_log", []),
        "score": score_result["total_score"],
        "rating": score_result["rating"],
        "action": score_result["action"],
        "score_breakdown": score_result["score_breakdown"],
        "bull_case": "基本面质量较高，盈利能力稳定，趋势结构有所改善。",
        "bear_case": "估值分位不低，短期继续上行需要新的催化因素。",
        "risk_review": "整体风险中等，适合观察或小仓位分批参与，不建议重仓追高。",
        "final_opinion": "未来1-3个月谨慎看多，建议回调时分批关注。",
        "max_position": "5%-8%",
    }


def mark_no_llm_template_result(result: dict) -> dict:
    result["analysis_mode"] = "template_no_llm"
    result["llm_enabled"] = False
    warnings = list(result.get("analysis_warnings", []))
    if NO_LLM_TEMPLATE_WARNING not in warnings:
        warnings.append(NO_LLM_TEMPLATE_WARNING)
    result["analysis_warnings"] = warnings
    return result


def mark_llm_json_fallback_result(
    result: dict,
    error: BaseException | str | None = None,
) -> dict:
    mark_no_llm_template_result(result)
    result["analysis_mode"] = "llm_json_fallback_template"
    warnings = list(result.get("analysis_warnings", []))
    warning = LLM_JSON_FALLBACK_WARNING
    if error:
        warning = f"{warning} 错误：{error}"
    if warning not in warnings:
        warnings.append(warning)
    result["analysis_warnings"] = warnings
    return result


def _is_llm_json_runtime_error(error: BaseException) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "json",
            "missing required fields",
            "invalid value",
            "must be",
            "no valid",
        )
    )


def start_hitl_research(
    symbol: str,
    data_source: str = "mock",
    max_rounds: int = 3,
) -> dict:
    """运行研究到 HITL 中断点，返回中间状态供人工审核。

    执行步骤：
    1. 加载数据 + 评分 → partial_result
    2. start_hitl_debate() → 暂停于 committee_convergence 节点

    Returns:
        {
            "partial_result": dict,   # 评分 + 数据（不含 debate_result/decision_guard）
            "hitl_state": dict,       # 中断时的 DebateState
            "thread_id": str,         # 用于 resume 的线程标识
        }
    """
    from services.agents.langgraph_orchestrator import start_hitl_debate

    asset_data = _load_asset_data(symbol, data_source)
    score_result = score_asset(asset_data)
    partial_result = _build_partial_result(asset_data, data_source, score_result)

    thread_id = f"debate-hitl-{symbol}-{uuid.uuid4().hex[:8]}"

    try:
        hitl_state = start_hitl_debate(
            partial_result,
            thread_id=thread_id,
            max_rounds=max_rounds,
        )
    except ImportError:
        raise
    except Exception:
        raise

    return {
        "partial_result": partial_result,
        "hitl_state": hitl_state,
        "thread_id": thread_id,
    }


def resume_hitl_research(
    partial_result: dict,
    thread_id: str,
    modified_state: dict | None = None,
) -> dict:
    """从 HITL 中断恢复，完成完整研究 pipeline。

    执行步骤：
    1. resume_hitl_debate() → 完成 committee_convergence + assemble_result
    2. 将 debate_result 合并到 result
    3. apply_decision_guard() + validate_protocol("final_decision")

    Args:
        partial_result: start_hitl_research 返回的 partial_result
        thread_id: 与 start_hitl_debate 相同的 thread_id
        modified_state: 可选的人工修改内容，传入 Command(resume=...)

    Returns:
        完整 result dict，与 run_single_asset_research 同构
    """
    from services.agents.langgraph_orchestrator import resume_hitl_debate

    debate_result = resume_hitl_debate(thread_id, modified_state)

    result = dict(partial_result)

    committee = debate_result.get("committee_conclusion", {})
    risk_review = debate_result.get("risk_review", {})

    result["debate_result"] = debate_result
    result["bull_case"] = debate_result.get("bull_case", {}).get(
        "thesis", result["bull_case"]
    )
    result["bear_case"] = debate_result.get("bear_case", {}).get(
        "thesis", result["bear_case"]
    )
    result["risk_review"] = risk_review.get(
        "risk_summary", result["risk_review"]
    )
    result["final_opinion"] = committee.get(
        "final_opinion", result["final_opinion"]
    )
    result["action"] = committee.get("action", result["action"])
    result["max_position"] = risk_review.get(
        "max_position", result["max_position"]
    )

    result = apply_decision_guard(result)
    validate_protocol("final_decision", result)
    return result


def run_single_asset_research(
    symbol: str,
    use_llm: bool = True,
    data_source: str = "mock",
    use_graph: bool = False,
) -> dict:
    """
    单只股票/ETF研究流程。

    Args:
        symbol: 股票/ETF 代码。
        use_llm: 是否启用 DeepSeek 辩论。
        data_source: 数据源（qmt/akshare/mock）。
        use_graph: 是否使用 LangGraph 完整 pipeline 图。默认 False 走顺序路径。
    """

    if use_graph:
        from services.agents.langgraph_orchestrator import run_full_research_graph
        return run_full_research_graph(
            symbol=symbol,
            data_source=data_source,
            use_llm=use_llm,
        )

    asset_data = _load_asset_data(symbol, data_source)
    score_result = score_asset(asset_data)
    result = _build_partial_result(asset_data, data_source, score_result)

    if use_llm:
        try:
            debate_result = generate_debate_result(result)
        except LLMJsonError as exc:
            mark_llm_json_fallback_result(result, exc)
        except RuntimeError as exc:
            if not _is_llm_json_runtime_error(exc):
                raise
            mark_llm_json_fallback_result(result, exc)
        else:

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
            result["analysis_mode"] = "llm_debate"
            result["llm_enabled"] = True
    else:
        mark_no_llm_template_result(result)

    result = apply_decision_guard(result)
    validate_protocol("final_decision", result)

    return result
