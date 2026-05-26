"""网页新闻/舆情趋势分析脚本。

从 history.jsonl 读取多次运行摘要，按 provider 分层聚合，
判断趋势健康状态，输出 trend_summary / trend_report / provider_trends。

Usage:
    python scripts/analyze_web_news_quality_trends.py
    python scripts/analyze_web_news_quality_trends.py --window-days 14
    python scripts/analyze_web_news_quality_trends.py --fail-on-warning
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.data.news_quality_trends import (  # noqa: E402
    TrendPolicy,
    analyze_trends,
    save_trend_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="网页新闻/舆情趋势分析",
    )
    parser.add_argument(
        "--history-path",
        type=str,
        default=str(PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality" / "live" / "history.jsonl"),
        help="history.jsonl 路径",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality" / "live"),
        help="输出目录",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="分析窗口天数 (default: 7)",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=3,
        help="最少运行次数 (default: 3)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(PROJECT_ROOT / "configs" / "web_news_quality_policy.json"),
        help="治理策略配置路径",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        default=False,
        help="warning 也返回非 0",
    )
    parser.add_argument(
        "--fail-on-watch",
        action="store_true",
        default=False,
        help="watch 也返回非 0",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Load policy — config is required (exit 2 if missing/invalid)
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}", file=sys.stderr)
        return 2
    try:
        policy_data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(policy_data, dict):
            raise ValueError("配置文件必须是 JSON object")
        policy = TrendPolicy.from_dict(policy_data)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        print(f"错误: 配置文件解析失败: {config_path} — {exc}", file=sys.stderr)
        return 2

    # Override min_runs if specified
    if args.min_runs:
        policy.min_runs_for_trend = args.min_runs

    # Run analysis
    history_path = Path(args.history_path)
    output_dir = Path(args.output_dir)

    summary = analyze_trends(
        history_path=history_path,
        policy=policy,
        window_days=args.window_days,
    )

    # Save artifacts
    save_trend_artifacts(summary, output_dir)

    # Print summary
    print(f"Run ID: {summary.run_id}")
    print(f"窗口: {summary.window_days} 天")
    print(f"运行次数: {summary.run_count}")
    print(f"覆盖天数: {summary.day_count}")
    print(f"Provider 总数: {summary.provider_count}")
    print(f"健康: {summary.healthy_provider_count}")
    print(f"降级: {summary.degraded_provider_count}")
    print(f"失败: {summary.failed_provider_count}")
    print(f"Core Provider 正常: {'Yes' if summary.core_provider_ok else 'No'}")
    print(f"总体状态: {summary.overall_severity}")

    if summary.warnings:
        print("\n警告:")
        for w in summary.warnings[:10]:
            print(f"  - {w}")

    print(f"\n输出目录: {output_dir}")
    for f in ["trend_summary.json", "trend_report.md", "provider_trends.json"]:
        print(f"  - {f}")

    # Exit code logic
    if summary.overall_severity == "blocker":
        return 1
    if args.fail_on_warning and summary.overall_severity == "warning":
        return 1
    if args.fail_on_watch and summary.overall_severity in ("warning", "watch"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
