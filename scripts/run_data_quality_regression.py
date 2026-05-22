"""Run data quality regression against live QMT and produce summary artifacts.

Usage::

    python scripts/run_data_quality_regression.py

Reads samples from ``tests/fixtures/data_quality_regression_samples.json``,
runs ``run_single_asset_research(symbol, use_llm=False, data_source="qmt")``
for each, and writes results to ``storage/artifacts/data_quality_regression/``.

Exit code is non-zero if any sample fails.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from services.orchestrator.single_asset_research import run_single_asset_research  # noqa: E402
from tests.helpers.data_quality_regression import (  # noqa: E402
    assert_result_matches_sample,
    load_sample_spec,
    summarize_result,
)

_ARTIFACT_DIR = _REPO_ROOT / "storage" / "artifacts" / "data_quality_regression"


def main() -> int:
    spec = load_sample_spec()
    samples = spec["samples"]
    print(f"Loaded {len(samples)} regression samples (version {spec['version']})")

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    failures: list[dict] = []

    for sample in samples:
        sid = sample["id"]
        symbol = sample["symbol"]
        print(f"\n--- {sid} ({symbol}) ---")

        try:
            result = run_single_asset_research(
                symbol,
                use_llm=False,
                data_source="qmt",
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            failures.append({"sample_id": sid, "symbol": symbol, "error": str(exc)})
            summaries.append({
                "sample_id": sid,
                "symbol": symbol,
                "pass": False,
                "error": str(exc),
            })
            continue

        try:
            assert_result_matches_sample(result, sample)
            summary = summarize_result(result, sample)
            print("  PASS")
            summaries.append(summary)
        except AssertionError as exc:
            summary = summarize_result(result, sample)
            print(f"  FAIL: {exc}")
            failures.append({
                "sample_id": sid,
                "symbol": symbol,
                "error": str(exc),
            })
            summaries.append(summary)

    # Write artifacts
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _ARTIFACT_DIR / "latest.json"
    md_path = _ARTIFACT_DIR / "latest.md"
    dated_json = _ARTIFACT_DIR / f"regression_{timestamp}.json"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "total": len(samples),
        "passed": len(samples) - len(failures),
        "failed": len(failures),
        "summaries": summaries,
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    dated_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"Results: {payload['passed']}/{payload['total']} passed")
    print(f"Artifacts: {json_path}")
    print(f"Artifacts: {md_path}")

    if failures:
        print("\nFailed samples:")
        for f in failures:
            print(f"  - {f['sample_id']} ({f['symbol']}): {f['error'][:120]}")
        return 1

    return 0


def _render_markdown(payload: dict) -> str:
    lines = [
        "# Data Quality Regression Summary",
        "",
        f"Generated: {payload['generated_at']}",
        f"Total: {payload['total']} | Passed: {payload['passed']} | Failed: {payload['failed']}",
        "",
        "| Sample | Symbol | Result |",
        "|--------|--------|--------|",
    ]
    for s in payload["summaries"]:
        status = "PASS" if s.get("pass") else "FAIL"
        lines.append(f"| {s['sample_id']} | {s['symbol']} | {status} |")

    failures = [s for s in payload["summaries"] if not s.get("pass")]
    if failures:
        lines.extend(["", "## Failures", ""])
        for s in failures:
            lines.append(f"### {s['sample_id']} ({s['symbol']})")
            for field_name, entry in s.get("fields", {}).items():
                if not entry.get("pass"):
                    lines.append(
                        f"- **{field_name}**: value={entry.get('value')}, "
                        f"reason={entry.get('reason')}, state={entry.get('state')}"
                    )
            if not s.get("valuation_source", {}).get("pass", True):
                lines.append(f"- **source**: {s['valuation_source'].get('actual', '')}")
            if not s.get("provider_log", {}).get("pass", True):
                lines.append("- **provider_log**: no matching entry found")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
