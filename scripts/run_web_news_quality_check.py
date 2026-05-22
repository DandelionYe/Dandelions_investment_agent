"""网页新闻/舆情质量验收脚本。

离线运行，不发真实网络请求。
读取新闻质量样本，执行去重/相关性/质量评估，输出 JSON 和 Markdown artifact。

Usage:
    python scripts/run_web_news_quality_check.py
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.data.news_quality import (
    evaluate_news_provider_result,
    summarize_news_quality,
)


def main():
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "web_news_quality_samples.json"
    output_dir = PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"加载新闻质量样本: {fixture_path}")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    samples = data["samples"]
    print(f"样本数量: {len(samples)}")

    evaluations = []
    all_passed = True

    for sample in samples:
        sample_id = sample["id"]
        symbol_info = sample["symbol_info"]
        items = sample["items"]
        provider_metadata = sample.get("provider_metadata", {"success": True})

        result = {
            "data": items,
            "metadata": provider_metadata,
        }
        evaluation = evaluate_news_provider_result(result, symbol_info)
        evaluation["sample_id"] = sample_id
        evaluations.append(evaluation)

        # 验收检查
        expected = sample["expected"]
        checks_passed = True

        if "deduped_total" in expected and evaluation["deduped_total"] != expected["deduped_total"]:
            print(f"  FAIL [{sample_id}] deduped_total: "
                  f"got {evaluation['deduped_total']}, expected {expected['deduped_total']}")
            checks_passed = False

        if "relevant_count_min" in expected and evaluation["relevant_count"] < expected["relevant_count_min"]:
            print(f"  FAIL [{sample_id}] relevant_count: "
                  f"got {evaluation['relevant_count']}, min {expected['relevant_count_min']}")
            checks_passed = False

        if "relevant_count_max" in expected and evaluation["relevant_count"] > expected["relevant_count_max"]:
            print(f"  FAIL [{sample_id}] relevant_count: "
                  f"got {evaluation['relevant_count']}, max {expected['relevant_count_max']}")
            checks_passed = False

        if "low_quality_count_min" in expected and evaluation["low_quality_count"] < expected["low_quality_count_min"]:
            print(f"  FAIL [{sample_id}] low_quality_count: "
                  f"got {evaluation['low_quality_count']}, min {expected['low_quality_count_min']}")
            checks_passed = False

        if "failure_count" in expected and evaluation["failure_count"] != expected["failure_count"]:
            print(f"  FAIL [{sample_id}] failure_count: "
                  f"got {evaluation['failure_count']}, expected {expected['failure_count']}")
            checks_passed = False

        if checks_passed:
            print(f"  PASS [{sample_id}]")
        else:
            all_passed = False

    summary = summarize_news_quality(evaluations)
    print(f"\n汇总: 总评估={summary['total_evaluations']}, "
          f"总条目={summary['total_items']}, 去重后={summary['total_deduped']}, "
          f"相关={summary['total_relevant']}, 低质量={summary['total_low_quality']}, "
          f"失败={summary['total_failures']}")

    # 输出 JSON artifact
    json_path = output_dir / "summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"JSON artifact: {json_path}")

    # 输出 Markdown artifact
    md_lines = ["# 网页新闻质量验收报告", ""]
    md_lines.append(f"总评估: {summary['total_evaluations']}")
    md_lines.append(f"总条目: {summary['total_items']}")
    md_lines.append(f"去重后: {summary['total_deduped']}")
    md_lines.append(f"相关: {summary['total_relevant']}")
    md_lines.append(f"低质量: {summary['total_low_quality']}")
    md_lines.append(f"失败: {summary['total_failures']}")
    md_lines.append(f"整体相关率: {summary['overall_relevance_rate']:.1%}")
    md_lines.append("")
    md_lines.append("## 来源统计")
    md_lines.append("| 来源 | 条数 |")
    md_lines.append("|---|---:|")
    for src, cnt in sorted(summary["source_counts"].items()):
        md_lines.append(f"| {src} | {cnt} |")
    if summary["warnings"]:
        md_lines.append("")
        md_lines.append("## 警告")
        for w in summary["warnings"]:
            md_lines.append(f"- {w}")

    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown artifact: {md_path}")

    if all_passed:
        print("\n验收通过!")
        return 0
    else:
        print("\n验收失败!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
