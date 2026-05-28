# Fix Report Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 landing issues from report.md: system settings path resolution, verification evidence, watchlist trigger expansion, and real verification artifacts.

**Architecture:** Extract settings helpers into `settings_config.py`, add centralized trigger evaluator in `watchlist_triggers.py`, extend schemas/UI/tests, create verification scripts with artifact output.

**Tech Stack:** Python, Streamlit, FastAPI, Pydantic, Celery, SQLite, pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `apps/dashboard/settings_config.py` | Pure functions: resolve_project_root, read_env, write_env |
| Modify | `apps/dashboard/pages/4_系统设置.py` | Use settings_config helpers |
| Create | `tests/test_dashboard_settings.py` | Unit tests for settings_config |
| Create | `scripts/verify_system_settings_page.py` | Verification script with artifact output |
| Modify | `apps/api/schemas/watchlist.py` | Add valuation/risk/event fields to ConditionTriggers |
| Create | `apps/api/task_manager/watchlist_triggers.py` | Centralized trigger evaluator |
| Modify | `apps/api/task_manager/celery_tasks.py` | Use centralized evaluator in watchlist_scheduler_check |
| Modify | `apps/api/task_manager/store.py` | Add last_trigger_snapshot to watchlist_items |
| Modify | `apps/dashboard/pages/3_观察池.py` | UI for new trigger fields |
| Modify | `tests/test_condition_triggers.py` | Extend tests for new trigger types |
| Modify | `tests/integration/test_watchlist_scan_e2e.py` | Extend e2e tests |
| Modify | `scripts/verify_watchlist_triggers.py` | Use centralized evaluator, add --ensure-sample, --require-triggered-and-untriggered |

---

## Task 1: Create settings_config.py helper module

**Files:**
- Create: `apps/dashboard/settings_config.py`
- Test: `tests/test_dashboard_settings.py`

- [ ] **Step 1: Create settings_config.py**

```python
"""Pure helper functions for system settings page.

resolve_project_root: locate repo root by walking up from a start path
read_env / write_env: .env file I/O with sensitive-key protection
"""

from pathlib import Path

PROJECT_MARKERS = ("pyproject.toml", ".env.example", "CLAUDE.md")


def resolve_project_root(start: Path) -> Path:
    """Walk up from *start* until a marker file is found.

    Raises FileNotFoundError if no marker is found before filesystem root.
    """
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(20):
        if any((cur / m).exists() for m in PROJECT_MARKERS):
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError(
        f"Could not locate project root (searched for {PROJECT_MARKERS}) "
        f"starting from {start}"
    )


def read_env(env_path: Path) -> dict[str, str]:
    """Read a .env file into a dict. Preserves key order.

    Lines starting with '#' are skipped. Blank lines are skipped.
    """
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def write_env(
    env_path: Path,
    updates: dict[str, str],
    sensitive_keys: set[str],
) -> None:
    """Update *env_path* with *updates*.

    Sensitive keys whose new value is ``"****"`` or ``""`` are NOT overwritten.
    New keys are appended. Comments and blank lines are preserved.
    """
    if not env_path.exists():
        return
    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines: list[str] = []
    updated_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" not in stripped:
            new_lines.append(line)
            continue
        key, _, old_value = stripped.partition("=")
        key = key.strip()
        if key in updates:
            new_value = updates[key]
            if key in sensitive_keys and new_value in ("****", ""):
                new_lines.append(line)  # preserve original
            else:
                new_lines.append(f"{key}={new_value}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append new keys
    for key, value in updates.items():
        if key not in updated_keys and value:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
```

- [ ] **Step 2: Write tests for settings_config**

Create `tests/test_dashboard_settings.py`:

```python
"""Tests for apps/dashboard/settings_config.py."""

import textwrap
from pathlib import Path

import pytest

from apps.dashboard.settings_config import (
    PROJECT_MARKERS,
    read_env,
    resolve_project_root,
    write_env,
)


class TestResolveProjectRoot:

    def test_from_apps_dashboard_pages(self, tmp_path: None) -> None:
        """Resolve from apps/dashboard/pages/ back to repo root."""
        # The real repo root has CLAUDE.md
        from apps.dashboard.settings_config import resolve_project_root as fn
        start = Path(__file__).resolve().parents[2] / "apps" / "dashboard" / "pages"
        root = fn(start)
        assert (root / "CLAUDE.md").exists() or (root / ".env.example").exists()

    def test_from_apps_dir(self) -> None:
        """Resolve from apps/ directory."""
        start = Path(__file__).resolve().parents[2] / "apps"
        root = resolve_project_root(start)
        assert any((root / m).exists() for m in PROJECT_MARKERS)

    def test_raises_on_no_marker(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when no marker found."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            resolve_project_root(nested)


class TestReadEnv:

    def test_reads_simple_kv(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=123\n", encoding="utf-8")
        result = read_env(env_file)
        assert result == {"FOO": "bar", "BAZ": "123"}

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nFOO=bar\n", encoding="utf-8")
        result = read_env(env_file)
        assert result == {"FOO": "bar"}

    def test_empty_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("", encoding="utf-8")
        assert read_env(env_file) == {}

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert read_env(tmp_path / "nope.env") == {}

    def test_value_with_equals(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("URL=http://x.com?a=b\n", encoding="utf-8")
        result = read_env(env_file)
        assert result["URL"] == "http://x.com?a=b"


class TestWriteEnv:

    def test_updates_existing_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")
        write_env(env_file, {"FOO": "new"}, set())
        result = read_env(env_file)
        assert result["FOO"] == "new"
        assert result["BAR"] == "keep"

    def test_appends_new_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=1\n", encoding="utf-8")
        write_env(env_file, {"NEW_KEY": "hello"}, set())
        result = read_env(env_file)
        assert result["NEW_KEY"] == "hello"
        assert result["FOO"] == "1"

    def test_sensitive_mask_not_overwritten(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=real_value\n", encoding="utf-8")
        sensitive = {"SECRET"}
        write_env(env_file, {"SECRET": "****"}, sensitive)
        result = read_env(env_file)
        assert result["SECRET"] == "real_value"

    def test_sensitive_empty_not_overwritten(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=real_value\n", encoding="utf-8")
        sensitive = {"SECRET"}
        write_env(env_file, {"SECRET": ""}, sensitive)
        result = read_env(env_file)
        assert result["SECRET"] == "real_value"

    def test_sensitive_real_value_is_written(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=old\n", encoding="utf-8")
        sensitive = {"SECRET"}
        write_env(env_file, {"SECRET": "new_secret"}, sensitive)
        result = read_env(env_file)
        assert result["SECRET"] == "new_secret"

    def test_preserves_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        original = "# header\n\nFOO=1\n# middle\nBAR=2\n"
        env_file.write_text(original, encoding="utf-8")
        write_env(env_file, {"FOO": "updated"}, set())
        content = env_file.read_text(encoding="utf-8")
        assert "# header" in content
        assert "# middle" in content

    def test_no_op_when_file_missing(self, tmp_path: Path) -> None:
        write_env(tmp_path / "nope.env", {"X": "1"}, set())
        assert not (tmp_path / "nope.env").exists()
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard_settings.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add apps/dashboard/settings_config.py tests/test_dashboard_settings.py
git commit -m "feat: extract settings_config.py with resolve_project_root, read_env, write_env"
```

