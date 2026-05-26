"""P2 Phase 6: 研究质量治理脚本。

统一加载 baseline，比较已有 artifact，输出 drift/failure 报告。

Usage:
    python scripts/run_research_quality_governance.py
    python scripts/run_research_quality_governance.py --refresh-offline-artifacts
    python scripts/run_research_quality_governance.py --include-web-news-live
    python scripts/run_research_quality_governance.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.research.quality_governance import (  # noqa: E402
    GovernanceReport,
    generate_baseline_candidate,
    generate_drift_report,
    generate_failures_jsonl,
    load_baseline,
    run_governance,
    validate_baseline_schema,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="研究质量治理")
    parser.add_argument(
        "--baseline",
        default=str(PROJECT_ROOT / "configs" / "research_quality_baseline.json"),
        help="baseline 配置路径",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "storage" / "artifacts" / "research_quality" / "governance"),
        help="输出目录",
    )
    parser.add_argument(
        "--refresh-offline-artifacts",
        action="store_true",
        help="运行离线质量脚本后再比较",
    )
    parser.add_argument(
        "--include-qmt-regression",
        action="store_true",
        help="包含 QMT 数据质量回归",
    )
    parser.add_argument(
        "--include-web-news-live",
        action="store_true",
        help="包含真实网页新闻 monitor artifact",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="输出 baseline candidate",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="warning 也返回非 0",
    )
    parser.add_argument(
        "--fail-on-watch",
        action="store_true",
        help="watch 也返回非 0",
    )
    parser.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="刷新脚本失败时继续使用旧 artifact（默认会退出）",
    )
    return parser.parse_args()


def _refresh_offline_artifacts() -> list[str]:
    """运行离线质量脚本刷新 artifact。返回失败脚本列表。"""
    scripts = [
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_historical_research_quality_backtest.py")],
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_web_news_quality_check.py")],
    ]
    failures: list[str] = []
    for cmd in scripts:
        print(f"运行: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            print(f"  错误: exit code {result.returncode}")
            if result.stderr:
                print(f"  {result.stderr[:500]}")
            failures.append(" ".join(cmd))
        else:
            print("  完成")
    return failures


def main() -> int:
    args = parse_args()

    # Refresh offline artifacts if requested
    if args.refresh_offline_artifacts:
        refresh_failures = _refresh_offline_artifacts()
        if refresh_failures and not args.allow_stale_artifacts:
            print(f"\n错误: {len(refresh_failures)} 个刷新脚本失败，退出。"
                  f" 使用 --allow-stale-artifacts 可继续使用旧 artifact。",
                  file=sys.stderr)
            return 2

    # Load baseline
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(f"错误: baseline 文件不存在: {baseline_path}", file=sys.stderr)
        return 2

    baseline = load_baseline(baseline_path)
    baseline["_path"] = str(baseline_path)

    # Validate baseline schema
    schema_errors = validate_baseline_schema(baseline)
    if schema_errors:
        print("baseline schema 校验失败:", file=sys.stderr)
        for e in schema_errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    # Run governance
    report = run_governance(
        baseline,
        project_root=PROJECT_ROOT,
        include_qmt_regression=args.include_qmt_regression,
        include_web_news_live=args.include_web_news_live,
    )

    # Output artifacts
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # latest.json
    latest_json = output_dir / "latest.json"
    latest_json.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # latest.md
    latest_md = output_dir / "latest.md"
    latest_md.write_text(_build_markdown(report), encoding="utf-8")

    # drift_report.md
    drift_md = output_dir / "drift_report.md"
    drift_md.write_text(generate_drift_report(report), encoding="utf-8")

    # failures.jsonl
    failures_path = output_dir / "failures.jsonl"
    failures = generate_failures_jsonl(report)
    with failures_path.open("w", encoding="utf-8") as f:
        for item in failures:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    # baseline_candidate.json
    if args.update_baseline:
        candidate = generate_baseline_candidate(report, baseline=baseline)
        candidate_path = output_dir / "baseline_candidate.json"
        candidate_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"baseline candidate: {candidate_path}")

    # Print summary
    print(f"\nRun ID: {report.run_id}")
    print(f"总体状态: {report.overall_status}")

    for comp in report.component_results:
        if comp.skipped:
            print(f"  {comp.component}: 跳过 ({comp.skip_reason})")
        elif not comp.artifact_loaded:
            print(f"  {comp.component}: artifact 不存在")
        else:
            status = "blocker" if comp.has_blocker else ("warning" if comp.has_warning else ("watch" if comp.has_watch else "ok"))
            print(f"  {comp.component}: {status} ({comp.pass_count} pass, {comp.fail_count} fail)")

    print(f"\n输出目录: {output_dir}")
    for f in ["latest.json", "latest.md", "drift_report.md", "failures.jsonl"]:
        print(f"  - {f}")

    # Exit code logic
    if report.has_blocker:
        return 1
    if args.fail_on_warning and report.has_warning:
        return 1
    if args.fail_on_watch and report.has_watch:
        return 1
    return 0


def _build_markdown(report: GovernanceReport) -> str:
    lines = ["# 研究质量治理报告", ""]
    lines.append(f"**Run ID**: {report.run_id}")
    lines.append(f"**时间**: {report.started_at}")
    lines.append(f"**总体状态**: {report.overall_status}")
    lines.append("")

    # Summary table
    lines.append("## 组件概览")
    lines.append("")
    lines.append("| 组件 | 状态 | pass | fail | 说明 |")
    lines.append("|---|---|---|---|---|")
    for comp in report.component_results:
        if comp.skipped:
            lines.append(f"| {comp.component} | 跳过 | - | - | {comp.skip_reason} |")
        elif not comp.artifact_loaded:
            lines.append(f"| {comp.component} | artifact 缺失 | - | - | |")
        else:
            status = "ok"
            if comp.has_blocker:
                status = "BLOCKER"
            elif comp.has_warning:
                status = "warning"
            elif comp.has_watch:
                status = "watch"
            lines.append(f"| {comp.component} | {status} | {comp.pass_count} | {comp.fail_count} | |")
    lines.append("")

    # Detail per component
    for comp in report.component_results:
        if comp.skipped:
            continue
        lines.append(f"## {comp.component}")
        lines.append("")

        if not comp.artifact_loaded:
            lines.append("**artifact 不存在**")
            lines.append("")
            continue

        lines.append("| 指标 | 状态 | severity | 实际值 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for m in comp.metrics:
            status_icon = {"pass": "pass", "fail": "FAIL", "missing": "N/A", "skipped": "-"}.get(m.status, "?")
            actual_str = str(m.actual) if m.actual is not None else "-"
            lines.append(
                f"| {m.metric_path} | {status_icon} | {m.severity} | "
                f"{actual_str} | {m.message} |"
            )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
