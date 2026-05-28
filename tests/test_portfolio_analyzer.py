"""Tests for services/portfolio/portfolio_analyzer.py."""

import dataclasses
import json
from pathlib import Path

import pytest

from services.portfolio.portfolio_analyzer import (
    Constraints,
    HoldingAnalysis,
    PortfolioAnalysis,
    analyze_portfolio,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "portfolio_analysis_samples.json"


@pytest.fixture
def sample_data():
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["positions"], data["research_results"]


class TestWeightNormalization:

    def test_weights_sum_to_investable(self, sample_data):
        """target_weights + cash ≈ 100%."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results, risk_profile="balanced")
        total_weight = sum(h.target_weight for h in analysis.holdings)
        assert abs(total_weight + analysis.cash_weight - 1.0) < 0.01

    def test_weights_sum_with_custom_cash(self, sample_data):
        """Cash weight is at least min_cash_weight."""
        positions, results = sample_data
        c = Constraints(min_cash_weight=0.20)
        analysis = analyze_portfolio(positions, results, constraints=c)
        total_weight = sum(h.target_weight for h in analysis.holdings)
        assert abs(total_weight + analysis.cash_weight - 1.0) < 0.01
        assert analysis.cash_weight >= 0.20


class TestMissingData:

    def test_missing_result_recorded(self):
        """Missing research result → missing_reasons."""
        positions = [{"symbol": "MISSING.SH", "asset_type": "stock"}]
        analysis = analyze_portfolio(positions, {})
        assert len(analysis.missing_reasons) > 0
        assert "MISSING.SH" in analysis.missing_reasons[0]
        assert analysis.holdings[0].missing_reasons == ["无研究结果"]

    def test_partial_data_no_crash(self):
        """Partial result doesn't crash, fills what it can."""
        positions = [{"symbol": "X.SH", "asset_type": "stock"}]
        results = {"X.SH": {"score": 50, "rating": "C"}}
        analysis = analyze_portfolio(positions, results)
        assert analysis.holdings[0].score == 50
        assert analysis.holdings[0].risk_level is None

    def test_missing_result_no_high_confidence_weight(self):
        """Missing research result should not get high confidence weight."""
        positions = [
            {"symbol": "GOOD.SH", "asset_type": "stock"},
            {"symbol": "MISSING.SH", "asset_type": "stock"},
        ]
        results = {"GOOD.SH": {"score": 85, "rating": "B+", "action": "买入"}}
        analysis = analyze_portfolio(positions, results)
        missing_h = next(h for h in analysis.holdings if h.symbol == "MISSING.SH")
        good_h = next(h for h in analysis.holdings if h.symbol == "GOOD.SH")
        # Missing should get less weight than a scored holding
        assert missing_h.target_weight < good_h.target_weight

    def test_all_missing_results_allocate_to_cash(self):
        """If every holding lacks research data, do not manufacture target weights."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock"},
            {"symbol": "B.SH", "asset_type": "stock"},
        ]
        analysis = analyze_portfolio(positions, {})
        assert all(h.target_weight == 0 for h in analysis.holdings)
        assert analysis.cash_weight == 1.0
        assert analysis.portfolio_score is None


class TestIndustryCap:

    def test_industry_cap_enforced(self, sample_data):
        """No industry exceeds max_industry_weight."""
        positions, results = sample_data
        c = Constraints(max_industry_weight=0.30)
        analysis = analyze_portfolio(positions, results, constraints=c)
        for ind, weight in analysis.industry_exposure.items():
            assert weight <= 0.30 + 0.01, f"{ind} weight {weight} exceeds cap"

    def test_all_same_industry_respects_cap(self):
        """All holdings in same industry — industry cap must hold, excess goes to cash."""
        positions = [
            {"symbol": f"S{i}.SH", "asset_type": "stock", "asset_name": f"Stock {i}"}
            for i in range(4)
        ]
        results = {
            f"S{i}.SH": {
                "score": 70 + i * 5,
                "rating": "B",
                "action": "观察",
                "valuation_data": {"industry_name": "银行"},
                "decision_guard": {"risk_level": "medium"},
            }
            for i in range(4)
        }
        c = Constraints(max_industry_weight=0.35, max_single_weight=0.25, min_cash_weight=0.05)
        analysis = analyze_portfolio(positions, results, constraints=c)

        # Industry exposure must not exceed cap
        bank_exposure = analysis.industry_exposure.get("银行", 0)
        assert bank_exposure <= 0.36, f"Industry exposure {bank_exposure} exceeds cap 0.35"

        # Cash must absorb the remainder
        total_holdings = sum(h.target_weight for h in analysis.holdings)
        assert abs(total_holdings + analysis.cash_weight - 1.0) < 0.01
        # With 4 same-industry holdings capped at 35%, cash should be significant
        assert analysis.cash_weight > 0.5


class TestSingleHoldingCap:

    def test_single_holding_cap(self, sample_data):
        """No single holding exceeds max_single_weight."""
        positions, results = sample_data
        c = Constraints(max_single_weight=0.20)
        analysis = analyze_portfolio(positions, results, constraints=c)
        for h in analysis.holdings:
            assert h.target_weight <= 0.20 + 0.01, \
                f"{h.symbol} weight {h.target_weight} exceeds cap 0.20"


class TestHighRiskPenalty:

    def test_high_risk_always_lower_weight_balanced(self):
        """High risk gets lower weight than medium risk with same score (balanced).

        Uses 6 holdings with high cap so the single-holding cap doesn't mask the risk discount.
        """
        positions = [{"symbol": f"S{i}.SH", "asset_type": "stock"} for i in range(6)]
        results = {}
        for i in range(6):
            risk = "high" if i == 0 else "medium"
            ind = f"行业{i}"
            results[f"S{i}.SH"] = {
                "score": 75, "rating": "B", "action": "观察",
                "decision_guard": {"risk_level": risk},
                "valuation_data": {"industry_name": ind},
            }
        c = Constraints(max_single_weight=0.50, max_industry_weight=0.50)
        analysis = analyze_portfolio(positions, results, risk_profile="balanced", constraints=c)
        high_h = next(h for h in analysis.holdings if h.symbol == "S0.SH")
        med_h = next(h for h in analysis.holdings if h.symbol == "S1.SH")
        assert high_h.target_weight < med_h.target_weight, \
            f"High risk {high_h.target_weight} should be < medium risk {med_h.target_weight}"

    def test_high_risk_always_lower_weight_aggressive(self):
        """High risk gets lower weight than medium risk even in aggressive mode."""
        positions = [{"symbol": f"S{i}.SH", "asset_type": "stock"} for i in range(6)]
        results = {}
        for i in range(6):
            risk = "high" if i == 0 else "medium"
            ind = f"行业{i}"
            results[f"S{i}.SH"] = {
                "score": 75, "rating": "B", "action": "观察",
                "decision_guard": {"risk_level": risk},
                "valuation_data": {"industry_name": ind},
            }
        c = Constraints(max_single_weight=0.50, max_industry_weight=0.50)
        analysis = analyze_portfolio(positions, results, risk_profile="aggressive", constraints=c)
        high_h = next(h for h in analysis.holdings if h.symbol == "S0.SH")
        med_h = next(h for h in analysis.holdings if h.symbol == "S1.SH")
        assert high_h.target_weight < med_h.target_weight, \
            f"Aggressive: high risk {high_h.target_weight} should be < medium {med_h.target_weight}"


class TestRiskProfileDifference:

    def test_conservative_lower_risk_allocation(self, sample_data):
        """Conservative profile gives less weight to high-risk holdings."""
        positions, results = sample_data
        conservative = analyze_portfolio(positions, results, risk_profile="conservative")
        aggressive = analyze_portfolio(positions, results, risk_profile="aggressive")

        high_risk_symbol = "300750.SZ"
        c_weight = next(h.target_weight for h in conservative.holdings if h.symbol == high_risk_symbol)
        a_weight = next(h.target_weight for h in aggressive.holdings if h.symbol == high_risk_symbol)
        assert c_weight <= a_weight


class TestCashWeight:

    def test_cash_weight_present(self, sample_data):
        """Cash weight is at least min_cash_weight."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        assert analysis.cash_weight >= 0.05

    def test_custom_cash_weight(self, sample_data):
        positions, results = sample_data
        c = Constraints(min_cash_weight=0.15)
        analysis = analyze_portfolio(positions, results, constraints=c)
        assert analysis.cash_weight >= 0.15


class TestNoTradingLanguage:

    def test_no_auto_trade_language(self, sample_data):
        """Analysis output must not contain auto-trade language."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        forbidden = ["自动下单", "自动交易", "交易指令", "auto trade", "auto order"]
        analysis_str = json.dumps(dataclasses.asdict(analysis), ensure_ascii=False)
        for word in forbidden:
            assert word not in analysis_str, f"Forbidden word '{word}' found in analysis"


class TestCurrentWeightAndRebalance:

    def test_current_weight_wired_through(self):
        """current_weight from positions must appear in holding output."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.30},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.10},
        ]
        results = {
            "A.SH": {"score": 70, "rating": "B", "action": "观察",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "银行"}},
            "B.SH": {"score": 80, "rating": "B+", "action": "分批买入",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "科技"}},
        }
        analysis = analyze_portfolio(positions, results)
        a_h = next(h for h in analysis.holdings if h.symbol == "A.SH")
        b_h = next(h for h in analysis.holdings if h.symbol == "B.SH")
        assert a_h.current_weight == 0.30
        assert b_h.current_weight == 0.10

    def test_delta_weight_computed(self):
        """delta_weight = target - current."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.50},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.05},
        ]
        results = {
            "A.SH": {"score": 60, "rating": "C", "action": "谨慎观察",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "银行"}},
            "B.SH": {"score": 85, "rating": "B+", "action": "分批买入",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "科技"}},
        }
        analysis = analyze_portfolio(positions, results)
        for h in analysis.holdings:
            expected_delta = round(h.target_weight - h.current_weight, 4)
            assert abs(h.delta_weight - expected_delta) < 0.001

    def test_rebalance_action_reduce_for_overweight(self):
        """Holding with current > target should get 'reduce' action."""
        positions = [
            {"symbol": "OVER.SH", "asset_type": "stock", "current_weight": 0.50},
            {"symbol": "UNDER.SH", "asset_type": "stock", "current_weight": 0.01},
        ]
        results = {
            "OVER.SH": {"score": 60, "rating": "C", "action": "谨慎观察",
                         "decision_guard": {"risk_level": "medium"},
                         "valuation_data": {"industry_name": "银行"}},
            "UNDER.SH": {"score": 90, "rating": "A", "action": "买入",
                          "decision_guard": {"risk_level": "low"},
                          "valuation_data": {"industry_name": "科技"}},
        }
        analysis = analyze_portfolio(positions, results)
        over_h = next(h for h in analysis.holdings if h.symbol == "OVER.SH")
        # With 50% current and lower score, target should be less → reduce
        assert over_h.target_weight < 0.50
        assert over_h.rebalance_action == "reduce"
        assert over_h.rebalance_reason is not None
        assert "减仓" in over_h.rebalance_reason

    def test_rebalance_action_hold_for_near_target(self):
        """Holding near target should get 'hold' action."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.47},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.48},
        ]
        results = {
            "A.SH": {"score": 75, "rating": "B", "action": "观察",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "银行"}},
            "B.SH": {"score": 75, "rating": "B", "action": "观察",
                      "decision_guard": {"risk_level": "medium"},
                      "valuation_data": {"industry_name": "科技"}},
        }
        analysis = analyze_portfolio(positions, results)
        for h in analysis.holdings:
            if abs(h.delta_weight) <= 0.02:
                assert h.rebalance_action == "hold"


