from datetime import date
from time import perf_counter

import pandas as pd

from services.data.provider_contracts import (
    ProviderMetadata,
    ProviderResult,
    get_provider_error_type,
)
from services.network.proxy_policy import disable_proxy_for_current_process


class AKShareFundamentalProvider:
    provider = "akshare"
    dataset = "stock_financial_analysis_indicator"

    def fetch_fundamental(self, symbol_info: dict) -> ProviderResult:
        started = perf_counter()

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            plain_code = symbol_info["plain_code"]
            df = ak.stock_financial_analysis_indicator(symbol=plain_code)
            records = self._frame_to_records(df)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=records,
                raw={},
                metadata=ProviderMetadata(
                    source_url="https://data.eastmoney.com/",
                    success=True,
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except Exception as exc:
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=[],
                raw={},
                metadata=ProviderMetadata(
                    source_url="https://data.eastmoney.com/",
                    success=False,
                    error=str(exc),
                    error_type=get_provider_error_type(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _frame_to_records(self, value) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, pd.DataFrame):
            value = pd.DataFrame(value)
        if value.empty:
            return []
        return value.where(pd.notna(value), None).to_dict(orient="records")
