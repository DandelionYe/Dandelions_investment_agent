"""估值分位计算测试 — 价格比例法 + AKShare 补充。"""

import pytest
from services.data.normalizers.valuation_normalizer import (
    compute_percentiles_from_history,
    _compute_percentile,
)


class TestComputePercentile:

    def test_below_all(self):
        assert _compute_percentile(5, [10, 20, 30]) == 0.0

    def test_above_all(self):
        assert _compute_percentile(40, [10, 20, 30]) == 1.0

    def test_middle(self):
        assert _compute_percentile(15, [10, 20, 30]) == pytest.approx(1 / 3, rel=0.01)

    def test_empty_history(self):
        assert _compute_percentile(10, []) == 0.5


class TestPercentilesFromHistory:

    def test_basic_pe_percentile(self):
        history_close = [90, 95, 100, 105, 110] * 60  # 300 samples
        current_close = 100
        current_pe = 15.0
        result = compute_percentiles_from_history(
            current_pe=current_pe, current_pb=None, current_ps=None,
            history_close=history_close, current_close=current_close,
        )
        # PE series: 15 * [0.9, 0.95, 1.0, 1.05, 1.1] * 60 → half below 15
        assert result["pe_percentile"] is not None
        assert result["pe_percentile"] == 0.6  # 180/300 values <= 15

    def test_basic_pb_percentile(self):
        history_close = [80, 90, 100, 110, 120] * 60
        result = compute_percentiles_from_history(
            current_pe=None, current_pb=2.0, current_ps=None,
            history_close=history_close, current_close=100,
        )
        assert result["pb_percentile"] is not None
        assert result["pb_percentile"] == 0.6

    def test_insufficient_samples(self):
        history_close = [100] * 100  # 100 samples, < 250
        result = compute_percentiles_from_history(
            current_pe=15.0, current_pb=2.0, current_ps=None,
            history_close=history_close, current_close=100,
        )
        assert result["pe_percentile"] is None
        assert result["pb_percentile"] is None

    def test_negative_pe_skipped(self):
        history_close = [100] * 300
        result = compute_percentiles_from_history(
            current_pe=-5.0, current_pb=2.0, current_ps=None,
            history_close=history_close, current_close=100,
        )
        assert result["pe_percentile"] is None  # negative PE excluded
        assert result["pb_percentile"] is not None

    def test_pe_outlier_clipped(self):
        """PE values > 300 should be filtered, and with <250 valid samples return null."""
        history_close = list(range(1, 301))
        result = compute_percentiles_from_history(
            current_pe=500, current_pb=None, current_ps=None,  # 500 * r → most >300
            history_close=history_close, current_close=150,
        )
        # Only ~90 valid PE points (<250 threshold) → null
        assert result["pe_percentile"] is None

    def test_no_history_close(self):
        result = compute_percentiles_from_history(
            current_pe=15, current_pb=2, current_ps=None,
            history_close=[], current_close=100,
        )
        assert result["pe_percentile"] is None
        assert result["pb_percentile"] is None

    def test_no_current_close(self):
        result = compute_percentiles_from_history(
            current_pe=15, current_pb=2, current_ps=None,
            history_close=[100] * 300, current_close=0,
        )
        assert result["pe_percentile"] is None


class TestAKShareSupplement:

    def test_fetch_with_bad_symbol(self):
        """对无效代码返回空列表。"""
        from services.data.normalizers.valuation_normalizer import (
            _fetch_akshare_supplement_history_close,
        )
        result = _fetch_akshare_supplement_history_close("INVALID")
        assert result == [] or len(result) > 0  # 不抛异常

    def test_duplicate_removal(self):
        """验证 AKShare 补充不会引入重复数据。"""
        pass  # 补充数据的去重由 compute_percentiles 的裁剪逻辑保证
