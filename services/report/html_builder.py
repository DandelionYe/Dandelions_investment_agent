from pathlib import Path

import markdown as md


def build_html_report(markdown_text: str, title: str = "投研报告", theme=None) -> str:
    """
    把 Markdown 文本转换成 HTML。

    Parameters
    ----------
    markdown_text : str
        Markdown 文本。
    title : str
        HTML 标题。
    theme : ReportTheme | dict | None
        视觉主题。dict 会自动转换为 ReportTheme。None 使用默认主题。
    """
    from services.report.template_config import ReportTheme, build_theme_css

    if theme is None:
        from services.report.template_config import get_theme
        theme_obj = get_theme("institutional_light")
    elif isinstance(theme, dict):
        theme_obj = ReportTheme(**theme)
    else:
        theme_obj = theme

    css = build_theme_css(theme_obj)

    body_html = md.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "toc"],
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        {css}
    </style>
</head>
<body>
{body_html}
</body>
</html>
"""

    return html


def save_html_report(
    markdown_path: str,
    output_dir: str = "storage/reports",
) -> str:
    """
    从 Markdown 文件生成 HTML 文件。
    """

    markdown_file = Path(markdown_path)
    markdown_text = markdown_file.read_text(encoding="utf-8")

    title = markdown_file.stem.replace("_report", "") + " 投研报告"
    html = build_html_report(markdown_text, title=title)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = Path(output_dir) / f"{markdown_file.stem}.html"
    output_path.write_text(html, encoding="utf-8")

    return str(output_path)