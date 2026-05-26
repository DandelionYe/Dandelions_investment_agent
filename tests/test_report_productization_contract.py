"""P2 Phase 4: 报告体系产品化契约测试。

覆盖：
- 4 个正式模板预设（default, institutional_full, compact_review, risk_only）
- 模板配置解析（resolve_report_config）
- 报告内容增强（证据索引、数据质量摘要、风险降级解释、估值分位解释）
- 章节开关控制
- 向后兼容性（不传参数时行为不变）
- Markdown/HTML 一致性
"""

from __future__ import annotations

import pytest

from services.report.html_builder import build_html_report
from services.report.markdown_builder import build_markdown_report
from services.report.template_config import (
    FORMAL_TEMPLATE_IDS,
    SECTION_IDS,
    ReportTemplateConfig,
    get_template_preset,
    get_theme,
    resolve_report_config,
    template_config_from_dict,
    validate_template_config,
)

# ── 共用测试数据 ──────────────────────────────────────────────────

def _minimal_result(**overrides):
    """构建最小测试结果 dict，包含完整 evidence_fields 用于测试。"""
    from services.data.evidence_schema import make_evidence_field

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
        "final_opinion": "综合三方意见后，投委会建议观察。",
        "score_breakdown": {
            "trend_momentum": 16, "liquidity": 13, "fundamental_quality": 16,
            "valuation": 10, "risk_control": 15, "event_policy": 2,
        },
        "price_data": {
            "close": 1688.0, "change_20d": 0.052, "change_60d": 0.083,
            "ma20_position": "above", "ma60_position": "above",
            "max_drawdown_60d": -0.092, "volatility_60d": 0.186,
            "avg_turnover_20d": 4800000000, "data_vendor": "eastmoney",
        },
        "fundamental_data": {
            "roe": 0.33, "gross_margin": 0.91, "revenue_growth": 0.15,
            "net_profit_growth": 0.12, "debt_ratio": 0.22,
            "operating_cashflow_quality": 1.3,
        },
        "valuation_data": {
            "pe_ttm": 21.5, "pb_mrq": 5.2, "ps_ttm": 10.1,
            "market_cap": 2100000000000,
            "pe_percentile": 0.42, "pb_percentile": 0.51, "ps_percentile": 0.47,
            "dividend_yield": 0.018, "valuation_label": "neutral",
            "pe_percentile_source": "local_csmar_daily_derived",
            "pe_percentile_sample_count": 36,
            "industry_level": "SW1", "industry_name": "SW1食品饮料",
            "industry_peer_count": 35, "industry_valid_peer_count": 32,
            "industry_valid_peer_count_pe": 32, "industry_valid_peer_count_pb": 33,
            "industry_valid_peer_count_ps": 31,
            "industry_pe_percentile": 0.30, "industry_pb_percentile": 0.40,
            "industry_ps_percentile": 0.50,
            "industry_valuation_label": "industry_reasonable",
            "industry_valuation_source": "local_csmar_industry_history",
            "industry_valuation_warnings": [],
        },
        "industry": {
            "industry_code": "C1234", "industry_name": "白酒",
            "classification_system": "P0221", "peer_count": 35,
            "valid_peer_count_pe": 32, "valid_peer_count_pb": 33,
            "valid_peer_count_ps": 31,
        },
        "event_data": {
            "recent_news_sentiment": "neutral", "policy_risk": "low",
            "event_summary": {"critical_count": 0, "high_count": 0},
        },
        "source_metadata": {
            "price_data": {"source": "qmt_xtdata"},
            "fundamental_data": {"source": "local_csmar_financial_statements"},
            "capital_structure_source": "local_csmar_eva_structure_partial",
            "valuation_data": {"source": "local_csmar_daily_derived"},
            "industry_source": "local_csmar_industry_history",
            "event_data": {"source": "cninfo"},
        },
        "data_quality": {
            "overall_confidence": 0.85, "has_placeholder": False,
            "blocking_issues": [], "warnings": ["测试警告：PE分位数据不足"],
            "field_quality": {
                "price_data": {"available": True, "source": "qmt_xtdata", "confidence": 0.9, "freshness": "fresh"},
                "fundamental_data": {"available": True, "source": "local_csmar_financial_statements", "confidence": 0.85, "freshness": "historical"},
                "valuation_data": {"available": True, "source": "local_csmar_daily_derived", "confidence": 0.8, "freshness": "stale"},
                "event_data": {"available": True, "source": "cninfo", "confidence": 0.7, "freshness": "fresh"},
            },
        },
        "evidence_bundle": {
            "bundle_id": "evb_test", "symbol": "600519.SH", "as_of": "2026-05-04",
            "items": [
                {"evidence_id": "ev_price_close", "category": "price", "title": "收盘价",
                 "value": 1688.0, "display_value": "1688.00", "source": "qmt_xtdata",
                 "source_date": "2026-05-04", "confidence": 0.9},
            ],
        },
        "evidence_fields": {
            "price_data.close": make_evidence_field(
                1688.0, source="qmt_xtdata", as_of="2026-05-04", freshness="fresh",
            ),
            "valuation_data.pe_ttm": make_evidence_field(
                21.5, source="local_csmar_daily_derived", as_of="2026-05-04", freshness="stale",
            ),
            "fundamental_data.roe": make_evidence_field(
                0.33, source="local_csmar_financial_statements", as_of="2026-05-04",
                freshness="historical",
            ),
            "industry.industry_name": make_evidence_field(
                "白酒", source="local_csmar_industry_history", as_of="2026-05-04",
                freshness="historical",
            ),
            "event_data.recent_news_sentiment": make_evidence_field(
                "neutral", source="cninfo", as_of="2026-05-04", freshness="fresh",
            ),
        },
        "decision_guard": {
            "enabled": True, "score": 72, "rating": "B",
            "risk_level": "medium", "llm_action": "分批买入",
            "max_allowed_action": "观察", "final_action": "观察",
            "guard_reasons": ["评分不足，最高建议限制为观察。"],
        },
        "debate_result": {
            "bull_case": {"thesis": "看多", "key_arguments": ["理由1"], "catalysts": [], "invalidation_conditions": []},
            "bear_case": {"thesis": "看空", "key_arguments": ["理由1"], "main_concerns": [], "invalidation_conditions": []},
            "risk_review": {"risk_level": "medium", "blocking": False, "max_position": "5%", "risk_summary": "中等风险", "risk_triggers": []},
            "committee_conclusion": {"stance": "中性", "action": "观察", "confidence": 0.7, "final_opinion": "测试观点。"},
        },
    }
    data.update(overrides)
    return data


