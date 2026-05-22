"""报告模板配置测试。

覆盖：
- 默认模板配置值稳定。
- 关闭 evidence/data_quality/decision_guard section 后报告不包含对应章节。
- 默认报告仍包含关键章节。
- HTML theme CSS 可稳定输出。
"""

from services.report.template_config import (
    SECTION_IDS,
    ReportTemplateConfig,
    ReportTheme,
    build_theme_css,
    default_template_config,
    get_theme,
    template_config_from_dict,
    validate_template_config,
)


class TestDefaultTemplateConfig:

    def test_default_values(self):
        cfg = default_template_config()
        assert cfg.template_id == "default"
        assert cfg.theme_id == "institutional_light"
        assert cfg.show_evidence is True
        assert cfg.show_data_quality is True
        assert cfg.show_decision_guard is True
        assert cfg.show_disclaimer is True
        assert cfg.table_density == "normal"
        assert cfg.language == "zh-CN"

    def test_default_sections(self):
        cfg = default_template_config()
        assert len(cfg.sections) == len(SECTION_IDS)
        assert "basic_info" in cfg.sections
        assert "decision_guard" in cfg.sections
        assert "disclaimer" in cfg.sections


class TestReportTheme:

    def test_default_theme(self):
        theme = ReportTheme()
        assert theme.theme_id == "institutional_light"
        assert "Microsoft YaHei" in theme.font_family
        assert "A4" not in theme.page_margin  # margin doesn't contain "A4"

    def test_get_known_theme(self):
        theme = get_theme("institutional_light")
        assert theme.theme_id == "institutional_light"

    def test_get_unknown_theme_returns_default(self):
        theme = get_theme("nonexistent_theme")
        assert theme.theme_id == "institutional_light"

    def test_dark_theme(self):
        theme = get_theme("institutional_dark")
        assert theme.theme_id == "institutional_dark"
        assert theme.heading_background == "#2a2a2a"

    def test_compact_blue_theme(self):
        theme = get_theme("compact_blue")
        assert theme.theme_id == "compact_blue"
        assert "12mm" in theme.page_margin


class TestValidateTemplateConfig:

    def test_default_config_valid(self):
        cfg = default_template_config()
        warnings = validate_template_config(cfg)
        assert len(warnings) == 0

    def test_unknown_template_id(self):
        cfg = ReportTemplateConfig(template_id="unknown")
        warnings = validate_template_config(cfg)
        assert any("template_id" in w for w in warnings)

    def test_unknown_theme_id(self):
        cfg = ReportTemplateConfig(theme_id="unknown")
        warnings = validate_template_config(cfg)
        assert any("theme_id" in w for w in warnings)

    def test_unknown_section(self):
        cfg = ReportTemplateConfig(sections=["basic_info", "nonexistent"])
        warnings = validate_template_config(cfg)
        assert any("nonexistent" in w for w in warnings)


class TestTemplateConfigFromDict:

    def test_from_dict(self):
        data = {
            "template_id": "custom",
            "theme_id": "institutional_dark",
            "sections": ["basic_info", "scorecard"],
            "show_evidence": False,
            "table_density": "compact",
        }
        cfg = template_config_from_dict(data)
        assert cfg.template_id == "custom"
        assert cfg.theme_id == "institutional_dark"
        assert cfg.sections == ["basic_info", "scorecard"]
        assert cfg.show_evidence is False
        assert cfg.table_density == "compact"

    def test_from_dict_defaults(self):
        cfg = template_config_from_dict({})
        assert cfg.template_id == "default"
        assert cfg.show_evidence is True
        assert len(cfg.sections) == len(SECTION_IDS)


class TestBuildThemeCss:

    def test_css_contains_theme_values(self):
        theme = ReportTheme(accent_color="#ff0000", heading_background="#00ff00")
        css = build_theme_css(theme)
        assert "#ff0000" in css
        assert "#00ff00" in css

    def test_css_contains_a4(self):
        css = build_theme_css(ReportTheme())
        assert "@page" in css
        assert "A4" in css

    def test_css_contains_font(self):
        css = build_theme_css(ReportTheme())
        assert "Microsoft YaHei" in css

    def test_css_table_border(self):
        theme = ReportTheme(table_border_color="#abc123")
        css = build_theme_css(theme)
        assert "#abc123" in css


