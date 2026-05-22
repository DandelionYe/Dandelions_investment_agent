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
_NUMERIC_VALUATION_FIELDS = {
    "pe_ttm",
    "pb_mrq",
    "ps_ttm",
    "dividend_yield",
    "pe_percentile",
    "pb_percentile",
    "ps_percentile",
    "industry_pe_percentile",
    "industry_pb_percentile",
    "industry_ps_percentile",
    "market_cap",
    "float_market_cap",
}
_STRING_MATCH_KEYS = {"contains_any", "contains_all", "equals_any"}
_CATEGORY_REQUIRED_CHECKS = {
    "eva_share_capital_fallback": {
        "provider_log": {
            "provider": "local_csmar_eva_structure",
            "dataset": "eva_structure_latest",
        },
        "source_fragment": "local_csmar_eva_structure",
    },
    "csmar_daily_derived_fallback": {
        "provider_log": {
            "provider": "local_csmar_daily_derived",
            "dataset_any": [
                "csmar_daily_derived_snapshots",
                "latest_non_null_metrics",
                "monthly_snapshots",
            ],
        },
        "source_fragment": "csmar_daily_derived",
    },
    "industry_peer_insufficient_or_preflight_failed": {
        "provider_log": {
            "dataset": "industry_valuation",
        },
    },
}


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
    - string match specs use at least one of ``contains_any``,
      ``contains_all``, or ``equals_any``.
    - ``provider_log`` entries have ``dataset`` or ``dataset_any`` and
      ``status_any``.
    - category-specific samples include enough source/provider checks to prove
      that their named fallback path was actually exercised.
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

    vs = expected.get("valuation_source")
    if vs is not None:
        _validate_string_match_rule(vs, f"{prefix}.valuation_source")

    cm = expected.get("calculation_method")
    if cm is not None:
        _validate_string_match_rule(cm, f"{prefix}.calculation_method")

    result_checks = expected.get("result_checks", [])
    if not isinstance(result_checks, list):
        raise ValueError(f"{prefix}.result_checks must be a list")
    for cidx, check in enumerate(result_checks):
        _validate_result_check(check, f"{prefix}.result_checks[{cidx}]")

    plog = expected.get("provider_log", [])
    if not isinstance(plog, list):
        raise ValueError(f"{prefix}.provider_log must be a list")
    for pidx, entry in enumerate(plog):
        _validate_provider_log_entry(entry, f"{prefix}.provider_log[{pidx}]")

    _validate_category_contract(sample, prefix)


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
    if "dataset" not in entry and "dataset_any" not in entry:
        raise ValueError(f"{prefix} must have 'dataset' or 'dataset_any'")
    dataset_any = entry.get("dataset_any")
    if dataset_any is not None and (
        not isinstance(dataset_any, list) or not dataset_any
    ):
        raise ValueError(f"{prefix}.dataset_any must be a non-empty list")
    status_any = entry.get("status_any")
    if not isinstance(status_any, list) or not status_any:
        raise ValueError(f"{prefix}.status_any must be a non-empty list")
    for key in (
        "fields_applied_contains_any",
        "fields_applied_contains_all",
        "fields_available_contains_any",
        "fields_available_contains_all",
        "error_contains_any",
        "error_contains_all",
    ):
        value = entry.get(key)
        if value is not None and (not isinstance(value, list) or not value):
            raise ValueError(f"{prefix}.{key} must be a non-empty list")


def _validate_string_match_rule(rule: dict, prefix: str) -> None:
    if not any(key in rule for key in _STRING_MATCH_KEYS):
        raise ValueError(
            f"{prefix} must include one of {sorted(_STRING_MATCH_KEYS)}"
        )
    for key in _STRING_MATCH_KEYS:
        value = rule.get(key)
        if value is not None and (not isinstance(value, list) or not value):
            raise ValueError(f"{prefix}.{key} must be a non-empty list")


def _validate_result_check(check: dict, prefix: str) -> None:
    if not isinstance(check, dict):
        raise ValueError(f"{prefix} must be a dict")
    if not check.get("path"):
        raise ValueError(f"{prefix}.path is required")
    _validate_string_match_rule(check, prefix)


