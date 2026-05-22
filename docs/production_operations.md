# Production Operations Guide

This document covers deploying and operating Dandelions Investment Agent on a
Windows workstation in a production/准生产 environment.

## Scope

- Windows workstation deployment with local MiniQMT.
- Redis (Docker or WSL), FastAPI, Celery, Streamlit co-located on one machine.
- Single-user or small-team usage.

**Not covered:**

- Cloud-native / Kubernetes deployment.
- High-availability clusters.
- Multi-node Celery scaling.
- Watchlist real-market-data acceptance testing (see `report.md` P1 backlog).

---

## Production vs Development Boundary

| Aspect | Development | Production |
|--------|-------------|------------|
| Startup script | `scripts/start_dev_services.ps1` | `scripts/prod/start_production_services.ps1` |
| Redis launcher | `scripts/start_redis.ps1` (WSL, no persistence guaranteed) | Docker Compose with AOF volume, or WSL with explicit persistence |
| FastAPI reload | `--reload` enabled | `--reload` forbidden; uses `--workers 2` |
| Celery Beat schedule | `storage/runtime/celerybeat-schedule` | `storage/runtime/prod/celerybeat-schedule` |
| Log output | Separate PowerShell windows, stdout only | `storage/logs/prod/*.log` files |
| PID management | None | `storage/runtime/prod/*.pid` and `*.json` metadata files |
| Config secrets | Example values acceptable | Must use real random secrets |
| `.env` template | `.env.example` | `.env.production.example` |

---

## 1. Prerequisites

### 1.1 System Requirements

- Windows 10/11 with PowerShell 5.1+ or PowerShell 7+.
- Python 3.13+ in `.venv`.
- Docker Desktop (for Redis) or WSL2 Ubuntu (for Redis via `start_redis.ps1`).
- MiniQMT/xtquant installed and logged in (for QMT data source).
- Playwright Chromium (for PDF generation): `python -m playwright install chromium`.

### 1.2 Install Python Dependencies

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

---

## 2. Redis Strategy

### 2.1 Recommended: Docker Compose (with persistence)

The project includes `docker-compose.yml` with Redis 7 Alpine and AOF persistence:

```powershell
docker compose up -d redis
```

Verify:

```powershell
docker compose ps
# Should show redis container as "Up" with healthcheck passing
```

The Redis data volume `redis-data` persists across container restarts.

### 2.2 Alternative: WSL Redis

The development script `scripts/start_redis.ps1` starts Redis in WSL, but
**does not enable persistence by default**. For production WSL usage, configure
persistence manually:

```powershell
wsl -d Ubuntu -- bash -lc "redis-server --port 6379 --bind 0.0.0.0 --protected-mode no --save 60 1 --appendonly yes --daemonize yes --logfile /tmp/dandelions-redis-prod.log"
```

### 2.3 Redis Not Available — Recovery

**Symptoms:**

- FastAPI health check returns 503 with `redis: { status: "error" }`.
- Celery worker logs `ConnectionError` or `redis.exceptions.ConnectionError`.
- WebSocket progress events stop flowing.

**Steps:**

1. Check if Redis is running:
   ```powershell
   docker compose ps          # Docker approach
   wsl -d Ubuntu -- redis-cli ping   # WSL approach
   ```

2. Restart Redis:
   ```powershell
   docker compose restart redis       # Docker
   # or
   wsl -d Ubuntu -- sudo service redis-server restart   # WSL
   ```

3. Restart dependent services:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1 -Services worker,beat,api
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services api,worker,beat
   ```

---

## 3. Sensitive Configuration

### 3.1 `.env` Management

- `.env` is listed in `.gitignore` and must never be committed.
- Use `.env.production.example` as a template. Copy it:
  ```powershell
  Copy-Item .env.production.example .env
  ```

### 3.2 Required Production Secrets

| Variable | Requirement | How to Generate |
|----------|-------------|-----------------|
| `JWT_SECRET` | ≥32 random characters | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `AUTH_ADMIN_PASS` | Strong password, not the example | `python -c "import secrets; print(secrets.token_urlsafe(16))"` |
| `DEEPSEEK_API_KEY` | Valid API key | From DeepSeek console |
| `CELERY_BROKER_URL` | Valid Redis URL | `redis://127.0.0.1:6379/0` |
| `CELERY_RESULT_BACKEND` | Valid Redis URL | `redis://127.0.0.1:6379/1` |

### 3.3 Sensitive Path Configuration

These paths are environment-specific and should be adjusted per machine:

- `QMT_*` — QMT data directory and connection settings.
- `LOCAL_CSMAR_INDUSTRY_DB`, `CSMAR_DAILY_DERIVED_DB`, `CSMAR_EVA_STRUCTURE_DB` — local reference database paths.
- `CORS_ORIGINS` — allowed frontend origins.
- `TRUSTED_PROXY_IPS` — only set behind a trusted reverse proxy.

### 3.4 Secret Rotation

**JWT Secret:**

