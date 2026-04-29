from datetime import date


class ETFDataService:
    def build(self, asset_data: dict) -> dict:
        symbol_info = asset_data.get("symbol_info", {})
        price_data = asset_data.get("price_data", {})
        etf_data = {
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

        return {
            "data": {"etf_data": etf_data},
            "source_metadata": {
                "etf_data": {
                    "source": "mock_placeholder",
                    "confidence": 0.25,
                    "as_of": str(date.today()),
                    "note": "ETF extended data is placeholder until ETF provider is connected.",
                }
            },
            "provider_run_log": [
                {
                    "provider": "mock_placeholder",
                    "dataset": "etf_data",
                    "symbol": asset_data["symbol"],
                    "status": "placeholder",
                    "rows": 1,
                    "error": None,
                    "as_of": str(date.today()),
                }
            ],
        }
