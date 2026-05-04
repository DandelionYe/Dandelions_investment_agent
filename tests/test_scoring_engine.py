"""
评分引擎边界条件和边缘情况测试。

覆盖：负PE估值、极端波动率/回撤、低流动性、强弱基本面、
熊市趋势、placeholder上限、事件正向/负向得分、ETF评分。
"""

import pytest
from services.research.scoring_engine import score_asset, _event_policy_score


# ── 辅助函数：构建最小股票测试数据 ────────────────────────────────

def _stock(
    change_20d=0.0, change_60d=0.0,
    ma20="below", ma60="below",
    avg_turnover=300_000_000,
    max_dd=-0.05, vol=0.15,
    fundamental=None,
    valuation=None,
    event=None,
    source_meta=None,
):
    data = {
        "asset_type": "stock",
        "price_data": {
            "change_20d": change_20d,
            "change_60d": change_60d,
            "ma20_position": ma20,
            "ma60_position": ma60,
            "avg_turnover_20d": avg_turnover,
            "max_drawdown_60d": max_dd,
            "volatility_60d": vol,
        },
        "fundamental_data": fundamental or {},
        "valuation_data": valuation or {},
        "event_data": event or {
            "recent_news_sentiment": "neutral",
            "policy_risk": "medium",
            "event_summary": {},
            "events": [],
        },
        "source_metadata": source_meta or {},
    }
    return data


# ── 趋势动量维度 ───────────────────────────────────────────────────

def test_bullish_trend_scores_max():
    result = score_asset(_stock(
        change_20d=0.10, change_60d=0.15,
        ma20="above", ma60="above",
    ))
    assert result["score_breakdown"]["trend_momentum"] == 20


def test_bearish_trend_scores_min():
    result = score_asset(_stock(
        change_20d=-0.10, change_60d=-0.15,
        ma20="below", ma60="below",
    ))
    assert result["score_breakdown"]["trend_momentum"] == 0


def test_partial_trend_scores_partial():
    """20日涨但60日跌，价格在 MA20 上方但 MA60 下方。"""
    result = score_asset(_stock(
        change_20d=0.05, change_60d=-0.05,
        ma20="above", ma60="below",
    ))
    # +6 (change_20d>0) + 0 + 4 (above ma20) + 0 = 10
    assert result["score_breakdown"]["trend_momentum"] == 10


# ── 流动性维度 ─────────────────────────────────────────────────────

def test_high_turnover_scores_high_liquidity():
    result = score_asset(_stock(avg_turnover=5_000_000_000))
    assert result["score_breakdown"]["liquidity"] == 13


def test_low_turnover_scores_low_liquidity():
    result = score_asset(_stock(avg_turnover=100_000_000))
    assert result["score_breakdown"]["liquidity"] == 8


# ── 风险控制维度 ───────────────────────────────────────────────────

def test_extreme_volatility_reduces_risk_score():
    result = score_asset(_stock(vol=0.35))
    assert result["score_breakdown"]["risk_control"] <= 15  # 20 - 5


def test_high_volatility_reduces_risk_score():
    result = score_asset(_stock(vol=0.25))
    # 20 - 2 = 18 (vol > 0.20 but <= 0.30)
    assert result["score_breakdown"]["risk_control"] == 18


def test_normal_volatility_no_penalty():
    result = score_asset(_stock(vol=0.15))
    assert result["score_breakdown"]["risk_control"] == 20


def test_large_drawdown_reduces_risk_score():
    result = score_asset(_stock(max_dd=-0.20))
    assert result["score_breakdown"]["risk_control"] <= 14  # 20 - 6


def test_moderate_drawdown_reduces_risk_score():
    result = score_asset(_stock(max_dd=-0.12))
    # 20 - 3 = 17 (dd < -0.10 but >= -0.15)
    assert result["score_breakdown"]["risk_control"] == 17


def test_combined_volatility_and_drawdown_penalty():
    result = score_asset(_stock(vol=0.35, max_dd=-0.20))
    # 20 - 5 (vol) - 6 (dd) = 9
    assert result["score_breakdown"]["risk_control"] == 9


# ── 基本面质量维度 ────────────────────────────────────────────────

def test_strong_fundamental_scores_high():
    result = score_asset(_stock(
        fundamental={
            "roe": 0.25,
            "gross_margin": 0.60,
            "net_profit_growth": 0.20,
            "revenue_growth": 0.15,
            "debt_ratio": 0.30,
        },
    ))
    # 6 + 4 + 4 + 3 + 3 = 20
    assert result["score_breakdown"]["fundamental_quality"] == 20


