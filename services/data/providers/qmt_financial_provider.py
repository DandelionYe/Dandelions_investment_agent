from datetime import date, timedelta
from time import perf_counter
from typing import Any

import pandas as pd

from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.data.qmt_provider import _env_bool, _import_xtdata, connect_qmt


QMT_FINANCIAL_TABLES = ["Balance", "Income", "CashFlow", "PershareIndex"]


class QMTFinancialProvider:
    provider = "qmt"
    dataset = "financial_data"

    def fetch_fundamental(self, symbol_info: dict) -> ProviderResult:
        symbol = symbol_info["qmt_code"]
        start = (date.today() - timedelta(days=365 * 6)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")
        started = perf_counter()

        try:
            xtdata = _import_xtdata()
            connect_qmt()
            if _env_bool("QMT_FINANCIAL_AUTO_DOWNLOAD", False):
                xtdata.download_financial_data(
                    [symbol],
                    QMT_FINANCIAL_TABLES,
                    start,
                    end,
                    incrementally=True,
                )
            raw = xtdata.get_financial_data(
                [symbol],
                QMT_FINANCIAL_TABLES,
                start,
                end,
                report_type="report_time",
            )
            tables = raw.get(symbol, {}) if isinstance(raw, dict) else {}
            data = {
                table: self._frame_to_records(tables.get(table))
                for table in QMT_FINANCIAL_TABLES
            }
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=end,
                data=data,
                raw={},
                metadata=ProviderMetadata(
                    source_url=None,
                    success=True,
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except Exception as exc:
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=end,
                data={},
                raw={},
                metadata=ProviderMetadata(
                    source_url=None,
                    success=False,
                    error=str(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _frame_to_records(self, value: Any) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, pd.DataFrame):
            value = pd.DataFrame(value)
        if value.empty:
            return []
        return value.where(pd.notna(value), None).to_dict(orient="records")
