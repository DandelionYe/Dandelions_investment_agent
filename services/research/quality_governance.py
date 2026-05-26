"""P2 Phase 6: 研究质量治理核心模块。

统一加载 baseline、比较 artifact、输出 drift/failure/warning/watch 结果。
复用已有历史回测、evidence schema、报告产品化、新闻质量模块的 artifact。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo  # noqa: I001

# ── 数据类 ──────────────────────────────────────────────────────


@dataclass
class MetricResult:
    path: str
    component: str
    metric_path: str
    severity: str  # blocker | warning | watch
    status: str  # pass | fail | missing | skipped
    expected: Any = None
    actual: Any = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "component": self.component,
            "metric_path": self.metric_path,
            "severity": self.severity,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass
class ComponentResult:
    component: str
    enabled: bool
    skipped: bool = False
    skip_reason: str = ""
    artifact_loaded: bool = False
    metrics: list[MetricResult] = field(default_factory=list)

    @property
    def has_blocker(self) -> bool:
        return any(
            m.status in ("fail", "missing") and m.severity == "blocker"
            for m in self.metrics
        )

    @property
    def has_warning(self) -> bool:
        return any(
            m.status in ("fail", "missing") and m.severity == "warning"
            for m in self.metrics
        )

    @property
    def has_watch(self) -> bool:
        return any(
            m.status in ("fail", "missing") and m.severity == "watch"
            for m in self.metrics
        )

    @property
    def fail_count(self) -> int:
        return sum(1 for m in self.metrics if m.status in ("fail", "missing"))

    @property
    def pass_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "pass")

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "enabled": self.enabled,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "artifact_loaded": self.artifact_loaded,
            "has_blocker": self.has_blocker,
            "has_warning": self.has_warning,
            "has_watch": self.has_watch,
            "fail_count": self.fail_count,
            "pass_count": self.pass_count,
            "metrics": [m.to_dict() for m in self.metrics],
        }


@dataclass
class GovernanceReport:
    run_id: str
    started_at: str
    completed_at: str
    baseline_path: str
    component_results: list[ComponentResult] = field(default_factory=list)

    @property
    def has_blocker(self) -> bool:
        return any(c.has_blocker for c in self.component_results)

    @property
    def has_warning(self) -> bool:
        return any(c.has_warning for c in self.component_results)

    @property
    def has_watch(self) -> bool:
        return any(c.has_watch for c in self.component_results)

    @property
    def overall_status(self) -> str:
        if self.has_blocker:
            return "blocker"
        if self.has_warning:
            return "warning"
        if self.has_watch:
            return "watch"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "baseline_path": self.baseline_path,
            "overall_status": self.overall_status,
            "has_blocker": self.has_blocker,
            "has_warning": self.has_warning,
            "has_watch": self.has_watch,
            "component_results": [c.to_dict() for c in self.component_results],
        }


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _check_artifact_freshness(
    artifact: dict,
    comp_name: str,
    comp_config: dict,
) -> MetricResult | None:
    """检查 artifact 新鲜度。返回 MetricResult（如果是 stale），否则 None。"""
    max_age_hours = comp_config.get("max_age_hours")
    max_age_days = comp_config.get("max_age_days")
    if max_age_hours is None and max_age_days is None:
        return None

    timestamp_value = (
        artifact.get("generated_at")
        or artifact.get("completed_at")
        or artifact.get("started_at")
    )
    severity = comp_config.get("freshness_severity", "warning")
    if not timestamp_value:
        return MetricResult(
            path=f"{comp_name}._artifact_freshness",
            component=comp_name,
            metric_path="_artifact_freshness",
            severity=severity,
            status="missing",
            message="artifact 缺少 generated_at/completed_at/started_at 字段，无法校验新鲜度",
        )

    try:
        gen_dt = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
        if gen_dt.tzinfo is None:
            gen_dt = gen_dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        now = datetime.now(ZoneInfo("UTC"))
        age_hours = (now - gen_dt).total_seconds() / 3600
        max_hours = max_age_hours if max_age_hours is not None else (max_age_days or 0) * 24

        if age_hours > max_hours:
            return MetricResult(
                path=f"{comp_name}._artifact_freshness",
                component=comp_name,
                metric_path="_artifact_freshness",
                severity=severity,
                status="fail",
                expected=f"<= {max_hours}h",
                actual=round(age_hours, 1),
                message=f"artifact 已过期: {age_hours:.1f}h > {max_hours}h (timestamp={timestamp_value})",
            )
    except (ValueError, TypeError):
        return MetricResult(
            path=f"{comp_name}._artifact_freshness",
            component=comp_name,
            metric_path="_artifact_freshness",
            severity=severity,
            status="fail",
            message=f"artifact timestamp 格式无法解析: {timestamp_value}",
        )

    return None


# ── Baseline 校验 ────────────────────────────────────────────────


def validate_baseline_schema(data: dict) -> list[str]:
    """校验 baseline JSON 结构。返回错误列表。"""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["baseline 必须是 dict"]

    if "version" not in data:
        errors.append("缺少 version")
    if "components" not in data:
        errors.append("缺少 components")
        return errors

    components = data["components"]
    if not isinstance(components, dict):
        errors.append("components 必须是 dict")
        return errors

    for comp_name, comp in components.items():
        if not isinstance(comp, dict):
            errors.append(f"components.{comp_name} 必须是 dict")
            continue
        if "enabled" not in comp:
            errors.append(f"components.{comp_name} 缺少 enabled")
        if "metrics" not in comp:
            errors.append(f"components.{comp_name} 缺少 metrics")
            continue
        metrics = comp["metrics"]
        if not isinstance(metrics, dict):
            errors.append(f"components.{comp_name}.metrics 必须是 dict")
            continue
        for metric_path, rule in metrics.items():
            if not isinstance(rule, dict):
                errors.append(f"components.{comp_name}.metrics.{metric_path} 必须是 dict")
                continue
            if "severity" not in rule:
                errors.append(f"components.{comp_name}.metrics.{metric_path} 缺少 severity")
            elif rule["severity"] not in ("blocker", "warning", "watch"):
                errors.append(
                    f"components.{comp_name}.metrics.{metric_path} "
                    f"severity={rule['severity']} 不在 blocker/warning/watch"
                )
            has_range = any(k in rule for k in ("min", "max", "expected"))
            if not has_range and not rule.get("optional", False):
                errors.append(
                    f"components.{comp_name}.metrics.{metric_path} "
                    "缺少 min/max/expected"
                )

    return errors


# ── Artifact 加载 ────────────────────────────────────────────────


def load_baseline(path: str | Path) -> dict:
    """加载 baseline 配置。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"baseline 文件不存在: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_artifact(path: str | Path) -> dict | None:
    """加载 artifact JSON。缺失返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None


def extract_metric(artifact: dict, metric_path: str) -> Any:
    """按点路径从 artifact 提取指标值。支持嵌套如 data_gap_summary.data_complete_coverage。"""
    parts = metric_path.split(".")
    cur: Any = artifact
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


# ── 指标比较 ─────────────────────────────────────────────────────


def compare_metric(
    actual: Any,
    rule: dict,
    metric_path: str,
    component: str,
) -> MetricResult:
    """比较单个指标。"""
    severity = rule.get("severity", "warning")
    path = f"{component}.{metric_path}"

    if actual is None:
        if rule.get("optional", False):
            return MetricResult(
                path=path,
                component=component,
                metric_path=metric_path,
                severity=severity,
                status="skipped",
                message=f"可选指标 {metric_path} 缺失，跳过",
            )
        return MetricResult(
            path=path,
            component=component,
            metric_path=metric_path,
            severity=severity,
            status="missing",
            message=f"指标 {metric_path} 在 artifact 中不存在",
        )

    # expected + tolerance
    if "expected" in rule:
        expected = rule["expected"]
        tolerance = rule.get("tolerance", 0)
        try:
            diff = abs(float(actual) - float(expected))
            if diff > tolerance:
                return MetricResult(
                    path=path, component=component, metric_path=metric_path,
                    severity=severity, status="fail",
                    expected=expected, actual=actual,
                    message=f"期望 {expected}±{tolerance}，实际 {actual}",
                )
        except (TypeError, ValueError):
            if actual != expected:
                return MetricResult(
                    path=path, component=component, metric_path=metric_path,
                    severity=severity, status="fail",
                    expected=expected, actual=actual,
                    message=f"期望 {expected}，实际 {actual}",
                )
        return MetricResult(
            path=path, component=component, metric_path=metric_path,
            severity=severity, status="pass",
            expected=expected, actual=actual,
        )

    # min
    if "min" in rule:
        min_val = rule["min"]
        try:
            if float(actual) < min_val:
                return MetricResult(
                    path=path, component=component, metric_path=metric_path,
                    severity=severity, status="fail",
                    expected=f">={min_val}", actual=actual,
                    message=f"{actual} < {min_val}",
                )
        except (TypeError, ValueError):
            return MetricResult(
                path=path, component=component, metric_path=metric_path,
                severity=severity, status="fail",
                expected=f">={min_val}", actual=actual,
                message=f"无法比较: {actual} 不是数字",
            )

    # max
    if "max" in rule:
        max_val = rule["max"]
        try:
            if float(actual) > max_val:
                return MetricResult(
                    path=path, component=component, metric_path=metric_path,
                    severity=severity, status="fail",
                    expected=f"<={max_val}", actual=actual,
                    message=f"{actual} > {max_val}",
                )
        except (TypeError, ValueError):
            return MetricResult(
                path=path, component=component, metric_path=metric_path,
                severity=severity, status="fail",
                expected=f"<={max_val}", actual=actual,
                message=f"无法比较: {actual} 不是数字",
            )

    return MetricResult(
        path=path, component=component, metric_path=metric_path,
        severity=severity, status="pass", actual=actual,
    )


# ── 静态数据源 ──────────────────────────────────────────────────


def _get_evidence_schema_metrics(project_root: Path | None = None) -> dict:
    """从 evidence schema 模块获取指标，并对历史样本运行真实校验。"""
    from services.data.evidence_schema import (
        _KEY_FIELD_MAP,
        normalize_key_fields,
        validate_evidence_fields,
    )

    total_required = len(_KEY_FIELD_MAP)
    validation_error_count = 0
    validation_ran = False
    validation_sample_count = 0
    validation_error_message = ""

    root = project_root or Path(__file__).resolve().parents[2]
    samples_path = root / "tests" / "fixtures" / "research_quality_historical_samples.json"
    try:
        samples_data = json.loads(samples_path.read_text(encoding="utf-8"))
        samples = samples_data.get("samples", [])
        sample_batch = samples[:5]
        if not sample_batch:
            validation_error_count = 1
            validation_error_message = "historical samples fixture 为空"
        else:
            validation_ran = True
            validation_sample_count = len(sample_batch)
            for sample in sample_batch:
                normalize_key_fields(sample)
                errors = validate_evidence_fields(sample)
                validation_error_count += len(errors)
    except Exception as exc:
        validation_error_count = 1
        validation_error_message = f"{type(exc).__name__}: {exc}"

    return {
        "total_required": total_required,
        "validation_ran": validation_ran,
        "validation_sample_count": validation_sample_count,
        "validation_error_count": validation_error_count,
        "validation_error_message": validation_error_message,
    }


def _get_report_productization_metrics() -> dict:
    """从报告模板配置获取指标（不运行测试）。"""
    from services.report.template_config import FORMAL_TEMPLATE_IDS, SECTION_IDS
    return {
        "template_count": len(FORMAL_TEMPLATE_IDS),
        "section_count": len(SECTION_IDS),
    }


# ── 治理运行 ────────────────────────────────────────────────────


def run_governance(
    baseline: dict,
    *,
    project_root: Path | None = None,
    include_qmt_regression: bool = False,
    include_web_news_live: bool = False,
) -> GovernanceReport:
    """运行全部治理检查。"""
    run_id = uuid.uuid4().hex[:12]
    started_at = _now_iso()
    root = project_root or Path(".")

    component_results: list[ComponentResult] = []

    components = baseline.get("components", {})
    for comp_name, comp_config in components.items():
        enabled = comp_config.get("enabled", True)

        # Handle opt-in overrides
        if comp_name == "data_quality_regression" and include_qmt_regression:
            enabled = True
        if comp_name == "web_news_live" and include_web_news_live:
            enabled = True

        if not enabled:
            component_results.append(ComponentResult(
                component=comp_name,
                enabled=False,
                skipped=True,
                skip_reason=comp_config.get("opt_in_reason", "disabled"),
            ))
            continue

        artifact_path = comp_config.get("artifact_path")
        source = comp_config.get("source", "artifact")

        # Load artifact or use static source
        artifact = None
        artifact_loaded = False

        if source == "contract_test":
            if comp_name == "evidence_schema":
                artifact = _get_evidence_schema_metrics(project_root=root)
                artifact_loaded = True
            elif comp_name == "report_productization":
                artifact = _get_report_productization_metrics()
                artifact_loaded = True
        elif artifact_path:
            full_path = root / artifact_path
            artifact = load_artifact(full_path)
            artifact_loaded = artifact is not None

        comp_result = ComponentResult(
            component=comp_name,
            enabled=True,
            artifact_loaded=artifact_loaded,
        )

        # Freshness check
        if artifact is not None and artifact_loaded:
            freshness_result = _check_artifact_freshness(artifact, comp_name, comp_config)
            if freshness_result is not None:
                comp_result.metrics.append(freshness_result)

        metrics_config = comp_config.get("metrics", {})
        for metric_path, rule in metrics_config.items():
            if artifact is None:
                comp_result.metrics.append(MetricResult(
                    path=f"{comp_name}.{metric_path}",
                    component=comp_name,
                    metric_path=metric_path,
                    severity=rule.get("severity", "warning"),
                    status="missing",
                    message=f"artifact 不存在: {artifact_path}",
                ))
                continue

            actual = extract_metric(artifact, metric_path)
            result = compare_metric(actual, rule, metric_path, comp_name)
            comp_result.metrics.append(result)

        component_results.append(comp_result)

    completed_at = _now_iso()

    return GovernanceReport(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        baseline_path=str(baseline.get("_path", "")),
        component_results=component_results,
    )


# ── 报告生成 ────────────────────────────────────────────────────


def generate_drift_report(report: GovernanceReport) -> str:
    """生成 drift markdown 报告。"""
    lines = ["# 研究质量治理 Drift 报告", ""]
    lines.append(f"**Run ID**: {report.run_id}")
    lines.append(f"**时间**: {report.started_at}")
    lines.append(f"**总体状态**: {report.overall_status}")
    lines.append("")

    for comp in report.component_results:
        lines.append(f"## {comp.component}")
        lines.append("")

        if comp.skipped:
            lines.append(f"跳过: {comp.skip_reason}")
            lines.append("")
            continue

        if not comp.artifact_loaded:
            lines.append("**artifact 不存在**")
            lines.append("")

        # Summary table
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


def generate_baseline_candidate(
    report: GovernanceReport,
    baseline: dict | None = None,
) -> dict:
    """从当前 governance 结果生成 baseline 更新候选。

    基于原 baseline 深拷贝，只更新 metric 阈值，保留组件元数据和 opt-in 状态。
    """
    import copy

    if baseline is not None:
        candidate = copy.deepcopy(baseline)
        candidate.pop("_path", None)
    else:
        candidate: dict[str, Any] = {"version": 1, "components": {}}  # type: ignore[no-redef]

    for comp in report.component_results:
        if comp.skipped:
            continue

        if comp.component in candidate.get("components", {}):
            comp_entry = candidate["components"][comp.component]
        else:
            comp_entry = {"enabled": True, "metrics": {}}
            candidate.setdefault("components", {})[comp.component] = comp_entry

        for m in comp.metrics:
            if m.actual is not None:
                existing_rule = comp_entry.get("metrics", {}).get(m.metric_path, {})
                rule: dict[str, Any] = {"severity": m.severity}
                # Preserve original rule type (min/max/expected/tolerance)
                if "expected" in existing_rule:
                    rule["expected"] = m.actual
                    if "tolerance" in existing_rule:
                        rule["tolerance"] = existing_rule["tolerance"]
                elif "max" in existing_rule:
                    rule["max"] = m.actual
                elif isinstance(m.actual, (int, float)):
                    rule["min"] = m.actual
                else:
                    rule["expected"] = m.actual
                # Preserve optional flag if present
                if "optional" in existing_rule:
                    rule["optional"] = existing_rule["optional"]
                comp_entry.setdefault("metrics", {})[m.metric_path] = rule

    return candidate


def generate_failures_jsonl(report: GovernanceReport) -> list[dict]:
    """提取所有失败和缺失条目为 failures.jsonl 格式。"""
    failures = []
    for comp in report.component_results:
        for m in comp.metrics:
            if m.status in ("fail", "missing"):
                failures.append(m.to_dict())
    return failures


# ── Case Registry ────────────────────────────────────────────────


def validate_case_registry(data: dict) -> list[str]:
    """校验 case registry 结构。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["registry 必须是 dict"]
    if "version" not in data:
        errors.append("缺少 version")
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        errors.append("cases 必须是 list")
        return errors
    required_keys = {"case_id", "component", "failure_type", "severity", "status", "created_at"}
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{i}] 必须是 dict")
            continue
        for key in required_keys:
            if key not in case:
                errors.append(f"cases[{i}] 缺少 {key}")
        if case.get("status") not in (None, "proposed", "accepted", "regression"):
            errors.append(f"cases[{i}] status={case.get('status')} 不在 proposed/accepted/regression")
    return errors


def load_case_registry(path: str | Path) -> dict:
    """加载 case registry。"""
    p = Path(path)
    if not p.exists():
        return {"version": 1, "cases": []}
    return json.loads(p.read_text(encoding="utf-8"))


def generate_case_entry(
    failure: MetricResult,
    *,
    source_artifact: str = "",
    symbol: str = "",
    target_fixture: str = "",
) -> dict:
    """从 governance failure 生成 proposed case 条目。"""
    return {
        "case_id": f"case-{uuid.uuid4().hex[:8]}",
        "component": failure.component,
        "source_artifact": source_artifact,
        "symbol/sample_id": symbol,
        "failure_type": failure.status,
        "severity": failure.severity,
        "target_fixture": target_fixture,
        "status": "proposed",
        "created_at": _now_iso(),
        "notes": failure.message,
    }
