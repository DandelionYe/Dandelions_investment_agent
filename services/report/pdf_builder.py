from pathlib import Path


def save_pdf_report(
    html_path: str,
    output_dir: str = "storage/reports"
) -> str | None:
    """
    从 HTML 文件生成 PDF 文件。
    如果当前环境缺少 WeasyPrint 依赖，则返回 None，不阻塞主流程。
    """

    try:
        from weasyprint import HTML
    except Exception as exc:
        print()
        print("PDF 生成被跳过：当前 Windows 环境缺少 WeasyPrint 所需的底层依赖。")
        print(f"具体错误：{exc}")
        print("Markdown 和 HTML 报告仍然有效。")
        return None

    html_file = Path(html_path)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = Path(output_dir) / f"{html_file.stem}.pdf"

    try:
        HTML(filename=str(html_file)).write_pdf(str(output_path))
        return str(output_path)
    except Exception as exc:
        print()
        print("PDF 生成失败，但 Markdown 和 HTML 已生成。")
        print(f"具体错误：{exc}")
        return None