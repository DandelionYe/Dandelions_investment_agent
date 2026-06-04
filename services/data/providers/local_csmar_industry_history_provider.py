"""Local CSMAR industry history provider.

Reads historical industry classification from DEBT_INSTITUTIONINFO.csv
with bad-row tolerance, as_of filtering, and P0207/P0221 selection.

Source: data/raw/csmar/industry_history/Basic Information Table/DEBT_INSTITUTIONINFO.csv
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from services.data.market_data_utils import strip_suffix_zfill6
from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
    ProviderUnavailableError,
    get_provider_error_type,
)

logger = logging.getLogger(__name__)

_DEFAULT_CSV_PATH = Path(
    "data/raw/csmar/industry_history/Basic Information Table/DEBT_INSTITUTIONINFO.csv"
)

# Columns we need from the CSV
_USECOLS = [
    "Symbol",
    "EndDate",
    "ABSign",
    "Plate",
    "INDCLASSIFYSYSTEM",
    "INDUSTRYCODE",
    "IndustryName",
]


class LocalCSMARIndustryHistoryProvider:
    """Reads historical industry classification from DEBT_INSTITUTIONINFO.csv."""

    provider = "local_csmar"
    dataset = "industry_history"

    def __init__(self, csv_path: Path | str | None = None) -> None:
        self.csv_path = Path(csv_path or os.getenv("CSMAR_INDUSTRY_HISTORY_CSV", _DEFAULT_CSV_PATH))
        self._cache: pd.DataFrame | None = None

    def resolve_industry(
        self,
        symbol: str,
        as_of: str | None = None,
    ) -> ProviderResult:
        """Resolve industry classification for a symbol at as_of date.

        Returns a ProviderResult with industry_code, industry_name,
        classification_system, and industry_as_of.
        """
        started = perf_counter()
        resolved_as_of = as_of or str(date.today())
        normalized = strip_suffix_zfill6(symbol)

        try:
            payload = self._resolve(normalized, resolved_as_of)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
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
                symbol=symbol,
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

    def _resolve(self, code: str, as_of: str) -> dict[str, Any]:
        """Find the best industry record for code at as_of."""
        df = self._load_data()
        if df.empty:
            raise ProviderUnavailableError("Industry history CSV is empty or unreadable")

        # Filter by symbol (match 6-digit code)
        symbol_mask = df["_code"] == code
        symbol_df = df[symbol_mask]
        if symbol_df.empty:
            raise ProviderDataQualityError(f"No industry records for symbol {code}")

        # Filter by EndDate <= as_of
        try:
            as_of_date = date.fromisoformat(as_of)
        except (ValueError, TypeError) as exc:
            raise ProviderDataQualityError(f"Invalid as_of date: {as_of}") from exc

        visible_mask = symbol_df["_end_date"] <= as_of_date
        visible_df = symbol_df[visible_mask]
        if visible_df.empty:
            raise ProviderDataQualityError(
                f"No industry records visible for {code} as of {as_of}"
            )

        # Select classification system:
        # 2021-2022: prefer P0207
        # 2023+: prefer P0221
        year = as_of_date.year
        if year <= 2022:
            preferred_system = "P0207"
        else:
            preferred_system = "P0221"

        # Try preferred system first
        preferred_mask = visible_df["_system"] == preferred_system
        preferred_df = visible_df[preferred_mask]

        if not preferred_df.empty:
            # Get the latest record in the preferred system
            best = preferred_df.sort_values("_end_date").iloc[-1]
        else:
            # Fallback to any available system, preferring P0207 then P0221
            for fallback in ["P0207", "P0221", "P0201"]:
                fallback_mask = visible_df["_system"] == fallback
                fallback_df = visible_df[fallback_mask]
                if not fallback_df.empty:
                    best = fallback_df.sort_values("_end_date").iloc[-1]
                    break
            else:
                # Use whatever is latest
                best = visible_df.sort_values("_end_date").iloc[-1]

        members = self._resolve_members(
            df=df,
            as_of_date=as_of_date,
            classification_system=str(best.get("INDCLASSIFYSYSTEM", "")).strip(),
            industry_code=str(best.get("INDUSTRYCODE", "")).strip(),
        )

        return {
            "industry_code": str(best.get("INDUSTRYCODE", "")).strip(),
            "industry_name": str(best.get("IndustryName", "")).strip(),
            "classification_system": str(best.get("INDCLASSIFYSYSTEM", "")).strip(),
            "industry_as_of": str(best["_end_date"]),
            "industry_members": members,
            "peer_count": len(members),
            "source": "local_csmar_industry_history",
        }

    def _resolve_members(
        self,
        *,
        df: pd.DataFrame,
        as_of_date: date,
        classification_system: str,
        industry_code: str,
    ) -> list[str]:
        """Return historical peers in the same industry at as_of.

        Each peer is represented by its latest visible record in the same
        classification system. This prevents a later industry assignment from
        leaking into an earlier historical sample.
        """
        if not classification_system or not industry_code:
            return []

        visible = df[
            (df["_end_date"] <= as_of_date)
            & (df["_system"] == classification_system)
        ].copy()
        if visible.empty:
            return []

        visible = visible.sort_values(["_code", "_end_date"])
        latest = visible.drop_duplicates(subset=["_code"], keep="last")
        latest = latest[latest["INDUSTRYCODE"].astype(str).str.strip() == industry_code]
        if latest.empty:
            return []

        # Phase 2B samples are A-share Shanghai/Shenzhen mainboard. Historical
        # CSMAR labels former SME board as "中小板"; include it with mainboard.
        if "ABSign" in latest.columns:
            latest = latest[latest["ABSign"].astype(str).str.strip().isin({"A", ""})]
        if "Plate" in latest.columns:
            plate = latest["Plate"].astype(str).str.strip()
            latest = latest[plate.isin({"主板", "中小板"})]

        members = sorted({_format_symbol(code) for code in latest["_code"].tolist()})
        return members

    def _load_data(self) -> pd.DataFrame:
        """Load and cache the CSV data with bad-row tolerance."""
        if self._cache is not None:
            return self._cache

        if not self.csv_path.exists():
            raise ProviderUnavailableError(
                f"Industry history CSV not found: {self.csv_path}"
            )

        try:
            df = pd.read_csv(
                self.csv_path,
                usecols=_USECOLS,
                dtype=str,
                encoding="utf-8-sig",
                on_bad_lines="skip",
                engine="python",
            )
        except Exception:
            # Fallback with C engine
            try:
                df = pd.read_csv(
                    self.csv_path,
                    dtype=str,
                    encoding="utf-8-sig",
                    on_bad_lines="skip",
                )
                # Keep only needed columns
                available = [c for c in _USECOLS if c in df.columns]
                df = df[available]
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Failed to read industry history CSV: {exc}"
                ) from exc

        # Normalize symbol codes
        df["_code"] = df["Symbol"].apply(lambda x: str(x).strip().strip('"').zfill(6))

        # Parse EndDate
        df["_end_date"] = pd.to_datetime(df["EndDate"].str.strip().str.strip('"'), errors="coerce").dt.date
        df = df.dropna(subset=["_end_date"])

        # Normalize classification system
        df["_system"] = df["INDCLASSIFYSYSTEM"].apply(lambda x: str(x).strip().strip('"'))

        self._cache = df
        return self._cache



def _format_symbol(code: str) -> str:
    """Format a normalized 6-digit code with exchange suffix."""
    normalized = str(code).strip().zfill(6)
    if normalized.startswith(("6", "9")):
        return f"{normalized}.SH"
    if normalized.startswith(("4", "8")):
        return f"{normalized}.BJ"
    return f"{normalized}.SZ"


def is_csmar_industry_history_enabled() -> bool:
    """Check if the industry history CSV exists."""
    csv_path = Path(os.getenv("CSMAR_INDUSTRY_HISTORY_CSV", _DEFAULT_CSV_PATH))
    return csv_path.exists()