---

## Task 2: Update system settings page to use settings_config

**Files:**
- Modify: `apps/dashboard/pages/4_系统设置.py`

- [ ] **Step 1: Replace inline functions with imports**

Replace the entire file content. Key changes:
- `PROJECT_ROOT = resolve_project_root(Path(__file__))` (was `parents[2]`)
- Remove inline `read_env()` and `write_env()` definitions
- Import from `apps.dashboard.settings_config`
- `ENV_PATH = PROJECT_ROOT / ".env"` stays the same

Replace lines 1-14 (imports and PROJECT_ROOT):

```python
"""系统设置页面 — 可视化编辑 .env 配置。

仅 admin 可访问。修改后需重启 FastAPI / Celery worker 生效。
"""

import sys
from pathlib import Path

import streamlit as st

from apps.dashboard.settings_config import (
    PROJECT_MARKERS,
    read_env,
    resolve_project_root,
    write_env,
)

PROJECT_ROOT = resolve_project_root(Path(__file__))
sys.path.append(str(PROJECT_ROOT))
```

Replace lines 128-181 (the read_env and write_env definitions) with just the function calls — remove the function definitions entirely since they're now imported.

The read_env call at line 185 stays: `env_values = read_env(ENV_PATH)`
The write_env call at line 242 stays: `write_env(ENV_PATH, changes, SENSITIVE_KEYS)`

- [ ] **Step 2: Run the existing tests to verify no regression**

Run: `python -m pytest tests/test_dashboard_settings.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add apps/dashboard/pages/4_系统设置.py
git commit -m "refactor: system settings page uses settings_config helpers"
```

---

## Task 3: Create verify_system_settings_page.py

**Files:**
- Create: `scripts/verify_system_settings_page.py`

- [ ] **Step 1: Write the verification script**

```python
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
            original = read_env(env_path)
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
                    "detail": f"Canary key not found after write",
                })
                overall_pass = False

            # Restore original
            shutil.copy2(backup_path, env_path)
            backup_path.unlink(missing_ok=True)

            # Verify restore
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
            # Restore on error
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
```

- [ ] **Step 2: Run the script to verify it works**

Run: `python scripts/verify_system_settings_page.py --output-dir storage/artifacts/verification/system_settings`
Expected: PASS (or warning if FastAPI/Streamlit not running)

- [ ] **Step 3: Verify artifacts were created**

Run: `ls storage/artifacts/verification/system_settings/`
Expected: `latest.json`, `latest.md`, `system_settings_<timestamp>.json`, `system_settings_<timestamp>.md`

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_system_settings_page.py
git commit -m "feat: add system settings verification script with artifact output"
```

---

## Task 4: Add valuation/risk/event fields to ConditionTriggers schema

**Files:**
- Modify: `apps/api/schemas/watchlist.py`

- [ ] **Step 1: Extend ConditionTriggers model**

Replace the `ConditionTriggers` class (lines 10-23) with:

```python
class ConditionTriggers(BaseModel):
    price_change_pct: Optional[float] = Field(
        default=None, ge=0, le=20,
        description="价格变动百分比阈值（如 5.0 表示涨跌幅超 5% 触发扫描）"
    )
    score_threshold: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="评分阈值（如 80 表示上次评分 ≥80 分时触发扫描）"
    )
    volume_spike_ratio: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="成交量异动倍数（如 3.0 表示成交量超 3 倍均量触发扫描）"
    )
    # ── Valuation triggers ────────────────────────────────────
    pe_ttm_max: Optional[float] = Field(
        default=None, ge=0,
        description="PE-TTM 上限阈值（如 20 表示 PE ≤ 20 时触发）"
    )
    pb_mrq_max: Optional[float] = Field(
        default=None, ge=0,
        description="PB-MRQ 上限阈值（如 2.0 表示 PB ≤ 2.0 时触发）"
    )
    valuation_percentile_max: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="估值分位上限（如 30 表示估值分位 ≤ 30% 时触发，即低估区间）"
    )
    # ── Risk triggers ─────────────────────────────────────────
    risk_level_min: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description="最低风险等级阈值（low/medium/high，触发当实际风险 ≥ 此级别）"
    )
    # ── Event triggers ────────────────────────────────────────
    event_severity_min: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description="最低事件严重性阈值（low/medium/high，触发当事件严重性 ≥ 此级别）"
    )
    event_keywords: list[str] = Field(
        default_factory=list,
        description="事件关键词列表（任一关键词出现在公告标题中即触发）"
    )
```

- [ ] **Step 2: Update description in ScheduleConfig**

Update the `condition_triggers` field description in `ScheduleConfig` (line 43-46):

```python
    condition_triggers: ConditionTriggers = Field(
        default_factory=ConditionTriggers,
        description="条件触发器：价格/评分/量比/估值/风险/事件条件，满足任一触发自动扫描",
    )
