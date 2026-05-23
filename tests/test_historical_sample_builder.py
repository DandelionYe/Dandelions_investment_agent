"""Phase 2B: historical_sample_builder 单元测试。

全部离线，不依赖 QMT/网络。
使用 mock pd.Series 模拟历史行情数据。
"""

from __future__ import annotations

import pandas as pd
import pytest

from services.research.historical_sample_builder import (  # noqa: E402
    BOUNDARY_SYMBOLS,
    OUT_OF_SCOPE_EXCEPTION_SYMBOLS,
    build_sample_from_qmt_data,
    compute_forward_metrics,
    compute_price_data,
    infer_scenario_tags,
    is_allowed_by_asset_scope,
    is_boundary_symbol,
    is_mainboard_a,
    is_out_of_scope_exception,
)

# ── 主板过滤 ──────────────────────────────────────────────────

class TestIsMainboardA:

    @pytest.mark.parametrize("symbol", [
        "600519.SH", "601318.SH", "603259.SH", "605000.SH",
    ])
    def test_sh_mainboard(self, symbol):
        assert is_mainboard_a(symbol) is True

    @pytest.mark.parametrize("symbol", [
        "000001.SZ", "001001.SZ", "002001.SZ",
    ])
    def test_sz_mainboard(self, symbol):
        assert is_mainboard_a(symbol) is True

    @pytest.mark.parametrize("symbol", [
        "300001.SZ", "301001.SZ",  # 创业板
        "688001.SH", "689001.SH",  # 科创板
        "830799.BJ", "430047.BJ",  # 北交所
        "510300.SH", "159915.SZ",  # ETF
    ])
    def test_not_mainboard(self, symbol):
        assert is_mainboard_a(symbol) is False

    def test_688646_out_of_scope_exception(self):
        """688646.SH 在 OUT_OF_SCOPE_EXCEPTION_SYMBOLS 中，返回 False。"""
        assert is_mainboard_a("688646.SH") is False
        assert is_out_of_scope_exception("688646.SH") is True


class TestBoundarySymbols:

    def test_boundary_list_length(self):
        assert len(BOUNDARY_SYMBOLS) == 13

    def test_all_boundary_symbols_recognized(self):
        for sym in BOUNDARY_SYMBOLS:
            assert is_boundary_symbol(sym) is True

    def test_non_boundary_not_recognized(self):
        assert is_boundary_symbol("600519.SH") is False

    def test_out_of_scope_exception_set(self):
        assert "688646.SH" in OUT_OF_SCOPE_EXCEPTION_SYMBOLS
        assert len(OUT_OF_SCOPE_EXCEPTION_SYMBOLS) == 1


class TestAssetScope:

    def test_mainboard_scope_allows_mainboard(self):
        assert is_allowed_by_asset_scope("600519.SH", "mainboard-a") is True
        assert is_allowed_by_asset_scope("000001.SZ", "mainboard-a") is True

    def test_mainboard_scope_rejects_non_mainboard(self):
        assert is_allowed_by_asset_scope("300001.SZ", "mainboard-a") is False
        assert is_allowed_by_asset_scope("510300.SH", "mainboard-a") is False

    def test_mainboard_scope_allows_declared_exception(self):
        assert is_allowed_by_asset_scope("688646.SH", "mainboard-a") is True


# ── Forward Metrics 计算 ──────────────────────────────────────

def _make_close_series(
    start_price: float = 100.0,
    days: int = 300,
    daily_return: float = 0.001,
    start_date: str = "2023-01-01",
) -> pd.Series:
    """构造一个模拟日收盘价序列。"""
    dates = pd.bdate_range(start=start_date, periods=days)
    prices = [start_price]
    for _i in range(1, days):
        prices.append(prices[-1] * (1 + daily_return))
    return pd.Series(prices, index=dates, name="close")


