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
