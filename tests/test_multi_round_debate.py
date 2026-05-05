"""
多轮辩论测试。

覆盖：Supervisor 单元测试、完整多轮图执行、收敛终止、
debate_history 累积、协议兼容性、向后兼容、HITL 保持、错误路径。
"""

import pytest

from services.agents.supervisor import Supervisor
from services.agents.bull_analyst import BullAnalyst
from services.agents.bear_analyst import BearAnalyst
from services.agents.risk_officer import RiskOfficer
from services.agents.committee_secretary import CommitteeSecretary
from services.agents.langgraph_orchestrator import (
    generate_debate_result_langgraph,
    start_hitl_debate,
    resume_hitl_debate,
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


# ── Supervisor 单元测试 ──────────────────────────────────────────

class TestSupervisor:
    def test_supervisor_produces_valid_schema(self, monkeypatch):
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return {
                "is_converged": False,
                "convergence_reason": None,
                "next_speaker": "bear",
                "challenge": "请回应估值问题。",
                "round_summary": "存在分歧。",
            }

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        s = Supervisor()
        result = s.evaluate(
            research_result=_research_result(),
            bull_case=_mock_bull_output(),
            bear_case=_mock_bear_output(),
            risk_review=_mock_risk_output(),
            debate_history=[],
            current_round=1,
            max_rounds=3,
        )

        assert "is_converged" in result
        assert "convergence_reason" in result
        assert "next_speaker" in result
        assert "challenge" in result
        assert "round_summary" in result

    def test_supervisor_detects_convergence_all_agree(self, monkeypatch):
        """三方立场一致时应判定收敛。"""
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return {
                "is_converged": True,
                "convergence_reason": "all_agree",
                "next_speaker": None,
                "challenge": None,
                "round_summary": "三方均持谨慎态度，观点一致。",
            }

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        s = Supervisor()
        result = s.evaluate(
            research_result=_research_result(),
            bull_case={"thesis": "谨慎看多"},
            bear_case={"thesis": "中性偏谨慎"},
            risk_review={"risk_summary": "风险可控"},
            debate_history=[],
            current_round=1,
            max_rounds=3,
        )

        assert result["is_converged"] is True
        assert result["convergence_reason"] == "all_agree"
        assert result["next_speaker"] is None

    def test_supervisor_formats_challenge(self, monkeypatch):
        """质询应包含具体指向。"""
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return {
                "is_converged": False,
                "convergence_reason": None,
                "next_speaker": "bear",
                "challenge": "Bull 声称趋势改善，但估值处于85分位，请空头具体回应。",
                "round_summary": "多空在估值上存在明显分歧。",
            }

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        s = Supervisor()
        result = s.evaluate(
            research_result=_research_result(),
            bull_case=_mock_bull_output(),
            bear_case=_mock_bear_output(),
            risk_review=_mock_risk_output(),
            debate_history=[],
            current_round=1,
            max_rounds=3,
        )

        assert result["next_speaker"] == "bear"
        assert len(result["challenge"]) > 10

    def test_supervisor_handles_empty_history(self, monkeypatch):
        """空辩论历史时仍能正常输出。"""
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return {
                "is_converged": False,
                "convergence_reason": None,
                "next_speaker": "bull",
                "challenge": "请详细阐述趋势改善的具体证据。",
                "round_summary": "需要更多多头证据。",
            }

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        s = Supervisor()
        result = s.evaluate(
            research_result=_research_result(),
            bull_case=_mock_bull_output(),
            bear_case=_mock_bear_output(),
            risk_review=_mock_risk_output(),
            debate_history=[],
            current_round=0,
            max_rounds=3,
        )

        assert result["is_converged"] is False
        assert result["next_speaker"] is not None


# ── 向后兼容性测试 ───────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_agent_analyze_without_challenge(self, monkeypatch):
        """不传 challenge/debate_history 时行为与原来一致。"""
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return _mock_bull_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        analyst = BullAnalyst()
        result = analyst.analyze(_research_result())

        assert result["thesis"] == "多头核心观点：趋势改善。"
        assert "key_arguments" in result
        assert "catalysts" in result
        assert "invalidation_conditions" in result

    def test_committee_converge_without_history(self, monkeypatch):
        """不传 debate_history 时行为与原来一致。"""
        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        sec = CommitteeSecretary()
        result = sec.converge(
            research_result=_research_result(),
            bull_case=_mock_bull_output(),
            bear_case=_mock_bear_output(),
            risk_review=_mock_risk_output(),
        )

        assert result["stance"] == "谨慎看多"
        assert result["action"] == "观察"

    def test_generate_debate_result_unchanged_interface(self, monkeypatch):
        """debate_agent.generate_debate_result() 接口不变。"""
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
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "已收敛。",
                }
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


# ── 完整图端到端测试 ─────────────────────────────────────────────

