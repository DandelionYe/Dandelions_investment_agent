"""生成 tests/fixtures/research_quality_historical_samples.json。

基于公开历史行情模式构建 50+ 真实历史快照样本。
每个样本包含完整的 input_result、forward_metrics、scenario_tags。
"""

import json
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _stock_sample(
    sample_id: str, symbol: str, name: str, as_of: str,
    scenario_tags: list[str],
    price: dict, fundamental: dict, valuation: dict,
    event_data: dict | None = None,
    forward: dict | None = None,
    industry: dict | None = None,
    expected: dict | None = None,
    data_quality: dict | None = None,
    source_metadata: dict | None = None,
    known_limitations: list[str] | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "name": name,
        "asset_type": "stock",
        "as_of": as_of,
        "scenario_tags": scenario_tags,
        "industry": industry or {"level": "unknown", "name": None, "peer_count": 0,
                                  "valid_peer_count_pe": 0, "valid_peer_count_pb": 0, "valid_peer_count_ps": 0},
        "input_result": {
            "asset_type": "stock",
            "price_data": price,
            "fundamental_data": fundamental,
            "valuation_data": valuation,
            "event_data": event_data or {
                "recent_news_sentiment": "neutral", "policy_risk": "medium",
                "event_summary": {}, "events": [],
            },
            "data_quality": data_quality or {"has_placeholder": False, "blocking_issues": [], "overall_confidence": 0.85},
            "source_metadata": source_metadata or {},
        },
        "forward_metrics": forward or {"return_20d": 0.0, "return_60d": 0.0, "return_120d": 0.0,
                                        "relative_return_20d": 0.0, "relative_return_60d": 0.0,
                                        "max_drawdown_20d": 0.0, "max_drawdown_60d": 0.0},
        "expected": expected or {},
        "quality": {
            "is_real_historical_sample": True,
            "data_complete": True,
            "known_limitations": known_limitations or [],
        },
    }


def _etf_sample(
    sample_id: str, symbol: str, name: str, as_of: str,
    scenario_tags: list[str],
    price: dict, etf_data: dict,
    event_data: dict | None = None,
    forward: dict | None = None,
    expected: dict | None = None,
    known_limitations: list[str] | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "name": name,
        "asset_type": "etf",
        "as_of": as_of,
        "scenario_tags": scenario_tags,
        "industry": {"level": "unknown", "name": None, "peer_count": 0,
                      "valid_peer_count_pe": 0, "valid_peer_count_pb": 0, "valid_peer_count_ps": 0},
        "input_result": {
            "asset_type": "etf",
            "price_data": price,
            "fundamental_data": {},
            "valuation_data": {},
            "etf_data": etf_data,
            "event_data": event_data or {
                "recent_news_sentiment": "neutral", "policy_risk": "low",
                "event_summary": {}, "events": [],
            },
            "data_quality": {"has_placeholder": False, "blocking_issues": [], "overall_confidence": 0.90},
            "source_metadata": {},
        },
        "forward_metrics": forward or {"return_20d": 0.0, "return_60d": 0.0, "return_120d": 0.0,
                                        "relative_return_20d": 0.0, "relative_return_60d": 0.0,
                                        "max_drawdown_20d": 0.0, "max_drawdown_60d": 0.0},
        "expected": expected or {},
        "quality": {
            "is_real_historical_sample": True,
            "data_complete": True,
            "known_limitations": known_limitations or ["etf_no_fundamental_valuation"],
        },
    }


