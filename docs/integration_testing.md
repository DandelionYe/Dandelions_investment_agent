# Integration Testing

This project keeps live integration tests opt-in. The default test suite should
remain runnable without Redis, FastAPI, Celery, QMT, Streamlit, or external
network access.

## Prerequisites

Start local development services from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dev_services.ps1
```

This starts Redis, FastAPI, Celery worker, Celery Beat, and Streamlit in
separate windows. Keep those windows open while running live tests.

Use the repository virtual environment for all commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Default Test Run

Without opt-in environment variables, live tests are collected but skipped:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

Expected shape:

```text
skipped
```

## FastAPI, Redis, Celery, and WebSocket Live Tests

Enable local service integration tests:

```powershell
$env:RUN_LIVE_INTEGRATION='1'
Remove-Item Env:RUN_QMT_INTEGRATION -ErrorAction SilentlyContinue
Remove-Item Env:RUN_AKSHARE_NETWORK -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

These tests verify:

- `/api/v1/health` reports API, DB, and Redis as ok.
- Authenticated and unauthenticated API boundaries behave correctly.
- A mock single-asset research task can be submitted through FastAPI.
- Celery worker completes the task and persists status/result/report paths.
- WebSocket task progress reaches a terminal `completed` event.
- Redis broker is reachable and Celery registered tasks match schedule needs.

## QMT Local Smoke Test

Run this only when XtMiniQMT/xtquant is open and connected:

```powershell
$env:RUN_QMT_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_qmt_local_live.py -q
```

The test keeps QMT auto-download disabled and checks only a minimal local data
path for `600519.SH`: connection status, price data, row count, and provider
run log.

## AKShare Network Smoke Test

Run this only when external network access is available:

```powershell
$env:RUN_AKSHARE_NETWORK='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_akshare_network_live.py -q
```

This checks that AKShare can fetch price data for `600519.SH`. Network,
provider schema, proxy, or rate-limit failures should be treated as integration
environment failures, not unit-test failures.

## Marker Reference

- `integration`: cross-component tests.
- `live`: requires running services or external systems.
- `qmt`: requires local QMT/xtquant.
- `network`: requires external network data sources.

