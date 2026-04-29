from datetime import date

from services.data.supplemental_provider import get_placeholder_supplemental_data


class ValuationService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        supplemental = get_placeholder_supplemental_data(symbol)
        valuation_data = dict(asset_data.get("valuation_data") or supplemental["valuation_data"])
        metadata = dict(
            asset_data.get("source_metadata", {}).get("valuation_data")
            or supplemental["source_metadata"]["valuation_data"]
        )

        valuation_data.setdefault("valuation_label", self._label(valuation_data))

        return {
            "data": {"valuation_data": valuation_data},
            "source_metadata": {"valuation_data": metadata},
            "provider_run_log": [
                {
                    "provider": metadata.get("source", "unknown"),
                    "dataset": "valuation_data",
                    "symbol": symbol,
                    "status": "placeholder" if metadata.get("source") == "mock_placeholder" else "success",
                    "rows": 1 if valuation_data else 0,
                    "error": None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _label(self, data: dict) -> str:
        pe_percentile = data.get("pe_percentile")
        pb_percentile = data.get("pb_percentile")
        pe_ttm = data.get("pe_ttm")

        if pe_ttm is not None and pe_ttm <= 0:
            return "loss_making_or_invalid_pe"
        if pe_percentile is None:
            return "unavailable"
        if pe_percentile <= 0.25 and (pb_percentile is None or pb_percentile <= 0.35):
            return "cheap"
        if pe_percentile <= 0.60:
            return "reasonable"
        if pe_percentile <= 0.80:
            return "slightly_expensive"
        return "expensive"
