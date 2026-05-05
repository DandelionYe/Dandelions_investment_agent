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

_shared_checkpointer = MemorySaver()

from services.agents.bull_analyst import BullAnalyst
from services.agents.bear_analyst import BearAnalyst
from services.agents.risk_officer import RiskOfficer
from services.agents.committee_secretary import CommitteeSecretary
from services.agents.supervisor import Supervisor
from services.protocols.validation import validate_protocol


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
        interrupt(review_package)

    secretary = CommitteeSecretary()
    conclusion = secretary.converge(
        research_result=state["research_result"],
        bull_case=state["bull_case"],
        bear_case=state["bear_case"],
        risk_review=state["risk_review"],
        debate_history=state.get("debate_history"),
    )

    return {"committee_conclusion": conclusion}


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

    return builder.compile(checkpointer=_shared_checkpointer)


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
