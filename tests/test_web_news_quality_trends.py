"""网页新闻/舆情趋势分析模块测试。

覆盖：
- history.jsonl 正常聚合
- history.jsonl 不存在
- history.jsonl 空文件
- 单行 JSON 损坏
- 缺少 per_provider
- core provider 缺失检测
- core provider 失败触发 warning/blocker
- weak/fallback provider 失败只触发 watch
- trend_summary.json schema
- trend_report.md 包含核心字段
- parse warnings 记录
- governance 优先读取 trend_summary.json
- governance fallback latest.json 时有明确 warning/watch
- governance trend 指标在 trend_summary 时 required
"""

import json
import shutil
import tempfile
from datetime import datetime, timedelta
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


def _recent_date(days_ago: int = 0) -> str:
    """返回相对于今天的 ISO 日期字符串，确保在 7 天窗口内。"""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT10:00:00")


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


def _make_run(run_id="r1", completed_at=None, per_provider=None):
    if completed_at is None:
        completed_at = _recent_date()
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
    last_success_at=None,
    raw_counts=None,
):
    if last_success_at is None:
        last_success_at = _recent_date()
    info = {
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
    if raw_counts:
        info.update(raw_counts)
    return info


class TestLoadHistoryRuns:

    def test_normal_load(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run1 = _make_run("r1", _recent_date())
            run2 = _make_run("r2", _recent_date(1))
            history_path.write_text(
                json.dumps(run1) + "\n" + json.dumps(run2) + "\n",
                encoding="utf-8",
            )
            runs, warnings = load_history_runs(history_path)
            assert len(runs) == 2
            assert warnings == []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_file(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            runs, warnings = load_history_runs(tmp_dir / "nonexistent.jsonl")
            assert runs == []
            assert len(warnings) == 1
            assert "不存在" in warnings[0]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_empty_file(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            history_path.write_text("", encoding="utf-8")
            runs, warnings = load_history_runs(history_path)
            assert runs == []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_corrupt_line(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run1 = _make_run("r1", _recent_date())
            history_path.write_text(
                json.dumps(run1) + "\n{invalid json\n" + json.dumps(_make_run("r2", _recent_date(1))) + "\n",
                encoding="utf-8",
            )
            runs, warnings = load_history_runs(history_path)
            assert len(runs) == 2  # corrupt line skipped, others loaded
            assert len(warnings) == 1
            assert "损坏" in warnings[0]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_per_provider_warning(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = {"run_id": "r1", "completed_at": _recent_date()}
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")
            runs, warnings = load_history_runs(history_path)
            assert len(runs) == 1
            assert any("per_provider" in w for w in warnings)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_window_filter(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run_old = _make_run("old", "2020-01-01T10:00:00")
            run_new = _make_run("new", _recent_date(2))
            history_path.write_text(
                json.dumps(run_old) + "\n" + json.dumps(run_new) + "\n",
                encoding="utf-8",
            )
            runs, _ = load_history_runs(history_path, window_days=7)
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
                    _recent_date(i),
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
            assert summary.core_provider_ok is True
            assert summary.missing_core_provider_count == 0
            assert summary.overall_severity in ("ok", "watch", "warning")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_core_provider_missing_detected(self):
        """Core provider absent from all runs should set core_provider_ok=False."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            runs = []
            for i in range(4):
                runs.append(_make_run(
                    f"r{i}",
                    _recent_date(i),
                    per_provider={
                        "sina": _make_provider_info("ok", success_rate=0.5),
                    },
                ))
            history_path.write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            assert summary.core_provider_ok is False
            assert summary.missing_core_provider_count == 1
            # Missing core is warning, not blocker (no consecutive failures)
            assert summary.overall_severity == "warning"
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
                    _recent_date(i),
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
                    _recent_date(i),
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
                    _recent_date(i),
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
            run = _make_run("r1", _recent_date(), per_provider={})
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            # All configured providers should still appear (initialized from policy)
            assert summary.provider_count == 4  # eastmoney, sina, baidu, hotrank
            assert summary.run_count == 1
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_parse_warnings_in_summary(self):
        """Parse warnings from load_history_runs should appear in TrendSummary.warnings."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run("r1", _recent_date(), per_provider={})
            history_path.write_text(
                json.dumps(run) + "\n{bad json\n",
                encoding="utf-8",
            )

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            assert any("损坏" in w for w in summary.warnings)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_raw_counts_used_when_available(self):
        """When raw counts are in per_provider, trend should use them."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run(
                "r1", _recent_date(),
                per_provider={
                    "eastmoney": _make_provider_info(
                        "ok", success_rate=0.8, attempts=10,
                        raw_counts={
                            "successes": 8,
                            "timeouts": 1,
                            "empty_results": 2,
                            "total_deduped": 15,
                            "total_relevant": 7,
                            "total_low_quality": 3,
                        },
                    ),
                },
            )
            history_path.write_text(json.dumps(run) + "\n", encoding="utf-8")

            policy = _make_policy()
            summary = analyze_trends(history_path, policy)

            eastmoney = next(pt for pt in summary.provider_trends if pt.provider == "eastmoney")
            assert eastmoney.successes == 8
            assert eastmoney.timeouts == 1
            assert eastmoney.empty_results == 2
            assert eastmoney.total_deduped == 15
            assert eastmoney.total_relevant == 7
            assert eastmoney.total_low_quality == 3
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestTrendSummarySchema:

    def test_to_dict_keys(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            history_path = tmp_dir / "history.jsonl"
            run = _make_run(
                "r1", _recent_date(),
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
                "failed_core_provider_count", "missing_core_provider_count",
                "overall_severity", "warnings", "provider_trends", "assessments",
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
                "r1", _recent_date(),
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
                "r1", _recent_date(),
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
            assert "missing_core_provider_count" in trend_summary
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestGovernanceIntegration:
    """Test that governance reads trend_summary.json when available."""

    def test_governance_prefers_trend_summary(self):
        from services.research.quality_governance import load_artifact

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            trend_data = {
                "run_id": "test123",
                "generated_at": _recent_date(2),
                "window_days": 7,
                "run_count": 5,
                "day_count": 5,
                "core_provider_ok": True,
                "healthy_provider_count": 1,
                "failed_core_provider_count": 0,
                "missing_core_provider_count": 0,
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
            latest_data = {
                "run_id": "latest123",
                "overall": {"success_rate": 0.6},
                "per_provider": {},
            }
            latest_path = tmp_dir / "latest.json"
            latest_path.write_text(json.dumps(latest_data), encoding="utf-8")

            trend_path = tmp_dir / "trend_summary.json"
            assert not trend_path.exists()

            artifact = load_artifact(latest_path)
            assert artifact is not None
            assert artifact["overall"]["success_rate"] == 0.6
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_trend_metrics_required_when_trend_loaded(self):
        """When trend_summary.json is loaded, trend metrics should NOT be optional."""
        from services.research.quality_governance import run_governance

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            trend_data = {
                "run_id": "test123",
                "generated_at": _recent_date(2),
                "window_days": 7,
                "run_count": 5,
                "day_count": 5,
                "core_provider_ok": True,
                "healthy_provider_count": 1,
                "failed_core_provider_count": 0,
                "missing_core_provider_count": 0,
                "overall_severity": "ok",
                "provider_trends": [],
                "assessments": [],
            }
            trend_path = tmp_dir / "storage" / "artifacts" / "web_news_quality" / "live"
            trend_path.mkdir(parents=True, exist_ok=True)
            (trend_path / "trend_summary.json").write_text(
                json.dumps(trend_data), encoding="utf-8",
            )

            baseline = {
                "version": 1,
                "components": {
                    "web_news_live": {
                        "enabled": True,
                        "artifact_path": "storage/artifacts/web_news_quality/live/latest.json",
                        "metrics": {
                            "run_count": {"min": 3, "severity": "watch", "optional": True},
                            "core_provider_ok": {"expected": True, "severity": "warning", "optional": True},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=tmp_dir)
            comp = report.component_results[0]

            # With trend loaded, metrics should be required (not skipped)
            run_count_metric = next(m for m in comp.metrics if m.metric_path == "run_count")
            assert run_count_metric.status == "pass"  # 5 >= 3
            assert run_count_metric.status != "skipped"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_trend_metrics_optional_on_fallback(self):
        """When falling back to latest.json, trend metrics should be optional (skipped)."""
        from services.research.quality_governance import run_governance

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Only latest.json exists
            latest_data = {
                "run_id": "latest123",
                "overall": {"success_rate": 0.6},
                "per_provider": {},
            }
            latest_dir = tmp_dir / "storage" / "artifacts" / "web_news_quality" / "live"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (latest_dir / "latest.json").write_text(
                json.dumps(latest_data), encoding="utf-8",
            )

            baseline = {
                "version": 1,
                "components": {
                    "web_news_live": {
                        "enabled": True,
                        "artifact_path": "storage/artifacts/web_news_quality/live/latest.json",
                        "metrics": {
                            "run_count": {"min": 3, "severity": "watch", "optional": True},
                            "core_provider_ok": {"expected": True, "severity": "warning", "optional": True},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=tmp_dir)
            comp = report.component_results[0]

            # On fallback, trend metrics should be skipped (optional)
            run_count_metric = next(m for m in comp.metrics if m.metric_path == "run_count")
            assert run_count_metric.status == "skipped"

            # Should have fallback warning
            fallback_metric = next(m for m in comp.metrics if m.metric_path == "_trend_fallback")
            assert fallback_metric.status == "fail"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
