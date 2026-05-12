import os
from datetime import date, timedelta
from typing import Any, Sequence

import pandas as pd

from services.data.market_data_utils import guess_asset_type
from services.data.normalizers.common import _first_present, _to_float
from services.data.normalizers.fundamental_normalizer import (
    NET_PROFIT_FIELDS,
    REPORT_PERIOD_FIELDS,
    REVENUE_FIELDS,
    _annualize_statement_amount,
    _latest_record,
)
from services.data.provider_contracts import (
    ProviderSchemaError,
    ProviderUnavailableError,
)
from services.data.providers.qmt_financial_provider import QMT_FINANCIAL_TABLES
from services.data.qmt_provider import _env_bool, _import_xtdata, connect_qmt

TOTAL_VOLUME_FIELDS = [
    "TotalVolume",
    "total_volume",
    "totalVol",
    "total_share",
    "total_shares",
    "capital_stock",
    "总股本",
]
FLOAT_VOLUME_FIELDS = [
    "FloatVolume",
    "float_volume",
    "floatVol",
    "float_share",
    "float_shares",
    "circulating_share",
    "流通股本",
]
BPS_FIELDS = [
    "每股净资产",
    "s_fa_bps",
    "bps",
    "BPS",
    "book_value_per_share",
    "net_asset_per_share",
]


