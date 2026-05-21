"""Local CSMAR daily-derived snapshot provider.

Reads from a pre-built SQLite database that aggregates CSMAR
个股日交易衍生指标 data.  This provider is strictly a **fallback**:
callers must only use it when QMT / existing valuation chains
cannot supply a given field.

Tables consumed:
  - latest_non_null_metrics  (per-symbol, per-field latest non-null value + date)
  - monthly_snapshots        (per-symbol, per-month last trading day)

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
from typing import Any, Sequence

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


def is_csmar_daily_derived_enabled() -> bool:
    return _env_bool("CSMAR_DAILY_DERIVED_PROVIDER", True)


def _db_path() -> str:
    return os.getenv(
        "CSMAR_DAILY_DERIVED_DB",
        "storage/reference/csmar_daily_derived_snapshots.sqlite",
    )


def _max_stale_days_general() -> int:
    return _env_int("CSMAR_DAILY_DERIVED_MAX_STALE_DAYS", 370)


def _max_stale_days_valuation() -> int:
    return _env_int("CSMAR_DAILY_DERIVED_VALUATION_MAX_STALE_DAYS", 45)


# ---------------------------------------------------------------------------
# Field groups (valuation fields use shorter staleness window)
# ---------------------------------------------------------------------------

_VALUATION_FIELDS = frozenset({"pe", "pb", "pcf", "ps"})
_ALL_FIELDS = frozenset({
    "dividend_yield", "pe", "pb", "pcf", "ps",
    "turnover", "circulated_market_value",
    "change_ratio", "amount", "liquidility",
})


def _stale_limit_for_field(field: str) -> int:
    if field in _VALUATION_FIELDS:
        return _max_stale_days_valuation()
    return _max_stale_days_general()


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class LocalCSMARDailyDerivedProvider:
    """Read-only fallback provider backed by the local CSMAR SQLite snapshot."""

    provider = "local_csmar_daily_derived"
    dataset = "csmar_daily_derived_snapshots"

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _db_path()

    # -- public API --------------------------------------------------------

    def get_latest_metrics(self, symbol: str) -> ProviderResult:
        """Return the latest non-null metrics for *symbol*.

        On any failure (missing DB, missing symbol, stale data) the result
        carries ``metadata.success=True`` with empty data and warnings --
        callers treat this as "no usable data" rather than an error.
        """
        started = perf_counter()
        warnings: list[str] = []

        if not is_csmar_daily_derived_enabled():
            return self._empty_result(symbol, started, "provider disabled by env")

        if not Path(self._db_path).exists():
            return self._empty_result(symbol, started, f"SQLite not found: {self._db_path}")

        try:
            row = self._query_latest_non_null(symbol)
        except Exception as exc:
            return self._empty_result(symbol, started, f"query failed: {exc}")

        if row is None:
            return self._empty_result(symbol, started, f"symbol {symbol} not in latest_non_null_metrics")

        today = date.today()
        data: dict[str, Any] = {"symbol": symbol, "source": self.provider}

        for field in _ALL_FIELDS:
            value = row.get(field)
            date_str = row.get(f"{field}_date")
            if value is None:
                continue

            stale_days = _stale_limit_for_field(field)
            if date_str:
                try:
                    field_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
                    age = (today - field_date).days
                    if age > stale_days:
                        warnings.append(
                            f"{field} is {age} days old (limit {stale_days}), "
                            f"last updated {date_str}"
                        )
                        continue
                except (ValueError, TypeError):
                    warnings.append(f"{field} has unparseable date: {date_str}")
                    continue

            data[field] = _safe_float(value)
            data[f"{field}_date"] = date_str

        # Always carry source even if all fields were filtered out
        data["source"] = self.provider
        if warnings:
            data["warnings"] = warnings

        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(today),
            data=data,
            raw=row,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                error="; ".join(warnings) if warnings else None,
                error_type=ProviderDataQualityError.error_type if warnings else None,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def get_monthly_history(
        self,
        symbols: Sequence[str],
        metrics: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ProviderResult:
        """Return monthly snapshot history for *symbols* x *metrics*.

        Returns a ProviderResult whose ``data`` is a list of row dicts,
        each containing ``symbol``, ``trading_date``, ``period``, and the
        requested metric columns.
        """
        started = perf_counter()
        symbols = list(symbols)
        metrics = list(metrics)

        if not is_csmar_daily_derived_enabled():
            return self._empty_list_result(symbols, started, "provider disabled by env")

        if not Path(self._db_path).exists():
            return self._empty_list_result(symbols, started, f"SQLite not found: {self._db_path}")

        if not symbols:
            return self._empty_list_result(symbols, started, "no symbols requested")

        # Validate requested metrics against known columns
        valid_metrics = [m for m in metrics if m in _ALL_FIELDS]
        if not valid_metrics:
            return self._empty_list_result(symbols, started, f"no valid metrics in {metrics}")

        try:
            rows = self._query_monthly_snapshots(symbols, valid_metrics, start_date, end_date)
        except Exception as exc:
            return self._empty_list_result(symbols, started, f"query failed: {exc}")

        return ProviderResult(
            provider=self.provider,
            dataset="monthly_snapshots",
            symbol=",".join(symbols[:5]) + ("..." if len(symbols) > 5 else ""),
            as_of=str(date.today()),
            data=rows,
            raw=None,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    # -- internal queries --------------------------------------------------

    def _query_latest_non_null(self, symbol: str) -> dict[str, Any] | None:
        conn = sqlite3.connect(self._db_path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM latest_non_null_metrics WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def _query_monthly_snapshots(
        self,
        symbols: Sequence[str],
        metrics: Sequence[str],
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict[str, Any]]:
        columns = ["symbol", "trading_date", "period"] + list(metrics)
        col_clause = ", ".join(columns)
        placeholders = ",".join("?" for _ in symbols)

        sql = f"SELECT {col_clause} FROM monthly_snapshots WHERE symbol IN ({placeholders})"
        params: list[Any] = list(symbols)

        if start_date:
            sql += " AND trading_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trading_date <= ?"
            params.append(end_date)

        sql += " ORDER BY symbol, trading_date"

        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            col_names = [desc[0] for desc in cur.description]
            return [dict(zip(col_names, row, strict=False)) for row in cur.fetchall()]
        finally:
            conn.close()

    # -- result helpers ----------------------------------------------------

    def _empty_result(self, symbol: str, started: float, warning: str) -> ProviderResult:
        logger.debug("CSMAR provider empty result for %s: %s", symbol, warning)
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
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def _empty_list_result(self, symbols: list[str], started: float, warning: str) -> ProviderResult:
        logger.debug("CSMAR provider empty list result: %s", warning)
        return ProviderResult(
            provider=self.provider,
            dataset="monthly_snapshots",
            symbol=",".join(symbols[:5]) + ("..." if len(symbols) > 5 else ""),
            as_of=str(date.today()),
            data=[],
            raw=None,
            metadata=ProviderMetadata(
                source_url=f"sqlite:///{self._db_path}",
                success=True,
                error=warning,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
