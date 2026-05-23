"""P2 Phase 2: 历史样本 fixture 契约测试。

覆盖：
- fixture 文件格式正确
- 顶层 schema 字段完整
- 每个样本 schema 校验通过
- 样本数 >= 50
- 覆盖必需场景标签
- 数值精度合理
- 不包含非确定性字段
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.research.historical_quality_backtest import (
    REQUIRED_SCENARIO_TAGS,
    validate_historical_sample,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "research_quality_historical_samples.json"


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def is_real_qmt(fixture_data) -> bool:
    source = fixture_data.get("source", {})
    return source.get("price") == "qmt_xtdata"


@pytest.fixture(scope="module")
def samples(fixture_data) -> list[dict]:
    return fixture_data["samples"]


# ── 顶层 Schema ──────────────────────────────────────────────

class TestFixtureSchema:

    def test_has_version(self, fixture_data):
        assert "version" in fixture_data
        assert isinstance(fixture_data["version"], int)

    def test_has_generated_at(self, fixture_data):
        assert "generated_at" in fixture_data
        assert isinstance(fixture_data["generated_at"], str)

    def test_has_source(self, fixture_data):
        assert "source" in fixture_data
        source = fixture_data["source"]
        for key in ("price", "fundamental", "valuation", "industry"):
            assert key in source, f"source 缺少 {key}"

    def test_has_samples(self, fixture_data):
        assert "samples" in fixture_data
        assert isinstance(fixture_data["samples"], list)


# ── 样本数量 ──────────────────────────────────────────────────

class TestSampleCount:

    def test_at_least_50_samples(self, samples):
        assert len(samples) >= 50, f"只有 {len(samples)} 个样本，需要 >= 50"


# ── 样本 Schema 校验 ─────────────────────────────────────────

class TestSampleSchema:

    def test_all_samples_validate(self, samples):
        failures = []
        for s in samples:
            errors = validate_historical_sample(s)
            if errors:
                failures.append(f"{s.get('sample_id', '?')}: {errors}")
        assert not failures, f"{len(failures)} 个样本校验失败:\n" + "\n".join(failures[:10])

    def test_all_samples_have_fixed_as_of(self, samples):
        for s in samples:
            as_of = s.get("as_of", "")
            assert as_of, f"{s.get('sample_id')}: as_of 为空"
            assert len(as_of) == 10, f"{s['sample_id']}: as_of 格式应为 YYYY-MM-DD"

    def test_all_samples_have_forward_metrics(self, samples):
        required_keys = {"return_20d", "return_60d", "max_drawdown_20d", "max_drawdown_60d"}
        for s in samples:
            fm = s.get("forward_metrics", {})
            missing = required_keys - set(fm.keys())
            assert not missing, f"{s['sample_id']}: forward_metrics 缺少 {missing}"

    def test_all_samples_have_return_120d(self, samples):
        for s in samples:
            fm = s.get("forward_metrics", {})
            assert "return_120d" in fm, f"{s['sample_id']}: 缺少 return_120d"
            assert "max_drawdown_120d" in fm, f"{s['sample_id']}: 缺少 max_drawdown_120d"

    def test_all_samples_have_benchmark_returns(self, samples):
        for s in samples:
            fm = s.get("forward_metrics", {})
            for key in (
                "benchmark_return_20d",
                "benchmark_return_60d",
                "benchmark_return_120d",
            ):
                assert key in fm, f"{s['sample_id']}: 缺少 {key}"

    def test_qmt_samples_have_sample_level_source(self, samples, is_real_qmt):
        if not is_real_qmt:
            pytest.skip("Only applies to QMT fixtures")
        for s in samples:
            source = s.get("source")
            assert isinstance(source, dict), f"{s['sample_id']}: 缺少 sample source"
            assert source.get("price") == "qmt_xtdata"

    def test_out_of_scope_exception_flagged(self, samples, is_real_qmt):
        if not is_real_qmt:
            pytest.skip("Only applies to QMT fixtures")
        target = [s for s in samples if s.get("symbol") == "688646.SH"]
        assert len(target) == 1
        sample = target[0]
        assert sample.get("out_of_scope_exception") is True
        assert "out_of_scope_exception" in sample.get("scenario_tags", [])

    def test_quality_flags_set(self, samples, is_real_qmt):
        for s in samples:
            q = s.get("quality", {})
            assert q.get("is_real_historical_sample") is True, \
                f"{s['sample_id']}: is_real_historical_sample 不为 true"
            if not is_real_qmt:
                assert q.get("data_complete") is True, \
                    f"{s['sample_id']}: data_complete 不为 true"


# ── 场景覆盖 ──────────────────────────────────────────────────

class TestScenarioTagCoverage:

    def test_all_required_tags_present(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本不强制要求所有场景标签")
        covered = set()
        for s in samples:
            covered.update(s.get("scenario_tags", []))
        missing = REQUIRED_SCENARIO_TAGS - covered
        assert not missing, f"缺少必需场景标签: {missing}"

    def test_has_stock_samples(self, samples):
        stock = [s for s in samples if s["asset_type"] == "stock"]
        assert len(stock) >= 30, f"股票样本不足: {len(stock)}"

    def test_has_etf_samples(self, samples, is_real_qmt):
        etf = [s for s in samples if s["asset_type"] == "etf"]
        if is_real_qmt:
            pytest.skip("真实 QMT 模式仅含股票样本")
        assert len(etf) >= 5, f"ETF 样本不足: {len(etf)}"

    def test_has_large_cap(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本无市值数据")
        assert any("large_cap" in s.get("scenario_tags", []) for s in samples)

    def test_has_small_or_mid_cap(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本无市值数据")
        assert any("small_or_mid_cap" in s.get("scenario_tags", []) for s in samples)

    def test_has_loss_making(self, samples):
        assert any("loss_making_or_invalid_pe" in s.get("scenario_tags", []) for s in samples)

    def test_has_missing_fundamental(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本接入 EVA 后，fundamental 不再全部缺失")
        assert any("missing_fundamental" in s.get("scenario_tags", []) for s in samples)

    def test_has_industry_insufficient(self, samples, is_real_qmt):
        if is_real_qmt:
            pytest.skip("真实 QMT 样本无行业数据")
        assert any("industry_insufficient_peers" in s.get("scenario_tags", []) for s in samples)

    def test_has_extreme_drawdown(self, samples):
        assert any("extreme_drawdown" in s.get("scenario_tags", []) for s in samples)

    def test_has_earnings_window(self, samples):
        assert any("earnings_window" in s.get("scenario_tags", []) for s in samples)


# ── 数值精度 ──────────────────────────────────────────────────

class TestNumericPrecision:

    def test_score_values_reasonable(self, samples):
        for s in samples:
            ir = s.get("input_result", {})
            pd = ir.get("price_data", {})
            # 波动率应在合理范围
            vol = pd.get("volatility_60d")
            if vol is not None:
                assert -1.0 <= vol <= 5.0, f"{s['sample_id']}: volatility_60d={vol} 异常"

    def test_percentile_values_bounded(self, samples):
        for s in samples:
            ir = s.get("input_result", {})
            vd = ir.get("valuation_data", {})
            for key in ("pe_percentile", "pb_percentile", "ps_percentile"):
                val = vd.get(key)
                if val is not None:
                    assert 0.0 <= val <= 1.0, f"{s['sample_id']}: {key}={val} 超出 [0,1]"

    def test_forward_returns_reasonable(self, samples):
        for s in samples:
            fm = s.get("forward_metrics", {})
            for key in ("return_20d", "return_60d", "return_120d"):
                val = fm.get(key)
                if val is not None:
                    assert -1.0 <= val <= 5.0, f"{s['sample_id']}: {key}={val} 异常"


# ── 确定性 ──────────────────────────────────────────────────

class TestDeterminism:

    def test_no_current_date_dependency(self, samples):
        """样本不应包含当前日期等非确定性值。"""
        for s in samples:
            as_of = s.get("as_of", "")
            # as_of 应该是固定的历史日期，不是 "today"
            assert "today" not in as_of.lower()
            assert "now" not in as_of.lower()

    def test_sample_ids_unique(self, samples):
        ids = [s["sample_id"] for s in samples]
        assert len(ids) == len(set(ids)), "存在重复的 sample_id"

    def test_symbols_valid_format(self, samples):
        for s in samples:
            symbol = s.get("symbol", "")
            assert symbol, f"{s.get('sample_id')}: symbol 为空"
            # 应该是 XX.XX 格式
            assert "." in symbol, f"{s['sample_id']}: symbol 格式异常: {symbol}"
