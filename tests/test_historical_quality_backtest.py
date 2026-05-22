"""P2 Phase 2: 历史回测模块测试。

覆盖：
- load_historical_samples 加载 fixture
- validate_historical_sample schema 校验
- evaluate_historical_sample 评分 + 保护器
- run_historical_backtest 全量运行
- summarize_historical_backtest 分布统计
- assert_historical_backtest_acceptance 阈值校验
- 不能出现永真验收
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.research.historical_quality_backtest import (
    PRICE_ONLY_QMT_ACCEPTANCE_THRESHOLDS,
    REAL_QMT_ACCEPTANCE_THRESHOLDS,
    REQUIRED_SCENARIO_TAGS,
    assert_historical_backtest_acceptance,
    evaluate_historical_sample,
    run_historical_backtest,
    summarize_historical_backtest,
    validate_historical_sample,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "research_quality_historical_samples.json"


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    import json
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def is_real_qmt(fixture_data) -> bool:
    source = fixture_data.get("source", {})
    return source.get("price") == "qmt_xtdata"


@pytest.fixture(scope="module")
def samples(fixture_data) -> list[dict]:
    return fixture_data.get("samples", [])


@pytest.fixture(scope="module")
def backtest_result(samples) -> dict:
    return run_historical_backtest(samples)


@pytest.fixture(scope="module")
def summary(backtest_result) -> dict:
    return summarize_historical_backtest(backtest_result)


# ── 加载 ──────────────────────────────────────────────────────

class TestLoadHistoricalSamples:

    def test_fixture_loads(self, samples):
        assert len(samples) >= 50

    def test_each_sample_has_required_fields(self, samples):
        required = {"sample_id", "symbol", "as_of", "asset_type",
                    "scenario_tags", "input_result", "forward_metrics",
                    "expected", "quality"}
        for s in samples:
            missing = required - set(s.keys())
            assert not missing, f"{s.get('sample_id')}: 缺少 {missing}"


# ── Schema 校验 ───────────────────────────────────────────────

class TestValidateHistoricalSample:

    def test_valid_stock_passes(self, samples):
        stock = next(s for s in samples if s["asset_type"] == "stock")
        errors = validate_historical_sample(stock)
        assert errors == []

    def test_valid_etf_passes(self, samples, is_real_qmt):
        etf_samples = [s for s in samples if s["asset_type"] == "etf"]
        if not etf_samples:
            pytest.skip("当前 fixture 无 ETF 样本（真实 QMT 模式仅含股票）")
        errors = validate_historical_sample(etf_samples[0])
        assert errors == []

    def test_missing_sample_id_fails(self, samples):
        bad = dict(samples[0])
        del bad["sample_id"]
        errors = validate_historical_sample(bad)
        assert any("sample_id" in e for e in errors)

    def test_empty_scenario_tags_fails(self, samples):
        bad = dict(samples[0])
        bad["scenario_tags"] = []
        errors = validate_historical_sample(bad)
        assert any("scenario_tags" in e for e in errors)

    def test_missing_forward_metrics_fails(self, samples):
        bad = dict(samples[0])
        del bad["forward_metrics"]
        errors = validate_historical_sample(bad)
        assert any("forward_metrics" in e for e in errors)

    def test_quality_must_be_real(self, samples):
        bad = dict(samples[0])
        bad["quality"] = {"is_real_historical_sample": False, "data_complete": True}
        errors = validate_historical_sample(bad)
        assert any("is_real_historical_sample" in e for e in errors)

    def test_quality_must_be_complete(self, samples):
        bad = dict(samples[0])
        bad["quality"] = {"is_real_historical_sample": True, "data_complete": False}
        errors = validate_historical_sample(bad)
        # Phase 2B: data_complete=False 不再是校验错误（真实 QMT 样本可能缺少基本面数据）
        # 只检查 is_real_historical_sample 必须为 True
        assert not any("is_real_historical_sample" in e for e in errors)


# ── 评估 ──────────────────────────────────────────────────────

class TestEvaluateHistoricalSample:

    def test_stock_sample_evaluates(self, samples):
        stock = next(s for s in samples if s["asset_type"] == "stock")
        result = evaluate_historical_sample(stock)
        assert "score" in result
        assert "rating" in result
        assert "action" in result
        assert "score_breakdown" in result
        assert "decision_guard" in result

    def test_etf_sample_evaluates(self, samples):
        etf_samples = [s for s in samples if s["asset_type"] == "etf"]
        if not etf_samples:
            pytest.skip("当前 fixture 无 ETF 样本")
        result = evaluate_historical_sample(etf_samples[0])
        assert "score" in result
        assert result["score"] >= 0

    def test_score_in_range(self, samples):
        for s in samples:
            result = evaluate_historical_sample(s)
            assert 0 <= result["score"] <= 100, f"{s['sample_id']}: score={result['score']}"

    def test_all_dimensions_present(self, samples):
        required_dims = {"trend_momentum", "liquidity", "fundamental_quality",
                         "valuation", "risk_control", "event_policy"}
        for s in samples:
            result = evaluate_historical_sample(s)
            dims = set(result["score_breakdown"].keys())
            assert required_dims <= dims, f"{s['sample_id']}: 缺少维度 {required_dims - dims}"

    def test_decision_guard_present(self, samples):
        for s in samples:
            result = evaluate_historical_sample(s)
            assert result["decision_guard"], f"{s['sample_id']}: decision_guard 为空"

    def test_high_quality_low_valuation(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本缺少基本面数据，不适用此测试")
        s = next(x for x in samples if x["sample_id"] == "hist_600519_2024q1_bull")
        result = evaluate_historical_sample(s)
        assert result["score"] >= 70
        assert result["decision_guard"]["final_action"] not in ("回避", "谨慎观察")

    def test_extreme_drawdown_caps_action(self, samples):
        s = next(x for x in samples
                 if "extreme_drawdown" in x.get("scenario_tags", [])
                 and x["asset_type"] == "stock")
        result = evaluate_historical_sample(s)
        from services.research.decision_guard import ACTION_LEVEL
        assert ACTION_LEVEL.get(result["action"], 99) <= ACTION_LEVEL.get("观察", 2)

    def test_loss_making_no_buy(self, samples):
        loss_samples = [x for x in samples
                        if "loss_making_or_invalid_pe" in x.get("scenario_tags", [])]
        assert len(loss_samples) > 0
        for s in loss_samples:
            result = evaluate_historical_sample(s)
            assert result["action"] not in ("分批买入", "买入"), \
                f"{s['sample_id']}: 亏损样本不应有买入动作"


# ── 运行 ──────────────────────────────────────────────────────

class TestRunHistoricalBacktest:

    def test_total_matches_input(self, samples, backtest_result):
        assert backtest_result["total"] == len(samples)

    def test_passed_plus_failed_equals_total(self, backtest_result):
        assert backtest_result["passed"] + backtest_result["failed"] == backtest_result["total"]

    def test_scenario_tags_propagated(self, backtest_result):
        for r in backtest_result["results"]:
            assert "scenario_tags" in r, f"{r.get('sample_id')}: 缺少 scenario_tags"

    def test_forward_metrics_propagated(self, backtest_result):
        for r in backtest_result["results"]:
            assert "forward_metrics" in r, f"{r.get('sample_id')}: 缺少 forward_metrics"


# ── 汇总 ──────────────────────────────────────────────────────

class TestSummarizeHistoricalBacktest:

    def test_summary_structure(self, summary):
        required_keys = {
            "total", "passed", "failed", "pass_rate",
            "scenario_summary", "dimension_stats",
            "score_distribution", "rating_distribution", "action_distribution",
            "scenario_coverage",
            "high_risk_aggressive_violation_count",
            "placeholder_guard_hit_rate", "critical_guard_hit_rate",
            "industry_percentile_valid_rate",
            "max_single_score_bucket_ratio",
            "rating_bucket_count", "action_bucket_count",
            "forward_return_by_score_bucket",
        }
        missing = required_keys - set(summary.keys())
        assert not missing, f"缺少 key: {missing}"

    def test_dimension_stats(self, summary):
        for dim in ["trend_momentum", "liquidity", "fundamental_quality",
                    "valuation", "risk_control", "event_policy"]:
            assert dim in summary["dimension_stats"], f"缺少维度: {dim}"
            stats = summary["dimension_stats"][dim]
            assert "min" in stats and "max" in stats and "avg" in stats

    def test_score_distribution_has_entries(self, summary):
        assert sum(summary["score_distribution"].values()) == summary["total"]

    def test_scenario_coverage(self, summary, is_real_qmt):
        coverage = summary["scenario_coverage"]
        assert len(coverage) > 0
        assert "stock" in coverage
        if not is_real_qmt:
            assert "etf" in coverage


# ── 验收阈值 ──────────────────────────────────────────────────

class TestAssertHistoricalAcceptance:

    def test_acceptance_passes(self, summary, is_real_qmt):
        """Default/manual thresholds pass; QMT price-only fixtures use smoke thresholds."""
        if is_real_qmt:
            assert_historical_backtest_acceptance(
                summary,
                PRICE_ONLY_QMT_ACCEPTANCE_THRESHOLDS,
            )
        else:
            assert_historical_backtest_acceptance(summary)

    def test_strict_qmt_acceptance_fails_when_research_inputs_missing(
        self, summary, is_real_qmt
    ):
        if not is_real_qmt:
            pytest.skip("Only applies to QMT fixtures")
        if summary.get("fundamental_source_coverage", 0.0) > 0:
            pytest.skip("Fixture has research inputs available")
        with pytest.raises(AssertionError, match="基本面来源覆盖率"):
            assert_historical_backtest_acceptance(
                summary,
                REAL_QMT_ACCEPTANCE_THRESHOLDS,
            )

    def test_acceptance_fails_on_too_few_samples(self, summary):
        """样本数不足时应失败。"""
        with pytest.raises(AssertionError, match="样本数不足"):
            assert_historical_backtest_acceptance(summary, {"min_samples": 9999})

    def test_acceptance_fails_on_bad_threshold(self, summary):
        """设置不可能的阈值应失败。"""
        with pytest.raises(AssertionError):
            assert_historical_backtest_acceptance(summary, {
                "min_critical_guard_hit_rate": 999.0,
            })

    def test_not_always_passing(self, summary):
        """验证验收不是永真的——设置极高阈值应失败。"""
        with pytest.raises(AssertionError):
            assert_historical_backtest_acceptance(summary, {
                "min_samples": 999999,
                "min_rating_bucket_count": 999,
            })

    def test_required_scenario_tags_checked(self, summary):
        """缺少必需场景标签应失败。"""
        # 通过修改 coverage 来测试
        modified = dict(summary)
        modified["scenario_coverage"] = {"stock": 10}
        with pytest.raises(AssertionError, match="缺少必需场景标签"):
            assert_historical_backtest_acceptance(modified)


# ── 场景覆盖 ──────────────────────────────────────────────────

class TestScenarioCoverage:

    def test_all_required_tags_present(self, summary, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本不强制要求所有场景标签")
        coverage = set(summary["scenario_coverage"].keys())
        missing = REQUIRED_SCENARIO_TAGS - coverage
        assert not missing, f"缺少必需场景标签: {missing}"

    def test_has_stock_and_etf(self, samples, is_real_qmt):
        asset_types = {s["asset_type"] for s in samples}
        assert "stock" in asset_types
        if not is_real_qmt:
            assert "etf" in asset_types

    def test_has_large_cap(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本无市值数据，不标记 large_cap")
        tags = set()
        for s in samples:
            tags.update(s.get("scenario_tags", []))
        assert "large_cap" in tags

    def test_has_loss_making(self, samples):
        tags = set()
        for s in samples:
            tags.update(s.get("scenario_tags", []))
        assert "loss_making_or_invalid_pe" in tags

    def test_has_extreme_drawdown(self, samples):
        tags = set()
        for s in samples:
            tags.update(s.get("scenario_tags", []))
        assert "extreme_drawdown" in tags


# ── Forward Metrics ───────────────────────────────────────────

class TestForwardMetrics:

    def test_all_samples_have_forward_metrics(self, samples):
        for s in samples:
            fm = s.get("forward_metrics", {})
            for key in ("return_20d", "return_60d", "max_drawdown_20d", "max_drawdown_60d"):
                assert key in fm, f"{s['sample_id']}: forward_metrics 缺少 {key}"

    def test_all_samples_have_return_120d(self, samples):
        for s in samples:
            fm = s.get("forward_metrics", {})
            assert "return_120d" in fm, f"{s['sample_id']}: forward_metrics 缺少 return_120d"
            assert "max_drawdown_120d" in fm, f"{s['sample_id']}: forward_metrics 缺少 max_drawdown_120d"
            assert "benchmark_return_120d" in fm, f"{s['sample_id']}: forward_metrics 缺少 benchmark_return_120d"

    def test_forward_return_buckets_exist(self, summary):
        buckets = summary.get("forward_return_by_score_bucket", {})
        assert len(buckets) > 0
        for _bucket, data in buckets.items():
            assert "count" in data
            assert "avg_return_20d" in data

    def test_forward_return_buckets_have_120d(self, summary):
        buckets = summary.get("forward_return_by_score_bucket", {})
        for _bucket, data in buckets.items():
            assert "avg_return_120d" in data, f"bucket {_bucket} 缺少 avg_return_120d"
            assert "avg_benchmark_return_120d" in data, f"bucket {_bucket} 缺少 avg_benchmark_return_120d"
            assert "avg_max_drawdown_120d" in data, f"bucket {_bucket} 缺少 avg_max_drawdown_120d"


# ── Phase 2B 新增汇总字段 ──────────────────────────────────────

class TestPhase2BSummaryFields:

    def test_has_max_drawdown_by_action_bucket(self, summary):
        assert "max_drawdown_by_action_bucket" in summary
        dda = summary["max_drawdown_by_action_bucket"]
        assert len(dda) > 0

    def test_has_max_drawdown_by_rating_bucket(self, summary):
        assert "max_drawdown_by_rating_bucket" in summary
        ddr = summary["max_drawdown_by_rating_bucket"]
        assert len(ddr) > 0

    def test_has_year_coverage(self, summary):
        assert "year_coverage" in summary
        yc = summary["year_coverage"]
        assert len(yc) > 0

    def test_has_market_cap_coverage(self, summary):
        assert "market_cap_coverage" in summary
        mc = summary["market_cap_coverage"]
        assert "large_cap" in mc
        assert "small_or_mid_cap" in mc

    def test_has_price_source_coverage(self, summary):
        assert "price_source_coverage" in summary
        psc = summary["price_source_coverage"]
        assert 0.0 <= psc <= 1.0

    def test_has_research_source_coverage(self, summary):
        for key in (
            "fundamental_source_coverage",
            "valuation_source_coverage",
            "industry_source_coverage",
        ):
            assert key in summary
            assert 0.0 <= summary[key] <= 1.0

    def test_guard_sample_counts_are_reported(self, summary):
        assert "placeholder_sample_count" in summary
        assert "critical_sample_count" in summary

    def test_has_data_gap_summary(self, summary):
        assert "data_gap_summary" in summary
        dg = summary["data_gap_summary"]
        assert "total_with_blocking_issues" in dg
        assert "data_complete_count" in dg
        assert "data_complete_coverage" in dg
