"""P2 Phase 6: 研究质量治理模块测试。

覆盖：
- baseline schema 校验
- metric path 读取
- min/max/expected/tolerance 比较
- severity 分级
- missing artifact 行为
- blocker exit 逻辑
- warning/watch 默认不阻断
- baseline_candidate 生成
- failures.jsonl schema
- case registry schema
"""

import json
import shutil
import tempfile
from pathlib import Path

from services.research.quality_governance import (  # noqa: I001
    ComponentResult,
    GovernanceReport,
    MetricResult,
    compare_metric,
    extract_metric,
    generate_baseline_candidate,
    generate_case_entry,
    generate_drift_report,
    generate_failures_jsonl,
    load_artifact,
    run_governance,
    validate_baseline_schema,
    validate_case_registry,
)

# ── Baseline Schema 校验 ────────────────────────────────────────


class TestBaselineSchema:

    def test_valid_baseline(self):
        data = {
            "version": 1,
            "components": {
                "test_comp": {
                    "enabled": True,
                    "metrics": {
                        "some_metric": {"min": 0.5, "severity": "blocker"},
                    },
                },
            },
        }
        errors = validate_baseline_schema(data)
        assert errors == []

    def test_missing_version(self):
        data = {"components": {"test": {"enabled": True, "metrics": {"m": {"min": 1, "severity": "warning"}}}}}
        errors = validate_baseline_schema(data)
        assert any("version" in e for e in errors)

    def test_missing_components(self):
        data = {"version": 1}
        errors = validate_baseline_schema(data)
        assert any("components" in e for e in errors)

    def test_missing_severity(self):
        data = {
            "version": 1,
            "components": {
                "test": {"enabled": True, "metrics": {"m": {"min": 1}}},
            },
        }
        errors = validate_baseline_schema(data)
        assert any("severity" in e for e in errors)

    def test_invalid_severity(self):
        data = {
            "version": 1,
            "components": {
                "test": {"enabled": True, "metrics": {"m": {"min": 1, "severity": "critical"}}},
            },
        }
        errors = validate_baseline_schema(data)
        assert any("severity" in e for e in errors)

    def test_missing_range_rule(self):
        data = {
            "version": 1,
            "components": {
                "test": {"enabled": True, "metrics": {"m": {"severity": "warning"}}},
            },
        }
        errors = validate_baseline_schema(data)
        assert any("min/max/expected" in e for e in errors)


# ── Metric Path 读取 ────────────────────────────────────────────


class TestExtractMetric:

    def test_simple_path(self):
        artifact = {"total": 100, "pass_rate": 1.0}
        assert extract_metric(artifact, "total") == 100
        assert extract_metric(artifact, "pass_rate") == 1.0

    def test_nested_path(self):
        artifact = {"data_gap_summary": {"data_complete_coverage": 0.71}}
        assert extract_metric(artifact, "data_gap_summary.data_complete_coverage") == 0.71

    def test_missing_path(self):
        artifact = {"total": 100}
        assert extract_metric(artifact, "nonexistent") is None

    def test_deeply_nested_missing(self):
        artifact = {"a": {"b": 1}}
        assert extract_metric(artifact, "a.b.c") is None


# ── 指标比较 ─────────────────────────────────────────────────────


