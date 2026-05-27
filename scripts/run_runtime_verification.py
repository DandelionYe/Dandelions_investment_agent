"""P0: Runtime verification matrix — unified local smoke entry point.

Checks current running state of all services (FastAPI, Redis, Celery, WebSocket,
Streamlit, MiniQMT, PDF) without starting or stopping anything.

Usage:
    python scripts/run_runtime_verification.py
    python scripts/run_runtime_verification.py --strict
    python scripts/run_runtime_verification.py --include-qmt --include-network
    python scripts/run_runtime_verification.py --output-dir storage/artifacts/verification
"""

from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    category: str
    status: str  # pass | fail | warning | skipped
    severity: str  # blocker | warning | watch
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationReport:
    run_id: str
    generated_at: str
    overall_status: str  # pass | warning | fail
    strict: bool
    checks: list[dict[str, Any]]
    summary: dict[str, int]
    environment: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Return (status_code, body_text). Returns (0, error_msg) on failure."""
    try:
        import requests  # noqa: PLC0415
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, timeout=timeout)
        return resp.status_code, resp.text
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _read_dotenv_value(project_root: Path, key: str) -> str | None:
    env_path = project_root / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            return v
    return None


def _get_api_port() -> int:
    val = _read_dotenv_value(PROJECT_ROOT, "API_PORT")
    if val and val.isdigit():
        return int(val)
    return 8000


def _get_streamlit_port() -> int:
    val = _read_dotenv_value(PROJECT_ROOT, "STREAMLIT_PORT")
    if val and val.isdigit():
        return int(val)
    return 8501


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_python_environment() -> CheckResult:
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return CheckResult(
        name="python_environment",
        category="env",
        status="pass",
        severity="blocker",
        message=f"Python {platform.python_version()} at {sys.executable}",
        details={
            "python_version": platform.python_version(),
            "executable": sys.executable,
            "venv_expected": str(venv_python),
            "venv_matches": str(venv_python) == sys.executable,
            "platform": platform.platform(),
        },
    )


def check_redis() -> CheckResult:
    redis_url = _read_dotenv_value(PROJECT_ROOT, "CELERY_BROKER_URL")
    if not redis_url:
        return CheckResult(
            name="redis_ping",
            category="redis",
            status="fail",
            severity="blocker",
            message="CELERY_BROKER_URL not found in .env",
        )
    try:
        import redis  # noqa: PLC0415
        client = redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
        try:
            pong = client.ping()
        finally:
            client.close()
        return CheckResult(
            name="redis_ping",
            category="redis",
            status="pass" if pong else "fail",
            severity="blocker",
            message="Redis PONG received" if pong else "Redis ping returned False",
            details={"url": redis_url},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="redis_ping",
            category="redis",
            status="fail",
            severity="blocker",
            message=f"Redis connection failed: {exc}",
            details={"url": redis_url, "error": str(exc)},
        )


def check_fastapi_health() -> CheckResult:
    port = _get_api_port()
    if not _tcp_port_open("127.0.0.1", port):
        return CheckResult(
            name="fastapi_health",
            category="api",
            status="fail",
            severity="blocker",
            message=f"FastAPI port {port} not reachable",
            details={"port": port},
        )
    code, body = _http_get(f"http://127.0.0.1:{port}/api/v1/health", timeout=5)
    if code != 200:
        return CheckResult(
            name="fastapi_health",
            category="api",
            status="fail",
            severity="blocker",
            message=f"Health endpoint returned HTTP {code}",
            details={"port": port, "status_code": code, "body": body[:500]},
        )
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return CheckResult(
            name="fastapi_health",
            category="api",
            status="fail",
            severity="blocker",
            message="Health endpoint returned non-JSON response",
            details={"port": port, "body": body[:500]},
        )
    api_ok = data.get("api", {}).get("status") == "ok"
    db_ok = data.get("db", {}).get("status") == "ok"
    redis_ok = data.get("redis", {}).get("status") == "ok"
    all_ok = api_ok and db_ok and redis_ok
    return CheckResult(
        name="fastapi_health",
        category="api",
        status="pass" if all_ok else "warning",
        severity="blocker",
        message="API/DB/Redis all healthy" if all_ok else f"api={api_ok} db={db_ok} redis={redis_ok}",
        details=data,
    )


def check_fastapi_auth() -> CheckResult:
    """Check auth endpoint — skipped if no test credentials."""
    import os  # noqa: PLC0415
    port = _get_api_port()
    if not _tcp_port_open("127.0.0.1", port):
        return CheckResult(
            name="fastapi_auth",
            category="api",
            status="skipped",
            severity="warning",
            message="API port not reachable, skipping auth check",
        )
    username = os.getenv("AUTH_ADMIN_USER", "admin")
    password = os.getenv("AUTH_ADMIN_PASS")
    if not password:
        return CheckResult(
            name="fastapi_auth",
            category="api",
            status="skipped",
            severity="warning",
            message="AUTH_ADMIN_PASS not set, skipping auth smoke",
        )
    code, body = _http_get(f"http://127.0.0.1:{port}/api/v1/health", timeout=5)
    if code != 200:
        return CheckResult(
            name="fastapi_auth",
            category="api",
            status="skipped",
            severity="warning",
            message="API not healthy, skipping auth check",
        )
    try:
        import requests  # noqa: PLC0415
        resp = requests.post(
            f"http://127.0.0.1:{port}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10,
            trust_env=False,
        )
        if resp.status_code == 200:
            return CheckResult(
                name="fastapi_auth",
                category="api",
                status="pass",
                severity="warning",
                message="Auth login succeeded",
            )
        return CheckResult(
            name="fastapi_auth",
            category="api",
            status="warning",
            severity="warning",
            message=f"Auth login returned HTTP {resp.status_code}",
            details={"status_code": resp.status_code},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="fastapi_auth",
            category="api",
            status="warning",
            severity="warning",
            message=f"Auth check failed: {exc}",
        )


def check_celery_worker() -> CheckResult:
    """Ping Celery workers via inspect."""
    try:
        import apps.api.task_manager.celery_tasks  # noqa: F401, PLC0415
        from apps.api.celery_app import celery_app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="celery_worker",
            category="celery",
            status="fail",
            severity="blocker",
            message=f"Cannot import celery app: {exc}",
        )
    try:
        inspector = celery_app.control.inspect(timeout=5)
        ping_result = inspector.ping()
        if not ping_result:
            return CheckResult(
                name="celery_worker",
                category="celery",
                status="fail",
                severity="blocker",
                message="No Celery workers responded to ping",
            )
        worker_names = list(ping_result.keys())
        return CheckResult(
            name="celery_worker",
            category="celery",
            status="pass",
            severity="blocker",
            message=f"{len(worker_names)} worker(s) responded",
            details={"workers": worker_names},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="celery_worker",
            category="celery",
            status="fail",
            severity="blocker",
            message=f"Celery worker ping failed: {exc}",
        )


def check_celery_beat() -> CheckResult:
    """Try to detect Celery Beat — best-effort, not a blocker."""
    beat_schedule = PROJECT_ROOT / "storage" / "runtime" / "celerybeat-schedule"
    if beat_schedule.exists():
        mtime = datetime.fromtimestamp(beat_schedule.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        if age_hours < 24:
            return CheckResult(
                name="celery_beat",
                category="celery",
                status="pass",
                severity="watch",
                message=f"celerybeat-schedule updated {age_hours:.1f}h ago",
                details={"schedule_path": str(beat_schedule), "age_hours": round(age_hours, 1)},
            )
        return CheckResult(
            name="celery_beat",
            category="celery",
            status="warning",
            severity="watch",
            message=f"celerybeat-schedule is {age_hours:.0f}h old — beat may not be running",
            details={"schedule_path": str(beat_schedule), "age_hours": round(age_hours, 1)},
        )
    return CheckResult(
        name="celery_beat",
        category="celery",
        status="skipped",
        severity="watch",
        message="celerybeat-schedule file not found — cannot determine beat status",
    )


def check_websocket() -> CheckResult:
    """Basic WebSocket connectivity — skipped unless --include-websocket."""
    port = _get_api_port()
    if not _tcp_port_open("127.0.0.1", port):
        return CheckResult(
            name="websocket_connect",
            category="websocket",
            status="skipped",
            severity="warning",
            message="API port not reachable, skipping WebSocket smoke",
        )
    try:
        import asyncio  # noqa: PLC0415, I001
        import websockets  # noqa: PLC0415
    except ImportError:
        return CheckResult(
            name="websocket_connect",
            category="websocket",
            status="skipped",
            severity="warning",
            message="websockets library not installed",
        )

    async def _try_connect() -> bool:
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws/ping",
                open_timeout=3,
                close_timeout=2,
            ):
                return True
        except Exception:  # noqa: BLE001
            return False

    try:
        ok = asyncio.run(_try_connect())
        return CheckResult(
            name="websocket_connect",
            category="websocket",
            status="pass" if ok else "warning",
            severity="warning",
            message="WebSocket endpoint reachable" if ok else "WebSocket connection failed",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="websocket_connect",
            category="websocket",
            status="warning",
            severity="warning",
            message=f"WebSocket smoke error: {exc}",
        )


def check_streamlit() -> CheckResult:
    port = _get_streamlit_port()
    reachable = _tcp_port_open("127.0.0.1", port)
    return CheckResult(
        name="streamlit_port",
        category="streamlit",
        status="pass" if reachable else "warning",
        severity="warning",
        message=f"Streamlit port {port} {'reachable' if reachable else 'not reachable'}",
        details={"port": port},
    )


def check_qmt() -> CheckResult:
    """MiniQMT / xtquant import and connect — opt-in only."""
    try:
        from xtquant import xtdata  # noqa: F401, PLC0415
    except ImportError:
        return CheckResult(
            name="qmt_xtquant_import",
            category="qmt",
            status="skipped",
            severity="warning",
            message="xtquant not importable — QMT not installed in this environment",
        )
    try:
        xtdata.connect()
        return CheckResult(
            name="qmt_xtquant_connect",
            category="qmt",
            status="pass",
            severity="warning",
            message="xtdata.connect() succeeded",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="qmt_xtquant_connect",
            category="qmt",
            status="fail",
            severity="warning",
            message=f"xtdata.connect() failed: {exc}",
        )


def check_local_data_paths() -> CheckResult:
    """Check if CSMAR/EVA/local data paths are accessible."""
    storage = PROJECT_ROOT / "storage"
    data_dir = storage / "data"
    ok_paths = []
    missing_paths = []
    for label, p in [
        ("storage/data", data_dir),
        ("storage/artifacts", storage / "artifacts"),
        ("configs", PROJECT_ROOT / "configs"),
    ]:
        if p.exists():
            ok_paths.append(label)
        else:
            missing_paths.append(label)
    status = "pass" if not missing_paths else "warning"
    return CheckResult(
        name="local_data_paths",
        category="data",
        status=status,
        severity="watch",
        message=f"Accessible: {', '.join(ok_paths)}" if not missing_paths else f"Missing: {', '.join(missing_paths)}",
        details={"accessible": ok_paths, "missing": missing_paths},
    )


def check_pdf_generation() -> CheckResult:
    """Check if PDF generation dependencies are available."""
    missing = []
    for mod in ["playwright", "weasyprint", "markdown"]:
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            missing.append(mod)
    if not missing:
        return CheckResult(
            name="pdf_dependencies",
            category="pdf",
            status="pass",
            severity="warning",
            message="PDF generation dependencies available",
        )
    return CheckResult(
        name="pdf_dependencies",
        category="pdf",
        status="warning",
        severity="warning",
        message=f"Missing PDF dependencies: {', '.join(missing)}",
        details={"missing": missing},
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_verification(args: argparse.Namespace) -> VerificationReport:
    run_id = uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc).isoformat()
    checks: list[CheckResult] = []

    # Always-run checks
    checks.append(check_python_environment())
    checks.append(check_redis())
    checks.append(check_fastapi_health())
    checks.append(check_fastapi_auth())
    checks.append(check_celery_worker())
    checks.append(check_celery_beat())
    checks.append(check_local_data_paths())

    # Opt-in checks
    if args.include_websocket:
        checks.append(check_websocket())
    else:
        checks.append(CheckResult(
            name="websocket_connect", category="websocket", status="skipped",
            severity="warning", message="Pass --include-websocket to enable",
        ))

    if args.include_streamlit:
        checks.append(check_streamlit())
    else:
        checks.append(CheckResult(
            name="streamlit_port", category="streamlit", status="skipped",
            severity="warning", message="Pass --include-streamlit to enable",
        ))

    if args.include_qmt:
        checks.append(check_qmt())
    else:
        checks.append(CheckResult(
            name="qmt_xtquant_connect", category="qmt", status="skipped",
            severity="warning", message="Pass --include-qmt to enable",
        ))

    checks.append(check_pdf_generation())

    # Determine overall status
    summary = {"pass": 0, "warning": 0, "fail": 0, "skipped": 0}
    for c in checks:
        summary[c.status] = summary.get(c.status, 0) + 1

    has_blocker_fail = any(c.status == "fail" and c.severity == "blocker" for c in checks)
    has_warning = any(c.status == "warning" for c in checks)
    has_any_fail = any(c.status == "fail" for c in checks)

    if has_blocker_fail or (args.strict and has_any_fail):
        overall = "fail"
    elif has_warning or has_any_fail:
        overall = "warning"
    else:
        overall = "pass"

    return VerificationReport(
        run_id=run_id,
        generated_at=generated_at,
        overall_status=overall,
        strict=args.strict,
        checks=[asdict(c) for c in checks],
        summary=summary,
        environment={
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "project_root": str(PROJECT_ROOT),
            "executable": sys.executable,
        },
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _generate_markdown(report: VerificationReport) -> str:
    lines = [
        "# Runtime Verification Report",
        "",
        f"- **Run ID**: {report.run_id}",
        f"- **Generated**: {report.generated_at}",
        f"- **Overall**: {report.overall_status}",
        f"- **Strict**: {report.strict}",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|--------|-------||",
    ]
    for status in ("pass", "warning", "fail", "skipped"):
        lines.append(f"| {status} | {report.summary.get(status, 0)} |")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| Name | Category | Status | Severity | Message |")
    lines.append("|------|----------|--------|----------|---------|")
    for c in report.checks:
        lines.append(f"| {c['name']} | {c['category']} | {c['status']} | {c['severity']} | {c['message']} |")
    lines.append("")
    return "\n".join(lines)


def save_artifacts(report: VerificationReport, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    report_dict = asdict(report)

    # summary.json
    (run_dir / "summary.json").write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # summary.md
    (run_dir / "summary.md").write_text(_generate_markdown(report), encoding="utf-8")

    # service_status.json
    service_status = {
        "checks": {c["name"]: c["status"] for c in report.checks},
        "overall": report.overall_status,
    }
    (run_dir / "service_status.json").write_text(
        json.dumps(service_status, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # environment_snapshot.json
    (run_dir / "environment_snapshot.json").write_text(
        json.dumps(report.environment, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # latest.json / latest.md
    (output_dir / "latest.json").write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "latest.md").write_text(_generate_markdown(report), encoding="utf-8")

    return run_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runtime verification matrix")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "storage" / "artifacts" / "verification"),
        help="Output directory for verification artifacts",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as failures",
    )
    parser.add_argument(
        "--include-qmt", action="store_true",
        help="Enable MiniQMT real connection check",
    )
    parser.add_argument(
        "--include-network", action="store_true",
        help="Enable real network checks (reserved for future use)",
    )
    parser.add_argument(
        "--include-streamlit", action="store_true",
        help="Enable Streamlit port check",
    )
    parser.add_argument(
        "--include-websocket", action="store_true",
        help="Enable WebSocket smoke check",
    )
    parser.add_argument(
        "--json-only", action="store_true",
        help="Print JSON to stdout instead of writing artifacts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_verification(args)

    if args.json_only:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        output_dir = Path(args.output_dir)
        run_dir = save_artifacts(report, output_dir)

        # Console output
        print()
        print(f"=== Runtime Verification: {report.overall_status} ===")
        print()
        for c in report.checks:
            icon = {"pass": "OK", "warning": "WARN", "fail": "FAIL", "skipped": "SKIP"}
            print(f"  [{icon.get(c['status'], '??'):4s}] {c['name']}: {c['message']}")
        print()
        print(f"Summary: {report.summary}")
        print(f"Artifacts: {run_dir}")
        print(f"Latest:    {output_dir / 'latest.json'}")
        print()

    # Exit code: blocker fail => 1, strict + any fail => 1, otherwise 0
    has_blocker_fail = any(
        c["status"] == "fail" and c["severity"] == "blocker"
        for c in report.checks
    )
    has_any_fail = any(c["status"] == "fail" for c in report.checks)
    if has_blocker_fail or (args.strict and has_any_fail):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
