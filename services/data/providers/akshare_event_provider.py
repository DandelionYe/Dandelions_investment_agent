from datetime import date, timedelta
from time import perf_counter

import pandas as pd

from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.network.proxy_policy import disable_proxy_for_current_process


class AKShareEventProvider:
    provider = "akshare"
    dataset = "stock_individual_notice_report"

    def fetch_events(self, symbol_info: dict, lookback_days: int = 90) -> ProviderResult:
        started = perf_counter()
        begin = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            df = self._fetch_notice_frame(ak, symbol_info, begin, end)
            records = self._frame_to_records(df)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=records,
                raw={},
                metadata=ProviderMetadata(
                    source_url="https://data.eastmoney.com/notices/",
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
                    source_url="https://data.eastmoney.com/notices/",
                    success=False,
                    error=str(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _fetch_notice_frame(self, ak, symbol_info: dict, begin: str, end: str):
        plain_code = symbol_info["plain_code"]
        if hasattr(ak, "stock_individual_notice_report"):
            return ak.stock_individual_notice_report(
                security=plain_code,
                symbol="全部",
                begin_date=begin,
                end_date=end,
            )
        if hasattr(ak, "stock_notice_report"):
            df = ak.stock_notice_report(symbol="全部", date=end)
            records = self._frame_to_records(df)
            filtered = [
                row
                for row in records
                if plain_code
                in str(
                    row.get("代码")
                    or row.get("证券代码")
                    or row.get("股票代码")
                    or row.get("secCode")
                    or row.get("security_code")
                    or ""
                )
            ]
            return pd.DataFrame(filtered)
        raise AttributeError(
            "akshare 当前版本缺少 stock_individual_notice_report/stock_notice_report 公告接口"
        )

    def _frame_to_records(self, value) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, pd.DataFrame):
            value = pd.DataFrame(value)
        if value.empty:
            return []
        return value.where(pd.notna(value), None).to_dict(orient="records")
