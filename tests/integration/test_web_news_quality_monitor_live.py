"""网页新闻/舆情质量监控真实网络 smoke 测试。

默认跳过，只有设置 RUN_WEB_NEWS_NETWORK=1 时才运行。
至少对 1-2 个核心标的运行真实 provider，timeout 设置保守。
不要求每个 provider 都成功，只要求脚本能完成、生成 artifact、失败被记录。
"""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import requires_network

requires_network = pytest.mark.skipif(
    os.environ.get("RUN_WEB_NEWS_NETWORK") != "1",
    reason="RUN_WEB_NEWS_NETWORK not set",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@requires_network
class TestWebNewsQualityMonitorLive:

    def test_single_target_single_source(self, tmp_path):
        """Run monitor on 1 target with 1 source, verify artifacts generated."""
        from services.data.news_quality_monitor import (
            MonitorThresholds,
            NewsQualityMonitor,
        )

        targets = [
            {
                "normalized_symbol": "600519.SH",
                "plain_code": "600519",
                "name": "贵州茅台",
                "asset_type": "stock",
            }
        ]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney"],
            thresholds=MonitorThresholds(),
            lookback_days=7,
            limit=5,
            timeout_seconds=8,
            max_seconds=12,
            output_dir=tmp_path / "live",
        )
        report = monitor.run_and_save()

        assert "run_id" in report
        assert report["overall"]["total_attempts"] == 1
        assert (tmp_path / "live" / "latest.json").exists()
        assert (tmp_path / "live" / "latest.md").exists()
        assert (tmp_path / "live" / "history.jsonl").exists()
        assert (tmp_path / "live" / "provider_health.json").exists()

    def test_two_targets_two_sources(self, tmp_path):
        """Run monitor on 2 targets with 2 sources, verify no crash on partial failure."""
        from services.data.news_quality_monitor import (
            MonitorThresholds,
            NewsQualityMonitor,
        )

        targets = [
            {
                "normalized_symbol": "600519.SH",
                "plain_code": "600519",
                "name": "贵州茅台",
                "asset_type": "stock",
            },
            {
                "normalized_symbol": "000001.SZ",
                "plain_code": "000001",
                "name": "平安银行",
                "asset_type": "stock",
            },
        ]
        monitor = NewsQualityMonitor(
            targets=targets,
            sources=["eastmoney", "sina"],
            thresholds=MonitorThresholds(),
            lookback_days=7,
            limit=5,
            timeout_seconds=8,
            max_seconds=15,
            output_dir=tmp_path / "live",
        )
        report = monitor.run_and_save()

        assert report["overall"]["total_attempts"] == 4
        assert report["targets_count"] == 2
        # At least some should succeed (or all may fail in bad network)
        # The key assertion is that it completes without raising
        assert "per_provider" in report
        assert "per_symbol" in report

    def test_script_runs_with_artifacts(self, tmp_path):
        """Verify the CLI script can run and produce artifacts."""
        import subprocess

        output_dir = tmp_path / "script_output"
        result = subprocess.run(
            [
                "python",
                str(PROJECT_ROOT / "scripts" / "run_web_news_quality_monitor.py"),
                "--targets",
                str(PROJECT_ROOT / "configs" / "web_news_quality_targets.json"),
                "--sources",
                "eastmoney",
                "--lookback-days",
                "7",
                "--limit",
                "3",
                "--timeout-seconds",
                "8",
                "--max-seconds",
                "12",
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )

        # Script should complete (exit 0 or 1, not crash)
        assert result.returncode in (0, 1), f"Script crashed: {result.stderr}"
        assert (output_dir / "latest.json").exists()
        assert (output_dir / "latest.md").exists()
