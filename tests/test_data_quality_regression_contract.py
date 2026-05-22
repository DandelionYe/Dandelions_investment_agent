"""Contract tests for data quality regression sample spec.

All tests use synthetic data — no QMT, no network, no SQLite.
"""

from __future__ import annotations

import pytest

from tests.helpers.data_quality_regression import (
    assert_result_matches_sample,
    load_sample_spec,
    summarize_result,
    validate_sample_spec,
)

# ---------------------------------------------------------------------------
# Spec schema validation
# ---------------------------------------------------------------------------


class TestSpecSchema:
    def test_fixture_spec_is_valid(self):
        spec = load_sample_spec()
        validate_sample_spec(spec)

    def test_spec_has_version(self):
        spec = load_sample_spec()
        assert spec["version"] == 1

    def test_spec_has_required_categories(self):
        spec = load_sample_spec()
        categories = {s["category"] for s in spec["samples"]}
        required = {
            "large_cap_complete_cache",
            "eva_share_capital_fallback",
            "csmar_daily_derived_fallback",
            "edge_case_negative_or_missing_fundamental",
            "industry_peer_insufficient_or_preflight_failed",
        }
        assert required.issubset(categories), f"Missing categories: {required - categories}"

    def test_spec_has_minimum_sample_count(self):
        spec = load_sample_spec()
        assert len(spec["samples"]) >= 5

    def test_all_sample_ids_unique(self):
        spec = load_sample_spec()
        ids = [s["id"] for s in spec["samples"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Field rule validation
# ---------------------------------------------------------------------------


class TestFieldRuleValidation:
    def test_present_field_passes(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
        )
        result = _make_result(valuation_data={"pe_ttm": 25.0})
        assert_result_matches_sample(result, sample)

    def test_present_field_none_fails(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
        )
        result = _make_result(valuation_data={"pe_ttm": None})
        with pytest.raises(AssertionError, match="expected present"):
            assert_result_matches_sample(result, sample)

    def test_present_field_nan_fails(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
        )
        result = _make_result(valuation_data={"pe_ttm": float("nan")})
        with pytest.raises(AssertionError, match="NaN"):
            assert_result_matches_sample(result, sample)

    def test_present_numeric_field_string_fails(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
        )
        result = _make_result(valuation_data={"pe_ttm": "not-a-number"})
        with pytest.raises(AssertionError, match="expected numeric"):
            assert_result_matches_sample(result, sample)

    def test_missing_field_with_allowed_reason_passes(self):
        sample = _make_sample(
            fields={
                "pe_ttm": {
                    "state": "missing",
                    "allowed_missing_reasons": ["loss_making_or_invalid_pe"],
                }
            },
        )
        result = _make_result(
            valuation_data={"pe_ttm": None, "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        )
        assert_result_matches_sample(result, sample)

    def test_missing_field_with_disallowed_reason_fails(self):
        sample = _make_sample(
            fields={
                "pe_ttm": {
                    "state": "missing",
                    "allowed_missing_reasons": ["loss_making_or_invalid_pe"],
                }
            },
        )
        result = _make_result(
            valuation_data={"pe_ttm": None, "pe_ttm_missing_reason": "some_other_reason"},
        )
        with pytest.raises(AssertionError, match="not in allowed"):
            assert_result_matches_sample(result, sample)

    def test_missing_field_no_reason_fails(self):
        sample = _make_sample(
            fields={
                "pe_ttm": {
                    "state": "missing",
                    "allowed_missing_reasons": ["loss_making_or_invalid_pe"],
                }
            },
        )
        result = _make_result(valuation_data={"pe_ttm": None})
        with pytest.raises(AssertionError, match="missing_reason.*None"):
            assert_result_matches_sample(result, sample)

    def test_present_or_missing_with_value_passes(self):
        sample = _make_sample(
            fields={
                "pe_ttm": {
                    "state": "present_or_missing",
                    "allowed_missing_reasons": ["loss_making_or_invalid_pe"],
                }
            },
        )
        result = _make_result(valuation_data={"pe_ttm": 20.0})
        assert_result_matches_sample(result, sample)

    def test_present_or_missing_without_value_passes(self):
        sample = _make_sample(
            fields={
                "pe_ttm": {
                    "state": "present_or_missing",
                    "allowed_missing_reasons": ["loss_making_or_invalid_pe"],
                }
            },
        )
        result = _make_result(
            valuation_data={"pe_ttm": None, "pe_ttm_missing_reason": "loss_making_or_invalid_pe"},
        )
        assert_result_matches_sample(result, sample)


# ---------------------------------------------------------------------------
# valuation_source validation
# ---------------------------------------------------------------------------


class TestValuationSourceValidation:
    def test_matching_source_passes(self):
        sample = _make_sample(
            valuation_source={"contains_any": ["qmt_derived", "akshare"]},
        )
        result = _make_result(
            source_metadata={"valuation_data": {"source": "qmt_derived+akshare"}},
        )
        assert_result_matches_sample(result, sample)

    def test_non_matching_source_fails(self):
        sample = _make_sample(
            valuation_source={"contains_any": ["qmt_derived"]},
        )
        result = _make_result(
            source_metadata={"valuation_data": {"source": "mock_placeholder"}},
        )
        with pytest.raises(AssertionError, match="valuation_source mismatch"):
            assert_result_matches_sample(result, sample)

    def test_contains_all_source_requires_every_fragment(self):
        sample = _make_sample(
            valuation_source={"contains_all": ["qmt_derived", "local_csmar_eva_structure"]},
        )
        result = _make_result(
            source_metadata={"valuation_data": {"source": "qmt_derived"}},
        )
        with pytest.raises(AssertionError, match="valuation_source mismatch"):
            assert_result_matches_sample(result, sample)


# ---------------------------------------------------------------------------
# provider_log validation
# ---------------------------------------------------------------------------


class TestProviderLogValidation:
    def test_matching_log_entry_passes(self):
        sample = _make_sample(
            provider_log=[{"dataset": "valuation_data", "status_any": ["success"]}],
        )
        result = _make_result(
            provider_run_log=[
                {"dataset": "valuation_data", "status": "success", "provider": "qmt_derived"},
            ],
        )
        assert_result_matches_sample(result, sample)

    def test_missing_log_entry_fails(self):
        sample = _make_sample(
            provider_log=[{"dataset": "valuation_data", "status_any": ["success"]}],
        )
        result = _make_result(provider_run_log=[])
        with pytest.raises(AssertionError, match="provider_run_log"):
            assert_result_matches_sample(result, sample)

    def test_wrong_status_fails(self):
        sample = _make_sample(
            provider_log=[{"dataset": "valuation_data", "status_any": ["success"]}],
        )
        result = _make_result(
            provider_run_log=[
                {"dataset": "valuation_data", "status": "failed", "provider": "qmt"},
            ],
        )
        with pytest.raises(AssertionError, match="provider_run_log"):
            assert_result_matches_sample(result, sample)

    def test_status_any_multiple_values(self):
        sample = _make_sample(
            provider_log=[
                {"dataset": "valuation_data", "status_any": ["success", "fallback_placeholder"]},
            ],
        )
        result = _make_result(
            provider_run_log=[
                {"dataset": "valuation_data", "status": "fallback_placeholder"},
            ],
        )
        assert_result_matches_sample(result, sample)

    def test_provider_log_fields_applied_rule_passes(self):
        sample = _make_sample(
            provider_log=[
                {
                    "provider": "local_csmar_eva_structure",
                    "dataset": "eva_structure_latest",
                    "status_any": ["success"],
                    "fields_applied_contains_any": ["total_volume"],
                }
            ],
        )
        result = _make_result(
            provider_run_log=[
                {
                    "provider": "local_csmar_eva_structure",
                    "dataset": "eva_structure_latest",
                    "status": "success",
                    "fields_applied": ["total_volume", "market_cap"],
                }
            ],
        )
        assert_result_matches_sample(result, sample)

    def test_provider_log_fields_applied_rule_fails(self):
        sample = _make_sample(
            provider_log=[
                {
                    "provider": "local_csmar_eva_structure",
                    "dataset": "eva_structure_latest",
                    "status_any": ["success"],
                    "fields_applied_contains_any": ["total_volume"],
                }
            ],
        )
        result = _make_result(
            provider_run_log=[
                {
                    "provider": "local_csmar_eva_structure",
                    "dataset": "eva_structure_latest",
                    "status": "success",
                    "fields_applied": [],
                }
            ],
        )
        with pytest.raises(AssertionError, match="provider_run_log"):
            assert_result_matches_sample(result, sample)


# ---------------------------------------------------------------------------
# result_checks validation
# ---------------------------------------------------------------------------


class TestResultChecks:
    def test_result_check_passes(self):
        sample = _make_sample(
            result_checks=[
                {
                    "path": "valuation_data.dividend_yield_source",
                    "equals_any": ["local_csmar_daily_derived"],
                }
            ],
        )
        result = _make_result(
            valuation_data={
                "dividend_yield_source": "local_csmar_daily_derived",
            },
        )
        assert_result_matches_sample(result, sample)

    def test_result_check_fails(self):
        sample = _make_sample(
            result_checks=[
                {
                    "path": "valuation_data.dividend_yield_source",
                    "equals_any": ["local_csmar_daily_derived"],
                }
            ],
        )
        result = _make_result(
            valuation_data={"dividend_yield_source": "akshare"},
        )
        with pytest.raises(AssertionError, match="result_check mismatch"):
            assert_result_matches_sample(result, sample)


# ---------------------------------------------------------------------------
# summarize_result
# ---------------------------------------------------------------------------


class TestSummarizeResult:
    def test_all_pass(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
            valuation_source={"contains_any": ["qmt_derived"]},
            calculation_method={"contains_any": ["derived_from_qmt"]},
            provider_log=[{"dataset": "valuation_data", "status_any": ["success"]}],
        )
        result = _make_result(
            valuation_data={"pe_ttm": 25.0, "calculation_method": "derived_from_qmt"},
            source_metadata={"valuation_data": {"source": "qmt_derived"}},
            provider_run_log=[{"dataset": "valuation_data", "status": "success"}],
        )
        summary = summarize_result(result, sample)
        assert summary["pass"] is True
        assert summary["fields"]["pe_ttm"]["pass"] is True

    def test_field_fail(self):
        sample = _make_sample(
            fields={"pe_ttm": {"state": "present", "allowed_missing_reasons": []}},
        )
        result = _make_result(valuation_data={"pe_ttm": None})
        summary = summarize_result(result, sample)
        assert summary["pass"] is False
        assert summary["fields"]["pe_ttm"]["pass"] is False


# ---------------------------------------------------------------------------
# Spec validation edge cases
# ---------------------------------------------------------------------------


class TestSpecValidationEdgeCases:
    def test_invalid_state_rejected(self):
        spec = _invalid_spec(field_state="invalid_state")
        with pytest.raises(ValueError, match="state"):
            validate_sample_spec(spec)

    def test_empty_samples_rejected(self):
        spec = {"version": 1, "samples": []}
        with pytest.raises(ValueError, match="non-empty"):
            validate_sample_spec(spec)

    def test_missing_id_rejected(self):
        spec = {
            "version": 1,
            "samples": [{"symbol": "X.SH", "category": "c", "expected": {"fields": {}}}],
        }
        with pytest.raises(ValueError, match="id"):
            validate_sample_spec(spec)

    def test_duplicate_id_rejected(self):
        spec = {
            "version": 1,
            "samples": [
                {"id": "a", "symbol": "X.SH", "category": "c", "expected": {"fields": {}}},
                {"id": "a", "symbol": "Y.SH", "category": "c", "expected": {"fields": {}}},
            ],
        }
        with pytest.raises(ValueError, match="duplicate"):
            validate_sample_spec(spec)

    def test_empty_allowed_reasons_for_missing_rejected(self):
        spec = _invalid_spec(field_state="missing", allowed_reasons=[])
        with pytest.raises(ValueError, match="non-empty"):
            validate_sample_spec(spec)

    def test_empty_allowed_reasons_for_present_is_ok(self):
        spec = _invalid_spec(field_state="present", allowed_reasons=[])
        validate_sample_spec(spec)  # should not raise

    def test_empty_contains_any_rejected(self):
        spec = {
            "version": 1,
            "samples": [
                {
                    "id": "x",
                    "symbol": "X.SH",
                    "category": "c",
                    "expected": {
                        "fields": {},
                        "valuation_source": {"contains_any": []},
                    },
                }
            ],
        }
        with pytest.raises(ValueError, match="contains_any"):
            validate_sample_spec(spec)

    def test_eva_category_requires_eva_provider_log(self):
        spec = {
            "version": 1,
            "samples": [
                {
                    "id": "eva",
                    "symbol": "600410.SH",
                    "category": "eva_share_capital_fallback",
                    "expected": {
                        "fields": {},
                        "valuation_source": {"contains_any": ["qmt_derived"]},
                        "provider_log": [
                            {"dataset": "valuation_data", "status_any": ["success"]}
                        ],
                    },
                }
            ],
        }
        with pytest.raises(ValueError, match="local_csmar_eva_structure"):
            validate_sample_spec(spec)

    def test_dataset_any_provider_log_spec_is_valid(self):
        spec = {
            "version": 1,
            "samples": [
                {
                    "id": "csmar",
                    "symbol": "000001.SZ",
                    "category": "csmar_daily_derived_fallback",
                    "expected": {
                        "fields": {},
                        "valuation_source": {"contains_any": ["csmar_daily_derived"]},
                        "provider_log": [
                            {
                                "provider": "local_csmar_daily_derived",
                                "dataset_any": [
                                    "csmar_daily_derived_snapshots",
                                    "latest_non_null_metrics",
                                    "monthly_snapshots",
                                ],
                                "status_any": ["success"],
                            }
                        ],
                    },
                }
            ],
        }
        validate_sample_spec(spec)


# ---------------------------------------------------------------------------
# Helpers to build synthetic samples/results
# ---------------------------------------------------------------------------


def _make_sample(
    fields: dict | None = None,
    valuation_source: dict | None = None,
    calculation_method: dict | None = None,
    provider_log: list | None = None,
    result_checks: list | None = None,
) -> dict:
    return {
        "id": "test_sample",
        "symbol": "TEST.SH",
        "category": "test",
        "requires": [],
        "expected": {
            "fields": fields or {},
            "valuation_source": valuation_source or {"contains_any": ["any"]},
            "calculation_method": calculation_method or {"contains_any": ["any"]},
            "provider_log": provider_log or [
                {"dataset": "valuation_data", "status_any": ["success"]}
            ],
            "result_checks": result_checks or [],
        },
    }


def _make_result(
    valuation_data: dict | None = None,
    source_metadata: dict | None = None,
    provider_run_log: list | None = None,
) -> dict:
    vd = valuation_data if valuation_data is not None else {}
    vd.setdefault("calculation_method", "any")
    return {
        "valuation_data": vd,
        "source_metadata": source_metadata if source_metadata is not None else {"valuation_data": {"source": "any"}},
        "provider_run_log": provider_run_log if provider_run_log is not None else [
            {"dataset": "valuation_data", "status": "success"}
        ],
    }


def _invalid_spec(
    field_state: str = "present",
    allowed_reasons: list | None = None,
) -> dict:
    if allowed_reasons is None:
        allowed_reasons = ["some_reason"]
    return {
        "version": 1,
        "samples": [
            {
                "id": "test",
                "symbol": "X.SH",
                "category": "c",
                "expected": {
                    "fields": {
                        "pe_ttm": {
                            "state": field_state,
                            "allowed_missing_reasons": allowed_reasons,
                        }
                    }
                },
            }
        ],
    }
