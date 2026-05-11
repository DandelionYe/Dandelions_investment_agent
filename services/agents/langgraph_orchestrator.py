"""
LangGraph 投委会辩论编排器（多轮辩论版）。

构建有状态多轮辩论工作流：

    START
      │
      ▼
  run_initial_round (Bull/Bear/Risk 并行初始分析)
      │
      ▼
  supervisor_judge (LLM 主持人评估收敛/指定下一发言人)
      │
      ├── is_converged ──→ committee_convergence → assemble_result → END
      │
      └── next_speaker ──→ bull_challenge ──┐
                        → bear_challenge ──┤
                        → risk_challenge ──┘
                              │
                              ▼
                        supervisor_judge (循环)

每个 Agent 作为独立节点可单独调用。在 committee_convergence 节点
支持 human-in-the-loop（HITL）中断。
"""

import concurrent.futures
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig

from services.agents.bull_analyst import BullAnalyst
from services.agents.bear_analyst import BearAnalyst
from services.agents.risk_officer import RiskOfficer
from services.agents.committee_secretary import CommitteeSecretary
from services.agents.supervisor import Supervisor
from services.protocols.validation import validate_protocol


_DEBATE_CHECKPOINTER = MemorySaver()
_FULL_RESEARCH_CHECKPOINTER = MemorySaver()


# ── 状态定义 ──────────────────────────────────────────────────────

class DebateState(TypedDict):
    """LangGraph 多轮辩论工作流状态。

    所有字段通过节点返回值做部分更新（partial state update）。
    """
    research_result: dict
    bull_case: dict | None
    bear_case: dict | None
    risk_review: dict | None
    committee_conclusion: dict | None
    debate_result: dict | None
    error: str | None

    # 多轮辩论扩展字段
    debate_history: list[dict]
    current_round: int
    max_rounds: int
    supervisor_decision: dict | None


# ── Round 1：并行初始分析 ────────────────────────────────────────

def _node_run_initial_round(state: DebateState) -> dict:
    """并行运行 Bull/Bear/Risk 三个 Agent 的初始分析。"""
    research_result = state["research_result"]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            bull_fut = pool.submit(BullAnalyst().analyze, research_result)
            bear_fut = pool.submit(BearAnalyst().analyze, research_result)
            risk_fut = pool.submit(RiskOfficer().review, research_result)

            bull_case = bull_fut.result(timeout=90)
            bear_case = bear_fut.result(timeout=90)
            risk_review = risk_fut.result(timeout=90)
    except Exception as e:
        return {"error": f"初始并行分析失败：{e}"}

    history_entry = {
        "round": 0,
        "type": "initial",
        "speaker": "all",
        "outputs": {
            "bull_case": bull_case,
            "bear_case": bear_case,
            "risk_review": risk_review,
        },
    }

    return {
        "bull_case": bull_case,
        "bear_case": bear_case,
        "risk_review": risk_review,
        "debate_history": [history_entry],
        "current_round": 0,
    }


# ── Supervisor 节点 ───────────────────────────────────────────

def _node_supervisor_judge(state: DebateState, config: RunnableConfig) -> dict:
    """Supervisor 评估辩论状态，决定收敛或下一轮质询。"""
    max_rounds = config.get("configurable", {}).get("max_rounds", 3)
    current_round = state.get("current_round", 0)

    if current_round >= max_rounds:
        decision = {
            "is_converged": True,
            "convergence_reason": "max_rounds_reached",
            "next_speaker": None,
            "challenge": None,
            "round_summary": f"达到最大辩论轮次上限({max_rounds})，强制收敛。",
        }
    else:
        try:
            supervisor = Supervisor()
            decision = supervisor.evaluate(
                research_result=state["research_result"],
                bull_case=state["bull_case"],
                bear_case=state["bear_case"],
                risk_review=state["risk_review"],
                debate_history=state.get("debate_history", []),
                current_round=current_round,
                max_rounds=max_rounds,
            )
        except Exception as e:
            return {"error": f"Supervisor 评估失败：{e}"}

    decision.setdefault("is_converged", False)
    decision.setdefault("next_speaker", None)
    decision.setdefault("challenge", None)

    history_entry = {
        "round": current_round + 1,
        "type": "supervisor_judgment",
        "speaker": "supervisor",
        "decision": decision,
    }

    return {
        "supervisor_decision": decision,
        "debate_history": state.get("debate_history", []) + [history_entry],
        "current_round": current_round + 1,
    }


