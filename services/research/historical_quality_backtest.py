"""P2 Phase 2: 真实历史回测模块。

在 quality_backtest.py 基础上扩展，支持：
- 真实历史样本 schema 校验
- 场景标签覆盖统计
- forward_metrics 分桶分析
- 高风险样本激进建议违规检测
- placeholder/critical 保护器命中率
- 行业分位有效率
- 可配置验收阈值
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from services.research.decision_guard import ACTION_LEVEL
from services.research.quality_backtest import (
    evaluate_backtest_sample,
    load_backtest_samples,
    run_backtest,
)

# ── 默认验收阈值 ──────────────────────────────────────────────

DEFAULT_ACCEPTANCE_THRESHOLDS: dict[str, Any] = {
    "min_samples": 50,
    "max_aggressive_action_rate_for_high_risk": 0.0,
    "min_placeholder_guard_hit_rate": 1.0,
    "min_critical_guard_hit_rate": 1.0,
    "min_placeholder_sample_count": 0,
    "min_critical_sample_count": 0,
    "min_industry_percentile_valid_rate": 0.60,
    "max_single_score_bucket_ratio": 0.70,
    "min_rating_bucket_count": 3,
    "min_action_bucket_count": 3,
    "min_price_source_coverage": 0.0,  # 0 = 不要求，1.0 = 全部必须 qmt_xtdata
    "min_fundamental_source_coverage": 0.0,
    "min_valuation_source_coverage": 0.0,
    "min_industry_source_coverage": 0.0,
    "min_data_complete_coverage": 0.0,
}

# Phase 2B strict acceptance: full research-quality samples, not price-only smoke.
# Historical news/critical-event backtesting is explicitly out of scope, but
# valuation, profitability fundamentals, strict industry provenance, and complete
# research inputs must remain real thresholds. If local data cannot satisfy them,
# the strict run should fail and report the blocker instead of passing softly.
REAL_QMT_ACCEPTANCE_THRESHOLDS: dict[str, Any] = {
    "min_samples": 50,
    "max_aggressive_action_rate_for_high_risk": 0.0,
    "min_placeholder_guard_hit_rate": 1.0,
    "min_critical_guard_hit_rate": 0.0,
    "min_placeholder_sample_count": 1,
    "min_critical_sample_count": 0,
    "min_industry_percentile_valid_rate": 0.60,
    "max_single_score_bucket_ratio": 0.70,
    "min_rating_bucket_count": 3,
    "min_action_bucket_count": 3,
    "min_price_source_coverage": 1.0,
    "min_fundamental_source_coverage": 0.60,
    "min_valuation_source_coverage": 0.60,
    "min_industry_source_coverage": 0.60,
    "min_data_complete_coverage": 0.50,
    "skip_required_tag_check": True,
}

# QMT price-chain smoke acceptance. Do not use this to mark Phase 2B complete.
PRICE_ONLY_QMT_ACCEPTANCE_THRESHOLDS: dict[str, Any] = {
    "min_samples": 50,
    "max_aggressive_action_rate_for_high_risk": 0.0,
    "min_placeholder_guard_hit_rate": 1.0,
    "min_placeholder_sample_count": 1,
    "min_critical_guard_hit_rate": 0.0,
    "min_critical_sample_count": 0,
    "min_industry_percentile_valid_rate": 0.0,
    "max_single_score_bucket_ratio": 1.0,
    "min_rating_bucket_count": 1,
    "min_action_bucket_count": 1,
    "min_price_source_coverage": 1.0,
    "skip_required_tag_check": True,
}

# ── 必需场景标签（验收必须覆盖） ───────────────────────────────

REQUIRED_SCENARIO_TAGS = {
    "stock",
    "etf",
    "large_cap",
    "small_or_mid_cap",
    "loss_making_or_invalid_pe",
    "missing_fundamental",
    "industry_insufficient_peers",
    "extreme_drawdown",
    "earnings_window",
}

# ── 高风险场景标签 ────────────────────────────────────────────

HIGH_RISK_SCENARIO_TAGS = {
    "extreme_drawdown",
    "high_volatility",
    "loss_making_or_invalid_pe",
    "critical_event",
    "bear_market",
}

STRICT_FUNDAMENTAL_FIELDS = frozenset({
    "roe",
    "gross_margin",
    "net_margin",
    "net_profit_growth",
    "revenue_growth",
    "net_profit_ttm",
    "revenue_ttm",
    "debt_ratio",
    "operating_cashflow_quality",
})

STRICT_VALUATION_FIELDS = frozenset({
    "pe_ttm",
    "pb_mrq",
    "ps_ttm",
    "dividend_yield",
})

CAPITAL_STRUCTURE_FIELDS = frozenset({
    "total_volume",
    "float_volume",
    "market_cap",
    "float_market_cap",
    "bps",
})

NON_STRICT_SOURCE_LABELS = frozenset({
    None,
    "",
    "missing",
    "non_strict",
    "latest_snapshot_fallback",
    "local_csmar_industry_non_strict",
    "local_csmar_industry_history_non_strict",
    "local_csmar_eva_structure_partial",
})

# ── 评分分桶 ─────────────────────────────────────────────────

SCORE_BUCKETS = [
    (0, 30, "0-29"),
    (30, 50, "30-49"),
    (50, 65, "50-64"),
    (65, 80, "65-79"),
    (80, 101, "80-100"),
]


def _score_bucket(score: int) -> str:
    for lo, hi, label in SCORE_BUCKETS:
        if lo <= score < hi:
            return label
    return "unknown"


# ── Schema 校验 ───────────────────────────────────────────────

_REQUIRED_SAMPLE_KEYS = {"sample_id", "symbol", "as_of", "asset_type",
                         "scenario_tags", "input_result", "forward_metrics",
                         "expected", "quality"}

_REQUIRED_PRICE_KEYS = {"change_20d", "change_60d", "ma20_position",
                        "ma60_position", "avg_turnover_20d",
                        "max_drawdown_60d", "volatility_60d"}

_REQUIRED_FORWARD_KEYS = {
    "return_20d", "return_60d", "return_120d",
    "benchmark_return_20d", "benchmark_return_60d", "benchmark_return_120d",
    "relative_return_20d", "relative_return_60d", "relative_return_120d",
    "max_drawdown_20d", "max_drawdown_60d", "max_drawdown_120d",
}

_REQUIRED_QUALITY_KEYS = {"is_real_historical_sample", "data_complete"}


def validate_historical_sample(sample: dict) -> list[str]:
    """校验单个历史样本的 schema 完整性。

    Returns
    -------
    list[str]
        错误列表，空表示校验通过。
    """
    errors: list[str] = []

    for key in _REQUIRED_SAMPLE_KEYS:
        if key not in sample:
            errors.append(f"缺少顶层字段: {key}")

    if errors:
        return errors  # 缺少关键字段，无法继续校验

    # scenario_tags
    tags = sample.get("scenario_tags", [])
    if not isinstance(tags, list) or len(tags) == 0:
        errors.append("scenario_tags 必须是非空列表")

    # input_result 结构
    ir = sample.get("input_result", {})
    if not isinstance(ir, dict):
        errors.append("input_result 必须是 dict")
    else:
        pd = ir.get("price_data", {})
        for k in _REQUIRED_PRICE_KEYS:
            if k not in pd:
                errors.append(f"input_result.price_data 缺少: {k}")

    # forward_metrics 结构
    fm = sample.get("forward_metrics", {})
    if not isinstance(fm, dict):
        errors.append("forward_metrics 必须是 dict")
    else:
        for k in _REQUIRED_FORWARD_KEYS:
            if k not in fm:
                errors.append(f"forward_metrics 缺少: {k}")

    # quality 结构
    q = sample.get("quality", {})
    if not isinstance(q, dict):
        errors.append("quality 必须是 dict")
    else:
        if "is_real_historical_sample" not in q:
            errors.append("quality 缺少: is_real_historical_sample")
        if q.get("is_real_historical_sample") is not True:
            errors.append("quality.is_real_historical_sample 必须为 true")
        # data_complete 不再强制为 True：真实 QMT 样本可能缺少基本面/估值数据，
        # 但价格和 forward metrics 是真实的
        if "data_complete" not in q:
            errors.append("quality 缺少: data_complete")

    # expected 结构
    exp = sample.get("expected", {})
    if not isinstance(exp, dict):
        errors.append("expected 必须是 dict")

    return errors


def load_historical_samples(path: str | Path) -> list[dict]:
    """加载历史回测样本。"""
    return load_backtest_samples(path)


def evaluate_historical_sample(sample: dict) -> dict:
    """评估单个历史样本，复用 quality_backtest.evaluate_backtest_sample。"""
    return evaluate_backtest_sample(sample)


def run_historical_backtest(samples: list[dict]) -> dict:
    """运行历史回测，返回原始回测结果 + scenario_tags 传播。"""
    raw = run_backtest(samples)

    # 将 scenario_tags 和原始 input_result 附加到每个结果
    for i, r in enumerate(raw["results"]):
        if i < len(samples):
            r["scenario_tags"] = samples[i].get("scenario_tags", [])
            r["forward_metrics"] = samples[i].get("forward_metrics", {})
            r["symbol"] = samples[i].get("symbol", "")
            r["as_of"] = samples[i].get("as_of", "")
            r["input_result"] = samples[i].get("input_result", {})
            r["quality"] = samples[i].get("quality", {})
            r["source"] = samples[i].get("source", {})
            r["out_of_scope_exception"] = samples[i].get("out_of_scope_exception", False)

    return raw


def summarize_historical_backtest(backtest_result: dict) -> dict:
    """汇总历史回测结果，包含丰富的质量指标。"""
    results = backtest_result.get("results", [])
    total = backtest_result.get("total", 0)
    passed = backtest_result.get("passed", 0)
    pass_rate = passed / total if total > 0 else 0.0

    # ── 基础场景汇总 ──
    scenario_summary = []
    for r in results:
        fm = r.get("forward_metrics", {})
        scenario_summary.append({
            "sample_id": r.get("sample_id", ""),
            "scenario": r.get("scenario", ""),
            "scenario_tags": r.get("scenario_tags", []),
            "symbol": r.get("symbol", ""),
            "as_of": r.get("as_of", ""),
            "score": r.get("score"),
            "rating": r.get("rating"),
            "action": r.get("action"),
            "forward_return_20d": fm.get("return_20d"),
            "forward_return_60d": fm.get("return_60d"),
            "forward_return_120d": fm.get("return_120d"),
            "benchmark_return_20d": fm.get("benchmark_return_20d"),
            "benchmark_return_60d": fm.get("benchmark_return_60d"),
            "benchmark_return_120d": fm.get("benchmark_return_120d"),
            "relative_return_20d": fm.get("relative_return_20d"),
            "relative_return_60d": fm.get("relative_return_60d"),
            "relative_return_120d": fm.get("relative_return_120d"),
            "data_complete": r.get("quality", {}).get("data_complete"),
            "all_passed": r.get("all_passed", False),
            "failed_checks": [
                c["name"] for c in r.get("checks", []) if not c["passed"]
            ],
        })

    # ── 维度统计 ──
    dim_stats: dict[str, dict] = {}
    for dim in ["trend_momentum", "liquidity", "fundamental_quality",
                "valuation", "risk_control", "event_policy"]:
        values = []
        for r in results:
            bd = r.get("score_breakdown", {})
            if dim in bd:
                values.append(bd[dim])
        if values:
            dim_stats[dim] = {
                "min": min(values),
                "max": max(values),
                "avg": round(sum(values) / len(values), 2),
            }

    # ── 评分分布 ──
    score_dist: dict[str, int] = Counter()
    for r in results:
        if r.get("score") is not None:
            score_dist[_score_bucket(r["score"])] += 1

    # ── 评级分布 ──
    rating_dist: dict[str, int] = Counter()
    for r in results:
        if r.get("rating"):
            rating_dist[r["rating"]] += 1

    # ── 动作分布 ──
    action_dist: dict[str, int] = Counter()
    for r in results:
        if r.get("action"):
            action_dist[r["action"]] += 1

    # ── 场景覆盖矩阵 ──
    tag_coverage: dict[str, int] = Counter()
    for r in results:
        for tag in r.get("scenario_tags", []):
            tag_coverage[tag] += 1

    # ── 高风险激进建议违规 ──
    high_risk_count = 0
    high_risk_aggressive_count = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        if tags & HIGH_RISK_SCENARIO_TAGS:
            high_risk_count += 1
            action = r.get("action", "")
            if ACTION_LEVEL.get(action, 0) >= ACTION_LEVEL.get("分批买入", 4):
                high_risk_aggressive_count += 1

    # ── placeholder 保护器命中率 ──
    placeholder_total = 0
    placeholder_guarded = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        ir = r.get("input_result", {})
        dq = ir.get("data_quality", {}) if isinstance(ir, dict) else {}
        has_placeholder = (
            "placeholder_data" in tags
            or "blocking_data_quality" in tags
            or bool(dq.get("has_placeholder"))
            or bool(dq.get("blocking_issues"))
        )
        if has_placeholder:
            placeholder_total += 1
            guard = r.get("decision_guard", {})
            max_action = guard.get("max_allowed_action", "")
            if ACTION_LEVEL.get(max_action, 99) <= 2:
                placeholder_guarded += 1

    # ── critical 保护器命中率 ──
    critical_total = 0
    critical_guarded = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        ir = r.get("input_result", {})
        event_data = ir.get("event_data", {}) if isinstance(ir, dict) else {}
        event_summary = event_data.get("event_summary", {}) if isinstance(event_data, dict) else {}
        has_critical = (
            "critical_event" in tags
            or int(event_summary.get("critical_count", 0) or 0) > 0
        )
        if has_critical:
            critical_total += 1
            guard = r.get("decision_guard", {})
            final_action = guard.get("final_action", r.get("action", ""))
            max_action = guard.get("max_allowed_action", "")
            if min(
                ACTION_LEVEL.get(final_action, 99),
                ACTION_LEVEL.get(max_action, 99),
            ) <= 0:
                critical_guarded += 1

    # ── 行业分位有效率 ──
    # Strict Phase 2B only counts industry percentiles whose industry
    # classification is itself strict as_of. Non-strict latest-snapshot
    # percentiles are still reported separately for diagnostics.
    industry_total = 0
    industry_valid = 0
    all_industry_total = 0
    all_industry_valid = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        if "industry_insufficient_peers" in tags:
            continue
        ir = r.get("input_result", {})
        vd = ir.get("valuation_data", {}) if isinstance(ir, dict) else {}
        if not vd:
            continue
        sm = ir.get("source_metadata", {}) if isinstance(ir, dict) else {}
        industry_source = sm.get("industry_source") if isinstance(sm, dict) else None
        is_strict_industry = industry_source not in NON_STRICT_SOURCE_LABELS
        has_valid = any(
            vd.get(f"industry_{m}_percentile") is not None
            for m in ["pe", "pb", "ps"]
        )
        all_industry_total += 1
        if has_valid:
            all_industry_valid += 1

        if not is_strict_industry:
            continue

        industry_total += 1
        if has_valid:
            industry_valid += 1

    # ── forward return 分桶表现（含 120d） ──
    forward_buckets: dict[str, dict] = {}
    for r in results:
        score = r.get("score")
        if score is None:
            continue
        bucket = _score_bucket(score)
        if bucket not in forward_buckets:
            forward_buckets[bucket] = {
                "count": 0,
                "avg_return_20d": 0.0, "avg_return_60d": 0.0,
                "avg_return_120d": 0.0,
                "avg_benchmark_return_20d": 0.0,
                "avg_benchmark_return_60d": 0.0,
                "avg_benchmark_return_120d": 0.0,
                "avg_relative_return_20d": 0.0,
                "avg_relative_return_60d": 0.0,
                "avg_relative_return_120d": 0.0,
                "avg_max_drawdown_20d": 0.0,
                "avg_max_drawdown_60d": 0.0,
                "avg_max_drawdown_120d": 0.0,
            }
        b = forward_buckets[bucket]
        b["count"] += 1
        fm = r.get("forward_metrics", {})
        b["avg_return_20d"] += fm.get("return_20d", 0.0) or 0.0
        b["avg_return_60d"] += fm.get("return_60d", 0.0) or 0.0
        b["avg_return_120d"] += fm.get("return_120d", 0.0) or 0.0
        b["avg_benchmark_return_20d"] += fm.get("benchmark_return_20d", 0.0) or 0.0
        b["avg_benchmark_return_60d"] += fm.get("benchmark_return_60d", 0.0) or 0.0
        b["avg_benchmark_return_120d"] += fm.get("benchmark_return_120d", 0.0) or 0.0
        b["avg_relative_return_20d"] += fm.get("relative_return_20d", 0.0) or 0.0
        b["avg_relative_return_60d"] += fm.get("relative_return_60d", 0.0) or 0.0
        b["avg_relative_return_120d"] += fm.get("relative_return_120d", 0.0) or 0.0
        b["avg_max_drawdown_20d"] += fm.get("max_drawdown_20d", 0.0) or 0.0
        b["avg_max_drawdown_60d"] += fm.get("max_drawdown_60d", 0.0) or 0.0
        b["avg_max_drawdown_120d"] += fm.get("max_drawdown_120d", 0.0) or 0.0

    for bucket in forward_buckets.values():
        n = bucket["count"]
        if n > 0:
            for key in bucket:
                if key != "count":
                    bucket[key] = round(bucket[key] / n, 4)

    # ── max drawdown by action bucket ──
    drawdown_by_action: dict[str, dict] = {}
    for r in results:
        action = r.get("action", "unknown")
        if action not in drawdown_by_action:
            drawdown_by_action[action] = {
                "count": 0, "avg_max_drawdown_20d": 0.0,
                "avg_max_drawdown_60d": 0.0, "avg_max_drawdown_120d": 0.0,
            }
        d = drawdown_by_action[action]
        d["count"] += 1
        fm = r.get("forward_metrics", {})
        d["avg_max_drawdown_20d"] += fm.get("max_drawdown_20d", 0.0) or 0.0
        d["avg_max_drawdown_60d"] += fm.get("max_drawdown_60d", 0.0) or 0.0
        d["avg_max_drawdown_120d"] += fm.get("max_drawdown_120d", 0.0) or 0.0
    for d in drawdown_by_action.values():
        n = d["count"]
        if n > 0:
            d["avg_max_drawdown_20d"] = round(d["avg_max_drawdown_20d"] / n, 4)
            d["avg_max_drawdown_60d"] = round(d["avg_max_drawdown_60d"] / n, 4)
            d["avg_max_drawdown_120d"] = round(d["avg_max_drawdown_120d"] / n, 4)

    # ── max drawdown by rating bucket ──
    drawdown_by_rating: dict[str, dict] = {}
    for r in results:
        rating = r.get("rating", "unknown")
        if rating not in drawdown_by_rating:
            drawdown_by_rating[rating] = {
                "count": 0, "avg_max_drawdown_20d": 0.0,
                "avg_max_drawdown_60d": 0.0, "avg_max_drawdown_120d": 0.0,
            }
        d = drawdown_by_rating[rating]
        d["count"] += 1
        fm = r.get("forward_metrics", {})
        d["avg_max_drawdown_20d"] += fm.get("max_drawdown_20d", 0.0) or 0.0
        d["avg_max_drawdown_60d"] += fm.get("max_drawdown_60d", 0.0) or 0.0
        d["avg_max_drawdown_120d"] += fm.get("max_drawdown_120d", 0.0) or 0.0
    for d in drawdown_by_rating.values():
        n = d["count"]
        if n > 0:
            d["avg_max_drawdown_20d"] = round(d["avg_max_drawdown_20d"] / n, 4)
            d["avg_max_drawdown_60d"] = round(d["avg_max_drawdown_60d"] / n, 4)
            d["avg_max_drawdown_120d"] = round(d["avg_max_drawdown_120d"] / n, 4)

    # ── year coverage ──
    year_coverage: dict[str, int] = Counter()
    for r in results:
        as_of = r.get("as_of", "")
        if len(as_of) >= 4:
            year_coverage[as_of[:4]] += 1

    # ── industry coverage ──
    # 行业信息可能在原始 sample 的 industry 字段中，此处用 tag 近似统计

    # ── market cap coverage ──
    market_cap_large = 0
    market_cap_mid_small = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        if "large_cap" in tags:
            market_cap_large += 1
        elif "small_or_mid_cap" in tags:
            market_cap_mid_small += 1

    # ── source coverage ──
    # Exclude non-strict/latest/partial sources from strict coverage. EVA
    # capital-structure data is tracked separately and does not count as
    # profitability fundamental coverage.
    price_source_qmt = 0
    price_source_other = 0
    fundamental_available = 0
    capital_structure_available = 0
    valuation_available = 0
    industry_available = 0
    for r in results:
        ir = r.get("input_result", {})
        if isinstance(ir, dict):
            sm = ir.get("source_metadata", {})
            fundamental_data = ir.get("fundamental_data", {})
            valuation_data = ir.get("valuation_data", {})
            if isinstance(sm, dict) and sm.get("price_source") == "qmt_xtdata":
                price_source_qmt += 1
            else:
                price_source_other += 1
            if (
                isinstance(sm, dict)
                and sm.get("fundamental_source") not in NON_STRICT_SOURCE_LABELS
                and isinstance(fundamental_data, dict)
                and any(
                    fundamental_data.get(field) is not None
                    for field in STRICT_FUNDAMENTAL_FIELDS
                )
            ):
                fundamental_available += 1
            if (
                isinstance(sm, dict)
                and sm.get("capital_structure_source") not in {None, "", "missing"}
                and isinstance(fundamental_data, dict)
                and any(
                    fundamental_data.get(field) is not None
                    for field in CAPITAL_STRUCTURE_FIELDS
                )
            ):
                capital_structure_available += 1
            if (
                isinstance(sm, dict)
                and sm.get("valuation_source") not in NON_STRICT_SOURCE_LABELS
                and isinstance(valuation_data, dict)
                and any(
                    valuation_data.get(field) is not None
                    for field in STRICT_VALUATION_FIELDS
                )
            ):
                valuation_available += 1
            if isinstance(sm, dict) and sm.get("industry_source") not in NON_STRICT_SOURCE_LABELS:
                industry_available += 1
        else:
            price_source_other += 1

    total_with_source = price_source_qmt + price_source_other
    price_source_coverage = (
        price_source_qmt / total_with_source if total_with_source > 0 else 0.0
    )
    fundamental_source_coverage = (
        fundamental_available / total if total > 0 else 0.0
    )
    capital_structure_source_coverage = (
        capital_structure_available / total if total > 0 else 0.0
    )
    valuation_source_coverage = (
        valuation_available / total if total > 0 else 0.0
    )
    industry_source_coverage = (
        industry_available / total if total > 0 else 0.0
    )

    # ── data gap summary ──
    coverage_gap_count = 0
    data_complete_count = 0
    for r in results:
        ir = r.get("input_result", {})
        q = r.get("quality", {})
        if isinstance(q, dict) and q.get("data_complete") is True:
            data_complete_count += 1
            continue
        if isinstance(ir, dict):
            dq = ir.get("data_quality", {})
            if isinstance(dq, dict) and dq.get("blocking_issues"):
                coverage_gap_count += 1
            else:
                data_complete_count += 1

    # ── 最大分桶占比 ──
    max_bucket_count = max(score_dist.values()) if score_dist else 0
    max_bucket_ratio = max_bucket_count / total if total > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": backtest_result.get("failed", 0),
        "pass_rate": round(pass_rate, 4),
        "scenario_summary": scenario_summary,
        "dimension_stats": dim_stats,
        "score_distribution": dict(score_dist),
        "rating_distribution": dict(rating_dist),
        "action_distribution": dict(action_dist),
        "scenario_coverage": dict(tag_coverage),
        "high_risk_aggressive_violation_count": high_risk_aggressive_count,
        "high_risk_aggressive_violation_rate": round(
            high_risk_aggressive_count / high_risk_count, 4
        ) if high_risk_count > 0 else 0.0,
        "placeholder_sample_count": placeholder_total,
        "critical_sample_count": critical_total,
        "placeholder_guard_hit_rate": round(
            placeholder_guarded / placeholder_total, 4
        ) if placeholder_total > 0 else None,
        "critical_guard_hit_rate": round(
            critical_guarded / critical_total, 4
        ) if critical_total > 0 else None,
        "industry_percentile_valid_rate": round(
            industry_valid / industry_total, 4
        ) if industry_total > 0 else 0.0,
        "all_industry_percentile_valid_rate": round(
            all_industry_valid / all_industry_total, 4
        ) if all_industry_total > 0 else 0.0,
        "max_single_score_bucket_ratio": round(max_bucket_ratio, 4),
        "rating_bucket_count": len(rating_dist),
        "action_bucket_count": len(action_dist),
        "forward_return_by_score_bucket": forward_buckets,
        "max_drawdown_by_action_bucket": drawdown_by_action,
        "max_drawdown_by_rating_bucket": drawdown_by_rating,
        "year_coverage": dict(year_coverage),
        "market_cap_coverage": {
            "large_cap": market_cap_large,
            "small_or_mid_cap": market_cap_mid_small,
        },
        "price_source_coverage": round(price_source_coverage, 4),
        "fundamental_source_coverage": round(fundamental_source_coverage, 4),
        "capital_structure_source_coverage": round(capital_structure_source_coverage, 4),
        "valuation_source_coverage": round(valuation_source_coverage, 4),
        "industry_source_coverage": round(industry_source_coverage, 4),
        "data_gap_summary": {
            "total_with_blocking_issues": coverage_gap_count,
            "data_complete_count": data_complete_count,
            "data_complete_coverage": round(
                data_complete_count / total, 4
            ) if total > 0 else 0.0,
        },
    }


def assert_historical_backtest_acceptance(
    summary: dict,
    thresholds: dict | None = None,
) -> None:
    """断言历史回测结果满足验收阈值。

    Raises
    ------
    AssertionError
        如果任何阈值未满足，消息包含具体失败指标。
    """
    t = {**DEFAULT_ACCEPTANCE_THRESHOLDS, **(thresholds or {})}
    failures: list[str] = []

    if summary["total"] < t["min_samples"]:
        failures.append(
            f"样本数不足: {summary['total']} < {t['min_samples']}"
        )

    if summary.get("placeholder_sample_count", 0) < t.get("min_placeholder_sample_count", 0):
        failures.append(
            "placeholder/blocked-data sample count too low: "
            f"{summary.get('placeholder_sample_count', 0)} < "
            f"{t.get('min_placeholder_sample_count', 0)}"
        )

    if summary.get("critical_sample_count", 0) < t.get("min_critical_sample_count", 0):
        failures.append(
            "critical sample count too low: "
            f"{summary.get('critical_sample_count', 0)} < "
            f"{t.get('min_critical_sample_count', 0)}"
        )

    if summary["high_risk_aggressive_violation_rate"] > t["max_aggressive_action_rate_for_high_risk"]:
        failures.append(
            f"高风险激进建议违规率: "
            f"{summary['high_risk_aggressive_violation_rate']} > "
            f"{t['max_aggressive_action_rate_for_high_risk']}"
        )

    placeholder_rate = summary.get("placeholder_guard_hit_rate")
    if placeholder_rate is None and t["min_placeholder_guard_hit_rate"] > 0:
        failures.append("placeholder 保护器命中率不可计算：没有对应样本")
    elif placeholder_rate is not None and placeholder_rate < t["min_placeholder_guard_hit_rate"]:
        failures.append(
            f"placeholder 保护器命中率: "
            f"{placeholder_rate} < "
            f"{t['min_placeholder_guard_hit_rate']}"
        )

    critical_rate = summary.get("critical_guard_hit_rate")
    if critical_rate is None and t["min_critical_guard_hit_rate"] > 0:
        failures.append("critical 保护器命中率不可计算：没有对应样本")
    elif critical_rate is not None and critical_rate < t["min_critical_guard_hit_rate"]:
        failures.append(
            f"critical 保护器命中率: "
            f"{critical_rate} < "
            f"{t['min_critical_guard_hit_rate']}"
        )

    if summary["industry_percentile_valid_rate"] < t["min_industry_percentile_valid_rate"]:
        failures.append(
            f"行业分位有效率: "
            f"{summary['industry_percentile_valid_rate']} < "
            f"{t['min_industry_percentile_valid_rate']}"
        )

    if summary["max_single_score_bucket_ratio"] > t["max_single_score_bucket_ratio"]:
        failures.append(
            f"单一评分分桶占比过高: "
            f"{summary['max_single_score_bucket_ratio']} > "
            f"{t['max_single_score_bucket_ratio']}"
        )

    if summary["rating_bucket_count"] < t["min_rating_bucket_count"]:
        failures.append(
            f"评级分桶数不足: "
            f"{summary['rating_bucket_count']} < {t['min_rating_bucket_count']}"
        )

    if summary["action_bucket_count"] < t["min_action_bucket_count"]:
        failures.append(
            f"动作分桶数不足: "
            f"{summary['action_bucket_count']} < {t['min_action_bucket_count']}"
        )

    # 检查场景覆盖（可跳过）
    if not t.get("skip_required_tag_check"):
        coverage = summary.get("scenario_coverage", {})
        missing_tags = REQUIRED_SCENARIO_TAGS - set(coverage.keys())
        if missing_tags:
            failures.append(f"缺少必需场景标签: {sorted(missing_tags)}")

    # 检查价格来源覆盖率
    min_psc = t.get("min_price_source_coverage", 0.0)
    if min_psc > 0:
        actual_psc = summary.get("price_source_coverage", 0.0)
        if actual_psc < min_psc:
            failures.append(
                f"价格来源覆盖率: "
                f"{actual_psc} < {min_psc}"
            )

    for metric, threshold_key, label in [
        ("fundamental_source_coverage", "min_fundamental_source_coverage", "基本面来源覆盖率"),
        ("valuation_source_coverage", "min_valuation_source_coverage", "估值来源覆盖率"),
        ("industry_source_coverage", "min_industry_source_coverage", "行业来源覆盖率"),
    ]:
        minimum = t.get(threshold_key, 0.0)
        actual = summary.get(metric, 0.0)
        if minimum > 0 and actual < minimum:
            failures.append(f"{label}: {actual} < {minimum}")

    min_complete = t.get("min_data_complete_coverage", 0.0)
    actual_complete = summary.get("data_gap_summary", {}).get(
        "data_complete_coverage", 0.0
    )
    if min_complete > 0 and actual_complete < min_complete:
        failures.append(f"完整研究输入覆盖率: {actual_complete} < {min_complete}")

    if failures:
        failed_ids = [
            s["sample_id"]
            for s in summary.get("scenario_summary", [])
            if not s.get("all_passed")
        ]
        raise AssertionError(
            "历史回测验收失败:\n"
            + "\n".join(f"  - {f}" for f in failures)
            + f"\n失败样本ID: {failed_ids}"
        )
