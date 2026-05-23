"""Local CSMAR EVA_Structure provider for share capital / market value fallback.

Reads from a pre-built SQLite database (built by
scripts/build_csmar_eva_structure_reference.py) that aggregates CSMAR
EVA_Structure.csv data.

This provider is strictly a **fallback**: callers must only use it when
QMT cannot supply total_volume / market_cap.  It sits between QMT and
AKShare in the fallback chain.

Never reads raw CSV under data/raw/csmar/.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_eva_structure_enabled() -> bool:
    return _env_bool("CSMAR_EVA_STRUCTURE_PROVIDER", True)


def _db_path() -> str:
    return os.getenv(
        "CSMAR_EVA_STRUCTURE_DB",
        "storage/reference/csmar_eva_structure.sqlite",
    )


def _max_stale_days() -> int:
    return _env_int("CSMAR_EVA_STRUCTURE_MAX_STALE_DAYS", 460)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class LocalCSMAREVAStructureProvider:
    """Read-only fallback provider for share capital from EVA_Structure."""

    provider = "local_csmar_eva_structure"
    dataset = "eva_structure_latest"

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _db_path()

    def get_as_of_share_capital(
        self, symbol: str, as_of: str
    ) -> ProviderResult:
        """Return share capital data for *symbol* with end_date <= *as_of*.

        Strict historical query: only data visible on or before *as_of*.
        """
        started = perf_counter()

        if not is_eva_structure_enabled():
            return self._empty_result(symbol, started, "provider disabled by env")

        if not Path(self._db_path).exists():
            return self._empty_result(symbol, started, f"SQLite not found: {self._db_path}")

        try:
            row = self._query_as_of(symbol, as_of)
        except Exception as exc:
            return self._empty_result(symbol, started, f"query failed: {exc}")

        if row is None:
            return self._empty_result(
                symbol, started,
                f"no eva_structure_history for {symbol} with end_date <= {as_of}",
            )

        total_volume = _positive_float(row.get("total_volume"))
        float_volume = _positive_float(row.get("float_volume"))
        market_cap = _positive_float(row.get("market_cap"))
        float_market_cap = _positive_float(row.get("float_market_cap"))
        equity_per_share = _positive_float(row.get("equity_per_share"))

        data: dict[str, Any] = {
            "symbol": symbol,
            "stkcd": row.get("stkcd"),
            "as_of": row.get("end_date"),
            "short_name": row.get("short_name"),
            "source": self.provider,
        }

        if total_volume is not None and total_volume > 0:
            data["total_volume"] = total_volume
        if float_volume is not None and float_volume > 0:
            data["float_volume"] = float_volume
        if market_cap is not None and market_cap > 0:
            data["market_cap"] = market_cap
        if float_market_cap is not None and float_market_cap > 0:
            data["float_market_cap"] = float_market_cap
        if equity_per_share is not None and equity_per_share > 0:
            data["equity_per_share"] = equity_per_share

        return ProviderResult(
            provider=self.provider,
            dataset="eva_structure_history",
            symbol=symbol,
            as_of=as_of,
            data=data,
            raw=row,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def get_latest_share_capital(self, symbol: str) -> ProviderResult:
        """Return latest share capital data for *symbol*.

        On any failure (missing DB, missing symbol, stale data, invalid
        values) the result carries ``metadata.success=True`` with empty
        data -- callers treat this as "no usable data" rather than an error.
        """
        started = perf_counter()

        if not is_eva_structure_enabled():
            return self._empty_result(symbol, started, "provider disabled by env")

        if not Path(self._db_path).exists():
            return self._empty_result(symbol, started, f"SQLite not found: {self._db_path}")

        try:
            row = self._query_latest(symbol)
        except Exception as exc:
            return self._empty_result(symbol, started, f"query failed: {exc}")

        if row is None:
            return self._empty_result(symbol, started, f"symbol {symbol} not in eva_structure_latest")

        end_date_str = row.get("end_date")
        stale_warning = _stale_warning(end_date_str)
        if stale_warning:
            return self._empty_result(
                symbol,
                started,
                stale_warning,
                error_type=ProviderDataQualityError.error_type,
            )

        total_volume = _positive_float(row.get("total_volume"))
        float_volume = _positive_float(row.get("float_volume"))
        market_cap = _positive_float(row.get("market_cap"))
        float_market_cap = _positive_float(row.get("float_market_cap"))
        equity_per_share = _positive_float(row.get("equity_per_share"))

        data: dict[str, Any] = {
            "symbol": symbol,
            "stkcd": row.get("stkcd"),
            "as_of": end_date_str,
            "short_name": row.get("short_name"),
            "source": self.provider,
        }

        if total_volume is not None and total_volume > 0:
            data["total_volume"] = total_volume
        if float_volume is not None and float_volume > 0:
            data["float_volume"] = float_volume
        if market_cap is not None and market_cap > 0:
            data["market_cap"] = market_cap
        if float_market_cap is not None and float_market_cap > 0:
            data["float_market_cap"] = float_market_cap
        if equity_per_share is not None and equity_per_share > 0:
            data["equity_per_share"] = equity_per_share

        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data=data,
            raw=row,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    # -- batch API for peer loader / preflight -----------------------------

    def get_batch_share_capital(self, symbols: list[str]) -> dict[str, dict]:
        """Return share capital data for multiple symbols in one query.

        Returns a dict mapping symbol -> data dict (same fields as
        get_latest_share_capital.data).  Missing/invalid symbols are
        omitted from the result.
        """
        if not is_eva_structure_enabled():
            return {}
        if not Path(self._db_path).exists():
            return {}
        if not symbols:
            return {}

        try:
            rows = self._query_batch_latest(symbols)
        except Exception:
            return {}

        result: dict[str, dict] = {}
        stale_limit = _max_stale_days()
        today = date.today()

        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue

            end_date_str = row.get("end_date")
            if _stale_warning(end_date_str, today=today, stale_limit=stale_limit):
                continue

            total_volume = _positive_float(row.get("total_volume"))
            market_cap = _positive_float(row.get("market_cap"))
            if total_volume is None and market_cap is None:
                continue

            data: dict[str, Any] = {
                "symbol": symbol,
                "source": self.provider,
            }
            if total_volume is not None:
                data["total_volume"] = total_volume
            float_volume = _positive_float(row.get("float_volume"))
            if float_volume is not None and float_volume > 0:
                data["float_volume"] = float_volume
            if market_cap is not None and market_cap > 0:
                data["market_cap"] = market_cap

            result[symbol] = data

        return result

    # -- internal queries --------------------------------------------------

    def _query_as_of(self, symbol: str, as_of: str) -> dict[str, Any] | None:
        conn = sqlite3.connect(self._db_path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM eva_structure_history "
                "WHERE symbol = ? AND end_date <= ? "
                "ORDER BY end_date DESC LIMIT 1",
                (symbol, as_of),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def _query_latest(self, symbol: str) -> dict[str, Any] | None:
        conn = sqlite3.connect(self._db_path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM eva_structure_latest WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def _query_batch_latest(self, symbols: list[str]) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            placeholders = ",".join("?" for _ in symbols)
            cur.execute(
                f"SELECT * FROM eva_structure_latest WHERE symbol IN ({placeholders})",
                symbols,
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    # -- result helpers ----------------------------------------------------

    def _empty_result(
        self,
        symbol: str,
        started: float,
        warning: str,
        *,
        error_type: str | None = None,
    ) -> ProviderResult:
        logger.debug("EVA provider empty result for %s: %s", symbol, warning)
        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data={"symbol": symbol, "source": self.provider},
            raw=None,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                error=warning,
                error_type=error_type,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number) or number <= 0:
        return None
    return number


def _stale_warning(
    end_date_str: Any,
    *,
    today: date | None = None,
    stale_limit: int | None = None,
) -> str | None:
    if not end_date_str:
        return "EVA has missing end_date"
    effective_today = today or date.today()
    effective_limit = stale_limit if stale_limit is not None else _max_stale_days()
    try:
        field_date = datetime.strptime(str(end_date_str), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return f"EVA has unparseable end_date: {end_date_str}"
    age = (effective_today - field_date).days
    if age > effective_limit:
        return (
            f"EVA data is {age} days old (limit {effective_limit}), "
            f"last updated {end_date_str}"
        )
    return None
