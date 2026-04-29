from pathlib import Path
import sys
import asyncio

from playwright.sync_api import sync_playwright


def _ensure_windows_event_loop_policy():
    """
    Windows 下确保 Playwright 可以创建 Chromium 子进程。
    Streamlit/Tornado 环境有时会使用不支持 subprocess 的事件循环。
    """
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except AttributeError:
            pass


def save_pdf_report_with_playwright(
    html_path: str,
    output_dir: str = "storage/reports"
) -> str | None:
    """
    使用 Playwright / Chromium 把 HTML 文件导出为 PDF。
    """

    _ensure_windows_event_loop_policy()

    html_file = Path(html_path).resolve()

    if not html_file.exists():
        raise FileNotFoundError(f"HTML 文件不存在：{html_file}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = Path(output_dir) / f"{html_file.stem}.pdf"
    output_path = output_path.resolve()

    file_url = html_file.as_uri()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(file_url, wait_until="networkidle")

            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "18mm",
                    "right": "16mm",
                    "bottom": "18mm",
                    "left": "16mm",
                },
            )

            browser.close()
    except Exception as exc:
        print()
        print("PDF 生成失败，但 JSON、Markdown 和 HTML 已生成。")
        print(f"具体错误：{exc}")
        return None

    return str(output_path)
