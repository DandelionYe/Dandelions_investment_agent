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
from typing import Any

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
