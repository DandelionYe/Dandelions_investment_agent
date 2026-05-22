"""Helpers for data quality regression tests.

Provides functions to load, validate, and assert against the sample spec
defined in ``tests/fixtures/data_quality_regression_samples.json``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "data_quality_regression_samples.json"
)

_VALID_STATES = {"present", "missing", "present_or_missing"}


def load_sample_spec(path: str | Path | None = None) -> dict:
    """Load the regression sample spec from *path* (default: bundled fixture)."""
    target = Path(path) if path else _FIXTURE_PATH
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate_sample_spec(spec: dict) -> None:
    """Raise ``ValueError`` if *spec* violates the schema rules.

    Checks:
    - ``version`` is an int.
    - ``samples`` is a non-empty list.
    - Each sample has ``id``, ``symbol``, ``category``, ``expected``.
    - Each field rule has a valid ``state``.
    - ``allowed_missing_reasons`` is non-empty unless ``state`` is ``present``.
    - ``valuation_source.contains_any`` is a non-empty list (if present).
    - ``provider_log`` entries have ``dataset`` and ``status_any``.
    """
    if not isinstance(spec.get("version"), int):
        raise ValueError("spec.version must be an int")

    samples = spec.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("spec.samples must be a non-empty list")

    seen_ids: set[str] = set()
    for idx, sample in enumerate(samples):
        _validate_sample(sample, idx, seen_ids)


def _validate_sample(sample: dict, idx: int, seen_ids: set[str]) -> None:
    prefix = f"samples[{idx}]"

    for key in ("id", "symbol", "category", "expected"):
        if key not in sample:
            raise ValueError(f"{prefix} missing required key '{key}'")

    sid = sample["id"]
    if sid in seen_ids:
        raise ValueError(f"{prefix} duplicate sample id '{sid}'")
    seen_ids.add(sid)

    expected = sample["expected"]
    if not isinstance(expected, dict):
        raise ValueError(f"{prefix}.expected must be a dict")

    # Validate fields
    fields = expected.get("fields", {})
    for field_name, rule in fields.items():
        _validate_field_rule(rule, f"{prefix}.fields.{field_name}")

    # Validate valuation_source
    vs = expected.get("valuation_source")
    if vs is not None:
        contains = vs.get("contains_any", [])
        if not isinstance(contains, list) or not contains:
            raise ValueError(f"{prefix}.valuation_source.contains_any must be a non-empty list")

    # Validate calculation_method
    cm = expected.get("calculation_method")
    if cm is not None:
        contains = cm.get("contains_any", [])
        if not isinstance(contains, list) or not contains:
            raise ValueError(f"{prefix}.calculation_method.contains_any must be a non-empty list")

    # Validate provider_log
    plog = expected.get("provider_log", [])
    if not isinstance(plog, list):
        raise ValueError(f"{prefix}.provider_log must be a list")
    for pidx, entry in enumerate(plog):
        _validate_provider_log_entry(entry, f"{prefix}.provider_log[{pidx}]")


def _validate_field_rule(rule: dict, prefix: str) -> None:
    state = rule.get("state")
    if state not in _VALID_STATES:
        raise ValueError(f"{prefix}.state must be one of {_VALID_STATES}, got '{state}'")

    reasons = rule.get("allowed_missing_reasons", [])
    if state != "present":
        if not isinstance(reasons, list) or not reasons:
            raise ValueError(
                f"{prefix}.allowed_missing_reasons must be a non-empty list when state='{state}'"
            )


def _validate_provider_log_entry(entry: dict, prefix: str) -> None:
    if "dataset" not in entry:
        raise ValueError(f"{prefix} must have 'dataset'")
    status_any = entry.get("status_any")
    if not isinstance(status_any, list) or not status_any:
        raise ValueError(f"{prefix}.status_any must be a non-empty list")


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_result_matches_sample(result: dict, sample: dict) -> None:
    """Assert that *result* satisfies all expectations in *sample*.

    Raises ``AssertionError`` with sample id, symbol, and failing field/condition.
    """
    sid = sample["id"]
    symbol = sample["symbol"]
    expected = sample["expected"]
    valuation_data = result.get("valuation_data", {})
    source_metadata = result.get("source_metadata", {})
    provider_run_log = result.get("provider_run_log", [])

    # 1. Check fields
    fields_spec = expected.get("fields", {})
    for field_name, rule in fields_spec.items():
        _assert_field_rule(valuation_data, field_name, rule, sid, symbol)

    # 2. Check valuation_source
    vs_spec = expected.get("valuation_source")
    if vs_spec:
        _assert_contains_any(
            source_metadata,
            "valuation_data",
            "source",
            vs_spec["contains_any"],
            sid,
            symbol,
            "valuation_source",
        )

    # 3. Check calculation_method
    cm_spec = expected.get("calculation_method")
    if cm_spec:
        # calculation_method can be in source_metadata or valuation_data
        cm_value = (
            source_metadata.get("valuation_data", {}).get("calculation_method")
            or valuation_data.get("calculation_method")
            or ""
        )
        if not any(fragment in str(cm_value) for fragment in cm_spec["contains_any"]):
            raise AssertionError(
                f"[{sid}] ({symbol}) calculation_method mismatch: "
                f"value='{cm_value}', expected contains_any={cm_spec['contains_any']}"
            )

    # 4. Check provider_log
    plog_spec = expected.get("provider_log", [])
    for entry_spec in plog_spec:
        _assert_provider_log(provider_run_log, entry_spec, sid, symbol)


def _assert_field_rule(
    valuation_data: dict,
    field_name: str,
    rule: dict,
    sid: str,
    symbol: str,
) -> None:
    state = rule["state"]
    value = valuation_data.get(field_name)
    reason_field = f"{field_name}_missing_reason"
    reason_value = valuation_data.get(reason_field)

    if state == "present":
        _assert_present(value, field_name, sid, symbol)
    elif state == "missing":
        _assert_missing(value, reason_value, rule, field_name, sid, symbol)
    elif state == "present_or_missing":
        if value is not None:
            _assert_present(value, field_name, sid, symbol)
        else:
            _assert_missing(value, reason_value, rule, field_name, sid, symbol)


def _assert_present(value: Any, field_name: str, sid: str, symbol: str) -> None:
    if value is None:
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' expected present but is None"
        )
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' is {value} (NaN/Inf)"
        )


def _assert_missing(
    value: Any,
    reason_value: Any,
    rule: dict,
    field_name: str,
    sid: str,
    symbol: str,
) -> None:
    if value is not None:
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' expected missing but has value {value!r}"
        )
    allowed = rule.get("allowed_missing_reasons", [])
    if reason_value is None:
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' is missing but "
            f"'{field_name}_missing_reason' is None; expected one of {allowed}"
        )
    if reason_value not in allowed:
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' missing_reason='{reason_value}' "
            f"not in allowed {allowed}"
        )


def _assert_contains_any(
    metadata: dict,
    sub_key: str,
    field: str,
    contains_any: list[str],
    sid: str,
    symbol: str,
    label: str,
) -> None:
    actual = metadata.get(sub_key, {}).get(field, "")
    if not any(fragment in str(actual) for fragment in contains_any):
        raise AssertionError(
            f"[{sid}] ({symbol}) {label} mismatch: "
            f"value='{actual}', expected contains_any={contains_any}"
        )


def _assert_provider_log(
    run_log: list[dict],
    entry_spec: dict,
    sid: str,
    symbol: str,
) -> None:
    dataset = entry_spec["dataset"]
    status_any = entry_spec["status_any"]
    provider = entry_spec.get("provider")

    for entry in run_log:
        if entry.get("dataset") != dataset:
            continue
        if provider and entry.get("provider") != provider:
            continue
        if entry.get("status") in status_any:
            return  # match found

    raise AssertionError(
        f"[{sid}] ({symbol}) provider_run_log: no entry with "
        f"dataset='{dataset}'" + (f", provider='{provider}'" if provider else "")
        + f", status in {status_any}"
    )


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------


def summarize_result(result: dict, sample: dict) -> dict:
    """Return a summary dict comparing *result* against *sample* expectations.

    The summary includes pass/fail status per field and overall.
    """
    sid = sample["id"]
    symbol = sample["symbol"]
    expected = sample["expected"]
    valuation_data = result.get("valuation_data", {})
    source_metadata = result.get("source_metadata", {})
    provider_run_log = result.get("provider_run_log", [])

    field_results: dict[str, dict] = {}
    all_pass = True

    for field_name, rule in expected.get("fields", {}).items():
        entry = _summarize_field(valuation_data, field_name, rule)
        field_results[field_name] = entry
        if not entry["pass"]:
            all_pass = False

    # valuation_source
    vs_spec = expected.get("valuation_source", {})
    vs_actual = source_metadata.get("valuation_data", {}).get("source", "")
    vs_pass = (
        any(f in str(vs_actual) for f in vs_spec.get("contains_any", []))
        if vs_spec
        else True
    )
    if not vs_pass:
        all_pass = False

    # calculation_method
    cm_spec = expected.get("calculation_method", {})
    cm_actual = (
        source_metadata.get("valuation_data", {}).get("calculation_method")
        or valuation_data.get("calculation_method")
        or ""
    )
    cm_pass = (
        any(f in str(cm_actual) for f in cm_spec.get("contains_any", []))
        if cm_spec
        else True
    )
    if not cm_pass:
        all_pass = False

    # provider_log
    plog_pass = True
    for entry_spec in expected.get("provider_log", []):
        try:
            _assert_provider_log(provider_run_log, entry_spec, sid, symbol)
        except AssertionError:
            plog_pass = False
            all_pass = False
            break

    return {
        "sample_id": sid,
        "symbol": symbol,
        "pass": all_pass,
        "fields": field_results,
        "valuation_source": {"actual": vs_actual, "pass": vs_pass},
        "calculation_method": {"actual": str(cm_actual), "pass": cm_pass},
        "provider_log": {"pass": plog_pass},
    }


def _summarize_field(valuation_data: dict, field_name: str, rule: dict) -> dict:
    state = rule["state"]
    value = valuation_data.get(field_name)
    reason = valuation_data.get(f"{field_name}_missing_reason")
    allowed = rule.get("allowed_missing_reasons", [])

    if state == "present":
        ok = value is not None and not (isinstance(value, float) and math.isnan(value))
        return {"value": value, "state": state, "pass": ok}
    elif state == "missing":
        ok = value is None and reason in allowed
        return {"value": value, "reason": reason, "state": state, "pass": ok}
    else:  # present_or_missing
        if value is not None:
            ok = not (isinstance(value, float) and math.isnan(value))
            return {"value": value, "state": "present", "pass": ok}
        else:
            ok = reason in allowed
            return {"value": None, "reason": reason, "state": "missing", "pass": ok}