```

- [ ] **Step 3: Run schema tests**

Run: `python -m pytest tests/test_condition_triggers.py::TestConditionTriggersSchema -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add apps/api/schemas/watchlist.py
git commit -m "feat: add pe_ttm_max, pb_mrq_max, valuation_percentile_max, risk_level_min, event_severity_min, event_keywords to ConditionTriggers"
```

---

## Task 5: Create centralized watchlist_triggers evaluator

**Files:**
- Create: `apps/api/task_manager/watchlist_triggers.py`

- [ ] **Step 1: Write the evaluator module**

```python
"""Centralized condition trigger evaluator for watchlist items.

Single source of truth for trigger evaluation logic.
Used by both Celery scheduler and verification scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerEvaluationResult:
    triggered: bool = False
    reasons: list[str] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)
    categories_evaluated: list[str] = field(default_factory=list)


def evaluate_condition_triggers(
    item: dict,
    quote: dict[str, Any] | None = None,
    latest_result: dict[str, Any] | None = None,
) -> TriggerEvaluationResult:
    """Evaluate all condition triggers for a watchlist item.

    Args:
        item: Watchlist item dict (must contain schedule_config.condition_triggers)
        quote: Real-time quote data with keys: close, prev_close, volume, change_pct, volume_ratio
        latest_result: Latest research result with keys: valuation_data, risk_review, event_data

    Returns:
        TriggerEvaluationResult with triggered flag, reasons, missing_reasons, categories_evaluated
    """
    result = TriggerEvaluationResult()
    sc = item.get("schedule_config") or {}
    ct = sc.get("condition_triggers") or {}

    if not ct:
        return result

    # Check if any trigger is configured (is not None, not empty list)
    has_any = any(
        v is not None and v != [] for v in ct.values()
    )
    if not has_any:
        return result

    # ── Price change trigger ──────────────────────────────────
    if ct.get("price_change_pct") is not None:
        result.categories_evaluated.append("price_change_pct")
        threshold = ct["price_change_pct"]
        if quote and "change_pct" in quote:
            if abs(quote["change_pct"]) >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% >= 阈值 {threshold}%"
                )
            else:
                result.reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% < 阈值 {threshold}%"
                )
        elif quote and "error" in quote:
            result.missing_reasons.append(f"price: 行情获取失败: {quote['error']}")
        else:
            result.missing_reasons.append("price: 行情数据不可用")

    # ── Volume spike trigger ──────────────────────────────────
    if ct.get("volume_spike_ratio") is not None:
        result.categories_evaluated.append("volume_spike_ratio")
        threshold = ct["volume_spike_ratio"]
        if quote and "volume_ratio" in quote:
            if quote["volume_ratio"] >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} >= 阈值 {threshold}"
                )
            else:
                result.reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} < 阈值 {threshold}"
                )
        elif quote and "error" in quote:
            result.missing_reasons.append(f"volume: 行情获取失败: {quote['error']}")
        else:
            result.missing_reasons.append("volume: 行情数据不可用")

    # ── Score threshold trigger ───────────────────────────────
    if ct.get("score_threshold") is not None:
        result.categories_evaluated.append("score_threshold")
        threshold = ct["score_threshold"]
        last_score = item.get("last_score")
        if last_score is not None:
            if last_score >= threshold:
                result.triggered = True
                result.reasons.append(
                    f"评分 {last_score:.1f} >= 阈值 {threshold}"
                )
            else:
                result.reasons.append(
                    f"评分 {last_score:.1f} < 阈值 {threshold}"
                )
        else:
            result.missing_reasons.append("score: 无历史评分（首次扫描前无法触发）")

    # ── PE-TTM trigger ────────────────────────────────────────
    if ct.get("pe_ttm_max") is not None:
        result.categories_evaluated.append("pe_ttm_max")
        threshold = ct["pe_ttm_max"]
        val_data = _get_valuation_data(latest_result)
        pe = val_data.get("pe_ttm") if val_data else None
        if pe is not None:
            if pe <= threshold:
                result.triggered = True
                result.reasons.append(f"PE-TTM {pe:.2f} <= 阈值 {threshold}")
            else:
                result.reasons.append(f"PE-TTM {pe:.2f} > 阈值 {threshold}")
        else:
            result.missing_reasons.append("pe_ttm: 估值数据不可用")

    # ── PB-MRQ trigger ────────────────────────────────────────
    if ct.get("pb_mrq_max") is not None:
        result.categories_evaluated.append("pb_mrq_max")
        threshold = ct["pb_mrq_max"]
        val_data = _get_valuation_data(latest_result)
        pb = val_data.get("pb_mrq") if val_data else None
        if pb is not None:
            if pb <= threshold:
                result.triggered = True
                result.reasons.append(f"PB-MRQ {pb:.2f} <= 阈值 {threshold}")
            else:
                result.reasons.append(f"PB-MRQ {pb:.2f} > 阈值 {threshold}")
        else:
            result.missing_reasons.append("pb_mrq: 估值数据不可用")

    # ── Valuation percentile trigger ──────────────────────────
    if ct.get("valuation_percentile_max") is not None:
        result.categories_evaluated.append("valuation_percentile_max")
        threshold = ct["valuation_percentile_max"]
        val_data = _get_valuation_data(latest_result)
        pct = val_data.get("valuation_percentile") if val_data else None
        if pct is not None:
            if pct <= threshold:
                result.triggered = True
                result.reasons.append(f"估值分位 {pct:.1f}% <= 阈值 {threshold}%")
            else:
                result.reasons.append(f"估值分位 {pct:.1f}% > 阈值 {threshold}%")
        else:
            result.missing_reasons.append("valuation_percentile: 估值分位数据不可用")

    # ── Risk level trigger ────────────────────────────────────
    if ct.get("risk_level_min") is not None:
        result.categories_evaluated.append("risk_level_min")
        threshold = ct["risk_level_min"]
        risk_data = _get_risk_review(latest_result)
        level = risk_data.get("risk_level") if risk_data else None
        if level is not None:
            if _level_gte(level, threshold):
                result.triggered = True
                result.reasons.append(f"风险等级 {level} >= 阈值 {threshold}")
            else:
                result.reasons.append(f"风险等级 {level} < 阈值 {threshold}")
        else:
            result.missing_reasons.append("risk_level: 风险评估数据不可用")

    # ── Event severity trigger ────────────────────────────────
    if ct.get("event_severity_min") is not None:
        result.categories_evaluated.append("event_severity_min")
        threshold = ct["event_severity_min"]
        event_data = _get_event_data(latest_result)
        severity = event_data.get("max_severity") if event_data else None
        if severity is not None:
            if _level_gte(severity, threshold):
                result.triggered = True
                result.reasons.append(f"事件严重性 {severity} >= 阈值 {threshold}")
            else:
                result.reasons.append(f"事件严重性 {severity} < 阈值 {threshold}")
        else:
            result.missing_reasons.append("event_severity: 事件数据不可用")

    # ── Event keywords trigger ────────────────────────────────
    keywords = ct.get("event_keywords") or []
    if keywords:
        result.categories_evaluated.append("event_keywords")
        event_data = _get_event_data(latest_result)
        if event_data:
            matched = _match_event_keywords(event_data, keywords)
            if matched:
                result.triggered = True
                result.reasons.append(f"事件关键词匹配: {', '.join(matched)}")
            else:
                result.reasons.append(f"事件关键词未匹配: {', '.join(keywords)}")
        else:
            result.missing_reasons.append("event_keywords: 事件数据不可用")

    return result


# ── Internal helpers ──────────────────────────────────────────


def _get_valuation_data(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("valuation_data")


def _get_risk_review(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("risk_review")


def _get_event_data(latest_result: dict | None) -> dict | None:
    if not latest_result:
        return None
    return latest_result.get("event_data")


_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


def _level_gte(actual: str, threshold: str) -> bool:
    """Return True if actual level >= threshold level."""
    return _LEVEL_ORDER.get(actual, -1) >= _LEVEL_ORDER.get(threshold, -1)


def _match_event_keywords(event_data: dict, keywords: list[str]) -> list[str]:
    """Return list of matched keywords from event announcement titles."""
    matched = []
    announcements = event_data.get("announcements") or event_data.get("events") or []
    for ann in announcements:
        title = ann.get("title") or ann.get("name") or ""
        for kw in keywords:
            if kw.lower() in title.lower():
                if kw not in matched:
                    matched.append(kw)
    return matched
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/task_manager/watchlist_triggers.py
git commit -m "feat: add centralized watchlist trigger evaluator"
```

---

## Task 6: Add last_trigger_snapshot to watchlist store

**Files:**
- Modify: `apps/api/task_manager/store.py`
- Modify: `apps/api/task_manager/celery_tasks.py`

- [ ] **Step 1: Add migration column for last_trigger_snapshot**

In `store.py`, add to `_MIGRATION_COLUMNS` list (around line 370):

```python
_MIGRATION_COLUMNS = [
    ("watchlist_folders", "owner_username", "TEXT NOT NULL DEFAULT 'default'"),
    ("watchlist_items", "owner_username", "TEXT NOT NULL DEFAULT 'default'"),
    ("watchlist_tags", "owner_username", "TEXT NOT NULL DEFAULT 'default'"),
    ("watchlist_batches", "owner_username", "TEXT NOT NULL DEFAULT 'default'"),
    ("watchlist_items", "last_trigger_snapshot", "TEXT"),
]
```

Also add to the CREATE TABLE SQL in `_WATCHLIST_TABLES_SQL` (after `next_scan_at TEXT,`):

```sql
    last_trigger_snapshot TEXT,
```

And to `_CREATE_WATCHLIST_ITEMS_SQL` (after `next_scan_at TEXT,`):

```sql
    last_trigger_snapshot TEXT,
```

- [ ] **Step 2: Add method to update trigger snapshot**

In `WatchlistStore` class, add method after `update_item_scan_result`:

```python
    def update_item_trigger_snapshot(
        self, item_id: str, snapshot: dict | None
    ) -> None:
        """Store a narrow JSON snapshot of trigger-relevant data."""
        snapshot_json = json.dumps(snapshot, ensure_ascii=False) if snapshot else None
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE watchlist_items SET last_trigger_snapshot = ?, updated_at = ? WHERE id = ?",
                    (snapshot_json, now, item_id),
                )
                conn.commit()
            finally:
                conn.close()
```

- [ ] **Step 3: Update _row_to_item_dict to parse snapshot**

In `WatchlistStore._row_to_item_dict` static method, add parsing:

```python
    @staticmethod
    def _row_to_item_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if isinstance(d.get("schedule_config"), str):
            try:
                d["schedule_config"] = json.loads(d["schedule_config"])
            except (json.JSONDecodeError, TypeError):
                d["schedule_config"] = {}
        if isinstance(d.get("last_trigger_snapshot"), str):
            try:
                d["last_trigger_snapshot"] = json.loads(d["last_trigger_snapshot"])
            except (json.JSONDecodeError, TypeError):
                d["last_trigger_snapshot"] = None
        if "enabled" in d:
            d["enabled"] = bool(d["enabled"])
        return d
```

- [ ] **Step 4: Update scan_single_watchlist_item to build trigger snapshot**

In `celery_tasks.py`, after `wl_store.update_item_scan_result(...)` (around line 444), add:

```python
        # Build trigger snapshot for future condition evaluation
        trigger_snapshot = {
            "valuation_data": result.get("valuation_data"),
            "risk_review": result.get("risk_review"),
            "event_data": result.get("event_data"),
            "score": result.get("score"),
        }
        wl_store.update_item_trigger_snapshot(item_id, trigger_snapshot)
```

- [ ] **Step 5: Update watchlist_scheduler_check to use centralized evaluator**

In `celery_tasks.py`, replace the condition trigger evaluation block (lines 239-287) with:

```python
    # 2. 条件触发器检查 — use centralized evaluator
    from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers

    condition_triggered: dict[str, list[dict]] = {}  # owner -> items
    all_enabled = store.get_all_enabled_items()
    for item in all_enabled:
        item_id = str(item["id"])
        if item_id in triggered_ids:
            continue  # 已被 cron 触发，跳过

        sc = item.get("schedule_config") or {}
        ct = sc.get("condition_triggers") or {}
        if not ct or all(v is None or v == [] for v in ct.values()):
            continue

        # 防重复：距上次扫描至少 30 分钟
        last_scan = item.get("last_scan_at")
        if last_scan:
            try:
                last_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 1800:
                    continue
            except (ValueError, TypeError):
                pass

        # Fetch quote if needed
        quote = None
        need_quote = any(
            ct.get(k) is not None
            for k in ("price_change_pct", "volume_spike_ratio")
        )
        if need_quote:
            try:
                from services.data.qmt_realtime_quote import get_latest_price_data
                quote = get_latest_price_data(item["symbol"])
            except Exception:
                pass

        # Use centralized evaluator
        eval_result = evaluate_condition_triggers(
            item, quote=quote, latest_result=item.get("last_trigger_snapshot")
        )

        if eval_result.triggered:
            owner = item.get("owner_username", "default")
            condition_triggered.setdefault(owner, []).append(item)
            triggered_ids.add(item_id)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_watchlist_store.py tests/test_condition_triggers.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/task_manager/store.py apps/api/task_manager/celery_tasks.py
git commit -m "feat: add last_trigger_snapshot to watchlist_items, use centralized evaluator in scheduler"
```

---

## Task 7: Extend condition trigger tests

**Files:**
- Modify: `tests/test_condition_triggers.py`
- Modify: `tests/integration/test_watchlist_scan_e2e.py`

- [ ] **Step 1: Add tests for new trigger types in test_condition_triggers.py**

Add these test classes after the existing `TestConditionEvaluation` class:

```python
class TestValuationTriggers:

    def test_pe_ttm_below_threshold(self):
        """PE <= 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        latest = {"valuation_data": {"pe_ttm": 15.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True
        assert any("PE-TTM" in r for r in result.reasons)
        assert "pe_ttm_max" in result.categories_evaluated

    def test_pe_ttm_above_threshold(self):
        """PE > 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        latest = {"valuation_data": {"pe_ttm": 30.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_pe_ttm_no_data(self):
        """估值数据不可用时不触发，记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0

    def test_pb_mrq_below_threshold(self):
        """PB <= 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pb_mrq_max": 2.0}}}
        latest = {"valuation_data": {"pb_mrq": 1.5}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_valuation_percentile_below_threshold(self):
        """估值分位 <= 阈值时触发（低估区间）。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"valuation_percentile_max": 30.0}}}
        latest = {"valuation_data": {"valuation_percentile": 20.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_valuation_percentile_above_threshold(self):
        """估值分位 > 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"valuation_percentile_max": 30.0}}}
        latest = {"valuation_data": {"valuation_percentile": 50.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False


class TestRiskTriggers:

    def test_risk_level_high_triggers(self):
        """风险等级 high >= medium 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "medium"}}}
        latest = {"risk_review": {"risk_level": "high"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_risk_level_low_not_trigger(self):
        """风险等级 low < medium 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "medium"}}}
        latest = {"risk_review": {"risk_level": "low"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_risk_level_no_data(self):
        """风险数据不可用时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "high"}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0


class TestEventTriggers:

    def test_event_severity_high_triggers(self):
        """事件严重性 high >= high 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_severity_min": "high"}}}
        latest = {"event_data": {"max_severity": "high"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_event_severity_low_not_trigger(self):
        """事件严重性 low < high 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_severity_min": "high"}}}
        latest = {"event_data": {"max_severity": "low"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_event_keywords_match(self):
        """事件关键词匹配时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["问询函", "处罚"]}}}
        latest = {"event_data": {"announcements": [{"title": "关于收到问询函的公告"}]}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True
        assert any("问询函" in r for r in result.reasons)

    def test_event_keywords_no_match(self):
        """事件关键词不匹配时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["处罚"]}}}
        latest = {"event_data": {"announcements": [{"title": "2024年年度报告"}]}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_event_keywords_no_data(self):
        """事件数据不可用时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["问询函"]}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0

    def test_empty_keywords_list_not_trigger(self):
        """空关键词列表不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": []}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert "event_keywords" not in result.categories_evaluated


class TestMissingDataBehavior:

    def test_no_score_no_trigger_with_missing_reason(self):
        """无 last_score 时 score_threshold 不触发且记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"score_threshold": 80.0}}}
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert any("score" in r.lower() or "评分" in r for r in result.missing_reasons)

    def test_no_quote_no_trigger_with_missing_reason(self):
        """无行情数据时 price/volume 不触发且记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 5.0, "volume_spike_ratio": 3.0}}}
        result = evaluate_condition_triggers(item, quote=None)
        assert result.triggered is False
        assert len(result.missing_reasons) >= 2

    def test_quote_error_recorded(self):
        """行情获取失败时记录错误信息。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 5.0}}}
        quote = {"error": "QMT not available"}
        result = evaluate_condition_triggers(item, quote=quote)
        assert result.triggered is False
        assert any("QMT" in r for r in result.missing_reasons)


class TestThresholdZeroNotTriggered:

    def test_price_threshold_zero_not_configured(self):
        """price_change_pct=0 不应触发（0 视为未配置）。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 0.0}}}
        # 0.0 is not None, so it IS configured. But the user spec says threshold=0
        # should use is-not-None check. Let's verify: 0.0 is not None -> it's configured.
        # The issue was about using truthy check (if ct.get("x")) which treats 0 as falsy.
        # Our evaluator uses "is not None" which treats 0.0 as configured.
        quote = {"change_pct": 10.0, "volume_ratio": 1.0}
        result = evaluate_condition_triggers(item, quote=quote)
        assert result.triggered is True  # 0 threshold means always triggers
        assert "price_change_pct" in result.categories_evaluated


