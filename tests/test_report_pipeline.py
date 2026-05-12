import json
from pathlib import Path

import pandas as pd
import pytest

from services.data.aggregator.research_data_aggregator import ResearchDataAggregator
from services.data.akshare_provider import get_akshare_asset_data
from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.normalizers.fundamental_normalizer import FundamentalNormalizer
from services.data.normalizers.valuation_normalizer import ValuationNormalizer
from services.data.qmt_provider import get_qmt_asset_data
from services.orchestrator.single_asset_research import run_single_asset_research
from services.report.html_builder import save_html_report
from services.report.json_builder import save_json_result
from services.report.markdown_builder import save_markdown_report
from services.research.decision_guard import apply_decision_guard
from services.research.scoring_engine import score_asset


def test_mock_single_asset_research_without_llm():
    result = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="mock",
    )

    assert result["symbol"] == "600519.SH"
    assert result["data_source"] == "mock"
    assert result["score"] >= 0
    assert result["decision_guard"]["enabled"] is True
    assert result["source_metadata"]["fundamental_data"]["source"] == "mock_placeholder"
    assert result["data_quality"]["has_placeholder"] is True
    assert result["evidence_bundle"]["items"]
    assert result["score_breakdown"]["fundamental_quality"] <= 8
    assert result["score_breakdown"]["valuation"] <= 6
    assert result["score_breakdown"]["event_policy"] <= 4
    assert result["analysis_mode"] == "template_no_llm"
    assert result["llm_enabled"] is False
    assert result["analysis_warnings"]
    assert result["decision_guard"]["max_allowed_action"] == "观察"


def test_mock_graph_research_without_llm_skips_deepseek():
    result = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="mock",
        use_graph=True,
    )

    assert result["symbol"] == "600519.SH"
    assert result["analysis_mode"] == "template_no_llm"
    assert result["llm_enabled"] is False
    assert "debate_result" not in result
    assert result["decision_guard"]["enabled"] is True


def test_mock_etf_research_skips_stock_fundamental_and_valuation():
    result = run_single_asset_research(
        "510300.SH",
        use_llm=False,
        data_source="mock",
    )

    assert result["asset_type"] == "etf"
    assert result["fundamental_data"] == {}
    assert result["valuation_data"] == {}
    assert "fundamental_data" not in result["source_metadata"]
    assert "valuation_data" not in result["source_metadata"]
    assert result["data_quality"]["blocking_issues"] == []
    assert all(item["category"] != "fundamental" for item in result["evidence_bundle"]["items"])
    assert any(item["category"] == "etf" for item in result["evidence_bundle"]["items"])


def test_akshare_price_conversion_without_network(monkeypatch):
    rows = 80
    df = pd.DataFrame(
        {
            "收盘": [100 + index for index in range(rows)],
            "成交额": [1_000_000_000 + index for index in range(rows)],
            "data_vendor": ["eastmoney"] * rows,
        }
    )

    monkeypatch.setattr(
        "services.data.akshare_provider._load_price_history",
        lambda symbol, asset_type: df,
    )

    result = get_akshare_asset_data("600519.SH")

    assert result["data_source"] == "akshare"
    assert result["price_data"]["close"] == 179.0
    assert result["price_data"]["avg_turnover_20d"] > 0
    assert "fundamental_data" not in result


