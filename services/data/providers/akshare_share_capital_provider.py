"""AKShare-based share capital fallback provider.

When QMT get_instrument_detail() returns TotalVolume=0 or missing,
this provider fetches total_volume / float_volume / market_cap from
AKShare's stock_individual_info_em (东方财富个股信息).

Failures never block the main pipeline — the provider returns
metadata.success=False with a clear error message.
"""

from __future__ import annotations

import math
import os
from datetime import date
from time import perf_counter
from typing import Any, Mapping, Sequence

from services.data.provider_contracts import (
    ProviderMetadata,
    ProviderResult,
    get_provider_error_type,
)
from services.network.proxy_policy import disable_proxy_for_current_process


def _parse_cn_number(value: Any) -> float | None:
    """Parse a numeric value that may be a string with Chinese units (亿/万).

    Handles formats like "809.32亿", "809.32亿股", "8000万", "8000万股",
    "12345", "12,345". Returns None for missing/unparseable values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)

    text = str(value).strip()
    if not text or text in ("--", "-", "nan", "None", ""):
        return None

    # Remove common trailing unit characters (股, 元, etc.) before checking 亿/万
    for suffix in ("股", "元"):
        if text.endswith(suffix):
            text = text[:-1].strip()

    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 1e8
        text = text[:-1].strip()
    elif text.endswith("万"):
        multiplier = 1e4
        text = text[:-1].strip()

    text = text.replace(",", "").replace(" ", "")
    try:
        return float(text) * multiplier
    except (ValueError, TypeError):
        return None


def _extract_field(df: Any, field_name: str) -> float | None:
    """Extract a single field value from stock_individual_info_em result."""
    if df is None or not hasattr(df, "empty") or df.empty:
        return None

    # The DataFrame has columns like "item" and "value"
    item_col = None
    value_col = None
    for col in df.columns:
        col_str = str(col).strip().lower()
        if col_str in ("item", "项目", "指标"):
            item_col = col
        elif col_str in ("value", "值", "数值"):
            value_col = col

    if item_col is None or value_col is None:
        # Fallback: assume first col is item, second is value
        if len(df.columns) >= 2:
            item_col = df.columns[0]
            value_col = df.columns[1]
        else:
            return None

    for _, row in df.iterrows():
        item_text = str(row.get(item_col, "")).strip()
        if item_text == field_name:
            return _parse_cn_number(row.get(value_col))

    return None


def _symbol_to_eastmoney_code(symbol: str) -> str:
    """Convert 600519.SH -> 600519 (6-digit code for AKShare)."""
    return symbol.split(".")[0]


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= 0:
        return None
    return number


class AKShareShareCapitalProvider:
    """Fetch total_volume / float_volume / market_cap from AKShare.

    Uses ak.stock_individual_info_em(symbol=6位代码).
    """

    provider = "akshare"
    dataset = "stock_individual_info_em"

    def fetch_share_capital(self, symbol: str) -> ProviderResult:
        started = perf_counter()
        code = _symbol_to_eastmoney_code(symbol)

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            df = ak.stock_individual_info_em(symbol=code)
        except Exception as exc:
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=str(date.today()),
                data={},
                raw=None,
                metadata=ProviderMetadata(
                    source_url="https://emweb.securities.eastmoney.com/",
                    success=False,
                    error=str(exc),
                    error_type=get_provider_error_type(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

        data = self._parse_info(df)

        if not data.get("total_volume") and not data.get("market_cap"):
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=str(date.today()),
                data=data,
                raw=None,
                metadata=ProviderMetadata(
                    source_url="https://emweb.securities.eastmoney.com/",
                    success=False,
                    error="AKShare stock_individual_info_em returned no usable share capital data",
                    error_type="provider_data_quality",
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data=data,
            raw=None,
            metadata=ProviderMetadata(
                source_url="https://emweb.securities.eastmoney.com/",
                success=True,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def _parse_info(self, df: Any) -> dict:
        total_volume = _extract_field(df, "总股本")
        float_volume = _extract_field(df, "流通股")
        market_cap = _extract_field(df, "总市值")
        float_market_cap = _extract_field(df, "流通市值")

        result: dict[str, Any] = {}
        if total_volume is not None and total_volume > 0:
            result["total_volume"] = total_volume
        if float_volume is not None and float_volume > 0:
            result["float_volume"] = float_volume
        if market_cap is not None and market_cap > 0:
            result["market_cap"] = market_cap
        if float_market_cap is not None and float_market_cap > 0:
            result["float_market_cap"] = float_market_cap

        return result


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def is_share_capital_fallback_enabled() -> bool:
    provider = os.getenv("QMT_SHARE_CAPITAL_FALLBACK_PROVIDER", "akshare").strip().lower()
    return provider not in {"disabled", "off", "none", ""}


def get_share_capital_fallback_max_symbols() -> int:
    return int(os.getenv("QMT_SHARE_CAPITAL_FALLBACK_MAX_SYMBOLS", "50"))


def resolve_share_capital_fallback(
    symbols: Sequence[str],
    *,
    close_map: Mapping[str, float | None] | None = None,
    provider: AKShareShareCapitalProvider | None = None,
    max_symbols: int | None = None,
) -> dict:
    """Resolve share-capital fallback data for a bounded symbol list.

    The returned payload is intentionally structured so callers can surface
    skipped symbols and provider failures instead of silently truncating work.
    """
    ordered_symbols = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    if not is_share_capital_fallback_enabled():
        return {
            "enabled": False,
            "max_symbols": 0,
            "attempted_symbols": [],
            "skipped_symbols": [],
            "skipped_count": 0,
            "values": {},
            "errors": [],
        }

    limit = max(0, max_symbols if max_symbols is not None else get_share_capital_fallback_max_symbols())
    attempted_symbols = ordered_symbols[:limit]
    skipped_symbols = ordered_symbols[limit:]
    effective_provider = provider or AKShareShareCapitalProvider()
    values: dict[str, dict] = {}
    errors: list[dict[str, str | None]] = []
    closes = close_map or {}

    for symbol in attempted_symbols:
        result = effective_provider.fetch_share_capital(symbol)
        if not result.metadata.success:
            errors.append({
                "symbol": symbol,
                "error": result.metadata.error,
                "error_type": result.metadata.error_type,
            })
            continue

        data = dict(result.data) if isinstance(result.data, dict) else {}
        total_volume = _positive_float(data.get("total_volume"))
        market_cap = _positive_float(data.get("market_cap"))
        close = _positive_float(closes.get(symbol))

        if total_volume is None and market_cap is not None and close is not None:
            total_volume = market_cap / close
            data["total_volume"] = total_volume
            data["total_volume_inferred_from_market_cap"] = True

        if total_volume is not None:
            data["total_volume"] = total_volume
            values[symbol] = data

    return {
        "enabled": True,
        "max_symbols": limit,
        "attempted_symbols": attempted_symbols,
        "skipped_symbols": skipped_symbols,
        "skipped_count": len(skipped_symbols),
        "values": values,
        "errors": errors,
    }
