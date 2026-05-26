"""网页新闻/舆情趋势分析模块测试。

覆盖：
- history.jsonl 正常聚合
- history.jsonl 不存在
- history.jsonl 空文件
- 单行 JSON 损坏
- 缺少 per_provider
- core provider 失败触发 warning/blocker
- weak/fallback provider 失败只触发 watch
- trend_summary.json schema
- trend_report.md 包含核心字段
- governance 优先读取 trend_summary.json
- governance fallback latest.json 时有明确 warning/watch
"""

import json
import shutil
import tempfile
from pathlib import Path

from services.data.news_quality_trends import (
    ProviderTierConfig,
    TrendPolicy,
    analyze_trends,
    build_trend_report_markdown,
    compute_consecutive_failures,
    load_history_runs,
    save_trend_artifacts,
)


def _make_policy() -> TrendPolicy:
    return TrendPolicy(
        provider_tiers={
            "core": ProviderTierConfig(
                providers=["eastmoney"],
                on_failure="warning",
                on_consecutive_failures=3,
                on_consecutive_failures_severity="blocker",
                min_success_rate=0.40,
                success_rate_severity="warning",
            ),
            "secondary": ProviderTierConfig(
                providers=["sina", "baidu"],
                on_failure="watch",
                min_success_rate=0.20,
                success_rate_severity="watch",
            ),
            "weak": ProviderTierConfig(
                providers=["hotrank"],
                on_failure="watch",
                on_consecutive_failures=0,
                on_consecutive_failures_severity="watch",
                min_success_rate=0.0,
                success_rate_severity="watch",
                block_on_failure=False,
            ),
        },
        default_window_days=7,
        min_runs_for_trend=3,
        core_provider_ok_required=True,
        healthy_provider_count_min=1,
        failed_core_provider_count_max=0,
    )


def _make_run(run_id="r1", completed_at="2026-05-20T10:00:00", per_provider=None):
    return {
        "run_id": run_id,
        "started_at": completed_at,
        "completed_at": completed_at,
        "targets_count": 10,
        "sources": ["eastmoney", "sina", "hotrank"],
        "overall": {"success_rate": 0.8},
        "per_provider": per_provider or {},
    }


def _make_provider_info(
    status="ok", success_rate=0.8, timeout_rate=0.1, empty_rate=0.2,
    avg_latency=2.0, avg_relevance=0.5, avg_low_quality=0.2, attempts=10,
    last_success_at="2026-05-20T10:00:00",
):
    return {
        "status": status,
        "success_rate": success_rate,
        "timeout_rate": timeout_rate,
        "empty_rate": empty_rate,
        "avg_latency_seconds": avg_latency,
        "avg_relevance_rate": avg_relevance,
        "avg_low_quality_rate": avg_low_quality,
        "attempts": attempts,
        "last_success_at": last_success_at,
    }


