from datetime import date
from time import perf_counter, time

import pandas as pd

from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.network.proxy_policy import disable_proxy_for_current_process

_etf_spot_cache: pd.DataFrame | None = None
_etf_spot_cache_time: float = 0
_ETF_SPOT_CACHE_TTL = 300  # 5 分钟


class AKShareETFProvider:
    provider = "akshare"
    dataset = "fund_etf_info"

    def fetch_etf_data(self, symbol_info: dict) -> ProviderResult:
        started = perf_counter()
        plain_code = symbol_info["plain_code"]

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            records: list[dict] = []

            # ETF basic info (fund size, name, fees, underlying index)
            try:
                info_df = ak.fund_etf_fund_info_em(
                    fund=plain_code, start_date="19900101", end_date=str(date.today())
                )
                if info_df is not None and not info_df.empty:
                    records = self._frame_to_records(info_df)
            except Exception:
                pass

            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=records,
                raw={},
                metadata=ProviderMetadata(
                    source_url="https://fund.eastmoney.com/",
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
                    source_url="https://fund.eastmoney.com/",
                    success=False,
                    error=str(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def fetch_etf_spot(self, symbol_info: dict) -> ProviderResult:
        """Fetch real-time ETF spot data (NAV, premium/discount)."""
        started = perf_counter()
        plain_code = symbol_info["plain_code"]

        try:
            disable_proxy_for_current_process()
            import akshare as ak

            global _etf_spot_cache, _etf_spot_cache_time
            if _etf_spot_cache is not None and time() - _etf_spot_cache_time < _ETF_SPOT_CACHE_TTL:
                df = _etf_spot_cache
            else:
                df = ak.fund_etf_spot_em()
                _etf_spot_cache = df
                _etf_spot_cache_time = time()
            if df is not None and not df.empty:
                records = self._frame_to_records(df)
                matched = [
                    row for row in records
                    if str(row.get("代码") or row.get("基金代码") or "") == plain_code
                ]
                return ProviderResult(
                    provider=self.provider,
                    dataset="fund_etf_spot",
                    symbol=symbol_info["normalized_symbol"],
                    as_of=str(date.today()),
                    data=matched,
                    raw={},
                    metadata=ProviderMetadata(
                        source_url="https://fund.eastmoney.com/",
                        success=len(matched) > 0,
                        latency_ms=int((perf_counter() - started) * 1000),
                    ),
                )
            return ProviderResult(
                provider=self.provider,
                dataset="fund_etf_spot",
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=[],
                raw={},
                metadata=ProviderMetadata(success=False, error="Empty response from AKShare"),
            )
        except Exception as exc:
            return ProviderResult(
                provider=self.provider,
                dataset="fund_etf_spot",
                symbol=symbol_info["normalized_symbol"],
                as_of=str(date.today()),
                data=[],
                raw={},
                metadata=ProviderMetadata(success=False, error=str(exc)),
            )

    def _frame_to_records(self, value) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, pd.DataFrame):
            value = pd.DataFrame(value)
        if value.empty:
            return []
        return value.where(pd.notna(value), None).to_dict(orient="records")