class TestCompareMetric:

    def test_min_pass(self):
        result = compare_metric(0.8, {"min": 0.5, "severity": "blocker"}, "rate", "comp")
        assert result.status == "pass"

    def test_min_fail(self):
        result = compare_metric(0.3, {"min": 0.5, "severity": "blocker"}, "rate", "comp")
        assert result.status == "fail"
        assert result.severity == "blocker"

    def test_max_pass(self):
        result = compare_metric(0.0, {"max": 0.1, "severity": "warning"}, "rate", "comp")
        assert result.status == "pass"

    def test_max_fail(self):
        result = compare_metric(0.5, {"max": 0.1, "severity": "warning"}, "rate", "comp")
        assert result.status == "fail"
        assert result.severity == "warning"

    def test_expected_exact(self):
        result = compare_metric(100, {"expected": 100, "tolerance": 0, "severity": "blocker"}, "count", "comp")
        assert result.status == "pass"

    def test_expected_fail(self):
        result = compare_metric(99, {"expected": 100, "tolerance": 0, "severity": "blocker"}, "count", "comp")
        assert result.status == "fail"

    def test_expected_with_tolerance(self):
        result = compare_metric(99, {"expected": 100, "tolerance": 1, "severity": "warning"}, "count", "comp")
        assert result.status == "pass"

    def test_missing_actual(self):
        result = compare_metric(None, {"min": 0.5, "severity": "watch"}, "rate", "comp")
        assert result.status == "missing"
        assert result.severity == "watch"

    def test_non_numeric_actual(self):
        result = compare_metric("abc", {"min": 0.5, "severity": "blocker"}, "rate", "comp")
        assert result.status == "fail"


# ── Severity 分级 ────────────────────────────────────────────────


class TestSeverityGrading:

    def test_blocker_status(self):
        comp = ComponentResult(
            component="test", enabled=True,
            metrics=[
                MetricResult(path="x", component="test", metric_path="x",
                             severity="blocker", status="fail"),
            ],
        )
        assert comp.has_blocker is True
        assert comp.has_warning is False

    def test_warning_status(self):
        comp = ComponentResult(
            component="test", enabled=True,
            metrics=[
                MetricResult(path="x", component="test", metric_path="x",
                             severity="warning", status="fail"),
            ],
        )
        assert comp.has_blocker is False
        assert comp.has_warning is True

    def test_watch_status(self):
        comp = ComponentResult(
            component="test", enabled=True,
            metrics=[
                MetricResult(path="x", component="test", metric_path="x",
                             severity="watch", status="fail"),
            ],
        )
        assert comp.has_blocker is False
        assert comp.has_watch is True

    def test_overall_status_blocker(self):
        report = GovernanceReport(
            run_id="test", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="a", enabled=True, metrics=[
                    MetricResult(path="a.x", component="a", metric_path="x",
                                 severity="warning", status="fail"),
                ]),
                ComponentResult(component="b", enabled=True, metrics=[
                    MetricResult(path="b.y", component="b", metric_path="y",
                                 severity="blocker", status="fail"),
                ]),
            ],
        )
        assert report.overall_status == "blocker"
        assert report.has_blocker is True


# ── Missing Artifact ─────────────────────────────────────────────