# ── 质询回应节点 ─────────────────────────────────────────────────

def _node_bull_challenge(state: DebateState) -> dict:
    """Bull 回应 Supervisor 的质询。"""
    decision = state.get("supervisor_decision", {})
    challenge = decision.get("challenge", "")

    analyst = BullAnalyst()
    bull_case = analyst.analyze(
        research_result=state["research_result"],
        challenge=challenge,
        debate_history=state.get("debate_history", []),
    )

    history_entry = {
        "round": state.get("current_round", 0),
        "type": "challenge_response",
        "speaker": "bull",
        "challenge": challenge,
        "output": bull_case,
    }

    return {
        "bull_case": bull_case,
        "debate_history": state.get("debate_history", []) + [history_entry],
    }


def _node_bear_challenge(state: DebateState) -> dict:
    """Bear 回应 Supervisor 的质询。"""
    decision = state.get("supervisor_decision", {})
    challenge = decision.get("challenge", "")

    analyst = BearAnalyst()
    bear_case = analyst.analyze(
        research_result=state["research_result"],
        challenge=challenge,
        debate_history=state.get("debate_history", []),
    )

    history_entry = {
        "round": state.get("current_round", 0),
        "type": "challenge_response",
        "speaker": "bear",
        "challenge": challenge,
        "output": bear_case,
    }

    return {
        "bear_case": bear_case,
        "debate_history": state.get("debate_history", []) + [history_entry],
    }


def _node_risk_challenge(state: DebateState) -> dict:
    """Risk 回应 Supervisor 的质询。"""
    decision = state.get("supervisor_decision", {})
    challenge = decision.get("challenge", "")

    officer = RiskOfficer()
    risk_review = officer.review(
        research_result=state["research_result"],
        challenge=challenge,
        debate_history=state.get("debate_history", []),
    )

    history_entry = {
        "round": state.get("current_round", 0),
        "type": "challenge_response",
        "speaker": "risk",
        "challenge": challenge,
        "output": risk_review,
    }

    return {
        "risk_review": risk_review,
        "debate_history": state.get("debate_history", []) + [history_entry],
    }


# ── 收敛与组装节点 ─────────────────────────────────────────────────

def _node_committee_convergence(
    state: DebateState, config: RunnableConfig
) -> dict:
    """投委会秘书节点：整合三方意见 + 辩论历史，形成最终结论。

    支持 human-in-the-loop：当 config.configurable.human_in_the_loop 为 True 时，
    在 committee 分析前暂停，允许人工审核。
    """
    hitl = config.get("configurable", {}).get("human_in_the_loop", False)

    if hitl:
        review_package = {
            "message": (
                "多轮辩论已完成。请审核以下内容：\n"
                "  - bull_case: 多头最终观点\n"
                "  - bear_case: 空头最终观点\n"
                "  - risk_review: 风险官最终评估\n"
                "  - debate_history: 完整辩论历程\n"
                "如需修改，请通过 Command(resume=modified_state) 传入调整后的状态。\n"
                "直接恢复则按原样继续收敛。"
            ),
            "bull_case": state.get("bull_case"),
            "bear_case": state.get("bear_case"),
            "risk_review": state.get("risk_review"),
            "debate_history": state.get("debate_history"),
            "research_summary": {
                "symbol": state["research_result"].get("symbol"),
                "name": state["research_result"].get("name"),
                "score": state["research_result"].get("score"),
                "rating": state["research_result"].get("rating"),
            },
        }
        resume_value = interrupt(review_package)
    else:
        resume_value = None

    overrides = resume_value if isinstance(resume_value, dict) else {}
    bull_case = overrides.get("bull_case") or state["bull_case"]
    bear_case = overrides.get("bear_case") or state["bear_case"]
    risk_review = overrides.get("risk_review") or state["risk_review"]

    secretary = CommitteeSecretary()
    conclusion = secretary.converge(
        research_result=state["research_result"],
        bull_case=bull_case,
        bear_case=bear_case,
        risk_review=risk_review,
        debate_history=state.get("debate_history"),
    )

    if isinstance(overrides.get("action"), str) and overrides["action"].strip():
        conclusion["action"] = overrides["action"].strip()
    if (
        isinstance(overrides.get("reviewer_notes"), str)
        and overrides["reviewer_notes"].strip()
    ):
        conclusion["reviewer_notes"] = overrides["reviewer_notes"].strip()

    return {
        "bull_case": bull_case,
        "bear_case": bear_case,
        "risk_review": risk_review,
        "committee_conclusion": conclusion,
    }