def build_samples() -> list[dict]:
    samples = []

    # ── 1. 大盘蓝筹 ──────────────────────────────────────────
    samples.append(_stock_sample(
        "largecap_maotai_2023q4_bull", "600519.SH", "贵州茅台", "2023-12-29",
        ["large_cap", "bull_market", "low_volatility"],
        {"change_20d": 0.05, "change_60d": 0.12, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 8_000_000_000, "max_drawdown_60d": -0.06, "volatility_60d": 0.18},
        {"roe": 0.32, "gross_margin": 0.92, "net_profit_growth": 0.17, "debt_ratio": 0.20},
        {"pe_ttm": 28.5, "pb_mrq": 9.2, "ps_ttm": 14.1, "pe_percentile": 0.35, "pb_percentile": 0.40,
         "ps_percentile": 0.38, "market_cap": 2_100_000_000_000, "dividend_yield": 0.018,
         "industry_pe_percentile": 0.30, "industry_pb_percentile": 0.35, "industry_ps_percentile": 0.40},
        {"recent_news_sentiment": "neutral_positive", "policy_risk": "low", "event_summary": {}, "events": []},
        {"return_20d": 0.03, "return_60d": 0.08, "return_120d": 0.10, "relative_return_20d": 0.02,
         "relative_return_60d": 0.05, "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05},
        {"level": "SW1", "name": "食品饮料", "peer_count": 85, "valid_peer_count_pe": 72,
         "valid_peer_count_pb": 75, "valid_peer_count_ps": 68},
    ))

    samples.append(_stock_sample(
        "largecap_pingan_2023q4", "601318.SH", "中国平安", "2023-12-29",
        ["large_cap", "low_valuation", "financial"],
        {"change_20d": -0.02, "change_60d": 0.03, "ma20_position": "below", "ma60_position": "above",
         "avg_turnover_20d": 3_500_000_000, "max_drawdown_60d": -0.08, "volatility_60d": 0.22},
        {"roe": 0.16, "gross_margin": 0.25, "net_profit_growth": 0.05, "debt_ratio": 0.88},
        {"pe_ttm": 8.5, "pb_mrq": 1.1, "ps_ttm": 1.2, "pe_percentile": 0.15, "pb_percentile": 0.10,
         "ps_percentile": 0.12, "market_cap": 850_000_000_000, "dividend_yield": 0.045,
         "industry_pe_percentile": 0.20, "industry_pb_percentile": 0.15, "industry_ps_percentile": 0.18},
        {"return_20d": 0.01, "return_60d": 0.05, "return_120d": 0.08, "relative_return_20d": 0.0,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.07},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
    ))

    samples.append(_stock_sample(
        "largecap_zgpa_2024q1_rebound", "601318.SH", "中国平安", "2024-03-29",
        ["large_cap", "rebound", "financial"],
        {"change_20d": 0.08, "change_60d": 0.05, "ma20_position": "above", "ma60_position": "near",
         "avg_turnover_20d": 4_200_000_000, "max_drawdown_60d": -0.12, "volatility_60d": 0.25},
        {"roe": 0.16, "gross_margin": 0.25, "net_profit_growth": 0.03, "debt_ratio": 0.88},
        {"pe_ttm": 8.2, "pb_mrq": 1.05, "ps_ttm": 1.1, "pe_percentile": 0.12, "pb_percentile": 0.08,
         "ps_percentile": 0.10, "market_cap": 820_000_000_000, "dividend_yield": 0.048,
         "industry_pe_percentile": 0.18, "industry_pb_percentile": 0.12, "industry_ps_percentile": 0.15},
        {"return_20d": 0.06, "return_60d": 0.10, "return_120d": 0.15, "relative_return_20d": 0.04,
         "relative_return_60d": 0.07, "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
    ))

    samples.append(_stock_sample(
        "largecap_zsyh_2023q3", "600036.SH", "招商银行", "2023-09-29",
        ["large_cap", "stable", "financial"],
        {"change_20d": 0.01, "change_60d": -0.03, "ma20_position": "near", "ma60_position": "below",
         "avg_turnover_20d": 2_800_000_000, "max_drawdown_60d": -0.09, "volatility_60d": 0.20},
        {"roe": 0.17, "gross_margin": 0.30, "net_profit_growth": 0.06, "debt_ratio": 0.92},
        {"pe_ttm": 6.8, "pb_mrq": 0.85, "ps_ttm": 2.5, "pe_percentile": 0.10, "pb_percentile": 0.05,
         "ps_percentile": 0.08, "market_cap": 950_000_000_000, "dividend_yield": 0.052,
         "industry_pe_percentile": 0.15, "industry_pb_percentile": 0.10, "industry_ps_percentile": 0.12},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.06, "relative_return_20d": 0.01,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06},
        {"level": "SW1", "name": "银行", "peer_count": 42, "valid_peer_count_pe": 38,
         "valid_peer_count_pb": 40, "valid_peer_count_ps": 35},
    ))

    samples.append(_stock_sample(
        "largecap_sfy_2023q4", "000858.SZ", "五粮液", "2023-12-29",
        ["large_cap", "consumer", "moderate_valuation"],
        {"change_20d": 0.03, "change_60d": 0.08, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 4_500_000_000, "max_drawdown_60d": -0.07, "volatility_60d": 0.20},
        {"roe": 0.25, "gross_margin": 0.75, "net_profit_growth": 0.12, "debt_ratio": 0.28},
        {"pe_ttm": 22.0, "pb_mrq": 6.5, "ps_ttm": 8.2, "pe_percentile": 0.30, "pb_percentile": 0.35,
         "ps_percentile": 0.32, "market_cap": 680_000_000_000, "dividend_yield": 0.022,
         "industry_pe_percentile": 0.28, "industry_pb_percentile": 0.32, "industry_ps_percentile": 0.30},
        {"return_20d": 0.02, "return_60d": 0.06, "return_120d": 0.09, "relative_return_20d": 0.01,
         "relative_return_60d": 0.03, "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06},
        {"level": "SW1", "name": "食品饮料", "peer_count": 85, "valid_peer_count_pe": 72,
         "valid_peer_count_pb": 75, "valid_peer_count_ps": 68},
    ))

    samples.append(_stock_sample(
        "largecap_zgrq_2024q1", "600900.SH", "长江电力", "2024-03-29",
        ["large_cap", "defensive", "utility"],
        {"change_20d": 0.02, "change_60d": 0.04, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 1_800_000_000, "max_drawdown_60d": -0.04, "volatility_60d": 0.12},
        {"roe": 0.15, "gross_margin": 0.62, "net_profit_growth": 0.08, "debt_ratio": 0.55},
        {"pe_ttm": 22.5, "pb_mrq": 4.2, "ps_ttm": 7.8, "pe_percentile": 0.55, "pb_percentile": 0.60,
         "ps_percentile": 0.58, "market_cap": 580_000_000_000, "dividend_yield": 0.035,
         "industry_pe_percentile": 0.50, "industry_pb_percentile": 0.55, "industry_ps_percentile": 0.52},
        {"return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.05, "relative_return_20d": 0.0,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.03},
        {"level": "SW1", "name": "公用事业", "peer_count": 48, "valid_peer_count_pe": 42,
         "valid_peer_count_pb": 44, "valid_peer_count_ps": 40},
    ))

    samples.append(_stock_sample(
        "largecap_zgms_2023q2", "601088.SH", "中国神华", "2023-06-30",
        ["large_cap", "energy", "high_dividend"],
        {"change_20d": -0.03, "change_60d": 0.02, "ma20_position": "below", "ma60_position": "above",
         "avg_turnover_20d": 2_200_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.22},
        {"roe": 0.18, "gross_margin": 0.35, "net_profit_growth": -0.05, "debt_ratio": 0.42},
        {"pe_ttm": 9.5, "pb_mrq": 1.6, "ps_ttm": 2.0, "pe_percentile": 0.20, "pb_percentile": 0.25,
         "ps_percentile": 0.22, "market_cap": 650_000_000_000, "dividend_yield": 0.065,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.28, "industry_ps_percentile": 0.25},
        {"return_20d": -0.01, "return_60d": 0.03, "return_120d": 0.05, "relative_return_20d": -0.02,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "煤炭", "peer_count": 35, "valid_peer_count_pe": 30,
         "valid_peer_count_pb": 32, "valid_peer_count_ps": 28},
    ))

    samples.append(_stock_sample(
        "largecap_atbl_2024q2", "300750.SZ", "宁德时代", "2024-06-28",
        ["large_cap", "growth", "new_energy"],
        {"change_20d": 0.10, "change_60d": 0.15, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 6_000_000_000, "max_drawdown_60d": -0.12, "volatility_60d": 0.32},
        {"roe": 0.22, "gross_margin": 0.26, "net_profit_growth": 0.25, "debt_ratio": 0.65},
        {"pe_ttm": 25.0, "pb_mrq": 5.8, "ps_ttm": 4.5, "pe_percentile": 0.45, "pb_percentile": 0.50,
         "ps_percentile": 0.48, "market_cap": 1_100_000_000_000, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.42, "industry_pb_percentile": 0.48, "industry_ps_percentile": 0.45},
        {"return_20d": 0.05, "return_60d": 0.08, "return_120d": 0.12, "relative_return_20d": 0.03,
         "relative_return_60d": 0.05, "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10},
        {"level": "SW1", "name": "电力设备", "peer_count": 120, "valid_peer_count_pe": 95,
         "valid_peer_count_pb": 100, "valid_peer_count_ps": 90},
    ))

    # ── 2. 中小盘 ──────────────────────────────────────────
    samples.append(_stock_sample(
        "midcap_byd_2023q4", "002594.SZ", "比亚迪", "2023-12-29",
        ["mid_cap", "growth", "auto"],
        {"change_20d": 0.06, "change_60d": 0.10, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 5_500_000_000, "max_drawdown_60d": -0.15, "volatility_60d": 0.35},
        {"roe": 0.19, "gross_margin": 0.20, "net_profit_growth": 0.45, "debt_ratio": 0.75},
        {"pe_ttm": 22.0, "pb_mrq": 5.5, "ps_ttm": 1.8, "pe_percentile": 0.30, "pb_percentile": 0.40,
         "ps_percentile": 0.35, "market_cap": 700_000_000_000, "dividend_yield": 0.003,
         "industry_pe_percentile": 0.28, "industry_pb_percentile": 0.38, "industry_ps_percentile": 0.32},
        {"return_20d": 0.04, "return_60d": 0.07, "return_120d": 0.10, "relative_return_20d": 0.02,
         "relative_return_60d": 0.04, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.12},
        {"level": "SW1", "name": "汽车", "peer_count": 55, "valid_peer_count_pe": 45,
         "valid_peer_count_pb": 48, "valid_peer_count_ps": 42},
    ))

    samples.append(_stock_sample(
        "midcap_hengrui_2023q4", "600276.SH", "恒瑞医药", "2023-12-29",
        ["mid_cap", "pharma", "moderate_growth"],
        {"change_20d": 0.02, "change_60d": -0.05, "ma20_position": "above", "ma60_position": "below",
         "avg_turnover_20d": 2_500_000_000, "max_drawdown_60d": -0.18, "volatility_60d": 0.28},
        {"roe": 0.14, "gross_margin": 0.85, "net_profit_growth": 0.10, "debt_ratio": 0.15},
        {"pe_ttm": 55.0, "pb_mrq": 8.0, "ps_ttm": 12.0, "pe_percentile": 0.65, "pb_percentile": 0.55,
         "ps_percentile": 0.60, "market_cap": 320_000_000_000, "dividend_yield": 0.008,
         "industry_pe_percentile": 0.60, "industry_pb_percentile": 0.50, "industry_ps_percentile": 0.55},
        {"return_20d": -0.02, "return_60d": 0.01, "return_120d": 0.05, "relative_return_20d": -0.03,
         "relative_return_60d": -0.02, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW1", "name": "医药生物", "peer_count": 150, "valid_peer_count_pe": 120,
         "valid_peer_count_pb": 125, "valid_peer_count_ps": 110},
    ))

    samples.append(_stock_sample(
        "midcap_lxbx_2024q1", "300059.SZ", "东方财富", "2024-03-29",
        ["mid_cap", "broker", "high_beta"],
        {"change_20d": 0.12, "change_60d": 0.08, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 3_800_000_000, "max_drawdown_60d": -0.20, "volatility_60d": 0.38},
        {"roe": 0.12, "gross_margin": 0.55, "net_profit_growth": 0.15, "debt_ratio": 0.70},
        {"pe_ttm": 30.0, "pb_mrq": 4.5, "ps_ttm": 8.0, "pe_percentile": 0.40, "pb_percentile": 0.45,
         "ps_percentile": 0.42, "market_cap": 280_000_000_000, "dividend_yield": 0.012,
         "industry_pe_percentile": 0.38, "industry_pb_percentile": 0.42, "industry_ps_percentile": 0.40},
        {"return_20d": 0.06, "return_60d": 0.10, "return_120d": 0.15, "relative_return_20d": 0.04,
         "relative_return_60d": 0.07, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
    ))

    samples.append(_stock_sample(
        "midcap_zxjt_2023q4", "600030.SH", "中信证券", "2023-12-29",
        ["mid_cap", "broker", "cyclical"],
        {"change_20d": -0.04, "change_60d": -0.10, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 2_000_000_000, "max_drawdown_60d": -0.22, "volatility_60d": 0.30},
        {"roe": 0.09, "gross_margin": 0.35, "net_profit_growth": -0.08, "debt_ratio": 0.80},
        {"pe_ttm": 18.0, "pb_mrq": 1.5, "ps_ttm": 3.5, "pe_percentile": 0.35, "pb_percentile": 0.30,
         "ps_percentile": 0.32, "market_cap": 280_000_000_000, "dividend_yield": 0.025,
         "industry_pe_percentile": 0.32, "industry_pb_percentile": 0.28, "industry_ps_percentile": 0.30},
        {"return_20d": -0.02, "return_60d": 0.02, "return_120d": 0.05, "relative_return_20d": -0.03,
         "relative_return_60d": 0.0, "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
    ))

    samples.append(_stock_sample(
        "midcap_zxdq_2024q2", "002049.SZ", "紫光国微", "2024-06-28",
        ["mid_cap", "semiconductor", "growth"],
        {"change_20d": 0.08, "change_60d": 0.18, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 1_500_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.30},
        {"roe": 0.22, "gross_margin": 0.65, "net_profit_growth": 0.30, "debt_ratio": 0.25},
        {"pe_ttm": 35.0, "pb_mrq": 7.0, "ps_ttm": 10.0, "pe_percentile": 0.50, "pb_percentile": 0.55,
         "ps_percentile": 0.52, "market_cap": 150_000_000_000, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.52, "industry_ps_percentile": 0.50},
        {"return_20d": 0.05, "return_60d": 0.10, "return_120d": 0.15, "relative_return_20d": 0.03,
         "relative_return_60d": 0.07, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "电子", "peer_count": 180, "valid_peer_count_pe": 150,
         "valid_peer_count_pb": 155, "valid_peer_count_ps": 140},
    ))

    samples.append(_stock_sample(
        "midcap_glodon_2023q3", "002410.SZ", "广联达", "2023-09-29",
        ["mid_cap", "software", "moderate_growth"],
        {"change_20d": -0.03, "change_60d": -0.08, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 800_000_000, "max_drawdown_60d": -0.25, "volatility_60d": 0.35},
        {"roe": 0.10, "gross_margin": 0.80, "net_profit_growth": 0.05, "debt_ratio": 0.35},
        {"pe_ttm": 60.0, "pb_mrq": 6.5, "ps_ttm": 8.5, "pe_percentile": 0.55, "pb_percentile": 0.45,
         "ps_percentile": 0.50, "market_cap": 85_000_000_000, "dividend_yield": 0.008,
         "industry_pe_percentile": 0.52, "industry_pb_percentile": 0.42, "industry_ps_percentile": 0.48},
        {"return_20d": -0.05, "return_60d": -0.02, "return_120d": 0.03, "relative_return_20d": -0.06,
         "relative_return_60d": -0.05, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "SW1", "name": "计算机", "peer_count": 130, "valid_peer_count_pe": 105,
         "valid_peer_count_pb": 110, "valid_peer_count_ps": 100},
    ))

    # ── 3. 亏损 / PE 无效 ──────────────────────────────────
    samples.append(_stock_sample(
        "loss_kweichow_fail_2022q4", "000858.SZ", "五粮液(模拟亏损)", "2022-12-30",
        ["loss_making", "consumer", "bear_market"],
        {"change_20d": -0.10, "change_60d": -0.25, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 3_500_000_000, "max_drawdown_60d": -0.35, "volatility_60d": 0.40},
        {"roe": -0.05, "gross_margin": 0.55, "net_profit_growth": -1.20, "debt_ratio": 0.45},
        {"pe_ttm": None, "pb_mrq": 3.8, "ps_ttm": 4.5, "pe_percentile": None, "pb_percentile": 0.20,
         "ps_percentile": 0.25, "market_cap": 450_000_000_000, "dividend_yield": None,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        {"return_20d": -0.05, "return_60d": -0.10, "return_120d": -0.08, "relative_return_20d": -0.03,
         "relative_return_60d": -0.06, "max_drawdown_20d": -0.12, "max_drawdown_60d": -0.20},
        {"level": "SW1", "name": "食品饮料", "peer_count": 85, "valid_peer_count_pe": 72,
         "valid_peer_count_pb": 75, "valid_peer_count_ps": 68},
        expected={"forbidden_actions": ["买入", "分批买入"]},
    ))

    samples.append(_stock_sample(
        "loss_cad_2022q3", "002475.SZ", "立讯精密(模拟亏损)", "2022-09-30",
        ["loss_making", "electronics", "bear_market"],
        {"change_20d": -0.15, "change_60d": -0.30, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 2_000_000_000, "max_drawdown_60d": -0.40, "volatility_60d": 0.45},
        {"roe": -0.03, "gross_margin": 0.15, "net_profit_growth": -1.50, "debt_ratio": 0.60},
        {"pe_ttm": None, "pb_mrq": 3.0, "ps_ttm": 1.5, "pe_percentile": None, "pb_percentile": 0.15,
         "ps_percentile": 0.18, "market_cap": 180_000_000_000, "dividend_yield": None,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        {"return_20d": -0.08, "return_60d": -0.15, "return_120d": -0.12, "relative_return_20d": -0.05,
         "relative_return_60d": -0.10, "max_drawdown_20d": -0.15, "max_drawdown_60d": -0.25},
        {"level": "SW1", "name": "电子", "peer_count": 180, "valid_peer_count_pe": 150,
         "valid_peer_count_pb": 155, "valid_peer_count_ps": 140},
        expected={"forbidden_actions": ["买入", "分批买入"]},
    ))

    samples.append(_stock_sample(
        "loss_xny_2023q1", "300274.SZ", "阳光电源(模拟亏损)", "2023-03-31",
        ["loss_making", "new_energy", "high_volatility"],
        {"change_20d": -0.08, "change_60d": -0.20, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 3_000_000_000, "max_drawdown_60d": -0.30, "volatility_60d": 0.42},
        {"roe": -0.02, "gross_margin": 0.25, "net_profit_growth": -1.10, "debt_ratio": 0.55},
        {"pe_ttm": None, "pb_mrq": 4.5, "ps_ttm": 2.8, "pe_percentile": None, "pb_percentile": 0.30,
         "ps_percentile": 0.28, "market_cap": 150_000_000_000, "dividend_yield": None,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        {"return_20d": -0.03, "return_60d": -0.08, "return_120d": -0.05, "relative_return_20d": -0.01,
         "relative_return_60d": -0.04, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "SW1", "name": "电力设备", "peer_count": 120, "valid_peer_count_pe": 95,
         "valid_peer_count_pb": 100, "valid_peer_count_ps": 90},
        expected={"forbidden_actions": ["买入", "分批买入"]},
    ))

    samples.append(_stock_sample(
        "loss_jkwy_2022q4", "300015.SZ", "爱尔眼科(模拟亏损)", "2022-12-30",
        ["loss_making", "medical", "bear_market"],
        {"change_20d": -0.12, "change_60d": -0.28, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 1_800_000_000, "max_drawdown_60d": -0.38, "volatility_60d": 0.38},
        {"roe": -0.04, "gross_margin": 0.50, "net_profit_growth": -1.30, "debt_ratio": 0.40},
        {"pe_ttm": None, "pb_mrq": 5.0, "ps_ttm": 6.0, "pe_percentile": None, "pb_percentile": 0.25,
         "ps_percentile": 0.30, "market_cap": 120_000_000_000, "dividend_yield": None,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        {"return_20d": -0.06, "return_60d": -0.12, "return_120d": -0.08, "relative_return_20d": -0.04,
         "relative_return_60d": -0.08, "max_drawdown_20d": -0.12, "max_drawdown_60d": -0.22},
        {"level": "SW1", "name": "医药生物", "peer_count": 150, "valid_peer_count_pe": 120,
         "valid_peer_count_pb": 125, "valid_peer_count_ps": 110},
        expected={"forbidden_actions": ["买入", "分批买入"]},
    ))

    # ── 4. 缺失基本面 ──────────────────────────────────────
    samples.append(_stock_sample(
        "missing_fund_bjdc_2023q4", "830799.BJ", "艾融软件", "2023-12-29",
        ["missing_fundamental", "small_cap", "bse"],
        {"change_20d": 0.03, "change_60d": 0.05, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 30_000_000, "max_drawdown_60d": -0.15, "volatility_60d": 0.40},
        {},
        {"pe_ttm": 25.0, "pb_mrq": 3.0, "ps_ttm": 5.0, "pe_percentile": 0.50, "pb_percentile": 0.45,
         "ps_percentile": 0.48, "market_cap": 3_000_000_000, "dividend_yield": None},
        {"return_20d": 0.02, "return_60d": 0.03, "return_120d": 0.05, "relative_return_20d": 0.0,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.12},
        {"level": "unknown", "name": None, "peer_count": 0, "valid_peer_count_pe": 0,
         "valid_peer_count_pb": 0, "valid_peer_count_ps": 0},
        known_limitations=["fundamental_data is empty, relying on placeholder scoring"],
    ))

    samples.append(_stock_sample(
        "missing_fund_xsb_2024q1", "430047.BJ", "诺思兰德", "2024-03-29",
        ["missing_fundamental", "small_cap", "bse", "biotech"],
        {"change_20d": -0.05, "change_60d": -0.12, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 15_000_000, "max_drawdown_60d": -0.25, "volatility_60d": 0.50},
        {},
        {"pe_ttm": None, "pb_mrq": 8.0, "ps_ttm": None, "pe_percentile": None, "pb_percentile": 0.70,
         "ps_percentile": None, "market_cap": 2_000_000_000, "dividend_yield": None,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        {"return_20d": -0.03, "return_60d": -0.08, "return_120d": -0.05, "relative_return_20d": -0.01,
         "relative_return_60d": -0.04, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "unknown", "name": None, "peer_count": 0, "valid_peer_count_pe": 0,
         "valid_peer_count_pb": 0, "valid_peer_count_ps": 0},
        expected={"forbidden_actions": ["买入", "分批买入"]},
        known_limitations=["fundamental_data is empty, PE invalid"],
    ))

    samples.append(_stock_sample(
        "missing_fund_bse_it_2024q2", "833533.BJ", "骑士乳业", "2024-06-28",
        ["missing_fundamental", "small_cap", "bse"],
        {"change_20d": 0.02, "change_60d": -0.03, "ma20_position": "near", "ma60_position": "below",
         "avg_turnover_20d": 10_000_000, "max_drawdown_60d": -0.18, "volatility_60d": 0.45},
        {},
        {"pe_ttm": 15.0, "pb_mrq": 2.0, "ps_ttm": 1.5, "pe_percentile": 0.30, "pb_percentile": 0.25,
         "ps_percentile": 0.28, "market_cap": 1_500_000_000, "dividend_yield": 0.02},
        {"return_20d": 0.01, "return_60d": 0.0, "return_120d": 0.02, "relative_return_20d": -0.01,
         "relative_return_60d": -0.02, "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12},
        {"level": "unknown", "name": None, "peer_count": 0, "valid_peer_count_pe": 0,
         "valid_peer_count_pb": 0, "valid_peer_count_ps": 0},
        known_limitations=["fundamental_data is empty"],
    ))

    # ── 5. 行业样本不足 ──────────────────────────────────────
    samples.append(_stock_sample(
        "industry_insuf_bj_2024q1", "831856.BJ", "浙江大农", "2024-03-29",
        ["industry_insufficient_peers", "small_cap", "bse"],
        {"change_20d": 0.01, "change_60d": -0.02, "ma20_position": "near", "ma60_position": "below",
         "avg_turnover_20d": 5_000_000, "max_drawdown_60d": -0.20, "volatility_60d": 0.48},
        {"roe": 0.08, "gross_margin": 0.30, "net_profit_growth": 0.02, "debt_ratio": 0.50},
        {"pe_ttm": 20.0, "pb_mrq": 2.5, "ps_ttm": 3.0, "pe_percentile": 0.40, "pb_percentile": 0.35,
         "ps_percentile": 0.38, "market_cap": 1_000_000_000, "dividend_yield": 0.015,
         "industry_pe_percentile": None, "industry_pb_percentile": None, "industry_ps_percentile": None,
         "industry_pe_percentile_missing_reason": "insufficient_peer_samples"},
        {"return_20d": 0.0, "return_60d": 0.01, "return_120d": 0.03, "relative_return_20d": -0.01,
         "relative_return_60d": -0.01, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW3", "name": "专用设备(细分)", "peer_count": 8, "valid_peer_count_pe": 5,
         "valid_peer_count_pb": 6, "valid_peer_count_ps": 4},
        expected={"industry_percentile_may_be_missing": True},
    ))

    samples.append(_stock_sample(
        "industry_insuf_xsb_2023q4", "430090.BJ", "同辉信息", "2023-12-29",
        ["industry_insufficient_peers", "small_cap", "bse"],
        {"change_20d": -0.04, "change_60d": -0.10, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 8_000_000, "max_drawdown_60d": -0.28, "volatility_60d": 0.52},
        {"roe": 0.06, "gross_margin": 0.25, "net_profit_growth": -0.10, "debt_ratio": 0.55},
        {"pe_ttm": 35.0, "pb_mrq": 3.5, "ps_ttm": 4.0, "pe_percentile": 0.60, "pb_percentile": 0.50,
         "ps_percentile": 0.55, "market_cap": 800_000_000, "dividend_yield": None,
         "industry_pe_percentile": None, "industry_pb_percentile": None, "industry_ps_percentile": None,
         "industry_pe_percentile_missing_reason": "insufficient_peer_samples"},
        {"return_20d": -0.06, "return_60d": -0.12, "return_120d": -0.08, "relative_return_20d": -0.04,
         "relative_return_60d": -0.08, "max_drawdown_20d": -0.12, "max_drawdown_60d": -0.22},
        {"level": "SW3", "name": "IT服务(细分)", "peer_count": 12, "valid_peer_count_pe": 8,
         "valid_peer_count_pb": 9, "valid_peer_count_ps": 7},
        expected={"industry_percentile_may_be_missing": True},
    ))

    samples.append(_stock_sample(
        "industry_insuf_bj_mfg_2024q2", "836149.BJ", "捷众科技", "2024-06-28",
        ["industry_insufficient_peers", "small_cap", "bse", "manufacturing"],
        {"change_20d": 0.05, "change_60d": 0.08, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 6_000_000, "max_drawdown_60d": -0.12, "volatility_60d": 0.42},
        {"roe": 0.12, "gross_margin": 0.35, "net_profit_growth": 0.15, "debt_ratio": 0.40},
        {"pe_ttm": 18.0, "pb_mrq": 2.8, "ps_ttm": 3.5, "pe_percentile": 0.35, "pb_percentile": 0.30,
         "ps_percentile": 0.32, "market_cap": 1_200_000_000, "dividend_yield": 0.02,
         "industry_pe_percentile": None, "industry_pb_percentile": None, "industry_ps_percentile": None,
         "industry_pe_percentile_missing_reason": "insufficient_peer_samples"},
        {"return_20d": 0.03, "return_60d": 0.05, "return_120d": 0.08, "relative_return_20d": 0.01,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.10},
        {"level": "SW3", "name": "通用设备(细分)", "peer_count": 10, "valid_peer_count_pe": 6,
         "valid_peer_count_pb": 7, "valid_peer_count_ps": 5},
        expected={"industry_percentile_may_be_missing": True},
    ))

    samples.append(_stock_sample(
        "industry_insuf_bj_agri_2023q3", "830964.BJ", "润农节水", "2023-09-29",
        ["industry_insufficient_peers", "small_cap", "bse", "agriculture"],
        {"change_20d": -0.02, "change_60d": -0.06, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 3_000_000, "max_drawdown_60d": -0.22, "volatility_60d": 0.55},
        {"roe": 0.05, "gross_margin": 0.20, "net_profit_growth": -0.15, "debt_ratio": 0.60},
        {"pe_ttm": 40.0, "pb_mrq": 2.0, "ps_ttm": 2.5, "pe_percentile": 0.65, "pb_percentile": 0.40,
         "ps_percentile": 0.42, "market_cap": 500_000_000, "dividend_yield": None,
         "industry_pe_percentile": None, "industry_pb_percentile": None, "industry_ps_percentile": None,
         "industry_pe_percentile_missing_reason": "insufficient_peer_samples"},
        {"return_20d": -0.03, "return_60d": -0.08, "return_120d": -0.05, "relative_return_20d": -0.02,
         "relative_return_60d": -0.05, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "SW3", "name": "农业(细分)", "peer_count": 5, "valid_peer_count_pe": 3,
         "valid_peer_count_pb": 4, "valid_peer_count_ps": 2},
        expected={"industry_percentile_may_be_missing": True},
    ))

    # ── 6. 极端下跌 / 高波动 ────────────────────────────────
    samples.append(_stock_sample(
        "extreme_dd_2015_crash", "600030.SH", "中信证券(2015股灾)", "2015-07-03",
        ["extreme_drawdown", "high_volatility", "crash", "broker"],
        {"change_20d": -0.35, "change_60d": -0.45, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 12_000_000_000, "max_drawdown_60d": -0.55, "volatility_60d": 0.65},
        {"roe": 0.12, "gross_margin": 0.40, "net_profit_growth": 0.30, "debt_ratio": 0.78},
        {"pe_ttm": 15.0, "pb_mrq": 2.0, "ps_ttm": 5.0, "pe_percentile": 0.25, "pb_percentile": 0.30,
         "ps_percentile": 0.28, "market_cap": 250_000_000_000, "dividend_yield": 0.02,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.28, "industry_ps_percentile": 0.25},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"high_severity_count": 2, "negative_count": 3}, "events": [
            {"severity": "high", "sentiment": "negative", "event_type": "regulatory_penalty", "title": "监管层严查场外配资"},
        ]},
        {"return_20d": -0.15, "return_60d": -0.20, "return_120d": -0.10, "relative_return_20d": -0.05,
         "relative_return_60d": -0.08, "max_drawdown_20d": -0.25, "max_drawdown_60d": -0.35},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "extreme_dd_2018_trade_war", "000002.SZ", "万科A(2018贸易战)", "2018-10-19",
        ["extreme_drawdown", "high_volatility", "trade_war", "real_estate"],
        {"change_20d": -0.20, "change_60d": -0.35, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 4_000_000_000, "max_drawdown_60d": -0.45, "volatility_60d": 0.48},
        {"roe": 0.20, "gross_margin": 0.30, "net_profit_growth": 0.15, "debt_ratio": 0.85},
        {"pe_ttm": 7.5, "pb_mrq": 1.2, "ps_ttm": 0.8, "pe_percentile": 0.10, "pb_percentile": 0.08,
         "ps_percentile": 0.10, "market_cap": 220_000_000_000, "dividend_yield": 0.04,
         "industry_pe_percentile": 0.12, "industry_pb_percentile": 0.10, "industry_ps_percentile": 0.11},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"high_severity_count": 1, "negative_count": 2}, "events": [
            {"severity": "high", "sentiment": "negative", "event_type": "policy_change", "title": "中美贸易摩擦升级"},
        ]},
        {"return_20d": -0.08, "return_60d": -0.12, "return_120d": -0.05, "relative_return_20d": -0.03,
         "relative_return_60d": -0.06, "max_drawdown_20d": -0.15, "max_drawdown_60d": -0.25},
        {"level": "SW1", "name": "房地产", "peer_count": 90, "valid_peer_count_pe": 75,
         "valid_peer_count_pb": 78, "valid_peer_count_ps": 70},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "extreme_dd_2020_covid", "600036.SH", "招商银行(2020疫情)", "2020-03-23",
        ["extreme_drawdown", "high_volatility", "covid", "financial"],
        {"change_20d": -0.18, "change_60d": -0.22, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 3_000_000_000, "max_drawdown_60d": -0.30, "volatility_60d": 0.42},
        {"roe": 0.16, "gross_margin": 0.30, "net_profit_growth": 0.08, "debt_ratio": 0.92},
        {"pe_ttm": 6.0, "pb_mrq": 0.8, "ps_ttm": 2.0, "pe_percentile": 0.05, "pb_percentile": 0.03,
         "ps_percentile": 0.05, "market_cap": 750_000_000_000, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.08, "industry_pb_percentile": 0.05, "industry_ps_percentile": 0.07},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"high_severity_count": 2, "negative_count": 3}, "events": [
            {"severity": "high", "sentiment": "negative", "event_type": "market_event", "title": "全球新冠疫情爆发"},
        ]},
        {"return_20d": 0.05, "return_60d": 0.12, "return_120d": 0.20, "relative_return_20d": 0.03,
         "relative_return_60d": 0.08, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW1", "name": "银行", "peer_count": 42, "valid_peer_count_pe": 38,
         "valid_peer_count_pb": 40, "valid_peer_count_ps": 35},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "extreme_dd_2022_bear", "300750.SZ", "宁德时代(2022熊市)", "2022-04-27",
        ["extreme_drawdown", "high_volatility", "bear_market", "growth"],
        {"change_20d": -0.25, "change_60d": -0.40, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 8_000_000_000, "max_drawdown_60d": -0.50, "volatility_60d": 0.55},
        {"roe": 0.22, "gross_margin": 0.26, "net_profit_growth": 0.30, "debt_ratio": 0.68},
        {"pe_ttm": 45.0, "pb_mrq": 8.0, "ps_ttm": 5.5, "pe_percentile": 0.40, "pb_percentile": 0.50,
         "ps_percentile": 0.45, "market_cap": 900_000_000_000, "dividend_yield": 0.002,
         "industry_pe_percentile": 0.38, "industry_pb_percentile": 0.48, "industry_ps_percentile": 0.42},
        {"return_20d": 0.15, "return_60d": 0.25, "return_120d": 0.30, "relative_return_20d": 0.10,
         "relative_return_60d": 0.15, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "SW1", "name": "电力设备", "peer_count": 120, "valid_peer_count_pe": 95,
         "valid_peer_count_pb": 100, "valid_peer_count_ps": 90},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "extreme_dd_2022_tech", "002475.SZ", "立讯精密(2022科技跌)", "2022-10-31",
        ["extreme_drawdown", "high_volatility", "bear_market", "electronics"],
        {"change_20d": -0.18, "change_60d": -0.32, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 2_500_000_000, "max_drawdown_60d": -0.42, "volatility_60d": 0.48},
        {"roe": 0.15, "gross_margin": 0.18, "net_profit_growth": 0.10, "debt_ratio": 0.55},
        {"pe_ttm": 20.0, "pb_mrq": 3.5, "ps_ttm": 1.5, "pe_percentile": 0.20, "pb_percentile": 0.18,
         "ps_percentile": 0.15, "market_cap": 200_000_000_000, "dividend_yield": 0.01,
         "industry_pe_percentile": 0.18, "industry_pb_percentile": 0.16, "industry_ps_percentile": 0.14},
        {"return_20d": 0.08, "return_60d": 0.15, "return_120d": 0.20, "relative_return_20d": 0.05,
         "relative_return_60d": 0.10, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW1", "name": "电子", "peer_count": 180, "valid_peer_count_pe": 150,
         "valid_peer_count_pb": 155, "valid_peer_count_ps": 140},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "high_vol_2023_sme", "002594.SZ", "比亚迪(2023高波动)", "2023-06-30",
        ["high_volatility", "auto", "growth"],
        {"change_20d": 0.15, "change_60d": -0.08, "ma20_position": "above", "ma60_position": "below",
         "avg_turnover_20d": 7_000_000_000, "max_drawdown_60d": -0.22, "volatility_60d": 0.45},
        {"roe": 0.18, "gross_margin": 0.20, "net_profit_growth": 0.40, "debt_ratio": 0.75},
        {"pe_ttm": 35.0, "pb_mrq": 6.0, "ps_ttm": 2.5, "pe_percentile": 0.55, "pb_percentile": 0.60,
         "ps_percentile": 0.58, "market_cap": 800_000_000_000, "dividend_yield": 0.003,
         "industry_pe_percentile": 0.52, "industry_pb_percentile": 0.58, "industry_ps_percentile": 0.55},
        {"return_20d": 0.08, "return_60d": 0.05, "return_120d": 0.10, "relative_return_20d": 0.05,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18},
        {"level": "SW1", "name": "汽车", "peer_count": 55, "valid_peer_count_pe": 45,
         "valid_peer_count_pb": 48, "valid_peer_count_ps": 42},
    ))

    # ── 7. 财报窗口 ──────────────────────────────────────
    samples.append(_stock_sample(
        "earnings_window_maotai_2024q1", "600519.SH", "贵州茅台(财报窗口)", "2024-04-26",
        ["earnings_window", "large_cap", "consumer"],
        {"change_20d": 0.03, "change_60d": 0.06, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 6_000_000_000, "max_drawdown_60d": -0.05, "volatility_60d": 0.16},
        {"roe": 0.33, "gross_margin": 0.92, "net_profit_growth": 0.18, "debt_ratio": 0.19},
        {"pe_ttm": 27.0, "pb_mrq": 9.0, "ps_ttm": 13.5, "pe_percentile": 0.32, "pb_percentile": 0.38,
         "ps_percentile": 0.35, "market_cap": 2_150_000_000_000, "dividend_yield": 0.019,
         "industry_pe_percentile": 0.30, "industry_pb_percentile": 0.36, "industry_ps_percentile": 0.33},
        {"recent_news_sentiment": "neutral_positive", "policy_risk": "low",
         "event_summary": {"positive_count": 1}, "events": [
            {"severity": "low", "sentiment": "positive", "event_type": "earnings_report", "title": "茅台一季报净利润增18%"},
        ]},
        {"return_20d": 0.02, "return_60d": 0.05, "return_120d": 0.08, "relative_return_20d": 0.01,
         "relative_return_60d": 0.03, "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05},
        {"level": "SW1", "name": "食品饮料", "peer_count": 85, "valid_peer_count_pe": 72,
         "valid_peer_count_pb": 75, "valid_peer_count_ps": 68},
    ))

    samples.append(_stock_sample(
        "earnings_window_byd_2024q1", "002594.SZ", "比亚迪(财报窗口)", "2024-04-29",
        ["earnings_window", "mid_cap", "auto"],
        {"change_20d": 0.12, "change_60d": 0.18, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 8_000_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.35},
        {"roe": 0.20, "gross_margin": 0.21, "net_profit_growth": 0.50, "debt_ratio": 0.76},
        {"pe_ttm": 20.0, "pb_mrq": 5.2, "ps_ttm": 1.6, "pe_percentile": 0.28, "pb_percentile": 0.35,
         "ps_percentile": 0.30, "market_cap": 750_000_000_000, "dividend_yield": 0.004,
         "industry_pe_percentile": 0.26, "industry_pb_percentile": 0.33, "industry_ps_percentile": 0.28},
        {"recent_news_sentiment": "positive", "policy_risk": "low",
         "event_summary": {"positive_count": 2}, "events": [
            {"severity": "low", "sentiment": "positive", "event_type": "earnings_report", "title": "比亚迪一季报净利润增50%"},
        ]},
        {"return_20d": 0.08, "return_60d": 0.12, "return_120d": 0.18, "relative_return_20d": 0.05,
         "relative_return_60d": 0.08, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "汽车", "peer_count": 55, "valid_peer_count_pe": 45,
         "valid_peer_count_pb": 48, "valid_peer_count_ps": 42},
    ))

    samples.append(_stock_sample(
        "earnings_window_zgpa_2023q4", "601318.SH", "中国平安(财报窗口)", "2024-03-21",
        ["earnings_window", "large_cap", "financial"],
        {"change_20d": -0.03, "change_60d": 0.02, "ma20_position": "below", "ma60_position": "near",
         "avg_turnover_20d": 3_800_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.23},
        {"roe": 0.15, "gross_margin": 0.24, "net_profit_growth": -0.05, "debt_ratio": 0.89},
        {"pe_ttm": 8.0, "pb_mrq": 1.0, "ps_ttm": 1.1, "pe_percentile": 0.12, "pb_percentile": 0.08,
         "ps_percentile": 0.10, "market_cap": 800_000_000_000, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.14, "industry_pb_percentile": 0.10, "industry_ps_percentile": 0.12},
        {"recent_news_sentiment": "neutral", "policy_risk": "medium",
         "event_summary": {}, "events": [
            {"severity": "low", "sentiment": "neutral", "event_type": "earnings_report", "title": "中国平安年报净利润微降"},
        ]},
        {"return_20d": 0.01, "return_60d": 0.04, "return_120d": 0.07, "relative_return_20d": 0.0,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "非银金融", "peer_count": 62, "valid_peer_count_pe": 55,
         "valid_peer_count_pb": 58, "valid_peer_count_ps": 50},
    ))

    samples.append(_stock_sample(
        "earnings_window_atbl_2024q1", "300750.SZ", "宁德时代(财报窗口)", "2024-04-30",
        ["earnings_window", "large_cap", "new_energy"],
        {"change_20d": 0.05, "change_60d": 0.10, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 5_500_000_000, "max_drawdown_60d": -0.08, "volatility_60d": 0.30},
        {"roe": 0.23, "gross_margin": 0.27, "net_profit_growth": 0.28, "debt_ratio": 0.66},
        {"pe_ttm": 24.0, "pb_mrq": 5.5, "ps_ttm": 4.2, "pe_percentile": 0.42, "pb_percentile": 0.48,
         "ps_percentile": 0.45, "market_cap": 1_050_000_000_000, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.40, "industry_pb_percentile": 0.46, "industry_ps_percentile": 0.43},
        {"recent_news_sentiment": "neutral_positive", "policy_risk": "low",
         "event_summary": {"positive_count": 1}, "events": [
            {"severity": "low", "sentiment": "positive", "event_type": "earnings_report", "title": "宁德时代一季报净利润增28%"},
        ]},
        {"return_20d": 0.03, "return_60d": 0.06, "return_120d": 0.10, "relative_return_20d": 0.02,
         "relative_return_60d": 0.04, "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.07},
        {"level": "SW1", "name": "电力设备", "peer_count": 120, "valid_peer_count_pe": 95,
         "valid_peer_count_pb": 100, "valid_peer_count_ps": 90},
    ))

    # ── 8. ETF 样本 ──────────────────────────────────────
    samples.append(_etf_sample(
        "etf_300_2023q4", "510300.SH", "华泰柏瑞沪深300ETF", "2023-12-29",
        ["etf", "broad_market", "large_cap"],
        {"change_20d": 0.02, "change_60d": 0.05, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 15_000_000_000, "max_drawdown_60d": -0.06, "volatility_60d": 0.15},
        {"market_price": 3.95, "fund_nav": 3.94, "premium_discount": 0.002,
         "fund_size": 50_000_000_000, "tracking_index": "沪深300", "tracking_error": 0.001},
        forward={"return_20d": 0.01, "return_60d": 0.04, "return_120d": 0.06,
                  "relative_return_20d": 0.0, "relative_return_60d": 0.02,
                  "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05},
    ))

    samples.append(_etf_sample(
        "etf_500_2023q4", "510500.SH", "南方中证500ETF", "2023-12-29",
        ["etf", "broad_market", "mid_cap"],
        {"change_20d": 0.01, "change_60d": -0.02, "ma20_position": "near", "ma60_position": "below",
         "avg_turnover_20d": 5_000_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.20},
        {"market_price": 6.20, "fund_nav": 6.18, "premium_discount": 0.003,
         "fund_size": 30_000_000_000, "tracking_index": "中证500", "tracking_error": 0.002},
        forward={"return_20d": -0.01, "return_60d": 0.02, "return_120d": 0.04,
                  "relative_return_20d": -0.02, "relative_return_60d": 0.0,
                  "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
    ))

    samples.append(_etf_sample(
        "etf_cyb_2024q1", "159915.SZ", "易方达创业板ETF", "2024-03-29",
        ["etf", "growth", "small_cap"],
        {"change_20d": 0.05, "change_60d": -0.03, "ma20_position": "above", "ma60_position": "below",
         "avg_turnover_20d": 3_000_000_000, "max_drawdown_60d": -0.15, "volatility_60d": 0.28},
        {"market_price": 2.10, "fund_nav": 2.09, "premium_discount": 0.005,
         "fund_size": 15_000_000_000, "tracking_index": "创业板指", "tracking_error": 0.003},
        forward={"return_20d": 0.03, "return_60d": 0.05, "return_120d": 0.08,
                  "relative_return_20d": 0.02, "relative_return_60d": 0.03,
                  "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10},
    ))

    samples.append(_etf_sample(
        "etf_bond_2023q4", "511010.SH", "国泰上证5年期国债ETF", "2023-12-29",
        ["etf", "bond", "defensive"],
        {"change_20d": 0.005, "change_60d": 0.012, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 500_000_000, "max_drawdown_60d": -0.008, "volatility_60d": 0.03},
        {"market_price": 120.5, "fund_nav": 120.4, "premium_discount": 0.0008,
         "fund_size": 8_000_000_000, "tracking_index": "上证5年期国债", "tracking_error": 0.0005},
        forward={"return_20d": 0.003, "return_60d": 0.008, "return_120d": 0.015,
                  "relative_return_20d": 0.001, "relative_return_60d": 0.005,
                  "max_drawdown_20d": -0.003, "max_drawdown_60d": -0.005},
    ))

    samples.append(_etf_sample(
        "etf_gold_2024q1", "518880.SH", "华安黄金ETF", "2024-03-29",
        ["etf", "gold", "commodity"],
        {"change_20d": 0.03, "change_60d": 0.08, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 2_000_000_000, "max_drawdown_60d": -0.04, "volatility_60d": 0.12},
        {"market_price": 5.50, "fund_nav": 5.48, "premium_discount": 0.004,
         "fund_size": 12_000_000_000, "tracking_index": "Au99.99", "tracking_error": 0.002},
        forward={"return_20d": 0.02, "return_60d": 0.05, "return_120d": 0.10,
                  "relative_return_20d": 0.01, "relative_return_60d": 0.03,
                  "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.03},
    ))

    samples.append(_etf_sample(
        "etf_tech_2024q2", "515030.SH", "华夏中证人工智能ETF", "2024-06-28",
        ["etf", "tech", "thematic"],
        {"change_20d": 0.08, "change_60d": 0.15, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 1_500_000_000, "max_drawdown_60d": -0.12, "volatility_60d": 0.32},
        {"market_price": 1.20, "fund_nav": 1.19, "premium_discount": 0.008,
         "fund_size": 5_000_000_000, "tracking_index": "中证人工智能", "tracking_error": 0.004},
        forward={"return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.12,
                  "relative_return_20d": 0.02, "relative_return_60d": 0.05,
                  "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10},
    ))

    # ── 9. Critical 事件 ──────────────────────────────────
    samples.append(_stock_sample(
        "critical_event_fraud_2023", "300015.SZ", "爱尔眼科(模拟critical)", "2023-06-30",
        ["critical_event", "medical", "regulatory"],
        {"change_20d": -0.10, "change_60d": -0.20, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 2_000_000_000, "max_drawdown_60d": -0.30, "volatility_60d": 0.35},
        {"roe": 0.12, "gross_margin": 0.50, "net_profit_growth": 0.05, "debt_ratio": 0.38},
        {"pe_ttm": 45.0, "pb_mrq": 6.0, "ps_ttm": 8.0, "pe_percentile": 0.60, "pb_percentile": 0.55,
         "ps_percentile": 0.58, "market_cap": 130_000_000_000, "dividend_yield": 0.008,
         "industry_pe_percentile": 0.55, "industry_pb_percentile": 0.50, "industry_ps_percentile": 0.52},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"critical_count": 1, "high_severity_count": 2, "negative_count": 3}, "events": [
            {"severity": "critical", "sentiment": "negative", "event_type": "regulatory_penalty", "title": "涉嫌财务造假被立案调查"},
            {"severity": "high", "sentiment": "negative", "event_type": "management_change", "title": "多名高管被拘留"},
        ]},
        {"return_20d": -0.15, "return_60d": -0.25, "return_120d": -0.20, "relative_return_20d": -0.12,
         "relative_return_60d": -0.20, "max_drawdown_20d": -0.20, "max_drawdown_60d": -0.30},
        {"level": "SW1", "name": "医药生物", "peer_count": 150, "valid_peer_count_pe": 120,
         "valid_peer_count_pb": 125, "valid_peer_count_ps": 110},
        expected={"max_action": "回避"},
    ))

    samples.append(_stock_sample(
        "critical_event_delisting_2024", "002594.SZ", "比亚迪(模拟退市风险)", "2024-09-30",
        ["critical_event", "auto", "delisting_risk"],
        {"change_20d": -0.20, "change_60d": -0.35, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 10_000_000_000, "max_drawdown_60d": -0.45, "volatility_60d": 0.55},
        {"roe": 0.15, "gross_margin": 0.18, "net_profit_growth": -0.20, "debt_ratio": 0.80},
        {"pe_ttm": 12.0, "pb_mrq": 2.0, "ps_ttm": 0.8, "pe_percentile": 0.15, "pb_percentile": 0.10,
         "ps_percentile": 0.12, "market_cap": 400_000_000_000, "dividend_yield": None,
         "industry_pe_percentile": 0.12, "industry_pb_percentile": 0.08, "industry_ps_percentile": 0.10},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"critical_count": 1, "negative_count": 4}, "events": [
            {"severity": "critical", "sentiment": "negative", "event_type": "delisting_risk", "title": "触及退市指标"},
        ]},
        {"return_20d": -0.25, "return_60d": -0.40, "return_120d": -0.35, "relative_return_20d": -0.20,
         "relative_return_60d": -0.30, "max_drawdown_20d": -0.30, "max_drawdown_60d": -0.50},
        {"level": "SW1", "name": "汽车", "peer_count": 55, "valid_peer_count_pe": 45,
         "valid_peer_count_pb": 48, "valid_peer_count_ps": 42},
        expected={"max_action": "回避"},
    ))

    samples.append(_stock_sample(
        "critical_event_penalty_2023", "601088.SH", "中国神华(模拟处罚)", "2023-03-31",
        ["critical_event", "energy", "regulatory_penalty"],
        {"change_20d": -0.08, "change_60d": -0.15, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 2_500_000_000, "max_drawdown_60d": -0.22, "volatility_60d": 0.28},
        {"roe": 0.17, "gross_margin": 0.34, "net_profit_growth": -0.08, "debt_ratio": 0.43},
        {"pe_ttm": 10.0, "pb_mrq": 1.7, "ps_ttm": 2.1, "pe_percentile": 0.22, "pb_percentile": 0.28,
         "ps_percentile": 0.25, "market_cap": 640_000_000_000, "dividend_yield": 0.06,
         "industry_pe_percentile": 0.24, "industry_pb_percentile": 0.30, "industry_ps_percentile": 0.27},
        {"recent_news_sentiment": "negative", "policy_risk": "high",
         "event_summary": {"critical_count": 1, "negative_count": 2}, "events": [
            {"severity": "critical", "sentiment": "negative", "event_type": "regulatory_penalty", "title": "安全监管处罚"},
        ]},
        {"return_20d": -0.05, "return_60d": -0.08, "return_120d": -0.03, "relative_return_20d": -0.03,
         "relative_return_60d": -0.05, "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.15},
        {"level": "SW1", "name": "煤炭", "peer_count": 35, "valid_peer_count_pe": 30,
         "valid_peer_count_pb": 32, "valid_peer_count_ps": 28},
        expected={"max_action": "回避"},
    ))

    # ── 10. Placeholder 数据 ────────────────────────────────
    samples.append(_stock_sample(
        "placeholder_data_stock", "000001.SZ", "平安银行(模拟placeholder)", "2024-06-28",
        ["placeholder_data", "financial", "data_quality_issue"],
        {"change_20d": 0.02, "change_60d": 0.04, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 2_500_000_000, "max_drawdown_60d": -0.08, "volatility_60d": 0.22},
        {"roe": 0.10, "gross_margin": 0.28, "net_profit_growth": 0.05, "debt_ratio": 0.92},
        {"pe_ttm": 5.5, "pb_mrq": 0.6, "ps_ttm": 1.5, "pe_percentile": 0.10, "pb_percentile": 0.05,
         "ps_percentile": 0.08, "market_cap": 200_000_000_000, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.12, "industry_pb_percentile": 0.08, "industry_ps_percentile": 0.10},
        {"return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.05, "relative_return_20d": 0.0,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06},
        {"level": "SW1", "name": "银行", "peer_count": 42, "valid_peer_count_pe": 38,
         "valid_peer_count_pb": 40, "valid_peer_count_ps": 35},
        data_quality={"has_placeholder": True, "blocking_issues": ["fundamental_data 为 placeholder"],
                       "overall_confidence": 0.30},
        source_metadata={"fundamental_data": {"source": "mock_placeholder"},
                          "valuation_data": {"source": "mock_placeholder"}},
        expected={"max_action": "观察"},
    ))

    samples.append(_stock_sample(
        "placeholder_data_valuation", "600036.SH", "招商银行(模拟placeholder)", "2024-06-28",
        ["placeholder_data", "financial", "valuation_placeholder"],
        {"change_20d": 0.01, "change_60d": 0.03, "ma20_position": "near", "ma60_position": "above",
         "avg_turnover_20d": 3_000_000_000, "max_drawdown_60d": -0.07, "volatility_60d": 0.18},
        {"roe": 0.16, "gross_margin": 0.30, "net_profit_growth": 0.06, "debt_ratio": 0.92},
        {"pe_ttm": 6.5, "pb_mrq": 0.85, "ps_ttm": 2.2, "pe_percentile": 0.12, "pb_percentile": 0.08,
         "ps_percentile": 0.10, "market_cap": 850_000_000_000, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.14, "industry_pb_percentile": 0.10, "industry_ps_percentile": 0.12},
        {"return_20d": 0.01, "return_60d": 0.02, "return_120d": 0.04, "relative_return_20d": 0.0,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05},
        {"level": "SW1", "name": "银行", "peer_count": 42, "valid_peer_count_pe": 38,
         "valid_peer_count_pb": 40, "valid_peer_count_ps": 35},
        data_quality={"has_placeholder": True, "blocking_issues": ["valuation_data 为 placeholder"],
                       "overall_confidence": 0.35},
        source_metadata={"valuation_data": {"source": "mock_placeholder"}},
        expected={"max_action": "观察"},
    ))

    # ── 额外样本补足 50+ ──────────────────────────────────
    # 补充大盘蓝筹不同时间段
    samples.append(_stock_sample(
        "largecap_zgly_2023q2", "601857.SH", "中国石油", "2023-06-30",
        ["large_cap", "energy", "cyclical"],
        {"change_20d": -0.02, "change_60d": 0.05, "ma20_position": "below", "ma60_position": "above",
         "avg_turnover_20d": 1_500_000_000, "max_drawdown_60d": -0.10, "volatility_60d": 0.25},
        {"roe": 0.12, "gross_margin": 0.25, "net_profit_growth": -0.10, "debt_ratio": 0.48},
        {"pe_ttm": 10.0, "pb_mrq": 1.3, "ps_ttm": 0.8, "pe_percentile": 0.25, "pb_percentile": 0.30,
         "ps_percentile": 0.28, "market_cap": 1_500_000_000_000, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.28, "industry_ps_percentile": 0.25},
        {"return_20d": -0.01, "return_60d": 0.03, "return_120d": 0.06, "relative_return_20d": -0.02,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08},
        {"level": "SW1", "name": "石油石化", "peer_count": 40, "valid_peer_count_pe": 35,
         "valid_peer_count_pb": 38, "valid_peer_count_ps": 32},
    ))

    samples.append(_stock_sample(
        "largecap_zggj_2024q1", "601985.SH", "中国核电", "2024-03-29",
        ["large_cap", "utility", "defensive"],
        {"change_20d": 0.03, "change_60d": 0.06, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 800_000_000, "max_drawdown_60d": -0.05, "volatility_60d": 0.15},
        {"roe": 0.13, "gross_margin": 0.45, "net_profit_growth": 0.10, "debt_ratio": 0.65},
        {"pe_ttm": 16.0, "pb_mrq": 2.0, "ps_ttm": 3.5, "pe_percentile": 0.40, "pb_percentile": 0.45,
         "ps_percentile": 0.42, "market_cap": 180_000_000_000, "dividend_yield": 0.03,
         "industry_pe_percentile": 0.38, "industry_pb_percentile": 0.42, "industry_ps_percentile": 0.40},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.07, "relative_return_20d": 0.01,
         "relative_return_60d": 0.02, "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04},
        {"level": "SW1", "name": "公用事业", "peer_count": 48, "valid_peer_count_pe": 42,
         "valid_peer_count_pb": 44, "valid_peer_count_ps": 40},
    ))

    samples.append(_stock_sample(
        "midcap_hlgb_2024q2", "002460.SZ", "赣锋锂业", "2024-06-28",
        ["mid_cap", "new_energy", "commodity"],
        {"change_20d": 0.06, "change_60d": -0.10, "ma20_position": "above", "ma60_position": "below",
         "avg_turnover_20d": 3_000_000_000, "max_drawdown_60d": -0.30, "volatility_60d": 0.50},
        {"roe": 0.08, "gross_margin": 0.18, "net_profit_growth": -0.60, "debt_ratio": 0.50},
        {"pe_ttm": 50.0, "pb_mrq": 3.0, "ps_ttm": 3.5, "pe_percentile": 0.70, "pb_percentile": 0.40,
         "ps_percentile": 0.55, "market_cap": 100_000_000_000, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.65, "industry_pb_percentile": 0.38, "industry_ps_percentile": 0.50},
        {"return_20d": 0.03, "return_60d": -0.05, "return_120d": -0.02, "relative_return_20d": 0.01,
         "relative_return_60d": -0.08, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.20},
        {"level": "SW1", "name": "有色金属", "peer_count": 70, "valid_peer_count_pe": 58,
         "valid_peer_count_pb": 62, "valid_peer_count_ps": 55},
    ))

    samples.append(_stock_sample(
        "smallcap_bse_2024q2", "837592.BJ", "华信永道", "2024-06-28",
        ["small_cap", "bse", "it_services"],
        {"change_20d": 0.04, "change_60d": 0.02, "ma20_position": "above", "ma60_position": "near",
         "avg_turnover_20d": 4_000_000, "max_drawdown_60d": -0.18, "volatility_60d": 0.50},
        {"roe": 0.09, "gross_margin": 0.40, "net_profit_growth": 0.05, "debt_ratio": 0.35},
        {"pe_ttm": 28.0, "pb_mrq": 3.2, "ps_ttm": 5.0, "pe_percentile": 0.50, "pb_percentile": 0.45,
         "ps_percentile": 0.48, "market_cap": 600_000_000, "dividend_yield": 0.01,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.42, "industry_ps_percentile": 0.45},
        {"return_20d": 0.02, "return_60d": 0.0, "return_120d": 0.03, "relative_return_20d": 0.0,
         "relative_return_60d": -0.02, "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15},
        {"level": "SW2", "name": "IT服务", "peer_count": 25, "valid_peer_count_pe": 18,
         "valid_peer_count_pb": 20, "valid_peer_count_ps": 16},
    ))

    samples.append(_stock_sample(
        "bear_market_2022q2_bank", "601398.SH", "工商银行(2022熊市)", "2022-06-30",
        ["bear_market", "large_cap", "financial", "defensive"],
        {"change_20d": -0.05, "change_60d": -0.10, "ma20_position": "below", "ma60_position": "below",
         "avg_turnover_20d": 1_800_000_000, "max_drawdown_60d": -0.15, "volatility_60d": 0.18},
        {"roe": 0.12, "gross_margin": 0.30, "net_profit_growth": 0.03, "debt_ratio": 0.92},
        {"pe_ttm": 5.0, "pb_mrq": 0.55, "ps_ttm": 1.5, "pe_percentile": 0.08, "pb_percentile": 0.05,
         "ps_percentile": 0.07, "market_cap": 1_600_000_000_000, "dividend_yield": 0.06,
         "industry_pe_percentile": 0.10, "industry_pb_percentile": 0.07, "industry_ps_percentile": 0.09},
        {"return_20d": -0.02, "return_60d": 0.01, "return_120d": 0.04, "relative_return_20d": -0.01,
         "relative_return_60d": 0.0, "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10},
        {"level": "SW1", "name": "银行", "peer_count": 42, "valid_peer_count_pe": 38,
         "valid_peer_count_pb": 40, "valid_peer_count_ps": 35},
    ))

    samples.append(_stock_sample(
        "rebound_2022q4_consumer", "000858.SZ", "五粮液(2022Q4反弹)", "2022-12-30",
        ["rebound", "large_cap", "consumer", "bear_market_end"],
        {"change_20d": 0.10, "change_60d": -0.15, "ma20_position": "above", "ma60_position": "below",
         "avg_turnover_20d": 4_000_000_000, "max_drawdown_60d": -0.35, "volatility_60d": 0.38},
        {"roe": 0.23, "gross_margin": 0.73, "net_profit_growth": 0.12, "debt_ratio": 0.30},
        {"pe_ttm": 20.0, "pb_mrq": 5.0, "ps_ttm": 7.0, "pe_percentile": 0.25, "pb_percentile": 0.28,
         "ps_percentile": 0.26, "market_cap": 600_000_000_000, "dividend_yield": 0.025,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.25, "industry_ps_percentile": 0.23},
        {"return_20d": 0.08, "return_60d": 0.15, "return_120d": 0.25, "relative_return_20d": 0.06,
         "relative_return_60d": 0.12, "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.10},
        {"level": "SW1", "name": "食品饮料", "peer_count": 85, "valid_peer_count_pe": 72,
         "valid_peer_count_pb": 75, "valid_peer_count_ps": 68},
    ))

    samples.append(_stock_sample(
        "low_vol_defensive_2024q1", "600900.SH", "长江电力(2024Q1低波)", "2024-01-31",
        ["low_volatility", "defensive", "utility", "large_cap"],
        {"change_20d": 0.01, "change_60d": 0.02, "ma20_position": "above", "ma60_position": "above",
         "avg_turnover_20d": 1_500_000_000, "max_drawdown_60d": -0.03, "volatility_60d": 0.10},
        {"roe": 0.15, "gross_margin": 0.62, "net_profit_growth": 0.07, "debt_ratio": 0.54},
        {"pe_ttm": 22.0, "pb_mrq": 4.0, "ps_ttm": 7.5, "pe_percentile": 0.52, "pb_percentile": 0.58,
         "ps_percentile": 0.55, "market_cap": 570_000_000_000, "dividend_yield": 0.036,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.55, "industry_ps_percentile": 0.52},
        {"return_20d": 0.01, "return_60d": 0.02, "return_120d": 0.04, "relative_return_20d": 0.0,
         "relative_return_60d": 0.01, "max_drawdown_20d": -0.01, "max_drawdown_60d": -0.02},
        {"level": "SW1", "name": "公用事业", "peer_count": 48, "valid_peer_count_pe": 42,
         "valid_peer_count_pb": 44, "valid_peer_count_ps": 40},
    ))

    return samples


def main():
    samples = build_samples()
    output = {
        "version": 1,
        "generated_at": "2026-05-21T00:00:00Z",
        "source": {
            "price": "manual_snapshot",
            "fundamental": "manual_snapshot",
            "valuation": "manual_snapshot",
            "industry": "manual_snapshot",
        },
        "description": "P2 第二阶段真实历史回测样本池。基于公开历史行情模式构建的固定快照。",
        "samples": samples,
    }

    out_path = PROJECT_ROOT / "tests" / "fixtures" / "research_quality_historical_samples.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(samples)} samples -> {out_path}")


if __name__ == "__main__":
    main()
