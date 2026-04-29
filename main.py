import argparse
import json

from services.orchestrator.single_asset_research import run_single_asset_research
from services.report.markdown_builder import save_markdown_report
from services.report.html_builder import save_html_report
from services.report.pdf_builder_playwright import save_pdf_report_with_playwright
from services.report.json_builder import save_json_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="600519.SH", help="股票或ETF代码")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="不调用 DeepSeek，使用本地 mock 文本",
    )
    parser.add_argument(
        "--data-source",
        choices=["qmt", "akshare", "mock"],
        default="mock",
        help="数据源：qmt 为主数据源，akshare 仅用于 fallback/调试，mock 用于离线测试",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="跳过 Playwright PDF 导出，只生成 JSON/Markdown/HTML",
    )
    args = parser.parse_args()

    result = run_single_asset_research(
        args.symbol,
        use_llm=not args.no_llm,
        data_source=args.data_source,
    )

    json_path = save_json_result(result)
    markdown_path = save_markdown_report(result)
    html_path = save_html_report(markdown_path)
    pdf_path = None
    if not args.no_pdf:
        pdf_path = save_pdf_report_with_playwright(html_path)

    print("研究结果 JSON：")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print()
    print(f"Markdown 报告已生成：{markdown_path}")
    print(f"HTML 报告已生成：{html_path}")
    if pdf_path:
        print(f"PDF 报告已生成：{pdf_path}")
    else:
        print("PDF 报告未生成。")
    print(f"JSON 结果已生成：{json_path}")


if __name__ == "__main__":
    main()