def _node_assemble_result(state: DebateState) -> dict:
    """组装最终 debate_result 并通过协议验证。"""
    debate_result = {
        "bull_case": state["bull_case"],
        "bear_case": state["bear_case"],
        "risk_review": state["risk_review"],
        "committee_conclusion": state["committee_conclusion"],
        "debate_history": state.get("debate_history", []),
    }

    validate_protocol("debate_result", debate_result)
    return {"debate_result": debate_result}


def _node_error_handler(state: DebateState) -> dict:
    """错误处理节点（由条件边路由至此）。"""
    return {
        "debate_result": {
            "bull_case": {"thesis": f"流程异常：{state.get('error', '未知错误')}"},
            "bear_case": {"thesis": "流程异常"},
            "risk_review": {"risk_level": "high", "blocking": True},
            "committee_conclusion": {
                "stance": "回避",
                "action": "回避",
                "confidence": 0.0,
                "final_opinion": f"辩论流程异常终止：{state.get('error', '未知错误')}",
            },
            "debate_history": state.get("debate_history", []),
        }
    }


# ── 路由函数 ──────────────────────────────────────────────────────

def _route_after_initial(state: DebateState) -> str:
    """初始轮之后的路由：有错误跳错误处理，否则进入 supervisor。"""
    if state.get("error"):
        return "error_handler"
    return "supervisor_judge"


def _route_after_supervisor(state: DebateState) -> str:
    """Supervisor 评估之后的路由：收敛/质询/错误。"""
    if state.get("error"):
        return "error_handler"

    decision = state.get("supervisor_decision", {})
    if decision.get("is_converged"):
        return "committee_convergence"

    next_speaker = decision.get("next_speaker", "")
    if next_speaker == "bull":
        return "bull_challenge"
    elif next_speaker == "bear":
        return "bear_challenge"
    elif next_speaker == "risk":
        return "risk_challenge"

    # 无效 speaker，安全降级为收敛
    return "committee_convergence"


# ── 图构建 ────────────────────────────────────────────────────────

def build_debate_graph() -> CompiledStateGraph:
    """构建并编译 LangGraph 多轮辩论工作流。

    Returns:
        编译后的 CompiledStateGraph，已挂载 MemorySaver 做检查点。
    """

    builder = StateGraph(DebateState)

    # 注册节点
    builder.add_node("run_initial_round", _node_run_initial_round)
    builder.add_node("supervisor_judge", _node_supervisor_judge)
    builder.add_node("bull_challenge", _node_bull_challenge)
    builder.add_node("bear_challenge", _node_bear_challenge)
    builder.add_node("risk_challenge", _node_risk_challenge)
    builder.add_node("committee_convergence", _node_committee_convergence)
    builder.add_node("assemble_result", _node_assemble_result)
    builder.add_node("error_handler", _node_error_handler)

    # START → 初始并行分析
    builder.add_edge(START, "run_initial_round")

    # 初始轮 → supervisor（或错误）
    builder.add_conditional_edges(
        "run_initial_round",
        _route_after_initial,
        {
            "supervisor_judge": "supervisor_judge",
            "error_handler": "error_handler",
        },
    )

    # supervisor → 收敛 / 质询 / 错误
    builder.add_conditional_edges(
        "supervisor_judge",
        _route_after_supervisor,
        {
            "committee_convergence": "committee_convergence",
            "bull_challenge": "bull_challenge",
            "bear_challenge": "bear_challenge",
            "risk_challenge": "risk_challenge",
            "error_handler": "error_handler",
        },
    )

    # 质询节点 → 回到 supervisor（形成循环）
    builder.add_edge("bull_challenge", "supervisor_judge")
    builder.add_edge("bear_challenge", "supervisor_judge")
    builder.add_edge("risk_challenge", "supervisor_judge")

    # 收敛 → 组装 → 结束
    builder.add_edge("committee_convergence", "assemble_result")
    builder.add_edge("assemble_result", END)
    builder.add_edge("error_handler", END)

    return builder.compile(checkpointer=_DEBATE_CHECKPOINTER)


