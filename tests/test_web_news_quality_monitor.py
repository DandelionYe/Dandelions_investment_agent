"""网页新闻/舆情长期质量监控离线测试。

覆盖：
- 单 provider 成功/timeout/failure 聚合
- 多 provider 部分失败
- duplicate_rate/relevance_rate/low_quality_rate 计算
- history.jsonl 追加
- latest.json/latest.md/provider_health.json/manual_review_candidates.jsonl 输出
- --fail-on-threshold 行为
- manual_review_candidates schema 稳定
- provider 失败不抛出到主流程
- offline-fixture 模式可运行
"""

import json
import shutil
import tempfile
from pathlib import Path

from services.data.news_quality_monitor import (
    MonitorThresholds,
    NewsQualityMonitor,
    ProviderEvaluation,
    ProviderHealth,
    _classify_provider_status,
    _detect_manual_review_candidates,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "web_news_quality_samples.json"


class TestProviderHealth:

    def test_empty_health(self):
        h = ProviderHealth(source="test")
        assert h.success_rate == 0.0
        assert h.timeout_rate == 0.0
        assert h.empty_rate == 0.0
        assert h.avg_latency_seconds == 0.0
        assert h.avg_relevance_rate == 0.0
        assert h.avg_low_quality_rate == 0.0

    def test_health_with_data(self):
        h = ProviderHealth(source="test", attempts=10, successes=7, timeouts=2, empty_results=1)
        h.total_latency = 5.0
        h.total_relevant = 15
        h.total_deduped = 30
        h.total_low_quality = 5
        assert h.success_rate == 0.7
        assert h.timeout_rate == 0.2
        assert h.empty_rate == 0.1
        assert h.avg_latency_seconds == 0.5
        assert h.avg_relevance_rate == 0.5
        assert abs(h.avg_low_quality_rate - 5 / 30) < 0.001

    def test_health_to_dict(self):
        h = ProviderHealth(source="eastmoney", attempts=5, successes=4)
        d = h.to_dict()
        assert d["source"] == "eastmoney"
        assert d["attempts"] == 5
        assert d["success_rate"] == 0.8
        assert "timeout_rate" in d
        assert "avg_latency_seconds" in d


class TestClassifyProviderStatus:

    def test_ok(self):
        h = ProviderHealth(source="test", attempts=10, successes=8)
        h.total_relevant = 5
        h.total_deduped = 10
        h.total_low_quality = 2
        assert _classify_provider_status(h, MonitorThresholds()) == "ok"

    def test_fail_low_success(self):
        h = ProviderHealth(source="test", attempts=10, successes=2)
        assert _classify_provider_status(h, MonitorThresholds()) == "fail"

    def test_fail_high_timeout(self):
        h = ProviderHealth(source="test", attempts=10, successes=8, timeouts=6)
        assert _classify_provider_status(h, MonitorThresholds()) == "fail"

    def test_warn_high_empty(self):
        h = ProviderHealth(source="test", attempts=10, successes=10, empty_results=8)
        assert _classify_provider_status(h, MonitorThresholds()) == "warn"

    def test_warn_low_relevance(self):
        h = ProviderHealth(source="test", attempts=10, successes=10)
        h.total_relevant = 1
        h.total_deduped = 10
        assert _classify_provider_status(h, MonitorThresholds()) == "warn"

    def test_warn_high_low_quality(self):
        h = ProviderHealth(source="test", attempts=10, successes=10)
        h.total_relevant = 5
        h.total_deduped = 10
        h.total_low_quality = 8
        assert _classify_provider_status(h, MonitorThresholds()) == "warn"

    def test_warn_zero_attempts(self):
        h = ProviderHealth(source="test", attempts=0)
        assert _classify_provider_status(h, MonitorThresholds()) == "warn"


class TestManualReviewCandidates:

    def _make_eval(self, classified_items, run_id="test", symbol="600519.SH", symbol_name="贵州茅台", provider="eastmoney"):
        return ProviderEvaluation(
            run_id=run_id,
            timestamp="2026-05-26T10:00:00",
            symbol=symbol,
            symbol_name=symbol_name,
            provider=provider,
            dataset="test",
            success=True,
            error_type=None,
            error_message=None,
            latency_seconds=1.0,
            total_items=len(classified_items),
            deduped_total=len(classified_items),
            relevant_count=0,
            low_quality_count=0,
            duplicate_rate=0.0,
            relevance_rate=0.0,
            low_quality_rate=0.0,
            is_timeout=False,
            is_empty=False,
            source_counts={},
            warnings=[],
            classified_items=classified_items,
        )

    def test_no_candidates_for_clean_items(self):
        items = [
            {
                "title": "贵州茅台一季度净利润增长15%",
                "url": "https://example.com/1",
                "summary": "贵州茅台发布公告",
                "query_provider": "eastmoney",
                "relevance": 0.7,
                "quality_tier": "high",
            }
        ]
        symbol_info = {"name": "贵州茅台", "plain_code": "600519"}
        eval_record = self._make_eval(items)
        candidates = _detect_manual_review_candidates(eval_record, symbol_info)
        assert len(candidates) == 0

    def test_low_relevance_high_tier(self):
        items = [
            {
                "title": "某公司新闻",
                "url": "https://example.com/1",
                "summary": "某公司发布公告",
                "query_provider": "eastmoney",
                "relevance": 0.3,
                "quality_tier": "high",
            }
        ]
        symbol_info = {"name": "贵州茅台", "plain_code": "600519"}
        eval_record = self._make_eval(items)
        candidates = _detect_manual_review_candidates(eval_record, symbol_info)
        assert len(candidates) == 1
        assert "low_relevance_but_high_tier" in candidates[0]["reasons"]

    def test_high_relevance_low_quality(self):
        items = [
            {
                "title": "贵州茅台福利大放送",
                "url": "https://example.com/1",
                "summary": "免费领取",
                "query_provider": "eastmoney",
                "relevance": 0.5,
                "quality_tier": "low",
            }
        ]
        symbol_info = {"name": "贵州茅台", "plain_code": "600519"}
        eval_record = self._make_eval(items)
        candidates = _detect_manual_review_candidates(eval_record, symbol_info)
        assert len(candidates) == 1
        assert "high_relevance_but_low_quality" in candidates[0]["reasons"]

    def test_no_company_match(self):
        items = [
            {
                "title": "某不相关公司新闻",
                "url": "https://example.com/1",
                "summary": "与标的无关的内容",
                "query_provider": "eastmoney",
                "relevance": 0.2,
                "quality_tier": "medium",
            }
        ]
        symbol_info = {"name": "贵州茅台", "plain_code": "600519"}
        eval_record = self._make_eval(items)
        candidates = _detect_manual_review_candidates(eval_record, symbol_info)
        assert len(candidates) == 1
        assert "no_company_match_in_text" in candidates[0]["reasons"]

    def test_candidate_schema_stable(self):
        items = [
            {
                "title": "某公司新闻",
                "url": "https://example.com/1",
                "summary": "摘要",
                "publish_time": "2026-05-26",
                "query_provider": "eastmoney",
                "relevance": 0.3,
                "quality_tier": "high",
            }
        ]
        symbol_info = {"name": "贵州茅台", "plain_code": "600519"}
        eval_record = self._make_eval(items)
        candidates = _detect_manual_review_candidates(eval_record, symbol_info)
        assert len(candidates) == 1
        c = candidates[0]
        required_keys = {
            "run_id", "symbol", "provider", "title", "url", "summary",
            "published_at", "relevance", "quality_tier", "reasons",
            "review_label", "reviewer_notes",
        }
        assert required_keys == set(c.keys())
        assert c["review_label"] is None
        assert c["reviewer_notes"] is None


class TestNewsQualityMonitorFixture:

    def test_evaluate_fixture(self):
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=MonitorThresholds(),
        )
        report = monitor.evaluate_fixture(FIXTURE_PATH)

        assert "run_id" in report
        assert "started_at" in report
        assert "completed_at" in report
        assert report["targets_count"] == 7
        assert "overall" in report
        assert "per_provider" in report
        assert "per_symbol" in report
        assert "evaluations" in report
        assert len(report["evaluations"]) == 7

    def test_fixture_overall_metrics(self):
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=MonitorThresholds(),
        )
        report = monitor.evaluate_fixture(FIXTURE_PATH)
        overall = report["overall"]

        assert overall["total_attempts"] == 7
        assert overall["success_rate"] < 1.0  # Some fixtures are failures
        assert overall["total_items"] > 0
        assert overall["total_deduped"] > 0
        assert "relevance_rate" in overall
        assert "low_quality_rate" in overall
        assert "avg_latency_seconds" in overall

    def test_fixture_provider_health(self):
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=MonitorThresholds(),
        )
        report = monitor.evaluate_fixture(FIXTURE_PATH)

        for _provider, info in report["per_provider"].items():
            assert "status" in info
            assert info["status"] in ("ok", "warn", "fail")
            assert "success_rate" in info
            assert "timeout_rate" in info

    def test_fixture_failure_does_not_raise(self):
        """Provider failures in fixture data should not raise."""
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=MonitorThresholds(),
        )
        # This should complete without raising, even though some samples are failures
        report = monitor.evaluate_fixture(FIXTURE_PATH)
        assert report["overall"]["total_attempts"] == 7


