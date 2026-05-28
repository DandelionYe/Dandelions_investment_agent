"""Verification script for system settings page.

Checks:
1. PROJECT_ROOT resolves to repo root (not apps/)
2. .env is readable and writable (canary test)
3. apps/.env is NOT created
4. FastAPI/Streamlit health check (warning if not running)

Outputs: summary.json + summary.md to storage/artifacts/verification/system_settings/<timestamp>/
         latest.json + latest.md

Usage:
    python scripts/verify_system_settings_page.py
    python scripts/verify_system_settings_page.py --output-dir storage/artifacts/verification/system_settings
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def verify(output_dir: Path) -> dict:
    from apps.dashboard.settings_config import (
        PROJECT_MARKERS,
        read_env,
        resolve_project_root,
        write_env,
    )

    results: list[dict] = []
    overall_pass = True

    # ── Check 1: PROJECT_ROOT resolution ──────────────────────
    pages_dir = PROJECT_ROOT / "apps" / "dashboard" / "pages"
    try:
        resolved = resolve_project_root(pages_dir)
        root_ok = resolved == PROJECT_ROOT
        results.append({
            "check": "project_root_resolution",
            "status": "pass" if root_ok else "fail",
            "detail": f"Resolved to {resolved}, expected {PROJECT_ROOT}",
        })
        if not root_ok:
            overall_pass = False
    except Exception as exc:
        results.append({
            "check": "project_root_resolution",
            "status": "fail",
            "detail": str(exc),
        })
        overall_pass = False

    # ── Check 2: .env canary write test ───────────────────────
    env_path = PROJECT_ROOT / ".env"
    backup_path = PROJECT_ROOT / ".env.verification_backup"
    canary_key = "_VERIFICATION_CANARY_DELETE_ME"
    canary_value = "canary_test_value"

    if env_path.exists():
        shutil.copy2(env_path, backup_path)
        try:
            write_env(env_path, {canary_key: canary_value}, set())
            after = read_env(env_path)
            if after.get(canary_key) == canary_value:
                results.append({
                    "check": "env_writable",
                    "status": "pass",
                    "detail": f"Successfully wrote and read canary key '{canary_key}'",
                })
            else:
                results.append({
                    "check": "env_writable",
                    "status": "fail",
                    "detail": "Canary key not found after write",
                })
                overall_pass = False

            # Restore original
            shutil.copy2(backup_path, env_path)
            backup_path.unlink(missing_ok=True)

            restored = read_env(env_path)
            if canary_key not in restored:
                results.append({
                    "check": "env_restored",
                    "status": "pass",
                    "detail": "Canary key removed after restore",
                })
            else:
                results.append({
                    "check": "env_restored",
                    "status": "fail",
                    "detail": "Canary key still present after restore!",
                })
                overall_pass = False
        except Exception as exc:
            if backup_path.exists():
                shutil.copy2(backup_path, env_path)
                backup_path.unlink(missing_ok=True)
            results.append({
                "check": "env_writable",
                "status": "fail",
                "detail": str(exc),
            })
            overall_pass = False
    else:
        results.append({
            "check": "env_writable",
            "status": "skip",
            "detail": ".env file does not exist",
        })

    # ── Check 3: apps/.env should NOT exist ───────────────────
    apps_env = PROJECT_ROOT / "apps" / ".env"
    if apps_env.exists():
        results.append({
            "check": "apps_env_not_created",
            "status": "fail",
            "detail": f"apps/.env exists at {apps_env} — this should not happen",
        })
        overall_pass = False
    else:
        results.append({
            "check": "apps_env_not_created",
            "status": "pass",
            "detail": "apps/.env does not exist (correct)",
        })

    # ── Check 4: FastAPI health ───────────────────────────────
    try:
        import requests
        resp = requests.get("http://127.0.0.1:8000/api/v1/health/ready", timeout=3)
        if resp.status_code == 200:
            results.append({
                "check": "fastapi_health",
                "status": "pass",
                "detail": "FastAPI is running",
            })
        else:
            results.append({
                "check": "fastapi_health",
                "status": "warning",
                "detail": f"FastAPI returned {resp.status_code}",
            })
    except Exception:
        results.append({
            "check": "fastapi_health",
            "status": "warning",
            "detail": "FastAPI not running (not required for offline verification)",
        })

    # ── Check 5: Streamlit health ─────────────────────────────
    try:
        import requests
        resp = requests.get("http://127.0.0.1:8501/_stcore/health", timeout=3)
        if resp.status_code == 200:
            results.append({
                "check": "streamlit_health",
                "status": "pass",
                "detail": "Streamlit is running",
            })
        else:
            results.append({
                "check": "streamlit_health",
                "status": "warning",
                "detail": f"Streamlit returned {resp.status_code}",
            })
    except Exception:
        results.append({
            "check": "streamlit_health",
            "status": "warning",
            "detail": "Streamlit not running (not required for offline verification)",
        })

    # ── Summary ───────────────────────────────────────────────
    pass_count = sum(1 for r in results if r["status"] == "pass")
    fail_count = sum(1 for r in results if r["status"] == "fail")
    warn_count = sum(1 for r in results if r["status"] == "warning")
    skip_count = sum(1 for r in results if r["status"] == "skip")

    return {
        "run_id": _timestamp(),
        "generated_at": _now_iso(),
        "overall_status": "pass" if overall_pass else "fail",
        "checks": results,
        "summary": {
            "total": len(results),
            "pass": pass_count,
            "fail": fail_count,
            "warning": warn_count,
            "skip": skip_count,
        },
    }


def write_artifacts(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report["run_id"]

    json_path = output_dir / f"system_settings_{timestamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_json = output_dir / "latest.json"
    latest_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# System Settings Verification Report",
        f"- Generated: {report['generated_at']}",
        f"- Overall: **{report['overall_status'].upper()}**",
        f"- Pass: {report['summary']['pass']} | Fail: {report['summary']['fail']} | "
        f"Warning: {report['summary']['warning']} | Skip: {report['summary']['skip']}",
        "",
        "## Checks",
        "",
    ]
    for c in report["checks"]:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "skip": "SKIP"}.get(c["status"], "?")
        md_lines.append(f"- [{icon}] **{c['check']}**: {c['detail']}")

    md_path = output_dir / f"system_settings_{timestamp}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    latest_md = output_dir / "latest.md"
    latest_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="System settings page verification")
    parser.add_argument(
        "--output-dir",
        default="storage/artifacts/verification/system_settings",
        help="Output directory for artifacts",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report = verify(output_dir)
    json_path, md_path = write_artifacts(report, output_dir)

    print(f"\n{'='*60}")
    print("System Settings Verification")
    print(f"{'='*60}")
    print(f"Overall: {report['overall_status'].upper()}")
    for c in report["checks"]:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "skip": "SKIP"}.get(c["status"], "?")
        print(f"  [{icon}] {c['check']}: {c['detail']}")
    print(f"\nArtifacts: {json_path}")
    print(f"Latest:    {output_dir / 'latest.json'}")

    if report["overall_status"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
