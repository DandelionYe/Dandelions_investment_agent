"""
决策保护器边界条件测试。

覆盖：评分阈值、风险等级降级、数据质量阻断、critical 事件强制回避、
placeholder 限制、缺失数据限制、clamp_action 逻辑、完整 apply_decision_guard 流程。
"""

from services.research.decision_guard import (
    ACTION_LEVEL,
    get_max_allowed_action,
    clamp_action,
    apply_data_quality_action_limits,
    apply_decision_guard,
)


# ── get_max_allowed_action 评分阈值 ──────────────────────────────

def test_score_below_55_gives_avoid():
    assert get_max_allowed_action(0, "D") == "回避"
    assert get_max_allowed_action(40, "D") == "回避"
    assert get_max_allowed_action(54, "D") == "回避"


def test_score_55_to_64_gives_cautious_watch():
    assert get_max_allowed_action(55, "C") == "谨慎观察"
    assert get_max_allowed_action(60, "C") == "谨慎观察"
    assert get_max_allowed_action(64, "C") == "谨慎观察"


def test_score_65_to_74_gives_observe():
    assert get_max_allowed_action(65, "B") == "观察"
    assert get_max_allowed_action(70, "B") == "观察"
    assert get_max_allowed_action(74, "B") == "观察"


def test_score_75_to_84_gives_accumulate():
    assert get_max_allowed_action(75, "B+") == "分批买入"
    assert get_max_allowed_action(80, "B+") == "分批买入"
    assert get_max_allowed_action(84, "B+") == "分批买入"


def test_score_85_and_above_gives_buy():
    assert get_max_allowed_action(85, "A") == "买入"
    assert get_max_allowed_action(95, "A") == "买入"
    assert get_max_allowed_action(100, "A") == "买入"


# ── 风险等级降级 ──────────────────────────────────────────────────

def test_high_risk_level_caps_to_observe_regardless_of_score():
    """风险等级为 high 时，即使分数很高也只允许观察。"""
    assert get_max_allowed_action(90, "A", risk_level="high") == "观察"
    assert get_max_allowed_action(100, "A", risk_level="high") == "观察"
    assert get_max_allowed_action(50, "D", risk_level="high") == "观察"


def test_medium_risk_below_75_caps_to_observe():
    """风险等级 medium 且分数 < 75 时，最多观察。"""
    assert get_max_allowed_action(70, "B", risk_level="medium") == "观察"
    assert get_max_allowed_action(60, "C", risk_level="medium") == "观察"
    assert get_max_allowed_action(54, "D", risk_level="medium") == "观察"


def test_medium_risk_75_and_above_no_extra_cap():
    """风险等级 medium 但分数 >= 75 时，不额外降级。"""
    assert get_max_allowed_action(75, "B+", risk_level="medium") == "分批买入"
    assert get_max_allowed_action(85, "A", risk_level="medium") == "买入"


def test_low_risk_no_cap():
    """风险等级 low 不影响最大允许操作。"""
    assert get_max_allowed_action(90, "A", risk_level="low") == "买入"
    assert get_max_allowed_action(60, "C", risk_level="low") == "谨慎观察"


# ── clamp_action 逻辑 ─────────────────────────────────────────────

def test_clamp_action_reduces_aggressive_to_allowed():
    assert clamp_action("买入", "观察") == "观察"
    assert clamp_action("买入", "回避") == "回避"
    assert clamp_action("分批买入", "谨慎观察") == "谨慎观察"
    assert clamp_action("分批买入", "观察") == "观察"


def test_clamp_action_keeps_allowed_or_lower():
    assert clamp_action("观察", "买入") == "观察"
    assert clamp_action("观察", "分批买入") == "观察"
    assert clamp_action("谨慎观察", "买入") == "谨慎观察"
    assert clamp_action("回避", "买入") == "回避"


def test_clamp_action_same_level_unchanged():
    assert clamp_action("观察", "观察") == "观察"
    assert clamp_action("买入", "买入") == "买入"


# ── apply_data_quality_action_limits ──────────────────────────────

