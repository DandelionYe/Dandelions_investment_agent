"""网页新闻/舆情长期趋势分析模块。

从 history.jsonl 读取多次运行摘要，按 provider 分层聚合指标，
判断趋势健康状态，输出 trend_summary / trend_report / provider_trends。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ── 数据类 ──────────────────────────────────────────────────────


@dataclass
class ProviderTierConfig:
    providers: list[str]
    on_failure: str = "watch"
    on_consecutive_failures: int = 3
    on_consecutive_failures_severity: str = "blocker"
    min_success_rate: float = 0.0
    success_rate_severity: str = "watch"
    block_on_failure: bool = True


@dataclass
class TrendPolicy:
    provider_tiers: dict[str, ProviderTierConfig] = field(default_factory=dict)
    default_window_days: int = 7
    min_runs_for_trend: int = 3
    core_provider_ok_required: bool = True
    healthy_provider_count_min: int = 1
    failed_core_provider_count_max: int = 0
    max_age_hours: float = 48.0
    freshness_severity: str = "warning"

    @classmethod
    def from_dict(cls, data: dict) -> TrendPolicy:
        tiers = {}
        for tier_name, tier_data in data.get("provider_tiers", {}).items():
            tiers[tier_name] = ProviderTierConfig(
                providers=tier_data.get("providers", []),
                on_failure=tier_data.get("on_failure", "watch"),
                on_consecutive_failures=tier_data.get("on_consecutive_failures", 3),
                on_consecutive_failures_severity=tier_data.get("on_consecutive_failures_severity", "blocker"),
                min_success_rate=tier_data.get("min_success_rate", 0.0),
                success_rate_severity=tier_data.get("success_rate_severity", "watch"),
                block_on_failure=tier_data.get("block_on_failure", True),
            )
        trend_cfg = data.get("trend_analysis", {})
        freshness_cfg = data.get("freshness", {})
        return cls(
            provider_tiers=tiers,
            default_window_days=trend_cfg.get("default_window_days", 7),
            min_runs_for_trend=trend_cfg.get("min_runs_for_trend", 3),
            core_provider_ok_required=trend_cfg.get("core_provider_ok_required", True),
            healthy_provider_count_min=trend_cfg.get("healthy_provider_count_min", 1),
            failed_core_provider_count_max=trend_cfg.get("failed_core_provider_count_max", 0),
            max_age_hours=freshness_cfg.get("max_age_hours", 48.0),
            freshness_severity=freshness_cfg.get("freshness_severity", "warning"),
        )


@dataclass
class ProviderTrend:
    provider: str
    tier: str
    run_count: int = 0
    attempts: int = 0
    successes: int = 0
    timeouts: int = 0
    empty_results: int = 0
    total_items: int = 0
    total_deduped: int = 0
    total_relevant: int = 0
    total_low_quality: int = 0
    total_latency: float = 0.0
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_run_at: str | None = None

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

    @property
    def timeout_rate(self) -> float:
        return self.timeouts / self.attempts if self.attempts > 0 else 0.0

    @property
    def empty_rate(self) -> float:
        return self.empty_results / self.attempts if self.attempts > 0 else 0.0

    @property
    def relevance_rate(self) -> float:
        return self.total_relevant / self.total_deduped if self.total_deduped > 0 else 0.0

    @property
    def low_quality_rate(self) -> float:
        return self.total_low_quality / self.total_deduped if self.total_deduped > 0 else 0.0

    @property
    def avg_latency_seconds(self) -> float:
        return self.total_latency / self.attempts if self.attempts > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "tier": self.tier,
            "run_count": self.run_count,
            "attempts": self.attempts,
            "success_rate": round(self.success_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "empty_rate": round(self.empty_rate, 4),
            "relevance_rate": round(self.relevance_rate, 4),
            "low_quality_rate": round(self.low_quality_rate, 4),
            "avg_latency_seconds": round(self.avg_latency_seconds, 3),
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at,
            "last_run_at": self.last_run_at,
        }


@dataclass
class TrendAssessment:
    provider: str
    tier: str
    status: str  # ok | degraded | failed
    severity: str  # blocker | warning | watch
    issues: list[str] = field(default_factory=list)


@dataclass
class TrendSummary:
    run_id: str
    generated_at: str
    window_days: int
    run_count: int
    day_count: int
    first_run_at: str | None
    last_run_at: str | None
    provider_count: int
    healthy_provider_count: int
    degraded_provider_count: int
    failed_provider_count: int
    core_provider_ok: bool
    failed_core_provider_count: int
    overall_severity: str  # ok | warning | watch | blocker
    warnings: list[str] = field(default_factory=list)
    provider_trends: list[ProviderTrend] = field(default_factory=list)
    assessments: list[TrendAssessment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "window_days": self.window_days,
            "run_count": self.run_count,
            "day_count": self.day_count,
            "first_run_at": self.first_run_at,
            "last_run_at": self.last_run_at,
            "provider_count": self.provider_count,
            "healthy_provider_count": self.healthy_provider_count,
            "degraded_provider_count": self.degraded_provider_count,
            "failed_provider_count": self.failed_provider_count,
            "core_provider_ok": self.core_provider_ok,
            "failed_core_provider_count": self.failed_core_provider_count,
            "overall_severity": self.overall_severity,
            "warnings": self.warnings,
            "provider_trends": [pt.to_dict() for pt in self.provider_trends],
            "assessments": [
                {
                    "provider": a.provider,
                    "tier": a.tier,
                    "status": a.status,
                    "severity": a.severity,
                    "issues": a.issues,
                }
                for a in self.assessments
            ],
        }


# ── Helper ──────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return dt
    except (ValueError, TypeError):
        return None


def _get_provider_tier(
    provider: str,
    policy: TrendPolicy,
) -> str:
    for tier_name, tier_cfg in policy.provider_tiers.items():
        if provider in tier_cfg.providers:
            return tier_name
    return "unknown"


def _get_tier_config(
    tier: str,
    policy: TrendPolicy,
) -> ProviderTierConfig | None:
    return policy.provider_tiers.get(tier)


# ── Core ────────────────────────────────────────────────────────


def load_history_runs(
    history_path: Path,
    window_days: int | None = None,
) -> list[dict]:
    """Load runs from history.jsonl, filtering by window_days.

    Tolerates: missing file, empty file, corrupt lines, missing per_provider.
    Returns list of valid run dicts.
    """
    if not history_path.exists():
        return []

    runs: list[dict] = []
    now = datetime.now(ZoneInfo("UTC"))
    cutoff = now - timedelta(days=window_days) if window_days else None

    for _line_num, line in enumerate(history_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Filter by window
        if cutoff:
            completed_at = _parse_timestamp(entry.get("completed_at"))
            if completed_at and completed_at < cutoff:
                continue

        runs.append(entry)

    return runs


def aggregate_provider_trends(
    runs: list[dict],
    policy: TrendPolicy,
) -> dict[str, ProviderTrend]:
    """Aggregate runs into per-provider trends."""
    trends: dict[str, ProviderTrend] = {}

    for run in runs:
        per_provider = run.get("per_provider", {})
        for provider, info in per_provider.items():
            if provider not in trends:
                tier = _get_provider_tier(provider, policy)
                trends[provider] = ProviderTrend(provider=provider, tier=tier)

            pt = trends[provider]
            pt.run_count += 1
            pt.last_run_at = run.get("completed_at")

            attempts = info.get("attempts", 0)
            pt.attempts += attempts
            pt.successes += int(info.get("success_rate", 0) * attempts)
            pt.timeouts += int(info.get("timeout_rate", 0) * attempts)
            pt.empty_results += int(info.get("empty_rate", 0) * attempts)
            pt.total_latency += info.get("avg_latency_seconds", 0) * attempts

            # Relevance and low quality (from aggregated rates)
            deduped_est = max(1, attempts)  # approximate
            pt.total_relevant += int(info.get("avg_relevance_rate", 0) * deduped_est)
            pt.total_deduped += deduped_est
            pt.total_low_quality += int(info.get("avg_low_quality_rate", 0) * deduped_est)

            if info.get("last_success_at"):
                pt.last_success_at = info["last_success_at"]

    return trends


def compute_consecutive_failures(
    runs: list[dict],
    provider: str,
) -> int:
    """Count consecutive failures from the most recent run backwards."""
    consecutive = 0
    for run in reversed(runs):
        pp = run.get("per_provider", {})
        info = pp.get(provider)
        if info is None:
            continue
        status = info.get("status", "ok")
        if status == "fail":
            consecutive += 1
        else:
            break
    return consecutive


def assess_providers(
    trends: dict[str, ProviderTrend],
    runs: list[dict],
    policy: TrendPolicy,
) -> tuple[list[TrendAssessment], list[str]]:
    """Assess each provider's health and return assessments + global warnings."""
    assessments: list[TrendAssessment] = []
    warnings: list[str] = []

    for provider, pt in trends.items():
        tier_cfg = _get_tier_config(pt.tier, policy)
        issues: list[str] = []
        status = "ok"
        severity = "watch"

        # Compute consecutive failures from recent runs
        pt.consecutive_failures = compute_consecutive_failures(runs, provider)

        if tier_cfg:
            # Success rate check
            if tier_cfg.min_success_rate > 0 and pt.success_rate < tier_cfg.min_success_rate:
                issues.append(
                    f"success_rate {pt.success_rate:.2%} < {tier_cfg.min_success_rate:.2%}"
                )
                severity = tier_cfg.success_rate_severity
                status = "degraded"

            # Consecutive failures check
            if (tier_cfg.on_consecutive_failures > 0
                    and pt.consecutive_failures >= tier_cfg.on_consecutive_failures):
                issues.append(
                    f"consecutive_failures {pt.consecutive_failures} >= {tier_cfg.on_consecutive_failures}"
                )
                sev = tier_cfg.on_consecutive_failures_severity
                if _severity_rank(sev) > _severity_rank(severity):
                    severity = sev
                status = "failed"

            # Zero successes in core tier
            if pt.tier == "core" and pt.attempts > 0 and pt.successes == 0:
                issues.append("core provider has zero successes")
                if _severity_rank("warning") > _severity_rank(severity):
                    severity = "warning"
                status = "failed"

        if issues:
            assessments.append(TrendAssessment(
                provider=provider,
                tier=pt.tier,
                status=status,
                severity=severity,
                issues=issues,
            ))
            for issue in issues:
                warnings.append(f"[{pt.tier}/{provider}] {issue}")
        else:
            assessments.append(TrendAssessment(
                provider=provider,
                tier=pt.tier,
                status="ok",
                severity="watch",
            ))

    return assessments, warnings