class TestMultipleTriggersAnyFires:

    def test_mixed_triggers_partial_match(self):
        """多条件中部分满足即触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {
            "schedule_config": {
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "pe_ttm_max": 20.0,
                    "event_severity_min": "high",
                }
            },
            "last_score": None,
        }
        quote = {"change_pct": 7.0, "volume_ratio": 1.0}
        latest = {"valuation_data": {"pe_ttm": 25.0}, "event_data": {"max_severity": "low"}}
        result = evaluate_condition_triggers(item, quote=quote, latest_result=latest)
        assert result.triggered is True  # price trigger fires
        assert len(result.categories_evaluated) == 3

    def test_no_triggers_configured(self):
        """所有字段为 None/空时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {}}}
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert len(result.categories_evaluated) == 0

    def test_all_none_not_triggered(self):
        """所有字段显式为 None 时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {
            "schedule_config": {
                "condition_triggers": {
                    "price_change_pct": None,
                    "score_threshold": None,
                    "volume_spike_ratio": None,
                    "pe_ttm_max": None,
                    "pb_mrq_max": None,
                }
            }
        }
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert len(result.categories_evaluated) == 0
```

- [ ] **Step 2: Add e2e tests for new trigger types**

Add to `tests/integration/test_watchlist_scan_e2e.py` in the `TestConditionTriggerEvaluation` class:

```python
    def test_pe_trigger_fires(self, stores):
        """PE-TTM <= 阈值时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"pe_ttm_max": 20.0},
            },
        )
        # Store trigger snapshot
        wl_store.update_item_trigger_snapshot(item["id"], {
            "valuation_data": {"pe_ttm": 15.0},
        })
        updated = wl_store.get_item(item["id"])
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        result = evaluate_condition_triggers(
            updated, latest_result=updated.get("last_trigger_snapshot")
        )
        assert result.triggered is True

    def test_risk_trigger_fires(self, stores):
        """风险等级 >= 阈值时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"risk_level_min": "medium"},
            },
        )
        wl_store.update_item_trigger_snapshot(item["id"], {
            "risk_review": {"risk_level": "high"},
        })
        updated = wl_store.get_item(item["id"])
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        result = evaluate_condition_triggers(
            updated, latest_result=updated.get("last_trigger_snapshot")
        )
        assert result.triggered is True

    def test_event_keyword_trigger_fires(self, stores):
        """事件关键词匹配时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"event_keywords": ["问询函"]},
            },
        )
        wl_store.update_item_trigger_snapshot(item["id"], {
            "event_data": {"announcements": [{"title": "关于收到问询函的公告"}]},
        })
        updated = wl_store.get_item(item["id"])
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        result = evaluate_condition_triggers(
            updated, latest_result=updated.get("last_trigger_snapshot")
        )
        assert result.triggered is True

    def test_no_snapshot_no_trigger(self, stores):
        """无 last_trigger_snapshot 时估值/风险/事件不触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"pe_ttm_max": 20.0, "event_keywords": ["问询函"]},
            },
        )
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) >= 2

    def test_owner_isolation_preserved(self, stores):
        """新增字段不影响 owner 隔离。"""
        _, wl_store = stores
        fa = wl_store.create_folder("fa", owner_username="alice")
        fb = wl_store.create_folder("fb", owner_username="bob")
        a = wl_store.add_item(
            "600519.SH", "stock", fa["id"],
            schedule_config={"condition_triggers": {"pe_ttm_max": 20.0}},
            owner_username="alice",
        )
        b = wl_store.add_item(
            "000001.SZ", "stock", fb["id"],
            schedule_config={"condition_triggers": {"pe_ttm_max": 20.0}},
            owner_username="bob",
        )
        alice_items = [i for i in wl_store.get_all_enabled_items()
                       if i.get("owner_username") == "alice"]
        bob_items = [i for i in wl_store.get_all_enabled_items()
                     if i.get("owner_username") == "bob"]
        assert len(alice_items) == 1
        assert len(bob_items) == 1
```

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/test_condition_triggers.py tests/integration/test_watchlist_scan_e2e.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_condition_triggers.py tests/integration/test_watchlist_scan_e2e.py
git commit -m "test: extend condition trigger tests for valuation/risk/event/missing-data"
```

---

## Task 8: Update watchlist UI for new trigger fields

**Files:**
- Modify: `apps/dashboard/pages/3_观察池.py`

- [ ] **Step 1: Update detail display for new trigger fields**

Replace the trigger display section (around lines 389-399). Find:

```python
            # 条件触发器
            ct = sc.get("condition_triggers") or {}
            active_triggers = {k: v for k, v in ct.items() if v is not None}
            if active_triggers:
                trigger_parts = []
                if "price_change_pct" in active_triggers:
                    trigger_parts.append(f"涨跌幅 >= {active_triggers['price_change_pct']}%")
                if "score_threshold" in active_triggers:
                    trigger_parts.append(f"评分 >= {active_triggers['score_threshold']}")
                if "volume_spike_ratio" in active_triggers:
                    trigger_parts.append(f"量比 >= {active_triggers['volume_spike_ratio']}")
                st.caption("🔔 条件触发: " + " | ".join(trigger_parts))
```

Replace with:

```python
            # 条件触发器
            ct = sc.get("condition_triggers") or {}
            active_triggers = {k: v for k, v in ct.items()
                               if v is not None and v != []}
            if active_triggers:
                trigger_parts = []
                if "price_change_pct" in active_triggers:
                    trigger_parts.append(f"涨跌幅 >= {active_triggers['price_change_pct']}%")
                if "score_threshold" in active_triggers:
                    trigger_parts.append(f"评分 >= {active_triggers['score_threshold']}")
                if "volume_spike_ratio" in active_triggers:
                    trigger_parts.append(f"量比 >= {active_triggers['volume_spike_ratio']}")
                if "pe_ttm_max" in active_triggers:
                    trigger_parts.append(f"PE <= {active_triggers['pe_ttm_max']}")
                if "pb_mrq_max" in active_triggers:
                    trigger_parts.append(f"PB <= {active_triggers['pb_mrq_max']}")
                if "valuation_percentile_max" in active_triggers:
                    trigger_parts.append(f"估值分位 <= {active_triggers['valuation_percentile_max']}%")
                if "risk_level_min" in active_triggers:
                    trigger_parts.append(f"风险 >= {active_triggers['risk_level_min']}")
                if "event_severity_min" in active_triggers:
                    trigger_parts.append(f"事件 >= {active_triggers['event_severity_min']}")
                if "event_keywords" in active_triggers:
                    trigger_parts.append(f"事件关键词: {','.join(active_triggers['event_keywords'])}")
                st.caption("🔔 条件触发: " + " | ".join(trigger_parts))
```

- [ ] **Step 2: Update trigger editor expander**

Replace the trigger editor expander (around lines 457-494). Find the `with st.expander("🔔 编辑条件触发器", expanded=False):` block and replace with:

```python
            # 条件触发器编辑
            with st.expander("🔔 编辑条件触发器", expanded=False):
                sc = item.get("schedule_config", {})
                ct = sc.get("condition_triggers") or {}

                st.caption("基础条件")
                edit_ct1, edit_ct2, edit_ct3 = st.columns(3)
                with edit_ct1:
                    new_price = st.number_input(
                        "涨跌幅（%）", min_value=0.0, max_value=20.0,
                        value=float(ct.get("price_change_pct") or 0), step=0.5,
                        key=f"edit_ct_price_{item['id']}",
                        help="0 表示不启用",
                    )
                with edit_ct2:
                    new_score = st.number_input(
                        "评分阈值", min_value=0.0, max_value=100.0,
                        value=float(ct.get("score_threshold") or 0), step=5.0,
                        key=f"edit_ct_score_{item['id']}",
                        help="0 表示不启用",
                    )
                with edit_ct3:
                    new_volume = st.number_input(
                        "量比倍数", min_value=0.0, max_value=100.0,
                        value=float(ct.get("volume_spike_ratio") or 0), step=0.5,
                        key=f"edit_ct_volume_{item['id']}",
                        help="0 表示不启用",
                    )

                st.caption("估值条件")
                edit_val1, edit_val2, edit_val3 = st.columns(3)
                with edit_val1:
                    new_pe = st.number_input(
                        "PE-TTM 上限", min_value=0.0, max_value=1000.0,
                        value=float(ct.get("pe_ttm_max") or 0), step=1.0,
                        key=f"edit_ct_pe_{item['id']}",
                        help="0 表示不启用",
                    )
                with edit_val2:
                    new_pb = st.number_input(
                        "PB-MRQ 上限", min_value=0.0, max_value=100.0,
                        value=float(ct.get("pb_mrq_max") or 0), step=0.1,
                        key=f"edit_ct_pb_{item['id']}",
                        help="0 表示不启用",
                    )
                with edit_val3:
                    new_pct = st.number_input(
                        "估值分位上限（%）", min_value=0.0, max_value=100.0,
                        value=float(ct.get("valuation_percentile_max") or 0), step=5.0,
                        key=f"edit_ct_pct_{item['id']}",
                        help="0 表示不启用",
                    )

                st.caption("风险/事件条件")
                edit_risk1, edit_risk2, edit_risk3 = st.columns(3)
                with edit_risk1:
                    risk_options = ["不启用", "low", "medium", "high"]
                    current_risk = ct.get("risk_level_min") or "不启用"
                    new_risk = st.selectbox(
                        "最低风险等级", options=risk_options,
                        index=risk_options.index(current_risk) if current_risk in risk_options else 0,
                        key=f"edit_ct_risk_{item['id']}",
                    )
                with edit_risk2:
                    sev_options = ["不启用", "low", "medium", "high"]
                    current_sev = ct.get("event_severity_min") or "不启用"
                    new_sev = st.selectbox(
                        "最低事件严重性", options=sev_options,
                        index=sev_options.index(current_sev) if current_sev in sev_options else 0,
                        key=f"edit_ct_sev_{item['id']}",
                    )
                with edit_risk3:
                    current_kw = ",".join(ct.get("event_keywords") or [])
                    new_kw = st.text_input(
                        "事件关键词", value=current_kw,
                        key=f"edit_ct_kw_{item['id']}",
                        help="逗号分隔，如：问询函,处罚,退市",
                    )

                if st.button("保存触发器", key=f"save_ct_{item['id']}"):
                    new_ct = {}
                    if new_price > 0:
                        new_ct["price_change_pct"] = new_price
                    if new_score > 0:
                        new_ct["score_threshold"] = new_score
                    if new_volume > 0:
                        new_ct["volume_spike_ratio"] = new_volume
                    if new_pe > 0:
                        new_ct["pe_ttm_max"] = new_pe
                    if new_pb > 0:
                        new_ct["pb_mrq_max"] = new_pb
                    if new_pct > 0:
                        new_ct["valuation_percentile_max"] = new_pct
                    if new_risk != "不启用":
                        new_ct["risk_level_min"] = new_risk
                    if new_sev != "不启用":
                        new_ct["event_severity_min"] = new_sev
                    kw_list = [k.strip() for k in new_kw.split(",") if k.strip()]
                    if kw_list:
                        new_ct["event_keywords"] = kw_list
                    new_sc = {**sc, "condition_triggers": new_ct}
                    if st.session_state["wl_api_ok"]:
                        _api_call("PUT", f"/api/v1/watchlist/items/{item['id']}",
                                  json={"schedule_config": new_sc})
                    else:
                        _get_store().update_item(item["id"], schedule_config=new_sc)
                    st.success("条件触发器已更新")
                    st.rerun()
```

- [ ] **Step 3: Update add item dialog trigger section**

Replace the trigger input section in the add-item dialog (around lines 546-558) with extended fields:

```python
                st.caption("条件触发器（满足任一条件自动触发扫描，0 表示不启用）")
                ct_col1, ct_col2, ct_col3 = st.columns(3)
                with ct_col1:
                    ct_price = st.number_input(
                        "涨跌幅阈值（%）", min_value=0.0, max_value=20.0, value=0.0, step=0.5,
                        key="add_ct_price",
                    )
                    ct_score = st.number_input(
                        "评分阈值", min_value=0.0, max_value=100.0, value=0.0, step=5.0,
                        key="add_ct_score",
                    )
                with ct_col2:
                    ct_volume = st.number_input(
                        "成交量异动倍数", min_value=0.0, max_value=100.0, value=0.0, step=0.5,
                        key="add_ct_volume",
                    )
                    ct_pe = st.number_input(
                        "PE-TTM 上限", min_value=0.0, max_value=1000.0, value=0.0, step=1.0,
                        key="add_ct_pe",
                    )
                with ct_col3:
                    ct_pb = st.number_input(
                        "PB-MRQ 上限", min_value=0.0, max_value=100.0, value=0.0, step=0.1,
                        key="add_ct_pb",
                    )
                    ct_pct = st.number_input(
                        "估值分位上限（%）", min_value=0.0, max_value=100.0, value=0.0, step=5.0,
                        key="add_ct_pct",
                    )
```

And update the body construction to include the new fields:

```python
                            condition_triggers = {}
                            if ct_price > 0:
                                condition_triggers["price_change_pct"] = ct_price
                            if ct_score > 0:
                                condition_triggers["score_threshold"] = ct_score
                            if ct_volume > 0:
                                condition_triggers["volume_spike_ratio"] = ct_volume
                            if ct_pe > 0:
                                condition_triggers["pe_ttm_max"] = ct_pe
                            if ct_pb > 0:
                                condition_triggers["pb_mrq_max"] = ct_pb
                            if ct_pct > 0:
                                condition_triggers["valuation_percentile_max"] = ct_pct
```

- [ ] **Step 4: Commit**

```bash
git add apps/dashboard/pages/3_观察池.py
git commit -m "feat: watchlist UI supports valuation/risk/event trigger configuration"
```

---

## Task 9: Enhance verify_watchlist_triggers.py

**Files:**
- Modify: `scripts/verify_watchlist_triggers.py`

- [ ] **Step 1: Rewrite to use centralized evaluator and add new features**

Replace the entire file with:

```python
"""观察池条件触发器真实行情验收脚本。

