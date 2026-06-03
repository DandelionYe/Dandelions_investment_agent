"""报告模板配置层。

在不破坏现有 API 的前提下，为 Markdown/HTML/PDF 报告提供模板和主题配置。

支持 4 个正式模板预设：
- default：保持当前用户体验，不造成已有报告大幅破坏。
- institutional_full：最完整的证据、数据质量、风险降级、历史分位解释。
- compact_review：适合快速审阅，只保留核心结论、关键证据、主要风险。
- risk_only：聚焦风险、保护器、数据质量问题，不展开完整投资叙述。
"""

from __future__ import annotations

import copy
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

# 正式模板 ID 集合
FORMAL_TEMPLATE_IDS = frozenset({
    "default",
    "institutional_full",
    "compact_review",
    "risk_only",
})

FORMAL_THEME_IDS = frozenset({
    "institutional_light",
    "institutional_dark",
    "compact_blue",
})


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
    text_color: str = "#222222"
    heading_color: str = "#333333"
    body_background: str = "#ffffff"
    blockquote_bg: str = "#f7f7f7"
    blockquote_color: str = "#333333"
    code_bg: str = "#f2f2f2"
    th_background: str = "#f0f0f0"
    th_color: str = "#222222"


# ── 内置主题 ─────────────────────────────────────────────────

_THEMES: dict[str, ReportTheme] = {
    "institutional_light": ReportTheme(),
    "institutional_dark": ReportTheme(
        theme_id="institutional_dark",
        accent_color="#4a90d9",
        heading_background="#2a2a2a",
        table_border_color="#555555",
        text_color="#e0e0e0",
        heading_color="#e8e8e8",
        body_background="#1e1e1e",
        blockquote_bg="#2d2d2d",
        blockquote_color="#d0d0d0",
        code_bg="#2d2d2d",
        th_background="#333333",
        th_color="#e0e0e0",
    ),
    "compact_blue": ReportTheme(
        theme_id="compact_blue",
        page_margin="12mm 10mm 12mm 10mm",
        accent_color="#1a5276",
        heading_background="#eaf2f8",
        table_border_color="#aed6f1",
        heading_color="#1a5276",
        blockquote_bg="#eaf2f8",
        th_background="#d6eaf8",
    ),
}

# ── 内置模板预设 ──────────────────────────────────────────────

_TEMPLATE_PRESETS: dict[str, ReportTemplateConfig] = {
    "default": ReportTemplateConfig(
        template_id="default",
        theme_id="institutional_light",
        sections=list(SECTION_IDS),
        show_evidence=True,
        show_data_quality=True,
        show_decision_guard=True,
        show_disclaimer=True,
        table_density="normal",
    ),
    "institutional_full": ReportTemplateConfig(
        template_id="institutional_full",
        theme_id="institutional_light",
        sections=list(SECTION_IDS),
        show_evidence=True,
        show_data_quality=True,
        show_decision_guard=True,
        show_disclaimer=True,
        table_density="normal",
    ),
    "compact_review": ReportTemplateConfig(
        template_id="compact_review",
        theme_id="compact_blue",
        sections=[
            "basic_info",
            "committee_conclusion",
            "data_source_and_price",
            "scorecard",
            "risk_officer",
            "decision_guard",
            "follow_up",
            "disclaimer",
        ],
        show_evidence=True,
        show_data_quality=False,
        show_decision_guard=True,
        show_disclaimer=True,
        table_density="compact",
    ),
    "risk_only": ReportTemplateConfig(
        template_id="risk_only",
        theme_id="institutional_dark",
        sections=[
            "basic_info",
            "committee_conclusion",
            "scorecard",
            "risk_officer",
            "decision_guard",
            "disclaimer",
        ],
        show_evidence=False,
        show_data_quality=True,
        show_decision_guard=True,
        show_disclaimer=True,
        table_density="compact",
    ),
}


def default_template_config() -> ReportTemplateConfig:
    """返回默认模板配置。"""
    return ReportTemplateConfig()


def get_template_preset(template_id: str) -> ReportTemplateConfig:
    """获取模板预设，未知 ID 抛出 ValueError。

    Parameters
    ----------
    template_id : str
        模板 ID，必须是 FORMAL_TEMPLATE_IDS 中的一个。

    Returns
    -------
    ReportTemplateConfig
        对应的模板配置副本。

    Raises
    ------
    ValueError
        如果 template_id 不在已知模板列表中。
    """
    if template_id not in _TEMPLATE_PRESETS:
        raise ValueError(
            f"未知模板 ID: {template_id!r}，"
            f"可用模板: {', '.join(sorted(FORMAL_TEMPLATE_IDS))}"
        )
    return copy.deepcopy(_TEMPLATE_PRESETS[template_id])


def get_theme(theme_id: str) -> ReportTheme:
    """获取主题，未知 id 返回默认主题。"""
    return _THEMES.get(theme_id, ReportTheme())


