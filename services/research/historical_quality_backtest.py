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
    "min_industry_percentile_valid_rate": 0.60,
    "max_single_score_bucket_ratio": 0.70,
    "min_rating_bucket_count": 3,
    "min_action_bucket_count": 3,
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

_REQUIRED_FORWARD_KEYS = {"return_20d", "return_60d",
                          "max_drawdown_20d", "max_drawdown_60d"}

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
        for k in _REQUIRED_QUALITY_KEYS:
            if k not in q:
                errors.append(f"quality 缺少: {k}")
        if q.get("is_real_historical_sample") is not True:
            errors.append("quality.is_real_historical_sample 必须为 true")
        if q.get("data_complete") is not True:
            errors.append("quality.data_complete 必须为 true")

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
        scenario_summary.append({
            "sample_id": r.get("sample_id", ""),
            "scenario": r.get("scenario", ""),
            "scenario_tags": r.get("scenario_tags", []),
            "symbol": r.get("symbol", ""),
            "as_of": r.get("as_of", ""),
            "score": r.get("score"),
            "rating": r.get("rating"),
            "action": r.get("action"),
            "forward_return_20d": r.get("forward_return_20d"),
            "forward_return_60d": r.get("forward_return_60d"),
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
        if "placeholder_data" in tags or "blocking_data_quality" in tags:
            placeholder_total += 1
            guard = r.get("decision_guard", {})
            max_action = guard.get("max_allowed_action", "")
            if ACTION_LEVEL.get(max_action, 99) <= ACTION_LEVEL.get("观察", 2):
                placeholder_guarded += 1

    # ── critical 保护器命中率 ──
    critical_total = 0
    critical_guarded = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        if "critical_event" in tags:
            critical_total += 1
            action = r.get("action", "")
            if action == "回避":
                critical_guarded += 1

    # ── 行业分位有效率 ──
    industry_total = 0
    industry_valid = 0
    for r in results:
        tags = set(r.get("scenario_tags", []))
        if "industry_insufficient_peers" in tags:
            continue
        ir = r.get("input_result", {})
        vd = ir.get("valuation_data", {}) if isinstance(ir, dict) else {}
        if not vd:
            continue
        industry_total += 1
        has_valid = any(
            vd.get(f"industry_{m}_percentile") is not None
            for m in ["pe", "pb", "ps"]
        )
        if has_valid:
            industry_valid += 1

    # ── forward return 分桶表现 ──
    forward_buckets: dict[str, dict] = {}
    for r in results:
        score = r.get("score")
        if score is None:
            continue
        bucket = _score_bucket(score)
        if bucket not in forward_buckets:
            forward_buckets[bucket] = {
                "count": 0, "avg_return_20d": 0.0,
                "avg_return_60d": 0.0, "avg_max_drawdown_20d": 0.0,
            }
        b = forward_buckets[bucket]
        b["count"] += 1
        fm = r.get("forward_metrics", {})
        b["avg_return_20d"] += fm.get("return_20d", 0.0)
        b["avg_return_60d"] += fm.get("return_60d", 0.0)
        b["avg_max_drawdown_20d"] += fm.get("max_drawdown_20d", 0.0)

    for bucket in forward_buckets.values():
        n = bucket["count"]
        if n > 0:
            bucket["avg_return_20d"] = round(bucket["avg_return_20d"] / n, 4)
            bucket["avg_return_60d"] = round(bucket["avg_return_60d"] / n, 4)
            bucket["avg_max_drawdown_20d"] = round(bucket["avg_max_drawdown_20d"] / n, 4)

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
        "placeholder_guard_hit_rate": round(
            placeholder_guarded / placeholder_total, 4
        ) if placeholder_total > 0 else 1.0,
        "critical_guard_hit_rate": round(
            critical_guarded / critical_total, 4
        ) if critical_total > 0 else 1.0,
        "industry_percentile_valid_rate": round(
            industry_valid / industry_total, 4
        ) if industry_total > 0 else 0.0,
        "max_single_score_bucket_ratio": round(max_bucket_ratio, 4),
        "rating_bucket_count": len(rating_dist),
        "action_bucket_count": len(action_dist),
        "forward_return_by_score_bucket": forward_buckets,
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

    if summary["high_risk_aggressive_violation_rate"] > t["max_aggressive_action_rate_for_high_risk"]:
        failures.append(
            f"高风险激进建议违规率: "
            f"{summary['high_risk_aggressive_violation_rate']} > "
            f"{t['max_aggressive_action_rate_for_high_risk']}"
        )

    if summary["placeholder_guard_hit_rate"] < t["min_placeholder_guard_hit_rate"]:
        failures.append(
            f"placeholder 保护器命中率: "
            f"{summary['placeholder_guard_hit_rate']} < "
            f"{t['min_placeholder_guard_hit_rate']}"
        )

    if summary["critical_guard_hit_rate"] < t["min_critical_guard_hit_rate"]:
        failures.append(
            f"critical 保护器命中率: "
            f"{summary['critical_guard_hit_rate']} < "
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

    # 检查场景覆盖
    coverage = summary.get("scenario_coverage", {})
    missing_tags = REQUIRED_SCENARIO_TAGS - set(coverage.keys())
    if missing_tags:
        failures.append(f"缺少必需场景标签: {sorted(missing_tags)}")

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
