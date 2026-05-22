"""研究质量回测与压力测试。

覆盖：
- backtest fixture 加载成功。
- 每个 backtest sample 可执行评分和决策保护器。
- critical/placeholder/blocking 样本不得给出激进建议。
- 高质量样本评分高于压力样本。
- ETF 样本不因缺少股票 fundamental/valuation 失败。
- backtest summary 可写 JSON/Markdown artifact。
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from services.research.decision_guard import ACTION_LEVEL
from services.research.quality_backtest import (
    assert_backtest_acceptance,
    evaluate_backtest_sample,
    load_backtest_samples,
    run_backtest,
    summarize_backtest,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "research_quality_backtest_samples.json"


class TestLoadBacktestSamples:

    def test_load_fixture(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        assert len(samples) == 8

    def test_each_sample_has_required_fields(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        for s in samples:
            assert "sample_id" in s
            assert "symbol" in s
            assert "scenario" in s
            assert "input_result" in s
            assert "expected" in s


class TestEvaluateBacktestSample:

    def test_high_quality_low_valuation(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "high_quality_low_valuation")
        result = evaluate_backtest_sample(sample)
        assert result["score"] >= 70
        assert result["decision_guard"]["final_action"] not in ["回避", "谨慎观察"]

    def test_high_valuation_strong_trend(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "high_valuation_strong_trend")
        result = evaluate_backtest_sample(sample)
        assert result["score"] <= 90

    def test_large_drawdown_high_volatility(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "large_drawdown_high_volatility")
        result = evaluate_backtest_sample(sample)
        action = result["decision_guard"]["final_action"]
        assert ACTION_LEVEL.get(action, 0) <= ACTION_LEVEL.get("观察", 2)

    def test_loss_making_invalid_pe(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "loss_making_invalid_pe")
        result = evaluate_backtest_sample(sample)
        assert result["action"] not in ["买入", "分批买入"]

    def test_industry_insufficient_peers(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "industry_insufficient_peers")
        result = evaluate_backtest_sample(sample)
        # 应能正常评分而不报错
        assert 0 <= result["score"] <= 100
        assert all(c["passed"] for c in result["checks"])

    def test_industry_missing_requires_warning_or_reason(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "industry_insufficient_peers")
        sample = json.loads(json.dumps(sample, ensure_ascii=False))
        vd = sample["input_result"]["valuation_data"]
        vd.pop("industry_valuation_warnings", None)
        for metric in ["pe", "pb", "ps"]:
            vd.pop(f"industry_{metric}_percentile_missing_reason", None)

        result = evaluate_backtest_sample(sample)
        check = next(c for c in result["checks"] if c["name"] == "industry_missing_handled")
        assert check["passed"] is False

    def test_forward_return_expectations_are_checked(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "high_quality_low_valuation")
        result = evaluate_backtest_sample(sample)
        assert result["forward_return_60d"] == sample["forward_return_60d"]
        check = next(c for c in result["checks"] if c["name"] == "min_forward_return_60d_check")
        assert check["passed"] is True

    def test_forward_return_expectation_can_fail(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "high_quality_low_valuation")
        sample = json.loads(json.dumps(sample, ensure_ascii=False))
        sample["forward_return_60d"] = -0.2
        result = evaluate_backtest_sample(sample)
        check = next(c for c in result["checks"] if c["name"] == "min_forward_return_60d_check")
        assert check["passed"] is False

    def test_critical_event(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "critical_event")
        result = evaluate_backtest_sample(sample)
        # critical 事件必须限制到回避
        assert result["decision_guard"]["final_action"] == "回避"
        reasons = " ".join(result["decision_guard"].get("guard_reasons", []))
        assert "critical" in reasons

    def test_placeholder_blocking(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "placeholder_blocking")
        result = evaluate_backtest_sample(sample)
        from services.research.decision_guard import ACTION_LEVEL
        action_level = ACTION_LEVEL.get(result["action"], 0)
        assert action_level <= ACTION_LEVEL.get("观察", 2), (
            f"placeholder/blocking sample action={result['action']} should be <= 观察"
        )

    def test_etf_no_fundamental(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        sample = next(s for s in samples if s["sample_id"] == "etf_no_fundamental")
        result = evaluate_backtest_sample(sample)
        assert result["score"] >= 50
        assert "error" not in result


class TestRunBacktest:

    def test_run_all_samples(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        assert result["total"] == 8
        assert result["passed"] + result["failed"] == 8

    def test_high_quality_scores_higher_than_stress(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        by_id = {r["sample_id"]: r for r in result["results"]}
        hq = by_id["high_quality_low_valuation"]["score"]
        stress = by_id["large_drawdown_high_volatility"]["score"]
        assert hq > stress


class TestSummarizeBacktest:

    def test_summary_structure(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        summary = summarize_backtest(result)
        assert "total" in summary
        assert "passed" in summary
        assert "failed" in summary
        assert "pass_rate" in summary
        assert "scenario_summary" in summary
        assert "dimension_stats" in summary

    def test_dimension_stats(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        summary = summarize_backtest(result)
        ds = summary["dimension_stats"]
        assert "trend_momentum" in ds
        assert "risk_control" in ds
        assert "min" in ds["trend_momentum"]
        assert "max" in ds["trend_momentum"]


class TestAssertBacktestAcceptance:

    def test_acceptance_passes(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        summary = summarize_backtest(result)
        # 应该全部通过
        assert_backtest_acceptance(summary)

    def test_acceptance_fails_on_bad_sample(self):
        # 构造一个必定失败的样本
        bad_sample = {
            "sample_id": "bad",
            "symbol": "TEST",
            "scenario": "bad",
            "input_result": {
                "asset_type": "stock",
                "price_data": {"change_20d": 0, "change_60d": 0,
                               "ma20_position": "below", "ma60_position": "below",
                               "avg_turnover_20d": 100, "max_drawdown_60d": 0,
                               "volatility_60d": 0},
                "event_data": {"recent_news_sentiment": "neutral",
                               "policy_risk": "medium",
                               "event_summary": {}, "events": []},
                "source_metadata": {},
            },
            "expected": {"max_action": "回避", "min_score": 99},
        }
        result = run_backtest([bad_sample])
        summary = summarize_backtest(result)
        with pytest.raises(AssertionError, match="回测验收失败"):
            assert_backtest_acceptance(summary)


class TestArtifactGeneration:

    def test_json_artifact(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        summary = summarize_backtest(result)
        path = os.path.join(tempfile.gettempdir(), "backtest_test_artifact.json")
        try:
            Path(path).write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
            assert loaded["total"] == 8
        finally:
            Path(path).unlink(missing_ok=True)

    def test_markdown_artifact(self):
        samples = load_backtest_samples(FIXTURE_PATH)
        result = run_backtest(samples)
        summary = summarize_backtest(result)
        lines = ["# 研究质量回测报告", ""]
        lines.append(f"总样本: {summary['total']}, 通过: {summary['passed']}, "
                     f"失败: {summary['failed']}, 通过率: {summary['pass_rate']:.1%}")
        lines.append("")
        lines.append("## 场景汇总")
        lines.append("| 样本 | 场景 | 评分 | 评级 | 建议 | 结果 |")
        lines.append("|---|---|---:|---|---|---|")
        for s in summary["scenario_summary"]:
            status = "PASS" if s["all_passed"] else "FAIL"
            lines.append(f"| {s['sample_id']} | {s['scenario']} | {s['score']} | "
                         f"{s['rating']} | {s['action']} | {status} |")
        md = "\n".join(lines)
        assert "研究质量回测报告" in md
        assert "高质量低估值" in md
