from datetime import date

from services.data.supplemental_provider import get_placeholder_supplemental_data


def get_mock_asset_data(symbol: str) -> dict:
    """
    模拟一只股票/ETF的基础数据。
    这里的数据是假的，只用于测试系统流程。
    """

    supplemental = get_placeholder_supplemental_data(symbol)

    asset_data = {
        "symbol": symbol,
        "asset_type": "stock",
        "name": "贵州茅台",
        "as_of": str(date.today()),
        "data_source": "mock",

        "price_data": {
            "close": 1688.0,
            "change_20d": 0.052,
            "change_60d": 0.083,
            "ma20_position": "above",
            "ma60_position": "above",
            "max_drawdown_60d": -0.092,
            "volatility_60d": 0.186,
            "avg_turnover_20d": 4800000000,
            "data_vendor": "mock",
        },
        "source_metadata": {
            "price_data": {
                "source": "mock",
                "confidence": 0.2,
                "as_of": str(date.today()),
                "vendor": "mock",
                "note": "Synthetic price data for offline pipeline tests.",
            },
        }
    }

    asset_data.update(
        {
            "fundamental_data": supplemental["fundamental_data"],
            "valuation_data": supplemental["valuation_data"],
            "event_data": supplemental["event_data"],
        }
    )
    asset_data["source_metadata"].update(supplemental["source_metadata"])

    return asset_data