# ── 公开 API ──────────────────────────────────────────────────────

def generate_debate_result_langgraph(
    research_result: dict,
    *,
    thread_id: str | None = None,
    max_rounds: int | None = None,
) -> dict:
    """使用 LangGraph 编排完整的多轮投委会辩论流程（无中断模式）。

    Args:
        research_result: 单票研究结果。
        thread_id: 检查点线程标识。默认自动生成。
        max_rounds: 最大辩论轮次（不含初始轮），默认 3。

    Returns:
        完整的 debate_result dict，已通过协议验证。
    """

    graph = build_debate_graph()

    initial_state: DebateState = {
        "research_result": research_result,
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "error": None,
        "debate_history": [],
        "current_round": 0,
        "max_rounds": max_rounds or 3,
        "supervisor_decision": None,
    }

    config = {
        "configurable": {
            "thread_id": thread_id
            or f"debate-{research_result.get('symbol', 'unknown')}",
            "human_in_the_loop": False,
            "max_rounds": max_rounds or 3,
        }
    }

    final_state = graph.invoke(initial_state, config)

    if final_state.get("error"):
        raise RuntimeError(
            f"LangGraph 辩论流程出错：{final_state['error']}"
        )

    return final_state["debate_result"]


def start_hitl_debate(
    research_result: dict,
    *,
    thread_id: str | None = None,
    max_rounds: int | None = None,
) -> dict:
    """启动带 human-in-the-loop 中断的多轮辩论流程。

    在多轮辩论完成后，在 committee_convergence 节点暂停，
    返回包含三方分析结果和辩论历史的中间状态，供人工审核。

    Args:
        research_result: 单票研究结果。
        thread_id: 检查点线程标识。
        max_rounds: 最大辩论轮次，默认 3。

    Returns:
        中断时的 DebateState，包含 __interrupt__ 信息。
    """

    graph = build_debate_graph()

    initial_state: DebateState = {
        "research_result": research_result,
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "error": None,
        "debate_history": [],
        "current_round": 0,
        "max_rounds": max_rounds or 3,
        "supervisor_decision": None,
    }

    config = {
        "configurable": {
            "thread_id": thread_id
            or f"debate-hitl-{research_result.get('symbol', 'unknown')}",
            "human_in_the_loop": True,
            "max_rounds": max_rounds or 3,
        }
    }

    interrupted_state = graph.invoke(initial_state, config)

    if "__interrupt__" not in interrupted_state:
        raise RuntimeError(
            "HITL 中断未触发，流程可能已完成（这可能表示配置有误）。"
        )

    return interrupted_state


def resume_hitl_debate(
    thread_id: str,
    modified_state: dict | None = None,
) -> dict:
    """恢复 HITL 中断的辩论流程，完成 committee_convergence 和 assemble_result。

    Args:
        thread_id: 与 start_hitl_debate() 相同的 thread_id。
        modified_state: 可选的修改内容。

    Returns:
        完整的 debate_result dict。
    """

    graph = build_debate_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "human_in_the_loop": True,
        }
    }

    resume_value = modified_state or {"approved": True}
    final_state = graph.invoke(Command(resume=resume_value), config)

    return final_state["debate_result"]


