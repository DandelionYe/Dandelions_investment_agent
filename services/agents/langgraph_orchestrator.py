"""
LangGraph 投委会辩论编排器。

构建有状态工作流：

    START
      │
      ▼
  bull_analysis (多头独立分析)
      │
      ▼
  bear_analysis (空头独立分析)
      │
      ▼
  risk_review   (风险官独立评估)
      │
      ▼
  committee_convergence (投委会秘书收敛)
      │  ▲
      │  │  [HITL] interrupt() — 人工审核后可修改
      │  ▼
  assemble_result (组装最终 debate_result)
      │
      ▼
     END

每个节点是独立 Agent，可单独调用。在 committee_convergence 节点
支持 human-in-the-loop（HITL）中断，允许人工审核辩论结果后再继续。
"""

from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig

# 模块级 MemorySaver，确保 HITL 中断/恢复之间共享检查点数据。
_shared_checkpointer = MemorySaver()

from services.agents.bull_analyst import BullAnalyst
from services.agents.bear_analyst import BearAnalyst
from services.agents.risk_officer import RiskOfficer
from services.agents.committee_secretary import CommitteeSecretary
from services.protocols.validation import validate_protocol


# ── 状态定义 ──────────────────────────────────────────────────────

class DebateState(TypedDict):
    """LangGraph 辩论工作流状态。

    所有字段通过节点返回值做部分更新（partial state update）。
    """
    research_result: dict
    bull_case: dict | None
    bear_case: dict | None
    risk_review: dict | None
    committee_conclusion: dict | None
    debate_result: dict | None
    error: str | None


# ── 节点函数 ──────────────────────────────────────────────────────

def _node_bull_analysis(state: DebateState) -> dict:
    """多头分析师节点：独立评估看多逻辑。"""
    analyst = BullAnalyst()
    bull_case = analyst.analyze(state["research_result"])
    return {"bull_case": bull_case}


def _node_bear_analysis(state: DebateState) -> dict:
    """空头分析师节点：独立评估看空逻辑。"""
    analyst = BearAnalyst()
    bear_case = analyst.analyze(state["research_result"])
    return {"bear_case": bear_case}


def _node_risk_review(state: DebateState) -> dict:
    """风险官节点：独立评估风险等级。"""
    officer = RiskOfficer()
    risk_review = officer.review(state["research_result"])
    return {"risk_review": risk_review}


def _node_committee_convergence(
    state: DebateState, config: RunnableConfig
) -> dict:
    """投委会秘书节点：整合三方意见形成最终结论。

    支持 human-in-the-loop：当 config.configurable.human_in_the_loop 为 True 时，
    在三方分析完成后暂停，允许人工审核 bull_case/bear_case/risk_review，
    必要时可修改 state 后再继续。
    """
    hitl = config.get("configurable", {}).get("human_in_the_loop", False)

    if hitl:
        review_package = {
            "message": (
                "三方独立分析已完成。请审核以下内容：\n"
                "  - bull_case: 多头核心观点\n"
                "  - bear_case: 空头核心观点\n"
                "  - risk_review: 风险官评估\n\n"
                "如需修改，请通过 Command(resume=modified_state) 传入调整后的状态。\n"
                "直接恢复则按原样继续收敛。"
            ),
            "bull_case": state.get("bull_case"),
            "bear_case": state.get("bear_case"),
            "risk_review": state.get("risk_review"),
            "research_summary": {
                "symbol": state["research_result"].get("symbol"),
                "name": state["research_result"].get("name"),
                "score": state["research_result"].get("score"),
                "rating": state["research_result"].get("rating"),
            },
        }
        interrupt(review_package)

    secretary = CommitteeSecretary()
    conclusion = secretary.converge(
        research_result=state["research_result"],
        bull_case=state["bull_case"],
        bear_case=state["bear_case"],
        risk_review=state["risk_review"],
    )

    return {"committee_conclusion": conclusion}


def _node_assemble_result(state: DebateState) -> dict:
    """组装最终 debate_result 并通过协议验证。"""
    debate_result = {
        "bull_case": state["bull_case"],
        "bear_case": state["bear_case"],
        "risk_review": state["risk_review"],
        "committee_conclusion": state["committee_conclusion"],
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
        }
    }


def _should_route_to_error(state: DebateState) -> str:
    """条件边：有错误则跳到错误处理。"""
    if state.get("error"):
        return "error_handler"
    return "committee_convergence"


# ── 图构建 ────────────────────────────────────────────────────────

def build_debate_graph() -> CompiledStateGraph:
    """构建并编译 LangGraph 辩论工作流。

    Returns:
        编译后的 CompiledStateGraph，已挂载 MemorySaver 做检查点。
        支持 .invoke() 和 .stream() 两种执行模式。
    """

    builder = StateGraph(DebateState)

    # 注册节点
    builder.add_node("bull_analysis", _node_bull_analysis)
    builder.add_node("bear_analysis", _node_bear_analysis)
    builder.add_node("risk_review", _node_risk_review)
    builder.add_node("committee_convergence", _node_committee_convergence)
    builder.add_node("assemble_result", _node_assemble_result)
    builder.add_node("error_handler", _node_error_handler)

    # 连线：顺序执行
    # 三者无依赖关系，后续可改为并行：
    #   START → bull_analysis ──┐
    #   START → bear_analysis ──┼──→ committee_convergence → assemble_result → END
    #   START → risk_review ────┘
    builder.add_edge(START, "bull_analysis")
    builder.add_edge("bull_analysis", "bear_analysis")
    builder.add_edge("bear_analysis", "risk_review")

    # 条件边：有错误则跳转错误处理，否则进入收敛节点
    builder.add_conditional_edges(
        "risk_review",
        _should_route_to_error,
        {
            "committee_convergence": "committee_convergence",
            "error_handler": "error_handler",
        },
    )

    builder.add_edge("committee_convergence", "assemble_result")
    builder.add_edge("assemble_result", END)
    builder.add_edge("error_handler", END)

    return builder.compile(checkpointer=_shared_checkpointer)


# ── 公开 API ──────────────────────────────────────────────────────

def generate_debate_result_langgraph(
    research_result: dict,
    *,
    thread_id: str | None = None,
) -> dict:
    """使用 LangGraph 编排完整的投委会辩论流程（无中断模式）。

    顺序执行 bull → bear → risk → committee → assemble 五步，
    不启用 human-in-the-loop。

    Args:
        research_result: 单票研究结果（来自 single_asset_research 的输出）。
        thread_id: 检查点线程标识。默认自动生成。

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
    }

    config = {
        "configurable": {
            "thread_id": thread_id
            or f"debate-{research_result.get('symbol', 'unknown')}",
            "human_in_the_loop": False,
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
) -> dict:
    """启动带 human-in-the-loop 中断的辩论流程。

    在 committee_convergence 节点暂停，返回包含三方分析结果的
    中间状态，供人工审核。审核后调用 resume_hitl_debate() 继续。

    Args:
        research_result: 单票研究结果。
        thread_id: 检查点线程标识。

    Returns:
        中断时的 DebateState，包含 bull_case、bear_case、risk_review
        和 __interrupt__ 信息。
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
    }

    config = {
        "configurable": {
            "thread_id": thread_id
            or f"debate-hitl-{research_result.get('symbol', 'unknown')}",
            "human_in_the_loop": True,
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
        modified_state: 可选的修改内容。例如传入
            {"committee_conclusion": {"stance": "回避", "action": "回避"}}
            来覆盖秘书的结论。

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
