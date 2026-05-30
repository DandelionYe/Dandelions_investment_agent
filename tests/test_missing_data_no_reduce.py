"""Tests for missing-data rebalance guard in portfolio_analyzer.

When research results are missing or lack a score, the system must NOT generate
'reduce' rebalance actions. "No research data" != "should reduce position".

Regression tests for the score-is-None guard in _allocate_weights Step 6.
"""

import pytest

from services.portfolio.portfolio_analyzer import analyze_portfolio

# Sentinel for parametrize: represents "omit the score key entirely"
_SENTINEL = object()


class TestMissingDataNoReduce:
    """Verify that missing research data does not produce reduce rebalance actions."""

    def test_all_missing_with_current_weights_no_reduce(self):
        """When all research results are missing but user has current weights,
        the system should NOT generate 'reduce' rebalance actions."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.30},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.20},
        ]
        research_results = {}  # No research results at all

        analysis = analyze_portfolio(positions, research_results)

        a_h = next(h for h in analysis.holdings if h.symbol == "A.SH")
        b_h = next(h for h in analysis.holdings if h.symbol == "B.SH")

        # Target weight should be 0 (no research data)
        assert a_h.target_weight == 0.0
        assert b_h.target_weight == 0.0

        # delta_weight should be 0 (no data → no meaningful delta)
        assert a_h.delta_weight == 0.0, \
            f"delta_weight should be 0 for missing data, got {a_h.delta_weight}"
        assert b_h.delta_weight == 0.0, \
            f"delta_weight should be 0 for missing data, got {b_h.delta_weight}"

        # Should NOT generate reduce advice
        assert a_h.rebalance_action is None, \
            f"A.SH should not have rebalance_action, got '{a_h.rebalance_action}'"
        assert b_h.rebalance_action is None, \
            f"B.SH should not have rebalance_action, got '{b_h.rebalance_action}'"

        # Should have informative reason
        assert "缺少研究结果" in a_h.rebalance_reason
        assert "缺少研究结果" in b_h.rebalance_reason

    def test_partial_missing_with_current_weights(self):
        """Mix of missing and present research results with current weights."""
        positions = [
            {"symbol": "GOOD.SH", "asset_type": "stock", "current_weight": 0.30},
            {"symbol": "MISSING.SH", "asset_type": "stock", "current_weight": 0.20},
        ]
        research_results = {
            "GOOD.SH": {
                "score": 80,
                "rating": "B+",
                "action": "买入",
                "decision_guard": {"risk_level": "medium"},
                "valuation_data": {"industry_name": "科技"},
            }
        }

        analysis = analyze_portfolio(positions, research_results)

        good_h = next(h for h in analysis.holdings if h.symbol == "GOOD.SH")
        missing_h = next(h for h in analysis.holdings if h.symbol == "MISSING.SH")

        # GOOD.SH should have valid rebalance advice based on research
        assert good_h.score == 80
        assert good_h.rebalance_action in ("add", "hold", "reduce"), \
            f"GOOD.SH should have a valid action, got '{good_h.rebalance_action}'"

        # MISSING.SH should NOT have reduce advice
        assert missing_h.rebalance_action is None, \
            f"MISSING.SH should not have rebalance_action, got '{missing_h.rebalance_action}'"
        assert missing_h.delta_weight == 0.0
        assert "缺少研究结果" in missing_h.rebalance_reason

    def test_all_missing_no_current_weights(self):
        """When all research results are missing and no current weights,
        the system should NOT generate any rebalance actions."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock"},
            {"symbol": "B.SH", "asset_type": "stock"},
        ]
        research_results = {}

        analysis = analyze_portfolio(positions, research_results)

        for h in analysis.holdings:
            assert h.target_weight == 0.0
            assert h.delta_weight == 0.0
            assert h.rebalance_action is None
            assert "缺少研究结果" in h.rebalance_reason

    @pytest.mark.parametrize("score_value", [_SENTINEL, None], ids=["omitted", "explicit_none"])
    def test_result_without_score_no_reduce(self, score_value):
        """When research result has no score (omitted or explicit None), should NOT generate reduce."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.30},
        ]
        result = {
            "rating": "B+",
            "action": "观察",
            "valuation_data": {"industry_name": "银行"},
        }
        if score_value is not _SENTINEL:
            result["score"] = score_value
        research_results = {"A.SH": result}

        analysis = analyze_portfolio(positions, research_results)
        h = analysis.holdings[0]

        # Should NOT generate reduce advice when score is missing
        assert h.rebalance_action is None, \
            f"Should not have rebalance_action when score is missing, got '{h.rebalance_action}'"
        assert h.delta_weight == 0.0
        assert "缺少研究结果" in h.rebalance_reason

    def test_score_zero_is_valid_data_not_missing(self):
        """Score=0 is valid data (not None), so normal rebalance logic applies.
        With score=0 and current_weight=0.30, target will be low → reduce is expected."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.30},
        ]
        research_results = {
            "A.SH": {
                "score": 0,
                "rating": "D",
                "action": "回避",
                "decision_guard": {"risk_level": "medium"},
                "valuation_data": {"industry_name": "银行"},
            }
        }

        analysis = analyze_portfolio(positions, research_results)
        h = analysis.holdings[0]

        # score=0 is valid data, so normal rebalance logic should run
        assert h.score == 0
        assert h.target_weight > 0  # raw_weight = max(0/100 * mult, 0.01) > 0
        # With target < current (0.30), should be reduce
        assert h.rebalance_action == "reduce"
        assert h.delta_weight < 0
