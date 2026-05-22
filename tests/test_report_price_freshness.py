"""Tests for price freshness display in reports (layer 4 price fix).

Covers: stale warning, price source/status/date display, warning dedup,
JSON field preservation, LLM input slimming.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.agents.research_context import compact_research_result_for_llm
from services.report.json_builder import save_json_result
from services.report.markdown_builder import build_markdown_report

# ── Helpers ─────────────────────────────────────────────────────────

def _base_result(**overrides):
    """Minimal valid result dict for report generation."""
    data = {
        "symbol": "600519.SH",
        "name": "测试标的",
        "asset_type": "stock",
        "as_of": "2026-05-22",
        "data_source": "qmt",
        "score": 72,
        "rating": "B",
        "action": "观察",
        "max_position": "5%-8%",
        "final_opinion": "测试观点。",
        "score_breakdown": {
            "trend_momentum": 16,
            "liquidity": 13,
            "fundamental_quality": 16,
            "valuation": 10,
            "risk_control": 15,
            "event_policy": 2,
        },
        "price_data": {
            "close": 1688.0,
            "change_20d": 0.052,
            "change_60d": 0.083,
            "ma20_position": "above",
            "ma60_position": "above",
            "max_drawdown_60d": -0.092,
            "volatility_60d": 0.186,
            "avg_turnover_20d": 4_800_000_000,
            "data_vendor": "qmt",
            "latest_trade_date": "2026-05-21",
            "price_is_stale": False,
            "price_uses_intraday_tick": False,
            "latest_price_source": "qmt_kline",
            "price_history_source": "qmt",
        },
        "valuation_data": {
            "pe_ttm": 21.5,
            "pb_mrq": 5.2,
            "market_cap": 2_100_000_000_000,
            "pe_percentile": 0.42,
            "pb_percentile": 0.51,
        },
        "data_quality": {
            "overall_confidence": 0.85,
            "has_placeholder": False,
            "blocking_issues": [],
            "warnings": [],
        },
        "evidence_bundle": {"items": []},
        "decision_guard": {"enabled": False},
        "debate_result": {
            "bull_case": {"thesis": "多头"},
            "bear_case": {"thesis": "空头"},
            "risk_review": {"risk_summary": "风险"},
            "committee_conclusion": {
                "stance": "中性",
                "action": "观察",
                "confidence": 0.5,
                "final_opinion": "测试。",
            },
        },
        "source_metadata": {
            "qmt_status": {},
        },
        "data_warnings": [],
    }
    data.update(overrides)
    return data


# ── 1. Normal price_data ────────────────────────────────────────────

class TestNormalPriceData:
    def test_contains_trade_date(self):
        md = build_markdown_report(_base_result())
        assert "行情日期" in md
        assert "2026-05-21" in md

    def test_contains_price_source_qmt_kline(self):
        md = build_markdown_report(_base_result())
        assert "价格来源" in md
        assert "QMT 日 K" in md

    def test_contains_price_status_normal(self):
        md = build_markdown_report(_base_result())
        assert "行情状态" in md
        assert "正常" in md

    def test_no_stale_warning_when_fresh(self):
        md = build_markdown_report(_base_result())
        assert "行情数据可能过期" not in md

    def test_contains_price_history_source(self):
        md = build_markdown_report(_base_result())
        assert "价格历史序列" in md
        assert "QMT" in md


# ── 2. Stale price_data ────────────────────────────────────────────

class TestStalePriceData:
    def test_contains_stale_status(self):
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-05-14"

        md = build_markdown_report(result)
        assert "行情状态" in md
        assert "可能过期" in md

    def test_contains_stale_warning(self):
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-05-14"

        md = build_markdown_report(result)
        assert "行情数据可能过期" in md
        assert "2026-05-14" in md

    def test_stale_warning_mentions_impact(self):
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-05-14"

        md = build_markdown_report(result)
        assert "均线" in md or "涨跌幅" in md


# ── 3. Tick overlay ────────────────────────────────────────────────

class TestTickOverlay:
    def test_tick_overlay_source_display(self):
        result = _base_result()
        result["price_data"]["latest_price_source"] = "qmt_full_tick_overlay"
        result["price_data"]["price_uses_intraday_tick"] = True

        md = build_markdown_report(result)
        assert "QMT full tick 临时 bar" in md

    def test_tick_overlay_status_follows_stale(self):
        result = _base_result()
        result["price_data"]["latest_price_source"] = "qmt_full_tick_overlay"
        result["price_data"]["price_uses_intraday_tick"] = True
        result["price_data"]["price_is_stale"] = True

        md = build_markdown_report(result)
        assert "可能过期" in md


# ── 4. AKShare fallback ────────────────────────────────────────────

class TestAkshareFallback:
    def test_akshare_fallback_source_display(self):
        result = _base_result()
        result["price_data"]["latest_price_source"] = "akshare_price_history_fallback"
        result["price_data"]["price_history_source"] = "akshare"
        result["price_data"]["data_vendor"] = "eastmoney"

        md = build_markdown_report(result)
        assert "AKShare 行情 fallback" in md
        assert "eastmoney" in md or "东方财富" in md

    def test_akshare_fallback_history_source(self):
        result = _base_result()
        result["price_data"]["latest_price_source"] = "akshare_price_history_fallback"
        result["price_data"]["price_history_source"] = "akshare"

        md = build_markdown_report(result)
        assert "AKShare" in md


# ── 5. Unknown source ──────────────────────────────────────────────

class TestUnknownSource:
    def test_unknown_source_no_error(self):
        result = _base_result()
        result["price_data"]["latest_price_source"] = None
        result["price_data"]["price_history_source"] = None

        md = build_markdown_report(result)
        assert "未知" in md
        # Should not raise


# ── 6. Warning deduplication ───────────────────────────────────────

class TestWarningDedup:
    def test_no_duplicate_stale_warning(self):
        """When data_warnings already has stale warning, report should not repeat."""
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-05-14"
        result["data_warnings"] = [
            "QMT 日 K 行情可能过期：最后交易日为 2026-05-14，当前日期为 2026-05-22。",
        ]

        md = build_markdown_report(result)
        # The freshness warning should appear once
        assert md.count("行情数据可能过期") == 1

    def test_non_stale_warnings_preserved(self):
        """Non-stale warnings from data_warnings should still appear."""
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-05-14"
        result["data_warnings"] = [
            "QMT 日 K 行情可能过期：最后交易日为 2026-05-14。",
            "某些其他警告信息",
        ]

        md = build_markdown_report(result)
        assert "某些其他警告信息" in md

    def test_multiple_stale_variants_filtered(self):
        """Various stale warning phrasings should all be filtered."""
        result = _base_result()
        result["price_data"]["price_is_stale"] = True
        result["data_warnings"] = [
            "QMT 日 K 行情可能过期",
            "行情仍可能过期",
            "行情仍过期，AKShare 行情 fallback 未应用（akshare_unavailable）",
            "非过期相关警告",
        ]

        md = build_markdown_report(result)
        assert "非过期相关警告" in md


# ── 7. Price chain summary ─────────────────────────────────────────

class TestPriceChain:
    def test_qmt_kline_chain(self):
        result = _base_result()
        result["source_metadata"] = {
            "qmt_status": {
                "download_attempted": False,
                "full_tick_attempted": False,
                "full_tick_applied": False,
                "akshare_price_fallback_attempted": False,
            }
        }

        md = build_markdown_report(result)
        assert "价格链路" in md
        assert "QMT 日 K" in md

    def test_tick_overlay_chain(self):
        result = _base_result()
        result["source_metadata"] = {
            "qmt_status": {
                "download_attempted": True,
                "download_reason": "stale",
                "full_tick_attempted": True,
                "full_tick_applied": True,
                "akshare_price_fallback_attempted": False,
            }
        }

        md = build_markdown_report(result)
        assert "full tick 临时 bar" in md

    def test_akshare_fallback_chain(self):
        result = _base_result()
        result["source_metadata"] = {
            "qmt_status": {
                "download_attempted": True,
                "download_reason": "stale",
                "full_tick_attempted": True,
                "full_tick_applied": False,
                "akshare_price_fallback_attempted": True,
                "akshare_price_fallback_applied": True,
                "akshare_price_fallback_reason": "applied",
            }
        }

        md = build_markdown_report(result)
        assert "AKShare fallback" in md

    def test_empty_qmt_status_no_error(self):
        result = _base_result()
        result["source_metadata"] = {}

        md = build_markdown_report(result)
        assert "价格链路" in md


# ── 8. JSON field preservation ─────────────────────────────────────

class TestJsonFreshnessFields:
    def test_json_preserves_freshness_fields(self):
        import tempfile

        result = _base_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_json_result(result, output_dir=tmpdir)
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))

        pd_ = loaded["price_data"]
        assert pd_["latest_trade_date"] == "2026-05-21"
        assert pd_["price_is_stale"] is False
        assert pd_["latest_price_source"] == "qmt_kline"
        assert pd_["price_history_source"] == "qmt"
        assert pd_["price_uses_intraday_tick"] is False


# ── 9. LLM input slimming ──────────────────────────────────────────

class TestLlmInputFreshness:
    def test_compact_preserves_freshness_fields(self):
        result = _base_result()
        compact = compact_research_result_for_llm(result)

        pd_ = compact.get("price_data", {})
        assert "latest_trade_date" in pd_
        assert "price_is_stale" in pd_
        assert "latest_price_source" in pd_
        assert "price_history_source" in pd_
        assert "price_uses_intraday_tick" in pd_

    def test_compact_preserves_freshness_values(self):
        result = _base_result()
        compact = compact_research_result_for_llm(result)

        pd_ = compact["price_data"]
        assert pd_["latest_trade_date"] == "2026-05-21"
        assert pd_["price_is_stale"] is False
        assert pd_["latest_price_source"] == "qmt_kline"
        assert pd_["price_history_source"] == "qmt"

    def test_compact_removes_provider_run_log(self):
        result = _base_result()
        result["provider_run_log"] = [{"provider": "qmt"}]
        compact = compact_research_result_for_llm(result)

        assert "provider_run_log" not in compact
