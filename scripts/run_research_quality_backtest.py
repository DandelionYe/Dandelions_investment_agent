"""研究质量回测脚本。

离线运行，不连接 QMT/网络/Redis。
读取回测样本，执行评分和决策保护器，输出 JSON 和 Markdown artifact。

Usage:
    python scripts/run_research_quality_backtest.py
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.research.quality_backtest import (
    load_backtest_samples,
    run_backtest,
    summarize_backtest,
    assert_backtest_acceptance,
)


def main():
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "research_quality_backtest_samples.json"
    output_dir = PROJECT_ROOT / "storage" / "artifacts" / "research_quality"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"加载回测样本: {fixture_path}")
    samples = load_backtest_samples(fixture_path)
    print(f"样本数量: {len(samples)}")

    print("运行回测...")
    result = run_backtest(samples)
    summary = summarize_backtest(result)

    print(f"总样本: {summary['total']}")
    print(f"通过: {summary['passed']}")
    print(f"失败: {summary['failed']}")
    print(f"通过率: {summary['pass_rate']:.1%}")

    # 输出 JSON artifact
    json_path = output_dir / "backtest_summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"JSON artifact: {json_path}")

    # 输出 Markdown artifact
    md_lines = ["# 研究质量回测报告", ""]
    md_lines.append(f"总样本: {summary['total']}, 通过: {summary['passed']}, "
                    f"失败: {summary['failed']}, 通过率: {summary['pass_rate']:.1%}")
    md_lines.append("")
    md_lines.append("## 场景汇总")
    md_lines.append("| 样本 | 场景 | 评分 | 评级 | 建议 | 结果 |")
    md_lines.append("|---|---|---:|---|---|---|")
    for s in summary["scenario_summary"]:
        status = "PASS" if s["all_passed"] else "FAIL"
        md_lines.append(f"| {s['sample_id']} | {s['scenario']} | {s['score']} | "
                        f"{s['rating']} | {s['action']} | {status} |")
    md_lines.append("")
    md_lines.append("## 维度统计")
    md_lines.append("| 维度 | 最小 | 最大 | 平均 |")
    md_lines.append("|---|---:|---:|---:|")
    for dim, stats in summary.get("dimension_stats", {}).items():
        md_lines.append(f"| {dim} | {stats['min']} | {stats['max']} | {stats['avg']:.1f} |")

    md_path = output_dir / "backtest_summary.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown artifact: {md_path}")

    # 验收检查
    try:
        assert_backtest_acceptance(summary)
        print("\n验收通过!")
        return 0
    except AssertionError as e:
        print(f"\n验收失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