1. Generate new secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Update `JWT_SECRET` in `.env`.
3. Restart API: `stop -Services api; start -Services api`
4. All existing tokens become invalid; users must re-authenticate.

**DeepSeek API Key:**

1. Get new key from DeepSeek console.
2. Update `DEEPSEEK_API_KEY` in `.env`.
3. Restart API and Celery worker.

**Admin Password:**

1. Generate new password: `python -c "import secrets; print(secrets.token_urlsafe(16))"`
2. Update `AUTH_ADMIN_PASS` in `.env`.
3. Restart API. The new password takes effect on next login (admin user is
   re-seeded on startup).

---

## 4. Service Start / Stop / Restart

### 4.1 Start All Services

```powershell
.\.venv\Scripts\Activate.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1
```

This runs preflight checks (`.env`, `JWT_SECRET`, `AUTH_ADMIN_PASS`, Redis
connectivity from `CELERY_BROKER_URL`) and starts FastAPI, Celery worker,
Celery Beat, and Streamlit as hidden background processes. Each service gets a
PID file plus metadata under `storage/runtime/prod/`.

### 4.2 Start Specific Services

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services api,worker
```

Valid service names: `api`, `worker`, `beat`, `streamlit`, `all`.

### 4.3 Stop All Services

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1
```

### 4.4 Stop Specific Service

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1 -Services api
```

### 4.5 Check Status

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1
```

If the services were started on non-default ports, pass the same ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1 -ApiPort 9000 -StreamlitPort 9501
```

### 4.6 Health Check

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\health_check.ps1
echo $LASTEXITCODE
```

Returns exit code 0 if all checks pass, non-zero otherwise. Suitable for
scheduled tasks.

### 4.7 Restart a Single Service

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1 -Services api
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services api
```

### 4.8 Full Restart

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1
```

### 4.9 Service Ports and Logs

| Service | Default Port | Log File | PID File |
|---------|-------------|----------|----------|
| FastAPI | 8000 | `storage/logs/prod/api.out.log`, `api.err.log` | `storage/runtime/prod/api.pid` |
| Celery Worker | — | `storage/logs/prod/celery-worker.out.log`, `celery-worker.err.log` | `storage/runtime/prod/worker.pid` |
| Celery Beat | — | `storage/logs/prod/celery-beat.out.log`, `celery-beat.err.log` | `storage/runtime/prod/beat.pid` |
| Streamlit | 8501 | `storage/logs/prod/streamlit.out.log`, `streamlit.err.log` | `storage/runtime/prod/streamlit.pid` |

---

## 5. Backup Strategy

### 5.1 Backup Categories

| Category | Paths | Priority | Notes |
|----------|-------|----------|-------|
| **Must backup** | `.env` | Critical | Contains all secrets and config |
| **Must backup** | `storage/tasks.db` | Critical | Task history and results |
| **Must backup** | `storage/watchlist.json` | Critical | Watchlist configuration |
| **Must backup** | `storage/cache/research_data.sqlite` | High | Research cache |
| **Must backup** | `storage/reference/` | High | CSMAR/EVA reference databases |
| **Must backup** | `storage/reports/` | High | Generated reports |
| **Must backup** | `storage/artifacts/` | Medium | Verification artifacts |
| **Can clean** | `.venv/` | — | Reinstallable via pip |
| **Can clean** | `.git/` | — | Re-cloneable from remote |
| **Can clean** | `__pycache__/` | — | Regenerated on import |
| **Can clean** | `.pytest_cache/` | — | Regenerated by pytest |
| **Can clean** | `.ruff_cache/` | — | Regenerated by ruff |
| **Can clean** | `storage/logs/prod/*.log` (old) | — | Configurable retention |
| **Can clean** | `storage/runtime/prod/*.pid` and `*.json` (stale) | — | Cleaned by cleanup script |
| **Can clean** | `storage/prod/` | — | Legacy production runtime path from early scripts |

### 5.2 Backup Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\backup_runtime_data.ps1
```

Creates `backups/YYYYMMDD_HHMMSS/` with all must-backup items and a
`manifest.json` describing what was copied. The backup preserves the
project-relative directory layout, for example `storage/tasks.db` is copied to
`backups/YYYYMMDD_HHMMSS/storage/tasks.db`.

`backups/` is ignored by Git because it may contain `.env`, task history,
reports, and local reference databases.

Include production logs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\backup_runtime_data.ps1 -IncludeLogs
```

### 5.3 Restore (Basic Steps)

1. Stop all services.
2. Copy backup contents back to project root. The backup already preserves the
   project-relative directory structure.
3. Verify `.env` is present and correct.
4. Start services.
5. Run health check.

---

## 6. Cleanup

### 6.1 Dry-Run (Default)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1
```

Shows what would be deleted without actually deleting anything.

### 6.2 Execute Cleanup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1 -Execute
```

### 6.3 Custom Log Retention