def _severity_rank(severity: str) -> int:
    return {"watch": 0, "warning": 1, "blocker": 2}.get(severity, 0)


def compute_overall_severity(
    assessments: list[TrendAssessment],
    policy: TrendPolicy,
    run_count: int,
) -> str:
    """Compute overall severity from assessments."""
    if run_count < policy.min_runs_for_trend:
        return "watch"

    # Check blocker-level assessments
    for a in assessments:
        if a.severity == "blocker":
            return "blocker"

    # Core provider check
    core_providers = set()
    for tier_cfg in policy.provider_tiers.values():
        if any(t == "core" for t in [tier_cfg]):
            pass
    for tier_name, tier_cfg in policy.provider_tiers.items():
        if tier_name == "core":
            core_providers.update(tier_cfg.providers)

    core_ok = True
    for a in assessments:
        if a.provider in core_providers and a.status == "failed":
            core_ok = False

    if policy.core_provider_ok_required and not core_ok:
        return "blocker"

    # Check warning-level
    for a in assessments:
        if a.severity == "warning":
            return "warning"

    # Healthy provider count
    healthy_count = sum(1 for a in assessments if a.status == "ok")
    if healthy_count < policy.healthy_provider_count_min:
        return "warning"

    # Watch-level
    for a in assessments:
        if a.severity == "watch" and a.status != "ok":
            return "watch"

    return "ok"