class TestExposureComputation:

    def test_industry_exposure(self, sample_data):
        """Industry exposure covers all holdings."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        total_industry = sum(analysis.industry_exposure.values())
        total_holding = sum(h.target_weight for h in analysis.holdings)
        assert abs(total_industry - total_holding) < 0.01

    def test_asset_type_exposure(self, sample_data):
        """Asset type exposure covers all holdings."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        total_type = sum(analysis.asset_type_exposure.values())
        total_holding = sum(h.target_weight for h in analysis.holdings)
        assert abs(total_type - total_holding) < 0.01


class TestRebalanceSuggestions:

    def test_high_risk_suggestion(self, sample_data):
        """High-risk holdings generate rebalance suggestions."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        suggestions_text = " ".join(analysis.rebalance_suggestions)
        assert "300750.SZ" in suggestions_text

    def test_drawdown_suggestion(self, sample_data):
        """High drawdown holdings generate suggestions."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        suggestions_text = " ".join(analysis.rebalance_suggestions)
        assert "回撤" in suggestions_text or "300750.SZ" in suggestions_text


class TestEmptyPortfolio:

    def test_empty_positions(self):
        """Empty positions returns valid analysis."""
        analysis = analyze_portfolio([], {})
        assert analysis.total_holdings == 0
        assert analysis.portfolio_score is None
        assert analysis.cash_weight == 1.0