Keep only 7 days of logs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\cleanup_runtime_data.ps1 -Execute -LogRetentionDays 7
```

### 6.4 What Gets Cleaned

- `__pycache__/` directories (Python bytecode cache).
- `.pytest_cache/` directories.
- `.ruff_cache/` directories.
- Production log files older than retention period.
- Stale PID and metadata files (process no longer running).

### 6.5 What Is NOT Cleaned

- `storage/cache/research_data.sqlite` — research cache (has backup strategy).
- `storage/reference/` — CSMAR/EVA reference databases (has backup strategy).
- `storage/reports/` — generated reports (has backup strategy).
- `storage/tasks.db` — task database (has backup strategy).
- `storage/watchlist.json` — watchlist data (has backup strategy).
- `.env` — configuration (has backup strategy).

---

## 7. Fault Recovery

### 7.1 Service Exited Unexpectedly

1. Check status:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\status_production_services.ps1
   ```

2. Check the service log:
   ```powershell
   Get-Content storage\logs\prod\api.err.log -Tail 50
   Get-Content storage\logs\prod\celery-worker.err.log -Tail 50
   ```

3. Restart the specific service:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services api
   ```

### 7.2 Redis Not Available

See [Section 2.3](#23-redis-not-available--recovery).

### 7.3 QMT Not Started

**Symptoms:**

- Research tasks fail with `ProviderUnavailableError` or QMT connection errors.
- Data quality regression tests fail.

**Steps:**

1. Launch MiniQMT and log in.
2. Verify connection:
   ```powershell
   .\.venv\Scripts\python.exe -c "from xtquant import xtdata; xtdata.connect(); print('QMT connected')"
   ```
3. If using QMT data directory sync, run robocopy as documented in `README.md`.
4. Re-run data quality smoke:
   ```powershell
   .\.venv\Scripts\python.exe scripts\run_data_quality_regression.py
   ```

QMT is not a hard dependency for starting API/Celery/Streamlit. Research tasks
will fail gracefully if QMT is unavailable.

### 7.4 PDF Rendering Failure

**Symptoms:**

- Report generation completes but PDF is missing.
- Logs show Playwright/Chromium errors.

**Steps:**

1. Verify Playwright Chromium is installed:
   ```powershell
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```

2. PDF failure does not block core data production. JSON, Markdown, and HTML
   reports are always generated. PDF is optional.

3. To skip PDF generation, the CLI uses `--pdf` flag (off by default). The
   Streamlit dashboard generates PDF only on explicit request.

### 7.5 Celery Worker/Beat Issues

**Symptoms:**

- Tasks stuck in PENDING state.
- Beat schedule not triggering.

**Steps:**

1. Check worker and beat logs:
   ```powershell
   Get-Content storage\logs\prod\celery-worker.err.log -Tail 50
   Get-Content storage\logs\prod\celery-beat.err.log -Tail 50
   ```

2. If Beat schedule is corrupted, stop Beat and delete the schedule file:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\stop_production_services.ps1 -Services beat
   Remove-Item storage\runtime\prod\celerybeat-schedule -ErrorAction SilentlyContinue
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prod\start_production_services.ps1 -Services beat
   ```

3. Verify Redis is reachable (worker and Beat depend on Redis).

---

## 8. Scheduled Tasks (Windows Task Scheduler)

You can use Windows Task Scheduler to automate health checks, backups, and
cleanup. Example setup:

### 8.1 Daily Health Check

- **Trigger:** Daily at 08:00.
- **Action:** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "J:\Dandelions_investment_agent\scripts\prod\health_check.ps1"`
- **Settings:** Run whether user is logged on or not.

### 8.2 Daily Backup

- **Trigger:** Daily at 23:00.
- **Action:** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "J:\Dandelions_investment_agent\scripts\prod\backup_runtime_data.ps1"`

### 8.3 Weekly Cleanup

- **Trigger:** Weekly on Sunday at 02:00.
- **Action:** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "J:\Dandelions_investment_agent\scripts\prod\cleanup_runtime_data.ps1" -Execute -LogRetentionDays 30`

### 8.4 Notes

- Use absolute paths in Task Scheduler actions.
- Set "Start in" to the project root directory.
- For the health check, configure the task to send an email or write to the
  Windows Event Log on failure if notification is needed.

---

## 9. Script Reference

| Script | Purpose |
|--------|---------|
| `scripts/prod/start_production_services.ps1` | Start all or specific services with preflight checks |
| `scripts/prod/stop_production_services.ps1` | Stop services by PID file |
| `scripts/prod/status_production_services.ps1` | Show service status, port, Redis |
| `scripts/prod/health_check.ps1` | Automated health check (exit code based) |
| `scripts/prod/backup_runtime_data.ps1` | Backup critical data with manifest |
| `scripts/prod/cleanup_runtime_data.ps1` | Clean caches and old logs (dry-run default) |
| `scripts/start_dev_services.ps1` | Development launcher (separate windows, reload) |
| `scripts/start_redis.ps1` | Development Redis launcher (WSL, no persistence) |