def analyze_trends(
    history_path: Path,
    policy: TrendPolicy,
    window_days: int | None = None,
) -> TrendSummary:
    """Main entry point: load history, aggregate, assess, return summary."""
    wd = window_days or policy.default_window_days
    runs = load_history_runs(history_path, window_days=wd)

    trends = aggregate_provider_trends(runs, policy)
    assessments, warnings = assess_providers(trends, runs, policy)

    # Day count
    timestamps = []
    for run in runs:
        ts = _parse_timestamp(run.get("completed_at"))
        if ts:
            timestamps.append(ts)
    timestamps.sort()

    day_count = 0
    if len(timestamps) >= 2:
        day_count = (timestamps[-1] - timestamps[0]).days + 1
    elif len(timestamps) == 1:
        day_count = 1

    overall_severity = compute_overall_severity(assessments, policy, len(runs))

    # Core provider count
    core_providers = set()
    for tier_name, tier_cfg in policy.provider_tiers.items():
        if tier_name == "core":
            core_providers.update(tier_cfg.providers)

    failed_core = sum(
        1 for a in assessments
        if a.provider in core_providers and a.status == "failed"
    )

    healthy_count = sum(1 for a in assessments if a.status == "ok")
    degraded_count = sum(1 for a in assessments if a.status == "degraded")
    failed_count = sum(1 for a in assessments if a.status == "failed")

    return TrendSummary(
        run_id=uuid.uuid4().hex[:12],
        generated_at=_now_iso(),
        window_days=wd,
        run_count=len(runs),
        day_count=day_count,
        first_run_at=timestamps[0].isoformat(timespec="seconds") if timestamps else None,
        last_run_at=timestamps[-1].isoformat(timespec="seconds") if timestamps else None,
        provider_count=len(trends),
        healthy_provider_count=healthy_count,
        degraded_provider_count=degraded_count,
        failed_provider_count=failed_count,
        core_provider_ok=failed_core == 0,
        failed_core_provider_count=failed_core,
        overall_severity=overall_severity,
        warnings=warnings,
        provider_trends=list(trends.values()),
        assessments=assessments,
    )