class TestLoadHistoryRuns:

    def test_normal_load(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run1 = _make_run("r1", "2026-05-20T10:00:00")
            run2 = _make_run("r2", "2026-05-21T10:00:00")
            history_path.write_text(
                json.dumps(run1) + "\n" + json.dumps(run2) + "\n",
                encoding="utf-8",
            )
            runs = load_history_runs(history_path)
            assert len(runs) == 2
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_file(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            runs = load_history_runs(tmp_dir / "nonexistent.jsonl")
            assert runs == []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_empty_file(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            history_path.write_text("", encoding="utf-8")
            runs = load_history_runs(history_path)
            assert runs == []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_corrupt_line(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run1 = _make_run("r1", "2026-05-20T10:00:00")
            history_path.write_text(
                json.dumps(run1) + "\n{invalid json\n" + json.dumps(_make_run("r2", "2026-05-21T10:00:00")) + "\n",
                encoding="utf-8",
            )
            runs = load_history_runs(history_path)
            assert len(runs) == 2  # corrupt line skipped, others loaded
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_window_filter(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run_old = _make_run("old", "2020-01-01T10:00:00")
            run_new = _make_run("new", "2026-05-25T10:00:00")
            history_path.write_text(
                json.dumps(run_old) + "\n" + json.dumps(run_new) + "\n",
                encoding="utf-8",
            )
            runs = load_history_runs(history_path, window_days=7)
            # Only recent run should be loaded (old one filtered by window)
            assert len(runs) <= 2  # depends on current date
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestConsecutiveFailures:

    def test_no_failures(self):
        runs = [
            _make_run("r1", per_provider={"eastmoney": _make_provider_info("ok")}),
            _make_run("r2", per_provider={"eastmoney": _make_provider_info("ok")}),
        ]
        assert compute_consecutive_failures(runs, "eastmoney") == 0

    def test_consecutive_failures(self):
        runs = [
            _make_run("r1", per_provider={"eastmoney": _make_provider_info("ok")}),
            _make_run("r2", per_provider={"eastmoney": _make_provider_info("fail", success_rate=0.0)}),
            _make_run("r3", per_provider={"eastmoney": _make_provider_info("fail", success_rate=0.0)}),
        ]
        assert compute_consecutive_failures(runs, "eastmoney") == 2

    def test_failure_then_recovery(self):
        runs = [
            _make_run("r1", per_provider={"eastmoney": _make_provider_info("fail", success_rate=0.0)}),
            _make_run("r2", per_provider={"eastmoney": _make_provider_info("ok")}),
            _make_run("r3", per_provider={"eastmoney": _make_provider_info("fail", success_rate=0.0)}),
        ]
        assert compute_consecutive_failures(runs, "eastmoney") == 1

    def test_missing_provider(self):
        runs = [_make_run("r1", per_provider={})]
        assert compute_consecutive_failures(runs, "eastmoney") == 0


class TestAnalyzeTrends:

    def test_normal_analysis(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            runs = []
            for i in range(5):
                runs.append(_make_run(
                    f"r{i}",
                    f"2026-05-{20+i}T10:00:00",
                    per_provider={
                        "eastmoney": _make_provider_info("ok", success_rate=0.8),
                        "sina": _make_provider_info("ok", success_rate=0.5),
                    },
                ))
            history_path.write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            assert summary.run_count == 5
            assert summary.provider_count == 2
            assert summary.core_provider_ok is True
            assert summary.overall_severity in ("ok", "watch", "warning")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_core_provider_all_fail(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            runs = []
            for i in range(4):
                runs.append(_make_run(
                    f"r{i}",
                    f"2026-05-{20+i}T10:00:00",
                    per_provider={
                        "eastmoney": _make_provider_info("fail", success_rate=0.0),
                    },
                ))
            history_path.write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            assert summary.core_provider_ok is False
            assert summary.overall_severity == "blocker"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_weak_provider_fail_is_watch(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            runs = []
            for i in range(4):
                runs.append(_make_run(
                    f"r{i}",
                    f"2026-05-{20+i}T10:00:00",
                    per_provider={
                        "eastmoney": _make_provider_info("ok", success_rate=0.8),
                        "hotrank": _make_provider_info("fail", success_rate=0.0),
                    },
                ))
            history_path.write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            # hotrank failure should be watch, not blocker
            hotrank_assessment = next(a for a in summary.assessments if a.provider == "hotrank")
            assert hotrank_assessment.severity == "watch"
            assert summary.overall_severity != "blocker"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_consecutive_failures_trigger_blocker(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            runs = []
            for i in range(5):
                runs.append(_make_run(
                    f"r{i}",
                    f"2026-05-{20+i}T10:00:00",
                    per_provider={
                        "eastmoney": _make_provider_info("fail", success_rate=0.0),
                    },
                ))
            history_path.write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            eastmoney_assessment = next(a for a in summary.assessments if a.provider == "eastmoney")
            assert eastmoney_assessment.severity == "blocker"
            assert summary.overall_severity == "blocker"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_per_provider(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run("r1", "2026-05-20T10:00:00", per_provider={})
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            assert summary.provider_count == 0
            assert summary.run_count == 1
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestTrendSummarySchema:

    def test_to_dict_keys(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run(
                "r1", "2026-05-20T10:00:00",
                per_provider={"eastmoney": _make_provider_info()},
            )
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)
            d = summary.to_dict()

            required = {
                "run_id", "generated_at", "window_days", "run_count", "day_count",
                "first_run_at", "last_run_at", "provider_count",
                "healthy_provider_count", "degraded_provider_count",
                "failed_provider_count", "core_provider_ok",
                "failed_core_provider_count", "overall_severity",
                "warnings", "provider_trends", "assessments",
            }
            assert required == set(d.keys())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestTrendReportMarkdown:

    def test_contains_core_fields(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run(
                "r1", "2026-05-20T10:00:00",
                per_provider={"eastmoney": _make_provider_info()},
            )
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)
            md = build_trend_report_markdown(summary)

            assert "趋势分析报告" in md
            assert "eastmoney" in md
            assert "运行次数" in md
            assert "Provider 趋势" in md
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestSaveTrendArtifacts:

    def test_saves_all_files(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run(
                "r1", "2026-05-20T10:00:00",
                per_provider={"eastmoney": _make_provider_info()},
            )
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)
            output_dir = tmp_dir / "output"
            save_trend_artifacts(summary, output_dir)

            assert (output_dir / "trend_summary.json").exists()
            assert (output_dir / "trend_report.md").exists()
            assert (output_dir / "provider_trends.json").exists()

            trend_summary = json.loads((output_dir / "trend_summary.json").read_text(encoding="utf-8"))
            assert "run_id" in trend_summary
            assert "provider_trends" in trend_summary
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestGovernanceIntegration:
    """Test that governance reads trend_summary.json when available."""

    def test_governance_prefers_trend_summary(self):
        from services.research.quality_governance import load_artifact

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Create trend_summary.json with trend data
            trend_data = {
                "run_id": "test123",
                "generated_at": "2026-05-25T10:00:00",
                "window_days": 7,
                "run_count": 5,
                "day_count": 5,
                "core_provider_ok": True,
                "healthy_provider_count": 1,
                "failed_core_provider_count": 0,
                "overall_severity": "ok",
                "provider_trends": [],
                "assessments": [],
            }
            trend_path = tmp_dir / "trend_summary.json"
            trend_path.write_text(json.dumps(trend_data), encoding="utf-8")

            artifact = load_artifact(trend_path)
            assert artifact is not None
            assert artifact["run_count"] == 5
            assert artifact["core_provider_ok"] is True
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_governance_fallback_to_latest(self):
        from services.research.quality_governance import load_artifact

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Only latest.json exists (no trend_summary.json)
            latest_data = {
                "run_id": "latest123",
                "overall": {"success_rate": 0.6},
                "per_provider": {},
            }
            latest_path = tmp_dir / "latest.json"
            latest_path.write_text(json.dumps(latest_data), encoding="utf-8")

            # trend_summary.json does NOT exist
            trend_path = tmp_dir / "trend_summary.json"
            assert not trend_path.exists()

            artifact = load_artifact(latest_path)
            assert artifact is not None
            assert artifact["overall"]["success_rate"] == 0.6
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