# ═══════════════════════════════════════════════════════════════════
#  完整端到端研究 Pipeline 图
# ═══════════════════════════════════════════════════════════════════

class FullResearchState(TypedDict):
    """LangGraph 完整研究 pipeline 状态。

    从 symbol 输入到 final_result 输出，覆盖数据加载、评分、辩论、决策保护。
    """
    symbol: str
    data_source: str
    max_debate_rounds: int
    use_llm: bool

    # 数据加载阶段
    asset_data: dict | None
    data_error: str | None

    # 评分阶段
    score_result: dict | None
    partial_result: dict | None

    # 辩论阶段
    research_result: dict | None
    bull_case: dict | None
    bear_case: dict | None
    risk_review: dict | None
    committee_conclusion: dict | None
    debate_result: dict | None
    debate_history: list[dict]
    current_round: int
    supervisor_decision: dict | None
    debate_error: str | None

    # 决策保护阶段
    final_result: dict | None
    error: str | None


# ── 全图节点函数 ─────────────────────────────────────────────────

def _full_node_load_research_data(
    state: FullResearchState, config: RunnableConfig,
) -> dict:
    """加载并聚合资产数据."""
    from services.orchestrator.single_asset_research import _load_asset_data

    symbol = state["symbol"]
    data_source = state.get("data_source", "mock")

    try:
        asset_data = _load_asset_data(symbol, data_source)
    except Exception as exc:
        return {"data_error": f"数据加载失败（{data_source}）：{exc}"}

    return {
        "asset_data": asset_data,
        "data_error": None,
    }


