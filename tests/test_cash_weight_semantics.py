"""Tests for Issue 6: cash_weight semantic clarity.

Verifies that:
- target_cash_weight is the recommended cash allocation
- current_cash_weight is computed from user-provided current weights
- cash_weight is kept as a backward-compatible alias for target_cash_weight
- current_cash_weight is None when no current weights are provided
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.portfolio.portfolio_analyzer import (
    Constraints,
    HoldingAnalysis,
    PortfolioAnalysis,
    analyze_portfolio,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _positions_with_current_weights():
    """Two positions with current weights summing to 70%."""
    return [
        {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.40},
        {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.30},
    ]


def _positions_without_current_weights():
    """Two positions without current weights."""
    return [
        {"symbol": "A.SH", "asset_type": "stock"},
        {"symbol": "B.SH", "asset_type": "stock"},
    ]


def _research_results_with_scores():
    """Research results with valid scores."""
    return {
        "A.SH": {"score": 80, "rating": "B+", "action": "买入"},
        "B.SH": {"score": 65, "rating": "B", "action": "观察"},
    }


def _research_results_empty():
    """No research results."""
    return {}


# ── Test: target_cash_weight equals cash_weight ─────────────────────────────


class TestTargetCashWeightAlias:
    """target_cash_weight should always equal cash_weight for backward compat."""

    def test_target_equals_cash_with_scores(self):
        """When scores are present, target_cash_weight == cash_weight."""
        analysis = analyze_portfolio(
            _positions_without_current_weights(),
            _research_results_with_scores(),
        )
        assert analysis.target_cash_weight == analysis.cash_weight

    def test_target_equals_cash_all_missing(self):
        """When all research is missing, target_cash_weight == cash_weight == 1.0."""
        analysis = analyze_portfolio(
            _positions_without_current_weights(),
            _research_results_empty(),
        )
        assert analysis.target_cash_weight == 1.0
        assert analysis.cash_weight == 1.0

    def test_target_equals_cash_empty_portfolio(self):
        """Empty portfolio: target_cash_weight == cash_weight == 1.0."""
        analysis = analyze_portfolio([], {})
        assert analysis.target_cash_weight == 1.0
        assert analysis.cash_weight == 1.0

    def test_target_equals_cash_with_current_weights(self):
        """With current weights provided, target_cash_weight == cash_weight."""
        analysis = analyze_portfolio(
            _positions_with_current_weights(),
            _research_results_with_scores(),
        )
        assert analysis.target_cash_weight == analysis.cash_weight


# ── Test: current_cash_weight computation ───────────────────────────────────


class TestCurrentCashWeight:
    """current_cash_weight = 1 - sum(current_weights) when current weights provided."""

    def test_current_cash_weight_with_current_weights(self):
        """When current weights sum to 70%, current_cash_weight should be 30%."""
        analysis = analyze_portfolio(
            _positions_with_current_weights(),
            _research_results_with_scores(),
        )
        assert analysis.current_cash_weight is not None
        assert abs(analysis.current_cash_weight - 0.30) < 0.01

    def test_current_cash_weight_none_without_current_weights(self):
        """When no current weights provided, current_cash_weight should be None."""
        analysis = analyze_portfolio(
            _positions_without_current_weights(),
            _research_results_with_scores(),
        )
        assert analysis.current_cash_weight is None

    def test_current_cash_weight_100_when_all_zero(self):
        """When all current weights are explicitly 0.0, user has no holdings,
        so current_cash_weight should be 1.0 (100% cash)."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.0},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.0},
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        # Explicitly providing 0.0 means "no holdings", so cash is 100%
        assert analysis.current_cash_weight is not None
        assert abs(analysis.current_cash_weight - 1.0) < 0.01

    def test_current_cash_weight_0_percent_when_fully_invested(self):
        """When current weights sum to 100%, current_cash_weight should be 0%."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.60},
            {"symbol": "B.SH", "asset_type": "stock", "current_weight": 0.40},
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        assert analysis.current_cash_weight is not None
        assert abs(analysis.current_cash_weight - 0.0) < 0.01

    def test_current_cash_weight_all_missing_with_current_weights(self):
        """All missing research + current weights: current_cash still computed."""
        positions = _positions_with_current_weights()
        analysis = analyze_portfolio(positions, _research_results_empty())
        # target_cash should be 1.0 (all missing), current_cash should be 30%
        assert analysis.target_cash_weight == 1.0
        assert analysis.current_cash_weight is not None
        assert abs(analysis.current_cash_weight - 0.30) < 0.01

    def test_current_cash_weight_single_position(self):
        """Single position with current_weight=50% → current_cash=50%."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.50},
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        assert analysis.current_cash_weight is not None
        assert abs(analysis.current_cash_weight - 0.50) < 0.01

    def test_holding_current_weight_none_when_not_provided(self):
        """HoldingAnalysis.current_weight should be None when not provided."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock"},
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        assert len(analysis.holdings) == 1
        assert analysis.holdings[0].current_weight is None

    def test_holding_current_weight_zero_when_explicitly_zero(self):
        """HoldingAnalysis.current_weight should be 0.0 when explicitly provided as 0.0."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.0},
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        assert len(analysis.holdings) == 1
        assert analysis.holdings[0].current_weight == 0.0

    def test_current_cash_weight_none_when_mixed(self):
        """When some positions have current_weight and others don't,
        current_cash_weight should be None (data incomplete)."""
        positions = [
            {"symbol": "A.SH", "asset_type": "stock", "current_weight": 0.50},
            {"symbol": "B.SH", "asset_type": "stock"},  # not provided
        ]
        analysis = analyze_portfolio(positions, _research_results_with_scores())
        # Mixed: some provided, some not → current_cash_weight should be None
        assert analysis.current_cash_weight is None


# ── Test: target and current are independent ────────────────────────────────


class TestTargetCurrentIndependence:
    """target_cash_weight and current_cash_weight should be independent values."""

    def test_target_and_current_differ(self):
        """With current weights and scores, target and current should differ."""
        analysis = analyze_portfolio(
            _positions_with_current_weights(),
            _research_results_with_scores(),
        )
        # target is determined by score-based allocation + min_cash constraint
        # current is 1 - 0.70 = 0.30
        assert analysis.current_cash_weight is not None, "current_cash_weight should be set when current weights provided"
        assert analysis.target_cash_weight != analysis.current_cash_weight

    def test_target_respects_min_cash_constraint(self):
        """target_cash_weight should be at least min_cash_weight."""
        constraints = Constraints(min_cash_weight=0.10)
        analysis = analyze_portfolio(
            _positions_without_current_weights(),
            _research_results_with_scores(),
            constraints=constraints,
        )
        assert analysis.target_cash_weight >= 0.10
        # current_cash_weight should be None (no current weights provided)
        assert analysis.current_cash_weight is None