class QMTPeerValuationLoader:
    """Batch loader for peer valuation inputs from QMT.

    The loader intentionally returns plain dicts. Research-layer code converts
    them into PeerValuationInput to avoid a data-layer dependency on research
    dataclasses.
    """

    provider = "qmt"
    dataset = "peer_valuation_inputs"

    def __init__(self, chunk_size: int | None = None) -> None:
        configured_chunk_size = chunk_size or int(
            os.getenv("QMT_INDUSTRY_PEER_CHUNK_SIZE", "80")
        )
        self.chunk_size = max(1, configured_chunk_size)

    def load_peer_inputs(
        self,
        symbols: Sequence[str],
        as_of: str | None = None,
    ) -> list[dict]:
        cleaned_symbols = self._clean_symbols(symbols)
        if not cleaned_symbols:
            return []

        try:
            xtdata = _import_xtdata()
            connect_qmt()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(f"QMT peer valuation connection failed: {exc}") from exc

        end_date = self._parse_date(as_of or str(date.today()))
        end = end_date.strftime("%Y%m%d")
        start = (end_date - timedelta(days=365 * 6)).strftime("%Y%m%d")
        price_map = self._load_latest_prices(xtdata, cleaned_symbols, end)
        detail_map = self._load_instrument_details(xtdata, cleaned_symbols)
        financial_map = self._load_financial_metrics(xtdata, cleaned_symbols, start, end)

        peers = []
        for symbol in cleaned_symbols:
            detail = detail_map.get(symbol, {})
            financial = financial_map.get(symbol, {})
            name = (
                detail.get("InstrumentName")
                or detail.get("instrument_name")
                or detail.get("name")
                or symbol
            )
            peers.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "asset_type": guess_asset_type(symbol),
                    "close": price_map.get(symbol),
                    "total_volume": self._first_float(detail, TOTAL_VOLUME_FIELDS),
                    "float_volume": self._first_float(detail, FLOAT_VOLUME_FIELDS),
                    "net_profit_ttm": financial.get("net_profit_ttm"),
                    "revenue_ttm": financial.get("revenue_ttm"),
                    "bps": financial.get("bps"),
                    "is_st": self._is_st(name, detail),
                    "is_suspended": price_map.get(symbol) is None,
                }
            )
        return peers

    def _load_latest_prices(self, xtdata: Any, symbols: list[str], end: str) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for chunk in self._chunks(symbols):
            try:
                raw = xtdata.get_market_data_ex(
                    field_list=["time", "close"],
                    stock_list=chunk,
                    period=os.getenv("QMT_PERIOD", "1d"),
                    start_time="",
                    end_time=end,
                    count=1,
                    dividend_type=os.getenv("QMT_DIVIDEND_TYPE", "front"),
                    fill_data=True,
                )
            except Exception as exc:
                raise ProviderUnavailableError(f"QMT peer price query failed: {exc}") from exc

            for symbol in chunk:
                df = self._to_dataframe(raw, symbol)
                result[symbol] = self._latest_close(df)
        return result

    def _load_instrument_details(self, xtdata: Any, symbols: list[str]) -> dict[str, dict]:
        details: dict[str, dict] = {}
        for symbol in symbols:
            try:
                detail = xtdata.get_instrument_detail(symbol)
            except Exception:
                detail = {}
            details[symbol] = detail if isinstance(detail, dict) else {}
        return details

    def _load_financial_metrics(
        self,
        xtdata: Any,
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict[str, dict]:
        metrics: dict[str, dict] = {}
        for chunk in self._chunks(symbols):
            try:
                if _env_bool("QMT_INDUSTRY_FINANCIAL_AUTO_DOWNLOAD", False):
                    xtdata.download_financial_data(
                        chunk,
                        QMT_FINANCIAL_TABLES,
                        start,
                        end,
                        incrementally=True,
                    )
                raw = xtdata.get_financial_data(
                    chunk,
                    QMT_FINANCIAL_TABLES,
                    start,
                    end,
                    report_type="report_time",
                )
            except Exception as exc:
                raise ProviderUnavailableError(f"QMT peer financial query failed: {exc}") from exc

            if not isinstance(raw, dict):
                raise ProviderSchemaError(
                    f"QMT peer financial response must be dict, got {type(raw).__name__}"
                )

            for symbol in chunk:
                tables = raw.get(symbol, {})
                if not isinstance(tables, dict):
                    metrics[symbol] = {}
                    continue
                metrics[symbol] = self._extract_financial_metrics(tables)
        return metrics

    def _extract_financial_metrics(self, tables: dict) -> dict:
        pershare = _latest_record(self._frame_to_records(tables.get("PershareIndex")))
        income = _latest_record(self._frame_to_records(tables.get("Income")))
        report_period = _first_present(income or pershare, REPORT_PERIOD_FIELDS)
        revenue = _to_float(_first_present(income, REVENUE_FIELDS))
        net_profit = _to_float(_first_present(income, NET_PROFIT_FIELDS))
        bps = self._first_float(pershare, BPS_FIELDS)

        return {
            "revenue_ttm": _annualize_statement_amount(revenue, report_period),
            "net_profit_ttm": _annualize_statement_amount(net_profit, report_period),
            "bps": bps,
        }

    def _chunks(self, symbols: list[str]) -> list[list[str]]:
        return [
            symbols[index:index + self.chunk_size]
            for index in range(0, len(symbols), self.chunk_size)
        ]

    @staticmethod
    def _clean_symbols(symbols: Sequence[str]) -> list[str]:
        seen = set()
        result = []
        for symbol in symbols:
            normalized = str(symbol).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _parse_date(value: str) -> date:
        compact = str(value).replace("-", "").strip()
        if len(compact) != 8 or not compact.isdigit():
            raise ProviderSchemaError(f"Invalid QMT peer valuation date: {value}")
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))

    @staticmethod
    def _to_dataframe(raw: Any, symbol: str) -> pd.DataFrame:
        if isinstance(raw, dict):
            value = raw.get(symbol)
            if value is None and raw:
                value = next(iter(raw.values()))
        else:
            value = raw

        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            return value
        try:
            return pd.DataFrame(value)
        except Exception as exc:
            raise ProviderSchemaError(
                f"QMT peer price response cannot be converted to DataFrame for {symbol}: {exc}"
            ) from exc

    @staticmethod
    def _latest_close(df: pd.DataFrame) -> float | None:
        if df.empty:
            return None
        close_col = QMTPeerValuationLoader._find_column(df, ["close", "收盘", "Close"])
        if close_col is None:
            return None
        series = pd.to_numeric(df[close_col], errors="coerce").dropna()
        if series.empty:
            return None
        latest = float(series.iloc[-1])
        return latest if latest > 0 else None

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
        lower_columns = {str(column).lower(): column for column in df.columns}
        for candidate in candidates:
            if candidate.lower() in lower_columns:
                return lower_columns[candidate.lower()]
        return None

    @staticmethod
    def _frame_to_records(value: Any) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, pd.DataFrame):
            value = pd.DataFrame(value)
        if value.empty:
            return []
        return value.where(pd.notna(value), None).to_dict(orient="records")

    @staticmethod
    def _first_float(row: dict, candidates: list[str]) -> float | None:
        return _to_float(_first_present(row or {}, candidates))

    @staticmethod
    def _is_st(name: Any, detail: dict) -> bool:
        if bool(detail.get("IsST") or detail.get("is_st")):
            return True
        text = str(name or "").upper()
        return "ST" in text or "*ST" in text
