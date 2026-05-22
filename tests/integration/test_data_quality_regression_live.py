"""Live data quality regression tests.

These tests run ``run_single_asset_research`` with ``data_source="qmt"``
against real QMT data and verify that the result satisfies the sample spec.

**Opt-in**: set ``RUN_DATA_QUALITY_REGRESSION=1`` to enable.
"""

from __future__ import annotations

import os

import pytest

from services.orchestrator.single_asset_research import run_single_asset_research
from tests.helpers.data_quality_regression import (
    assert_result_matches_sample,
    load_sample_spec,
    summarize_result,
    validate_sample_spec,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.data_quality,
]


def _skip_if_not_enabled() -> None:
    if os.environ.get("RUN_DATA_QUALITY_REGRESSION") != "1":
        pytest.skip(
            "Set RUN_DATA_QUALITY_REGRESSION=1 to run live data quality regression tests"
        )


# Load spec once at module level for parametrize
_spec = load_sample_spec()
validate_sample_spec(_spec)
_samples = _spec["samples"]


@pytest.mark.parametrize(
    "sample",
    _samples,
    ids=[s["id"] for s in _samples],
)
def test_data_quality_regression(sample: dict):
    """Run single asset research and verify result matches sample spec."""
    _skip_if_not_enabled()

    symbol = sample["symbol"]
    result = run_single_asset_research(
        symbol,
        use_llm=False,
        data_source="qmt",
    )

    try:
        assert_result_matches_sample(result, sample)
    except AssertionError:
        # Print summary for debugging before re-raising
        summary = summarize_result(result, sample)
        _print_failure_summary(summary, result)
        raise


def _print_failure_summary(summary: dict, result: dict) -> None:
    """Print a human-readable failure summary to stdout."""
    print(f"\n{'='*60}")
    print(f"FAIL: {summary['sample_id']} ({summary['symbol']})")
    print(f"{'='*60}")

    for field_name, entry in summary.get("fields", {}).items():
        if not entry["pass"]:
            vd = result.get("valuation_data", {})
            actual = vd.get(field_name)
            reason = vd.get(f"{field_name}_missing_reason")
            print(f"  FIELD {field_name}: value={actual}, reason={reason}, state={entry['state']}")

    vs = summary.get("valuation_source", {})
    if not vs.get("pass", True):
        print(f"  SOURCE: actual='{vs.get('actual', '')}'")

    cm = summary.get("calculation_method", {})
    if not cm.get("pass", True):
        print(f"  CALC_METHOD: actual='{cm.get('actual', '')}'")

    if not summary.get("provider_log", {}).get("pass", True):
        log = result.get("provider_run_log", [])
        print(f"  PROVIDER_LOG ({len(log)} entries):")
        for entry in log[:10]:
            print(f"    - {entry.get('dataset')}: {entry.get('status')} ({entry.get('provider', '?')})")

    for check in summary.get("result_checks", []):
        if not check.get("pass", True):
            print(f"  RESULT_CHECK {check['path']}: actual={check.get('actual')!r}")

    print()
