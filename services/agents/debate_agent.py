"""
投委会辩论编排器（入口模块）。

默认使用 LangGraph 编排器构建有状态辩论工作流：
  START → bull_analysis → bear_analysis → risk_review → committee_convergence → END

每个 Agent 作为独立节点，支持 human-in-the-loop 中断。
当 langgraph 不可用时，自动回退到顺序编排。
"""

from services.agents.bull_analyst import BullAnalyst
from services.agents.bear_analyst import BearAnalyst
from services.agents.risk_officer import RiskOfficer
from services.agents.committee_secretary import CommitteeSecretary
from services.protocols.validation import validate_protocol


def generate_debate_result(research_result: dict) -> dict:
    """
    编排多 Agent 辩论流程，生成完整投委会辩论结果。

    优先使用 LangGraph 编排器；若 langgraph 未安装则回退到顺序执行。

    接口保持向后兼容，调用方无需修改。
    """
    try:
        from services.agents.langgraph_orchestrator import (
            generate_debate_result_langgraph,
        )
        return generate_debate_result_langgraph(research_result)
    except ImportError:
        return _generate_debate_result_sequential(research_result)


def _generate_debate_result_sequential(research_result: dict) -> dict:
    """顺序执行回退方案（langgraph 不可用时）。"""

    bull = BullAnalyst()
    bull_case = bull.analyze(research_result)

    bear = BearAnalyst()
    bear_case = bear.analyze(research_result)

    risk = RiskOfficer()
    risk_review = risk.review(research_result)

    secretary = CommitteeSecretary()
    committee_conclusion = secretary.converge(
        research_result=research_result,
        bull_case=bull_case,
        bear_case=bear_case,
        risk_review=risk_review,
    )

    debate_result = {
        "bull_case": bull_case,
        "bear_case": bear_case,
        "risk_review": risk_review,
        "committee_conclusion": committee_conclusion,
    }

    validate_protocol("debate_result", debate_result)
    return debate_result