class TestMissingArtifact:

    def test_missing_artifact_records_missing(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            baseline = {
                "version": 1,
                "components": {
                    "test_comp": {
                        "enabled": True,
                        "artifact_path": "nonexistent.json",
                        "metrics": {
                            "some_metric": {"min": 0.5, "severity": "blocker"},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=tmp_dir)
            comp = report.component_results[0]
            assert comp.artifact_loaded is False
            assert comp.metrics[0].status == "missing"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_blocker_artifact_triggers_blocker(self):
        """缺失 blocker 级 artifact 必须触发 overall_status=blocker。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            baseline = {
                "version": 1,
                "components": {
                    "critical_comp": {
                        "enabled": True,
                        "artifact_path": "nonexistent.json",
                        "metrics": {
                            "rate": {"min": 0.5, "severity": "blocker"},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=tmp_dir)
            assert report.overall_status == "blocker"
            assert report.has_blocker is True
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_blocker_metric_path_triggers_blocker(self):
        """缺失 blocker 级 metric path 必须触发 overall_status=blocker。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            artifact = {"total": 100}  # missing "rate"
            artifact_path = tmp_dir / "test.json"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

            baseline = {
                "version": 1,
                "components": {
                    "test_comp": {
                        "enabled": True,
                        "artifact_path": str(artifact_path),
                        "metrics": {
                            "rate": {"min": 0.5, "severity": "blocker"},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=Path("."))
            assert report.overall_status == "blocker"
            assert report.has_blocker is True
            comp = report.component_results[0]
            assert comp.metrics[0].status == "missing"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_metric_in_failures_jsonl(self):
        """缺失指标也应出现在 failures.jsonl 输出中。"""
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.x", component="comp",
                                 metric_path="x", severity="blocker",
                                 status="missing", message="artifact missing"),
                    MetricResult(path="comp.y", component="comp",
                                 metric_path="y", severity="warning",
                                 status="fail", actual=0.3),
                ]),
            ],
        )
        failures = generate_failures_jsonl(report)
        assert len(failures) == 2
        statuses = {f["status"] for f in failures}
        assert "missing" in statuses
        assert "fail" in statuses

    def test_disabled_component_skipped(self):
        baseline = {
            "version": 1,
            "components": {
                "test_comp": {
                    "enabled": False,
                    "opt_in_reason": "needs network",
                    "metrics": {},
                },
            },
        }
        report = run_governance(baseline)
        comp = report.component_results[0]
        assert comp.skipped is True
        assert comp.skip_reason == "needs network"


# ── Blocker Exit 逻辑 ────────────────────────────────────────────


class TestExitLogic:

    def test_blocker_returns_1(self):
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="a", enabled=True, metrics=[
                    MetricResult(path="a.x", component="a", metric_path="x",
                                 severity="blocker", status="fail"),
                ]),
            ],
        )
        assert report.has_blocker is True
        # In the script: if has_blocker → return 1

    def test_warning_only_returns_0(self):
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="a", enabled=True, metrics=[
                    MetricResult(path="a.x", component="a", metric_path="x",
                                 severity="warning", status="fail"),
                ]),
            ],
        )
        assert report.has_blocker is False
        assert report.has_warning is True

    def test_watch_only_returns_0(self):
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="a", enabled=True, metrics=[
                    MetricResult(path="a.x", component="a", metric_path="x",
                                 severity="watch", status="fail"),
                ]),
            ],
        )
        assert report.has_blocker is False
        assert report.has_watch is True


# ── Baseline Candidate 生成 ──────────────────────────────────────


class TestBaselineCandidate:

    def test_generate_from_report(self):
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp_a", enabled=True, metrics=[
                    MetricResult(path="comp_a.rate", component="comp_a",
                                 metric_path="rate", severity="blocker",
                                 status="pass", actual=0.95),
                    MetricResult(path="comp_a.count", component="comp_a",
                                 metric_path="count", severity="warning",
                                 status="pass", actual=100),
                ]),
            ],
        )
        candidate = generate_baseline_candidate(report)
        assert "comp_a" in candidate["components"]
        assert candidate["components"]["comp_a"]["metrics"]["rate"]["min"] == 0.95
        assert candidate["components"]["comp_a"]["metrics"]["count"]["min"] == 100


# ── Failures JSONL Schema ────────────────────────────────────────


class TestFailuresJsonl:

    def test_schema(self):
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.x", component="comp",
                                 metric_path="x", severity="blocker",
                                 status="fail", expected=">=0.5",
                                 actual=0.3, message="too low"),
                    MetricResult(path="comp.y", component="comp",
                                 metric_path="y", severity="warning",
                                 status="pass", actual=0.8),
                ]),
            ],
        )
        failures = generate_failures_jsonl(report)
        assert len(failures) == 1
        f = failures[0]
        required = {"path", "component", "metric_path", "severity", "status", "expected", "actual", "message"}
        assert required == set(f.keys())
        assert f["status"] == "fail"


# ── Case Registry Schema ─────────────────────────────────────────