class TestEndToEnd:
    def test_full_debate_converges_in_one_round(self, monkeypatch):
        """Supervisor 第一轮即判定收敛 → 5次 LLM 调用（3 initial + 1 sup + 1 cmt）。"""
        call_count = [0]

        def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_bull_output()
            elif call_count[0] == 2:
                return _mock_bear_output()
            elif call_count[0] == 3:
                return _mock_risk_output()
            elif call_count[0] == 4:
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "三方均谨慎，观点一致。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        result = generate_debate_result_langgraph(
            _research_result(), thread_id="test-e2e-1r"
        )

        assert "committee_conclusion" in result
        assert "debate_history" in result
        # debate_history: [initial, supervisor_judgment]
        assert len(result["debate_history"]) >= 2
        assert call_count[0] == 5

    def test_full_debate_converges_after_challenge(self, monkeypatch):
        """Supervisor 提出质询，Agent 回应后再收敛 → 7次调用。"""
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
                return {
                    "is_converged": False,
                    "next_speaker": "bear",
                    "challenge": "请空头回应估值问题。",
                    "round_summary": "估值存在分歧。",
                }
            elif call_count[0] == 5:
                return _mock_bear_output()
            elif call_count[0] == 6:
                return {
                    "is_converged": True,
                    "convergence_reason": "no_new_arguments",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "回应无新论据，辩论充分。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        result = generate_debate_result_langgraph(
            _research_result(), thread_id="test-e2e-ch", max_rounds=2
        )

        assert "committee_conclusion" in result
        assert "debate_history" in result
        assert call_count[0] == 7

    def test_full_debate_max_rounds_termination(self, monkeypatch):
        """Supervisor 永不收敛，max_rounds 硬上限强制终止。"""
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
                # 第1轮 supervisor：不收敛 → 路由到 bear_challenge
                return {
                    "is_converged": False,
                    "next_speaker": "bear",
                    "challenge": "请回应。",
                    "round_summary": "存在分歧。",
                }
            elif call_count[0] == 5:
                # bear 质询回应
                return _mock_bear_output()
            else:
                # 第2轮 supervisor 因 max_rounds=1 强制收敛（不调LLM）
                # 直接到 committee → call_count 变 6，应返回 committee 输出
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        result = generate_debate_result_langgraph(
            _research_result(), thread_id="test-e2e-max", max_rounds=1
        )

        assert "committee_conclusion" in result
        assert "debate_history" in result
        # max_rounds=1 时：3 initial + 1 sup + 1 bear + 1 committee = 6 LLM 调用
        assert call_count[0] == 6

    def test_debate_history_accumulates(self, monkeypatch):
        """验证 debate_history 随每轮正确累积。"""
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
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "已收敛。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        result = generate_debate_result_langgraph(
            _research_result(), thread_id="test-history"
        )

        history = result["debate_history"]
        assert len(history) >= 2
        assert history[0]["type"] == "initial"
        assert history[0]["round"] == 0
        assert history[1]["type"] == "supervisor_judgment"

    def test_protocol_validation_passes(self, monkeypatch):
        """端到端执行后 debate_result 通过协议验证。"""
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
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "已收敛。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        result = generate_debate_result_langgraph(
            _research_result(), thread_id="test-protocol-e2e"
        )

        assert result["bull_case"]["thesis"] is not None
        assert len(result["bull_case"]["key_arguments"]) >= 1
        assert result["risk_review"]["risk_level"] in ("low", "medium", "high")
        assert isinstance(result["risk_review"]["blocking"], bool)
        assert result["committee_conclusion"]["action"] in (
            "买入", "分批买入", "持有", "观察", "回避", "回调关注", "谨慎观察",
        )
        assert 0.0 <= result["committee_conclusion"]["confidence"] <= 1.0


# ── HITL 保持测试 ─────────────────────────────────────────────────

class TestHITLIntegration:
    def test_hitl_still_interrupts_after_debate(self, monkeypatch):
        """HITL 中断仍在 committee_convergence 正确触发。"""
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
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "已收敛。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        interrupted = start_hitl_debate(
            _research_result(), thread_id="test-hitl-multi", max_rounds=1
        )

        assert "__interrupt__" in interrupted
        interrupt_data = interrupted["__interrupt__"][0]
        # LangGraph Interrupt 对象，其 value 属性包含我们传入的 review_package
        interrupt_value = interrupt_data.value
        assert "debate_history" in interrupt_value

    def test_hitl_resume_with_debate_history(self, monkeypatch):
        """恢复 HITL 后 debate_history 完整保留。"""
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
                return {
                    "is_converged": True,
                    "convergence_reason": "all_agree",
                    "next_speaker": None,
                    "challenge": None,
                    "round_summary": "已收敛。",
                }
            else:
                return _mock_committee_output()

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        interrupted = start_hitl_debate(
            _research_result(), thread_id="test-hitl-resume-hist", max_rounds=1
        )
        assert "__interrupt__" in interrupted

        final_result = resume_hitl_debate(thread_id="test-hitl-resume-hist")

        assert "debate_history" in final_result
        assert len(final_result["debate_history"]) >= 2


# ── 错误路径测试 ─────────────────────────────────────────────────

def test_initial_round_error_routes_to_error_handler(monkeypatch):
    """初始轮 Agent 调用异常 → error_handler。"""
    def mock_chat_json(self, system_prompt, user_prompt, model, max_tokens):
        raise RuntimeError("网络不可达")

    monkeypatch.setattr(
        "services.llm.deepseek_client.DeepSeekClient.chat_json",
        mock_chat_json,
    )

    # 不传 use_llm=False，会走 LangGraph 路径触发异常
    with pytest.raises(RuntimeError, match="辩论流程出错"):
        generate_debate_result_langgraph(
            _research_result(), thread_id="test-error-init"
        )