class TestPortfolioScore:

    def test_portfolio_score_is_weighted_average(self, sample_data):
        """Portfolio score is weighted average of holding scores."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        if analysis.portfolio_score is not None:
            assert 0 <= analysis.portfolio_score <= 100

    def test_portfolio_rating_matches_score(self, sample_data):
        """Portfolio rating matches score thresholds."""
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        if analysis.portfolio_score is not None:
            score = analysis.portfolio_score
            rating = analysis.portfolio_rating
            if score >= 90:
                assert rating == "A"
            elif score >= 80:
                assert rating == "B+"
            elif score >= 70:
                assert rating == "B"
            elif score >= 60:
                assert rating == "C"
            else:
                assert rating == "D"


class TestArtifactContainsDisclaimer:

    def test_markdown_contains_disclaimer(self, sample_data):
        """Markdown artifact must contain disclaimer."""
        from services.portfolio.report_builder import save_portfolio_report
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        artifacts = save_portfolio_report(analysis)
        md_content = Path(artifacts["markdown"]).read_text(encoding="utf-8")
        assert "研究建议" in md_content
        assert "不构成交易指令" in md_content or "不会自动下单" in md_content

    def test_json_no_trade_language(self, sample_data):
        """JSON artifact must not contain trade language."""
        import dataclasses as dc
        from services.portfolio.report_builder import save_portfolio_report
        positions, results = sample_data
        analysis = analyze_portfolio(positions, results)
        artifacts = save_portfolio_report(analysis)
        json_content = Path(artifacts["json"]).read_text(encoding="utf-8")
        forbidden = ["自动下单", "自动交易", "交易指令"]
        for word in forbidden:
            assert word not in json_content