class TestCaseRegistry:

    def test_validate_empty_registry(self):
        data = {"version": 1, "cases": []}
        errors = validate_case_registry(data)
        assert errors == []

    def test_validate_valid_case(self):
        data = {
            "version": 1,
            "cases": [{
                "case_id": "case-123",
                "component": "backtest",
                "failure_type": "fail",
                "severity": "blocker",
                "status": "proposed",
                "created_at": "2026-05-26T10:00:00",
            }],
        }
        errors = validate_case_registry(data)
        assert errors == []

    def test_validate_missing_fields(self):
        data = {"version": 1, "cases": [{"case_id": "x"}]}
        errors = validate_case_registry(data)
        assert len(errors) > 0

    def test_validate_invalid_status(self):
        data = {
            "version": 1,
            "cases": [{
                "case_id": "x", "component": "c", "failure_type": "f",
                "severity": "s", "status": "invalid", "created_at": "t",
            }],
        }
        errors = validate_case_registry(data)
        assert any("status" in e for e in errors)

    def test_generate_case_entry(self):
        failure = MetricResult(
            path="comp.metric", component="comp", metric_path="metric",
            severity="blocker", status="fail", message="test failure",
        )
        entry = generate_case_entry(failure, source_artifact="test.json")
        assert entry["status"] == "proposed"
        assert entry["component"] == "comp"
        assert entry["severity"] == "blocker"
        assert "case_id" in entry
        assert "created_at" in entry


# ── Drift Report ─────────────────────────────────────────────────


class TestDriftReport:

    def test_generates_markdown(self):
        report = GovernanceReport(
            run_id="test123", started_at="2026-05-26T10:00:00",
            completed_at="2026-05-26T10:01:00", baseline_path="test.json",
            component_results=[
                ComponentResult(component="comp_a", enabled=True, metrics=[
                    MetricResult(path="comp_a.rate", component="comp_a",
                                 metric_path="rate", severity="blocker",
                                 status="pass", actual=0.95),
                ]),
                ComponentResult(component="comp_b", enabled=False,
                                skipped=True, skip_reason="needs network"),
            ],
        )
        md = generate_drift_report(report)
        assert "Drift 报告" in md
        assert "test123" in md
        assert "comp_a" in md
        assert "comp_b" in md
        assert "跳过" in md


# ── Artifact 加载 ────────────────────────────────────────────────


