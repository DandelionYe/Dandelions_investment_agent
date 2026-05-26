"""Re-enrich existing historical samples fixture with new providers.

Updates fundamental and industry data from local CSMAR financial statements
and industry history providers, without requiring QMT for price data.

Usage:
    python scripts/enrich_historical_samples.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    fixture_path = PROJECT_ROOT / "tests/fixtures/research_quality_historical_samples.json"
    if not fixture_path.exists():
        print(f"Error: fixture not found: {fixture_path}", file=sys.stderr)
        return 1

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    samples = fixture.get("samples", [])
    print(f"Loaded {len(samples)} samples")

    # Pre-load providers once (they cache CSV data internally)
    print("Loading financial statement provider...")
    from services.data.providers.local_csmar_financial_statement_provider import (
        LocalCSMARFinancialStatementProvider,
        is_csmar_financial_enabled,
    )
    fin_provider = LocalCSMARFinancialStatementProvider() if is_csmar_financial_enabled() else None
    print(f"  Financial provider: {'available' if fin_provider else 'not available'}")

    print("Loading industry history provider...")
    from services.data.providers.local_csmar_industry_history_provider import (
        LocalCSMARIndustryHistoryProvider,
        is_csmar_industry_history_enabled,
    )
    ind_provider = LocalCSMARIndustryHistoryProvider() if is_csmar_industry_history_enabled() else None
    print(f"  Industry history provider: {'available' if ind_provider else 'not available'}")

    # Pre-warm the caches by loading data once
    if fin_provider:
        print("Pre-warming financial data cache...")
        fin_provider.get_fundamentals("000001.SZ", "2024-12-31")
        print("  Cache warmed")

    if ind_provider:
        print("Pre-warming industry data cache...")
        ind_provider.resolve_industry("000001.SZ", as_of="2024-12-31")
        print("  Cache warmed")

    # Define field sets for data_complete check
    STRICT_FUNDAMENTAL_FIELDS = {
        "roe", "gross_margin", "net_margin", "net_profit_growth",
        "revenue_growth", "net_profit_ttm", "revenue_ttm",
        "debt_ratio", "operating_cashflow_quality",
    }
    STRICT_VALUATION_FIELDS = {"pe_ttm", "pb_mrq", "ps_ttm", "dividend_yield"}

    enriched_count = 0
    industry_enriched_count = 0

    for i, sample in enumerate(samples):
        symbol = sample.get("symbol", "")
        as_of = sample.get("as_of", "")
        ir = sample.get("input_result", {})
        sm = ir.get("source_metadata", {})

        # Enrich with financial statements if missing
        if sm.get("fundamental_source") in (None, "", "missing") and fin_provider:
            result = fin_provider.get_fundamentals(symbol, as_of)
            if result.metadata.success and result.data:
                fd = ir.get("fundamental_data", {})
                # Only add non-None fields
                for key in STRICT_FUNDAMENTAL_FIELDS:
                    if result.data.get(key) is not None:
                        fd[key] = result.data[key]
                ir["fundamental_data"] = fd
                sm["fundamental_source"] = "local_csmar_financial_statements"
                enriched_count += 1

        # Enrich with industry history if not already strict
        ind_strict = False
        if sm.get("industry_source") in (None, "", "missing", "local_csmar_industry_non_strict") and ind_provider:
            result = ind_provider.resolve_industry(symbol, as_of=as_of)
            if result.metadata.success and result.data:
                industry_as_of = result.data.get("industry_as_of", "")
                ind_strict = industry_as_of <= as_of if industry_as_of else False
                sample["industry"] = {
                    "level": "CSMAR_INDUSTRY_HISTORY",
                    "name": result.data.get("industry_name"),
                    "industry_code": result.data.get("industry_code"),
                    "classification_system": result.data.get("classification_system"),
                    "peer_count": 0,
                    "valid_peer_count_pe": 0,
                    "valid_peer_count_pb": 0,
                    "valid_peer_count_ps": 0,
                    "_industry_as_of": industry_as_of,
                }
                sm["industry_source"] = "local_csmar_industry_history" if ind_strict else "local_csmar_industry_history_non_strict"
                industry_enriched_count += 1
        else:
            # Check if existing industry is strict
            ind_strict = sm.get("industry_source") not in (
                None, "", "missing", "local_csmar_industry_non_strict",
                "local_csmar_industry_history_non_strict",
            )

        # Update source_metadata back
        ir["source_metadata"] = sm

        # Recalculate data_complete
        fd = ir.get("fundamental_data", {})
        vd = ir.get("valuation_data", {})
        pd_data = ir.get("price_data", {})

        has_strict_fundamental = any(fd.get(f) is not None for f in STRICT_FUNDAMENTAL_FIELDS)
        has_strict_valuation = any(vd.get(f) is not None for f in STRICT_VALUATION_FIELDS)

        # Recalculate has_placeholder based on current data state
        has_placeholder = not has_strict_fundamental
        dq = ir.get("data_quality", {})
        dq["has_placeholder"] = has_placeholder
        # Update blocking_issues
        blocking = []
        if not has_strict_fundamental:
            blocking.append("fundamental_profitability_missing")
        if not has_strict_valuation:
            blocking.append("valuation_data_missing")
        if not ind_strict:
            blocking.append("industry_as_of_unverifiable")
        dq["blocking_issues"] = blocking
        ir["data_quality"] = dq

        data_complete = (
            bool(pd_data)
            and not has_placeholder
            and has_strict_fundamental
            and has_strict_valuation
            and ind_strict
        )
        sample["quality"]["data_complete"] = data_complete

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(samples)}...")

    # Update fixture source info
    fixture["source"] = {
        "price": "qmt_xtdata",
        "fundamental": "local_csmar_financial_statements",
        "capital_structure": "local_csmar_eva_structure_partial",
        "valuation": "local_csmar_daily_derived",
        "industry": "local_csmar_industry_history",
    }

    print(f"\nEnriched {enriched_count} samples with financial data")
    print(f"Enriched {industry_enriched_count} samples with industry history")

    # Write back
    fixture_path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated fixture: {fixture_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