class TestComputeForwardMetrics:

    def test_basic_returns(self):
        """正常情况：有足够 forward 数据。"""
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        as_of = "2023-06-01"
        result = compute_forward_metrics(close, as_of)

        assert result["return_20d"] is not None
        assert result["return_60d"] is not None
        assert result["return_120d"] is not None
        assert result["coverage_gap"] is None
        # 正收益（daily_return > 0）
        assert result["return_20d"] > 0
        assert result["return_60d"] > result["return_20d"]

    def test_insufficient_data_marks_gap(self):
        """数据不足时标记 coverage_gap（不足 20 天 forward 数据）。"""
        # 15 天数据，as_of 在第 5 天，后面只有 10 天，不够 20d
        close = _make_close_series(start_price=100, days=15, daily_return=0.001)
        as_of = "2023-01-06"
        result = compute_forward_metrics(close, as_of)

        assert result["return_20d"] is None
        assert result["coverage_gap"] is not None
        assert "insufficient" in result["coverage_gap"]

    def test_with_benchmark(self):
        """有基准时计算相对收益。"""
        close = _make_close_series(start_price=100, days=300, daily_return=0.002)
        bench = _make_close_series(start_price=100, days=300, daily_return=0.001)
        as_of = "2023-06-01"

        result = compute_forward_metrics(close, as_of, bench)

        assert result["relative_return_20d"] is not None
        # 股票涨得比基准快，相对收益为正
        assert result["relative_return_20d"] > 0

    def test_max_drawdown(self):
        """计算最大回撤。"""
        # 构造先涨后跌的序列
        dates = pd.bdate_range(start="2023-01-01", periods=300)
        prices = [100.0]
        for _i in range(1, 200):
            prices.append(prices[-1] * 1.002)  # 上涨
        for _i in range(200, 300):
            prices.append(prices[-1] * 0.995)  # 下跌
        close = pd.Series(prices, index=dates)

        result = compute_forward_metrics(close, "2023-03-01")

        assert result["max_drawdown_20d"] is not None
        # 回撤应为负值
        assert result["max_drawdown_20d"] <= 0

    def test_as_of_not_found(self):
        """as_of 日期不在数据范围内。"""
        close = _make_close_series(start_price=100, days=300, start_date="2023-01-01")
        result = compute_forward_metrics(close, "2025-01-01")

        assert result["coverage_gap"] is not None

    def test_empty_series(self):
        """空序列。"""
        result = compute_forward_metrics(pd.Series(dtype=float), "2023-06-01")
        assert result["coverage_gap"] == "empty_close_series"


# ── Price Data 计算 ──────────────────────────────────────────

