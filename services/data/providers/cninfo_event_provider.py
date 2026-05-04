from datetime import date, timedelta
from time import perf_counter

import pandas as pd

from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.network.proxy_policy import disable_proxy_for_current_process


class CninfoEventProvider:
    """Primary event data provider backed by 巨潮资讯 (Cninfo) via AKShare."""

    provider = "cninfo"
    dataset = "stock_zh_a_disclosure_report_cninfo"

    def fetch_events(self, symbol_info: dict, lookback_days: int = 90) -> ProviderResult:
        started = perf_counter()
        plain_code = symbol_info["plain_code"]
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=plain_code,
                market="沪深京",
                keyword="",
                category="",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            records = self._frame_to_records(df)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=records,
                raw={},
                metadata=ProviderMetadata(
                    source_url="http://www.cninfo.com.cn/",
                    success=len(records) > 0,
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
                    source_url="http://www.cninfo.com.cn/",
                    success=False,
                    error=str(exc),
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