def _full_node_score_asset(state: FullResearchState) -> dict:
    """六维度量化评分."""
    from services.research.scoring_engine import score_asset

    asset_data = state["asset_data"]
    score_result = score_asset(asset_data)

    partial_result = {
        "symbol": asset_data["symbol"],
        "name": asset_data["name"],
        "asset_type": asset_data["asset_type"],
        "as_of": asset_data["as_of"],
        "data_source": asset_data.get("data_source", state.get("data_source", "mock")),
        "data_source_chain": asset_data.get(
            "data_source_chain",
            [asset_data.get("data_source", state.get("data_source", "mock"))],
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

    if not state.get("use_llm", True):
        from services.orchestrator.single_asset_research import mark_no_llm_template_result

        mark_no_llm_template_result(partial_result)

    return {
        "score_result": score_result,
        "partial_result": partial_result,
        "research_result": partial_result,
    }


def _full_node_run_debate_subgraph(
    state: FullResearchState, config: RunnableConfig,
) -> dict:
    """调用现有 8 节点辩论子图."""
    partial_result = state["partial_result"]
    max_rounds = state.get("max_debate_rounds", 3)

    if not state.get("use_llm", True):
        return {
            "debate_result": None,
            "bull_case": None,
            "bear_case": None,
            "risk_review": None,
            "committee_conclusion": None,
            "debate_history": [],
            "research_result": partial_result,
            "debate_error": None,
        }

    debate_state: DebateState = {
        "research_result": partial_result,
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "error": None,
        "debate_history": [],
        "current_round": 0,
        "max_rounds": max_rounds,
        "supervisor_decision": None,
    }

    debate_config: RunnableConfig = {
        "configurable": {
            "thread_id": (
                config.get("configurable", {}).get("thread_id", "full")
                + "-debate"
            ),
            "human_in_the_loop": False,
            "max_rounds": max_rounds,
        }
    }

    try:
        debate_graph = build_debate_graph()
        final_ds = debate_graph.invoke(debate_state, debate_config)
    except Exception as exc:
        return {"debate_error": f"辩论子图执行失败：{exc}"}

    if final_ds.get("error"):
        return {"debate_error": final_ds["error"]}

    debate_result = final_ds.get("debate_result", {})
    committee = debate_result.get("committee_conclusion", {})
    risk_review_result = debate_result.get("risk_review", {})

    merged = dict(partial_result)
    merged["debate_result"] = debate_result
    merged["bull_case"] = debate_result.get("bull_case", {}).get("thesis", merged["bull_case"])
    merged["bear_case"] = debate_result.get("bear_case", {}).get("thesis", merged["bear_case"])
    merged["risk_review"] = risk_review_result.get("risk_summary", merged["risk_review"])
    merged["final_opinion"] = committee.get("final_opinion", merged["final_opinion"])
    merged["action"] = committee.get("action", merged["action"])
    merged["max_position"] = risk_review_result.get("max_position", merged["max_position"])

    return {
        "debate_result": debate_result,
        "bull_case": final_ds.get("bull_case"),
        "bear_case": final_ds.get("bear_case"),
        "risk_review": final_ds.get("risk_review"),
        "committee_conclusion": final_ds.get("committee_conclusion"),
        "debate_history": final_ds.get("debate_history", []),
        "research_result": merged,
        "debate_error": None,
    }


def _full_node_hitl_review(
    state: FullResearchState, config: RunnableConfig,
) -> dict:
    """全图级 HITL 审核暂停点（辩论完成后、决策保护器执行前）."""
    hitl = config.get("configurable", {}).get("human_in_the_loop", False)
    if not hitl:
        return {}

    partial_result = state.get("partial_result", {})
    review_package = {
        "message": (
            "完整研究 pipeline 已执行到辩论阶段。请审核后继续。"
        ),
        "research_summary": {
            "symbol": state.get("symbol"),
            "score": partial_result.get("score"),
            "rating": partial_result.get("rating"),
        },
        "bull_case": state.get("bull_case"),
        "bear_case": state.get("bear_case"),
        "risk_review": state.get("risk_review"),
        "committee_conclusion": state.get("committee_conclusion"),
        "debate_history": state.get("debate_history"),
    }
    interrupt(review_package)
    return {}


def _full_node_apply_decision_guard(state: FullResearchState) -> dict:
    """应用决策保护器，约束最终建议."""
    from services.research.decision_guard import apply_decision_guard

    partial_result = dict(state["partial_result"])
    debate_result = state.get("debate_result")

    if debate_result:
        committee = debate_result.get("committee_conclusion", {})
        risk_review = debate_result.get("risk_review", {})
        partial_result["debate_result"] = debate_result
        partial_result["bull_case"] = debate_result.get("bull_case", {}).get(
            "thesis", partial_result.get("bull_case", "")
        )
        partial_result["bear_case"] = debate_result.get("bear_case", {}).get(
            "thesis", partial_result.get("bear_case", "")
        )
        partial_result["risk_review"] = risk_review.get(
            "risk_summary", partial_result.get("risk_review", "")
        )
        partial_result["final_opinion"] = committee.get(
            "final_opinion", partial_result.get("final_opinion", "")
        )
        partial_result["action"] = committee.get(
            "action", partial_result.get("action", "")
        )
        partial_result["max_position"] = risk_review.get(
            "max_position", partial_result.get("max_position", "")
        )

    final_result = apply_decision_guard(partial_result)
    return {"final_result": final_result}


def _full_node_validate_and_assemble(state: FullResearchState) -> dict:
    """协议验证并标记完成."""
    validate_protocol("final_decision", state["final_result"])
    return {}


def _full_node_handle_data_error(state: FullResearchState) -> dict:
    """数据加载失败时降级为 mock placeholder."""
    from services.data.mock_provider import get_mock_asset_data
    from services.data.aggregator.research_data_aggregator import ResearchDataAggregator
    from services.research.scoring_engine import score_asset

    asset_data = ResearchDataAggregator().enrich(
        get_mock_asset_data(state["symbol"])
    )
    asset_data["data_warnings"] = asset_data.get("data_warnings", []) + [
        f"数据加载失败已降级为 mock placeholder：{state.get('data_error', '未知错误')}"
    ]

    score_result = score_asset(asset_data)

    partial_result = {
        "symbol": asset_data["symbol"],
        "name": asset_data["name"],
        "asset_type": asset_data["asset_type"],
        "as_of": asset_data["as_of"],
        "data_source": "mock",
        "data_source_chain": ["mock_placeholder"],
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
        "action": "回避",
        "score_breakdown": score_result["score_breakdown"],
        "bull_case": "数据异常，无法生成多头观点。",
        "bear_case": "数据异常，无法生成空头观点。",
        "risk_review": "数据异常，风险无法评估。",
        "final_opinion": f"数据加载失败（{state.get('data_error', '未知错误')}），建议回避。",
        "max_position": "0%",
    }

    final_result = apply_decision_guard(partial_result)
    final_result["debate_result"] = {
        "bull_case": {"thesis": "数据异常"},
        "bear_case": {"thesis": "数据异常"},
        "risk_review": {"risk_level": "high", "blocking": True, "risk_summary": "数据异常"},
        "committee_conclusion": {
            "stance": "回避", "action": "回避", "confidence": 0.0,
            "final_opinion": f"数据加载失败：{state.get('data_error', '未知错误')}",
        },
        "debate_history": [],
    }

    return {
        "asset_data": asset_data,
        "score_result": score_result,
        "partial_result": partial_result,
        "debate_history": [],
        "research_result": partial_result,
        "final_result": final_result,
        "data_error": None,
    }


def _full_node_handle_debate_error(state: FullResearchState) -> dict:
    """辩论失败时降级为 placeholder 辩论结果."""
    partial_result = dict(state["partial_result"])

    partial_result["debate_result"] = {
        "bull_case": {"thesis": f"辩论异常：{state.get('debate_error', '未知错误')}"},
        "bear_case": {"thesis": "辩论异常"},
        "risk_review": {"risk_level": "high", "blocking": True, "risk_summary": "辩论异常"},
        "committee_conclusion": {
            "stance": "回避", "action": partial_result.get("action", "回避"),
            "confidence": 0.0,
            "final_opinion": f"辩论流程异常：{state.get('debate_error', '未知错误')}",
        },
        "debate_history": state.get("debate_history", []),
    }

    final_result = apply_decision_guard(partial_result)
    return {
        "final_result": final_result,
        "debate_error": None,
    }


# ── 全图路由函数 ───────────────────────────────────────────────

def _full_route_after_load(state: FullResearchState) -> str:
    if state.get("data_error"):
        return "handle_data_error"
    return "score_asset"


def _full_route_after_debate(state: FullResearchState) -> str:
    if state.get("debate_error"):
        return "handle_debate_error"
    return "hitl_review"


# ── 全图构建 ───────────────────────────────────────────────────

def build_full_research_graph() -> CompiledStateGraph:
    """构建完整端到端研究 pipeline 图。

    节点链：
      START → load_research_data → score_asset → run_debate_subgraph
            → hitl_review → apply_decision_guard → validate_and_assemble → END

    错误路径：
      load_research_data 失败 → handle_data_error → validate_and_assemble → END
      run_debate_subgraph 失败 → handle_debate_error → validate_and_assemble → END
    """
    builder = StateGraph(FullResearchState)

    builder.add_node("load_research_data", _full_node_load_research_data)
    builder.add_node("score_asset", _full_node_score_asset)
    builder.add_node("run_debate_subgraph", _full_node_run_debate_subgraph)
    builder.add_node("hitl_review", _full_node_hitl_review)
    builder.add_node("apply_decision_guard", _full_node_apply_decision_guard)
    builder.add_node("validate_and_assemble", _full_node_validate_and_assemble)
    builder.add_node("handle_data_error", _full_node_handle_data_error)
    builder.add_node("handle_debate_error", _full_node_handle_debate_error)

    builder.add_edge(START, "load_research_data")

    builder.add_conditional_edges(
        "load_research_data",
        _full_route_after_load,
        {
            "score_asset": "score_asset",
            "handle_data_error": "handle_data_error",
        },
    )

    builder.add_edge("score_asset", "run_debate_subgraph")

    builder.add_conditional_edges(
        "run_debate_subgraph",
        _full_route_after_debate,
        {
            "hitl_review": "hitl_review",
            "handle_debate_error": "handle_debate_error",
        },
    )

    builder.add_edge("hitl_review", "apply_decision_guard")
    builder.add_edge("apply_decision_guard", "validate_and_assemble")
    builder.add_edge("validate_and_assemble", END)

    builder.add_edge("handle_data_error", "validate_and_assemble")
    builder.add_edge("handle_debate_error", "validate_and_assemble")

    return builder.compile(checkpointer=_FULL_RESEARCH_CHECKPOINTER)


# ── 全图公开 API ───────────────────────────────────────────────

def run_full_research_graph(
    symbol: str,
    *,
    data_source: str = "mock",
    use_llm: bool = True,
    max_debate_rounds: int = 3,
    thread_id: str | None = None,
) -> dict:
    """端到端运行完整研究 pipeline 图（无中断模式）。

    Args:
        symbol: 股票/ETF 代码。
        data_source: 数据源（qmt/akshare/mock）。
        use_llm: 是否启用 LLM 辩论。
        max_debate_rounds: 最大辩论轮次。
        thread_id: 检查点线程标识。

    Returns:
        完整的 final_result dict（与 run_single_asset_research 同构）。
    """
    graph = build_full_research_graph()

    initial_state: FullResearchState = {
        "symbol": symbol,
        "data_source": data_source,
        "max_debate_rounds": max_debate_rounds,
        "use_llm": use_llm,
        "asset_data": None,
        "data_error": None,
        "score_result": None,
        "partial_result": None,
        "research_result": None,
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "debate_history": [],
        "current_round": 0,
        "supervisor_decision": None,
        "debate_error": None,
        "final_result": None,
        "error": None,
    }

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id or f"full-{symbol}",
            "human_in_the_loop": False,
        }
    }

    final_state = graph.invoke(initial_state, config)
    return final_state["final_result"]


