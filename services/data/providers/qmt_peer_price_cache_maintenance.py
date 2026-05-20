"""Maintenance tool for QMT peer price cache.

Provides utilities to check and warm missing peer price data for industry
valuation. This is a manual maintenance tool; it is not called by the
main research pipeline.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Sequence

from services.data.provider_contracts import ProviderUnavailableError
from services.data.providers.local_csmar_industry_provider import (
    LocalCSMARIndustryProvider,
    normalize_level,
)
from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight
from services.data.qmt_provider import _import_xtdata, connect_qmt


class QMTPeerPriceCacheMaintenance:
    """Check and warm missing peer price cache for industry valuation."""

    def __init__(
        self,
        industry_provider: LocalCSMARIndustryProvider | None = None,
        preflight: QMTPeerCachePreflight | None = None,
    ) -> None:
        self.industry_provider = industry_provider or LocalCSMARIndustryProvider()
        self.preflight = preflight or QMTPeerCachePreflight()

    def build_peer_universe(
        self,
        target_symbols: Sequence[str] | None = None,
        peer_symbols: Sequence[str] | None = None,
        level: str | None = None,
        as_of: str | None = None,
    ) -> dict:
        if not target_symbols and not peer_symbols:
            raise ValueError("At least one of target_symbols or peer_symbols is required.")

        effective_level = normalize_level(
            level or os.getenv("LOCAL_CSMAR_INDUSTRY_LEVEL", "CSMAR_ZX")
        )
        industries: list[dict] = []
        all_peers: set[str] = set()

        if target_symbols:
            for symbol in target_symbols:
                result = self.industry_provider.resolve_industry(
                    symbol=symbol,
                    level=effective_level,
                    as_of=as_of,
                )
                if not result.metadata.success:
                    raise ProviderUnavailableError(
                        f"Failed to resolve industry for {symbol}: {result.metadata.error}"
                    )
                payload = result.data
                members = payload.get("industry_members") or []
                all_peers.update(members)
                industries.append({
                    "target_symbol": symbol,
                    "industry_level": payload.get("industry_level", effective_level),
                    "industry_code": payload.get("industry_code", ""),
                    "industry_name": payload.get("industry_name", ""),
                    "peer_count": len(members),
                })

        if peer_symbols:
            all_peers.update(peer_symbols)

        sorted_peers = sorted(all_peers)
        return {
            "target_symbols": list(target_symbols or []),
            "peer_symbols": sorted_peers,
            "industries": industries,
        }

    def check_price_cache(
        self,
        peer_symbols: Sequence[str],
        as_of: str | None = None,
        threshold: float | None = None,
    ) -> dict:
        return self.preflight.check(
            symbols=peer_symbols,
            as_of=as_of,
            threshold=threshold,
            include_missing_symbols=True,
        )

    def warm_missing_price_cache(
        self,
        missing_symbols: Sequence[str],
        *,
        as_of: str | None = None,
        history_days: int = 30,
        period: str = "1d",
        max_downloads: int = 100,
        allow_large: bool = False,
    ) -> dict:
        if not missing_symbols:
            return {
                "attempted": 0,
                "succeeded": 0,
                "failed": 0,
                "errors": [],
                "start": "",
                "end": "",
                "period": period,
            }

        symbol_list = list(missing_symbols)
        if len(symbol_list) > max_downloads and not allow_large:
            raise ValueError(
                f"Missing symbols ({len(symbol_list)}) exceeds max_downloads ({max_downloads}). "
                "Use allow_large=True to override."
            )

        end_date = _parse_date(as_of or str(date.today()))
        start_date = end_date - timedelta(days=history_days)
        end = end_date.strftime("%Y%m%d")
        start = start_date.strftime("%Y%m%d")

        return self._do_download(
            symbols=symbol_list,
            period=period,
            start=start,
            end=end,
        )

    def _do_download(
        self,
        symbols: list[str],
        period: str,
        start: str,
        end: str,
    ) -> dict:
        try:
            xtdata = _import_xtdata()
            connect_qmt()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                f"QMT connection failed for price cache warming: {exc}"
            ) from exc

        errors: list[dict[str, str]] = []
        succeeded = 0
        for symbol in symbols:
            try:
                try:
                    xtdata.download_history_data(
                        symbol,
                        period,
                        start,
                        end,
                        incrementally=True,
                    )
                except TypeError:
                    xtdata.download_history_data(symbol, period, start, end)
                succeeded += 1
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})

        return {
            "attempted": len(symbols),
            "succeeded": succeeded,
            "failed": len(errors),
            "errors": errors,
            "start": start,
            "end": end,
            "period": period,
        }


def _parse_date(value: str) -> date:
    compact = str(value).replace("-", "").strip()
    if len(compact) != 8 or not compact.isdigit():
        raise ValueError(f"Invalid date: {value}")
    return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