def _validate_category_contract(sample: dict, prefix: str) -> None:
    category = sample.get("category")
    requirement = _CATEGORY_REQUIRED_CHECKS.get(category)
    if not requirement:
        return

    expected = sample["expected"]
    provider_req = requirement.get("provider_log")
    if provider_req and not any(
        _provider_log_spec_covers(entry, provider_req)
        for entry in expected.get("provider_log", [])
    ):
        raise ValueError(
            f"{prefix} category '{category}' must include provider_log check "
            f"covering {provider_req}"
        )

    source_fragment = requirement.get("source_fragment")
    if source_fragment:
        source_rule = expected.get("valuation_source", {})
        calc_rule = expected.get("calculation_method", {})
        if not (
            _string_rule_mentions(source_rule, source_fragment)
            or _string_rule_mentions(calc_rule, source_fragment)
        ):
            raise ValueError(
                f"{prefix} category '{category}' must require source or "
                f"calculation_method fragment '{source_fragment}'"
            )


def _provider_log_spec_covers(entry: dict, requirement: dict) -> bool:
    provider = requirement.get("provider")
    if provider and entry.get("provider") != provider:
        return False

    dataset = requirement.get("dataset")
    if dataset:
        return entry.get("dataset") == dataset or dataset in entry.get("dataset_any", [])

    dataset_any = requirement.get("dataset_any")
    if dataset_any:
        entry_datasets = set(entry.get("dataset_any", []))
        if entry.get("dataset"):
            entry_datasets.add(entry["dataset"])
        return bool(entry_datasets.intersection(dataset_any))

    return True


