"""
报告生成器格式验证测试。

覆盖：Markdown 报告结构完整性、缺失数据优雅降级、
HTML 结构有效性、CSS 页面定义、JSON 序列化往返。
"""

import json
from pathlib import Path

from services.report.html_builder import build_html_report, save_html_report
from services.report.json_builder import save_json_result
from services.report.markdown_builder import build_markdown_report, save_markdown_report

# ── 共用测试数据 ──────────────────────────────────────────────────

def _minimal_result(**overrides):
    data = {
        "symbol": "600519.SH",
        "name": "测试标的",
        "asset_type": "stock",
        "as_of": "2026-05-04",
        "data_source": "mock",
        "score": 72,
        "rating": "B",
        "action": "观察",
        "max_position": "5%-8%",
        "final_opinion": "未来1-3个月谨慎看多。",
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
            "avg_turnover_20d": 4800000000,
            "data_vendor": "eastmoney",
        },
        "valuation_data": {
            "pe_ttm": 21.5,
            "pb_mrq": 5.2,
            "ps_ttm": 10.1,
            "market_cap": 2_100_000_000_000,
            "pe_percentile": 0.42,
            "pb_percentile": 0.51,
            "ps_percentile": 0.47,
            "dividend_yield": 0.018,
            "valuation_label": "neutral",
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
        },
        "data_quality": {
            "overall_confidence": 0.85,
            "has_placeholder": False,
            "blocking_issues": [],
            "warnings": ["测试警告：PE分位数据不足"],
            "field_quality": {
                "price_data": {
                    "available": True, "source": "mock",
                    "confidence": 0.9, "freshness": "fresh",
                },
                "fundamental_data": {
                    "available": True, "source": "qmt",
                    "confidence": 0.8, "freshness": "fresh",
                },
            },
        },
        "evidence_bundle": {
            "bundle_id": "evb_test",
            "symbol": "600519.SH",
            "as_of": "2026-05-04",
            "items": [
                {
                    "evidence_id": "ev_price_close",
                    "category": "price",
                    "title": "最新收盘价",
                    "value": 1688.0,
                    "display_value": "1688.0",
                    "source": "mock",
                    "source_date": "2026-05-04",
                    "confidence": 0.9,
                },
            ],
        },
        "decision_guard": {
            "enabled": True,
            "score": 72,
            "rating": "B",
            "risk_level": "medium",
            "llm_action": "分批买入",
            "max_allowed_action": "观察",
            "final_action": "观察",
            "guard_reasons": ["placeholder数据限制"],
        },
        "debate_result": {
            "bull_case": {
                "thesis": "短期趋势改善明显，估值合理。",
                "key_arguments": ["MA20和MA60均在价格下方形成支撑", "近60日涨幅显著"],
                "catalysts": ["一季报可能超预期", "行业政策利好"],
                "invalidation_conditions": ["跌破MA60支撑", "成交量明显萎缩"],
            },
            "bear_case": {
                "thesis": "估值分位不低，上行动能有限。",
                "key_arguments": ["PE分位不低", "行业竞争加剧"],
                "main_concerns": ["估值扩张空间有限", "宏观不确定性"],
                "invalidation_conditions": ["PE分位回落至50%以下", "出现重大利好"],
            },
            "risk_review": {
                "risk_level": "medium",
                "blocking": False,
                "risk_summary": "整体风险中等，估值偏高但趋势尚可。",
                "max_position": "5%-8%",
                "risk_triggers": ["跌破MA60且成交量放大", "突发利空公告"],
            },
            "committee_conclusion": {
                "stance": "谨慎看多",
                "action": "观察",
                "confidence": 0.72,
                "final_opinion": "综合三方意见后，投委会建议观察。",
            },
        },
    }
    data.update(overrides)
    return data


# ── Markdown 报告结构测试 ─────────────────────────────────────────

REQUIRED_SECTIONS = [
    "一、基本信息",
    "二、投委会结论",
    "三、数据来源与行情摘要",
    "四、量化因子打分卡",
    "五、多头观点",
    "六、空头观点",
    "七、风险官意见",
    "八、决策保护器说明",
    "九、辩论收敛纪要",
    "十、后续跟踪建议",
    "十一、免责声明",
]


def test_markdown_contains_all_required_sections():
    md = build_markdown_report(_minimal_result())
    for section in REQUIRED_SECTIONS:
        assert section in md, f"缺少章节: {section}"


def test_markdown_contains_symbol_and_name():
    md = build_markdown_report(_minimal_result())
    assert "600519.SH" in md
    assert "测试标的" in md


def test_markdown_contains_score_and_rating():
    md = build_markdown_report(_minimal_result())
    assert "72" in md
    assert "B" in md


def test_markdown_warns_for_template_no_llm_mode():
    md = build_markdown_report(
        _minimal_result(
            analysis_mode="template_no_llm",
            analysis_warnings=[
                "本报告为无 LLM 模式生成，观点部分为规则/模板化输出，不构成完整投研分析。"
            ],
        )
    )

    assert "模式提示" in md
    assert "无 LLM 模式" in md


def test_markdown_contains_score_breakdown_dimensions():
    md = build_markdown_report(_minimal_result())
    assert "趋势动量" in md
    assert "流动性" in md
    assert "基本面质量" in md
    assert "估值性价比" in md
    assert "风险控制" in md
    assert "事件/政策" in md