class TestSectionToggle:

    def test_disable_evidence_section(self):
        """关闭 evidence section 后，报告应不包含证据预览表。"""
        from services.report.markdown_builder import build_markdown_report

        result = _minimal_result()
        md = build_markdown_report(result, template_config={"show_evidence": False})
        # 默认报告包含"证据"相关文字
        # 关闭后不应包含证据预览表
        assert "ev_price_close" not in md

    def test_disable_decision_guard_section(self):
        """关闭 decision guard section 后，报告应不包含决策保护器章节。"""
        from services.report.markdown_builder import build_markdown_report

        result = _minimal_result()
        md = build_markdown_report(result, template_config={"show_decision_guard": False})
        assert "决策保护器" not in md

    def test_disable_data_quality_section(self):
        """关闭 data quality section 后，报告应不包含数据质量表格。"""
        from services.report.markdown_builder import build_markdown_report

        result = _minimal_result()
        md = build_markdown_report(result, template_config={"show_data_quality": False})
        # field_quality 表格标题
        assert "字段质量" not in md and "field_quality" not in md

    def test_default_report_contains_key_sections(self):
        """默认报告应包含所有关键章节。"""
        from services.report.markdown_builder import build_markdown_report

        result = _minimal_result()
        md = build_markdown_report(result)
        assert "600519" in md
        assert "决策保护器" in md
        assert "免责声明" in md

    def test_html_theme_css_applied(self):
        """HTML 应根据 theme 输出稳定 CSS。"""
        from services.report.html_builder import build_html_report
        from services.report.template_config import get_theme

        theme = get_theme("institutional_dark")
        html = build_html_report("# Test", title="测试", theme=theme)
        assert theme.accent_color in html
        assert theme.heading_background in html


def _minimal_result():
    """构建最小测试结果 dict。"""
    return {
        "symbol": "600519.SH",
        "name": "测试标的",
        "asset_type": "stock",
        "as_of": "2026-05-04",
        "data_source": "mock",
        "score": 72,
        "rating": "B",
        "action": "观察",
        "max_position": "5%-8%",
        "final_opinion": "测试观点。",
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
        "valuation_data": {
            "pe_ttm": 21.5, "pb_mrq": 5.2, "ps_ttm": 10.1,
            "market_cap": 2100000000000,
            "pe_percentile": 0.42, "pb_percentile": 0.51, "ps_percentile": 0.47,
            "dividend_yield": 0.018, "valuation_label": "neutral",
            "industry_level": "SW1", "industry_name": "SW1食品饮料",
            "industry_peer_count": 35, "industry_valid_peer_count": 32,
            "industry_valid_peer_count_pe": 32, "industry_valid_peer_count_pb": 33,
            "industry_valid_peer_count_ps": 31,
            "industry_pe_percentile": 0.30, "industry_pb_percentile": 0.40,
            "industry_ps_percentile": 0.50,
            "industry_valuation_label": "industry_reasonable",
            "industry_valuation_source": "qmt_sector+qmt_financial+qmt_price",
            "industry_valuation_warnings": [],
        },
        "data_quality": {
            "overall_confidence": 0.85, "has_placeholder": False,
            "blocking_issues": [], "warnings": [],
            "field_quality": {
                "price_data": {"available": True, "source": "mock", "confidence": 0.9, "freshness": "fresh"},
                "fundamental_data": {"available": True, "source": "mock", "confidence": 0.8, "freshness": "fresh"},
                "valuation_data": {"available": True, "source": "mock", "confidence": 0.8, "freshness": "fresh"},
                "event_data": {"available": True, "source": "mock", "confidence": 0.7, "freshness": "fresh"},
            },
        },
        "evidence_bundle": {
            "bundle_id": "evb_test", "symbol": "600519.SH", "as_of": "2026-05-04",
            "items": [
                {"evidence_id": "ev_price_close", "category": "price", "title": "收盘价",
                 "value": 1688.0, "display_value": "1688.00", "source": "mock", "source_date": "2026-05-04", "confidence": 0.9},
            ],
        },
        "decision_guard": {
            "enabled": True, "score": 72, "rating": "B",
            "risk_level": "medium", "llm_action": "观察",
            "max_allowed_action": "观察", "final_action": "观察",
            "guard_reasons": [],
        },
        "debate_result": {
            "bull_case": {"thesis": "看多", "key_arguments": ["理由1"], "catalysts": [], "invalidation_conditions": []},
            "bear_case": {"thesis": "看空", "key_arguments": ["理由1"], "main_concerns": [], "invalidation_conditions": []},
            "risk_review": {"risk_level": "medium", "blocking": False, "max_position": "5%", "risk_summary": "中等风险", "risk_triggers": []},
            "committee_conclusion": {"stance": "中性", "action": "观察", "confidence": 0.7, "final_opinion": "测试观点。"},
        },
    }