class TestNewsQualityMonitorWithMockProvider:

    def _make_mock_provider_factory(self, results: dict):
        """Create a provider factory that returns canned results per source."""
        from services.data.provider_contracts import ProviderMetadata, ProviderResult

        def factory(source: str):
            class MockProvider:
                def __init__(self):
                    self.enabled = True

                def fetch_events(self, symbol_info, lookback_days=14):
                    result = results.get(source, {"data": [], "success": False, "error": "unknown source"})
                    return ProviderResult(
                        provider="web_news",
                        dataset=f"mock_{source}",
                        symbol=symbol_info.get("normalized_symbol", ""),
                        as_of="2026-05-26",
                        data=result.get("data", []),
                        raw={},
                        metadata=ProviderMetadata(
                            success=result.get("success", False),
                            error=result.get("error"),
                            error_type=result.get("error_type"),
                        ),
                    )

            return MockProvider()

        return factory

    def test_single_provider_success(self):
        factory = self._make_mock_provider_factory({
            "eastmoney": {
                "data": [
                    {"title": "贵州茅台一季度净利润增长", "url": "https://a.com/1", "query_provider": "eastmoney"},
                    {"title": "贵州茅台渠道价格分析", "url": "https://a.com/2", "query_provider": "eastmoney"},
                ],
                "success": True,
            },
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        assert report["overall"]["total_attempts"] == 1
        assert report["overall"]["success_rate"] == 1.0
        assert report["overall"]["total_items"] == 2
        assert report["per_provider"]["eastmoney"]["status"] == "ok"

    def test_single_provider_timeout(self):
        factory = self._make_mock_provider_factory({
            "sina": {
                "data": [],
                "success": False,
                "error": "Request timeout after 8s",
                "error_type": "provider_unavailable",
            },
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["sina"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        assert report["overall"]["total_attempts"] == 1
        assert report["overall"]["success_rate"] == 0.0
        assert report["per_provider"]["sina"]["status"] == "fail"

    def test_multi_provider_partial_failure(self):
        factory = self._make_mock_provider_factory({
            "eastmoney": {
                "data": [
                    {"title": "贵州茅台新闻", "url": "https://a.com/1", "query_provider": "eastmoney"},
                ],
                "success": True,
            },
            "sina": {
                "data": [],
                "success": False,
                "error": "Connection refused",
                "error_type": "provider_unavailable",
            },
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney", "sina"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        assert report["overall"]["total_attempts"] == 2
        assert report["overall"]["success_rate"] == 0.5
        assert report["per_provider"]["eastmoney"]["status"] == "ok"
        assert report["per_provider"]["sina"]["status"] == "fail"

    def test_all_providers_failure(self):
        factory = self._make_mock_provider_factory({
            "eastmoney": {"data": [], "success": False, "error": "down", "error_type": "provider_unavailable"},
            "sina": {"data": [], "success": False, "error": "down", "error_type": "provider_unavailable"},
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney", "sina"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        assert report["overall"]["success_rate"] == 0.0
        assert report["per_provider"]["eastmoney"]["status"] == "fail"
        assert report["per_provider"]["sina"]["status"] == "fail"
        # Report should still be generated
        assert "evaluations" in report
        assert len(report["evaluations"]) == 2

    def test_duplicate_rate_calculation(self):
        factory = self._make_mock_provider_factory({
            "eastmoney": {
                "data": [
                    {"title": "茅台新闻A", "url": "https://a.com/1", "query_provider": "eastmoney"},
                    {"title": "茅台新闻A", "url": "https://a.com/2", "query_provider": "eastmoney"},
                    {"title": "茅台新闻B", "url": "https://b.com/1", "query_provider": "eastmoney"},
                ],
                "success": True,
            },
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        ev = report["evaluations"][0]
        assert ev["total_items"] == 3
        assert ev["deduped_total"] == 2
        assert abs(ev["duplicate_rate"] - 1 / 3) < 0.001

    def test_relevance_rate_calculation(self):
        factory = self._make_mock_provider_factory({
            "eastmoney": {
                "data": [
                    {"title": "贵州茅台一季度净利润增长", "url": "https://a.com/1", "query_provider": "eastmoney"},
                    {"title": "今日A股大盘大涨", "url": "https://a.com/2", "query_provider": "eastmoney"},
                ],
                "success": True,
            },
        })
        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney"],
            thresholds=MonitorThresholds(),
            provider_factory=factory,
        )
        report = monitor.run()

        ev = report["evaluations"][0]
        assert ev["deduped_total"] == 2
        # First item should be relevant, second not
        assert ev["relevant_count"] >= 1
        assert ev["relevance_rate"] > 0.0

    def test_provider_failure_does_not_raise_to_main_flow(self):
        """Exception in provider should be caught, not propagated."""

        def broken_factory(source):
            class BrokenProvider:
                enabled = True

                def fetch_events(self, symbol_info, lookback_days=14):
                    raise RuntimeError("network exploded")

            return BrokenProvider()

        targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney"],
            thresholds=MonitorThresholds(),
            provider_factory=broken_factory,
        )
        report = monitor.run()

        assert report["overall"]["total_attempts"] == 1
        assert report["overall"]["success_rate"] == 0.0
        assert report["evaluations"][0]["error_type"] == "RuntimeError"


class TestMonitorThresholds:

    def test_default_thresholds(self):
        t = MonitorThresholds()
        assert t.min_success_rate == 0.50
        assert t.max_timeout_rate == 0.50
        assert t.max_empty_rate == 0.70
        assert t.min_relevance_rate == 0.20
        assert t.max_low_quality_rate == 0.60
        assert t.max_avg_latency_seconds == 15.0

    def test_from_dict(self):
        t = MonitorThresholds.from_dict({"min_success_rate": 0.8, "max_timeout_rate": 0.3})
        assert t.min_success_rate == 0.8
        assert t.max_timeout_rate == 0.3
        assert t.max_empty_rate == 0.70  # default preserved

    def test_to_dict(self):
        t = MonitorThresholds()
        d = t.to_dict()
        assert len(d) == 6
        assert "min_success_rate" in d


class TestMonitorArtifacts:

    def test_artifacts_written(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="news_monitor_test_"))
        try:
            factory = self._make_simple_factory()
            targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
            output_dir = tmp_dir / "artifacts"
            monitor = NewsQualityMonitor(
                targets=targets,
                sources=["eastmoney"],
                thresholds=MonitorThresholds(),
                output_dir=output_dir,
                provider_factory=factory,
            )
            report = monitor.run_and_save()

            assert (output_dir / "latest.json").exists()
            assert (output_dir / "latest.md").exists()
            assert (output_dir / "history.jsonl").exists()
            assert (output_dir / "provider_health.json").exists()
            assert (output_dir / "manual_review_candidates.jsonl").exists()

            latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
            assert latest["run_id"] == report["run_id"]

            md = (output_dir / "latest.md").read_text(encoding="utf-8")
            assert "监控报告" in md
            assert "Provider Health" in md
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_history_jsonl_append(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="news_monitor_test_"))
        try:
            factory = self._make_simple_factory()
            targets = [{"normalized_symbol": "600519.SH", "plain_code": "600519", "name": "贵州茅台", "asset_type": "stock"}]
            output_dir = tmp_dir / "artifacts"
            monitor = NewsQualityMonitor(
                targets=targets,
                sources=["eastmoney"],
                thresholds=MonitorThresholds(),
                output_dir=output_dir,
                provider_factory=factory,
            )

            monitor.run_and_save()
            monitor.run_and_save()

            history_path = output_dir / "history.jsonl"
            lines = history_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2

            for line in lines:
                entry = json.loads(line)
                assert "run_id" in entry
                assert "overall" in entry
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _make_simple_factory(self):
        from services.data.provider_contracts import ProviderMetadata, ProviderResult

        def factory(source):
            class MockProvider:
                enabled = True

                def fetch_events(self, symbol_info, lookback_days=14):
                    return ProviderResult(
                        provider="web_news",
                        dataset="mock",
                        symbol=symbol_info.get("normalized_symbol", ""),
                        as_of="2026-05-26",
                        data=[
                            {"title": "贵州茅台新闻", "url": "https://a.com/1", "query_provider": "eastmoney"},
                        ],
                        raw={},
                        metadata=ProviderMetadata(success=True),
                    )

            return MockProvider()

        return factory


class TestOfflineFixtureMode:

    def test_offline_fixture_via_evaluate(self):
        """The offline fixture path should work through evaluate_fixture."""
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=MonitorThresholds(),
        )
        report = monitor.evaluate_fixture(FIXTURE_PATH)

        assert report["overall"]["total_attempts"] == 7
        assert "per_provider" in report
        assert "per_symbol" in report

    def test_fail_on_threshold_with_fixture(self):
        """Verify threshold checking works with fixture data."""
        strict_thresholds = MonitorThresholds(min_success_rate=0.99)
        monitor = NewsQualityMonitor(
            targets=[],
            sources=["offline_fixture"],
            thresholds=strict_thresholds,
        )
        report = monitor.evaluate_fixture(FIXTURE_PATH)

        # Fixture has failures, so strict threshold should fail
        overall = report["overall"]
        assert overall["success_rate"] < 0.99
