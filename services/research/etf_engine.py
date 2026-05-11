from datetime import date

from services.data.normalizers.etf_normalizer import ETFNormalizer
from services.data.provider_contracts import ProviderDataQualityError
from services.data.providers.etf_provider import AKShareETFProvider


class ETFDataService:
    def __init__(self):
        self.provider = AKShareETFProvider()
        self.normalizer = ETFNormalizer()

    def build(self, asset_data: dict) -> dict:
        symbol_info = asset_data.get("symbol_info", {})
        price_data = asset_data.get("price_data", {})

        base = {
            "fund_code": symbol_info.get("plain_code", asset_data["symbol"].split(".")[0]),
            "fund_name": asset_data.get("name", asset_data["symbol"]),
            "tracking_index": None,
            "fund_size": None,
            "nav": None,
            "market_price": price_data.get("close"),
            "premium_discount": None,
            "avg_turnover_20d": price_data.get("avg_turnover_20d"),
            "tracking_error": None,
            "management_fee": None,
            "custodian_fee": None,
            "top_holdings": [],
            "index_valuation": {
                "pe_ttm": None,
                "pb": None,
                "pe_percentile": None,
            },
        }

        source = "mock_placeholder"
        confidence = 0.25
        provider_run_log = [
            {
                "provider": "mock_placeholder",
                "dataset": "etf_data",
                "symbol": asset_data["symbol"],
                "status": "placeholder",
                "rows": 1,
                "error": None,
                "error_type": None,
                "as_of": str(date.today()),
            }
        ]

        if asset_data.get("data_source") != "mock":
            info_result = self.provider.fetch_etf_data(symbol_info)
            if info_result.metadata.success and info_result.data:
                info_normalized = self.normalizer.normalize_akshare_info(info_result.to_dict())
                for key, value in info_normalized.items():
                    if value is not None:
                        base[key] = value
                source = "akshare"
                confidence = 0.65

            spot_result = self.provider.fetch_etf_spot(symbol_info)
            if spot_result.metadata.success and spot_result.data:
                spot_normalized = self.normalizer.normalize_akshare_spot(spot_result.to_dict())
                for key, value in spot_normalized.items():
                    if value is not None:
                        base[key] = value
                if spot_normalized.get("nav"):
                    source = "akshare"
                    confidence = 0.70

            provider_run_log = [
                {
                    "provider": "akshare",
                    "dataset": "etf_data",
                    "symbol": asset_data["symbol"],
                    "status": "success" if source == "akshare" else "placeholder",
                    "rows": len(info_result.data) + len(spot_result.data or []),
                    "error": None if source == "akshare" else "AKShare ETF data unavailable.",
                    "error_type": None if source == "akshare" else ProviderDataQualityError.error_type,
                    "as_of": str(date.today()),
                }
            ]

        note = None if source != "mock_placeholder" else "ETF extended data is placeholder until ETF provider is connected."
        return {
            "data": {"etf_data": base},
            "source_metadata": {
                "etf_data": {
                    "source": source,
                    "confidence": confidence,
                    "as_of": str(date.today()),
                    **({"note": note} if note else {}),
                }
            },
            "provider_run_log": provider_run_log,
        }