# ── 模板预设测试 ──────────────────────────────────────────────────

class TestTemplatePresets:

    def test_all_formal_templates_exist(self):
        for tid in FORMAL_TEMPLATE_IDS:
            cfg = get_template_preset(tid)
            assert cfg.template_id == tid

    def test_default_template_unchanged(self):
        cfg = get_template_preset("default")
        assert cfg.theme_id == "institutional_light"
        assert cfg.show_evidence is True
        assert cfg.show_data_quality is True
        assert cfg.show_decision_guard is True
        assert cfg.show_disclaimer is True
        assert len(cfg.sections) == len(SECTION_IDS)

    def test_institutional_full_has_all_sections(self):
        cfg = get_template_preset("institutional_full")
        assert len(cfg.sections) == len(SECTION_IDS)
        assert cfg.show_evidence is True
        assert cfg.show_data_quality is True
        assert cfg.show_decision_guard is True

    def test_compact_review_is_compact(self):
        cfg = get_template_preset("compact_review")
        assert cfg.table_density == "compact"
        assert cfg.show_data_quality is False
        assert cfg.show_evidence is True
        assert "bull_case" not in cfg.sections
        assert "bear_case" not in cfg.sections
        assert "basic_info" in cfg.sections
        assert "decision_guard" in cfg.sections

    def test_risk_only_focuses_on_risk(self):
        cfg = get_template_preset("risk_only")
        assert cfg.show_data_quality is True
        assert cfg.show_decision_guard is True
        assert "risk_officer" in cfg.sections
        assert "bull_case" not in cfg.sections
        assert "bear_case" not in cfg.sections
        assert "scorecard" in cfg.sections

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="未知模板 ID"):
            get_template_preset("nonexistent")

    def test_preset_returns_copy(self):
        cfg1 = get_template_preset("default")
        cfg2 = get_template_preset("default")
        cfg1.sections.append("extra")
        assert "extra" not in cfg2.sections


