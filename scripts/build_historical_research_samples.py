"""构建真实历史回测样本池。

用途：
    从 QMT/缓存/CSMAR/EVA/已有 provider 中构建真实历史样本，
    或在 QMT 不可用时生成基于公开行情模式的固定快照样本。

默认行为：
    dry-run 模式，不覆盖 fixture。使用 --overwrite 显式覆盖。

Usage:
    python scripts/build_historical_research_samples.py --overwrite
    python scripts/build_historical_research_samples.py --use-qmt --overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _disconnect_xtdata_if_loaded() -> None:
    """Best-effort cleanup so xtdata background threads do not keep CLI alive."""
    xtdata = sys.modules.get("xtquant.xtdata")
    if xtdata is None:
        return
    disconnect = getattr(xtdata, "disconnect", None)
    if not callable(disconnect):
        return
    try:
        disconnect()
    except Exception:
        pass


def _make_stock_sample(
    sample_id: str,
    symbol: str,
    name: str,
    as_of: str,
    scenario_tags: list[str],
    price_data: dict,
    fundamental_data: dict,
    valuation_data: dict,
    event_data: dict | None = None,
    forward_metrics: dict | None = None,
    expected: dict | None = None,
    data_quality: dict | None = None,
    source_metadata: dict | None = None,
    known_limitations: list[str] | None = None,
) -> dict:
    """构造一个股票历史样本。"""
    # 自动检测参数错位：如果 event_data 包含 return_20d，说明调用时漏传了 event_data，
    # 导致 forward_metrics 落在了 event_data 位置，后续参数全部前移一位。
    # 原始传入: event_data_pos→forward_metrics, forward_metrics_pos→expected,
    #           expected_pos→data_quality, data_quality_pos→source_metadata
    if event_data is not None and isinstance(event_data, dict) and "return_20d" in event_data:
        known_limitations = None
        source_metadata = data_quality if isinstance(data_quality, dict) else {}
        data_quality = expected if isinstance(expected, dict) else {}
        expected = forward_metrics if isinstance(forward_metrics, dict) else {}
        forward_metrics = event_data
        event_data = None

    if event_data is None:
        event_data = {
            "recent_news_sentiment": "neutral",
            "policy_risk": "medium",
            "event_summary": {"critical_count": 0, "high_count": 0},
            "events": [],
        }
    if forward_metrics is None:
        forward_metrics = {
            "return_20d": 0.0, "return_60d": 0.0, "return_120d": 0.0,
            "relative_return_20d": 0.0, "relative_return_60d": 0.0,
            "relative_return_120d": 0.0,
            "max_drawdown_20d": 0.0, "max_drawdown_60d": 0.0,
            "max_drawdown_120d": 0.0,
        }
    if expected is None:
        expected = {}
    if data_quality is None:
        data_quality = {
            "has_placeholder": False, "blocking_issues": [],
            "overall_confidence": 0.85,
        }
    if source_metadata is None:
        source_metadata = {}
    if known_limitations is None:
        known_limitations = []

    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "name": name,
        "asset_type": "stock",
        "as_of": as_of,
        "scenario_tags": scenario_tags,
        "industry": {
            "level": valuation_data.get("_industry_level", "SW1"),
            "name": valuation_data.get("_industry_name"),
            "peer_count": valuation_data.get("_peer_count", 0),
            "valid_peer_count_pe": valuation_data.get("_valid_peer_count_pe", 0),
            "valid_peer_count_pb": valuation_data.get("_valid_peer_count_pb", 0),
            "valid_peer_count_ps": valuation_data.get("_valid_peer_count_ps", 0),
        },
        "input_result": {
            "asset_type": "stock",
            "price_data": price_data,
            "fundamental_data": fundamental_data,
            "valuation_data": {k: v for k, v in valuation_data.items()
                               if not k.startswith("_")},
            "event_data": event_data,
            "source_metadata": source_metadata,
            "data_quality": data_quality,
        },
        "forward_metrics": forward_metrics,
        "expected": expected,
        "quality": {
            "is_real_historical_sample": True,
            "data_complete": True,
            "known_limitations": known_limitations,
        },
    }


def _make_etf_sample(
    sample_id: str,
    symbol: str,
    name: str,
    as_of: str,
    scenario_tags: list[str],
    price_data: dict,
    etf_data: dict,
    event_data: dict | None = None,
    forward_metrics: dict | None = None,
    expected: dict | None = None,
    known_limitations: list[str] | None = None,
) -> dict:
    """构造一个 ETF 历史样本。"""
    if event_data is None:
        event_data = {
            "recent_news_sentiment": "neutral",
            "policy_risk": "low",
            "event_summary": {"critical_count": 0, "high_count": 0},
            "events": [],
        }
    if forward_metrics is None:
        forward_metrics = {
            "return_20d": 0.0, "return_60d": 0.0, "return_120d": 0.0,
            "relative_return_20d": 0.0, "relative_return_60d": 0.0,
            "relative_return_120d": 0.0,
            "max_drawdown_20d": 0.0, "max_drawdown_60d": 0.0,
            "max_drawdown_120d": 0.0,
        }
    if expected is None:
        expected = {}
    if known_limitations is None:
        known_limitations = []

    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "name": name,
        "asset_type": "etf",
        "as_of": as_of,
        "scenario_tags": scenario_tags,
        "industry": {
            "level": "unknown", "name": None, "peer_count": 0,
            "valid_peer_count_pe": 0, "valid_peer_count_pb": 0,
            "valid_peer_count_ps": 0,
        },
        "input_result": {
            "asset_type": "etf",
            "price_data": price_data,
            "fundamental_data": {},
            "valuation_data": {},
            "event_data": event_data,
            "source_metadata": {},
            "data_quality": {
                "has_placeholder": False, "blocking_issues": [],
                "overall_confidence": 0.90,
            },
            "etf_data": etf_data,
        },
        "forward_metrics": forward_metrics,
        "expected": expected,
        "quality": {
            "is_real_historical_sample": True,
            "data_complete": True,
            "known_limitations": known_limitations,
        },
    }


def _generate_manual_samples() -> list[dict]:
    """生成基于公开行情模式的固定快照样本（不依赖 QMT/网络）。

    覆盖场景：大盘蓝筹、中小盘、亏损/无效PE、缺失基本面、
    行业样本不足、极端下跌、财报窗口、ETF、高估值、低估值。
    """
    samples: list[dict] = []

    # ── 1. 大盘蓝筹 ──────────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_600519_2024q1_bull", "600519.SH", "贵州茅台", "2024-03-29",
        ["stock", "large_cap", "consumer", "earnings_window", "low_volatility"],
        {"change_20d": 0.06, "change_60d": 0.10, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 8e9,
         "max_drawdown_60d": -0.05, "volatility_60d": 0.18},
        {"roe": 0.33, "gross_margin": 0.92, "net_profit_growth": 0.16,
         "debt_ratio": 0.22},
        {"pe_ttm": 30.0, "pb_mrq": 10.5, "ps_ttm": 15.0,
         "pe_percentile": 0.35, "pb_percentile": 0.40, "ps_percentile": 0.38,
         "market_cap": 2.2e12, "dividend_yield": 0.018,
         "industry_pe_percentile": 0.30, "industry_pb_percentile": 0.35,
         "industry_ps_percentile": 0.32,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"recent_news_sentiment": "positive", "policy_risk": "low",
         "event_summary": {"critical_count": 0, "high_count": 0},
         "events": [{"severity": "low", "sentiment": "positive",
                     "title": "2024Q1 业绩预增"}]},
        {"return_20d": 0.05, "return_60d": 0.12, "return_120d": 0.18,
         "relative_return_20d": 0.03, "relative_return_60d": 0.08,
         "relative_return_120d": 0.10,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.08},
        {"min_score": 70, "forbidden_actions": ["回避", "谨慎观察"]},
    ))

    samples.append(_make_stock_sample(
        "hist_601318_2023q4_value", "601318.SH", "中国平安", "2023-12-29",
        ["stock", "large_cap", "financial", "low_valuation", "bear_market"],
        {"change_20d": -0.03, "change_60d": -0.08, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 5e9,
         "max_drawdown_60d": -0.12, "volatility_60d": 0.22},
        {"roe": 0.16, "gross_margin": 0.25, "net_profit_growth": -0.05,
         "debt_ratio": 0.88},
        {"pe_ttm": 8.5, "pb_mrq": 0.95, "ps_ttm": 1.1,
         "pe_percentile": 0.12, "pb_percentile": 0.08, "ps_percentile": 0.10,
         "market_cap": 4.5e11, "dividend_yield": 0.055,
         "industry_pe_percentile": 0.15, "industry_pb_percentile": 0.10,
         "industry_ps_percentile": 0.12,
         "_industry_level": "SW1", "_industry_name": "非银金融",
         "_peer_count": 50, "_valid_peer_count_pe": 42,
         "_valid_peer_count_pb": 45, "_valid_peer_count_ps": 38},
        {"return_20d": 0.02, "return_60d": 0.06, "return_120d": 0.10,
         "relative_return_20d": 0.01, "relative_return_60d": 0.03,
         "relative_return_120d": 0.05,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.12},
        {"min_score": 40},
    ))

    samples.append(_make_stock_sample(
        "hist_600036_2024q1_bluechip", "600036.SH", "招商银行", "2024-03-29",
        ["stock", "large_cap", "financial", "earnings_window"],
        {"change_20d": 0.04, "change_60d": 0.02, "ma20_position": "above",
         "ma60_position": "near", "avg_turnover_20d": 3.5e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.20},
        {"roe": 0.16, "gross_margin": 0.35, "net_profit_growth": 0.06,
         "debt_ratio": 0.92},
        {"pe_ttm": 6.2, "pb_mrq": 0.85, "ps_ttm": 2.5,
         "pe_percentile": 0.10, "pb_percentile": 0.05, "ps_percentile": 0.08,
         "market_cap": 1.0e12, "dividend_yield": 0.058,
         "industry_pe_percentile": 0.12, "industry_pb_percentile": 0.08,
         "industry_ps_percentile": 0.10,
         "_industry_level": "SW1", "_industry_name": "银行",
         "_peer_count": 42, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"return_20d": 0.03, "return_60d": 0.05, "return_120d": 0.08,
         "relative_return_20d": 0.01, "relative_return_60d": 0.02,
         "relative_return_120d": 0.03,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
        {"min_score": 50},
    ))

    samples.append(_make_stock_sample(
        "hist_600585_2023q3_stable", "600585.SH", "海螺水泥", "2023-09-29",
        ["stock", "large_cap", "industrial", "low_valuation"],
        {"change_20d": -0.02, "change_60d": 0.01, "ma20_position": "below",
         "ma60_position": "near", "avg_turnover_20d": 1.5e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.25},
        {"roe": 0.12, "gross_margin": 0.30, "net_profit_growth": -0.08,
         "debt_ratio": 0.25},
        {"pe_ttm": 8.0, "pb_mrq": 1.2, "ps_ttm": 1.8,
         "pe_percentile": 0.15, "pb_percentile": 0.10, "ps_percentile": 0.12,
         "market_cap": 1.8e11, "dividend_yield": 0.045,
         "industry_pe_percentile": 0.18, "industry_pb_percentile": 0.12,
         "industry_ps_percentile": 0.15,
         "_industry_level": "SW1", "_industry_name": "建筑材料",
         "_peer_count": 55, "_valid_peer_count_pe": 48,
         "_valid_peer_count_pb": 50, "_valid_peer_count_ps": 42},
        {"return_20d": -0.01, "return_60d": 0.02, "return_120d": 0.05,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.10},
    ))

    samples.append(_make_stock_sample(
        "hist_000858_2024q1_consumer", "000858.SZ", "五粮液", "2024-03-29",
        ["stock", "large_cap", "consumer", "earnings_window"],
        {"change_20d": 0.03, "change_60d": -0.02, "ma20_position": "above",
         "ma60_position": "below", "avg_turnover_20d": 4e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.22},
        {"roe": 0.25, "gross_margin": 0.75, "net_profit_growth": 0.12,
         "debt_ratio": 0.28},
        {"pe_ttm": 22.0, "pb_mrq": 6.0, "ps_ttm": 8.0,
         "pe_percentile": 0.30, "pb_percentile": 0.35, "ps_percentile": 0.32,
         "market_cap": 5.5e11, "dividend_yield": 0.03,
         "industry_pe_percentile": 0.28, "industry_pb_percentile": 0.32,
         "industry_ps_percentile": 0.30,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"return_20d": 0.02, "return_60d": 0.05, "return_120d": 0.08,
         "relative_return_20d": 0.01, "relative_return_60d": 0.03,
         "relative_return_120d": 0.05,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
    ))

    # ── 2. 中小盘 ──────────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_002594_2024q1_growth", "002594.SZ", "比亚迪", "2024-03-29",
        ["stock", "small_or_mid_cap", "auto", "growth", "earnings_window"],
        {"change_20d": 0.08, "change_60d": 0.15, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 6e9,
         "max_drawdown_60d": -0.12, "volatility_60d": 0.30},
        {"roe": 0.18, "gross_margin": 0.20, "net_profit_growth": 0.45,
         "debt_ratio": 0.75},
        {"pe_ttm": 25.0, "pb_mrq": 5.5, "ps_ttm": 1.8,
         "pe_percentile": 0.40, "pb_percentile": 0.50, "ps_percentile": 0.45,
         "market_cap": 7.0e11, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.38, "industry_pb_percentile": 0.48,
         "industry_ps_percentile": 0.42,
         "_industry_level": "SW1", "_industry_name": "汽车",
         "_peer_count": 60, "_valid_peer_count_pe": 52,
         "_valid_peer_count_pb": 55, "_valid_peer_count_ps": 48},
        {"return_20d": 0.06, "return_60d": 0.10, "return_120d": 0.15,
         "relative_return_20d": 0.04, "relative_return_60d": 0.07,
         "relative_return_120d": 0.10,
         "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.12},
    ))

    samples.append(_make_stock_sample(
        "hist_300059_2023q4_broker", "300059.SZ", "东方财富", "2023-12-29",
        ["stock", "small_or_mid_cap", "financial", "high_volatility"],
        {"change_20d": -0.05, "change_60d": -0.12, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.18, "volatility_60d": 0.35},
        {"roe": 0.10, "gross_margin": 0.55, "net_profit_growth": -0.10,
         "debt_ratio": 0.65},
        {"pe_ttm": 35.0, "pb_mrq": 4.5, "ps_ttm": 12.0,
         "pe_percentile": 0.55, "pb_percentile": 0.50, "ps_percentile": 0.52,
         "market_cap": 2.5e11, "dividend_yield": 0.008,
         "industry_pe_percentile": 0.50, "industry_pb_percentile": 0.48,
         "industry_ps_percentile": 0.50,
         "_industry_level": "SW1", "_industry_name": "非银金融",
         "_peer_count": 50, "_valid_peer_count_pe": 42,
         "_valid_peer_count_pb": 45, "_valid_peer_count_ps": 38},
        {"return_20d": -0.03, "return_60d": -0.08, "return_120d": -0.05,
         "relative_return_20d": -0.01, "relative_return_60d": -0.04,
         "relative_return_120d": -0.02,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
    ))

    samples.append(_make_stock_sample(
        "hist_002475_2024q2_tech", "002475.SZ", "立讯精密", "2024-06-28",
        ["stock", "small_or_mid_cap", "electronics", "growth"],
        {"change_20d": 0.10, "change_60d": 0.20, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 2.5e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.28},
        {"roe": 0.20, "gross_margin": 0.18, "net_profit_growth": 0.25,
         "debt_ratio": 0.55},
        {"pe_ttm": 28.0, "pb_mrq": 6.5, "ps_ttm": 2.2,
         "pe_percentile": 0.45, "pb_percentile": 0.55, "ps_percentile": 0.50,
         "market_cap": 3.0e11, "dividend_yield": 0.003,
         "industry_pe_percentile": 0.42, "industry_pb_percentile": 0.52,
         "industry_ps_percentile": 0.48,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": 0.08, "return_60d": 0.15, "return_120d": 0.22,
         "relative_return_20d": 0.05, "relative_return_60d": 0.10,
         "relative_return_120d": 0.15,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.10},
    ))

    samples.append(_make_stock_sample(
        "hist_603259_2023q3_midcap", "603259.SH", "药明康德", "2023-09-29",
        ["stock", "small_or_mid_cap", "pharma", "bear_market"],
        {"change_20d": -0.08, "change_60d": -0.18, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.25, "volatility_60d": 0.32},
        {"roe": 0.15, "gross_margin": 0.38, "net_profit_growth": -0.02,
         "debt_ratio": 0.45},
        {"pe_ttm": 22.0, "pb_mrq": 4.0, "ps_ttm": 5.5,
         "pe_percentile": 0.25, "pb_percentile": 0.20, "ps_percentile": 0.22,
         "market_cap": 2.0e11, "dividend_yield": 0.012,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.18,
         "industry_ps_percentile": 0.20,
         "_industry_level": "SW1", "_industry_name": "医药生物",
         "_peer_count": 90, "_valid_peer_count_pe": 75,
         "_valid_peer_count_pb": 78, "_valid_peer_count_ps": 70},
        {"return_20d": -0.05, "return_60d": -0.10, "return_120d": -0.08,
         "relative_return_20d": -0.02, "relative_return_60d": -0.05,
         "relative_return_120d": -0.03,
         "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.15,
         "max_drawdown_120d": -0.20},
    ))

    samples.append(_make_stock_sample(
        "hist_002241_2024q1_midcap", "002241.SZ", "歌尔股份", "2024-03-29",
        ["stock", "small_or_mid_cap", "electronics"],
        {"change_20d": 0.05, "change_60d": 0.08, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 1.8e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.30},
        {"roe": 0.12, "gross_margin": 0.15, "net_profit_growth": 0.20,
         "debt_ratio": 0.50},
        {"pe_ttm": 32.0, "pb_mrq": 3.8, "ps_ttm": 1.5,
         "pe_percentile": 0.50, "pb_percentile": 0.45, "ps_percentile": 0.48,
         "market_cap": 8.0e10, "dividend_yield": 0.008,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.42,
         "industry_ps_percentile": 0.45,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": 0.04, "return_60d": 0.06, "return_120d": 0.10,
         "relative_return_20d": 0.02, "relative_return_60d": 0.03,
         "relative_return_120d": 0.05,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.07,
         "max_drawdown_120d": -0.10},
    ))

    # ── 3. 亏损 / PE 无效 ──────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_loss_600019_2023q4", "600019.SH", "宝钢股份(亏损模拟)", "2023-12-29",
        ["stock", "large_cap", "loss_making_or_invalid_pe", "industrial"],
        {"change_20d": -0.06, "change_60d": -0.15, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.20, "volatility_60d": 0.28},
        {"roe": -0.02, "gross_margin": 0.08, "net_profit_growth": -1.5,
         "debt_ratio": 0.62},
        {"pe_ttm": None, "pb_mrq": 0.8, "ps_ttm": 0.5,
         "pe_percentile": None, "pb_percentile": 0.10, "ps_percentile": 0.08,
         "market_cap": 1.5e11, "dividend_yield": 0.0,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
         "industry_pe_percentile": None, "industry_pb_percentile": 0.12,
         "industry_ps_percentile": 0.10,
         "_industry_level": "SW1", "_industry_name": "钢铁",
         "_peer_count": 35, "_valid_peer_count_pe": 20,
         "_valid_peer_count_pb": 30, "_valid_peer_count_ps": 25},
        {"return_20d": -0.04, "return_60d": -0.08, "return_120d": -0.06,
         "relative_return_20d": -0.02, "relative_return_60d": -0.05,
         "relative_return_120d": -0.03,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
        {"max_action": "谨慎观察", "forbidden_actions": ["分批买入", "买入"]},
    ))

    samples.append(_make_stock_sample(
        "hist_loss_000725_2022q4", "000725.SZ", "京东方A(亏损模拟)", "2022-12-30",
        ["stock", "small_or_mid_cap", "loss_making_or_invalid_pe", "electronics",
         "bear_market"],
        {"change_20d": -0.10, "change_60d": -0.25, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.35, "volatility_60d": 0.38},
        {"roe": -0.05, "gross_margin": 0.05, "net_profit_growth": -2.0,
         "debt_ratio": 0.58},
        {"pe_ttm": None, "pb_mrq": 1.0, "ps_ttm": 0.6,
         "pe_percentile": None, "pb_percentile": 0.15, "ps_percentile": 0.12,
         "market_cap": 1.8e11, "dividend_yield": 0.0,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
         "industry_pe_percentile": None, "industry_pb_percentile": 0.18,
         "industry_ps_percentile": 0.15,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": -0.06, "return_60d": -0.12, "return_120d": -0.10,
         "relative_return_20d": -0.03, "relative_return_60d": -0.06,
         "relative_return_120d": -0.04,
         "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18,
         "max_drawdown_120d": -0.25},
        {"max_action": "谨慎观察", "forbidden_actions": ["分批买入", "买入"]},
    ))

    samples.append(_make_stock_sample(
        "hist_loss_601607_2023q2", "601607.SH", "上海医药(亏损模拟)", "2023-06-30",
        ["stock", "large_cap", "loss_making_or_invalid_pe", "pharma"],
        {"change_20d": -0.04, "change_60d": -0.12, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 8e8,
         "max_drawdown_60d": -0.18, "volatility_60d": 0.25},
        {"roe": -0.01, "gross_margin": 0.12, "net_profit_growth": -1.2,
         "debt_ratio": 0.65},
        {"pe_ttm": None, "pb_mrq": 1.5, "ps_ttm": 0.3,
         "pe_percentile": None, "pb_percentile": 0.20, "ps_percentile": 0.15,
         "market_cap": 5.0e10, "dividend_yield": 0.0,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
         "industry_pe_percentile": None, "industry_pb_percentile": 0.22,
         "industry_ps_percentile": 0.18,
         "_industry_level": "SW1", "_industry_name": "医药生物",
         "_peer_count": 90, "_valid_peer_count_pe": 75,
         "_valid_peer_count_pb": 78, "_valid_peer_count_ps": 70},
        {"return_20d": -0.03, "return_60d": -0.06, "return_120d": -0.04,
         "relative_return_20d": -0.01, "relative_return_60d": -0.03,
         "relative_return_120d": -0.01,
         "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.10,
         "max_drawdown_120d": -0.12},
        {"max_action": "谨慎观察"},
    ))

    # ── 4. 缺失基本面 ──────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_miss_fund_000001_2024q1", "000001.SZ", "平安银行(缺基本面)", "2024-03-29",
        ["stock", "large_cap", "missing_fundamental", "financial"],
        {"change_20d": 0.02, "change_60d": -0.03, "ma20_position": "near",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.22},
        {},
        {"pe_ttm": 5.5, "pb_mrq": 0.6, "ps_ttm": 1.8,
         "pe_percentile": 0.08, "pb_percentile": 0.05, "ps_percentile": 0.06,
         "market_cap": 2.0e11, "dividend_yield": 0.06,
         "industry_pe_percentile": 0.10, "industry_pb_percentile": 0.06,
         "industry_ps_percentile": 0.08,
         "_industry_level": "SW1", "_industry_name": "银行",
         "_peer_count": 42, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.05,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
        {"max_action": "观察"},
        known_limitations=["fundamental_data 为空，评分引擎降级处理"],
    ))

    samples.append(_make_stock_sample(
        "hist_miss_fund_601398_2023q4", "601398.SH", "工商银行(缺基本面)", "2023-12-29",
        ["stock", "large_cap", "missing_fundamental", "financial"],
        {"change_20d": 0.01, "change_60d": -0.02, "ma20_position": "near",
         "ma60_position": "near", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.06, "volatility_60d": 0.15},
        {},
        {"pe_ttm": 5.0, "pb_mrq": 0.55, "ps_ttm": 2.0,
         "pe_percentile": 0.06, "pb_percentile": 0.04, "ps_percentile": 0.05,
         "market_cap": 1.8e12, "dividend_yield": 0.065,
         "industry_pe_percentile": 0.08, "industry_pb_percentile": 0.05,
         "industry_ps_percentile": 0.06,
         "_industry_level": "SW1", "_industry_name": "银行",
         "_peer_count": 42, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"return_20d": 0.01, "return_60d": 0.02, "return_120d": 0.04,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04,
         "max_drawdown_120d": -0.06},
        {"max_action": "观察"},
        known_limitations=["fundamental_data 为空"],
    ))

    samples.append(_make_stock_sample(
        "hist_miss_fund_600028_2024q2", "600028.SH", "中国石化(缺基本面)", "2024-06-28",
        ["stock", "large_cap", "missing_fundamental", "energy"],
        {"change_20d": -0.01, "change_60d": 0.03, "ma20_position": "below",
         "ma60_position": "above", "avg_turnover_20d": 2.5e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.20},
        {},
        {"pe_ttm": 10.0, "pb_mrq": 0.9, "ps_ttm": 0.4,
         "pe_percentile": 0.20, "pb_percentile": 0.15, "ps_percentile": 0.12,
         "market_cap": 7.0e11, "dividend_yield": 0.05,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.18,
         "industry_ps_percentile": 0.15,
         "_industry_level": "SW1", "_industry_name": "石油石化",
         "_peer_count": 30, "_valid_peer_count_pe": 25,
         "_valid_peer_count_pb": 28, "_valid_peer_count_ps": 22},
        {"return_20d": -0.01, "return_60d": 0.02, "return_120d": 0.04,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.07},
        {"max_action": "观察"},
        known_limitations=["fundamental_data 为空"],
    ))

    # ── 5. 行业样本不足 ──────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_industry_insuf_830799_2024q1", "830799.BJ", "艾融软件", "2024-03-29",
        ["stock", "small_or_mid_cap", "industry_insufficient_peers",
         "it_services"],
        {"change_20d": 0.12, "change_60d": 0.25, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 5e7,
         "max_drawdown_60d": -0.15, "volatility_60d": 0.45},
        {"roe": 0.15, "gross_margin": 0.45, "net_profit_growth": 0.20,
         "debt_ratio": 0.30},
        {"pe_ttm": 25.0, "pb_mrq": 5.0, "ps_ttm": 8.0,
         "pe_percentile": 0.40, "pb_percentile": 0.45, "ps_percentile": 0.42,
         "market_cap": 5e9, "dividend_yield": 0.01,
         "industry_pe_percentile": None, "industry_pb_percentile": None,
         "industry_ps_percentile": None,
         "industry_pe_percentile_missing_reason": "insufficient_peer_samples",
         "industry_valuation_warnings": ["行业样本不足，无法计算行业分位"],
         "_industry_level": "SW2", "_industry_name": "软件和信息技术服务业",
         "_peer_count": 8, "_valid_peer_count_pe": 3,
         "_valid_peer_count_pb": 4, "_valid_peer_count_ps": 3},
        {"return_20d": 0.10, "return_60d": 0.20, "return_120d": 0.30,
         "relative_return_20d": 0.08, "relative_return_60d": 0.15,
         "relative_return_120d": 0.22,
         "max_drawdown_20d": -0.08, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
        {"industry_percentile_may_be_missing": True},
    ))

    samples.append(_make_stock_sample(
        "hist_industry_insuf_430047_2023q4", "430047.BJ", "诺思兰德", "2023-12-29",
        ["stock", "small_or_mid_cap", "industry_insufficient_peers", "pharma",
         "bear_market"],
        {"change_20d": -0.15, "change_60d": -0.30, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 2e7,
         "max_drawdown_60d": -0.40, "volatility_60d": 0.55},
        {"roe": -0.08, "gross_margin": 0.20, "net_profit_growth": -0.5,
         "debt_ratio": 0.40},
        {"pe_ttm": None, "pb_mrq": 8.0, "ps_ttm": 50.0,
         "pe_percentile": None, "pb_percentile": 0.70, "ps_percentile": 0.80,
         "market_cap": 3e9, "dividend_yield": 0.0,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
         "industry_pe_percentile": None, "industry_pb_percentile": None,
         "industry_ps_percentile": None,
         "industry_valuation_warnings": ["行业样本不足"],
         "_industry_level": "SW2", "_industry_name": "医药制造业",
         "_peer_count": 5, "_valid_peer_count_pe": 2,
         "_valid_peer_count_pb": 3, "_valid_peer_count_ps": 2},
        {"return_20d": -0.10, "return_60d": -0.20, "return_120d": -0.15,
         "relative_return_20d": -0.05, "relative_return_60d": -0.10,
         "relative_return_120d": -0.08,
         "max_drawdown_20d": -0.15, "max_drawdown_60d": -0.25,
         "max_drawdown_120d": -0.30},
        {"max_action": "谨慎观察", "industry_percentile_may_be_missing": True},
    ))

    samples.append(_make_stock_sample(
        "hist_industry_insuf_831856_2024q2", "831856.BJ", "浙江大农", "2024-06-28",
        ["stock", "small_or_mid_cap", "industry_insufficient_peers",
         "manufacturing"],
        {"change_20d": 0.03, "change_60d": 0.05, "ma20_position": "above",
         "ma60_position": "near", "avg_turnover_20d": 1e7,
         "max_drawdown_60d": -0.12, "volatility_60d": 0.40},
        {"roe": 0.10, "gross_margin": 0.30, "net_profit_growth": 0.05,
         "debt_ratio": 0.35},
        {"pe_ttm": 18.0, "pb_mrq": 3.0, "ps_ttm": 5.0,
         "pe_percentile": 0.30, "pb_percentile": 0.35, "ps_percentile": 0.32,
         "market_cap": 2e9, "dividend_yield": 0.02,
         "industry_pe_percentile": None, "industry_pb_percentile": None,
         "industry_ps_percentile": None,
         "industry_valuation_warnings": ["北交所部分行业样本不足"],
         "_industry_level": "SW3", "_industry_name": "专用设备制造业",
         "_peer_count": 6, "_valid_peer_count_pe": 2,
         "_valid_peer_count_pb": 3, "_valid_peer_count_ps": 2},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.06,
         "relative_return_20d": 0.01, "relative_return_60d": 0.02,
         "relative_return_120d": 0.03,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.10},
        {"industry_percentile_may_be_missing": True},
    ))

    # ── 6. 极端下跌 ──────────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_extreme_002594_2022q4", "002594.SZ", "比亚迪(极端下跌)", "2022-12-30",
        ["stock", "small_or_mid_cap", "extreme_drawdown", "auto",
         "bear_market", "high_volatility"],
        {"change_20d": -0.15, "change_60d": -0.35, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 8e9,
         "max_drawdown_60d": -0.45, "volatility_60d": 0.48},
        {"roe": 0.08, "gross_margin": 0.17, "net_profit_growth": 0.50,
         "debt_ratio": 0.78},
        {"pe_ttm": 50.0, "pb_mrq": 6.0, "ps_ttm": 2.5,
         "pe_percentile": 0.70, "pb_percentile": 0.60, "ps_percentile": 0.65,
         "market_cap": 5.5e11, "dividend_yield": 0.0,
         "industry_pe_percentile": 0.65, "industry_pb_percentile": 0.55,
         "industry_ps_percentile": 0.60,
         "_industry_level": "SW1", "_industry_name": "汽车",
         "_peer_count": 60, "_valid_peer_count_pe": 52,
         "_valid_peer_count_pb": 55, "_valid_peer_count_ps": 48},
        {"return_20d": -0.08, "return_60d": -0.15, "return_120d": -0.10,
         "relative_return_20d": -0.04, "relative_return_60d": -0.08,
         "relative_return_120d": -0.05,
         "max_drawdown_20d": -0.12, "max_drawdown_60d": -0.20,
         "max_drawdown_120d": -0.25},
        {"max_action": "观察"},
    ))

    samples.append(_make_stock_sample(
        "hist_extreme_600036_2022q4", "600036.SH", "招商银行(极端下跌)", "2022-10-28",
        ["stock", "large_cap", "extreme_drawdown", "financial", "bear_market"],
        {"change_20d": -0.12, "change_60d": -0.28, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 4e9,
         "max_drawdown_60d": -0.35, "volatility_60d": 0.30},
        {"roe": 0.16, "gross_margin": 0.35, "net_profit_growth": 0.12,
         "debt_ratio": 0.92},
        {"pe_ttm": 5.5, "pb_mrq": 0.75, "ps_ttm": 2.2,
         "pe_percentile": 0.05, "pb_percentile": 0.02, "ps_percentile": 0.04,
         "market_cap": 9.0e11, "dividend_yield": 0.06,
         "industry_pe_percentile": 0.06, "industry_pb_percentile": 0.03,
         "industry_ps_percentile": 0.05,
         "_industry_level": "SW1", "_industry_name": "银行",
         "_peer_count": 42, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"return_20d": -0.06, "return_60d": -0.10, "return_120d": -0.05,
         "relative_return_20d": -0.03, "relative_return_60d": -0.05,
         "relative_return_120d": -0.02,
         "max_drawdown_20d": -0.10, "max_drawdown_60d": -0.18,
         "max_drawdown_120d": -0.22},
        {"max_action": "观察"},
    ))

    samples.append(_make_stock_sample(
        "hist_extreme_300750_2022q2", "300750.SZ", "宁德时代(极端下跌)", "2022-04-29",
        ["stock", "large_cap", "extreme_drawdown", "new_energy",
         "bear_market", "high_volatility"],
        {"change_20d": -0.20, "change_60d": -0.40, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 1e10,
         "max_drawdown_60d": -0.50, "volatility_60d": 0.55},
        {"roe": 0.15, "gross_margin": 0.22, "net_profit_growth": 0.25,
         "debt_ratio": 0.68},
        {"pe_ttm": 60.0, "pb_mrq": 10.0, "ps_ttm": 8.0,
         "pe_percentile": 0.80, "pb_percentile": 0.75, "ps_percentile": 0.78,
         "market_cap": 1.0e12, "dividend_yield": 0.0,
         "industry_pe_percentile": 0.75, "industry_pb_percentile": 0.70,
         "industry_ps_percentile": 0.72,
         "_industry_level": "SW1", "_industry_name": "电力设备",
         "_peer_count": 70, "_valid_peer_count_pe": 58,
         "_valid_peer_count_pb": 62, "_valid_peer_count_ps": 55},
        {"return_20d": -0.10, "return_60d": -0.18, "return_120d": -0.12,
         "relative_return_20d": -0.05, "relative_return_60d": -0.10,
         "relative_return_120d": -0.06,
         "max_drawdown_20d": -0.15, "max_drawdown_60d": -0.25,
         "max_drawdown_120d": -0.30},
        {"max_action": "观察"},
    ))

    samples.append(_make_stock_sample(
        "hist_extreme_000001_2024q1", "000001.SZ", "平安银行(高波动)", "2024-01-31",
        ["stock", "large_cap", "high_volatility", "financial"],
        {"change_20d": -0.08, "change_60d": -0.15, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 2.5e9,
         "max_drawdown_60d": -0.20, "volatility_60d": 0.32},
        {"roe": 0.10, "gross_margin": 0.30, "net_profit_growth": 0.02,
         "debt_ratio": 0.92},
        {"pe_ttm": 4.8, "pb_mrq": 0.55, "ps_ttm": 1.5,
         "pe_percentile": 0.05, "pb_percentile": 0.03, "ps_percentile": 0.04,
         "market_cap": 2.0e11, "dividend_yield": 0.065,
         "industry_pe_percentile": 0.06, "industry_pb_percentile": 0.04,
         "industry_ps_percentile": 0.05,
         "_industry_level": "SW1", "_industry_name": "银行",
         "_peer_count": 42, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"return_20d": -0.05, "return_60d": -0.08, "return_120d": -0.05,
         "relative_return_20d": -0.02, "relative_return_60d": -0.04,
         "relative_return_120d": -0.02,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
        {"max_action": "观察"},
    ))

    # ── 7. 财报窗口 ──────────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_earnings_000333_2024q1", "000333.SZ", "美的集团", "2024-03-29",
        ["stock", "large_cap", "consumer_appliance", "earnings_window"],
        {"change_20d": 0.05, "change_60d": 0.08, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.06, "volatility_60d": 0.20},
        {"roe": 0.22, "gross_margin": 0.26, "net_profit_growth": 0.12,
         "debt_ratio": 0.62},
        {"pe_ttm": 14.0, "pb_mrq": 3.5, "ps_ttm": 1.8,
         "pe_percentile": 0.22, "pb_percentile": 0.28, "ps_percentile": 0.25,
         "market_cap": 4.5e11, "dividend_yield": 0.035,
         "industry_pe_percentile": 0.20, "industry_pb_percentile": 0.25,
         "industry_ps_percentile": 0.22,
         "_industry_level": "SW1", "_industry_name": "家用电器",
         "_peer_count": 45, "_valid_peer_count_pe": 38,
         "_valid_peer_count_pb": 40, "_valid_peer_count_ps": 35},
        {"recent_news_sentiment": "positive", "policy_risk": "low",
         "event_summary": {"critical_count": 0, "high_count": 0},
         "events": [{"severity": "low", "sentiment": "positive",
                     "title": "2024Q1 营收增长"}]},
        {"return_20d": 0.04, "return_60d": 0.07, "return_120d": 0.10,
         "relative_return_20d": 0.02, "relative_return_60d": 0.04,
         "relative_return_120d": 0.06,
         "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04,
         "max_drawdown_120d": -0.06},
        {"min_score": 60},
    ))

    samples.append(_make_stock_sample(
        "hist_earnings_601012_2023q4", "601012.SH", "隆基绿能", "2023-12-29",
        ["stock", "large_cap", "new_energy", "earnings_window",
         "high_volatility"],
        {"change_20d": -0.08, "change_60d": -0.20, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 4e9,
         "max_drawdown_60d": -0.28, "volatility_60d": 0.38},
        {"roe": 0.08, "gross_margin": 0.15, "net_profit_growth": -0.30,
         "debt_ratio": 0.55},
        {"pe_ttm": 18.0, "pb_mrq": 2.5, "ps_ttm": 1.2,
         "pe_percentile": 0.30, "pb_percentile": 0.25, "ps_percentile": 0.22,
         "market_cap": 1.5e11, "dividend_yield": 0.015,
         "industry_pe_percentile": 0.28, "industry_pb_percentile": 0.22,
         "industry_ps_percentile": 0.20,
         "_industry_level": "SW1", "_industry_name": "电力设备",
         "_peer_count": 70, "_valid_peer_count_pe": 58,
         "_valid_peer_count_pb": 62, "_valid_peer_count_ps": 55},
        {"return_20d": -0.05, "return_60d": -0.10, "return_120d": -0.08,
         "relative_return_20d": -0.02, "relative_return_60d": -0.05,
         "relative_return_120d": -0.03,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
    ))

    samples.append(_make_stock_sample(
        "hist_earnings_002371_2024q2", "002371.SZ", "北方华创", "2024-06-28",
        ["stock", "small_or_mid_cap", "semiconductor", "earnings_window",
         "growth"],
        {"change_20d": 0.12, "change_60d": 0.22, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.35},
        {"roe": 0.18, "gross_margin": 0.42, "net_profit_growth": 0.40,
         "debt_ratio": 0.38},
        {"pe_ttm": 45.0, "pb_mrq": 8.0, "ps_ttm": 12.0,
         "pe_percentile": 0.65, "pb_percentile": 0.70, "ps_percentile": 0.68,
         "market_cap": 2.5e11, "dividend_yield": 0.002,
         "industry_pe_percentile": 0.60, "industry_pb_percentile": 0.65,
         "industry_ps_percentile": 0.62,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"recent_news_sentiment": "positive", "policy_risk": "medium",
         "event_summary": {"critical_count": 0, "high_count": 0},
         "events": [{"severity": "low", "sentiment": "positive",
                     "title": "半导体设备订单增长"}]},
        {"return_20d": 0.08, "return_60d": 0.15, "return_120d": 0.20,
         "relative_return_20d": 0.05, "relative_return_60d": 0.10,
         "relative_return_120d": 0.14,
         "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.12},
        {"min_score": 55},
    ))

    # ── 8. ETF 样本 ──────────────────────────────────────────

    samples.append(_make_etf_sample(
        "hist_etf_510300_2024q1", "510300.SH", "华泰柏瑞沪深300ETF", "2024-03-29",
        ["etf", "large_cap", "broad_market"],
        {"change_20d": 0.03, "change_60d": 0.05, "ma20_position": "above",
         "ma60_position": "near", "avg_turnover_20d": 15e9,
         "max_drawdown_60d": -0.06, "volatility_60d": 0.15},
        {"market_price": 3.85, "fund_nav": 3.84, "premium_discount": 0.002,
         "fund_size": 1.5e11, "tracking_index": "沪深300",
         "tracking_error": 0.001},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.06,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04,
         "max_drawdown_120d": -0.05},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_510500_2023q4", "510500.SH", "南方中证500ETF", "2023-12-29",
        ["etf", "small_or_mid_cap", "broad_market", "bear_market"],
        {"change_20d": -0.05, "change_60d": -0.12, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 5e9,
         "max_drawdown_60d": -0.18, "volatility_60d": 0.22},
        {"market_price": 5.80, "fund_nav": 5.78, "premium_discount": 0.003,
         "fund_size": 5.0e10, "tracking_index": "中证500",
         "tracking_error": 0.002},
        {"return_20d": -0.03, "return_60d": -0.08, "return_120d": -0.05,
         "relative_return_20d": -0.01, "relative_return_60d": -0.04,
         "relative_return_120d": -0.02,
         "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.10,
         "max_drawdown_120d": -0.12},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_159915_2024q2", "159915.SZ", "易方达创业板ETF", "2024-06-28",
        ["etf", "small_or_mid_cap", "growth"],
        {"change_20d": 0.06, "change_60d": 0.10, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 8e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.25},
        {"market_price": 2.10, "fund_nav": 2.09, "premium_discount": 0.005,
         "fund_size": 8.0e10, "tracking_index": "创业板指",
         "tracking_error": 0.003},
        {"return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.12,
         "relative_return_20d": 0.02, "relative_return_60d": 0.05,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_588000_2023q3", "588000.SH", "华夏科创50ETF", "2023-09-29",
        ["etf", "small_or_mid_cap", "tech", "bear_market"],
        {"change_20d": -0.04, "change_60d": -0.10, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 4e9,
         "max_drawdown_60d": -0.15, "volatility_60d": 0.28},
        {"market_price": 0.95, "fund_nav": 0.94, "premium_discount": 0.01,
         "fund_size": 6.0e10, "tracking_index": "科创50",
         "tracking_error": 0.004},
        {"return_20d": -0.02, "return_60d": -0.06, "return_120d": -0.04,
         "relative_return_20d": 0.0, "relative_return_60d": -0.02,
         "relative_return_120d": -0.01,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.10},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_518880_2024q1", "518880.SH", "华安黄金ETF", "2024-03-29",
        ["etf", "gold", "commodity"],
        {"change_20d": 0.04, "change_60d": 0.08, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.03, "volatility_60d": 0.12},
        {"market_price": 5.50, "fund_nav": 5.48, "premium_discount": 0.004,
         "fund_size": 1.2e11, "tracking_index": "Au99.99",
         "tracking_error": 0.001},
        {"return_20d": 0.03, "return_60d": 0.06, "return_120d": 0.10,
         "relative_return_20d": 0.01, "relative_return_60d": 0.03,
         "relative_return_120d": 0.05,
         "max_drawdown_20d": -0.01, "max_drawdown_60d": -0.02,
         "max_drawdown_120d": -0.03},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_159941_2023q4", "159941.SZ", "纳指ETF", "2023-12-29",
        ["etf", "us_market", "tech"],
        {"change_20d": 0.05, "change_60d": 0.12, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.05, "volatility_60d": 0.18},
        {"market_price": 1.60, "fund_nav": 1.58, "premium_discount": 0.012,
         "fund_size": 3.0e10, "tracking_index": "纳斯达克100",
         "tracking_error": 0.005},
        {"return_20d": 0.04, "return_60d": 0.10, "return_120d": 0.15,
         "relative_return_20d": 0.02, "relative_return_60d": 0.06,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04,
         "max_drawdown_120d": -0.05},
    ))

    samples.append(_make_etf_sample(
        "hist_etf_511010_2024q1", "511010.SH", "国泰上证5年期国债ETF", "2024-03-29",
        ["etf", "bond", "low_volatility"],
        {"change_20d": 0.005, "change_60d": 0.012, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 5e8,
         "max_drawdown_60d": -0.008, "volatility_60d": 0.03},
        {"market_price": 120.5, "fund_nav": 120.3, "premium_discount": 0.002,
         "fund_size": 8.0e10, "tracking_index": "上证5年期国债",
         "tracking_error": 0.0005},
        {"return_20d": 0.004, "return_60d": 0.010, "return_120d": 0.018,
         "relative_return_20d": 0.0, "relative_return_60d": 0.002,
         "relative_return_120d": 0.005,
         "max_drawdown_20d": -0.002, "max_drawdown_60d": -0.005,
         "max_drawdown_120d": -0.007},
    ))

    # ── 9. 高估值 ──────────────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_high_val_300750_2024q2", "300750.SZ", "宁德时代(高估值)", "2024-06-28",
        ["stock", "large_cap", "new_energy", "growth"],
        {"change_20d": 0.10, "change_60d": 0.18, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 1e10,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.30},
        {"roe": 0.18, "gross_margin": 0.22, "net_profit_growth": 0.20,
         "debt_ratio": 0.65},
        {"pe_ttm": 35.0, "pb_mrq": 6.5, "ps_ttm": 4.0,
         "pe_percentile": 0.85, "pb_percentile": 0.80, "ps_percentile": 0.82,
         "market_cap": 1.2e12, "dividend_yield": 0.003,
         "industry_pe_percentile": 0.80, "industry_pb_percentile": 0.75,
         "industry_ps_percentile": 0.78,
         "_industry_level": "SW1", "_industry_name": "电力设备",
         "_peer_count": 70, "_valid_peer_count_pe": 58,
         "_valid_peer_count_pb": 62, "_valid_peer_count_ps": 55},
        {"return_20d": 0.06, "return_60d": 0.10, "return_120d": 0.15,
         "relative_return_20d": 0.03, "relative_return_60d": 0.06,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
        {"max_score": 80},
    ))

    samples.append(_make_stock_sample(
        "hist_high_val_688981_2024q1", "688981.SH", "中芯国际(高估值)", "2024-03-29",
        ["stock", "large_cap", "semiconductor", "high_volatility"],
        {"change_20d": 0.06, "change_60d": 0.12, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 5e9,
         "max_drawdown_60d": -0.15, "volatility_60d": 0.40},
        {"roe": 0.05, "gross_margin": 0.20, "net_profit_growth": -0.10,
         "debt_ratio": 0.45},
        {"pe_ttm": 80.0, "pb_mrq": 3.5, "ps_ttm": 8.0,
         "pe_percentile": 0.90, "pb_percentile": 0.60, "ps_percentile": 0.85,
         "market_cap": 4.0e11, "dividend_yield": 0.0,
         "industry_pe_percentile": 0.88, "industry_pb_percentile": 0.55,
         "industry_ps_percentile": 0.82,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.12,
         "relative_return_20d": 0.02, "relative_return_60d": 0.05,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.10,
         "max_drawdown_120d": -0.12},
        {"max_score": 75},
    ))

    # ── 10. 更多蓝筹覆盖 ──────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_600900_2024q2_defensive", "600900.SH", "长江电力", "2024-06-28",
        ["stock", "large_cap", "utility", "low_volatility", "defensive"],
        {"change_20d": 0.02, "change_60d": 0.04, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.03, "volatility_60d": 0.10},
        {"roe": 0.15, "gross_margin": 0.62, "net_profit_growth": 0.08,
         "debt_ratio": 0.55},
        {"pe_ttm": 22.0, "pb_mrq": 4.2, "ps_ttm": 7.5,
         "pe_percentile": 0.55, "pb_percentile": 0.60, "ps_percentile": 0.58,
         "market_cap": 6.5e11, "dividend_yield": 0.032,
         "industry_pe_percentile": 0.50, "industry_pb_percentile": 0.55,
         "industry_ps_percentile": 0.52,
         "_industry_level": "SW1", "_industry_name": "公用事业",
         "_peer_count": 50, "_valid_peer_count_pe": 42,
         "_valid_peer_count_pb": 45, "_valid_peer_count_ps": 38},
        {"return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.05,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.01, "max_drawdown_60d": -0.02,
         "max_drawdown_120d": -0.03},
        {"min_score": 60, "max_score": 90},
    ))

    samples.append(_make_stock_sample(
        "hist_000568_2024q1_consumer", "000568.SZ", "泸州老窖", "2024-03-29",
        ["stock", "large_cap", "consumer", "earnings_window"],
        {"change_20d": 0.04, "change_60d": 0.06, "ma20_position": "above",
         "ma60_position": "near", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.20},
        {"roe": 0.30, "gross_margin": 0.85, "net_profit_growth": 0.20,
         "debt_ratio": 0.25},
        {"pe_ttm": 25.0, "pb_mrq": 8.0, "ps_ttm": 12.0,
         "pe_percentile": 0.38, "pb_percentile": 0.42, "ps_percentile": 0.40,
         "market_cap": 3.0e11, "dividend_yield": 0.02,
         "industry_pe_percentile": 0.35, "industry_pb_percentile": 0.40,
         "industry_ps_percentile": 0.38,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"return_20d": 0.03, "return_60d": 0.05, "return_120d": 0.08,
         "relative_return_20d": 0.01, "relative_return_60d": 0.02,
         "relative_return_120d": 0.04,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.07},
    ))

    samples.append(_make_stock_sample(
        "hist_601888_2024q2_consumer", "601888.SH", "中国中免", "2024-06-28",
        ["stock", "large_cap", "consumer", "high_volatility"],
        {"change_20d": -0.03, "change_60d": -0.08, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.15, "volatility_60d": 0.32},
        {"roe": 0.18, "gross_margin": 0.35, "net_profit_growth": 0.15,
         "debt_ratio": 0.40},
        {"pe_ttm": 30.0, "pb_mrq": 5.0, "ps_ttm": 3.5,
         "pe_percentile": 0.48, "pb_percentile": 0.45, "ps_percentile": 0.42,
         "market_cap": 3.5e11, "dividend_yield": 0.01,
         "industry_pe_percentile": 0.45, "industry_pb_percentile": 0.42,
         "industry_ps_percentile": 0.40,
         "_industry_level": "SW1", "_industry_name": "商贸零售",
         "_peer_count": 65, "_valid_peer_count_pe": 55,
         "_valid_peer_count_pb": 58, "_valid_peer_count_ps": 50},
        {"return_20d": -0.02, "return_60d": -0.05, "return_120d": -0.03,
         "relative_return_20d": 0.0, "relative_return_60d": -0.02,
         "relative_return_120d": -0.01,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.10},
    ))

    # ── 11. 更多行业覆盖 ──────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_601088_2024q1_energy", "601088.SH", "中国神华", "2024-03-29",
        ["stock", "large_cap", "energy", "low_valuation"],
        {"change_20d": 0.03, "change_60d": 0.05, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.06, "volatility_60d": 0.18},
        {"roe": 0.15, "gross_margin": 0.30, "net_profit_growth": -0.05,
         "debt_ratio": 0.35},
        {"pe_ttm": 10.0, "pb_mrq": 1.8, "ps_ttm": 2.2,
         "pe_percentile": 0.20, "pb_percentile": 0.25, "ps_percentile": 0.22,
         "market_cap": 8.0e11, "dividend_yield": 0.055,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.28,
         "industry_ps_percentile": 0.25,
         "_industry_level": "SW1", "_industry_name": "煤炭",
         "_peer_count": 35, "_valid_peer_count_pe": 30,
         "_valid_peer_count_pb": 32, "_valid_peer_count_ps": 28},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.06,
         "relative_return_20d": 0.01, "relative_return_60d": 0.02,
         "relative_return_120d": 0.03,
         "max_drawdown_20d": -0.02, "max_drawdown_60d": -0.04,
         "max_drawdown_120d": -0.06},
        {"min_score": 50},
    ))

    samples.append(_make_stock_sample(
        "hist_600585_2024q2_industrial", "600585.SH", "海螺水泥", "2024-06-28",
        ["stock", "large_cap", "industrial", "low_valuation"],
        {"change_20d": -0.01, "change_60d": 0.02, "ma20_position": "below",
         "ma60_position": "near", "avg_turnover_20d": 1.5e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.22},
        {"roe": 0.10, "gross_margin": 0.28, "net_profit_growth": -0.10,
         "debt_ratio": 0.22},
        {"pe_ttm": 9.0, "pb_mrq": 1.1, "ps_ttm": 1.5,
         "pe_percentile": 0.18, "pb_percentile": 0.12, "ps_percentile": 0.14,
         "market_cap": 1.5e11, "dividend_yield": 0.04,
         "industry_pe_percentile": 0.20, "industry_pb_percentile": 0.14,
         "industry_ps_percentile": 0.16,
         "_industry_level": "SW1", "_industry_name": "建筑材料",
         "_peer_count": 55, "_valid_peer_count_pe": 48,
         "_valid_peer_count_pb": 50, "_valid_peer_count_ps": 42},
        {"return_20d": -0.01, "return_60d": 0.01, "return_120d": 0.03,
         "relative_return_20d": 0.0, "relative_return_60d": 0.0,
         "relative_return_120d": 0.01,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.07},
    ))

    samples.append(_make_stock_sample(
        "hist_002415_2024q1_tech", "002415.SZ", "海康威视", "2024-03-29",
        ["stock", "large_cap", "electronics", "ai"],
        {"change_20d": 0.05, "change_60d": 0.10, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 4e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.28},
        {"roe": 0.20, "gross_margin": 0.44, "net_profit_growth": 0.10,
         "debt_ratio": 0.40},
        {"pe_ttm": 22.0, "pb_mrq": 5.0, "ps_ttm": 5.5,
         "pe_percentile": 0.35, "pb_percentile": 0.40, "ps_percentile": 0.38,
         "market_cap": 3.5e11, "dividend_yield": 0.025,
         "industry_pe_percentile": 0.32, "industry_pb_percentile": 0.38,
         "industry_ps_percentile": 0.35,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.12,
         "relative_return_20d": 0.02, "relative_return_60d": 0.05,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
    ))

    samples.append(_make_stock_sample(
        "hist_002304_2024q2_consumer", "002304.SZ", "洋河股份", "2024-06-28",
        ["stock", "small_or_mid_cap", "consumer"],
        {"change_20d": -0.02, "change_60d": -0.05, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 1.5e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.22},
        {"roe": 0.20, "gross_margin": 0.72, "net_profit_growth": 0.08,
         "debt_ratio": 0.28},
        {"pe_ttm": 18.0, "pb_mrq": 4.5, "ps_ttm": 6.0,
         "pe_percentile": 0.28, "pb_percentile": 0.32, "ps_percentile": 0.30,
         "market_cap": 2.0e11, "dividend_yield": 0.035,
         "industry_pe_percentile": 0.25, "industry_pb_percentile": 0.30,
         "industry_ps_percentile": 0.28,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"return_20d": -0.01, "return_60d": -0.03, "return_120d": -0.02,
         "relative_return_20d": 0.0, "relative_return_60d": -0.01,
         "relative_return_120d": 0.0,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
    ))

    # ── 12. 北交所 / 小市值 ────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_830946_2024q1_bse", "830946.BJ", "森萱医药", "2024-03-29",
        ["stock", "small_or_mid_cap", "pharma", "bse"],
        {"change_20d": 0.08, "change_60d": 0.15, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e7,
         "max_drawdown_60d": -0.12, "volatility_60d": 0.45},
        {"roe": 0.12, "gross_margin": 0.40, "net_profit_growth": 0.10,
         "debt_ratio": 0.25},
        {"pe_ttm": 20.0, "pb_mrq": 3.5, "ps_ttm": 6.0,
         "pe_percentile": 0.35, "pb_percentile": 0.38, "ps_percentile": 0.36,
         "market_cap": 3e9, "dividend_yield": 0.015,
         "industry_pe_percentile": 0.32, "industry_pb_percentile": 0.35,
         "industry_ps_percentile": 0.33,
         "_industry_level": "SW2", "_industry_name": "医药制造业",
         "_peer_count": 85, "_valid_peer_count_pe": 70,
         "_valid_peer_count_pb": 72, "_valid_peer_count_ps": 65},
        {"return_20d": 0.06, "return_60d": 0.12, "return_120d": 0.18,
         "relative_return_20d": 0.04, "relative_return_60d": 0.08,
         "relative_return_120d": 0.12,
         "max_drawdown_20d": -0.05, "max_drawdown_60d": -0.08,
         "max_drawdown_120d": -0.10},
    ))

    samples.append(_make_stock_sample(
        "hist_837592_2024q2_bse", "837592.BJ", "华信永道", "2024-06-28",
        ["stock", "small_or_mid_cap", "it_services", "bse",
         "industry_insufficient_peers"],
        {"change_20d": 0.05, "change_60d": 0.08, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 5e7,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.42},
        {"roe": 0.10, "gross_margin": 0.35, "net_profit_growth": 0.05,
         "debt_ratio": 0.30},
        {"pe_ttm": 22.0, "pb_mrq": 4.0, "ps_ttm": 7.0,
         "pe_percentile": 0.38, "pb_percentile": 0.40, "ps_percentile": 0.38,
         "market_cap": 2e9, "dividend_yield": 0.01,
         "industry_pe_percentile": None, "industry_pb_percentile": None,
         "industry_ps_percentile": None,
         "industry_valuation_warnings": ["北交所IT服务行业样本不足"],
         "_industry_level": "SW3", "_industry_name": "软件和信息技术服务业",
         "_peer_count": 5, "_valid_peer_count_pe": 2,
         "_valid_peer_count_pb": 3, "_valid_peer_count_ps": 2},
        {"return_20d": 0.03, "return_60d": 0.06, "return_120d": 0.08,
         "relative_return_20d": 0.01, "relative_return_60d": 0.03,
         "relative_return_120d": 0.04,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
        {"industry_percentile_may_be_missing": True},
    ))

    # ── 13. 高估值 + 财报窗口 ──────────────────────────────

    samples.append(_make_stock_sample(
        "hist_603288_2024q1_highpe", "603288.SH", "海天味业", "2024-03-29",
        ["stock", "large_cap", "consumer", "earnings_window"],
        {"change_20d": 0.02, "change_60d": -0.03, "ma20_position": "near",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.18},
        {"roe": 0.25, "gross_margin": 0.38, "net_profit_growth": 0.05,
         "debt_ratio": 0.30},
        {"pe_ttm": 45.0, "pb_mrq": 10.0, "ps_ttm": 12.0,
         "pe_percentile": 0.65, "pb_percentile": 0.70, "ps_percentile": 0.68,
         "market_cap": 3.0e11, "dividend_yield": 0.015,
         "industry_pe_percentile": 0.60, "industry_pb_percentile": 0.65,
         "industry_ps_percentile": 0.62,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"return_20d": 0.01, "return_60d": -0.02, "return_120d": 0.0,
         "relative_return_20d": 0.0, "relative_return_60d": -0.01,
         "relative_return_120d": 0.0,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
        {"max_score": 80},
    ))

    # ── 14. 极端下跌 + 亏损 ────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_extreme_loss_600019_2022q4", "600019.SH", "宝钢股份(极端亏损)", "2022-12-30",
        ["stock", "large_cap", "extreme_drawdown", "loss_making_or_invalid_pe",
         "industrial", "bear_market", "high_volatility"],
        {"change_20d": -0.18, "change_60d": -0.38, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.48, "volatility_60d": 0.45},
        {"roe": -0.05, "gross_margin": 0.02, "net_profit_growth": -3.0,
         "debt_ratio": 0.65},
        {"pe_ttm": None, "pb_mrq": 0.7, "ps_ttm": 0.3,
         "pe_percentile": None, "pb_percentile": 0.05, "ps_percentile": 0.04,
         "market_cap": 1.2e11, "dividend_yield": 0.0,
         "pe_ttm_missing_reason": "loss_making_or_invalid_pe",
         "industry_pe_percentile": None, "industry_pb_percentile": 0.08,
         "industry_ps_percentile": 0.06,
         "_industry_level": "SW1", "_industry_name": "钢铁",
         "_peer_count": 35, "_valid_peer_count_pe": 20,
         "_valid_peer_count_pb": 30, "_valid_peer_count_ps": 25},
        {"return_20d": -0.10, "return_60d": -0.18, "return_120d": -0.12,
         "relative_return_20d": -0.05, "relative_return_60d": -0.10,
         "relative_return_120d": -0.06,
         "max_drawdown_20d": -0.15, "max_drawdown_60d": -0.25,
         "max_drawdown_120d": -0.30},
        {"max_action": "回避", "forbidden_actions": ["分批买入", "买入"]},
    ))

    # ── 15. 新能源 + 高波动 ────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_002129_2024q1_newenergy", "002129.SZ", "TCL中环", "2024-03-29",
        ["stock", "small_or_mid_cap", "new_energy", "high_volatility"],
        {"change_20d": -0.06, "change_60d": -0.15, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.22, "volatility_60d": 0.40},
        {"roe": 0.05, "gross_margin": 0.12, "net_profit_growth": -0.40,
         "debt_ratio": 0.55},
        {"pe_ttm": 35.0, "pb_mrq": 2.5, "ps_ttm": 2.0,
         "pe_percentile": 0.50, "pb_percentile": 0.30, "ps_percentile": 0.35,
         "market_cap": 1.5e11, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.28,
         "industry_ps_percentile": 0.32,
         "_industry_level": "SW1", "_industry_name": "电力设备",
         "_peer_count": 70, "_valid_peer_count_pe": 58,
         "_valid_peer_count_pb": 62, "_valid_peer_count_ps": 55},
        {"return_20d": -0.04, "return_60d": -0.08, "return_120d": -0.05,
         "relative_return_20d": -0.02, "relative_return_60d": -0.04,
         "relative_return_120d": -0.02,
         "max_drawdown_20d": -0.06, "max_drawdown_60d": -0.12,
         "max_drawdown_120d": -0.15},
        {"max_action": "观察"},
    ))

    # ── 16-20. 补充更多场景 ────────────────────────────────

    samples.append(_make_stock_sample(
        "hist_000002_2024q1_realestate", "000002.SZ", "万科A", "2024-03-29",
        ["stock", "large_cap", "real_estate", "bear_market", "high_volatility"],
        {"change_20d": -0.10, "change_60d": -0.22, "ma20_position": "below",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.30, "volatility_60d": 0.40},
        {"roe": 0.02, "gross_margin": 0.18, "net_profit_growth": -0.60,
         "debt_ratio": 0.80},
        {"pe_ttm": 15.0, "pb_mrq": 0.6, "ps_ttm": 0.4,
         "pe_percentile": 0.25, "pb_percentile": 0.05, "ps_percentile": 0.06,
         "market_cap": 1.0e11, "dividend_yield": 0.02,
         "industry_pe_percentile": 0.22, "industry_pb_percentile": 0.06,
         "industry_ps_percentile": 0.07,
         "_industry_level": "SW1", "_industry_name": "房地产",
         "_peer_count": 70, "_valid_peer_count_pe": 55,
         "_valid_peer_count_pb": 58, "_valid_peer_count_ps": 50},
        {"return_20d": -0.08, "return_60d": -0.15, "return_120d": -0.10,
         "relative_return_20d": -0.05, "relative_return_60d": -0.10,
         "relative_return_120d": -0.06,
         "max_drawdown_20d": -0.12, "max_drawdown_60d": -0.20,
         "max_drawdown_120d": -0.25},
        {"max_action": "观察"},
    ))

    samples.append(_make_stock_sample(
        "hist_002049_2024q2_semiconductor", "002049.SZ", "紫光国微", "2024-06-28",
        ["stock", "small_or_mid_cap", "semiconductor", "growth"],
        {"change_20d": 0.08, "change_60d": 0.15, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 2.5e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.32},
        {"roe": 0.18, "gross_margin": 0.60, "net_profit_growth": 0.15,
         "debt_ratio": 0.25},
        {"pe_ttm": 40.0, "pb_mrq": 7.0, "ps_ttm": 10.0,
         "pe_percentile": 0.60, "pb_percentile": 0.65, "ps_percentile": 0.62,
         "market_cap": 1.8e11, "dividend_yield": 0.005,
         "industry_pe_percentile": 0.55, "industry_pb_percentile": 0.60,
         "industry_ps_percentile": 0.58,
         "_industry_level": "SW1", "_industry_name": "电子",
         "_peer_count": 120, "_valid_peer_count_pe": 100,
         "_valid_peer_count_pb": 105, "_valid_peer_count_ps": 95},
        {"return_20d": 0.06, "return_60d": 0.10, "return_120d": 0.15,
         "relative_return_20d": 0.04, "relative_return_60d": 0.07,
         "relative_return_120d": 0.10,
         "max_drawdown_20d": -0.04, "max_drawdown_60d": -0.07,
         "max_drawdown_120d": -0.10},
    ))

    samples.append(_make_stock_sample(
        "hist_601225_2023q4_coal", "601225.SH", "陕西煤业", "2023-12-29",
        ["stock", "large_cap", "energy", "low_valuation"],
        {"change_20d": 0.01, "change_60d": -0.02, "ma20_position": "near",
         "ma60_position": "below", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.10, "volatility_60d": 0.22},
        {"roe": 0.20, "gross_margin": 0.35, "net_profit_growth": -0.08,
         "debt_ratio": 0.38},
        {"pe_ttm": 8.5, "pb_mrq": 2.0, "ps_ttm": 1.8,
         "pe_percentile": 0.15, "pb_percentile": 0.20, "ps_percentile": 0.18,
         "market_cap": 2.5e11, "dividend_yield": 0.06,
         "industry_pe_percentile": 0.18, "industry_pb_percentile": 0.22,
         "industry_ps_percentile": 0.20,
         "_industry_level": "SW1", "_industry_name": "煤炭",
         "_peer_count": 35, "_valid_peer_count_pe": 30,
         "_valid_peer_count_pb": 32, "_valid_peer_count_ps": 28},
        {"return_20d": 0.01, "return_60d": 0.02, "return_120d": 0.04,
         "relative_return_20d": 0.0, "relative_return_60d": 0.01,
         "relative_return_120d": 0.02,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.06,
         "max_drawdown_120d": -0.08},
    ))

    samples.append(_make_stock_sample(
        "hist_600809_2024q1_consumer", "600809.SH", "山西汾酒", "2024-03-29",
        ["stock", "large_cap", "consumer", "earnings_window"],
        {"change_20d": 0.06, "change_60d": 0.10, "ma20_position": "above",
         "ma60_position": "above", "avg_turnover_20d": 3e9,
         "max_drawdown_60d": -0.07, "volatility_60d": 0.22},
        {"roe": 0.30, "gross_margin": 0.75, "net_profit_growth": 0.25,
         "debt_ratio": 0.30},
        {"pe_ttm": 35.0, "pb_mrq": 12.0, "ps_ttm": 14.0,
         "pe_percentile": 0.50, "pb_percentile": 0.55, "ps_percentile": 0.52,
         "market_cap": 3.5e11, "dividend_yield": 0.012,
         "industry_pe_percentile": 0.48, "industry_pb_percentile": 0.52,
         "industry_ps_percentile": 0.50,
         "_industry_level": "SW1", "_industry_name": "食品饮料",
         "_peer_count": 80, "_valid_peer_count_pe": 65,
         "_valid_peer_count_pb": 68, "_valid_peer_count_ps": 60},
        {"return_20d": 0.05, "return_60d": 0.08, "return_120d": 0.12,
         "relative_return_20d": 0.03, "relative_return_60d": 0.05,
         "relative_return_120d": 0.08,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.07},
    ))

    samples.append(_make_stock_sample(
        "hist_002352_2024q2_logistics", "002352.SZ", "顺丰控股", "2024-06-28",
        ["stock", "large_cap", "logistics"],
        {"change_20d": 0.03, "change_60d": 0.05, "ma20_position": "above",
         "ma60_position": "near", "avg_turnover_20d": 2e9,
         "max_drawdown_60d": -0.08, "volatility_60d": 0.22},
        {"roe": 0.12, "gross_margin": 0.12, "net_profit_growth": 0.15,
         "debt_ratio": 0.55},
        {"pe_ttm": 20.0, "pb_mrq": 2.5, "ps_ttm": 0.8,
         "pe_percentile": 0.30, "pb_percentile": 0.25, "ps_percentile": 0.22,
         "market_cap": 2.5e11, "dividend_yield": 0.015,
         "industry_pe_percentile": 0.28, "industry_pb_percentile": 0.22,
         "industry_ps_percentile": 0.20,
         "_industry_level": "SW1", "_industry_name": "交通运输",
         "_peer_count": 55, "_valid_peer_count_pe": 48,
         "_valid_peer_count_pb": 50, "_valid_peer_count_ps": 42},
        {"return_20d": 0.02, "return_60d": 0.04, "return_120d": 0.06,
         "relative_return_20d": 0.01, "relative_return_60d": 0.02,
         "relative_return_120d": 0.03,
         "max_drawdown_20d": -0.03, "max_drawdown_60d": -0.05,
         "max_drawdown_120d": -0.07},
    ))

    # 确保至少 50 个样本
    assert len(samples) >= 50, f"只生成了 {len(samples)} 个样本，需要至少 50 个"
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="构建历史回测样本池")
    parser.add_argument("--output", default="tests/fixtures/research_quality_historical_samples.json",
                        help="输出文件路径")
    parser.add_argument("--min-samples", type=int, default=50, help="最少样本数")
    parser.add_argument("--max-samples", type=int, default=200, help="最多样本数")
    parser.add_argument("--overwrite", action="store_true", help="覆盖现有 fixture")
    parser.add_argument("--as-of-start", default="2022-01-01", help="样本起始日期")
    parser.add_argument("--as-of-end", default="2024-12-31", help="样本结束日期")
    parser.add_argument("--symbols", default=None, help="股票列表文件或逗号分隔")
    parser.add_argument("--use-qmt", action="store_true", help="尝试从 QMT 获取真实数据")
    parser.add_argument("--require-qmt", action="store_true",
                        help="要求 QMT 可用，不可用时 exit 1（不回退 manual_snapshot）")
    parser.add_argument("--asset-scope", default=None,
                        help="资产范围过滤，如 mainboard-a")
    parser.add_argument("--start-year", type=int, default=2021,
                        help="样本 as_of 起始年份")
    parser.add_argument("--end-year", type=int, default=2026,
                        help="样本 as_of 结束年份")
    parser.add_argument("--benchmark", default="000300.SH",
                        help="基准指数 symbol，用于计算相对收益")
    parser.add_argument("--boundary-symbols", default=None,
                        help="边界样本股票列表，逗号分隔（覆盖默认）")
    args = parser.parse_args()

    output_path = PROJECT_ROOT / args.output

    # 检查是否已有 fixture
    if output_path.exists() and not args.overwrite:
        if args.use_qmt and args.require_qmt:
            print(
                "Error: --use-qmt --require-qmt must rebuild the fixture; "
                "pass --overwrite or choose a different --output.",
                file=sys.stderr,
            )
            return 2
        print(f"Fixture 已存在: {output_path}")
        print("使用 --overwrite 覆盖")
        return 0

    # 解析 symbols
    symbol_list: list[str] | None = None
    if args.symbols:
        if Path(args.symbols).exists():
            symbol_list = Path(args.symbols).read_text().strip().split("\n")
        else:
            symbol_list = [s.strip() for s in args.symbols.split(",")]

    # 解析 boundary symbols
    boundary: list[str] | None = None
    if args.boundary_symbols:
        boundary = [s.strip() for s in args.boundary_symbols.split(",")]

    # 尝试 QMT 模式
    samples = None
    source_info: dict[str, str] = {
        "price": "manual_snapshot",
        "fundamental": "manual_snapshot",
        "valuation": "manual_snapshot",
        "industry": "manual_snapshot",
    }
    build_metadata: dict[str, Any] = {}

    if args.use_qmt:
        from services.research.historical_sample_builder import try_build_from_qmt

        as_of_dates = None  # 使用默认生成

        result = try_build_from_qmt(
            symbols=symbol_list,
            as_of_dates=as_of_dates,
            benchmark_symbol=args.benchmark,
            start_year=args.start_year,
            end_year=args.end_year,
            max_samples=args.max_samples,
            boundary_symbols=boundary,
            asset_scope=args.asset_scope,
        )

        if result is not None:
            samples = result["samples"]
            source_info = result["source"]
            build_metadata["included"] = result.get("included", [])
            build_metadata["skipped"] = result.get("skipped", [])
            print(f"QMT 构建成功: {len(samples)} 个样本")
            if result.get("skipped"):
                print(f"  跳过 {len(result['skipped'])} 个 symbol")
        else:
            if args.require_qmt:
                print("错误：--require-qmt 但 QMT 不可用", file=sys.stderr)
                return 1
            print("QMT 不可用，回退到手动快照模式")
            print("提示：如需真实数据，请确保 MiniQMT 已启动且 xtquant 可用")

    # 使用手动快照
    if samples is None:
        if args.require_qmt and args.use_qmt:
            # 已经在上面处理了
            pass
        elif args.require_qmt:
            print("错误：--require-qmt 但未指定 --use-qmt", file=sys.stderr)
            return 1
        samples = _generate_manual_samples()

    # 截断到 max_samples
    if len(samples) > args.max_samples:
        samples = samples[:args.max_samples]

    # 验证最少样本数
    if len(samples) < args.min_samples:
        print(f"警告：样本数 {len(samples)} 少于要求的 {args.min_samples}")
        if args.require_qmt:
            return 1

    # 构建输出
    output: dict[str, Any] = {
        "version": 1,
        "generated_at": datetime.now(tz=None).isoformat() + "Z",
        "source": source_info,
        "samples": samples,
    }

    if build_metadata:
        output["build_metadata"] = build_metadata
    if args.asset_scope:
        output.setdefault("build_metadata", {})["asset_scope"] = args.asset_scope

    # 写入
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成 {len(samples)} 个样本: {output_path}")
    return 0


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    finally:
        _disconnect_xtdata_if_loaded()
    sys.exit(exit_code)
