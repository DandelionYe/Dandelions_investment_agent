"""Portfolio analyzer — aggregate single-asset research into portfolio-level insights.

Pure business logic: no I/O, no DB, no network. Takes research results as input,
returns structured portfolio analysis.

Design constraints:
- Never produces trading instructions or auto-trade signals.
- Missing data → missing_reasons / data_warnings, never exceptions.
- Weight allocation uses explainable heuristics, not black-box optimization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

RiskProfile = Literal["conservative", "balanced", "aggressive"]


def normalize_symbol(symbol: str) -> str:
    """Canonical form for symbol lookup: strip whitespace, uppercase."""
    return str(symbol).strip().upper()


@dataclass
class Constraints:
    max_single_weight: float = 0.25  # max % for any single holding
    max_industry_weight: float = 0.35  # max % for any single industry
    min_cash_weight: float = 0.05  # minimum cash allocation


@dataclass
class HoldingAnalysis:
    symbol: str
    asset_type: str
    asset_name: str
    score: float | None = None
    rating: str | None = None
    action: str | None = None
    risk_level: str | None = None
    volatility_60d: float | None = None
    max_drawdown_60d: float | None = None
    industry: str | None = None
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    current_weight: float = 0.0  # user's current weight (0 if unknown)
    raw_weight: float = 0.0  # weight before constraints
    target_weight: float = 0.0  # weight after constraints
    delta_weight: float = 0.0  # target - current
    rebalance_action: str | None = None  # "add" / "reduce" / "hold"
    rebalance_reason: str | None = None
    data_warnings: list[str] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)


@dataclass
class PortfolioAnalysis:
    analysis_id: str
    generated_at: str
    risk_profile: RiskProfile
    constraints: Constraints
    total_holdings: int
    holdings: list[HoldingAnalysis]
    portfolio_score: float | None = None
    portfolio_rating: str | None = None
    risk_level: str | None = None
    # Deprecated: 使用 target_cash_weight 替代。保留此字段仅为向后兼容，
    # 未来版本将移除。构造时两者值相同（均在 analyze_portfolio 返回时赋值）。
    cash_weight: float = 0.0
    target_cash_weight: float = 0.0  # recommended cash allocation
    current_cash_weight: float | None = None  # 1 - sum(current_weights), None if no current weights
    industry_exposure: dict[str, float] = field(default_factory=dict)
    asset_type_exposure: dict[str, float] = field(default_factory=dict)
    rebalance_suggestions: list[str] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)
    data_warnings: list[str] = field(default_factory=list)


def analyze_portfolio(
    positions: list[dict[str, Any]],
    research_results: dict[str, dict[str, Any]],
    risk_profile: RiskProfile = "balanced",
    constraints: Constraints | None = None,
) -> PortfolioAnalysis:
    """Analyze a portfolio given positions and their research results.

    Args:
        positions: list of {symbol, asset_type?, asset_name?, current_weight?}
        research_results: dict mapping symbol → research result JSON
        risk_profile: conservative / balanced / aggressive
        constraints: weight constraints (defaults applied if None)

    Returns:
        PortfolioAnalysis with all fields populated
    """
    if constraints is None:
        constraints = Constraints()

    analysis_id = uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Build per-holding analysis ────────────────────────────
    holdings: list[HoldingAnalysis] = []
    global_missing: list[str] = []
    global_warnings: list[str] = []

    for pos in positions:
        symbol = normalize_symbol(pos["symbol"])
        result = research_results.get(symbol)
        h = _analyze_holding(symbol, pos, result)
        holdings.append(h)
        global_warnings.extend(f"{symbol}: {warning}" for warning in h.data_warnings)
        if not result:
            global_missing.append(f"{symbol}: 无研究结果，请先运行单票研究或观察池扫描")

    # ── Weight allocation ─────────────────────────────────────
    _allocate_weights(holdings, constraints, risk_profile)

    # ── Portfolio-level aggregation ───────────────────────────
    portfolio_score = _aggregate_score(holdings)
    portfolio_rating = _score_to_rating(portfolio_score)
    risk_level = _aggregate_risk(holdings)
    industry_exposure = _compute_industry_exposure(holdings)
    asset_type_exposure = _compute_asset_type_exposure(holdings)
    # Target cash: at least min_cash_weight, but can be more if caps reduce holdings
    holding_total = sum(h.target_weight for h in holdings)
    target_cash_weight = max(constraints.min_cash_weight, round(1.0 - holding_total, 4))

    # Current cash: only meaningful when user provided current weights
    current_holdings_total = sum(h.current_weight for h in holdings)
    if current_holdings_total > 0:
        current_cash_weight = round(max(0.0, 1.0 - current_holdings_total), 4)
    else:
        current_cash_weight = None

    # ── Rebalance suggestions ─────────────────────────────────
    rebalance_suggestions = _generate_rebalance_suggestions(
        holdings, industry_exposure, constraints, risk_profile
    )

    return PortfolioAnalysis(
        analysis_id=analysis_id,
        generated_at=generated_at,
        risk_profile=risk_profile,
        constraints=constraints,
        total_holdings=len(holdings),
        holdings=holdings,
        portfolio_score=portfolio_score,
        portfolio_rating=portfolio_rating,
        risk_level=risk_level,
        cash_weight=target_cash_weight,  # backward compat alias
        target_cash_weight=target_cash_weight,
        current_cash_weight=current_cash_weight,
        industry_exposure=industry_exposure,
        asset_type_exposure=asset_type_exposure,
        rebalance_suggestions=rebalance_suggestions,
        missing_reasons=global_missing,
        data_warnings=global_warnings,
    )


# ── Internal helpers ──────────────────────────────────────────


def _analyze_holding(
    symbol: str, pos: dict, result: dict | None
) -> HoldingAnalysis:
    """Extract portfolio-relevant fields from a single research result."""
    h = HoldingAnalysis(
        symbol=symbol,
        asset_type=pos.get("asset_type", "stock"),
        asset_name=pos.get("asset_name", ""),
        current_weight=pos.get("current_weight") or 0.0,
    )

    if not result:
        h.missing_reasons.append("无研究结果")
        return h

    h.score = result.get("score")
    h.rating = result.get("rating")
    h.action = result.get("action")

    if h.score is None:
        h.data_warnings.append("缺少 score，无法参与目标权重分配")

    # Risk level from decision_guard or risk_review
    guard = result.get("decision_guard") or {}
    h.risk_level = guard.get("risk_level")
    if not h.risk_level:
        rr = result.get("risk_review")
        if isinstance(rr, str):
            for kw in ("高风险", "high"):
                if kw in rr:
                    h.risk_level = "high"
                    break
        elif isinstance(rr, dict):
            h.risk_level = rr.get("risk_level")

    # Price data
    pd = result.get("price_data") or {}
    h.volatility_60d = pd.get("volatility_60d")
    h.max_drawdown_60d = pd.get("max_drawdown_60d")

    # Valuation
    vd = result.get("valuation_data") or {}
    h.pe_percentile = vd.get("pe_percentile")
    h.pb_percentile = vd.get("pb_percentile")

    # Industry
    h.industry = vd.get("industry_name") or result.get("basic_info", {}).get("industry")
    if not h.industry:
        h.industry = "未分类"
        h.data_warnings.append("行业分类缺失，归入「未分类」")

    # Data quality warnings
    dq = result.get("data_quality") or {}
    if dq.get("has_placeholder"):
        h.data_warnings.append("含占位数据")
    if dq.get("blocking_issues"):
        h.data_warnings.append(f"阻断问题: {', '.join(dq['blocking_issues'])}")
    for w in dq.get("warnings") or []:
        if w:
            h.data_warnings.append(w)

    return h


def _allocate_weights(
    holdings: list[HoldingAnalysis],
    constraints: Constraints,
    risk_profile: RiskProfile,
) -> None:
    """Heuristic weight allocation based on score, risk, and constraints.

    Steps:
    1. Compute raw weight from score/action
    2. Apply risk/volatility discount (always penalizes high risk)
    3. Normalize to investable
    4. Apply single-holding cap (hard)
    5. Apply industry cap (hard) — excess goes to cash, NOT redistributed
    6. Compute delta_weight and rebalance_action
    """
    if not holdings:
        return

    investable = 1.0 - constraints.min_cash_weight

    # Profile multipliers — score_boost scales preference, risk_discount is always <= 1.0
    profile_cfg = {
        "conservative": {"score_boost": 0.5, "high_risk_discount": 0.4, "medium_risk_discount": 0.7},
        "balanced": {"score_boost": 1.0, "high_risk_discount": 0.6, "medium_risk_discount": 0.85},
        "aggressive": {"score_boost": 1.5, "high_risk_discount": 0.8, "medium_risk_discount": 0.95},
    }[risk_profile]

    # Step 1: Raw weight from score
    raw_weights: list[float] = []
    for h in holdings:
        if h.score is None:
            raw_weights.append(0.0)
            continue
        base = h.score / 100.0
        action_mult = _action_multiplier(h.action)
        w = base * action_mult * profile_cfg["score_boost"]
        raw_weights.append(max(w, 0.01))

    # Step 2: Risk/volatility discount — high risk ALWAYS gets lower weight
    for i, h in enumerate(holdings):
        discount = 1.0
        if h.risk_level == "high":
            discount *= profile_cfg["high_risk_discount"]
        elif h.risk_level == "medium":
            discount *= profile_cfg["medium_risk_discount"]
        if h.volatility_60d and h.volatility_60d > 0.5:
            discount *= 0.7
        if h.max_drawdown_60d and h.max_drawdown_60d < -0.3:
            discount *= 0.8
        raw_weights[i] *= discount

    # Step 3: Normalize to investable
    total_raw = sum(raw_weights)
    if total_raw > 0:
        for i in range(len(raw_weights)):
            raw_weights[i] = (raw_weights[i] / total_raw) * investable
    else:
        # No scored research data means no defensible target allocation.
        # Keep the portfolio in cash instead of manufacturing equal weights.
        raw_weights = [0.0] * len(holdings)

    # Step 4: Single-holding cap (hard) — excess redistributed to uncapped
    # Iterate: cap → redistribute → re-cap → ...
    for _ in range(5):
        excess = 0.0
        uncapped = []
        for i in range(len(raw_weights)):
            if raw_weights[i] > constraints.max_single_weight:
                excess += raw_weights[i] - constraints.max_single_weight
                raw_weights[i] = constraints.max_single_weight
            else:
                uncapped.append(i)
        if excess <= 0:
            break
        if not uncapped:
            break  # all capped, excess goes to cash
        uncapped_total = sum(raw_weights[i] for i in uncapped)
        if uncapped_total > 0:
            for i in uncapped:
                raw_weights[i] += excess * (raw_weights[i] / uncapped_total)
        else:
            break

    # Final hard cap: guarantee no holding exceeds max_single_weight
    # If caps make total < investable, remainder becomes cash
    for i in range(len(raw_weights)):
        raw_weights[i] = min(raw_weights[i], constraints.max_single_weight)

    # Step 5: Industry cap (hard) — excess goes to cash, NOT redistributed
    # This ensures industry cap is never violated by subsequent normalization
    for _ in range(3):
        industry_totals: dict[str, float] = {}
        for i, h in enumerate(holdings):
            ind = h.industry or "未分类"
            industry_totals[ind] = industry_totals.get(ind, 0) + raw_weights[i]

        for ind, total in industry_totals.items():
            if total > constraints.max_industry_weight:
                scale = constraints.max_industry_weight / total
                for i, h in enumerate(holdings):
                    if (h.industry or "未分类") == ind:
                        raw_weights[i] *= scale

    # NO post-cap normalization — excess becomes cash. This prevents
    # industry/single caps from being invalidated.

    # Assign weights
    for i, h in enumerate(holdings):
        h.raw_weight = round(raw_weights[i], 4)
        h.target_weight = round(raw_weights[i], 4)

    # Step 6: Compute delta_weight and rebalance_action
    _REBALANCE_THRESHOLD = 0.02  # 2% delta triggers rebalance suggestion
    for h in holdings:
        h.delta_weight = round(h.target_weight - h.current_weight, 4)

        # Skip rebalance logic when research data is missing.
        # "No data" does NOT mean "should reduce position".
        if h.score is None:
            h.delta_weight = 0.0  # no data → no meaningful delta
            h.rebalance_action = None
            h.rebalance_reason = "缺少研究结果，无法给出目标仓位和再平衡建议"
            continue

        if h.current_weight <= 0:
            # No current position — this is a new holding suggestion
            h.rebalance_action = "add" if h.target_weight > 0 else None
            h.rebalance_reason = (
                f"建议建仓 {h.target_weight:.1%}" if h.target_weight > 0 else None
            )
        elif abs(h.delta_weight) <= _REBALANCE_THRESHOLD:
            h.rebalance_action = "hold"
            h.rebalance_reason = "仓位接近目标，维持"
        elif h.delta_weight > 0:
            h.rebalance_action = "add"
            h.rebalance_reason = (
                f"当前 {h.current_weight:.1%} → 目标 {h.target_weight:.1%}，"
                f"建议加仓 {h.delta_weight:.1%}"
            )
        else:
            h.rebalance_action = "reduce"
            h.rebalance_reason = (
                f"当前 {h.current_weight:.1%} → 目标 {h.target_weight:.1%}，"
                f"建议减仓 {abs(h.delta_weight):.1%}"
            )


def _action_multiplier(action: str | None) -> float:
    """Map action string to weight multiplier."""
    if not action:
        return 0.5
    action_map = {
        "买入": 1.5,
        "分批买入": 1.3,
        "观察": 1.0,
        "谨慎观察": 0.7,
        "回避": 0.3,
    }
    return action_map.get(action, 1.0)


def _aggregate_score(holdings: list[HoldingAnalysis]) -> float | None:
    """Weighted average score across holdings."""
    total_weight = 0.0
    weighted_sum = 0.0
    for h in holdings:
        if h.score is not None and h.target_weight > 0:
            weighted_sum += h.score * h.target_weight
            total_weight += h.target_weight
    if total_weight > 0:
        return round(weighted_sum / total_weight, 1)
    return None


def _score_to_rating(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 80:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _aggregate_risk(holdings: list[HoldingAnalysis]) -> str:
    """Aggregate risk level: high if any holding is high, else medium if any medium, else low."""
    has_high = any(h.risk_level == "high" for h in holdings)
    has_medium = any(h.risk_level == "medium" for h in holdings)
    if has_high:
        return "high"
    if has_medium:
        return "medium"
    return "low"


def _compute_industry_exposure(holdings: list[HoldingAnalysis]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for h in holdings:
        ind = h.industry or "未分类"
        exposure[ind] = exposure.get(ind, 0) + h.target_weight
    return {k: round(v, 4) for k, v in sorted(exposure.items(), key=lambda x: -x[1])}


def _compute_asset_type_exposure(holdings: list[HoldingAnalysis]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for h in holdings:
        at = h.asset_type or "unknown"
        exposure[at] = exposure.get(at, 0) + h.target_weight
    return {k: round(v, 4) for k, v in sorted(exposure.items(), key=lambda x: -x[1])}


def _generate_rebalance_suggestions(
    holdings: list[HoldingAnalysis],
    industry_exposure: dict[str, float],
    constraints: Constraints,
    risk_profile: RiskProfile,
) -> list[str]:
    suggestions: list[str] = []

    for h in holdings:
        if h.risk_level == "high" and h.target_weight > 0.1:
            suggestions.append(f"{h.symbol} 风险等级为 high，建议降低仓位至 10% 以下")
        if h.max_drawdown_60d and h.max_drawdown_60d < -0.3:
            suggestions.append(f"{h.symbol} 近 60 日最大回撤 {h.max_drawdown_60d:.1%}，注意风控")
        if h.data_warnings:
            for w in h.data_warnings:
                suggestions.append(f"{h.symbol}: {w}")

    for ind, weight in industry_exposure.items():
        if weight > constraints.max_industry_weight:
            suggestions.append(f"行业「{ind}」暴露 {weight:.1%} 超过上限 {constraints.max_industry_weight:.0%}，建议分散")

    if risk_profile == "conservative":
        high_risk_count = sum(1 for h in holdings if h.risk_level == "high")
        if high_risk_count > 0:
            suggestions.append(f"保守型配置中有 {high_risk_count} 个高风险标的，建议替换为低风险品种")

    return suggestions