def test_qmt_provider_auto_downloads_when_local_history_is_empty(monkeypatch):
    rows = 80
    history_df = pd.DataFrame(
        {
            "time": list(range(rows)),
            "close": [100 + index for index in range(rows)],
            "volume": [10_000 + index for index in range(rows)],
            "amount": [1_000_000_000 + index for index in range(rows)],
        }
    )

    class FakeXtData:
        enable_hello = True

        def __init__(self):
            self.download_called = False

        def connect(self):
            return object()

        def get_data_dir(self):
            return "fake-qmt-datadir"

        def get_market_data_ex(self, **kwargs):
            if not self.download_called:
                return {"600519.SH": pd.DataFrame()}
            return {"600519.SH": history_df}

        def download_history_data(self, stock_code, period, start_time="", end_time=""):
            self.download_called = True
            return True

        def get_instrument_detail(self, symbol):
            return {
                "ExchangeID": "SH",
                "InstrumentID": "600519",
                "InstrumentName": "贵州茅台",
            }

    fake_xtdata = FakeXtData()

    monkeypatch.setattr(
        "services.data.qmt_provider._import_xtdata",
        lambda: fake_xtdata,
    )
    monkeypatch.setenv("QMT_AUTO_DOWNLOAD", "true")
    monkeypatch.setenv("QMT_HISTORY_START", "20250101")
    monkeypatch.setenv("QMT_HISTORY_END", "20260429")

    result = get_qmt_asset_data("600519.SH")

    assert result["data_source"] == "qmt"
    assert result["name"] == "贵州茅台"
    assert result["price_data"]["close"] == 179.0
    assert result["source_metadata"]["qmt_status"]["download_attempted"] is True
    assert result["source_metadata"]["qmt_status"]["download_success"] is True
    assert result["source_metadata"]["qmt_status"]["row_count"] == rows


def test_qmt_fundamental_normalizer_converts_ratios_and_amounts():
    provider_result = {
        "data": {
            "PershareIndex": [
                {
                    "m_timetag": "20251231",
                    "m_anntime": "20260428",
                    "ROE": 18.2,
                    "销售毛利率": 52.1,
                    "营业收入同比增长率": 9.3,
                    "净利润同比增长率": 11.8,
                    "每股净资产": 28.4,
                }
            ],
            "Income": [{"营业收入": 123456789000, "净利润": 23456789000}],
            "Balance": [{"资产总计": 1000, "负债合计": 417}],
            "CashFlow": [{"经营活动产生的现金流量净额": 26200000000}],
        }
    }

    normalized = FundamentalNormalizer().normalize_qmt(provider_result)["normalized"]

    assert normalized["roe"] == 0.182
    assert normalized["gross_margin"] == 0.521
    assert normalized["revenue_growth"] == pytest.approx(0.093)
    assert normalized["net_profit_growth"] == pytest.approx(0.118)
    assert normalized["debt_ratio"] == 0.417
    assert normalized["operating_cashflow_quality"] > 1


def test_valuation_normalizer_derives_market_cap_from_qmt_fields():
    asset_data = {
        "as_of": "2026-04-29",
        "price_data": {"close": 10.0},
        "basic_info": {"total_volume": 1000, "float_volume": 800},
        "fundamental_data": {"net_profit_ttm": 500, "revenue_ttm": 2000, "bps": 4},
    }

    valuation = ValuationNormalizer().derive_from_qmt(asset_data)

    assert valuation["market_cap"] == 10000
    assert valuation["float_market_cap"] == 8000
    assert valuation["pe_ttm"] == 20
    assert valuation["ps_ttm"] == 5
    assert valuation["pb_mrq"] == 2.5


def test_event_normalizer_classifies_announcement_risk():
    provider_result = {
        "data": [
            {
                "公告标题": "关于收到交易所问询函的公告",
                "公告时间": "2026-04-20",
                "公告链接": "https://example.com/a.pdf",
            },
            {
                "公告标题": "2025年年度权益分派实施公告",
                "公告时间": "2026-04-21",
            },
        ]
    }

    events = EventNormalizer().normalize_akshare(provider_result, "600519.SH")

    assert events[0]["event_type"] == "regulatory_inquiry"
    assert events[0]["severity"] == "medium"
    assert events[1]["event_type"] == "dividend"
    assert events[1]["sentiment"] == "neutral_positive"


def test_scoring_result_matches_protocol():
    asset_data = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="mock",
    )

    score = score_asset(asset_data)

    assert set(score["score_breakdown"]) == {
        "trend_momentum",
        "liquidity",
        "fundamental_quality",
        "valuation",
        "risk_control",
        "event_policy",
    }
    assert 0 <= score["total_score"] <= 100


