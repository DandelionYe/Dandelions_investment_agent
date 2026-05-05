"""
LangGraph 多轮辩论编排器测试。

覆盖：图结构验证、节点函数隔离测试、完整图执行（mock DeepSeek）、
HITL 中断/恢复、错误处理路径、向后兼容性。
"""

import pytest

from services.agents.langgraph_orchestrator import (
    DebateState,
    build_debate_graph,
    generate_debate_result_langgraph,
    start_hitl_debate,
    resume_hitl_debate,
    _node_run_initial_round,
    _node_bull_challenge,
    _node_bear_challenge,
    _node_risk_challenge,
    _node_supervisor_judge,
    _node_committee_convergence,
    _node_assemble_result,
    _node_error_handler,
    _route_after_initial,
    _route_after_supervisor,
)


# ── 测试数据 ──────────────────────────────────────────────────────

def _research_result(**overrides):
    data = {
        "symbol": "600519.SH",
        "name": "贵州茅台",
        "asset_type": "stock",
        "as_of": "2026-05-04",
        "data_source": "mock",
        "score": 72,
        "rating": "B",
        "action": "观察",
        "max_position": "5%-8%",
        "final_opinion": "谨慎看多。",
        "score_breakdown": {
            "trend_momentum": 16,
            "liquidity": 13,
            "fundamental_quality": 16,
            "valuation": 10,
            "risk_control": 15,
            "event_policy": 2,
        },
        "price_data": {
            "close": 1688.0,
            "change_20d": 0.052,
            "change_60d": 0.083,
            "ma20_position": "above",
            "ma60_position": "above",
            "max_drawdown_60d": -0.092,
            "volatility_60d": 0.186,
            "avg_turnover_20d": 4800000000,
            "data_vendor": "eastmoney",
        },
        "data_quality": {"has_placeholder": False, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "evidence_bundle": {"items": []},
        "fundamental_data": {},
        "valuation_data": {},
        "etf_data": {},
    }
    data.update(overrides)
    return data


def _mock_bull_output():
    return {
        "thesis": "多头核心观点：趋势改善。",
        "key_arguments": ["MA支撑有效", "成交量放大"],
        "catalysts": ["一季报可能超预期"],
        "invalidation_conditions": ["跌破MA60"],
    }


def _mock_bear_output():
    return {
        "thesis": "空头核心观点：估值偏高。",
        "key_arguments": ["PE分位不低", "上行动能不足"],
        "main_concerns": ["估值扩张空间有限"],
        "invalidation_conditions": ["PE回落至50%分位以下"],
    }


def _mock_risk_output():
    return {
        "risk_level": "medium",
        "blocking": False,
        "risk_summary": "整体风险中等。",
        "max_position": "5%-8%",
        "risk_triggers": ["跌破MA60"],
    }


def _mock_committee_output():
    return {
        "stance": "谨慎看多",
        "action": "观察",
        "confidence": 0.72,
        "final_opinion": "综合三方意见，建议观察。",
    }


def _mock_supervisor_converged():
    return {
        "is_converged": True,
        "convergence_reason": "all_agree",
        "next_speaker": None,
        "challenge": None,
        "round_summary": "三方观点趋于一致，辩论充分。",
    }


def _mock_supervisor_challenge_bear():
    return {
        "is_converged": False,
        "convergence_reason": None,
        "next_speaker": "bear",
        "challenge": "多头声称趋势改善，请空头具体回应估值偏高的论据在当前PE分位下是否仍然成立。",
        "round_summary": "多空在估值上存在分歧。",
    }


def _full_state(research_result=None):
    """创建含多轮辩论字段的完整初始状态。"""
    return {
        "research_result": research_result or _research_result(),
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "error": None,
        "debate_history": [],
        "current_round": 0,
        "max_rounds": 3,
        "supervisor_decision": None,
    }


def _state_after_initial():
    """模拟初始轮完成后的状态。"""
    rr = _research_result()
    return {
        "research_result": rr,
        "bull_case": _mock_bull_output(),
        "bear_case": _mock_bear_output(),
        "risk_review": _mock_risk_output(),
        "committee_conclusion": None,
        "debate_result": None,
        "error": None,
        "debate_history": [
            {
                "round": 0,
                "type": "initial",
                "speaker": "all",
                "outputs": {
                    "bull_case": _mock_bull_output(),
                    "bear_case": _mock_bear_output(),
                    "risk_review": _mock_risk_output(),
                },
            }
        ],
        "current_round": 0,
        "max_rounds": 3,
        "supervisor_decision": None,
    }


# ── 图结构测试 ────────────────────────────────────────────────────

def test_graph_has_all_required_nodes():
    graph = build_debate_graph()
    nodes = list(graph.nodes.keys())
    assert "run_initial_round" in nodes
    assert "supervisor_judge" in nodes
    assert "bull_challenge" in nodes
    assert "bear_challenge" in nodes
    assert "risk_challenge" in nodes
    assert "committee_convergence" in nodes
    assert "assemble_result" in nodes
    assert "error_handler" in nodes


def test_graph_has_start_node():
    graph = build_debate_graph()
    assert "__start__" in graph.nodes


def test_graph_can_be_rebuilt():
    g1 = build_debate_graph()
    g2 = build_debate_graph()
    assert g1 is not g2
    assert list(g1.nodes.keys()) == list(g2.nodes.keys())


# ── 路由函数测试 ──────────────────────────────────────────────────

def test_route_after_initial_error():
    state = _full_state()
    state["error"] = "并行分析失败"
    assert _route_after_initial(state) == "error_handler"


def test_route_after_initial_success():
    state = _full_state()
    assert _route_after_initial(state) == "supervisor_judge"


def test_route_after_supervisor_error():
    state = _state_after_initial()
    state["error"] = "Supervisor 调用失败"
    assert _route_after_supervisor(state) == "error_handler"


def test_route_after_supervisor_converged():
    state = _state_after_initial()
    state["supervisor_decision"] = _mock_supervisor_converged()
    assert _route_after_supervisor(state) == "committee_convergence"


def test_route_after_supervisor_bull():
    state = _state_after_initial()
    state["supervisor_decision"] = {
        "is_converged": False,
        "next_speaker": "bull",
        "challenge": "请回应。",
    }
    assert _route_after_supervisor(state) == "bull_challenge"


def test_route_after_supervisor_bear():
    state = _state_after_initial()
    state["supervisor_decision"] = {
        "is_converged": False,
        "next_speaker": "bear",
        "challenge": "请回应。",
    }
    assert _route_after_supervisor(state) == "bear_challenge"


def test_route_after_supervisor_risk():
    state = _state_after_initial()
    state["supervisor_decision"] = {
        "is_converged": False,
        "next_speaker": "risk",
        "challenge": "请回应。",
    }
    assert _route_after_supervisor(state) == "risk_challenge"


def test_route_after_supervisor_invalid_speaker():
    state = _state_after_initial()
    state["supervisor_decision"] = {
        "is_converged": False,
        "next_speaker": "invalid",
        "challenge": "",
    }
    assert _route_after_supervisor(state) == "committee_convergence"


# ── 节点函数隔离测试 ────────────────────────────────────────────

def test_initial_round_produces_all_outputs(monkeypatch):
    call_count = [0]

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        call_count[0] += 1
        if call_count[0] == 1:
            return _mock_bull_output()
        elif call_count[0] == 2:
            return _mock_bear_output()
        else:
            return _mock_risk_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _full_state()
    result = _node_run_initial_round(state)

    assert result["bull_case"]["thesis"] == "多头核心观点：趋势改善。"
    assert result["bear_case"]["thesis"] == "空头核心观点：估值偏高。"
    assert result["risk_review"]["risk_level"] == "medium"
    assert len(result["debate_history"]) == 1
    assert result["debate_history"][0]["type"] == "initial"
    assert result["current_round"] == 0
    assert call_count[0] == 3


def test_bull_challenge_produces_valid_output(monkeypatch):
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        return _mock_bull_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _state_after_initial()
    state["supervisor_decision"] = _mock_supervisor_challenge_bear()
    result = _node_bull_challenge(state)

    assert result["bull_case"]["thesis"] == "多头核心观点：趋势改善。"
    assert len(result["debate_history"]) > len(state["debate_history"])


def test_bear_challenge_produces_valid_output(monkeypatch):
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        return _mock_bear_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _state_after_initial()
    state["supervisor_decision"] = _mock_supervisor_challenge_bear()
    result = _node_bear_challenge(state)

    assert result["bear_case"]["thesis"] == "空头核心观点：估值偏高。"
    assert len(result["debate_history"]) > len(state["debate_history"])


def test_risk_challenge_produces_valid_output(monkeypatch):
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        return _mock_risk_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _state_after_initial()
    state["supervisor_decision"] = {
        "is_converged": False,
        "next_speaker": "risk",
        "challenge": "请重新评估风险。",
    }
    result = _node_risk_challenge(state)

    assert result["risk_review"]["risk_level"] == "medium"
    assert len(result["debate_history"]) > len(state["debate_history"])


def test_supervisor_judge_max_rounds_forced_converge(monkeypatch):
    """current_round >= max_rounds 时直接强制收敛，不调 LLM。"""
    state = _state_after_initial()
    state["current_round"] = 3

    from langchain_core.runnables import RunnableConfig
    config = RunnableConfig(
        configurable={"thread_id": "test", "max_rounds": 3}
    )

    result = _node_supervisor_judge(state, config)

    assert result["supervisor_decision"]["is_converged"] is True
    assert result["supervisor_decision"]["convergence_reason"] == "max_rounds_reached"
    assert result["current_round"] == 4


def test_supervisor_judge_calls_llm(monkeypatch):
    """正常轮次时调用 Supervisor LLM。"""
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        return _mock_supervisor_converged()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _state_after_initial()
    from langchain_core.runnables import RunnableConfig
    config = RunnableConfig(
        configurable={"thread_id": "test", "max_rounds": 3}
    )

    result = _node_supervisor_judge(state, config)

    assert result["supervisor_decision"]["is_converged"] is True
    assert result["current_round"] == 1
    assert len(result["debate_history"]) == 2


def test_committee_node_produces_valid_output(monkeypatch):
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    state = _state_after_initial()
    state["debate_history"] = [
        {
            "round": 0,
            "type": "initial",
            "speaker": "all",
            "outputs": {
                "bull_case": _mock_bull_output(),
                "bear_case": _mock_bear_output(),
                "risk_review": _mock_risk_output(),
            },
        },
    ]

    from langchain_core.runnables import RunnableConfig
    config = RunnableConfig(
        configurable={"thread_id": "test", "human_in_the_loop": False}
    )

    result = _node_committee_convergence(state, config)

    assert result["committee_conclusion"]["stance"] == "谨慎看多"
    assert result["committee_conclusion"]["action"] == "观察"


def test_assemble_node_creates_valid_debate_result():
    state = _state_after_initial()
    state["committee_conclusion"] = _mock_committee_output()

    result = _node_assemble_result(state)

    dr = result["debate_result"]
    assert dr["bull_case"]["thesis"] is not None
    assert dr["bear_case"]["thesis"] is not None
    assert dr["risk_review"]["risk_level"] == "medium"
    assert dr["committee_conclusion"]["action"] == "观察"
    assert "debate_history" in dr


def test_error_handler_produces_safe_debate_result():
    state = _full_state()
    state["error"] = "DeepSeek API 超时"

    result = _node_error_handler(state)

    assert result["debate_result"]["committee_conclusion"]["action"] == "回避"
    assert result["debate_result"]["committee_conclusion"]["confidence"] == 0.0
    assert result["debate_result"]["risk_review"]["blocking"] is True


# ── 完整图执行测试（mock DeepSeek） ───────────────────────────────

def test_full_graph_execution_without_hitl(monkeypatch):
    """端到端执行——mock 监督在第一轮后收敛（7次 LLM 调用）。"""
    call_count = [0]

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        call_count[0] += 1
        if call_count[0] <= 3:
            # 初始并行：bull, bear, risk
            if call_count[0] == 1:
                return _mock_bull_output()
            elif call_count[0] == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif call_count[0] == 4:
            # supervisor 第1轮 → 提出质询
            return _mock_supervisor_challenge_bear()
        elif call_count[0] == 5:
            # bear 回应质询
            return _mock_bear_output()
        elif call_count[0] == 6:
            # supervisor 第2轮 → 判定收敛
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    result = generate_debate_result_langgraph(
        _research_result(),
        thread_id="test-full",
        max_rounds=2,
    )

    assert result["bull_case"]["thesis"] == "多头核心观点：趋势改善。"
    assert result["bear_case"]["thesis"] == "空头核心观点：估值偏高。"
    assert result["risk_review"]["risk_level"] == "medium"
    assert result["committee_conclusion"]["action"] == "观察"
    assert "debate_history" in result
    assert call_count[0] == 7  # 3 initial + 1 sup + 1 bear + 1 sup + 1 cmt


def test_full_graph_execution_returns_valid_protocol(monkeypatch):
    call_count = [0]

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        call_count[0] += 1
        if call_count[0] <= 3:
            if call_count[0] == 1:
                return _mock_bull_output()
            elif call_count[0] == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif call_count[0] == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    result = generate_debate_result_langgraph(
        _research_result(),
        thread_id="test-protocol",
    )

    assert set(result.keys()) >= {
        "bull_case", "bear_case", "risk_review", "committee_conclusion",
    }
    assert result["committee_conclusion"]["confidence"] <= 1.0


# ── HITL 中断和恢复测试 ─────────────────────────────────────────

def test_hitl_interrupt_returns_interrupt_key(monkeypatch):
    """human_in_the_loop=True 时 invoke 返回含 __interrupt__ 的中间状态。"""
    api_calls = []

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        api_calls.append("api")
        n = len(api_calls)
        if n <= 3:
            if n == 1:
                return _mock_bull_output()
            elif n == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif n == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    result = start_hitl_debate(
        _research_result(), thread_id="test-hitl", max_rounds=1
    )

    assert "__interrupt__" in result
    assert result["bull_case"]["thesis"] is not None
    assert result["bear_case"]["thesis"] is not None
    assert result["risk_review"]["risk_level"] is not None


def test_hitl_resume_after_interrupt_completes(monkeypatch):
    api_calls = []

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        api_calls.append("api")
        n = len(api_calls)
        if n <= 3:
            if n == 1:
                return _mock_bull_output()
            elif n == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif n == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    interrupted = start_hitl_debate(
        _research_result(), thread_id="test-hitl-resume", max_rounds=1
    )
    assert "__interrupt__" in interrupted

    final_result = resume_hitl_debate(thread_id="test-hitl-resume")

    assert final_result["committee_conclusion"]["action"] == "观察"
    assert final_result["bull_case"]["thesis"] is not None
    assert "debate_history" in final_result


def test_hitl_can_modify_state_before_resume(monkeypatch):
    api_calls = []

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        api_calls.append("api")
        n = len(api_calls)
        if n <= 3:
            if n == 1:
                return _mock_bull_output()
            elif n == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif n == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    interrupted = start_hitl_debate(
        _research_result(), thread_id="test-hitl-modify", max_rounds=1
    )
    assert "__interrupt__" in interrupted

    final_result = resume_hitl_debate(
        thread_id="test-hitl-modify",
        modified_state={
            "committee_conclusion": {
                "stance": "回避",
                "action": "回避",
                "confidence": 0.1,
                "final_opinion": "人工审核后否决：证据不足。",
            }
        },
    )

    assert "committee_conclusion" in final_result


# ── 错误处理路径测试 ──────────────────────────────────────────────

def test_error_routes_to_error_handler(monkeypatch):
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        raise RuntimeError("API 不可用")

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    graph = build_debate_graph()

    initial_state = {
        "research_result": _research_result(),
        "bull_case": None,
        "bear_case": None,
        "risk_review": None,
        "committee_conclusion": None,
        "debate_result": None,
        "error": "DeepSeek API key 缺失",
        "debate_history": [],
        "current_round": 0,
        "max_rounds": 3,
        "supervisor_decision": None,
    }

    config = {"configurable": {"thread_id": "test-error"}}

    final_state = graph.invoke(initial_state, config)

    assert final_state["debate_result"]["committee_conclusion"]["action"] == "回避"
    assert final_state["debate_result"]["committee_conclusion"]["confidence"] == 0.0


# ── 向后兼容性测试 ────────────────────────────────────────────────

def test_generate_debate_result_same_interface(monkeypatch):
    from services.agents.debate_agent import generate_debate_result

    call_count = [0]

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        call_count[0] += 1
        if call_count[0] <= 3:
            if call_count[0] == 1:
                return _mock_bull_output()
            elif call_count[0] == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif call_count[0] == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    result = generate_debate_result(_research_result())

    assert "bull_case" in result
    assert "bear_case" in result
    assert "risk_review" in result
    assert "committee_conclusion" in result


def test_single_asset_research_still_works(monkeypatch):
    from services.orchestrator.single_asset_research import run_single_asset_research

    result = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="mock",
    )

    assert result["symbol"] == "600519.SH"
    assert 0 <= result["score"] <= 100
    assert result["decision_guard"]["enabled"] is True


# ── 多个 thread_id 隔离测试 ───────────────────────────────────────

def test_different_thread_ids_isolated(monkeypatch):
    call_count = [0]

    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        call_count[0] += 1
        if call_count[0] <= 3:
            if call_count[0] == 1:
                return _mock_bull_output()
            elif call_count[0] == 2:
                return _mock_bear_output()
            else:
                return _mock_risk_output()
        elif call_count[0] == 4:
            return _mock_supervisor_converged()
        else:
            return _mock_committee_output()

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    r1 = generate_debate_result_langgraph(
        _research_result(symbol="600519.SH"),
        thread_id="thread-1",
    )

    call_count[0] = 0

    r2 = generate_debate_result_langgraph(
        _research_result(symbol="000001.SZ"),
        thread_id="thread-2",
    )

    assert r1["committee_conclusion"] is not None
    assert r2["committee_conclusion"] is not None
