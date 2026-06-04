from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from time import perf_counter

from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
    ProviderUnavailableError,
    get_provider_error_type,
)


DEFAULT_CSMAR_INDUSTRY_DB = "storage/reference/csmar_industry.sqlite"


class LocalCSMARIndustryProvider:
    provider = "local_csmar"
    dataset = "industry_sector"

    def __init__(
        self,
        db_path: str | Path | None = None,
        min_peers: int | None = None,
        fallback_to_section: bool | None = None,
    ) -> None:
        self.db_path = Path(
            db_path or os.getenv("LOCAL_CSMAR_INDUSTRY_DB", DEFAULT_CSMAR_INDUSTRY_DB)
        )
        self.min_peers = min_peers or int(os.getenv("LOCAL_CSMAR_INDUSTRY_MIN_PEERS", "20"))
        if fallback_to_section is None:
            fallback_to_section = _env_bool("LOCAL_CSMAR_INDUSTRY_FALLBACK_TO_SECTION", True)
        self.fallback_to_section = fallback_to_section

    def resolve_industry(
        self,
        symbol: str,
        level: str = "CSMAR_ZX",
        as_of: str | None = None,
    ) -> ProviderResult:
        started = perf_counter()
        resolved_as_of = as_of or str(date.today())
        normalized_symbol = canonical_symbol_with_suffix(symbol)

        try:
            payload = self._resolve_payload(normalized_symbol, level)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=normalized_symbol,
                as_of=resolved_as_of,
                data=payload,
                raw={},
                metadata=ProviderMetadata(
                    success=True,
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except (ProviderUnavailableError, ProviderDataQualityError) as exc:
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=normalized_symbol,
                as_of=resolved_as_of,
                data={},
                raw={},
                metadata=ProviderMetadata(
                    success=False,
                    error=str(exc),
                    error_type=get_provider_error_type(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _resolve_payload(self, symbol: str, level: str) -> dict:
        if not self.db_path.exists():
            raise ProviderUnavailableError(
                f"Local CSMAR industry database does not exist: {self.db_path}"
            )

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            security = connection.execute(
                "SELECT * FROM securities WHERE symbol = ?",
                (symbol,),
            ).fetchone()
            if security is None:
                raise ProviderDataQualityError(
                    f"Local CSMAR industry database has no symbol: {symbol}"
                )

            primary_code = security["primary_industry_code"]
            primary_name = security["primary_industry_name"]
            section_code = security["industry_section_code"]
            section_name = security["industry_section_name"]
            snapshot_date = security["snapshot_date"]

            requested_level = normalize_level(level)
            if requested_level == "CSMAR_ZX" and not primary_code and self.fallback_to_section:
                payload = self._payload_for_level(
                    connection=connection,
                    symbol=symbol,
                    industry_level="CSMAR_SECTION",
                    industry_code=section_code,
                    industry_name=section_name,
                    snapshot_date=snapshot_date,
                    fallback_used=True,
                    fallback_reason="primary_industry_code_missing",
                )
            else:
                payload = self._payload_for_level(
                    connection=connection,
                    symbol=symbol,
                    industry_level=requested_level,
                    industry_code=primary_code if requested_level == "CSMAR_ZX" else section_code,
                    industry_name=primary_name if requested_level == "CSMAR_ZX" else section_name,
                    snapshot_date=snapshot_date,
                    fallback_used=False,
                    fallback_reason=None,
                )

            if (
                requested_level == "CSMAR_ZX"
                and self.fallback_to_section
                and payload["peer_count"] < self.min_peers
                and section_code
            ):
                payload = self._payload_for_level(
                    connection=connection,
                    symbol=symbol,
                    industry_level="CSMAR_SECTION",
                    industry_code=section_code,
                    industry_name=section_name,
                    snapshot_date=snapshot_date,
                    fallback_used=True,
                    fallback_reason="primary_industry_peer_count_below_threshold",
                )

            return payload

    def _payload_for_level(
        self,
        *,
        connection: sqlite3.Connection,
        symbol: str,
        industry_level: str,
        industry_code: str | None,
        industry_name: str | None,
        snapshot_date: str | None,
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> dict:
        if not industry_code:
            raise ProviderDataQualityError(
                f"Local CSMAR industry code is missing for {symbol}"
            )

        rows = connection.execute(
            """
            SELECT symbol
            FROM industry_members
            WHERE industry_level = ?
              AND industry_code = ?
              AND is_active = 1
            ORDER BY symbol
            """,
            (industry_level, industry_code),
        ).fetchall()
        members = [str(row["symbol"]) for row in rows]
        if not members:
            raise ProviderDataQualityError(
                f"Local CSMAR industry has no members: {industry_level} {industry_code}"
            )

        return {
            "industry_level": industry_level,
            "industry_code": industry_code,
            "industry_name": industry_name or industry_code,
            "industry_members": members,
            "peer_count": len(members),
            "source": "local_csmar_trd_co",
            "snapshot_date": snapshot_date,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
        }


def normalize_level(level: str | None) -> str:
    value = (level or "CSMAR_ZX").strip().upper()
    if value in {"ZX", "CSMAR_ZX"}:
        return "CSMAR_ZX"
    if value in {"SECTION", "CSMAR_SECTION"}:
        return "CSMAR_SECTION"
    return "CSMAR_ZX"


def canonical_symbol_with_suffix(symbol: str) -> str:
    """标准化 symbol 并补全交易所后缀。如 '600519' → '600519.SH'，'600519.SH' → '600519.SH'。"""
    value = str(symbol).strip().upper()
    if "." in value:
        code, exchange = value.split(".", 1)
        return f"{code.zfill(6)}.{exchange}"
    code = value.zfill(6)
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