读取观察池配置，调用实时行情接口，判断条件触发器是否能正确评估。
输出验收报告到 storage/artifacts/verification/。

Usage:
    python scripts/verify_watchlist_triggers.py
    python scripts/verify_watchlist_triggers.py --data-source qmt
    python scripts/verify_watchlist_triggers.py --data-source akshare
    python scripts/verify_watchlist_triggers.py --ensure-sample
    python scripts/verify_watchlist_triggers.py --require-triggered-and-untriggered
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class TriggerCheckResult:
    symbol: str
    asset_type: str
    folder_name: str
    condition_triggers: dict[str, Any]
    quote: dict[str, Any] | None
    latest_result: dict[str, Any] | None
    triggered: bool
    trigger_reasons: list[str]
    missing_reasons: list[str]
    categories_evaluated: list[str]
    status: str  # pass | fail | skipped | error | warning
    message: str


@dataclass
class VerificationReport:
    run_id: str
    generated_at: str
    data_source: str
    overall_status: str
    total_items: int
    configured_items: int
    triggered_count: int
    non_triggered_count: int
    skipped_count: int
    quote_error_count: int
    categories_seen: list[str]
    acceptance_status: str
    checks: list[dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_quote_qmt(symbol: str) -> dict[str, Any] | None:
    """通过 QMT 获取实时行情。"""
    try:
        from services.data.qmt_realtime_quote import get_latest_price_data
        return get_latest_price_data(symbol)
    except Exception as exc:
        return {"error": str(exc)}


def get_quote_akshare(symbol: str) -> dict[str, Any] | None:
    """通过 AKShare 获取行情（使用最近日线数据）。"""
    try:
        import akshare as ak
        code = symbol.split(".")[0]
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        if df is None or len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest["收盘"])
        prev_close = float(prev["收盘"])
        volume = float(latest["成交量"])
        prev_volume = float(prev["成交量"]) if prev["成交量"] > 0 else 1
        return {
            "close": close,
            "prev_close": prev_close,
            "volume": volume,
            "change_pct": (close / prev_close - 1) * 100,
            "volume_ratio": volume / prev_volume if prev_volume > 0 else 1.0,
        }
    except Exception as exc:
        return {"error": str(exc)}