def _string_rule_mentions(rule: dict, fragment: str) -> bool:
    return any(
        fragment in str(item)
        for key in _STRING_MATCH_KEYS
        for item in rule.get(key, [])
    )


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
        vs_value = source_metadata.get("valuation_data", {}).get("source", "")
        _assert_string_rule(vs_value, vs_spec, sid, symbol, "valuation_source")

    # 3. Check calculation_method
    cm_spec = expected.get("calculation_method")
    if cm_spec:
        # calculation_method can be in source_metadata or valuation_data
        cm_value = (
            source_metadata.get("valuation_data", {}).get("calculation_method")
            or valuation_data.get("calculation_method")
            or ""
        )
        _assert_string_rule(cm_value, cm_spec, sid, symbol, "calculation_method")

    # 4. Check provider_log
    plog_spec = expected.get("provider_log", [])
    for entry_spec in plog_spec:
        _assert_provider_log(provider_run_log, entry_spec, sid, symbol)

    # 5. Check arbitrary result paths used for category-specific contracts.
    for check in expected.get("result_checks", []):
        _assert_result_check(result, check, sid, symbol)


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
    if field_name in _NUMERIC_VALUATION_FIELDS and (
        isinstance(value, bool) or not isinstance(value, int | float)
    ):
        raise AssertionError(
            f"[{sid}] ({symbol}) field '{field_name}' expected numeric "
            f"int/float but got {type(value).__name__}: {value!r}"
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


def _assert_string_rule(
    actual: Any,
    rule: dict,
    sid: str,
    symbol: str,
    label: str,
) -> None:
    if not _matches_string_rule(actual, rule):
        raise AssertionError(
            f"[{sid}] ({symbol}) {label} mismatch: "
            f"value={actual!r}, expected rule={rule}"
        )


def _assert_provider_log(
    run_log: list[dict],
    entry_spec: dict,
    sid: str,
    symbol: str,
) -> None:
    dataset = entry_spec.get("dataset")
    dataset_any = entry_spec.get("dataset_any")
    status_any = entry_spec["status_any"]
    provider = entry_spec.get("provider")

    for entry in run_log:
        if dataset and entry.get("dataset") != dataset:
            continue
        if dataset_any and entry.get("dataset") not in dataset_any:
            continue
        if provider and entry.get("provider") != provider:
            continue
        if entry.get("status") not in status_any:
            continue
        if not _provider_entry_matches_extra_rules(entry, entry_spec):
            continue
        return  # match found

    raise AssertionError(
        f"[{sid}] ({symbol}) provider_run_log: no entry with "
        f"dataset='{dataset or dataset_any}'"
        + (f", provider='{provider}'" if provider else "")
        + f", status in {status_any}, expected rule={entry_spec}"
    )


def _provider_entry_matches_extra_rules(entry: dict, entry_spec: dict) -> bool:
    for entry_key, spec_key, mode in [
        ("fields_applied", "fields_applied_contains_any", "any"),
        ("fields_applied", "fields_applied_contains_all", "all"),
        ("fields_available", "fields_available_contains_any", "any"),
        ("fields_available", "fields_available_contains_all", "all"),
        ("error", "error_contains_any", "any"),
        ("error", "error_contains_all", "all"),
    ]:
        expected = entry_spec.get(spec_key)
        if not expected:
            continue
        actual = entry.get(entry_key)
        if mode == "any" and not _matches_contains_any(actual, expected):
            return False
        if mode == "all" and not _matches_contains_all(actual, expected):
            return False
    return True


def _assert_result_check(result: dict, check: dict, sid: str, symbol: str) -> None:
    path = check["path"]
    actual = _get_path(result, path)
    if not _matches_string_rule(actual, check):
        raise AssertionError(
            f"[{sid}] ({symbol}) result_check mismatch at '{path}': "
            f"value={actual!r}, expected rule={check}"
        )


def _matches_string_rule(actual: Any, rule: dict) -> bool:
    equals_any = rule.get("equals_any")
    if equals_any is not None and actual not in equals_any:
        return False
    contains_any = rule.get("contains_any")
    if contains_any is not None and not _matches_contains_any(actual, contains_any):
        return False
    contains_all = rule.get("contains_all")
    if contains_all is not None and not _matches_contains_all(actual, contains_all):
        return False
    return True


def _matches_contains_any(actual: Any, expected: list[str]) -> bool:
    values = _coerce_search_values(actual)
    return any(fragment in value for fragment in expected for value in values)


def _matches_contains_all(actual: Any, expected: list[str]) -> bool:
    values = _coerce_search_values(actual)
    return all(any(fragment in value for value in values) for fragment in expected)


def _coerce_search_values(actual: Any) -> list[str]:
    if actual is None:
        return [""]
    if isinstance(actual, list | tuple | set):
        return [str(item) for item in actual]
    return [str(actual)]


def _get_path(payload: dict, path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


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
    vs_pass = _matches_string_rule(vs_actual, vs_spec) if vs_spec else True
    if not vs_pass:
        all_pass = False

    # calculation_method
    cm_spec = expected.get("calculation_method", {})
    cm_actual = (
        source_metadata.get("valuation_data", {}).get("calculation_method")
        or valuation_data.get("calculation_method")
        or ""
    )
    cm_pass = _matches_string_rule(cm_actual, cm_spec) if cm_spec else True
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

    result_check_summaries = []
    for check in expected.get("result_checks", []):
        actual = _get_path(result, check["path"])
        passed = _matches_string_rule(actual, check)
        result_check_summaries.append({
            "path": check["path"],
            "actual": actual,
            "pass": passed,
        })
        if not passed:
            all_pass = False

    return {
        "sample_id": sid,
        "symbol": symbol,
        "pass": all_pass,
        "fields": field_results,
        "valuation_source": {"actual": vs_actual, "pass": vs_pass},
        "calculation_method": {"actual": str(cm_actual), "pass": cm_pass},
        "provider_log": {"pass": plog_pass},
        "result_checks": result_check_summaries,
    }


def _summarize_field(valuation_data: dict, field_name: str, rule: dict) -> dict:
    state = rule["state"]
    value = valuation_data.get(field_name)
    reason = valuation_data.get(f"{field_name}_missing_reason")
    allowed = rule.get("allowed_missing_reasons", [])

    if state == "present":
        ok = _value_is_present(value, field_name)
        return {"value": value, "state": state, "pass": ok}
    elif state == "missing":
        ok = value is None and reason in allowed
        return {"value": value, "reason": reason, "state": state, "pass": ok}
    else:  # present_or_missing
        if value is not None:
            ok = _value_is_present(value, field_name)
            return {"value": value, "state": "present", "pass": ok}
        else:
            ok = reason in allowed
            return {"value": None, "reason": reason, "state": "missing", "pass": ok}


def _value_is_present(value: Any, field_name: str) -> bool:
    if value is None:
        return False
    if field_name in _NUMERIC_VALUATION_FIELDS and (
        isinstance(value, bool) or not isinstance(value, int | float)
    ):
        return False
    return not (isinstance(value, float) and (math.isnan(value) or math.isinf(value)))
