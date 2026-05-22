"""Contract tests for production operations scripts and documentation.

These tests verify static properties of the production infrastructure files
without starting any real services, Redis, QMT, or network access.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_SCRIPTS = PROJECT_ROOT / "scripts" / "prod"
DOCS = PROJECT_ROOT / "docs"
GITIGNORE = PROJECT_ROOT / ".gitignore"


# ---------------------------------------------------------------------------
# 1. Documentation existence and content
# ---------------------------------------------------------------------------


class TestProductionOperationsDoc:
    DOC = DOCS / "production_operations.md"

    def test_doc_exists(self):
        assert self.DOC.exists(), f"Missing: {self.DOC}"

    def _read(self) -> str:
        return self.DOC.read_text(encoding="utf-8")

    def test_mentions_redis(self):
        assert "Redis" in self._read()

    def test_mentions_celery_worker(self):
        text = self._read()
        assert "Celery" in text and "worker" in text.lower()

    def test_mentions_celery_beat(self):
        text = self._read()
        assert "Beat" in text

    def test_mentions_fastapi(self):
        assert "FastAPI" in self._read()

    def test_mentions_streamlit(self):
        assert "Streamlit" in self._read()

    def test_mentions_env(self):
        text = self._read()
        assert ".env" in text

    def test_mentions_jwt_secret(self):
        assert "JWT_SECRET" in self._read()

    def test_mentions_deepseek_key(self):
        assert "DEEPSEEK_API_KEY" in self._read()

    def test_mentions_qmt(self):
        assert "QMT" in self._read()

    def test_mentions_backup(self):
        text = self._read()
        assert "backup" in text.lower() or "Backup" in text

    def test_mentions_cleanup(self):
        text = self._read()
        assert "cleanup" in text.lower() or "Cleanup" in text

    def test_mentions_redis_unavailable(self):
        text = self._read()
        assert "Redis" in text and ("not available" in text.lower() or "not reachable" in text.lower() or "recovery" in text.lower())

    def test_mentions_qmt_not_started(self):
        text = self._read()
        assert "QMT" in text and ("not started" in text.lower() or "not ready" in text.lower() or "not connected" in text.lower() or "recovery" in text.lower())

    def test_mentions_pdf_failure(self):
        text = self._read()
        assert "PDF" in text and ("failure" in text.lower() or "fail" in text.lower() or "rendering" in text.lower())

    def test_mentions_prod_dev_boundary(self):
        text = self._read()
        assert ("development" in text.lower() or "dev" in text.lower()) and "production" in text.lower()


# ---------------------------------------------------------------------------
# 2. Start script — no --reload
# ---------------------------------------------------------------------------


class TestStartScript:
    SCRIPT = PROD_SCRIPTS / "start_production_services.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def _read(self) -> str:
        return self.SCRIPT.read_text(encoding="utf-8")

    def test_no_reload(self):
        text = self._read()
        assert "--reload" not in text, "Production start script must not use --reload"

    def test_uses_venv(self):
        assert ".venv" in self._read()

    def test_creates_pid_files(self):
        assert ".pid" in self._read()

    def test_creates_log_dir(self):
        text = self._read()
        assert "logs" in text.lower() and "prod" in text.lower()

    def test_preflight_jwt_check(self):
        assert "JWT_SECRET" in self._read()

    def test_preflight_admin_pass_check(self):
        assert "AUTH_ADMIN_PASS" in self._read()

    def test_preflight_redis_check(self):
        text = self._read()
        assert "redis" in text.lower() or "Redis" in text

    def test_redis_check_uses_configured_broker_url(self):
        text = self._read()
        assert "CELERY_BROKER_URL" in text
        assert "DANDELIONS_REDIS_CHECK_URL" in text
        assert "redis://127.0.0.1:6379/0" not in text

    def test_uses_runtime_prod_dir(self):
        text = self._read()
        assert "storage\\runtime\\prod" in text

    def test_starts_real_process_not_powershell_wrapper(self):
        text = self._read()
        assert 'Start-Process -FilePath $FilePath' in text
        assert 'Start-Process -FilePath "powershell.exe"' not in text
        assert "Tee-Object" not in text

    def test_redirects_stdout_and_stderr(self):
        text = self._read()
        assert "RedirectStandardOutput" in text
        assert "RedirectStandardError" in text

    def test_writes_service_metadata(self):
        text = self._read()
        assert "$Name.json" in text
        assert "start_time_utc" in text
        assert "project_root" in text

    def test_existing_pid_is_verified_before_auto_stop(self):
        text = self._read()
        assert "Test-ManagedProcessMatchesMetadata" in text
        assert "Refusing to stop it automatically" in text

    def test_no_global_process_kill(self):
        text = self._read()
        # Should not contain broad process killing
        assert "Stop-Process -Name python" not in text
        assert "taskkill /IM python.exe" not in text


# ---------------------------------------------------------------------------
# 3. Cleanup script — dry-run default
# ---------------------------------------------------------------------------


class TestCleanupScript:
    SCRIPT = PROD_SCRIPTS / "cleanup_runtime_data.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def _read(self) -> str:
        return self.SCRIPT.read_text(encoding="utf-8")

    def test_dry_run_default(self):
        text = self._read()
        assert "dry-run" in text.lower() or "dry_run" in text.lower() or "DRY-RUN" in text

    def test_requires_execute_flag(self):
        text = self._read()
        assert "-Execute" in text

    def test_path_validation(self):
        text = self._read()
        assert "ProjectRoot" in text or "project_root" in text.lower()
        assert "DirectorySeparatorChar" in text

    def test_does_not_delete_env(self):
        text = self._read()
        # .env should not be in the deletion targets
        lines = text.split("\n")
        for line in lines:
            if "Remove-Item" in line or "Remove-SafeItem" in line:
                assert '".env"' not in line, "Cleanup script must not delete .env"

    def test_does_not_delete_tasks_db(self):
        text = self._read()
        lines = text.split("\n")
        for line in lines:
            if "Remove-Item" in line or "Remove-SafeItem" in line:
                assert "tasks.db" not in line, "Cleanup script must not delete tasks.db"

    def test_does_not_delete_reference_dir(self):
        text = self._read()
        lines = text.split("\n")
        for line in lines:
            if "Remove-Item" in line or "Remove-SafeItem" in line:
                assert "reference" not in line.lower() or "pytest_cache" in line.lower(), \
                    "Cleanup script must not delete storage/reference"

    def test_no_global_process_kill(self):
        text = self._read()
        assert "Stop-Process -Name python" not in text
        assert "taskkill /IM python.exe" not in text


# ---------------------------------------------------------------------------
# 4. Stop script — no broad process killing
# ---------------------------------------------------------------------------


class TestStopScript:
    SCRIPT = PROD_SCRIPTS / "stop_production_services.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def _read(self) -> str:
        return self.SCRIPT.read_text(encoding="utf-8")

    def test_no_kill_by_process_name_python(self):
        text = self._read()
        assert "Stop-Process -Name python" not in text

    def test_no_taskkill_python(self):
        text = self._read()
        assert "taskkill /IM python.exe" not in text

    def test_no_kill_powershell(self):
        text = self._read()
        assert "Stop-Process -Name powershell" not in text

    def test_no_kill_redis_by_name(self):
        text = self._read()
        assert "Stop-Process -Name redis" not in text

    def test_no_kill_celery_by_name(self):
        text = self._read()
        assert "Stop-Process -Name celery" not in text

    def test_no_kill_streamlit_by_name(self):
        text = self._read()
        assert "Stop-Process -Name streamlit" not in text

    def test_uses_pid_files(self):
        text = self._read()
        assert ".pid" in text

    def test_validates_metadata_before_stopping(self):
        text = self._read()
        assert "$name.json" in text
        assert "Test-ManagedProcessMatchesMetadata" in text
        assert "AllowLegacyPid" in text

    def test_stops_process_tree_by_pid(self):
        text = self._read()
        assert "Get-CimInstance Win32_Process" in text
        assert "ParentProcessId=$Pid" in text
        assert "Stop-Process -Id $Pid" in text


# ---------------------------------------------------------------------------
# 5. Backup script — covers must-backup paths
# ---------------------------------------------------------------------------


class TestBackupScript:
    SCRIPT = PROD_SCRIPTS / "backup_runtime_data.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def _read(self) -> str:
        return self.SCRIPT.read_text(encoding="utf-8")

    def test_covers_env(self):
        assert ".env" in self._read()

    def test_covers_tasks_db(self):
        assert "tasks.db" in self._read()

    def test_covers_watchlist_json(self):
        assert "watchlist.json" in self._read()

    def test_covers_research_cache(self):
        assert "research_data.sqlite" in self._read()

    def test_covers_reference_dir(self):
        assert "reference" in self._read()

    def test_covers_reports_dir(self):
        assert "reports" in self._read()

    def test_generates_manifest(self):
        text = self._read()
        assert "manifest" in text.lower()

    def test_preserves_project_relative_layout(self):
        text = self._read()
        assert 'Join-Path $BackupDir $target.Source' in text
        assert "-replace '\\\\', '_'" not in text


# ---------------------------------------------------------------------------
# 6. .env.production.example
# ---------------------------------------------------------------------------


class TestEnvProductionExample:
    TEMPLATE = PROJECT_ROOT / ".env.production.example"

    def test_exists(self):
        assert self.TEMPLATE.exists(), f"Missing: {self.TEMPLATE}"

    def _read(self) -> str:
        return self.TEMPLATE.read_text(encoding="utf-8")

    def test_no_real_deepseek_key(self):
        text = self._read()
        # Should contain placeholder, not a real key
        assert "__REPLACE" in text or "your-deepseek" in text.lower() or "REPLACE" in text

    def test_no_real_jwt_secret(self):
        text = self._read()
        assert "__REPLACE" in text or "REPLACE" in text

    def test_no_real_admin_password(self):
        text = self._read()
        assert "__REPLACE" in text or "REPLACE" in text

    def test_contains_jwt_secret(self):
        assert "JWT_SECRET" in self._read()

    def test_contains_admin_pass(self):
        assert "AUTH_ADMIN_PASS" in self._read()

    def test_contains_deepseek_key(self):
        assert "DEEPSEEK_API_KEY" in self._read()

    def test_contains_celery_broker(self):
        assert "CELERY_BROKER_URL" in self._read()

    def test_contains_celery_backend(self):
        assert "CELERY_RESULT_BACKEND" in self._read()

    def test_contains_cors_origins(self):
        assert "CORS_ORIGINS" in self._read()

    def test_contains_qmt_config(self):
        assert "QMT_" in self._read()

    def test_contains_csmar_config(self):
        assert "CSMAR_" in self._read()

    def test_labeled_as_production(self):
        text = self._read()
        assert "production" in text.lower() or "Production" in text


# ---------------------------------------------------------------------------
# 7. Status script exists
# ---------------------------------------------------------------------------


class TestStatusScript:
    SCRIPT = PROD_SCRIPTS / "status_production_services.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def test_checks_pid(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert ".pid" in text

    def test_checks_redis(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "redis" in text.lower() or "Redis" in text

    def test_supports_custom_ports(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "[int]$ApiPort" in text
        assert "[int]$StreamlitPort" in text
        assert "http://127.0.0.1:$ApiPort/api/v1/health" in text

    def test_redis_check_uses_configured_broker_url(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "CELERY_BROKER_URL" in text
        assert "redis://127.0.0.1:6379/0" not in text


# ---------------------------------------------------------------------------
# 8. Health check script exists
# ---------------------------------------------------------------------------


class TestHealthCheckScript:
    SCRIPT = PROD_SCRIPTS / "health_check.ps1"

    def test_exists(self):
        assert self.SCRIPT.exists(), f"Missing: {self.SCRIPT}"

    def test_returns_exit_code(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "exit 0" in text
        assert "exit 1" in text

    def test_checks_redis(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "redis" in text.lower() or "Redis" in text

    def test_redis_check_uses_configured_broker_url(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "CELERY_BROKER_URL" in text
        assert "redis://127.0.0.1:6379/0" not in text

    def test_checks_api(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "health" in text.lower() or "api" in text.lower()


# ---------------------------------------------------------------------------
# 9. Git ignore rules keep production templates tracked and runtime data ignored
# ---------------------------------------------------------------------------


class TestGitIgnoreProductionOps:
    def _read(self) -> str:
        return GITIGNORE.read_text(encoding="utf-8")

    def test_env_production_template_is_not_ignored(self):
        text = self._read()
        assert ".env.*" in text
        assert "!.env.production.example" in text

    def test_runtime_and_backup_dirs_are_ignored(self):
        text = self._read()
        assert "storage/runtime/" in text
        assert "storage/prod/" in text
        assert "backups/" in text