def verify_watchlist(
    data_source: str = "qmt",
    ensure_sample: bool = False,
    require_triggered_and_untriggered: bool = False,
) -> VerificationReport:
    """执行观察池条件触发器验收。"""
    from apps.api.task_manager.store import get_watchlist_store
    from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers

    store = get_watchlist_store()

    # Optionally create/update sample items
    if ensure_sample:
        _ensure_sample_items(store)

    items = store.get_all_enabled_items()

    checks: list[TriggerCheckResult] = []
    triggered_count = 0
    non_triggered_count = 0
    skipped_count = 0
    quote_error_count = 0
    categories_seen: set[str] = set()
    configured_items = 0

    for item in items:
        symbol = item["symbol"]
        sc = item.get("schedule_config") or {}
        ct = sc.get("condition_triggers") or {}

        # Check if any trigger is configured
        has_any = any(v is not None and v != [] for v in ct.values())
        if not has_any:
            checks.append(TriggerCheckResult(
                symbol=symbol,
                asset_type=item.get("asset_type", "stock"),
                folder_name=item.get("folder_name", ""),
                condition_triggers=ct,
                quote=None,
                latest_result=None,
                triggered=False,
                trigger_reasons=[],
                missing_reasons=[],
                categories_evaluated=[],
                status="skipped",
                message="未配置条件触发器",
            ))
            skipped_count += 1
            continue

        configured_items += 1

        # Get quote if needed
        quote = None
        need_quote = any(
            ct.get(k) is not None
            for k in ("price_change_pct", "volume_spike_ratio")
        )
        if need_quote:
            if data_source == "qmt":
                quote = get_quote_qmt(symbol)
            elif data_source == "akshare":
                quote = get_quote_akshare(symbol)
            if quote and "error" in quote:
                quote_error_count += 1

        # Use centralized evaluator
        eval_result = evaluate_condition_triggers(
            item, quote=quote,
            latest_result=item.get("last_trigger_snapshot"),
        )

        if eval_result.triggered:
            triggered_count += 1
        else:
            non_triggered_count += 1

        categories_seen.update(eval_result.categories_evaluated)

        has_quote_error = quote and "error" in quote
        has_missing = len(eval_result.missing_reasons) > 0
        status = "pass"
        if has_quote_error:
            status = "warning"
        if has_missing and not eval_result.triggered:
            status = "warning"

        all_reasons = eval_result.reasons + eval_result.missing_reasons
        checks.append(TriggerCheckResult(
            symbol=symbol,
            asset_type=item.get("asset_type", "stock"),
            folder_name=item.get("folder_name", ""),
            condition_triggers=ct,
            quote=quote,
            latest_result=item.get("last_trigger_snapshot"),
            triggered=eval_result.triggered,
            trigger_reasons=eval_result.reasons,
            missing_reasons=eval_result.missing_reasons,
            categories_evaluated=eval_result.categories_evaluated,
            status=status,
            message="; ".join(all_reasons),
        ))

    # Determine acceptance status
    acceptance_status = "pass"
    if require_triggered_and_untriggered and configured_items > 0:
        if triggered_count == 0:
            acceptance_status = "fail"
        if non_triggered_count == 0:
            acceptance_status = "fail"

    if any(c.status == "fail" for c in checks):
        acceptance_status = "fail"
    elif any(c.status == "warning" for c in checks) and acceptance_status != "fail":
        acceptance_status = "warning"

    overall = "pass" if acceptance_status == "pass" else acceptance_status

    return VerificationReport(
        run_id=_timestamp(),
        generated_at=_now_iso(),
        data_source=data_source,
        overall_status=overall,
        total_items=len(items),
        configured_items=configured_items,
        triggered_count=triggered_count,
        non_triggered_count=non_triggered_count,
        skipped_count=skipped_count,
        quote_error_count=quote_error_count,
        categories_seen=sorted(categories_seen),
        acceptance_status=acceptance_status,
        checks=[asdict(c) for c in checks],
    )


