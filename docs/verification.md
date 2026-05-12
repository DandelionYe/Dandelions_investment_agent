# Verification Log

This file records reproducible local verification results for the current
workspace. Commands should be run from the repository root with the project
virtual environment.

## 2026-05-12 Celery Beat Schedule Fix

Scope:

- Fixed `apps/api/celery_app.py` so Celery Beat schedule entries use the same
  custom task names registered by the worker:
  - `beat.daily_health_check`
  - `beat.watchlist_scheduler_check`
  - `beat.watchlist_scan`
- Added `tests/test_celery_schedule.py` to assert every
  `celery_app.conf.beat_schedule[*]["task"]` exists in `celery_app.tasks`.

Commands:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
.\.venv\Scripts\python.exe -m pytest tests/test_celery_schedule.py -q -p no:cacheprovider
```

Result:

```text
1 passed
```

Schedule-to-registered-task check:

```powershell
.\.venv\Scripts\python.exe -c "from apps.api.celery_app import celery_app; import apps.api.task_manager.celery_tasks; print('schedule'); [print(name + '=' + entry['task']) for name, entry in celery_app.conf.beat_schedule.items()]; print('registered'); [print(name) for name in sorted(celery_app.tasks.keys()) if name.startswith('beat.') or name.startswith('watchlist.') or name.startswith('research.')]"
```

Result:

```text
schedule
daily-health-check=beat.daily_health_check
watchlist-scheduler-check=beat.watchlist_scheduler_check
watchlist-scan-weekday-close=beat.watchlist_scan
registered
beat.daily_health_check
beat.watchlist_scan
beat.watchlist_scheduler_check
research.run_single
watchlist.scan_single_item
```

Related tests:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
.\.venv\Scripts\python.exe -m pytest tests/test_celery_schedule.py tests/test_websocket.py -q -p no:cacheprovider
```

Result:

```text
9 passed, 2 skipped
```

Full local test suite:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
$env:RESEARCH_CACHE_ENABLED='false'
$env:MARKET_DATA_DISABLE_PROXY='true'
$env:QMT_AUTO_DOWNLOAD='false'
$env:QMT_FINANCIAL_AUTO_DOWNLOAD='false'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Result:

```text
262 passed, 7 skipped
```

## 2026-05-12 Live Integration Test Baseline

Scope:

- Added opt-in integration markers in `pyproject.toml`.
- Added `tests/integration/` live tests for:
  - FastAPI auth, health, research task, result, and report-info flow.
  - Redis broker reachability, Celery worker registered tasks, active queues,
    and health-check task roundtrip.
  - WebSocket task progress terminal event.
  - Local QMT minimal data smoke.
  - AKShare network smoke, disabled unless explicitly requested.
- Fixed `/api/v1/research/history` route ordering so it is not captured by the
  dynamic `/api/v1/research/{task_id}` route.
- Removed custom `beat` queue routing from Celery Beat schedule because the
  development worker listens on the default `celery` queue.

Default integration collection:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

Result without live flags:

```text
8 skipped
```

FastAPI/Celery/Redis/WebSocket live run:

```powershell
$env:RUN_LIVE_INTEGRATION='1'
Remove-Item Env:RUN_QMT_INTEGRATION -ErrorAction SilentlyContinue
Remove-Item Env:RUN_AKSHARE_NETWORK -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

Result:

```text
6 passed, 2 skipped
```

QMT local smoke:

```powershell
Remove-Item Env:RUN_LIVE_INTEGRATION -ErrorAction SilentlyContinue
$env:RUN_QMT_INTEGRATION='1'
Remove-Item Env:RUN_AKSHARE_NETWORK -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/integration/test_qmt_local_live.py -q
```

Result:

```text
1 passed, 1 warning
```

Static checks for the changed integration baseline:

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/celery_app.py apps/api/routers/research.py tests/test_celery_schedule.py tests/integration
```

Result:

```text
All checks passed!
```

Updated CI-targeted local test run:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
$env:RESEARCH_CACHE_ENABLED='false'
$env:MARKET_DATA_DISABLE_PROXY='true'
$env:QMT_AUTO_DOWNLOAD='false'
$env:QMT_FINANCIAL_AUTO_DOWNLOAD='false'
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_llm_json_guard.py tests/test_security_config.py tests/test_celery_schedule.py tests/test_provider_errors.py tests/test_report_pipeline.py tests/test_valuation_percentile.py tests/test_scoring_engine.py -q
```

Result:

```text
86 passed
```

Full default local test suite after adding integration tests:

```powershell
$env:JWT_SECRET='ci-secret-token-uses-more-than-32-characters'
$env:AUTH_ADMIN_PASS='ci-admin-password'
$env:AUTH_REVOCATION_FAIL_MODE='open'
$env:RESEARCH_CACHE_ENABLED='false'
$env:MARKET_DATA_DISABLE_PROXY='true'
$env:QMT_AUTO_DOWNLOAD='false'
$env:QMT_FINANCIAL_AUTO_DOWNLOAD='false'
Remove-Item Env:RUN_LIVE_INTEGRATION -ErrorAction SilentlyContinue
Remove-Item Env:RUN_QMT_INTEGRATION -ErrorAction SilentlyContinue
Remove-Item Env:RUN_AKSHARE_NETWORK -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
263 passed, 15 skipped
```

## 2026-05-12 Web News Event Enhancement

Scope:

- Added `services/data/providers/web_news_provider.py` as a default-off
  domestic news provider backed by Baidu News RSS.
- The provider enforces direct domestic connectivity for news crawling by:
  - removing common proxy environment variables;
  - setting `NO_PROXY=*`;
  - using `requests.Session.trust_env = False`;
  - passing explicit empty proxy settings to `requests`.
- Added `EventNormalizer.normalize_web_news()` and merged optional web news
  events into `EventService` without blocking the official announcement path.
- Added event-level evidence entries so high-priority official/news events can
  appear in `evidence_bundle`.
- Added `tests/test_web_news_provider.py` for disabled mode, forced no-proxy
  behavior, web news normalization, event merge, and evidence propagation.

Targeted provider/event tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_news_provider.py tests/test_report_pipeline.py tests/test_provider_errors.py -q -p no:cacheprovider
```

Result:

```text
23 passed
```

Static checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check services/data/providers/web_news_provider.py services/data/normalizers/event_normalizer.py services/research/event_engine.py services/data/aggregator/evidence_builder.py services/network/proxy_policy.py tests/test_web_news_provider.py
```

Result:

```text
All checks passed!
```

Updated CI-targeted local test run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_llm_json_guard.py tests/test_security_config.py tests/test_celery_schedule.py tests/test_provider_errors.py tests/test_web_news_provider.py tests/test_report_pipeline.py tests/test_valuation_percentile.py tests/test_scoring_engine.py -q -p no:cacheprovider
```

Result:

```text
90 passed
```

Full default local test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Result:

```text
267 passed, 15 skipped
```