def test_event_risk_reduces_event_policy_score():
    asset_data = {
        "asset_type": "stock",
        "price_data": {
            "change_20d": 0,
            "change_60d": 0,
            "ma20_position": "below",
            "ma60_position": "below",
            "avg_turnover_20d": 600_000_000,
            "max_drawdown_60d": -0.05,
            "volatility_60d": 0.15,
        },
        "fundamental_data": {},
        "valuation_data": {},
        "event_data": {
            "recent_news_sentiment": "neutral_negative",
            "policy_risk": "medium",
            "event_summary": {
                "critical_count": 1,
                "high_severity_count": 0,
                "negative_count": 0,
            },
            "events": [{"severity": "critical", "sentiment": "negative"}],
        },
        "source_metadata": {
            "fundamental_data": {"source": "mock_placeholder"},
            "valuation_data": {"source": "mock_placeholder"},
            "event_data": {"source": "akshare"},
        },
    }

    score = score_asset(asset_data)

    assert score["score_breakdown"]["event_policy"] == 0


def test_decision_guard_clamps_aggressive_llm_action():
    result = {
        "score": 62,
        "rating": "C",
        "action": "买入",
        "debate_result": {
            "risk_review": {"risk_level": "medium"},
            "committee_conclusion": {
                "action": "买入",
                "final_opinion": "模型建议买入。",
            },
        },
    }

    guarded = apply_decision_guard(result)

    assert guarded["action"] == "观察"
    assert guarded["decision_guard"]["llm_action"] == "买入"
    assert guarded["decision_guard"]["final_action"] == "观察"


