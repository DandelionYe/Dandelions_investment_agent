"""Preflight checker for QMT peer valuation cache coverage.

Validates that QMT has sufficient price, financial, and share-capital data
for a given set of peer symbols before attempting industry valuation.
"""

import os
from datetime import date, timedelta
from typing import Sequence

from services.data.provider_contracts import ProviderUnavailableError
from services.data.providers.qmt_peer_valuation_loader import (
    TOTAL_VOLUME_FIELDS,
    QMTPeerValuationLoader,
)
from services.data.qmt_provider import _import_xtdata, connect_qmt

_DEFAULT_THRESHOLD = 0.8
_REQUIRED_FINANCE_FIELDS = ("net_profit_ttm", "revenue_ttm", "bps")
_REQUIRED_ALL_FIELDS = ("close", "total_volume") + _REQUIRED_FINANCE_FIELDS
_SAMPLE_LIMIT = 10


class QMTPeerCachePreflight:
    """Check QMT cache coverage for peer valuation inputs."""

    def __init__(self, loader: QMTPeerValuationLoader | None = None) -> None:
        self.loader = loader or QMTPeerValuationLoader()

    def check(
        self,
        symbols: Sequence[str],
        as_of: str | None = None,
        threshold: float | None = None,
        include_missing_symbols: bool = False,
    ) -> dict:
        effective_threshold = threshold if threshold is not None else float(
            os.getenv("QMT_PEER_CACHE_MIN_COVERAGE", str(_DEFAULT_THRESHOLD))
        )

        cleaned = QMTPeerValuationLoader._clean_symbols(symbols)
        if not cleaned:
            result = self._empty_result(effective_threshold, "No symbols provided.")
            if include_missing_symbols:
                result["missing_symbols"] = {field: [] for field in _REQUIRED_ALL_FIELDS}
            return result

        try:
            xtdata = _import_xtdata()
            connect_qmt()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                f"QMT peer cache preflight connection failed: {exc}"
            ) from exc

        end_date = self.loader._parse_date(as_of or str(date.today()))
        end = end_date.strftime("%Y%m%d")
        start = (end_date - timedelta(days=365 * 6)).strftime("%Y%m%d")

        price_map = self.loader._load_latest_prices(xtdata, cleaned, end)
        detail_map = self.loader._load_instrument_details(xtdata, cleaned)
        financial_map = self.loader._load_financial_metrics(xtdata, cleaned, start, end)

        counts: dict[str, int] = {field: 0 for field in _REQUIRED_ALL_FIELDS}
        missing: dict[str, list[str]] = {field: [] for field in _REQUIRED_ALL_FIELDS}

        for symbol in cleaned:
            close = price_map.get(symbol)
            if close is not None and close > 0:
                counts["close"] += 1
            else:
                missing["close"].append(symbol)

            detail = detail_map.get(symbol, {})
            total_volume = self.loader._first_float(detail, TOTAL_VOLUME_FIELDS)
            if total_volume is not None and total_volume > 0:
                counts["total_volume"] += 1
            else:
                missing["total_volume"].append(symbol)

            financial = financial_map.get(symbol, {})
            for field in _REQUIRED_FINANCE_FIELDS:
                value = financial.get(field)
                if value is not None:
                    counts[field] += 1
                else:
                    missing[field].append(symbol)

        total = len(cleaned)
        coverage = {field: counts[field] / total if total else 0.0 for field in _REQUIRED_ALL_FIELDS}

        peer_complete_count = 0
        for symbol in cleaned:
            close = price_map.get(symbol)
            detail = detail_map.get(symbol, {})
            total_volume = self.loader._first_float(detail, TOTAL_VOLUME_FIELDS)
            financial = financial_map.get(symbol, {})
            if (
                close is not None and close > 0
                and total_volume is not None and total_volume > 0
                and all(financial.get(f) is not None for f in _REQUIRED_FINANCE_FIELDS)
            ):
                peer_complete_count += 1
        coverage["peer_valuation_complete"] = peer_complete_count / total if total else 0.0
        counts["peer_valuation_complete"] = peer_complete_count

        finance_ready = all(
            coverage[f] >= effective_threshold for f in _REQUIRED_FINANCE_FIELDS
        )
        price_ready = coverage["close"] >= effective_threshold
        share_capital_ready = coverage["total_volume"] >= effective_threshold
        ready = finance_ready and price_ready and share_capital_ready

        warnings: list[str] = []
        if not price_ready:
            warnings.append("qmt_peer_price_cache_insufficient")
        if not finance_ready:
            warnings.append("qmt_finance_cache_insufficient_for_peer_valuation")
        if not share_capital_ready:
            warnings.append("qmt_peer_share_capital_insufficient")

        sample_missing = {
            field: missing[field][:_SAMPLE_LIMIT] for field in _REQUIRED_ALL_FIELDS
        }

        result: dict = {
            "checked_count": total,
            "finance_ready": finance_ready,
            "price_ready": price_ready,
            "share_capital_ready": share_capital_ready,
            "ready": ready,
            "threshold": effective_threshold,
            "coverage": coverage,
            "counts": counts,
            "warnings": warnings,
            "sample_missing": sample_missing,
        }
        if include_missing_symbols:
            result["missing_symbols"] = {field: list(missing[field]) for field in _REQUIRED_ALL_FIELDS}
        return result

    @staticmethod
    def _empty_result(threshold: float, warning: str) -> dict:
        zero_coverage = {field: 0.0 for field in _REQUIRED_ALL_FIELDS}
        zero_coverage["peer_valuation_complete"] = 0.0
        zero_counts = {field: 0 for field in _REQUIRED_ALL_FIELDS}
        zero_counts["peer_valuation_complete"] = 0
        empty_missing = {field: [] for field in _REQUIRED_ALL_FIELDS}
        return {
            "checked_count": 0,
            "finance_ready": False,
            "price_ready": False,
            "share_capital_ready": False,
            "ready": False,
            "threshold": threshold,
            "coverage": zero_coverage,
            "counts": zero_counts,
            "warnings": [warning],
            "sample_missing": empty_missing,
        }