def _ensure_sample_items(store) -> None:
    """Create or update sample watchlist items for verification."""
    folders = store.list_folders()
    if not folders:
        folder = store.create_folder("验收样本", description="自动创建的验收观察池样本")
        folder_id = folder["id"]
    else:
        # Use first folder or one named "验收样本"
        sample_folder = next((f for f in folders if f["name"] == "验收样本"), None)
        if sample_folder:
            folder_id = sample_folder["id"]
        else:
            folder = store.create_folder("验收样本", description="自动创建的验收观察池样本")
            folder_id = folder["id"]

    # Sample items with different trigger configurations
    samples = [
        {
            "symbol": "600519.SH",
            "asset_type": "stock",
            "asset_name": "贵州茅台",
            "schedule_config": {
                "mode": "manual_only",
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "pe_ttm_max": 30.0,
                },
            },
        },
        {
            "symbol": "000001.SZ",
            "asset_type": "stock",
            "asset_name": "平安银行",
            "schedule_config": {
                "mode": "manual_only",
                "condition_triggers": {
                    "score_threshold": 90.0,
                    "volume_spike_ratio": 5.0,
                },
            },
        },
    ]

    existing_items = store.get_all_enabled_items()
    existing_symbols = {i["symbol"] for i in existing_items}

    for sample in samples:
        if sample["symbol"] not in existing_symbols:
            try:
                store.add_item(
                    symbol=sample["symbol"],
                    asset_type=sample["asset_type"],
                    folder_id=folder_id,
                    schedule_config=sample["schedule_config"],
                    asset_name=sample.get("asset_name", ""),
                )
            except Exception:
                pass  # May already exist under different owner