class TestLoadArtifact:

    def test_load_existing(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            p = tmp_dir / "test.json"
            p.write_text('{"key": "value"}', encoding="utf-8")
            result = load_artifact(p)
            assert result == {"key": "value"}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_load_missing(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            result = load_artifact(tmp_dir / "nonexistent.json")
            assert result is None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_load_invalid_json(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            p = tmp_dir / "bad.json"
            p.write_text("not json", encoding="utf-8")
            result = load_artifact(p)
            assert result is None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Governance 运行集成 ──────────────────────────────────────────


class TestGovernanceRun:

    def test_with_valid_artifact(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            artifact = {"total": 100, "pass_rate": 1.0}
            artifact_path = tmp_dir / "backtest.json"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

            baseline = {
                "version": 1,
                "components": {
                    "backtest": {
                        "enabled": True,
                        "artifact_path": str(artifact_path),
                        "metrics": {
                            "total": {"expected": 100, "tolerance": 0, "severity": "blocker"},
                            "pass_rate": {"min": 1.0, "severity": "blocker"},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=Path("."))
            assert report.overall_status == "ok"
            assert len(report.component_results) == 1
            assert report.component_results[0].pass_count == 2
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_with_failing_metric(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            artifact = {"total": 50, "pass_rate": 0.8}
            artifact_path = tmp_dir / "backtest.json"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

            baseline = {
                "version": 1,
                "components": {
                    "backtest": {
                        "enabled": True,
                        "artifact_path": str(artifact_path),
                        "metrics": {
                            "total": {"expected": 100, "tolerance": 0, "severity": "blocker"},
                            "pass_rate": {"min": 1.0, "severity": "warning"},
                        },
                    },
                },
            }
            report = run_governance(baseline, project_root=Path("."))
            assert report.has_blocker is True
            comp = report.component_results[0]
            assert comp.fail_count == 2
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Optional Metrics ─────────────────────────────────────────────


class TestOptionalMetrics:

    def test_optional_missing_metric_skipped(self):
        """optional=true 的缺失指标应返回 skipped 而非 missing。"""
        result = compare_metric(None, {"min": 0.5, "severity": "blocker", "optional": True}, "rate", "comp")
        assert result.status == "skipped"

    def test_optional_present_metric_evaluated(self):
        """optional=true 但指标存在时应正常评估。"""
        result = compare_metric(0.3, {"min": 0.5, "severity": "blocker", "optional": True}, "rate", "comp")
        assert result.status == "fail"

    def test_optional_missing_not_in_failures(self):
        """skipped 指标不应出现在 failures.jsonl 中。"""
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.x", component="comp",
                                 metric_path="x", severity="blocker",
                                 status="skipped", message="optional missing"),
                    MetricResult(path="comp.y", component="comp",
                                 metric_path="y", severity="warning",
                                 status="fail", actual=0.3),
                ]),
            ],
        )
        failures = generate_failures_jsonl(report)
        assert len(failures) == 1
        assert failures[0]["status"] == "fail"

    def test_optional_missing_does_not_trigger_blocker(self):
        """optional 缺失指标不应触发 blocker。"""
        comp = ComponentResult(
            component="test", enabled=True,
            metrics=[
                MetricResult(path="x", component="test", metric_path="x",
                             severity="blocker", status="skipped"),
            ],
        )
        assert comp.has_blocker is False

    def test_baseline_schema_accepts_optional_without_range(self):
        """baseline schema 校验应接受 optional=true 的无 min/max/expected 指标。"""
        data = {
            "version": 1,
            "components": {
                "test": {
                    "enabled": True,
                    "metrics": {
                        "m": {"severity": "warning", "optional": True},
                    },
                },
            },
        }
        errors = validate_baseline_schema(data)
        assert errors == []


# ── Freshness Check ──────────────────────────────────────────────


class TestFreshnessCheck:

    def test_fresh_artifact_passes(self):
        """新生成的 artifact 应通过新鲜度检查。"""
        from datetime import datetime, timezone

        from services.research.quality_governance import _check_artifact_freshness

        artifact = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": 100,
        }
        config = {"max_age_hours": 24}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is None

    def test_stale_artifact_fails(self):
        """过期 artifact 应返回 fail。"""
        from services.research.quality_governance import _check_artifact_freshness

        artifact = {
            "generated_at": "2020-01-01T00:00:00+00:00",
            "total": 100,
        }
        config = {"max_age_hours": 24}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is not None
        assert result.status == "fail"
        assert result.severity == "warning"

    def test_missing_generated_at(self):
        """缺少 generated_at 应返回 missing。"""
        from services.research.quality_governance import _check_artifact_freshness

        artifact = {"total": 100}
        config = {"max_age_hours": 24, "freshness_severity": "blocker"}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is not None
        assert result.status == "missing"
        assert result.severity == "blocker"

    def test_completed_at_can_drive_freshness(self):
        """live monitor artifact 可用 completed_at 校验新鲜度。"""
        from datetime import datetime, timezone

        from services.research.quality_governance import _check_artifact_freshness

        artifact = {"completed_at": datetime.now(timezone.utc).isoformat()}
        config = {"max_age_hours": 24}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is None

    def test_no_freshness_config_skips(self):
        """没有 max_age_hours/max_age_days 配置时跳过检查。"""
        from services.research.quality_governance import _check_artifact_freshness

        artifact = {"generated_at": "2020-01-01T00:00:00+00:00", "total": 100}
        result = _check_artifact_freshness(artifact, "comp", {})
        assert result is None

    def test_max_age_days(self):
        """max_age_days 应正确转换为小时。"""
        from services.research.quality_governance import _check_artifact_freshness

        artifact = {"generated_at": "2020-01-01T00:00:00+00:00", "total": 100}
        config = {"max_age_days": 1}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is not None
        assert result.status == "fail"

    def test_custom_freshness_severity(self):
        """可通过 freshness_severity 配置严重等级。"""
        from services.research.quality_governance import _check_artifact_freshness

        artifact = {"generated_at": "2020-01-01T00:00:00+00:00", "total": 100}
        config = {"max_age_hours": 1, "freshness_severity": "blocker"}
        result = _check_artifact_freshness(artifact, "comp", config)
        assert result is not None
        assert result.severity == "blocker"


# ── Evidence Schema Metrics ─────────────────────────────────────


class TestEvidenceSchemaMetrics:

    def test_missing_fixture_marks_validation_not_run(self):
        """找不到历史样本 fixture 时，evidence 校验不能被 max:0 误判通过。"""
        from services.research.quality_governance import _get_evidence_schema_metrics

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            metrics = _get_evidence_schema_metrics(project_root=tmp_dir)
            assert metrics["validation_ran"] is False
            assert metrics["validation_sample_count"] == 0
            assert metrics["validation_error_count"] > 0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Baseline Candidate Metadata ──────────────────────────────────


class TestBaselineCandidateMetadata:

    def test_preserves_component_metadata(self):
        """generate_baseline_candidate 应保留原始 baseline 的组件元数据。"""
        baseline = {
            "version": 1,
            "components": {
                "comp_a": {
                    "enabled": True,
                    "artifact_path": "storage/artifacts/comp_a.json",
                    "source": "artifact",
                    "metrics": {
                        "rate": {"min": 0.5, "severity": "blocker"},
                    },
                },
                "comp_b": {
                    "enabled": False,
                    "default_enabled": False,
                    "opt_in_reason": "needs network",
                    "artifact_path": "storage/artifacts/comp_b.json",
                    "metrics": {},
                },
            },
        }
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp_a", enabled=True, metrics=[
                    MetricResult(path="comp_a.rate", component="comp_a",
                                 metric_path="rate", severity="blocker",
                                 status="pass", actual=0.95),
                ]),
            ],
        )
        candidate = generate_baseline_candidate(report, baseline=baseline)
        # Metadata preserved
        assert candidate["components"]["comp_a"]["artifact_path"] == "storage/artifacts/comp_a.json"
        assert candidate["components"]["comp_a"]["source"] == "artifact"
        # Skipped component preserved
        assert "comp_b" in candidate["components"]
        assert candidate["components"]["comp_b"]["opt_in_reason"] == "needs network"
        # Metric updated
        assert candidate["components"]["comp_a"]["metrics"]["rate"]["min"] == 0.95

    def test_preserves_rule_type_max(self):
        """应保留原始 max 规则类型，不转为 min。"""
        baseline = {
            "version": 1,
            "components": {
                "comp": {
                    "enabled": True,
                    "metrics": {
                        "violation_rate": {"max": 0.0, "severity": "blocker"},
                    },
                },
            },
        }
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.violation_rate", component="comp",
                                 metric_path="violation_rate", severity="blocker",
                                 status="pass", actual=0.0),
                ]),
            ],
        )
        candidate = generate_baseline_candidate(report, baseline=baseline)
        rule = candidate["components"]["comp"]["metrics"]["violation_rate"]
        assert "max" in rule
        assert "min" not in rule

    def test_preserves_optional_flag(self):
        """应保留 optional 标记。"""
        baseline = {
            "version": 1,
            "components": {
                "comp": {
                    "enabled": True,
                    "metrics": {
                        "m": {"min": 0.5, "severity": "warning", "optional": True},
                    },
                },
            },
        }
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.m", component="comp",
                                 metric_path="m", severity="warning",
                                 status="pass", actual=0.8),
                ]),
            ],
        )
        candidate = generate_baseline_candidate(report, baseline=baseline)
        assert candidate["components"]["comp"]["metrics"]["m"]["optional"] is True

    def test_without_baseline_falls_back(self):
        """不传 baseline 时应回退到简单模式。"""
        report = GovernanceReport(
            run_id="t", started_at="", completed_at="", baseline_path="",
            component_results=[
                ComponentResult(component="comp", enabled=True, metrics=[
                    MetricResult(path="comp.rate", component="comp",
                                 metric_path="rate", severity="blocker",
                                 status="pass", actual=0.95),
                ]),
            ],
        )
        candidate = generate_baseline_candidate(report)
        assert candidate["components"]["comp"]["metrics"]["rate"]["min"] == 0.95
