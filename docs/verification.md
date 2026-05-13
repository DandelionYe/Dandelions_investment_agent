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

Related provider/pipeline tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_news_provider.py tests/test_report_pipeline.py tests/test_provider_errors.py -q -p no:cacheprovider
```

Result:

```text
28 passed
```

Full default local test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Result:

```text
272 passed, 16 skipped
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

## 2026-05-13 Web News Network Fallback Verification

Scope:

- Extended `WebNewsProvider` to use Eastmoney stock news as the preferred
  domestic news source, with Sina Finance rolling news, Xinhua Net finance
  latest news, hot-rank public-opinion sources, and Baidu News RSS retained as
  fallbacks.
- Reused the existing AKShare Eastmoney interface and guarded it with
  `pandas.option_context("future.infer_string", False)` to avoid pyarrow-backed
  string replacement failures in the current pandas runtime.
- Reviewed the local `tools/` reference repositories and converted the useful
  ideas into project-local implementation:
  - Sina Finance rolling news URL/content shape as a fallback source.
  - Xinhua Net finance `nodeart/list` endpoint shape from the local
    `tools/NewsCrawler` reference, parsed with safe JSONP handling instead of
    `eval`.
  - Wallstreetcn, Yicai, 36Kr, Tencent News, Sina News, Sina Hot Topics, The
    Paper, Bilibili, Douyin, CSDN, GitHub Trending, Google Trends, and WeRead
    endpoint shapes from the local `tools/hotToday` reference, filtered
    strictly by stock/company relevance before entering the event pipeline.
  - Optional `curl_cffi` browser impersonation for hot-rank endpoints such as
    Bilibili that reject generic HTTP clients.
  - Low-quality title filtering for obvious ads/promotions.
  Sohu was left as a later candidate because it adds broader portal-news noise
  without improving the first stock-specific fallback path.
- Kept the direct-connect requirement for news fetching: proxy environment
  variables are removed and `NO_PROXY=*` is set before network access.
- Added `tests/integration/test_web_news_network_live.py` as an opt-in live
  smoke test controlled by `RUN_WEB_NEWS_NETWORK=1`.

Default integration behavior:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration -q -p no:cacheprovider
```

Result without live flags:

```text
9 skipped
```

Unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_news_provider.py -q -p no:cacheprovider
```

Result:

```text
11 passed
```

Live web news smoke:

```powershell
$env:RUN_WEB_NEWS_NETWORK='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_web_news_network_live.py -q -p no:cacheprovider
```

Result:

```text
1 passed
```

Hot-rank source probes:

```powershell
.\.venv\Scripts\python.exe -c "from services.data.providers.web_news_provider import WebNewsProvider; p=WebNewsProvider(enabled=True, force_no_proxy=True, limit=3, timeout_seconds=12); si={'normalized_symbol':'','plain_code':'','name':'','asset_type':'stock'}; methods={'wallstreetcn':p._fetch_wallstreetcn_hotrank,'yicai':p._fetch_yicai_hotrank,'36kr':p._fetch_36kr_hotrank,'tencent':p._fetch_tencent_hotrank,'sina_news':p._fetch_sina_news_hotrank,'sina_hot':p._fetch_sina_hotrank,'pengpai':p._fetch_pengpai_hotrank,'bilibili':p._fetch_bilibili_hotrank,'douyin':p._fetch_douyin_hotrank,'csdn':p._fetch_csdn_hotrank,'github':p._fetch_github_hotrank,'google':p._fetch_google_hotrank,'weread':p._fetch_weread_hotrank}; [print(name, len(fn(si))) for name, fn in methods.items()]"
```

Result:

```text
wallstreetcn: 70 parsed
yicai: 20 parsed
36kr: 0 parsed
tencent: 51 parsed
sina_news: 60 parsed
sina_hot: 38 parsed
pengpai: 35 parsed
bilibili: 87 parsed
douyin: 46 parsed
csdn: 25 parsed
github: 11 parsed
google: ConnectTimeout in this environment
weread: 14 parsed
```

Stock-filtered hot-rank probe for `贵州茅台` returned no current hot-rank
records during this run, which is acceptable because hot-rank sources are
strict relevance fallbacks rather than guaranteed company-news feeds.
36Kr returned an anti-bot/challenge page in this run and parsed no records;
Google Trends timed out from this network. Both are isolated optional
sub-sources and do not block the provider fallback chain.

Static checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check services/data/providers/web_news_provider.py tests/test_web_news_provider.py tests/integration/test_web_news_network_live.py
```

Result:

```text
All checks passed!
```

Related provider/pipeline tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_news_provider.py tests/test_report_pipeline.py tests/test_provider_errors.py -q -p no:cacheprovider
```

Result:

```text
30 passed
```

Full default local test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Result:

```text
274 passed, 16 skipped
```