def test_report_artifacts_are_generated():
    result = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="mock",
    )

    output_dir = Path("storage/cache/test_reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = save_json_result(result, output_dir=str(output_dir))
    markdown_path = save_markdown_report(result, output_dir=str(output_dir))
    html_path = save_html_report(markdown_path, output_dir=str(output_dir))

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()
    assert Path(html_path).exists()

    saved = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert saved["symbol"] == "600519.SH"
    assert "投研报告" in Path(markdown_path).read_text(encoding="utf-8")
    assert "<html" in Path(html_path).read_text(encoding="utf-8").lower()


class _PipelineFundamentalService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        return {
            "data": {
                "fundamental_data": {
                    "roe": 0.18,
                    "gross_margin": 0.52,
                    "net_margin": 0.22,
                    "revenue_growth": 0.09,
                    "net_profit_growth": 0.11,
                    "debt_ratio": 0.42,
                    "net_profit_ttm": 100,
                    "revenue_ttm": 500,
                    "bps": 5,
                },
                "fundamental_analysis": {
                    "quality_label": "high",
                    "growth_label": "moderate_growth",
                    "cashflow_label": "good",
                    "leverage_label": "normal",
                    "key_points": ["盈利质量较高。"],
                    "warnings": [],
                },
            },
            "source_metadata": {
                "fundamental_data": {
                    "source": "qmt_financial",
                    "confidence": 0.78,
                    "as_of": "2026-05-12",
                }
            },
            "provider_run_log": [
                {
                    "provider": "qmt_financial",
                    "dataset": "fundamental_data",
                    "symbol": symbol,
                    "status": "success",
                    "rows": 4,
                    "error": None,
                    "error_type": None,
                    "as_of": "2026-05-12",
                }
            ],
        }


class _PipelineValuationService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        return {
            "data": {
                "valuation_data": {
                    "pe_ttm": 20,
                    "pb_mrq": 2,
                    "ps_ttm": 4,
                    "market_cap": 2000,
                    "valuation_label": "reasonable",
                    "industry_level": "SW1",
                    "industry_name": "SW1食品饮料",
                    "industry_peer_count": 35,
                    "industry_valid_peer_count": 32,
                    "industry_valid_peer_count_pe": 32,
                    "industry_valid_peer_count_pb": 33,
                    "industry_valid_peer_count_ps": 31,
                    "industry_pe_percentile": 0.30,
                    "industry_pb_percentile": 0.40,
                    "industry_ps_percentile": 0.50,
                    "industry_valuation_label": "industry_reasonable",
                    "industry_valuation_source": "qmt_sector+qmt_financial+qmt_price",
                    "industry_valuation_warnings": [],
                }
            },
            "source_metadata": {
                "valuation_data": {
                    "source": "qmt_derived",
                    "confidence": 0.78,
                    "as_of": "2026-05-12",
                }
            },
            "provider_run_log": [
                {
                    "provider": "qmt",
                    "dataset": "industry_valuation",
                    "symbol": symbol,
                    "status": "success",
                    "rows": 35,
                    "error": None,
                    "error_type": None,
                    "as_of": "2026-05-12",
                },
                {
                    "provider": "qmt_derived",
                    "dataset": "valuation_data",
                    "symbol": symbol,
                    "status": "success",
                    "rows": 1,
                    "error": None,
                    "error_type": None,
                    "as_of": "2026-05-12",
                },
            ],
        }


class _PipelineEventService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        return {
            "data": {
                "event_data": {
                    "major_event": "暂无重大事件",
                    "recent_news_sentiment": "neutral",
                    "policy_risk": "low",
                    "event_summary": {
                        "critical_count": 0,
                        "high_severity_count": 0,
                        "negative_count": 0,
                    },
                    "events": [],
                }
            },
            "source_metadata": {
                "event_data": {
                    "source": "akshare",
                    "confidence": 0.68,
                    "as_of": "2026-05-12",
                }
            },
            "provider_run_log": [
                {
                    "provider": "akshare",
                    "dataset": "event_data",
                    "symbol": symbol,
                    "status": "success",
                    "rows": 0,
                    "error": None,
                    "error_type": None,
                    "as_of": "2026-05-12",
                }
            ],
        }


class _NoopCache:
    def store_run(self, asset_data: dict) -> None:
        return None


def test_qmt_industry_valuation_reaches_pipeline_evidence_and_reports(monkeypatch, tmp_path):
    def fake_qmt_asset_data(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "name": "Pipeline QMT Stock",
            "asset_type": "stock",
            "as_of": "2026-05-12",
            "data_source": "qmt",
            "price_data": {
                "close": 10,
                "change_20d": 0.03,
                "change_60d": 0.08,
                "ma20_position": "above",
                "ma60_position": "above",
                "max_drawdown_60d": -0.05,
                "volatility_60d": 0.18,
                "avg_turnover_20d": 800_000_000,
                "data_vendor": "qmt",
            },
            "basic_info": {"total_volume": 200, "float_volume": 160},
            "source_metadata": {
                "price_data": {
                    "source": "qmt",
                    "vendor": "qmt",
                    "confidence": 0.90,
                    "as_of": "2026-05-12",
                }
            },
        }

    def fake_aggregator_factory():
        aggregator = ResearchDataAggregator()
        aggregator.fundamental_service = _PipelineFundamentalService()
        aggregator.valuation_service = _PipelineValuationService()
        aggregator.event_service = _PipelineEventService()
        aggregator.cache = _NoopCache()
        return aggregator

    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.get_qmt_asset_data",
        fake_qmt_asset_data,
    )
    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.ResearchDataAggregator",
        fake_aggregator_factory,
    )

    result = run_single_asset_research(
        "600519.SH",
        use_llm=False,
        data_source="qmt",
    )

    valuation = result["valuation_data"]
    evidence_by_id = {
        item["evidence_id"]: item
        for item in result["evidence_bundle"]["items"]
    }

    assert valuation["industry_name"] == "SW1食品饮料"
    assert valuation["industry_pe_percentile"] == pytest.approx(0.30)
    assert evidence_by_id["ev_val_industry_pe_percentile"]["display_value"] == "30.0%"
    assert evidence_by_id["ev_val_industry_pe_percentile"]["source"] == (
        "qmt_sector+qmt_financial+qmt_price"
    )
    assert any(
        item["dataset"] == "industry_valuation" and item["status"] == "success"
        for item in result["provider_run_log"]
    )

    output_dir = tmp_path / "reports"
    markdown_path = save_markdown_report(result, output_dir=str(output_dir))
    html_path = save_html_report(markdown_path, output_dir=str(output_dir))

    markdown_text = Path(markdown_path).read_text(encoding="utf-8")
    html_text = Path(html_path).read_text(encoding="utf-8")

    assert "行业横截面估值" in markdown_text
    assert "SW1食品饮料" in markdown_text
    assert "PE 行业分位" in markdown_text
    assert "30.00%" in markdown_text
    assert "行业横截面估值" in html_text
    assert "SW1食品饮料" in html_text
