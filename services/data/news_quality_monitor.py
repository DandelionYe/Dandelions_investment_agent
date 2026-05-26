"""网页新闻/舆情长期质量监控模块。

复用 WebNewsProvider 和 news_quality.py，对核心标的池运行真实抓取，
按 provider/source 维度评估稳定性，输出结构化 artifact。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from services.data.news_quality import (
    classify_news_quality,
    dedupe_news_items,
    evaluate_news_provider_result,
)
from services.data.providers.web_news_provider import WebNewsProvider

DEFAULT_SOURCES = ["eastmoney", "sina", "xinhuanet", "hotrank", "baidu"]


@dataclass
class MonitorThresholds:
    min_success_rate: float = 0.50
    max_timeout_rate: float = 0.50
    max_empty_rate: float = 0.70
    min_relevance_rate: float = 0.20
    max_low_quality_rate: float = 0.60
    max_avg_latency_seconds: float = 15.0

    def to_dict(self) -> dict:
        return {
            "min_success_rate": self.min_success_rate,
            "max_timeout_rate": self.max_timeout_rate,
            "max_empty_rate": self.max_empty_rate,
            "min_relevance_rate": self.min_relevance_rate,
            "max_low_quality_rate": self.max_low_quality_rate,
            "max_avg_latency_seconds": self.max_avg_latency_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MonitorThresholds:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ProviderEvaluation:
    run_id: str
    timestamp: str
    symbol: str
    symbol_name: str
    provider: str
    dataset: str
    success: bool
    error_type: str | None
    error_message: str | None
    latency_seconds: float
    total_items: int
    deduped_total: int
    relevant_count: int
    low_quality_count: int
    duplicate_rate: float
    relevance_rate: float
    low_quality_rate: float
    is_timeout: bool
    is_empty: bool
    source_counts: dict[str, int]
    warnings: list[str]
    classified_items: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "provider": self.provider,
            "dataset": self.dataset,
            "success": self.success,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "latency_seconds": round(self.latency_seconds, 3),
            "total_items": self.total_items,
            "deduped_total": self.deduped_total,
            "relevant_count": self.relevant_count,
            "low_quality_count": self.low_quality_count,
            "duplicate_rate": round(self.duplicate_rate, 4),
            "relevance_rate": round(self.relevance_rate, 4),
            "low_quality_rate": round(self.low_quality_rate, 4),
            "is_timeout": self.is_timeout,
            "is_empty": self.is_empty,
            "source_counts": self.source_counts,
            "warnings": self.warnings,
            "classified_items": self.classified_items,
        }


@dataclass
class ProviderHealth:
    source: str
    attempts: int = 0
    successes: int = 0
    timeouts: int = 0
    empty_results: int = 0
    total_latency: float = 0.0
    total_relevant: int = 0
    total_deduped: int = 0
    total_low_quality: int = 0
    last_success_at: str | None = None
    last_error_type: str | None = None

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
    def avg_latency_seconds(self) -> float:
        return self.total_latency / self.attempts if self.attempts > 0 else 0.0

    @property
    def avg_relevance_rate(self) -> float:
        return self.total_relevant / self.total_deduped if self.total_deduped > 0 else 0.0

    @property
    def avg_low_quality_rate(self) -> float:
        return self.total_low_quality / self.total_deduped if self.total_deduped > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "attempts": self.attempts,
            "successes": self.successes,
            "timeouts": self.timeouts,
            "empty_results": self.empty_results,
            "total_deduped": self.total_deduped,
            "total_relevant": self.total_relevant,
            "total_low_quality": self.total_low_quality,
            "success_rate": round(self.success_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "empty_rate": round(self.empty_rate, 4),
            "avg_latency_seconds": round(self.avg_latency_seconds, 3),
            "avg_relevance_rate": round(self.avg_relevance_rate, 4),
            "avg_low_quality_rate": round(self.avg_low_quality_rate, 4),
            "last_success_at": self.last_success_at,
            "last_error_type": self.last_error_type,
        }


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _classify_provider_status(
    health: ProviderHealth,
    thresholds: MonitorThresholds,
) -> str:
    """Return 'ok', 'warn', or 'fail' based on thresholds."""
    if health.attempts == 0:
        return "warn"

    fail_conditions = [
        health.success_rate < thresholds.min_success_rate,
        health.timeout_rate > thresholds.max_timeout_rate,
        health.avg_latency_seconds > thresholds.max_avg_latency_seconds,
    ]
    if any(fail_conditions):
        return "fail"

    warn_conditions = [
        health.empty_rate > thresholds.max_empty_rate,
        health.avg_relevance_rate < thresholds.min_relevance_rate,
        health.avg_low_quality_rate > thresholds.max_low_quality_rate,
    ]
    if any(warn_conditions):
        return "warn"

    return "ok"


def _detect_manual_review_candidates(
    eval_record: ProviderEvaluation,
    symbol_info: dict,
) -> list[dict]:
    """Identify items that need manual review."""
    candidates = []
    seen_keys: set[str] = set()

    for item in eval_record.classified_items:
        reasons = []
        relevance = item.get("relevance", 0.0)
        quality_tier = item.get("quality_tier", "unknown")
        title = item.get("title", "")

        # Low relevance but classified as relevant
        if quality_tier == "high" and relevance < 0.5:
            reasons.append("low_relevance_but_high_tier")

        # High relevance but low quality
        if relevance >= 0.4 and quality_tier == "low":
            reasons.append("high_relevance_but_low_quality")

        # Duplicate title detection (within this eval's deduped set)
        # We check against seen keys from classified items
        norm_title = title.strip().lower()
        if norm_title in seen_keys:
            reasons.append("duplicate_title_in_results")
        seen_keys.add(norm_title)

        # Provider returned but no company name/code hit
        company_name = (symbol_info.get("name") or "").lower()
        plain_code = (symbol_info.get("plain_code") or "").lower()
        text = f"{title} {item.get('summary', '')}".lower()
        if item.get("query_provider") and company_name not in text and plain_code not in text:
            reasons.append("no_company_match_in_text")

        if reasons:
            candidates.append({
                "run_id": eval_record.run_id,
                "symbol": eval_record.symbol,
                "provider": eval_record.provider,
                "title": title,
                "url": item.get("url", ""),
                "summary": item.get("summary", ""),
                "published_at": item.get("publish_time", ""),
                "relevance": round(relevance, 3),
                "quality_tier": quality_tier,
                "reasons": reasons,
                "review_label": None,
                "reviewer_notes": None,
            })

    return candidates


class NewsQualityMonitor:
    """Long-running web news quality monitor.

    Reuses WebNewsProvider and news_quality functions to evaluate
    per-source stability for a set of target symbols.
    """

    def __init__(
        self,
        *,
        targets: list[dict],
        sources: list[str] | None = None,
        thresholds: MonitorThresholds | None = None,
        lookback_days: int = 14,
        limit: int = 10,
        timeout_seconds: int = 8,
        max_seconds: int = 12,
        output_dir: Path | None = None,
        provider_factory: Any = None,
    ) -> None:
        self.targets = targets
        self.sources = sources or DEFAULT_SOURCES
        self.thresholds = thresholds or MonitorThresholds()
        self.lookback_days = lookback_days
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.max_seconds = max_seconds
        self.output_dir = output_dir or Path("storage/artifacts/web_news_quality/live")
        self.provider_factory = provider_factory

    def run(self) -> dict:
        """Execute a single monitoring run and return the report."""
        run_id = uuid.uuid4().hex[:12]
        started_at = _now_iso()
        evaluations: list[ProviderEvaluation] = []
        review_candidates: list[dict] = []

        for target in self.targets:
            symbol_info = {
                "normalized_symbol": target["normalized_symbol"],
                "plain_code": target["plain_code"],
                "name": target["name"],
                "asset_type": target.get("asset_type", "stock"),
            }
            for source in self.sources:
                eval_record = self._evaluate_single_source(
                    run_id=run_id,
                    symbol_info=symbol_info,
                    source=source,
                )
                evaluations.append(eval_record)

                # Detect manual review candidates
                candidates = _detect_manual_review_candidates(eval_record, symbol_info)
                review_candidates.extend(candidates)

        completed_at = _now_iso()

        # Build provider health
        provider_health = self._aggregate_provider_health(evaluations)

        # Build per-provider status
        per_provider = {}
        for source, health in provider_health.items():
            status = _classify_provider_status(health, self.thresholds)
            entry = health.to_dict()
            entry["status"] = status
            per_provider[source] = entry

        # Build per-symbol summary
        per_symbol = self._aggregate_per_symbol(evaluations)

        # Build overall summary
        overall = self._aggregate_overall(evaluations)

        report = {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "targets_count": len(self.targets),
            "sources": self.sources,
            "thresholds": self.thresholds.to_dict(),
            "overall": overall,
            "per_provider": per_provider,
            "per_symbol": per_symbol,
            "evaluations": [e.to_dict() for e in evaluations],
        }

        return report

    def run_and_save(self) -> dict:
        """Run monitoring and save all artifacts."""
        report = self.run()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        evaluations_data = report["evaluations"]

        # latest.json
        latest_path = self.output_dir / "latest.json"
        latest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # latest.md
        md_path = self.output_dir / "latest.md"
        md_path.write_text(
            self._build_markdown_report(report),
            encoding="utf-8",
        )

        # history.jsonl
        history_path = self.output_dir / "history.jsonl"
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

        # provider_health.json
        health_path = self.output_dir / "provider_health.json"
        health_data = {
            "updated_at": report["completed_at"],
            "providers": report["per_provider"],
        }
        health_path.write_text(
            json.dumps(health_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # manual_review_candidates.jsonl
        review_path = self.output_dir / "manual_review_candidates.jsonl"
        candidates = self._collect_review_candidates(evaluations_data)
        with review_path.open("a", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

        return report

    def evaluate_fixture(self, fixture_path: Path) -> dict:
        """Run in offline mode using fixture data (no real network)."""
        fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        samples = fixture_data.get("samples", [])

        run_id = uuid.uuid4().hex[:12]
        started_at = _now_iso()
        evaluations: list[ProviderEvaluation] = []
        review_candidates: list[dict] = []

        for sample in samples:
            sample_id = sample["id"]
            symbol_info = sample["symbol_info"]
            items = sample.get("items", [])
            provider_metadata = sample.get("provider_metadata", {"success": True})

            result = {"data": items, "metadata": provider_metadata}
            eval_result = evaluate_news_provider_result(result, symbol_info)

            # Classify each item for review candidates
            deduped = dedupe_news_items(items) if items else []
            classified = [classify_news_quality(item, symbol_info) for item in deduped]
            classified_with_details = []
            for i, item in enumerate(deduped):
                detail = {**item}
                if i < len(classified):
                    detail.update(classified[i])
                classified_with_details.append(detail)

            total = len(items)
            deduped_total = eval_result.get("deduped_total", 0)
            relevant = eval_result.get("relevant_count", 0)
            low_quality = eval_result.get("low_quality_count", 0)
            success = eval_result.get("success", provider_metadata.get("success", True))
            error_type = eval_result.get("error_type") if not success else None
            error_msg = eval_result.get("error") if not success else None

            duplicate_rate = (total - deduped_total) / total if total > 0 else 0.0
            relevance_rate = relevant / deduped_total if deduped_total > 0 else 0.0
            low_quality_rate = low_quality / deduped_total if deduped_total > 0 else 0.0
            is_timeout = error_type == "provider_unavailable" and "timeout" in (error_msg or "").lower()

            eval_record = ProviderEvaluation(
                run_id=run_id,
                timestamp=_now_iso(),
                symbol=symbol_info.get("normalized_symbol", sample_id),
                symbol_name=symbol_info.get("name", ""),
                provider=sample_id,
                dataset="fixture",
                success=success,
                error_type=error_type,
                error_message=error_msg,
                latency_seconds=0.0,
                total_items=total,
                deduped_total=deduped_total,
                relevant_count=relevant,
                low_quality_count=low_quality,
                duplicate_rate=duplicate_rate,
                relevance_rate=relevance_rate,
                low_quality_rate=low_quality_rate,
                is_timeout=is_timeout,
                is_empty=success and deduped_total == 0,
                source_counts=eval_result.get("source_counts", {}),
                warnings=eval_result.get("warnings", []),
                classified_items=classified_with_details,
            )
            evaluations.append(eval_record)

            candidates = _detect_manual_review_candidates(eval_record, symbol_info)
            review_candidates.extend(candidates)

        completed_at = _now_iso()

        provider_health = self._aggregate_provider_health(evaluations)
        per_provider = {}
        for source, health in provider_health.items():
            status = _classify_provider_status(health, self.thresholds)
            entry = health.to_dict()
            entry["status"] = status
            per_provider[source] = entry

        per_symbol = self._aggregate_per_symbol(evaluations)
        overall = self._aggregate_overall(evaluations)

        report = {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "targets_count": len(samples),
            "sources": ["offline_fixture"],
            "thresholds": self.thresholds.to_dict(),
            "overall": overall,
            "per_provider": per_provider,
            "per_symbol": per_symbol,
            "evaluations": [e.to_dict() for e in evaluations],
        }

        return report

    def _evaluate_single_source(
        self,
        *,
        run_id: str,
        symbol_info: dict,
        source: str,
    ) -> ProviderEvaluation:
        """Evaluate a single source for a single symbol."""
        started = perf_counter()
        success = False
        error_type = None
        error_message = None
        items: list[dict] = []
        dataset = ""
        is_timeout = False

        try:
            provider = self._create_provider(source)
            result = provider.fetch_events(symbol_info, lookback_days=self.lookback_days)
            success = result.metadata.success
            error_type = result.metadata.error_type if not success else None
            error_message = result.metadata.error if not success else None
            items = result.data if isinstance(result.data, list) else []
            dataset = result.dataset or ""
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)

        latency = perf_counter() - started
        is_timeout = "timeout" in (error_message or "").lower() and error_type == "provider_unavailable"

        # Evaluate quality
        total = len(items)
        deduped = dedupe_news_items(items)
        deduped_total = len(deduped)
        classified = [classify_news_quality(item, symbol_info) for item in deduped]
        relevant = sum(1 for c in classified if c["is_relevant"])
        low_quality = sum(1 for c in classified if c["quality_tier"] == "low")

        duplicate_rate = (total - deduped_total) / total if total > 0 else 0.0
        relevance_rate = relevant / deduped_total if deduped_total > 0 else 0.0
        low_quality_rate = low_quality / deduped_total if deduped_total > 0 else 0.0

        source_counts: dict[str, int] = {}
        for item in deduped:
            src = item.get("query_provider", item.get("source", "unknown"))
            source_counts[str(src)] = source_counts.get(str(src), 0) + 1

        warnings = []
        if not success:
            warnings.append(f"provider failed: {error_type or 'unknown'}")
        if deduped_total == 0 and success:
            warnings.append("empty result after dedup")

        classified_with_details = []
        for i, item in enumerate(deduped):
            detail = {**item}
            if i < len(classified):
                detail.update(classified[i])
            classified_with_details.append(detail)

        return ProviderEvaluation(
            run_id=run_id,
            timestamp=_now_iso(),
            symbol=symbol_info.get("normalized_symbol", ""),
            symbol_name=symbol_info.get("name", ""),
            provider=source,
            dataset=dataset,
            success=success,
            error_type=error_type,
            error_message=error_message,
            latency_seconds=latency,
            total_items=total,
            deduped_total=deduped_total,
            relevant_count=relevant,
            low_quality_count=low_quality,
            duplicate_rate=duplicate_rate,
            relevance_rate=relevance_rate,
            low_quality_rate=low_quality_rate,
            is_timeout=is_timeout,
            is_empty=success and deduped_total == 0,
            source_counts=source_counts,
            warnings=warnings,
            classified_items=classified_with_details,
        )

    def _create_provider(self, source: str) -> WebNewsProvider:
        if self.provider_factory:
            return self.provider_factory(source)
        return WebNewsProvider(
            enabled=True,
            force_no_proxy=True,
            source_order=[source],
            limit=self.limit,
            timeout_seconds=self.timeout_seconds,
            max_seconds=self.max_seconds,
        )

    def _aggregate_provider_health(
        self, evaluations: list[ProviderEvaluation],
    ) -> dict[str, ProviderHealth]:
        health_map: dict[str, ProviderHealth] = {}
        for ev in evaluations:
            if ev.provider not in health_map:
                health_map[ev.provider] = ProviderHealth(source=ev.provider)
            h = health_map[ev.provider]
            h.attempts += 1
            if ev.success:
                h.successes += 1
                h.last_success_at = ev.timestamp
            if ev.is_timeout:
                h.timeouts += 1
            if ev.is_empty:
                h.empty_results += 1
            h.total_latency += ev.latency_seconds
            h.total_relevant += ev.relevant_count
            h.total_deduped += ev.deduped_total
            h.total_low_quality += ev.low_quality_count
            if not ev.success:
                h.last_error_type = ev.error_type
        return health_map

    def _aggregate_per_symbol(
        self, evaluations: list[ProviderEvaluation],
    ) -> dict[str, dict]:
        symbol_map: dict[str, dict] = {}
        for ev in evaluations:
            key = ev.symbol
            if key not in symbol_map:
                symbol_map[key] = {
                    "symbol": ev.symbol,
                    "name": ev.symbol_name,
                    "attempts": 0,
                    "successes": 0,
                    "total_items": 0,
                    "total_deduped": 0,
                    "total_relevant": 0,
                    "total_low_quality": 0,
                    "sources": [],
                }
            s = symbol_map[key]
            s["attempts"] += 1
            if ev.success:
                s["successes"] += 1
            s["total_items"] += ev.total_items
            s["total_deduped"] += ev.deduped_total
            s["total_relevant"] += ev.relevant_count
            s["total_low_quality"] += ev.low_quality_count
            s["sources"].append(ev.provider)

        for _key, s in symbol_map.items():
            s["success_rate"] = round(s["successes"] / s["attempts"], 4) if s["attempts"] > 0 else 0.0
            s["relevance_rate"] = round(s["total_relevant"] / s["total_deduped"], 4) if s["total_deduped"] > 0 else 0.0

        return symbol_map

    def _aggregate_overall(
        self, evaluations: list[ProviderEvaluation],
    ) -> dict:
        total_attempts = len(evaluations)
        successes = sum(1 for e in evaluations if e.success)
        timeouts = sum(1 for e in evaluations if e.is_timeout)
        empty_results = sum(1 for e in evaluations if e.is_empty)
        total_items = sum(e.total_items for e in evaluations)
        total_deduped = sum(e.deduped_total for e in evaluations)
        total_relevant = sum(e.relevant_count for e in evaluations)
        total_low_quality = sum(e.low_quality_count for e in evaluations)
        total_latency = sum(e.latency_seconds for e in evaluations)

        return {
            "total_attempts": total_attempts,
            "success_rate": round(successes / total_attempts, 4) if total_attempts > 0 else 0.0,
            "timeout_rate": round(timeouts / total_attempts, 4) if total_attempts > 0 else 0.0,
            "empty_rate": round(empty_results / total_attempts, 4) if total_attempts > 0 else 0.0,
            "total_items": total_items,
            "total_deduped": total_deduped,
            "total_relevant": total_relevant,
            "total_low_quality": total_low_quality,
            "relevance_rate": round(total_relevant / total_deduped, 4) if total_deduped > 0 else 0.0,
            "low_quality_rate": round(total_low_quality / total_deduped, 4) if total_deduped > 0 else 0.0,
            "avg_latency_seconds": round(total_latency / total_attempts, 3) if total_attempts > 0 else 0.0,
            "total_warnings": sum(len(e.warnings) for e in evaluations),
        }

    def _collect_review_candidates(self, evaluations: list[dict]) -> list[dict]:
        candidates = []
        for ev in evaluations:
            symbol_info = {
                "name": ev.get("symbol_name", ""),
                "plain_code": ev.get("symbol", "").split(".")[0] if ev.get("symbol") else "",
            }
            # Reconstruct a ProviderEvaluation-like object for candidate detection
            for item_detail in ev.get("classified_items", []):
                reasons = []
                relevance = item_detail.get("relevance", 0.0)
                quality_tier = item_detail.get("quality_tier", "unknown")
                title = item_detail.get("title", "")
                company_name = (symbol_info.get("name") or "").lower()
                plain_code = (symbol_info.get("plain_code") or "").lower()
                text = f"{title} {item_detail.get('summary', '')}".lower()

                if quality_tier == "high" and relevance < 0.5:
                    reasons.append("low_relevance_but_high_tier")
                if relevance >= 0.4 and quality_tier == "low":
                    reasons.append("high_relevance_but_low_quality")
                if item_detail.get("query_provider") and company_name not in text and plain_code not in text:
                    reasons.append("no_company_match_in_text")

                if reasons:
                    candidates.append({
                        "run_id": ev.get("run_id", ""),
                        "symbol": ev.get("symbol", ""),
                        "provider": ev.get("provider", ""),
                        "title": title,
                        "url": item_detail.get("url", ""),
                        "summary": item_detail.get("summary", ""),
                        "published_at": item_detail.get("publish_time", ""),
                        "relevance": round(relevance, 3),
                        "quality_tier": quality_tier,
                        "reasons": reasons,
                        "review_label": None,
                        "reviewer_notes": None,
                    })
        return candidates

    def _build_markdown_report(self, report: dict) -> str:
        lines = ["# 网页新闻/舆情长期质量监控报告", ""]
        lines.append(f"**Run ID**: {report['run_id']}")
        lines.append(f"**开始时间**: {report['started_at']}")
        lines.append(f"**完成时间**: {report['completed_at']}")
        lines.append(f"**标的数量**: {report['targets_count']}")
        lines.append(f"**监控来源**: {', '.join(report['sources'])}")
        lines.append("")

        overall = report["overall"]
        lines.append("## 总体概况")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 成功率 | {overall['success_rate']:.1%} |")
        lines.append(f"| 超时率 | {overall['timeout_rate']:.1%} |")
        lines.append(f"| 空结果率 | {overall['empty_rate']:.1%} |")
        lines.append(f"| 总条目 | {overall['total_items']} |")
        lines.append(f"| 去重后条目 | {overall['total_deduped']} |")
        lines.append(f"| 相关性率 | {overall['relevance_rate']:.1%} |")
        lines.append(f"| 低质量率 | {overall['low_quality_rate']:.1%} |")
        lines.append(f"| 平均延迟 | {overall['avg_latency_seconds']:.2f}s |")
        lines.append(f"| 总警告数 | {overall['total_warnings']} |")
        lines.append("")

        lines.append("## Provider Health")
        lines.append("")
        lines.append("| 来源 | 状态 | 成功率 | 超时率 | 空结果率 | 平均延迟 | 相关性率 | 低质量率 | 尝试次数 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for source, info in report["per_provider"].items():
            status_icon = {"ok": "ok", "warn": "warn", "fail": "fail"}.get(info["status"], "?")
            lines.append(
                f"| {source} | {status_icon} | {info['success_rate']:.1%} | "
                f"{info['timeout_rate']:.1%} | {info['empty_rate']:.1%} | "
                f"{info['avg_latency_seconds']:.2f}s | {info['avg_relevance_rate']:.1%} | "
                f"{info['avg_low_quality_rate']:.1%} | {info['attempts']} |"
            )
        lines.append("")

        lines.append("## Symbol 维度")
        lines.append("")
        lines.append("| 标的 | 名称 | 成功率 | 相关条目 | 去重后总数 | 相关率 | 尝试来源 |")
        lines.append("|---|---|---|---|---|---|---|")
        for _sym, info in report["per_symbol"].items():
            lines.append(
                f"| {info['symbol']} | {info['name']} | {info['success_rate']:.1%} | "
                f"{info['total_relevant']} | {info['total_deduped']} | "
                f"{info['relevance_rate']:.1%} | {', '.join(set(info['sources']))} |"
            )
        lines.append("")

        # Warnings
        all_warnings = []
        for ev in report["evaluations"]:
            for w in ev.get("warnings", []):
                all_warnings.append(f"[{ev['provider']}/{ev['symbol']}] {w}")
        if all_warnings:
            lines.append("## Warnings")
            lines.append("")
            for w in all_warnings[:20]:
                lines.append(f"- {w}")
            if len(all_warnings) > 20:
                lines.append(f"- ... 共 {len(all_warnings)} 条警告")
            lines.append("")

        lines.append("## 人工抽样候选")
        lines.append("")
        lines.append("详见 `manual_review_candidates.jsonl`，包含以下类型：")
        lines.append("- 低相关但被判 high tier")
        lines.append("- 高相关但低质量")
        lines.append("- provider 返回但无公司名/代码命中")
        lines.append("")

        return "\n".join(lines)