def test_weak_fundamental_scores_low():
    result = score_asset(_stock(
        fundamental={
            "roe": 0.05,
            "gross_margin": 0.20,
            "net_profit_growth": -0.10,
            "revenue_growth": -0.05,
            "debt_ratio": 0.60,
        },
    ))
    assert result["score_breakdown"]["fundamental_quality"] == 0


def test_missing_fundamental_scores_zero():
    result = score_asset(_stock(fundamental={}))
    assert result["score_breakdown"]["fundamental_quality"] == 0


def test_placeholder_caps_fundamental_to_8():
    result = score_asset(_stock(
        fundamental={
            "roe": 0.25,
            "gross_margin": 0.60,
            "net_profit_growth": 0.20,
            "revenue_growth": 0.15,
            "debt_ratio": 0.30,
        },
        source_meta={
            "fundamental_data": {"source": "mock_placeholder"},
        },
    ))
    # 本来应该是 20，但被 cap 到 8
    assert result["score_breakdown"]["fundamental_quality"] == 8


# ── 估值性价比维度 ─────────────────────────────────────────────────

def test_negative_pe_gives_min_valuation():
    result = score_asset(_stock(valuation={"pe_ttm": -5}))
    assert result["score_breakdown"]["valuation"] == 4


def test_zero_pe_gives_min_valuation():
    result = score_asset(_stock(valuation={"pe_ttm": 0}))
    assert result["score_breakdown"]["valuation"] == 4


def test_no_percentile_data_gives_mid_valuation():
    """有正PE但没有分位数据 → 8分。"""
    result = score_asset(_stock(valuation={"pe_ttm": 15}))
    assert result["score_breakdown"]["valuation"] == 8


def test_high_pe_percentile_reduces_valuation():
    result = score_asset(_stock(valuation={
        "pe_ttm": 25,
        "pe_percentile": 0.85,
        "pb_percentile": 0.50,
    }))
    # 15 - 5 (pe_percentile > 0.8) - 0 = 10
    assert result["score_breakdown"]["valuation"] == 10


def test_high_pb_percentile_reduces_valuation():
    result = score_asset(_stock(valuation={
        "pe_ttm": 20,
        "pe_percentile": 0.50,
        "pb_percentile": 0.90,
    }))
    # 15 - 0 - 3 (pb > 0.8) = 12
    assert result["score_breakdown"]["valuation"] == 12


def test_both_percentiles_high_reduces_valuation():
    result = score_asset(_stock(valuation={
        "pe_ttm": 20,
        "pe_percentile": 0.90,
        "pb_percentile": 0.90,
    }))
    # 15 - 5 - 3 = 7
    assert result["score_breakdown"]["valuation"] == 7


def test_low_percentile_full_valuation_score():
    result = score_asset(_stock(valuation={
        "pe_ttm": 12,
        "pe_percentile": 0.30,
        "pb_percentile": 0.40,
    }))
    assert result["score_breakdown"]["valuation"] == 15


def test_placeholder_caps_valuation_to_6():
    result = score_asset(_stock(
        valuation={"pe_ttm": 12, "pe_percentile": 0.30},
        source_meta={"valuation_data": {"source": "mock_placeholder"}},
    ))
    assert result["score_breakdown"]["valuation"] == 6


# ── 事件/政策维度（通过 _event_policy_score）──────────────────────

def _event_data(**kwargs):
    base = {
        "event_data": {
            "recent_news_sentiment": "neutral",
            "policy_risk": "medium",
            "event_summary": {},
            "events": [],
        },
        "source_metadata": {},
    }
    base["event_data"].update(kwargs)
    return base


def test_critical_event_gives_zero_event_score():
    data = _event_data(
        event_summary={"critical_count": 1},
        events=[{"severity": "critical", "sentiment": "negative"}],
    )
    assert _event_policy_score(data) == 0


def test_high_severity_events_reduce_score():
    """high severity 事件扣分：每 high 事件扣 2 分。"""
    data = _event_data(
        event_summary={"high_severity_count": 2},
        events=[
            {"severity": "high", "sentiment": "neutral", "event_type": "other"},
            {"severity": "high", "sentiment": "neutral", "event_type": "other"},
        ],
    )
    # high_count=2 (from summary), negative_count=0
    # base 6 - min(4, 2*2) - 0 = 6 - 4 = 2
    assert _event_policy_score(data) == 2