def run_full_research_graph_hitl(
    symbol: str,
    *,
    data_source: str = "mock",
    use_llm: bool = True,
    max_debate_rounds: int = 3,
    thread_id: str | None = None,
) -> dict:
    """端到端运行完整研究 pipeline 图到 HITL 中断点。

    在 run_debate_subgraph 完成后、apply_decision_guard 前暂停。

    Returns:
        {
            "partial_result": dict,
            "hitl_state": dict,
            "thread_id": str,
        }
    """
    graph = build_full_research_graph()

    initial_state: FullResearchState = {
        "symbol": symbol,
        "data_source": data_source,
        "max_debate_rounds": max_debate_rounds,
        "use_llm": use_llm,
        "asset_data": None,
        "data_error": None,
        "score_result": None,
        "partial_result": None,
        "research_result": None,
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "debate_history": [],
        "current_round": 0,
        "supervisor_decision": None,
        "debate_error": None,
        "final_result": None,
        "error": None,
    }

    tid = thread_id or f"full-hitl-{symbol}"
    config: RunnableConfig = {
        "configurable": {
            "thread_id": tid,
            "human_in_the_loop": True,
        }
    }

    hitl_state = graph.invoke(initial_state, config)

    if "__interrupt__" not in hitl_state:
        raise RuntimeError(
            "HITL 中断未触发，流程可能已完成（这可能表示配置有误）。"
        )

    return {
        "partial_result": hitl_state.get("partial_result", {}),
        "hitl_state": hitl_state,
        "thread_id": tid,
    }


def resume_full_research_graph(
    thread_id: str,
    modified_state: dict | None = None,
) -> dict:
    """从全图 HITL 中断恢复，完成剩余节点。

    Args:
        thread_id: 与 run_full_research_graph_hitl 相同的 thread_id。
        modified_state: 可选的人工修改内容。

    Returns:
        完整的 final_result dict。
    """
    graph = build_full_research_graph()

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "human_in_the_loop": True,
        }
    }

    resume_value = modified_state or {"approved": True}
    final_state = graph.invoke(Command(resume=resume_value), config)
    return final_state["final_result"]
