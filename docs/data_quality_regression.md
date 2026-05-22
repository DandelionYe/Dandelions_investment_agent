# Data Quality Regression

## What This Solves

The data quality regression sample set detects drift in the data source and fallback chain. It verifies that:

- Valuation fields (PE, PB, PS, dividend yield, percentiles) either have a valid value **or** a machine-readable `*_missing_reason` from an allowed set.
- `source_metadata.valuation_data.source` and `calculation_method` contain expected chain fragments.
- `provider_run_log` records the expected provider/dataset/status entries.

**It does NOT lock down exact PE/PB/PS/percentile values.** Market data changes daily; the test only checks that the *source chain* and *missing-reason logic* remain stable.

## Sample Categories

| Category | Purpose |
|----------|---------|
| `large_cap_complete_cache` | Large-cap stock expected to have relatively complete QMT/CSMAR data. Verifies the happy path. |
| `eva_share_capital_fallback` | Stock where QMT `TotalVolume` is often zero; EVA_Structure or AKShare fallback should fill it. |
| `csmar_daily_derived_fallback` | Stock expected to have CSMAR daily-derived snapshot data for dividend yield and percentiles. |
| `edge_case_negative_or_missing_fundamental` | Stock with potentially missing or negative fundamentals; tests `missing_reason` propagation for all field types. |
| `industry_peer_insufficient_or_preflight_failed` | Smaller stock where industry peer pool may be insufficient or preflight fails. |

## Default Offline Contract Test

Runs without QMT, network, or SQLite. Uses synthetic data to validate the spec schema and assertion logic:

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pytest tests/test_data_quality_regression_contract.py -q
```

## Opt-in Live Test

Requires a running MiniQMT environment. Set the env var to enable:

```powershell
$env:RUN_DATA_QUALITY_REGRESSION='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_data_quality_regression_live.py -q -s
```

Without the env var, the entire test suite is skipped.

## Generate Summary Manually

```powershell
.\.venv\Scripts\python.exe scripts/run_data_quality_regression.py
```

Outputs:
- `storage/artifacts/data_quality_regression/latest.json` — machine-readable summary
- `storage/artifacts/data_quality_regression/latest.md` — human-readable summary

## Updating the JSON After Data Changes

1. Run the live test or script to see which samples fail.
2. If a failure is due to a **real data change** (e.g., a stock's financials changed, CSMAR snapshot expired), update the sample's `allowed_missing_reasons` to include the new reason, or change the `state` if appropriate.
3. If a failure is due to a **code change** (e.g., new missing_reason code, renamed source string), fix the code or update the spec accordingly.
4. Commit the updated JSON with a clear message explaining what changed and why.

## Key Principle

> Do not require exact numerical values to remain constant.
> Only require that the source chain and missing-reason explanations are stable.

This means a stock's PE can change from 25 to 30, or a percentile can shift from 0.42 to 0.38, and the test still passes — as long as the field is present (or has a valid missing_reason) and comes from the expected data source chain.