def test_positive_catalysts_boost_score():
    data = _event_data(
        events=[
            {"severity": "low", "sentiment": "positive", "event_type": "dividend"},
            {"severity": "low", "sentiment": "neutral_positive", "event_type": "buyback"},
        ],
    )
    # base 6 + 2 (2 catalysts) = 8
    score = _event_policy_score(data)
    assert score >= 8


def test_negative_events_reduce_score():
    data = _event_data(
        event_summary={"negative_count": 2},
        events=[
            {"severity": "medium", "sentiment": "negative", "event_type": "regulatory_inquiry"},
            {"severity": "medium", "sentiment": "negative", "event_type": "other"},
        ],
    )
    # base 6 - min(3, 4) = 2, but also high_severity_count may affect
    score = _event_policy_score(data)
    assert score <= 4


def test_neutral_positive_sentiment_boosts_score():
    data = _event_data(recent_news_sentiment="neutral_positive")
    score = _event_policy_score(data)
    assert score >= 7  # base 6 + 1


def test_low_policy_risk_boosts_score():
    data = _event_data(policy_risk="low")
    score = _event_policy_score(data)
    assert score >= 7  # base 6 + 1


def test_event_policy_score_clamped_to_10_max():
    data = _event_data(
        recent_news_sentiment="neutral_positive",
        policy_risk="low",
        events=[
            {"severity": "low", "sentiment": "positive", "event_type": "dividend"},
            {"severity": "low", "sentiment": "positive", "event_type": "buyback"},
            {"severity": "low", "sentiment": "neutral_positive", "event_type": "earnings_forecast"},
            {"severity": "low", "sentiment": "neutral_positive", "event_type": "major_contract"},
        ],
    )
    score = _event_policy_score(data)
    assert score == 10  # clamped at 10


def test_event_policy_score_clamped_to_0_min():
    data = _event_data(
        event_summary={"negative_count": 5, "high_severity_count": 3},
        events=[
            {"severity": "high", "sentiment": "negative", "event_type": "regulatory_inquiry"},
            {"severity": "high", "sentiment": "negative", "event_type": "regulatory_inquiry"},
            {"severity": "high", "sentiment": "negative", "event_type": "regulatory_inquiry"},
        ],
    )
    score = _event_policy_score(data)
    assert score == 0


# ── 总分和评级 ─────────────────────────────────────────────────────

def test_max_possible_score_is_100():
    result = score_asset(_stock(
        change_20d=0.10, change_60d=0.15,
        ma20="above", ma60="above",
        avg_turnover=5_000_000_000,
        max_dd=-0.03, vol=0.10,
        fundamental={
            "roe": 0.25, "gross_margin": 0.60,
            "net_profit_growth": 0.20, "revenue_growth": 0.15,
            "debt_ratio": 0.20,
        },
        valuation={"pe_ttm": 12, "pe_percentile": 0.20, "pb_percentile": 0.30},
    ))
    # trend=20, liquidity=13, fundamental=20, valuation=15, risk=20, event≈7
    # max possible stock score is close to but not exceeding 100
    assert 0 <= result["total_score"] <= 100


def test_rating_a_for_high_score():
    result = score_asset(_stock(
        change_20d=0.10, change_60d=0.15,
        ma20="above", ma60="above",
        avg_turnover=5_000_000_000,
        max_dd=-0.03, vol=0.10,
        fundamental={
            "roe": 0.25, "gross_margin": 0.60,
            "net_profit_growth": 0.20, "revenue_growth": 0.15,
            "debt_ratio": 0.20,
        },
        valuation={"pe_ttm": 12, "pe_percentile": 0.20, "pb_percentile": 0.30},
    ))
    assert result["rating"] in ("A", "B+")
    assert result["total_score"] >= 80


def test_rating_d_for_low_score():
    result = score_asset(_stock(
        change_20d=-0.15, change_60d=-0.20,
        ma20="below", ma60="below",
        avg_turnover=100_000_000,
        max_dd=-0.25, vol=0.35,
        fundamental={
            "roe": 0.02, "gross_margin": 0.10,
            "net_profit_growth": -0.20, "revenue_growth": -0.10,
            "debt_ratio": 0.70,
        },
        valuation={"pe_ttm": 0},
    ))
    assert result["rating"] == "D"
    assert result["total_score"] < 60


def test_score_breakdown_has_all_six_dimensions():
    result = score_asset(_stock())
    assert set(result["score_breakdown"].keys()) == {
        "trend_momentum", "liquidity", "fundamental_quality",
        "valuation", "risk_control", "event_policy",
    }