# ── resolve_report_config 测试 ────────────────────────────────────

class TestResolveReportConfig:

    def test_none_uses_default(self):
        cfg, theme = resolve_report_config(None, None)
        assert cfg.template_id == "default"
        assert theme.theme_id == "institutional_light"

    def test_empty_uses_default(self):
        cfg, theme = resolve_report_config("", "")
        assert cfg.template_id == "default"

    def test_valid_template(self):
        cfg, theme = resolve_report_config("compact_review", None)
        assert cfg.template_id == "compact_review"
        assert cfg.table_density == "compact"
        assert theme.theme_id == "compact_blue"  # preset theme

    def test_theme_override(self):
        cfg, theme = resolve_report_config("default", "institutional_dark")
        assert cfg.template_id == "default"
        assert theme.theme_id == "institutional_dark"

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="未知模板 ID"):
            resolve_report_config("nonexistent", None)

    def test_unknown_theme_raises(self):
        with pytest.raises(ValueError, match="未知主题 ID"):
            resolve_report_config("default", "nonexistent_theme")

    def test_risk_only_with_dark_theme(self):
        cfg, theme = resolve_report_config("risk_only", None)
        assert cfg.template_id == "risk_only"
        assert theme.theme_id == "institutional_dark"


class TestApiReportConfigValidation:

    def test_research_request_accepts_formal_report_config(self):
        from apps.api.schemas.research import ResearchRequest

        req = ResearchRequest(
            symbol="600519.SH",
            report_template="institutional_full",
            report_theme="compact_blue",
        )
        assert req.report_template == "institutional_full"
        assert req.report_theme == "compact_blue"

    def test_research_request_rejects_unknown_report_template(self):
        from pydantic import ValidationError

        from apps.api.schemas.research import ResearchRequest

        with pytest.raises(ValidationError):
            ResearchRequest(symbol="600519.SH", report_template="unknown")


# ── validate_template_config 测试 ─────────────────────────────────

class TestValidateTemplateConfig:

    def test_formal_templates_no_warnings(self):
        for tid in FORMAL_TEMPLATE_IDS:
            cfg = get_template_preset(tid)
            warnings = validate_template_config(cfg)
            assert len(warnings) == 0, f"{tid}: {warnings}"

    def test_custom_template_id_warns(self):
        cfg = ReportTemplateConfig(template_id="custom")
        warnings = validate_template_config(cfg)
        assert any("template_id" in w for w in warnings)


# ── template_config_from_dict 浀试 ────────────────────────────────

class TestTemplateConfigFromDict:

    def test_from_dict_with_preset(self):
        cfg = template_config_from_dict({"template_id": "compact_review"})
        assert cfg.template_id == "compact_review"
        assert cfg.table_density == "compact"

    def test_from_dict_with_preset_override(self):
        cfg = template_config_from_dict({
            "template_id": "compact_review",
            "show_data_quality": True,  # override preset
        })
        assert cfg.template_id == "compact_review"
        assert cfg.show_data_quality is True  # overridden

    def test_from_dict_unknown_template(self):
        cfg = template_config_from_dict({"template_id": "custom"})
        assert cfg.template_id == "custom"


# ── 报告内容增强测试 ──────────────────────────────────────────────