def _stock_result(**overrides):
    base = {
        "data_quality": {"has_placeholder": False, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "asset_type": "stock",
        "valuation_data": {"pe_ttm": 15},
        "fundamental_data": {"roe": 0.2},
    }
    base.update(overrides)
    return base


def test_placeholder_data_caps_to_observe():
    result = _stock_result(
        data_quality={"has_placeholder": True, "blocking_issues": []},
    )
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "观察"
    assert any("placeholder" in r for r in reasons)


def test_blocking_issues_caps_to_observe():
    result = _stock_result(
        data_quality={
            "has_placeholder": False,
            "blocking_issues": ["数据源连接失败"],
        },
    )
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "观察"
    assert any("阻断" in r for r in reasons)


def test_critical_event_count_forces_avoid():
    result = _stock_result(
        event_data={"event_summary": {"critical_count": 1}},
    )
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "回避"
    assert any("critical" in r.lower() for r in reasons)


def test_critical_event_count_forces_avoid_via_blocking_issues():
    """critical 事件通过 blocking_issues 触发回避。"""
    result = _stock_result(
        event_data={"event_summary": {"critical_count": 0}},
        data_quality={
            "has_placeholder": False,
            "blocking_issues": ["检测到 critical 级别公告风险"],
        },
    )
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "回避"
    assert any("critical" in r.lower() for r in reasons)


def test_missing_valuation_caps_stock_to_observe():
    result = _stock_result()
    del result["valuation_data"]
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "观察"
    assert any("valuation_data" in r for r in reasons)


def test_missing_fundamental_caps_stock_to_observe():
    result = _stock_result()
    del result["fundamental_data"]
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "观察"
    assert any("fundamental_data" in r for r in reasons)


def test_etf_skips_fundamental_and_valuation_checks():
    """ETF 不检查 fundamental_data 和 valuation_data 缺失。"""
    result = {
        "data_quality": {"has_placeholder": False, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "asset_type": "etf",
    }
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "买入"


def test_multiple_quality_issues_accumulate_reasons():
    result = _stock_result(
        data_quality={"has_placeholder": True, "blocking_issues": ["缺失字段"]},
    )
    action, reasons = apply_data_quality_action_limits(result, "买入")
    assert action == "观察"
    assert len(reasons) >= 2


def test_already_low_action_not_further_capped_by_quality():
    """已经是观察或更低时，数据质量问题不会把已经很低的操作再降级（除了 critical）。"""
    result = _stock_result(
        data_quality={"has_placeholder": True, "blocking_issues": []},
    )
    action, reasons = apply_data_quality_action_limits(result, "观察")
    assert action == "观察"


# ── apply_decision_guard 完整流程 ──────────────────────────────────

def test_apply_decision_guard_clamps_and_adds_guard_info():
    result = {
        "score": 62,
        "rating": "C",
        "action": "买入",
        "data_quality": {"has_placeholder": False, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "asset_type": "stock",
        "valuation_data": {"pe_ttm": 15},
        "fundamental_data": {"roe": 0.2},
        "debate_result": {
            "risk_review": {"risk_level": "medium"},
            "committee_conclusion": {
                "action": "买入",
                "final_opinion": "模型建议买入。",
            },
        },
    }

    guarded = apply_decision_guard(result)

    assert guarded["action"] == "观察"
    assert guarded["decision_guard"]["enabled"] is True
    assert guarded["decision_guard"]["llm_action"] == "买入"
    assert guarded["decision_guard"]["final_action"] == "观察"
    assert "降级" in guarded["debate_result"]["committee_conclusion"]["final_opinion"]


def test_apply_decision_guard_no_debate_result():
    """没有 debate_result 时 action 来自 result 顶层字段。"""
    result = {
        "score": 70,
        "rating": "B",
        "action": "买入",
        "data_quality": {"has_placeholder": False, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "asset_type": "stock",
        "valuation_data": {"pe_ttm": 15},
        "fundamental_data": {"roe": 0.2},
    }

    guarded = apply_decision_guard(result)

    assert guarded["action"] == "观察"
    assert guarded["decision_guard"]["llm_action"] == "买入"
    assert guarded["decision_guard"]["final_action"] == "观察"


def test_apply_decision_guard_preserves_guard_reasons():
    result = {
        "score": 80,
        "rating": "B+",
        "action": "买入",
        "data_quality": {"has_placeholder": True, "blocking_issues": []},
        "source_metadata": {},
        "event_data": {"event_summary": {"critical_count": 0}},
        "asset_type": "stock",
        "valuation_data": {"pe_ttm": 15},
        "fundamental_data": {"roe": 0.2},
        "debate_result": {
            "risk_review": {"risk_level": "low"},
            "committee_conclusion": {
                "action": "买入",
                "final_opinion": "强烈建议买入。",
            },
        },
    }

    guarded = apply_decision_guard(result)

    assert guarded["decision_guard"]["guard_reasons"]
    assert guarded["action"] == "观察"


# ── ACTION_LEVEL 常量 ─────────────────────────────────────────────

def test_action_level_ordering():
    """确认操作激进程度排序符合设计预期。"""
    assert ACTION_LEVEL["回避"] < ACTION_LEVEL["谨慎观察"]
    assert ACTION_LEVEL["谨慎观察"] < ACTION_LEVEL["观察"]
    assert ACTION_LEVEL["观察"] < ACTION_LEVEL["持有"]
    assert ACTION_LEVEL["持有"] < ACTION_LEVEL["分批买入"]
    assert ACTION_LEVEL["分批买入"] < ACTION_LEVEL["买入"]
