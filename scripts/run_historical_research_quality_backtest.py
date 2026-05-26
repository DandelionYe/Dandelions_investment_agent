"""运行真实历史回测并生成质量报告。

Usage:
    python scripts/run_historical_research_quality_backtest.py
    python scripts/run_historical_research_quality_backtest.py --no-fail-on-threshold
    python scripts/run_historical_research_quality_backtest.py --thresholds path/to/thresholds.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.research.historical_quality_backtest import (  # noqa: E402
    PRICE_ONLY_QMT_ACCEPTANCE_THRESHOLDS,
    REAL_QMT_ACCEPTANCE_THRESHOLDS,
    assert_historical_backtest_acceptance,
    run_historical_backtest,
    summarize_historical_backtest,
    validate_historical_sample,
)


def _format_rate(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1%}"


def _build_markdown_report(summary: dict, fixture_path: str, source: dict | None = None) -> str:
    """构建 Markdown 质量报告。"""
    lines: list[str] = []
    lines.append("# 真实历史回测质量报告")
    lines.append("")
    lines.append(f"- **样本来源**: `{fixture_path}`")
    lines.append(f"- **样本总数**: {summary['total']}")
    lines.append(f"- **通过**: {summary['passed']}")
    lines.append(f"- **失败**: {summary['failed']}")
    lines.append(f"- **通过率**: {summary['pass_rate']:.1%}")
    lines.append("")

    # 数据来源
    if source:
        lines.append("## 数据来源")
        lines.append("")
        lines.append("| 类别 | 来源 |")
        lines.append("|------|------|")
        for k, v in source.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # 样本来源覆盖率
    psc = summary.get("price_source_coverage", 0.0)
    lines.append("## 样本来源覆盖率")
    lines.append("")
    lines.append(f"- **价格数据来源 (QMT)**: {psc:.1%}")
    dg = summary.get("data_gap_summary", {})
    lines.append(f"- **数据完整样本**: {dg.get('data_complete_count', 'N/A')}")
    lines.append(f"- **存在阻断问题样本**: {dg.get('total_with_blocking_issues', 'N/A')}")
    lines.append("")

    # 年份覆盖
    yc = summary.get("year_coverage", {})
    if yc:
        lines.append("## 年份覆盖")
        lines.append("")
        lines.append("| 年份 | 样本数 |")
        lines.append("|------|-------|")
        for year, count in sorted(yc.items()):
            lines.append(f"| {year} | {count} |")
        lines.append("")

    # 市值覆盖
    mc = summary.get("market_cap_coverage", {})
    if mc:
        lines.append("## 市值覆盖")
        lines.append("")
        lines.append(f"- **大盘股 (large_cap)**: {mc.get('large_cap', 0)}")
        lines.append(f"- **中小盘 (small_or_mid_cap)**: {mc.get('small_or_mid_cap', 0)}")
        lines.append("")

    # 场景覆盖矩阵
    lines.append("## 场景覆盖矩阵")
    lines.append("")
    lines.append("| 场景标签 | 覆盖样本数 |")
    lines.append("|---------|----------|")
    for tag, count in sorted(summary.get("scenario_coverage", {}).items()):
        lines.append(f"| {tag} | {count} |")
    lines.append("")

    # 评分分布
    lines.append("## 评分分布")
    lines.append("")
    lines.append("| 分桶 | 样本数 |")
    lines.append("|------|-------|")
    for bucket, count in sorted(summary.get("score_distribution", {}).items()):
        lines.append(f"| {bucket} | {count} |")
    lines.append("")

    # 评级分布
    lines.append("## 评级分布")
    lines.append("")
    lines.append("| 评级 | 样本数 |")
    lines.append("|------|-------|")
    for rating, count in sorted(summary.get("rating_distribution", {}).items()):
        lines.append(f"| {rating} | {count} |")
    lines.append("")

    # 动作分布
    lines.append("## 动作分布")
    lines.append("")
    lines.append("| 动作 | 样本数 |")
    lines.append("|------|-------|")
    for action, count in sorted(summary.get("action_distribution", {}).items()):
        lines.append(f"| {action} | {count} |")
    lines.append("")

    # 关键质量指标
    lines.append("## 关键质量指标")
    lines.append("")
    lines.append(f"- **高风险激进建议违规数**: {summary['high_risk_aggressive_violation_count']}")
    lines.append(f"- **高风险激进建议违规率**: {summary['high_risk_aggressive_violation_rate']:.1%}")
    lines.append(f"- **placeholder 样本数**: {summary.get('placeholder_sample_count', 0)}")
    lines.append(f"- **critical 样本数**: {summary.get('critical_sample_count', 0)}")
    lines.append(f"- **placeholder 保护器命中率**: {_format_rate(summary.get('placeholder_guard_hit_rate'))}")
    lines.append(f"- **critical 保护器命中率**: {_format_rate(summary.get('critical_guard_hit_rate'))}")
    lines.append(f"- **严格 as_of 行业分位有效率**: {summary['industry_percentile_valid_rate']:.1%}")
    lines.append(f"- **全部行业分位有效率（含 non-strict）**: {summary.get('all_industry_percentile_valid_rate', 0.0):.1%}")
    lines.append(f"- **最大单一评分分桶占比**: {summary['max_single_score_bucket_ratio']:.1%}")
    lines.append(f"- **评级分桶数**: {summary['rating_bucket_count']}")
    lines.append(f"- **动作分桶数**: {summary['action_bucket_count']}")
    lines.append(f"- **fundamental source coverage**: {summary.get('fundamental_source_coverage', 0.0):.1%}")
    lines.append(f"- **capital structure source coverage**: {summary.get('capital_structure_source_coverage', 0.0):.1%}")
    lines.append(f"- **valuation source coverage**: {summary.get('valuation_source_coverage', 0.0):.1%}")
    lines.append(f"- **industry source coverage**: {summary.get('industry_source_coverage', 0.0):.1%}")
    lines.append(f"- **data complete coverage**: {summary.get('data_gap_summary', {}).get('data_complete_coverage', 0.0):.1%}")
    lines.append("")

    # forward return 分桶表现（含 120d）
    lines.append("## Forward Return 分桶表现")
    lines.append("")
    lines.append("| 评分分桶 | 样本数 | 平均20日收益 | 平均60日收益 | 平均120日收益 | 平均20日回撤 | 平均60日回撤 | 平均120日回撤 |")
    lines.append("|---------|-------|------------|------------|-------------|------------|------------|-------------|")
    for bucket, data in sorted(summary.get("forward_return_by_score_bucket", {}).items()):
        lines.append(
            f"| {bucket} | {data['count']} | "
            f"{data.get('avg_return_20d', 0):.2%} | "
            f"{data.get('avg_return_60d', 0):.2%} | "
            f"{data.get('avg_return_120d', 0):.2%} | "
            f"{data.get('avg_max_drawdown_20d', 0):.2%} | "
            f"{data.get('avg_max_drawdown_60d', 0):.2%} | "
            f"{data.get('avg_max_drawdown_120d', 0):.2%} |"
        )
    lines.append("")

    lines.append("## Benchmark Return 分桶表现")
    lines.append("")
    lines.append("| 评分分桶 | 样本数 | 平均20日基准 | 平均60日基准 | 平均120日基准 |")
    lines.append("|---------|-------|------------|------------|-------------|")
    for bucket, data in sorted(summary.get("forward_return_by_score_bucket", {}).items()):
        lines.append(
            f"| {bucket} | {data['count']} | "
            f"{data.get('avg_benchmark_return_20d', 0):.2%} | "
            f"{data.get('avg_benchmark_return_60d', 0):.2%} | "
            f"{data.get('avg_benchmark_return_120d', 0):.2%} |"
        )
    lines.append("")

    # 相对收益分桶
    lines.append("## 相对收益分桶表现")
    lines.append("")
    lines.append("| 评分分桶 | 样本数 | 平均20日相对 | 平均60日相对 | 平均120日相对 |")
    lines.append("|---------|-------|------------|------------|-------------|")
    for bucket, data in sorted(summary.get("forward_return_by_score_bucket", {}).items()):
        lines.append(
            f"| {bucket} | {data['count']} | "
            f"{data.get('avg_relative_return_20d', 0):.2%} | "
            f"{data.get('avg_relative_return_60d', 0):.2%} | "
            f"{data.get('avg_relative_return_120d', 0):.2%} |"
        )
    lines.append("")

    # max drawdown by action
    dda = summary.get("max_drawdown_by_action_bucket", {})
    if dda:
        lines.append("## 按动作分桶的最大回撤")
        lines.append("")
        lines.append("| 动作 | 样本数 | 平均20日回撤 | 平均60日回撤 | 平均120日回撤 |")
        lines.append("|------|-------|------------|------------|-------------|")
        for action, data in sorted(dda.items()):
            lines.append(
                f"| {action} | {data['count']} | "
                f"{data.get('avg_max_drawdown_20d', 0):.2%} | "
                f"{data.get('avg_max_drawdown_60d', 0):.2%} | "
                f"{data.get('avg_max_drawdown_120d', 0):.2%} |"
            )
        lines.append("")

    # max drawdown by rating
    ddr = summary.get("max_drawdown_by_rating_bucket", {})
    if ddr:
        lines.append("## 按评级分桶的最大回撤")
        lines.append("")
        lines.append("| 评级 | 样本数 | 平均20日回撤 | 平均60日回撤 | 平均120日回撤 |")
        lines.append("|------|-------|------------|------------|-------------|")
        for rating, data in sorted(ddr.items()):
            lines.append(
                f"| {rating} | {data['count']} | "
                f"{data.get('avg_max_drawdown_20d', 0):.2%} | "
                f"{data.get('avg_max_drawdown_60d', 0):.2%} | "
                f"{data.get('avg_max_drawdown_120d', 0):.2%} |"
            )
        lines.append("")

    # 维度统计
    lines.append("## 评分维度统计")
    lines.append("")
    lines.append("| 维度 | 最小 | 最大 | 平均 |")
    lines.append("|------|------|------|------|")
    for dim, stats in sorted(summary.get("dimension_stats", {}).items()):
        lines.append(f"| {dim} | {stats['min']} | {stats['max']} | {stats['avg']:.1f} |")
    lines.append("")

    # 失败样本列表
    failed = [s for s in summary.get("scenario_summary", []) if not s.get("all_passed")]
    if failed:
        lines.append("## 失败样本列表")
        lines.append("")
        lines.append("| 样本ID | 场景 | 评分 | 评级 | 动作 | 失败检查 |")
        lines.append("|--------|------|------|------|------|---------|")
        for s in failed[:20]:  # 限制输出
            tags = ", ".join(s.get("scenario_tags", []))
            failed_checks = ", ".join(s.get("failed_checks", []))
            lines.append(
                f"| {s['sample_id']} | {tags} | {s.get('score', '-')} | "
                f"{s.get('rating', '-')} | {s.get('action', '-')} | {failed_checks} |"
            )
        if len(failed) > 20:
            lines.append(f"| ... | 还有 {len(failed) - 20} 个 | | | | |")
        lines.append("")
    else:
        lines.append("## 失败样本列表")
        lines.append("")
        lines.append("无失败样本。")
        lines.append("")

    # 数据缺口
    lines.append("## 数据缺口与不可验收原因")
    lines.append("")
    lines.append(f"- **价格来源覆盖率**: {psc:.1%}")
    lines.append(f"- **数据完整样本数**: {dg.get('data_complete_count', 'N/A')}")
    lines.append(f"- **存在阻断问题样本数**: {dg.get('total_with_blocking_issues', 'N/A')}")
    lines.append(f"- **基本面来源覆盖率**: {summary.get('fundamental_source_coverage', 0.0):.1%}")
    lines.append(f"- **股本/BPS 来源覆盖率**: {summary.get('capital_structure_source_coverage', 0.0):.1%}")
    lines.append(f"- **估值来源覆盖率**: {summary.get('valuation_source_coverage', 0.0):.1%}")
    lines.append(f"- **行业来源覆盖率**: {summary.get('industry_source_coverage', 0.0):.1%}")
    lines.append(f"- **完整研究输入覆盖率**: {dg.get('data_complete_coverage', 0.0):.1%}")
    if psc < 1.0:
        lines.append("- **注意**: 部分样本价格数据非 QMT 来源，不满足真实 QMT 验收")
    if (
        summary.get("fundamental_source_coverage", 0.0) == 0.0
        or summary.get("valuation_source_coverage", 0.0) == 0.0
        or summary.get("industry_source_coverage", 0.0) == 0.0
    ):
        lines.append("- **注意**: 当前为 QMT price-only 样本池，不满足严格 Phase 2B 研究质量验收。")
    if summary.get("critical_sample_count", 0) == 0:
        lines.append("- **注意**: Phase 2B 不做历史新闻事件回测，critical 样本不作为本阶段阻塞项。")
    lines.append("")

    # 质量结论
    lines.append("## 质量结论")
    lines.append("")
    is_price_only = (
        summary.get("price_source_coverage", 0.0) == 1.0
        and (
            summary.get("fundamental_source_coverage", 0.0) == 0.0
            or summary.get("valuation_source_coverage", 0.0) == 0.0
            or summary.get("industry_source_coverage", 0.0) == 0.0
        )
    )
    if is_price_only:
        lines.append("QMT 价格链路已通过 smoke 检查，但基本面/估值/行业输入缺失，严格 Phase 2B 未完成。")
    elif dg.get("data_complete_coverage", 0.0) < 0.5:
        lines.append("历史价格、CSMAR 估值和 EVA 股本/BPS 已接入，但完整研究输入覆盖率不足，严格 Phase 2B 未完成。")
    elif summary["failed"] == 0:
        lines.append("所有历史样本均通过严格验收。评分/估值/保护器行为稳定。")
    else:
        lines.append(f"**{summary['failed']} 个样本未通过验收**，需要检查评分引擎或决策保护器逻辑。")
    lines.append("")

    # 后续建议
    lines.append("## 后续建议")
    lines.append("")
    if psc < 1.0:
        lines.append("- 接入真实 QMT 历史数据替换手动快照（使用 --use-qmt --require-qmt）")
    lines.append("- 建立季度回归机制，检测评分漂移")
    lines.append("- 补充可严格 as_of 的历史行业分类库和盈利质量基本面来源")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行历史回测质量报告")
    parser.add_argument("--samples",
                        default="tests/fixtures/research_quality_historical_samples.json",
                        help="样本文件路径")
    parser.add_argument("--output-dir",
                        default="storage/artifacts/research_quality",
                        help="输出目录")
    parser.add_argument("--thresholds", default=None, help="验收阈值 JSON 文件")
    parser.add_argument("--no-fail-on-threshold", action="store_true",
                        help="阈值失败时不返回 exit code 1")
    parser.add_argument("--allow-price-only", action="store_true",
                        help="允许 QMT price-only smoke 验收；不能用于标记 Phase 2B 完成")
    args = parser.parse_args()

    # 加载样本
    sample_path = PROJECT_ROOT / args.samples
    if not sample_path.exists():
        print(f"错误：样本文件不存在: {sample_path}", file=sys.stderr)
        return 2

    try:
        fixture_data = json.loads(sample_path.read_text(encoding="utf-8"))
        samples = fixture_data.get("samples", [])
        source = fixture_data.get("source")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"错误：样本文件格式错误: {exc}", file=sys.stderr)
        return 2

    # 校验 schema
    schema_errors: list[str] = []
    for sample in samples:
        errors = validate_historical_sample(sample)
        if errors:
            schema_errors.append(f"  {sample.get('sample_id', '?')}: {errors}")
    if schema_errors:
        print(f"警告：{len(schema_errors)} 个样本 schema 校验失败:", file=sys.stderr)
        for e in schema_errors[:10]:
            print(e, file=sys.stderr)

    # 运行回测
    backtest_result = run_historical_backtest(samples)
    summary = summarize_historical_backtest(backtest_result)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    # 加载自定义阈值
    thresholds = None
    if args.thresholds:
        thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))

    # 输出
    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = output_dir / "historical_backtest_summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"JSON: {json_path}")

    # Markdown
    md_path = output_dir / "historical_backtest_report.md"
    md_content = _build_markdown_report(summary, str(sample_path), source)
    md_path.write_text(md_content, encoding="utf-8")
    print(f"Markdown: {md_path}")

    # 验收：自动检测真实 QMT 模式并使用对应阈值
    if thresholds is None and source and source.get("price") == "qmt_xtdata":
        if args.allow_price_only:
            thresholds = PRICE_ONLY_QMT_ACCEPTANCE_THRESHOLDS
            print("检测到 QMT price-only 数据源，使用 smoke 阈值")
        else:
            thresholds = REAL_QMT_ACCEPTANCE_THRESHOLDS
            print("检测到 QMT 数据源，使用严格 Phase 2B 阈值")

    try:
        assert_historical_backtest_acceptance(summary, thresholds)
        print("验收通过")
        return 0
    except AssertionError as exc:
        print(f"验收失败:\n{exc}", file=sys.stderr)
        if args.no_fail_on_threshold:
            print("--no-fail-on-threshold 模式，返回 exit code 0")
            return 0
        return 1


if __name__ == "__main__":
    sys.exit(main())