class TestReportContentEnhancements:

    def test_evidence_index_present_when_evidence_enabled(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "证据索引" in md
        assert "qmt_xtdata" in md

    def test_evidence_index_absent_when_evidence_disabled(self):
        result = _minimal_result()
        md = build_markdown_report(result, template_config={"show_evidence": False})
        assert "证据索引" not in md

    def test_percentile_explanation_present(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "估值分位解释" in md
        assert "分位值含义" in md
        assert "42.00%" in md or "42%" in md  # pe_percentile

    def test_risk_degradation_explanation_present(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "风险降级详解" in md
        assert "被降级" in md  # llm_action != final_action

    def test_risk_degradation_no_degradation(self):
        result = _minimal_result()
        result["decision_guard"]["llm_action"] = "观察"
        result["decision_guard"]["final_action"] = "观察"
        md = build_markdown_report(result)
        assert "未被降级" in md

    def test_data_quality_summary_present(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "数据质量摘要" in md
        assert "数据证据字段摘要" in md
        assert "核心字段覆盖率" in md
        assert "strict source 覆盖率" in md

    def test_industry_percentile_explanation(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "PE 行业分位" in md
        assert "30.00%" in md or "30%" in md


# ── 模板生成测试 ──────────────────────────────────────────────────

class TestTemplateGeneration:

    def test_all_templates_generate_markdown(self):
        result = _minimal_result()
        for tid in FORMAL_TEMPLATE_IDS:
            cfg = get_template_preset(tid)
            md = build_markdown_report(result, template_config=cfg)
            assert len(md) > 100, f"{tid} produced empty report"
            assert "投研报告" in md

    def test_all_templates_generate_html(self):
        result = _minimal_result()
        for tid in FORMAL_TEMPLATE_IDS:
            cfg = get_template_preset(tid)
            md = build_markdown_report(result, template_config=cfg)
            theme = get_theme(cfg.theme_id)
            html = build_html_report(md, theme=theme)
            assert "<!DOCTYPE html>" in html
            assert "<body>" in html

    def test_compact_review_omits_bull_bear(self):
        result = _minimal_result()
        cfg = get_template_preset("compact_review")
        md = build_markdown_report(result, template_config=cfg)
        assert "## 五、多头观点" not in md
        assert "## 六、空头观点" not in md
        assert "## 八、决策保护器说明" in md

    def test_risk_only_omits_bull_bear_followup(self):
        result = _minimal_result()
        cfg = get_template_preset("risk_only")
        md = build_markdown_report(result, template_config=cfg)
        assert "## 五、多头观点" not in md
        assert "## 六、空头观点" not in md
        assert "## 十、后续跟踪建议" not in md
        assert "## 七、风险官意见" in md
        assert "## 八、决策保护器说明" in md

    def test_default_preserves_all_sections(self):
        result = _minimal_result()
        cfg = get_template_preset("default")
        md = build_markdown_report(result, template_config=cfg)
        for section in ["一、基本信息", "二、投委会结论", "五、多头观点",
                         "六、空头观点", "七、风险官意见", "八、决策保护器说明",
                         "十一、免责声明"]:
            assert section in md, f"Default template missing: {section}"


# ── 向后兼容性测试 ────────────────────────────────────────────────

class TestBackwardCompatibility:

    def test_build_markdown_no_args(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        assert "投研报告" in md
        assert "600519.SH" in md

    def test_build_markdown_dict_config(self):
        result = _minimal_result()
        md = build_markdown_report(result, template_config={"show_evidence": False})
        assert "投研报告" in md

    def test_build_html_no_theme(self):
        md = "# Test"
        html = build_html_report(md)
        assert "<!DOCTYPE html>" in html


# ── HTML 一致性测试 ───────────────────────────────────────────────

class TestHtmlConsistency:

    def test_html_contains_markdown_content(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        html = build_html_report(md)
        # Key content from markdown should appear in HTML
        assert "600519.SH" in html
        assert "投研报告" in html

    def test_html_theme_css_applied(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        theme = get_theme("institutional_dark")
        html = build_html_report(md, theme=theme)
        assert theme.accent_color in html
        assert theme.heading_background in html

    def test_html_no_raw_python_dict(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        html = build_html_report(md)
        # Should not contain Python dict repr
        assert "{'" not in html
        assert "'key'" not in html

    def test_html_escapes_raw_script_tags(self):
        result = _minimal_result(name="<script>alert(1)</script>")
        md = build_markdown_report(result)
        html = build_html_report(md, title="<script>alert(2)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ── 确定性测试 ────────────────────────────────────────────────────

class TestDeterminism:

    def test_report_deterministic(self):
        result = _minimal_result()
        md1 = build_markdown_report(result)
        md2 = build_markdown_report(result)
        assert md1 == md2

    def test_report_no_dynamic_date_in_content(self):
        result = _minimal_result()
        md = build_markdown_report(result)
        # The report should use result's as_of, not current date
        assert "2026-05-04" in md

    def test_stale_price_warning_uses_result_as_of(self):
        result = _minimal_result()
        result["price_data"]["price_is_stale"] = True
        result["price_data"]["latest_trade_date"] = "2026-04-30"
        md = build_markdown_report(result)
        assert "报告日期为 2026-05-04" in md
