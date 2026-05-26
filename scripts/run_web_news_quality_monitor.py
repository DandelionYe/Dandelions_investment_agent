"""网页新闻/舆情长期质量监控脚本。

对核心标的池运行真实 WebNewsProvider 抓取，按 provider/source 维度评估稳定性，
输出 JSON/Markdown artifact 和 provider health 报告。

Usage:
    python scripts/run_web_news_quality_monitor.py
    python scripts/run_web_news_quality_monitor.py --offline-fixture tests/fixtures/web_news_quality_samples.json
    python scripts/run_web_news_quality_monitor.py --sources eastmoney,sina --limit 5
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.data.news_quality_monitor import (  # noqa: E402
    DEFAULT_SOURCES,
    MonitorThresholds,
    NewsQualityMonitor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="网页新闻/舆情长期质量监控",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=str(PROJECT_ROOT / "configs" / "web_news_quality_targets.json"),
        help="标的池配置文件路径",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=",".join(DEFAULT_SOURCES),
        help="逗号分隔的来源列表 (default: eastmoney,sina,xinhuanet,hotrank,baidu)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="新闻回看天数 (default: 14)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="每个来源最大条目数 (default: 10)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=8,
        help="单次请求超时秒数 (default: 8)",
    )
    parser.add_argument(
        "--max-seconds",
        type=int,
        default=12,
        help="单个 provider 最大总秒数 (default: 12)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality" / "live"),
        help="输出目录 (default: storage/artifacts/web_news_quality/live)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="重复运行次数 (default: 1)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="重复运行间隔秒数 (default: 60)",
    )
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        default=False,
        help="阈值不达标时返回非 0 exit code",
    )
    parser.add_argument(
        "--offline-fixture",
        type=str,
        default=None,
        help="离线 fixture 文件路径，不发真实网络请求",
    )
    return parser.parse_args()


def load_targets(targets_path: str) -> list[dict]:
    path = Path(targets_path)
    if not path.exists():
        print(f"ERROR: 标的池配置不存在: {path}")
        sys.exit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("targets", [])


def check_thresholds(report: dict, thresholds: MonitorThresholds) -> bool:
    """Check if report meets thresholds. Returns True if all pass."""
    overall = report.get("overall", {})

    failures = []

    if overall.get("success_rate", 0) < thresholds.min_success_rate:
        failures.append(
            f"success_rate {overall['success_rate']:.2%} < {thresholds.min_success_rate:.2%}"
        )

    if overall.get("timeout_rate", 0) > thresholds.max_timeout_rate:
        failures.append(
            f"timeout_rate {overall['timeout_rate']:.2%} > {thresholds.max_timeout_rate:.2%}"
        )

    if overall.get("empty_rate", 0) > thresholds.max_empty_rate:
        failures.append(
            f"empty_rate {overall['empty_rate']:.2%} > {thresholds.max_empty_rate:.2%}"
        )

    if overall.get("relevance_rate", 0) < thresholds.min_relevance_rate:
        failures.append(
            f"relevance_rate {overall['relevance_rate']:.2%} < {thresholds.min_relevance_rate:.2%}"
        )

    if overall.get("low_quality_rate", 0) > thresholds.max_low_quality_rate:
        failures.append(
            f"low_quality_rate {overall['low_quality_rate']:.2%} > {thresholds.max_low_quality_rate:.2%}"
        )

    if overall.get("avg_latency_seconds", 0) > thresholds.max_avg_latency_seconds:
        failures.append(
            f"avg_latency_seconds {overall['avg_latency_seconds']:.1f}s > {thresholds.max_avg_latency_seconds:.1f}s"
        )

    if failures:
        print("\n阈值不达标:")
        for f in failures:
            print(f"  - {f}")
        return False

    return True


def main() -> int:
    args = parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    output_dir = Path(args.output_dir)
    thresholds = MonitorThresholds()

    is_offline = args.offline_fixture is not None

    if is_offline:
        # Offline fixture mode
        fixture_path = Path(args.offline_fixture)
        if not fixture_path.exists():
            print(f"ERROR: fixture 文件不存在: {fixture_path}")
            return 1

        print(f"离线模式: {fixture_path}")
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=thresholds,
            output_dir=output_dir,
        )
        report = monitor.evaluate_fixture(fixture_path)

        # Save artifacts
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "latest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (output_dir / "latest.md").write_text(
            monitor._build_markdown_report(report),
            encoding="utf-8",
        )
        history_path = output_dir / "history.jsonl"
        history_entry = {
            "run_id": report["run_id"],
            "started_at": report["started_at"],
            "completed_at": report["completed_at"],
            "targets_count": report["targets_count"],
            "sources": report["sources"],
            "overall": report["overall"],
            "per_provider": report["per_provider"],
        }
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_entry, ensure_ascii=False, default=str) + "\n")

        health_path = output_dir / "provider_health.json"
        health_data = {
            "updated_at": report["completed_at"],
            "providers": report["per_provider"],
        }
        health_path.write_text(
            json.dumps(health_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        review_path = output_dir / "manual_review_candidates.jsonl"
        candidates = monitor._collect_review_candidates(report["evaluations"])
        with review_path.open("a", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

        print(f"\nRun ID: {report['run_id']}")
        print(f"总体成功率: {report['overall']['success_rate']:.1%}")
        print(f"输出目录: {output_dir}")
        for f in ["latest.json", "latest.md", "history.jsonl", "provider_health.json", "manual_review_candidates.jsonl"]:
            print(f"  - {f}")

        if args.fail_on_threshold:
            if not check_thresholds(report, thresholds):
                return 1
        return 0

    # Real network mode
    targets = load_targets(args.targets)
    if not targets:
        print("ERROR: 标的池为空")
        return 1

    print(f"标的数量: {len(targets)}")
    print(f"监控来源: {', '.join(sources)}")
    print(f"输出目录: {output_dir}")

    import time

    all_passed = True
    for run_idx in range(args.repeat):
        if run_idx > 0:
            print(f"\n等待 {args.interval_seconds}s 后进行第 {run_idx + 1} 次运行...")
            time.sleep(args.interval_seconds)

        print(f"\n--- 第 {run_idx + 1}/{args.repeat} 次运行 ---")
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=sources,
            thresholds=thresholds,
            lookback_days=args.lookback_days,
            limit=args.limit,
            timeout_seconds=args.timeout_seconds,
            max_seconds=args.max_seconds,
            output_dir=output_dir,
        )
        report = monitor.run_and_save()

        print(f"\nRun ID: {report['run_id']}")
        print(f"总体成功率: {report['overall']['success_rate']:.1%}")
        print(f"超时率: {report['overall']['timeout_rate']:.1%}")
        print(f"空结果率: {report['overall']['empty_rate']:.1%}")
        print(f"相关性率: {report['overall']['relevance_rate']:.1%}")
        print(f"平均延迟: {report['overall']['avg_latency_seconds']:.2f}s")

        print("\nProvider Health:")
        for source, info in report["per_provider"].items():
            status = info["status"]
            print(
                f"  {source}: {status} | "
                f"成功率={info['success_rate']:.1%} | "
                f"延迟={info['avg_latency_seconds']:.2f}s | "
                f"相关率={info['avg_relevance_rate']:.1%}"
            )

        if args.fail_on_threshold:
            if not check_thresholds(report, thresholds):
                all_passed = False

    print(f"\n输出目录: {output_dir}")
    print("Artifacts:")
    for f in ["latest.json", "latest.md", "history.jsonl", "provider_health.json", "manual_review_candidates.jsonl"]:
        print(f"  - {f}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
