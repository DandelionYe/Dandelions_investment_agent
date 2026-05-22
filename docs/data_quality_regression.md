# Data Quality Regression

## What This Solves

The data quality regression sample set detects drift in valuation data sources,
fallback behavior, and structured missing-reason explanations.

The live regression intentionally does not lock exact PE/PB/PS, dividend yield,
or percentile values. Those values can move with market data and reference
snapshots. The checks lock the contract that matters for research reliability:

- Valuation fields either contain finite numeric values or expose an allowed
  machine-readable `*_missing_reason`.
- `source_metadata.valuation_data.source` and `calculation_method` contain the
  expected source-chain fragments.
- `provider_run_log` records the expected provider, dataset, status, and applied
  fields for fallback paths.
- Category-specific samples prove their named path. For example, the EVA sample
  must include `local_csmar_eva_structure/eva_structure_latest`; the CSMAR
  sample must include `local_csmar_daily_derived/latest_non_null_metrics`; the
  industry failure sample must include `industry_valuation` with a stable
  failure or partial-success reason.

## Sample Categories

| Category | Sample | Contract |
|----------|--------|----------|
| `large_cap_complete_cache` | `600519.SH` | Baseline QMT-derived valuation source and valuation report shape. |
| `eva_share_capital_fallback` | `600905.SH` | QMT share-capital gaps must be repaired by local EVA before AKShare. |
| `csmar_daily_derived_fallback` | `000001.SZ` | Local CSMAR daily-derived snapshots must apply at least one valuation/dividend field. |
| `edge_case_negative_or_missing_fundamental` | `600759.SH` | Missing or invalid fundamental-derived fields must keep stable `*_missing_reason` codes. |
| `industry_peer_insufficient_or_preflight_failed` | `300736.SZ` | Industry percentile failures must be visible through `industry_valuation` logs and missing reasons. |

The sample specification lives in
`tests/fixtures/data_quality_regression_samples.json`. Its schema is enforced by
the offline contract test, including category-specific provider/source
requirements.

## Default Offline Contract Test

Runs without QMT, network, Redis, or local reference SQLite. It validates the
sample spec and the assertion helper with synthetic data:

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pytest tests/test_data_quality_regression_contract.py -q
```

## Opt-in Live Test

Run this only on a workstation where MiniQMT and local reference databases are
available:

```powershell
$env:RUN_DATA_QUALITY_REGRESSION='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_data_quality_regression_live.py -q -s
```

Without `RUN_DATA_QUALITY_REGRESSION=1`, the live tests are collected and
skipped.

## Generate Summary Manually

```powershell
.\.venv\Scripts\python.exe scripts/run_data_quality_regression.py
```

Outputs:

- `storage/artifacts/data_quality_regression/latest.json`
- `storage/artifacts/data_quality_regression/latest.md`

These files are runtime artifacts and should not be committed.

## Updating The Baseline

When a live regression fails:

1. Inspect the failed sample id, symbol, field, actual source, provider log, and
   missing reason.
2. If the expected provider chain disappeared unexpectedly, treat it as a code or
   data-source regression.
3. If the market/reference data legitimately changed so the sample no longer
   represents its category, replace the sample or update the sample's expected
   contract.
4. Do not broaden a rule just to make the test pass. Category-specific samples
   must continue to prove their named path.

The key rule is still: exact numbers may drift, but source chains and missing
explanations must remain stable and reviewable.