def test_markdown_contains_industry_valuation_section():
    md = build_markdown_report(_minimal_result())
    assert "估值概览" in md
    assert "行业横截面估值" in md
    assert "SW1食品饮料" in md
    assert "PE 行业分位" in md
    assert "30.00%" in md
    assert "qmt_sector+qmt_financial+qmt_price" in md


def test_markdown_contains_bull_bear_risk_content():
    md = build_markdown_report(_minimal_result())
    assert "短期趋势改善明显" in md
    assert "估值分位不低" in md
    assert "整体风险中等" in md


def test_markdown_contains_decision_guard_info():
    md = build_markdown_report(_minimal_result())
    assert "决策保护器" in md
    assert "placeholder数据限制" in md


def test_markdown_handles_missing_debate_result():
    """无 debate_result 时应该使用顶层 fallback 字段。"""
    result = _minimal_result()
    del result["debate_result"]
    result["bull_case"] = "fallback多头文本"
    result["bear_case"] = "fallback空头文本"
    result["risk_review"] = "fallback风险文本"

    md = build_markdown_report(result)
    assert "fallback多头文本" in md
    assert "fallback空头文本" in md
    assert "fallback风险文本" in md


def test_markdown_handles_missing_price_data():
    result = _minimal_result()
    result["price_data"] = {}
    result["price_data"]["data_vendor"] = "eastmoney"

    md = build_markdown_report(result)
    # 不应该报错，应该显示"暂无"
    assert "暂无" in md


def test_markdown_handles_empty_field_quality():
    result = _minimal_result()
    result["data_quality"]["field_quality"] = {}

    md = build_markdown_report(result)
    assert "暂无" in md


def test_markdown_handles_empty_evidence_bundle():
    result = _minimal_result()
    result["evidence_bundle"]["items"] = []

    md = build_markdown_report(result)
    assert "暂无" in md


def test_markdown_handles_empty_guard_reasons():
    result = _minimal_result()
    result["decision_guard"]["guard_reasons"] = []

    md = build_markdown_report(result)
    # 不应该报错
    assert "降级/限制原因" in md


# ── Markdown 文件保存测试 ──────────────────────────────────────────

def test_save_markdown_creates_file(tmp_path):
    output_dir = tmp_path / "reports"
    result = _minimal_result()

    path = save_markdown_report(result, output_dir=str(output_dir))

    saved = Path(path)
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert "600519.SH" in content
    assert "投研报告" in content


def test_save_markdown_filename_matches_symbol():
    result = _minimal_result()
    result["symbol"] = "000001.SZ"

    import tempfile

    from services.report.markdown_builder import save_markdown_report
    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_markdown_report(result, output_dir=tmpdir)
        assert "000001.SZ" in Path(path).name


# ── HTML 报告结构测试 ──────────────────────────────────────────────

def test_html_report_has_doctype():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md, title="测试报告")
    assert "<!DOCTYPE html>" in html


def test_html_report_has_lang_attribute():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md)
    assert 'lang="zh-CN"' in html


def test_html_report_has_head_and_body():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md)
    assert "<head>" in html
    assert "<body>" in html
    assert "</html>" in html


def test_html_report_has_css_a4_page_definition():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md)
    assert "@page" in html
    assert "A4" in html


def test_html_report_contains_markdown_content():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md)
    assert "短期趋势改善明显" in html
    assert "投研报告" in html or "测试标的" in html


def test_html_report_encodes_utf8():
    md = build_markdown_report(_minimal_result())
    html = build_html_report(md, title="测试报告")
    assert 'charset="UTF-8"' in html or "charset=utf-8" in html.lower()


def test_save_html_creates_file(tmp_path):
    output_dir = tmp_path / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = save_markdown_report(_minimal_result(), output_dir=str(output_dir))
    html_path = save_html_report(md_path, output_dir=str(output_dir))

    assert Path(html_path).exists()
    content = Path(html_path).read_text(encoding="utf-8")
    assert "<html" in content.lower()
    assert "<body>" in content


# ── JSON 报告测试 ──────────────────────────────────────────────────

def test_save_json_creates_valid_file(tmp_path):
    output_dir = tmp_path / "reports"
    result = _minimal_result()

    path = save_json_result(result, output_dir=str(output_dir))

    saved = Path(path)
    assert saved.exists()
    loaded = json.loads(saved.read_text(encoding="utf-8"))
    assert loaded["symbol"] == "600519.SH"
    assert loaded["score"] == 72


def test_json_roundtrip_preserves_nested_objects(tmp_path):
    output_dir = tmp_path / "reports"
    result = _minimal_result()

    path = save_json_result(result, output_dir=str(output_dir))
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))

    assert loaded["debate_result"]["bull_case"]["thesis"] == "短期趋势改善明显，估值合理。"
    assert loaded["score_breakdown"]["trend_momentum"] == 16
    assert loaded["decision_guard"]["enabled"] is True


def test_json_filename_matches_symbol(tmp_path):
    output_dir = tmp_path / "reports"
    result = _minimal_result()

    path = save_json_result(result, output_dir=str(output_dir))
    assert "600519.SH" in Path(path).name
    assert Path(path).suffix == ".json"
