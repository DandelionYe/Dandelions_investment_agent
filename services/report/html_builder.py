from pathlib import Path

import markdown as md


def build_html_report(markdown_text: str, title: str = "投研报告") -> str:
    """
    把 Markdown 文本转换成 HTML。
    """

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
        @page {{
            size: A4;
            margin: 18mm 16mm 18mm 16mm;
        }}

        body {{
            font-family: "Microsoft YaHei", "SimSun", Arial, sans-serif;
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
            border-bottom: 2px solid #222;
            padding-bottom: 16px;
            margin: 0 0 28px 0;
            font-size: 26px;
            line-height: 1.35;
        }}

        h2 {{
            margin-top: 30px;
            margin-bottom: 14px;
            border-left: 5px solid #333;
            padding: 8px 12px;
            background: #f5f5f5;
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
            border: 1px solid #ccc;
            padding: 7px 10px;
            text-align: left;
            vertical-align: top;
        }}

        th {{
            background: #f0f0f0;
            font-weight: 600;
        }}

        td:last-child,
        th:last-child {{
            text-align: left;
        }}

        blockquote {{
            border-left: 4px solid #888;
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