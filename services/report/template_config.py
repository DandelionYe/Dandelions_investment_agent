"""报告模板配置层。

在不破坏现有 API 的前提下，为 Markdown/HTML/PDF 报告提供模板和主题配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# 报告章节标识
SECTION_IDS = [
    "basic_info",
    "committee_conclusion",
    "data_source_and_price",
    "scorecard",
    "bull_case",
    "bear_case",
    "risk_officer",
    "decision_guard",
    "debate_convergence",
    "follow_up",
    "disclaimer",
]


@dataclass
class ReportTemplateConfig:
    """报告模板配置。"""

    template_id: str = "default"
    theme_id: str = "institutional_light"
    sections: list[str] = field(default_factory=lambda: list(SECTION_IDS))
    show_evidence: bool = True
    show_data_quality: bool = True
    show_decision_guard: bool = True
    show_disclaimer: bool = True
    table_density: Literal["compact", "normal"] = "normal"
    language: Literal["zh-CN"] = "zh-CN"


@dataclass
class ReportTheme:
    """报告视觉主题。"""

    theme_id: str = "institutional_light"
    font_family: str = '"Microsoft YaHei", "SimSun", Arial, sans-serif'
    page_margin: str = "18mm 16mm 18mm 16mm"
    accent_color: str = "#333333"
    heading_background: str = "#f5f5f5"
    table_border_color: str = "#cccccc"


# ── 内置主题 ─────────────────────────────────────────────────

_THEMES: dict[str, ReportTheme] = {
    "institutional_light": ReportTheme(),
    "institutional_dark": ReportTheme(
        theme_id="institutional_dark",
        accent_color="#4a90d9",
        heading_background="#2a2a2a",
        table_border_color="#555555",
    ),
    "compact_blue": ReportTheme(
        theme_id="compact_blue",
        page_margin="12mm 10mm 12mm 10mm",
        accent_color="#1a5276",
        heading_background="#eaf2f8",
        table_border_color="#aed6f1",
    ),
}


def default_template_config() -> ReportTemplateConfig:
    """返回默认模板配置。"""
    return ReportTemplateConfig()


def get_theme(theme_id: str) -> ReportTheme:
    """获取主题，未知 id 返回默认主题。"""
    return _THEMES.get(theme_id, ReportTheme())


def validate_template_config(config: ReportTemplateConfig) -> list[str]:
    """校验模板配置，返回警告列表（空列表表示无问题）。"""
    warnings: list[str] = []
    if config.template_id not in ("default",):
        warnings.append(f"未知 template_id: {config.template_id}")
    if config.theme_id not in _THEMES:
        warnings.append(f"未知 theme_id: {config.theme_id}，将使用默认主题")
    unknown = [s for s in config.sections if s not in SECTION_IDS]
    if unknown:
        warnings.append(f"未知章节: {', '.join(unknown)}")
    return warnings


def template_config_from_dict(data: dict) -> ReportTemplateConfig:
    """从 dict 构造 ReportTemplateConfig。"""
    sections = data.get("sections")
    if sections is None:
        sections = list(SECTION_IDS)
    return ReportTemplateConfig(
        template_id=data.get("template_id", "default"),
        theme_id=data.get("theme_id", "institutional_light"),
        sections=list(sections),
        show_evidence=data.get("show_evidence", True),
        show_data_quality=data.get("show_data_quality", True),
        show_decision_guard=data.get("show_decision_guard", True),
        show_disclaimer=data.get("show_disclaimer", True),
        table_density=data.get("table_density", "normal"),
        language=data.get("language", "zh-CN"),
    )


def build_theme_css(theme: ReportTheme) -> str:
    """根据主题生成 CSS 字符串片段。"""
    return f"""
        @page {{
            size: A4;
            margin: {theme.page_margin};
        }}

        body {{
            font-family: {theme.font_family};
            line-height: 1.75;
            color: #222;
            max-width: 960px;
            margin: 0 auto;
            padding: 0;
            background: #ffffff;
            font-size: 14px;
        }}

        h1 {{
            text-align: center;
            border-bottom: 2px solid {theme.accent_color};
            padding-bottom: 16px;
            margin: 0 0 28px 0;
            font-size: 26px;
            line-height: 1.35;
        }}

        h2 {{
            margin-top: 30px;
            margin-bottom: 14px;
            border-left: 5px solid {theme.accent_color};
            padding: 8px 12px;
            background: {theme.heading_background};
            font-size: 20px;
            line-height: 1.35;
            break-after: avoid;
        }}

        h3 {{
            margin-top: 22px;
            margin-bottom: 10px;
            font-size: 16px;
            line-height: 1.35;
            color: #333;
            break-after: avoid;
        }}

        p {{
            margin: 8px 0 12px 0;
        }}

        ul, ol {{
            margin-top: 8px;
            margin-bottom: 12px;
            padding-left: 24px;
        }}

        li {{
            margin: 4px 0;
        }}

        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 14px 0 20px 0;
            font-size: 13px;
            page-break-inside: avoid;
        }}

        th, td {{
            border: 1px solid {theme.table_border_color};
            padding: 7px 10px;
            text-align: left;
            vertical-align: top;
        }}

        th {{
            background: #f0f0f0;
            font-weight: 600;
        }}

        blockquote {{
            border-left: 4px solid {theme.accent_color};
            margin: 14px 0 18px 0;
            padding: 8px 14px;
            background: #f7f7f7;
            color: #333;
        }}

        code {{
            background: #f2f2f2;
            padding: 2px 4px;
            border-radius: 4px;
            font-family: Consolas, "Courier New", monospace;
        }}

        strong {{
            font-weight: 700;
        }}

        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 24px 0;
        }}

        a {{
            color: #222;
            text-decoration: none;
        }}
    """