def build_trend_report_markdown(summary: TrendSummary) -> str:
    """Generate markdown trend report."""
    lines = ["# 网页新闻/舆情趋势分析报告", ""]
    lines.append(f"**Run ID**: {summary.run_id}")
    lines.append(f"**生成时间**: {summary.generated_at}")
    lines.append(f"**窗口**: {summary.window_days} 天")
    lines.append(f"**总体状态**: {summary.overall_severity}")
    lines.append("")

    lines.append("## 概览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 运行次数 | {summary.run_count} |")
    lines.append(f"| 覆盖天数 | {summary.day_count} |")
    lines.append(f"| 首次运行 | {summary.first_run_at or '-'} |")
    lines.append(f"| 最近运行 | {summary.last_run_at or '-'} |")
    lines.append(f"| Provider 总数 | {summary.provider_count} |")
    lines.append(f"| 健康 Provider | {summary.healthy_provider_count} |")
    lines.append(f"| 降级 Provider | {summary.degraded_provider_count} |")
    lines.append(f"| 失败 Provider | {summary.failed_provider_count} |")
    lines.append(f"| Core Provider 正常 | {'Yes' if summary.core_provider_ok else 'No'} |")
    lines.append("")

    lines.append("## Provider 趋势")
    lines.append("")
    lines.append("| Provider | 层级 | 状态 | 成功率 | 超时率 | 空结果率 | 相关率 | 平均延迟 | 连续失败 | 运行次数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for a in summary.assessments:
        pt = next((p for p in summary.provider_trends if p.provider == a.provider), None)
        if pt:
            lines.append(
                f"| {a.provider} | {a.tier} | {a.status} | "
                f"{pt.success_rate:.1%} | {pt.timeout_rate:.1%} | "
                f"{pt.empty_rate:.1%} | {pt.relevance_rate:.1%} | "
                f"{pt.avg_latency_seconds:.2f}s | {pt.consecutive_failures} | "
                f"{pt.run_count} |"
            )
    lines.append("")

    if summary.warnings:
        lines.append("## 警告")
        lines.append("")
        for w in summary.warnings[:20]:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def save_trend_artifacts(
    summary: TrendSummary,
    output_dir: Path,
) -> None:
    """Save trend_summary.json, trend_report.md, provider_trends.json."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # trend_summary.json
    (output_dir / "trend_summary.json").write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # trend_report.md
    (output_dir / "trend_report.md").write_text(
        build_trend_report_markdown(summary),
        encoding="utf-8",
    )

    # provider_trends.json
    provider_trends_data = {
        "generated_at": summary.generated_at,
        "window_days": summary.window_days,
        "run_count": summary.run_count,
        "providers": [pt.to_dict() for pt in summary.provider_trends],
    }
    (output_dir / "provider_trends.json").write_text(
        json.dumps(provider_trends_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