def validate_template_config(config: ReportTemplateConfig) -> list[str]:
    """校验模板配置，返回警告列表（空列表表示无问题）。"""
    warnings: list[str] = []
    if config.template_id not in FORMAL_TEMPLATE_IDS:
        warnings.append(
            f"未知 template_id: {config.template_id}，"
            f"可用模板: {', '.join(sorted(FORMAL_TEMPLATE_IDS))}"
        )
    if config.theme_id not in _THEMES:
        warnings.append(f"未知 theme_id: {config.theme_id}，将使用默认主题")
    unknown = [s for s in config.sections if s not in SECTION_IDS]
    if unknown:
        warnings.append(f"未知章节: {', '.join(unknown)}")
    return warnings


def template_config_from_dict(data: dict) -> ReportTemplateConfig:
    """从 dict 构造 ReportTemplateConfig。

    如果 data 包含 template_id 且该 ID 是已知预设，则以预设为基础，
    data 中的其他字段会覆盖预设值。否则使用默认值作为基础。
    """
    template_id = data.get("template_id", "default")

    # Start from preset if known, otherwise from defaults
    if template_id in _TEMPLATE_PRESETS:
        cfg = copy.deepcopy(_TEMPLATE_PRESETS[template_id])
    else:
        cfg = ReportTemplateConfig(template_id=template_id)

    # Apply overrides from data
    if "theme_id" in data:
        cfg.theme_id = data["theme_id"]
    if "sections" in data:
        cfg.sections = list(data["sections"])
    if "show_evidence" in data:
        cfg.show_evidence = data["show_evidence"]
    if "show_data_quality" in data:
        cfg.show_data_quality = data["show_data_quality"]
    if "show_decision_guard" in data:
        cfg.show_decision_guard = data["show_decision_guard"]
    if "show_disclaimer" in data:
        cfg.show_disclaimer = data["show_disclaimer"]
    if "table_density" in data:
        cfg.table_density = data["table_density"]
    if "language" in data:
        cfg.language = data["language"]

    return cfg


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
            color: {theme.text_color};
            max-width: 960px;
            margin: 0 auto;
            padding: 0;
            background: {theme.body_background};
            font-size: 14px;
        }}

        h1 {{
            text-align: center;
            border-bottom: 2px solid {theme.accent_color};
            padding-bottom: 16px;
            margin: 0 0 28px 0;
            font-size: 26px;
            line-height: 1.35;
            color: {theme.heading_color};
        }}

        h2 {{
            margin-top: 30px;
            margin-bottom: 14px;
            border-left: 5px solid {theme.accent_color};
            padding: 8px 12px;
            background: {theme.heading_background};
            font-size: 20px;
            line-height: 1.35;
            color: {theme.heading_color};
            break-after: avoid;
        }}

        h3 {{
            margin-top: 22px;
            margin-bottom: 10px;
            font-size: 16px;
            line-height: 1.35;
            color: {theme.heading_color};
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
            color: {theme.text_color};
        }}

        th {{
            background: {theme.th_background};
            font-weight: 600;
            color: {theme.th_color};
        }}

        blockquote {{
            border-left: 4px solid {theme.accent_color};
            margin: 14px 0 18px 0;
            padding: 8px 14px;
            background: {theme.blockquote_bg};
            color: {theme.blockquote_color};
        }}

        code {{
            background: {theme.code_bg};
            padding: 2px 4px;
            border-radius: 4px;
            font-family: Consolas, "Courier New", monospace;
        }}

        strong {{
            font-weight: 700;
        }}

        hr {{
            border: none;
            border-top: 1px solid {theme.table_border_color};
            margin: 24px 0;
        }}

        a {{
            color: {theme.accent_color};
            text-decoration: none;
        }}
    """


def resolve_report_config(
    report_template: str | None = None,
    report_theme: str | None = None,
) -> tuple[ReportTemplateConfig, ReportTheme]:
    """从任务参数解析报告模板和主题配置。

    Parameters
    ----------
    report_template : str | None
        模板 ID（如 "default", "institutional_full", "compact_review", "risk_only"）。
        None 或空字符串使用 "default"。
    report_theme : str | None
        主题 ID（如 "institutional_light", "institutional_dark", "compact_blue"）。
        None 或空字符串使用模板预设的主题。

    Returns
    -------
    tuple[ReportTemplateConfig, ReportTheme]
        解析后的模板配置和主题。

    Raises
    ------
    ValueError
        显式传入未知模板或主题时抛出，避免生产任务静默生成错误模板。
    """
    template_id = (report_template or "default").strip() or "default"

    cfg = get_template_preset(template_id)

    # Theme override
    if report_theme:
        theme_id = report_theme.strip()
        if theme_id:
            if theme_id not in FORMAL_THEME_IDS:
                raise ValueError(
                    f"未知主题 ID: {theme_id!r}，"
                    f"可用主题: {', '.join(sorted(FORMAL_THEME_IDS))}"
                )
            cfg.theme_id = theme_id

    theme = get_theme(cfg.theme_id)
    return cfg, theme