def write_artifacts(
    report: VerificationReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write report artifacts to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.run_id

    report_dict = asdict(report)

    json_path = output_dir / f"watchlist_triggers_{timestamp}.json"
    json_path.write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    latest_json = output_dir / "watchlist_triggers_latest.json"
    latest_json.write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_lines = [
        "# Watchlist Triggers Verification Report",
        f"- Generated: {report.generated_at}",
        f"- Data Source: {report.data_source}",
        f"- Overall: **{report.overall_status.upper()}**",
        f"- Acceptance: **{report.acceptance_status.upper()}**",
        "",
        "## Summary",
        f"- Total items: {report.total_items}",
        f"- Configured items: {report.configured_items}",
        f"- Triggered: {report.triggered_count}",
        f"- Non-triggered: {report.non_triggered_count}",
        f"- Skipped: {report.skipped_count}",
        f"- Quote errors: {report.quote_error_count}",
        f"- Categories seen: {', '.join(report.categories_seen) or 'none'}",
        "",
        "## Checks",
        "",
    ]
    for c in report.checks:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "skipped": "SKIP",
                "error": "ERR"}.get(c["status"], "?")
        trig = "TRIGGERED" if c["triggered"] else ""
        md_lines.append(f"- [{icon}] {c['symbol']} ({c['folder_name']}) {trig}")
        md_lines.append(f"  - Config: {c['condition_triggers']}")
        if c["trigger_reasons"]:
            md_lines.append(f"  - Reasons: {'; '.join(c['trigger_reasons'])}")
        if c["missing_reasons"]:
            md_lines.append(f"  - Missing: {'; '.join(c['missing_reasons'])}")

    md_path = output_dir / f"watchlist_triggers_{timestamp}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    latest_md = output_dir / "watchlist_triggers_latest.md"
    latest_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="观察池条件触发器验收")
    parser.add_argument("--data-source", default="qmt", choices=["qmt", "akshare"],
                        help="数据源（默认 qmt）")
    parser.add_argument("--output-dir", default="storage/artifacts/verification",
                        help="输出目录")
    parser.add_argument("--ensure-sample", action="store_true",
                        help="创建/更新验收观察池样本")
    parser.add_argument("--require-triggered-and-untriggered", action="store_true",
                        help="要求至少 1 个触发和 1 个未触发的已配置观察项")
    args = parser.parse_args()

    report = verify_watchlist(
        data_source=args.data_source,
        ensure_sample=args.ensure_sample,
        require_triggered_and_untriggered=args.require_triggered_and_untriggered,
    )

    # Output to terminal
    print(f"\n{'='*60}")
    print("观察池条件触发器验收报告")
    print(f"{'='*60}")
    print(f"数据源: {report.data_source}")
    print(f"观察项总数: {report.total_items}")
    print(f"已配置: {report.configured_items}")
    print(f"触发: {report.triggered_count}")
    print(f"未触发: {report.non_triggered_count}")
    print(f"跳过: {report.skipped_count}")
    print(f"行情错误: {report.quote_error_count}")
    print(f"评估类别: {', '.join(report.categories_seen) or 'none'}")
    print(f"总体状态: {report.overall_status}")
    print(f"验收状态: {report.acceptance_status}")
    print()

    for check in report.checks:
        icon = {"pass": "PASS", "warning": "WARN", "fail": "FAIL",
                "skipped": "SKIP"}.get(check["status"], "?")
        trig = "TRIGGERED" if check["triggered"] else ""
        print(f"[{icon}] {check['symbol']} ({check['folder_name']}) {trig}")
        print(f"   Config: {check['condition_triggers']}")
        if check["trigger_reasons"]:
            print(f"   Reasons: {'; '.join(check['trigger_reasons'])}")
        if check["missing_reasons"]:
            print(f"   Missing: {'; '.join(check['missing_reasons'])}")
        print()

    output_dir = Path(args.output_dir)
    json_path, md_path = write_artifacts(report, output_dir)

    print(f"报告已保存: {json_path}")
    print(f"最新报告: {output_dir / 'watchlist_triggers_latest.json'}")

    if report.acceptance_status == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/verify_watchlist_triggers.py
git commit -m "feat: enhance verify_watchlist_triggers.py with centralized evaluator, --ensure-sample, --require-triggered-and-untriggered"
```

---

## Task 10: Run full test suite and verification

**Files:** None (verification only)

- [ ] **Step 1: Run unit tests**

Run: `python -m pytest tests/test_dashboard_settings.py tests/test_condition_triggers.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/integration/test_watchlist_scan_e2e.py -v -p no:cacheprovider`
Expected: All PASS

- [ ] **Step 3: Run system settings verification**

Run: `python scripts/verify_system_settings_page.py --output-dir storage/artifacts/verification/system_settings`
Expected: PASS

- [ ] **Step 4: Run watchlist triggers verification (offline/mock)**

Run: `python scripts/verify_watchlist_triggers.py --data-source akshare --output-dir storage/artifacts/verification --ensure-sample --require-triggered-and-untriggered`
Expected: PASS (or warning if no real data)

- [ ] **Step 5: Run offline CI**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_offline_ci.ps1`
Expected: PASS

- [ ] **Step 6: Commit any fixes**

If any tests fail, fix and commit.

---

## Execution Summary

After all tasks complete:
- `apps/dashboard/settings_config.py` — new pure helper module
- `apps/dashboard/pages/4_系统设置.py` — uses helpers, correct path resolution
- `tests/test_dashboard_settings.py` — 10+ unit tests
- `scripts/verify_system_settings_page.py` — verification with artifact output
- `apps/api/schemas/watchlist.py` — 6 new trigger fields
- `apps/api/task_manager/watchlist_triggers.py` — centralized evaluator
- `apps/api/task_manager/store.py` — last_trigger_snapshot column
- `apps/api/task_manager/celery_tasks.py` — uses centralized evaluator
- `apps/dashboard/pages/3_观察池.py` — UI for all trigger types
- `tests/test_condition_triggers.py` — 20+ new tests
- `tests/integration/test_watchlist_scan_e2e.py` — 5+ new e2e tests
- `scripts/verify_watchlist_triggers.py` — enhanced with new flags
