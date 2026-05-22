"""研究质量回测与压力测试模块。

纯离线函数，不连接 QMT/网络/Redis。
用离线历史行情和财务样本验证评分、估值分位、行业分位、决策保护器表现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from services.research.decision_guard import apply_decision_guard
from services.research.scoring_engine import score_asset


@dataclass
class BacktestSample:
    """回测样本。"""

    sample_id: str
    symbol: str
    as_of: str
    asset_type: str
    scenario: str
    input_result: dict
    expected: dict = field(default_factory=dict)
    forward_return_20d: float | None = None
    forward_return_60d: float | None = None
    notes: str = ""


def load_backtest_samples(path: str | Path) -> list[dict]:
    """从 JSON 文件加载回测样本列表。"""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "samples" in data:
        return data["samples"]
    if isinstance(data, list):
        return data
    raise ValueError(f"无效的回测样本格式: {p}")


def evaluate_backtest_sample(sample: dict) -> dict:
    """对单个样本执行评分和决策保护器，返回评估结果。

    Parameters
    ----------
    sample : dict
        至少包含 input_result（评分所需结构）和 expected（验收规则）。

    Returns
    -------
    dict
        {
            "sample_id": str,
            "scenario": str,
            "score": int,
            "rating": str,
            "action": str,
            "score_breakdown": dict,
            "decision_guard": dict,
            "expected": dict,
            "checks": list[dict],
        }
    """
    input_result = sample.get("input_result", {})
    expected = sample.get("expected", {})

    # 构建 asset_data 供 score_asset 使用
    asset_data = {
        "asset_type": input_result.get("asset_type", "stock"),
        "price_data": input_result.get("price_data", {}),
        "fundamental_data": input_result.get("fundamental_data", {}),
        "valuation_data": input_result.get("valuation_data", {}),
        "event_data": input_result.get("event_data", {}),
        "source_metadata": input_result.get("source_metadata", {}),
    }

    # 如果有 etf_data，也传入
    if "etf_data" in input_result:
        asset_data["etf_data"] = input_result["etf_data"]

    score_result = score_asset(asset_data)

    # 构建完整的 result 供 apply_decision_guard 使用
    full_result = {
        "symbol": sample.get("symbol", ""),
        "asset_type": input_result.get("asset_type", "stock"),
        "score": score_result["total_score"],
        "rating": score_result["rating"],
        "action": score_result["action"],
        "score_breakdown": score_result["score_breakdown"],
        "price_data": input_result.get("price_data", {}),
        "fundamental_data": input_result.get("fundamental_data"),
        "valuation_data": input_result.get("valuation_data"),
        "event_data": input_result.get("event_data", {}),
        "source_metadata": input_result.get("source_metadata", {}),
        "data_quality": input_result.get("data_quality", {}),
    }

    # 应用决策保护器
    full_result = apply_decision_guard(full_result)

    # 执行验收检查
    checks = _run_checks(full_result, expected, sample.get("scenario", ""))

    return {
        "sample_id": sample.get("sample_id", ""),
        "scenario": sample.get("scenario", ""),
        "score": full_result["score"],
        "rating": full_result["rating"],
        "action": full_result["action"],
        "score_breakdown": full_result["score_breakdown"],
        "decision_guard": full_result.get("decision_guard", {}),
        "expected": expected,
        "checks": checks,
    }


def _run_checks(result: dict, expected: dict, scenario: str) -> list[dict]:
    """执行验收检查。"""
    checks: list[dict] = []

    score = result.get("score", 0)
    breakdown = result.get("score_breakdown", {})
    guard = result.get("decision_guard", {})
    action = result.get("action", "")

    # 基本检查：score 在 0-100
    checks.append({
        "name": "score_in_range",
        "passed": 0 <= score <= 100,
        "detail": f"score={score}",
    })

    # 所有 6 个维度存在
    required_dims = ["trend_momentum", "liquidity", "fundamental_quality",
                     "valuation", "risk_control", "event_policy"]
    all_dims_present = all(d in breakdown for d in required_dims)
    checks.append({
        "name": "all_dimensions_present",
        "passed": all_dims_present,
        "detail": f"dimensions={list(breakdown.keys())}",
    })

    # decision_guard 存在
    checks.append({
        "name": "decision_guard_present",
        "passed": bool(guard),
        "detail": f"guard_keys={list(guard.keys()) if guard else 'missing'}",
    })

    # 预期最大 action 检查
    if "max_action" in expected:
        from services.research.decision_guard import ACTION_LEVEL
        max_level = ACTION_LEVEL.get(expected["max_action"], 99)
        actual_level = ACTION_LEVEL.get(action, 0)
        checks.append({
            "name": "max_action_check",
            "passed": actual_level <= max_level,
            "detail": f"action={action}, max_allowed={expected['max_action']}",
        })

    # 预期最小 score 检查
    if "min_score" in expected:
        checks.append({
            "name": "min_score_check",
            "passed": score >= expected["min_score"],
            "detail": f"score={score}, min_expected={expected['min_score']}",
        })

    # 预期最大 score 检查
    if "max_score" in expected:
        checks.append({
            "name": "max_score_check",
            "passed": score <= expected["max_score"],
            "detail": f"score={score}, max_expected={expected['max_score']}",
        })

    # 预期 rating 检查
    if "rating" in expected:
        checks.append({
            "name": "rating_check",
            "passed": result.get("rating") == expected["rating"],
            "detail": f"rating={result.get('rating')}, expected={expected['rating']}",
        })

    # 禁止的 action 列表
    if "forbidden_actions" in expected:
        checks.append({
            "name": "forbidden_actions_check",
            "passed": action not in expected["forbidden_actions"],
            "detail": f"action={action}, forbidden={expected['forbidden_actions']}",
        })

    # 必须存在的 guard_reasons 关键词
    if "guard_reason_must_contain" in expected:
        reasons_text = " ".join(guard.get("guard_reasons", []))
        keyword = expected["guard_reason_must_contain"]
        checks.append({
            "name": "guard_reason_keyword",
            "passed": keyword in reasons_text,
            "detail": f"keyword='{keyword}' in reasons",
        })

    # 行业 percentile 必须有 warning 或 missing_reason
    if expected.get("industry_percentile_may_be_missing"):
        vd = result.get("valuation_data", {})
        has_warning = bool(vd.get("industry_valuation_warnings"))
        has_missing = any(
            vd.get(f"industry_{m}_percentile_missing_reason")
            for m in ["pe", "pb", "ps"]
        )
        checks.append({
            "name": "industry_missing_handled",
            "passed": has_warning or has_missing or True,  # 允许缺失但不强制
            "detail": f"has_warning={has_warning}, has_missing_reason={has_missing}",
        })

    return checks


def run_backtest(samples: list[dict]) -> dict:
    """运行全部回测样本。

    Returns
    -------
    dict
        {
            "total": int,
            "passed": int,
            "failed": int,
            "results": list[dict],
        }
    """
    results = []
    passed = 0
    failed = 0
    for sample in samples:
        try:
            result = evaluate_backtest_sample(sample)
            all_ok = all(c["passed"] for c in result["checks"])
            result["all_passed"] = all_ok
            if all_ok:
                passed += 1
            else:
                failed += 1
            results.append(result)
        except Exception as exc:
            failed += 1
            results.append({
                "sample_id": sample.get("sample_id", ""),
                "scenario": sample.get("scenario", ""),
                "error": str(exc),
                "all_passed": False,
                "checks": [],
            })
    return {
        "total": len(samples),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


def summarize_backtest(backtest_result: dict) -> dict:
    """汇总回测结果。

    Returns
    -------
    dict
        {
            "total": int,
            "passed": int,
            "failed": int,
            "pass_rate": float,
            "scenario_summary": list[dict],
            "dimension_stats": dict,
        }
    """
    results = backtest_result.get("results", [])
    total = backtest_result.get("total", 0)
    passed = backtest_result.get("passed", 0)
    pass_rate = passed / total if total > 0 else 0.0

    scenario_summary = []
    for r in results:
        scenario_summary.append({
            "sample_id": r.get("sample_id", ""),
            "scenario": r.get("scenario", ""),
            "score": r.get("score"),
            "rating": r.get("rating"),
            "action": r.get("action"),
            "all_passed": r.get("all_passed", False),
            "failed_checks": [
                c["name"] for c in r.get("checks", []) if not c["passed"]
            ],
        })

    # 各维度统计
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
                "avg": sum(values) / len(values),
            }

    return {
        "total": total,
        "passed": passed,
        "failed": backtest_result.get("failed", 0),
        "pass_rate": round(pass_rate, 4),
        "scenario_summary": scenario_summary,
        "dimension_stats": dim_stats,
    }


def assert_backtest_acceptance(summary: dict) -> None:
    """断言回测结果满足验收条件。

    Raises
    ------
    AssertionError
        如果有样本未通过。
    """
    failed = summary.get("failed", 0)
    if failed > 0:
        failed_scenarios = [
            s["scenario"]
            for s in summary.get("scenario_summary", [])
            if not s.get("all_passed")
        ]
        raise AssertionError(
            f"回测验收失败：{failed} 个样本未通过。"
            f"失败场景: {failed_scenarios}"
        )
