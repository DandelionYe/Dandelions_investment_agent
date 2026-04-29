import json
import pytest
from pathlib import Path

import pandas as pd

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
    assert result["decision_guard"]["max_allowed_action"] == "观察"


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
