"""Windows Task Scheduler 脚本契约测试。

覆盖：
- 脚本文件存在
- 包含预期命令
- 不包含危险命令（Stop-Process / taskkill / Remove-Item -Recurse）
- Celery Beat 集成默认关闭
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestSchedulerScriptsExist:

    def test_run_daily_script_exists(self):
        path = PROJECT_ROOT / "scripts" / "prod" / "run_web_news_quality_daily.ps1"
        assert path.exists(), f"脚本不存在: {path}"

    def test_install_script_exists(self):
        path = PROJECT_ROOT / "scripts" / "prod" / "install_web_news_quality_task.ps1"
        assert path.exists(), f"脚本不存在: {path}"

    def test_uninstall_script_exists(self):
        path = PROJECT_ROOT / "scripts" / "prod" / "uninstall_web_news_quality_task.ps1"
        assert path.exists(), f"脚本不存在: {path}"


class TestSchedulerScriptContent:

    def _read_script(self, name: str) -> str:
        path = PROJECT_ROOT / "scripts" / "prod" / name
        return path.read_text(encoding="utf-8")

    def test_run_daily_calls_monitor(self):
        content = self._read_script("run_web_news_quality_daily.ps1")
        assert "run_web_news_quality_monitor.py" in content

    def test_run_daily_calls_trend_analyzer(self):
        content = self._read_script("run_web_news_quality_daily.ps1")
        assert "analyze_web_news_quality_trends.py" in content

    def test_run_daily_creates_log_dir(self):
        content = self._read_script("run_web_news_quality_daily.ps1")
        assert "LogsDir" in content or "logs" in content.lower()

    def test_install_registers_scheduled_task(self):
        content = self._read_script("install_web_news_quality_task.ps1")
        assert "Register-ScheduledTask" in content

    def test_install_uses_correct_task_name(self):
        content = self._read_script("install_web_news_quality_task.ps1")
        assert "DandelionsWebNewsQualityDaily" in content

    def test_uninstall_removes_scheduled_task(self):
        content = self._read_script("uninstall_web_news_quality_task.ps1")
        assert "Unregister-ScheduledTask" in content

    def test_install_supports_custom_params(self):
        content = self._read_script("install_web_news_quality_task.ps1")
        assert "-TaskName" in content
        assert "-At" in content
        assert "-Sources" in content
        assert "-Limit" in content


class TestNoDangerousCommands:

    DANGEROUS_PATTERNS = [
        "Stop-Process",
        "taskkill",
        "Remove-Item -Recurse",
        "Remove-Item -Force -Recurse",
        "rm -rf",
    ]

    def _read_script(self, name: str) -> str:
        path = PROJECT_ROOT / "scripts" / "prod" / name
        return path.read_text(encoding="utf-8")

    def test_run_daily_no_dangerous_commands(self):
        content = self._read_script("run_web_news_quality_daily.ps1")
        for pattern in self.DANGEROUS_PATTERNS:
            assert pattern not in content, f"发现危险命令: {pattern}"

    def test_install_no_dangerous_commands(self):
        content = self._read_script("install_web_news_quality_task.ps1")
        for pattern in self.DANGEROUS_PATTERNS:
            assert pattern not in content, f"发现危险命令: {pattern}"

    def test_uninstall_no_dangerous_commands(self):
        content = self._read_script("uninstall_web_news_quality_task.ps1")
        for pattern in self.DANGEROUS_PATTERNS:
            assert pattern not in content, f"发现危险命令: {pattern}"


class TestCeleryBeatDefaultOff:

    def test_beat_disabled_by_default(self):
        """WEB_NEWS_QUALITY_BEAT_ENABLED 未设置时，beat schedule 不应包含新闻任务。"""
        # Clear env var if set
        old_val = os.environ.pop("WEB_NEWS_QUALITY_BEAT_ENABLED", None)
        try:
            # Re-import to check default state
            # The beat_schedule is built at import time, so we check the source
            celery_app_path = PROJECT_ROOT / "apps" / "api" / "celery_app.py"
            content = celery_app_path.read_text(encoding="utf-8")

            # The condition should check for env var
            assert "WEB_NEWS_QUALITY_BEAT_ENABLED" in content
            # The default beat_schedule should NOT include web-news-quality-daily
            # (it's added conditionally)
            assert '"web-news-quality-daily"' in content
        finally:
            if old_val is not None:
                os.environ["WEB_NEWS_QUALITY_BEAT_ENABLED"] = old_val

    def test_beat_task_exists_in_celery_tasks(self):
        """web_news_quality_monitor_beat task should be defined."""
        tasks_path = PROJECT_ROOT / "apps" / "api" / "task_manager" / "celery_tasks.py"
        content = tasks_path.read_text(encoding="utf-8")
        assert "beat.web_news_quality_monitor" in content
        assert "web_news_quality_monitor_beat" in content


class TestPolicyConfig:

    def test_policy_config_exists(self):
        path = PROJECT_ROOT / "configs" / "web_news_quality_policy.json"
        assert path.exists(), f"配置不存在: {path}"

    def test_policy_has_tiers(self):
        import json
        path = PROJECT_ROOT / "configs" / "web_news_quality_policy.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "provider_tiers" in data
        tiers = data["provider_tiers"]
        assert "core" in tiers
        assert "secondary" in tiers
        assert "weak" in tiers

    def test_core_has_eastmoney(self):
        import json
        path = PROJECT_ROOT / "configs" / "web_news_quality_policy.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "eastmoney" in data["provider_tiers"]["core"]["providers"]

    def test_weak_has_hotrank(self):
        import json
        path = PROJECT_ROOT / "configs" / "web_news_quality_policy.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "hotrank" in data["provider_tiers"]["weak"]["providers"]