class TestComputePriceData:

    def test_basic_price_data(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        as_of = "2023-06-01"
        result = compute_price_data(close, None, as_of)

        assert "change_20d" in result
        assert "change_60d" in result
        assert "ma20_position" in result
        assert "ma60_position" in result
        assert "volatility_60d" in result
        assert "max_drawdown_60d" in result
        assert result["data_vendor"] == "qmt_xtdata"

    def test_change_sign(self):
        """上涨序列的 change_20d 应为正。"""
        close = _make_close_series(start_price=100, days=300, daily_return=0.002)
        result = compute_price_data(close, None, "2023-06-01")
        assert result["change_20d"] > 0

    def test_with_amount(self):
        """有成交额数据时计算 avg_turnover_20d。"""
        close = _make_close_series(start_price=100, days=300)
        dates = close.index
        amount = pd.Series(
            [1e9] * len(dates),
            index=dates,
            name="amount",
        )
        result = compute_price_data(close, amount, "2023-06-01")
        assert result["avg_turnover_20d"] == pytest.approx(1e9)

    def test_insufficient_data_returns_empty(self):
        """数据不足 61 天时返回空。"""
        close = _make_close_series(start_price=100, days=30)
        result = compute_price_data(close, None, "2023-02-01")
        assert result == {}


# ── 场景标签推断 ──────────────────────────────────────────────

class TestInferScenarioTags:

    def test_large_cap_stock(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.05}
        fund = {"roe": 0.15}
        val = {"pe_ttm": 20.0, "market_cap": 2e11}
        tags = infer_scenario_tags("600519.SH", price, fund, val)
        assert "stock" in tags
        assert "large_cap" in tags
        assert "mainboard" in tags

    def test_small_cap_stock(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.05}
        fund = {"roe": 0.10}
        val = {"pe_ttm": 30.0, "market_cap": 5e10}
        tags = infer_scenario_tags("002594.SZ", price, fund, val)
        assert "small_or_mid_cap" in tags

    def test_high_volatility(self):
        price = {"volatility_60d": 0.35, "max_drawdown_60d": -0.05}
        tags = infer_scenario_tags("600519.SH", price, None, None)
        assert "high_volatility" in tags

    def test_extreme_drawdown(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.25}
        tags = infer_scenario_tags("600519.SH", price, None, None)
        assert "extreme_drawdown" in tags

    def test_loss_making(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.05}
        fund = {"roe": -0.05}
        tags = infer_scenario_tags("600519.SH", price, fund, None)
        assert "loss_making_or_invalid_pe" in tags

    def test_missing_fundamental(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.05}
        tags = infer_scenario_tags("600519.SH", price, None, None)
        assert "missing_fundamental" in tags

    def test_out_of_scope_exception(self):
        price = {"volatility_60d": 0.20, "max_drawdown_60d": -0.05}
        tags = infer_scenario_tags("688646.SH", price, None, None)
        assert "out_of_scope_exception" in tags


# ── 样本组装 ──────────────────────────────────────────────────

class TestBuildSampleFromQmtData:

    def test_basic_sample_structure(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        sample = build_sample_from_qmt_data(
            sample_id="test_001",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=None,
            industry_data=None,
        )

        assert sample["sample_id"] == "test_001"
        assert sample["symbol"] == "600519.SH"
        assert sample["asset_type"] == "stock"
        assert sample["as_of"] == "2023-06-01"
        assert isinstance(sample["scenario_tags"], list)
        assert "input_result" in sample
        assert "forward_metrics" in sample
        assert "quality" in sample

    def test_source_provenance(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        sample = build_sample_from_qmt_data(
            sample_id="test_002",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=None,
            industry_data=None,
            fundamental_source="local_csmar_eva_structure",
            valuation_source="local_csmar_daily_derived",
            industry_source="local_csmar_industry",
        )

        sm = sample["input_result"]["source_metadata"]
        assert sm["price_source"] == "qmt_xtdata"
        assert sm["as_of"] == "2023-06-01"
        assert sm["symbol"] == "600519.SH"
        assert sm["fundamental_source"] == "missing"
        assert sm["capital_structure_source"] == "missing"
        assert sm["valuation_source"] == "missing"

    def test_forward_metrics_computed(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        sample = build_sample_from_qmt_data(
            sample_id="test_003",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=None,
            industry_data=None,
        )

        fm = sample["forward_metrics"]
        assert fm["return_20d"] is not None
        assert fm["return_60d"] is not None
        assert fm["return_120d"] is not None
        assert fm["max_drawdown_20d"] is not None

    def test_quality_flags(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        sample = build_sample_from_qmt_data(
            sample_id="test_004",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=None,
            industry_data=None,
        )

        assert sample["quality"]["is_real_historical_sample"] is True
        # data_complete 可能因缺少 fundamental 而为 False
        assert isinstance(sample["quality"]["data_complete"], bool)

    def test_with_fundamental_data(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        fund = {"roe": 0.15, "gross_margin": 0.40, "net_profit_growth": 0.10, "debt_ratio": 0.50}
        val = {"pe_ttm": 20.0, "pb_mrq": 3.0, "ps_ttm": 5.0,
               "pe_percentile": 0.30, "pb_percentile": 0.25, "ps_percentile": 0.28,
               "market_cap": 2e11}
        ind = {"level": "SW1", "name": "食品饮料", "peer_count": 80,
               "valid_peer_count_pe": 65, "valid_peer_count_pb": 68,
               "valid_peer_count_ps": 60}

        sample = build_sample_from_qmt_data(
            sample_id="test_005",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=fund,
            valuation_data=val,
            industry_data=ind,
            fundamental_source="local_csmar_eva_structure",
            valuation_source="local_csmar_daily_derived",
            industry_source="local_csmar_industry",
            industry_strict=True,
        )

        assert sample["quality"]["data_complete"] is True
        assert sample["input_result"]["source_metadata"]["fundamental_source"] == "local_csmar_eva_structure"

    def test_out_of_scope_exception_flagged(self):
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        sample = build_sample_from_qmt_data(
            sample_id="test_006",
            symbol="688646.SH",
            name="逸飞激光",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=None,
            industry_data=None,
        )

        assert "out_of_scope_exception" in sample["scenario_tags"]
        assert any("out_of_scope_exception" in lim
                    for lim in sample["quality"]["known_limitations"])


# ── 日期生成 ──────────────────────────────────────────────────

class TestGenerateAsOfDates:

    def test_generates_dates_for_year_range(self):
        from services.research.historical_sample_builder import generate_as_of_dates
        dates = generate_as_of_dates(2021, 2023)
        assert len(dates) > 0
        assert any("2021" in d for d in dates)
        assert any("2023" in d for d in dates)
        # 每年 6 个日期
        assert len(dates) == 3 * 6

    def test_date_format(self):
        from services.research.historical_sample_builder import generate_as_of_dates
        dates = generate_as_of_dates(2022, 2022)
        for d in dates:
            assert len(d) == 10
            assert d[4] == "-"
            assert d[7] == "-"


# ── Provider as_of 查询 ──────────────────────────────────────────

class TestCSMARDailyDerivedAsOf:

    def test_as_of_returns_historical_data(self):
        """as_of 查询应返回 <= as_of 日期的数据。"""
        from services.data.providers.local_csmar_daily_derived_provider import (
            LocalCSMARDailyDerivedProvider,
        )
        provider = LocalCSMARDailyDerivedProvider()
        result = provider.get_as_of_metrics("600519.SH", "2023-06-30", metrics=["pe", "pb"])
        assert result.metadata.success
        assert result.data.get("pe") is not None or result.data.get("pb") is not None
        # trading_date should be <= as_of
        td = result.data.get("trading_date", "")
        assert td <= "2023-06-30"

    def test_future_date_returns_none(self):
        """未来日期不应返回数据。"""
        from services.data.providers.local_csmar_daily_derived_provider import (
            LocalCSMARDailyDerivedProvider,
        )
        provider = LocalCSMARDailyDerivedProvider()
        result = provider.get_as_of_metrics("600519.SH", "2099-01-01", metrics=["pe"])
        assert result.data.get("pe") is None
        assert "future as_of" in (result.metadata.error or "")


class TestEVAAsOf:

    def test_as_of_returns_historical_data(self):
        """EVA as_of 查询应返回 <= as_of 日期的数据。"""
        from services.data.providers.local_csmar_eva_structure_provider import (
            LocalCSMAREVAStructureProvider,
        )
        provider = LocalCSMAREVAStructureProvider()
        result = provider.get_as_of_share_capital("600519.SH", "2023-06-30")
        assert result.metadata.success
        assert result.data.get("total_volume") is not None or result.data.get("market_cap") is not None
        # end_date should be <= as_of
        ed = result.data.get("as_of", "")
        assert ed <= "2023-06-30"

    def test_future_date_returns_none(self):
        """未来日期不应返回数据。"""
        from services.data.providers.local_csmar_eva_structure_provider import (
            LocalCSMAREVAStructureProvider,
        )
        provider = LocalCSMAREVAStructureProvider()
        result = provider.get_as_of_share_capital("600519.SH", "2099-01-01")
        assert result.data.get("total_volume") is None
        assert result.data.get("market_cap") is None
        assert "future as_of" in (result.metadata.error or "")


# ── 行业严格/非严格 ──────────────────────────────────────────────

class TestIndustryStrictVsNonStrict:

    def test_industry_non_strict_for_historical_date(self):
        """行业库只有 2026-05-20 快照，历史日期应标记为 non-strict。"""
        from services.research.historical_sample_builder import enrich_industry_from_local
        _, source, is_strict = enrich_industry_from_local("600519.SH", "2023-06-30")
        # Industry snapshot is 2026-05-20, so 2023-06-30 < snapshot → non-strict
        assert is_strict is False
        assert "non_strict" in source

    def test_industry_strict_for_recent_date(self):
        """如果 as_of >= snapshot_date，应标记为 strict。"""
        from services.research.historical_sample_builder import enrich_industry_from_local
        _, source, is_strict = enrich_industry_from_local("600519.SH", "2026-05-20")
        # snapshot_date is 2026-05-20, as_of >= snapshot → strict
        assert is_strict is True
        assert source == "local_csmar_industry"


# ── 样本 source 字段 ────────────────────────────────────────────

class TestSampleSourceFields:

    def test_enriched_sample_has_csmar_eva_sources(self):
        """接入 CSMAR/EVA 后，sample source 不应全是 missing。"""
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        fund = {"total_volume": 1e9, "bps": 50.0}
        val = {"pe_ttm": 25.0, "pb_mrq": 5.0}
        ind = {"level": "SW1", "name": "食品饮料", "peer_count": 80,
               "valid_peer_count_pe": 65, "valid_peer_count_pb": 68,
               "valid_peer_count_ps": 60}

        sample = build_sample_from_qmt_data(
            sample_id="test_enriched",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=fund,
            valuation_data=val,
            industry_data=ind,
            fundamental_source="local_csmar_eva_structure",
            valuation_source="local_csmar_daily_derived",
            industry_source="local_csmar_industry_non_strict",
            industry_strict=False,
        )

        sm = sample["input_result"]["source_metadata"]
        assert sm["fundamental_source"] == "missing"
        assert sm["capital_structure_source"] == "local_csmar_eva_structure"
        assert sm["valuation_source"] == "local_csmar_daily_derived"
        assert sm["industry_source"] == "local_csmar_industry_non_strict"

    def test_non_strict_industry_adds_blocking_issue(self):
        """non-strict 行业应添加 blocking issue。"""
        close = _make_close_series(start_price=100, days=300, daily_return=0.001)
        val = {"pe_ttm": 25.0}
        ind = {"level": "SW1", "name": "食品饮料", "peer_count": 80}

        sample = build_sample_from_qmt_data(
            sample_id="test_non_strict",
            symbol="600519.SH",
            name="贵州茅台",
            as_of="2023-06-01",
            close_series=close,
            amount_series=None,
            benchmark_close=None,
            fundamental_data=None,
            valuation_data=val,
            industry_data=ind,
            industry_source="local_csmar_industry_non_strict",
            industry_strict=False,
        )

        assert "industry_as_of_unverifiable" in sample["input_result"]["data_quality"]["blocking_issues"]
        assert sample["quality"]["data_complete"] is False
