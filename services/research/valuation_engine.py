from datetime import date

from services.data.normalizers.valuation_normalizer import ValuationNormalizer
from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderError,
    get_provider_error_type,
)
from services.data.providers.akshare_valuation_provider import AKShareValuationProvider
from services.data.supplemental_provider import get_placeholder_supplemental_data
from services.research.industry_valuation_engine import IndustryValuationService


class ValuationService:
    def __init__(
        self,
        normalizer: ValuationNormalizer | None = None,
        akshare_provider: AKShareValuationProvider | None = None,
        industry_service: IndustryValuationService | None = None,
    ):
        self.normalizer = normalizer or ValuationNormalizer()
        self.akshare_provider = akshare_provider or AKShareValuationProvider()
        self.industry_service = industry_service or IndustryValuationService()

    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]

        if asset_data.get("data_source") == "mock":
            return self._placeholder_result(symbol, "mock data source selected", [])

        symbol_info = asset_data.get("symbol_info", {})
        provider_run_log = []

        valuation_data = self.normalizer.derive_from_qmt(asset_data)
        metadata = {
            "source": "qmt_derived",
            "confidence": 0.72 if valuation_data.get("market_cap") else 0.45,
            "as_of": str(date.today()),
            "calculation_method": valuation_data.get("calculation_method"),
        }

        akshare_result = None
        if not self._has_core_fields(valuation_data):
            akshare_result = self.akshare_provider.fetch_valuation(symbol_info)
            provider_run_log.append(
                {
                    "provider": akshare_result.provider,
                    "dataset": akshare_result.dataset,
                    "symbol": symbol,
                    "status": "success" if akshare_result.metadata.success else "failed",
                    "rows": len(akshare_result.data) if isinstance(akshare_result.data, list) else 0,
                    "error": akshare_result.metadata.error,
                    "error_type": akshare_result.metadata.error_type,
                    "as_of": str(date.today()),
                }
            )
            if akshare_result.metadata.success:
                akshare_valuation = self.normalizer.normalize_akshare(akshare_result.to_dict())
                for key, value in akshare_valuation.items():
                    valuation_data.setdefault(key, value)
                if akshare_valuation:
                    metadata["source"] = "qmt_derived+akshare"
                    metadata["confidence"] = 0.78
                    metadata["akshare_dataset"] = akshare_result.dataset

        if not self._has_core_fields(valuation_data):
            return self._placeholder_result(
                symbol,
                (akshare_result.metadata.error if akshare_result else None)
                or "QMT-derived valuation core fields are missing.",
                provider_run_log,
            )

        valuation_data.setdefault("valuation_label", self._label(valuation_data))
        self._attach_industry_valuation(
            asset_data=asset_data,
            valuation_data=valuation_data,
            provider_run_log=provider_run_log,
        )
        return {
            "data": {"valuation_data": valuation_data},
            "source_metadata": {"valuation_data": metadata},
            "provider_run_log": provider_run_log
            + [
                {
                    "provider": metadata.get("source", "unknown"),
                    "dataset": "valuation_data",
                    "symbol": symbol,
                    "status": "success",
                    "rows": 1,
                    "error": None,
                    "error_type": None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _placeholder_result(self, symbol: str, error: str | None, provider_run_log: list[dict]) -> dict:
        supplemental = get_placeholder_supplemental_data(symbol)
        valuation_data = dict(supplemental["valuation_data"])
        valuation_data.setdefault("valuation_label", self._label(valuation_data))
        metadata = dict(supplemental["source_metadata"]["valuation_data"])
        return {
            "data": {"valuation_data": valuation_data},
            "source_metadata": {"valuation_data": metadata},
            "provider_run_log": provider_run_log
            + [
                {
                    "provider": "mock_placeholder",
                    "dataset": "valuation_data",
                    "symbol": symbol,
                    "status": "fallback_placeholder",
                    "rows": 1,
                    "error": error,
                    "error_type": ProviderDataQualityError.error_type if error else None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _has_core_fields(self, data: dict) -> bool:
        return any(data.get(field) is not None for field in ("pe_ttm", "pb_mrq", "market_cap"))

    def _attach_industry_valuation(
        self,
        *,
        asset_data: dict,
        valuation_data: dict,
        provider_run_log: list[dict],
    ) -> None:
        if asset_data.get("asset_type") != "stock":
            return

        symbol = asset_data["symbol"]
        try:
            industry_result = self.industry_service.build(asset_data, valuation_data)
            valuation_data.update(industry_result.get("fields", {}))
            provider_run_log.extend(industry_result.get("provider_run_log", []))
        except ProviderError as exc:
            self._record_industry_valuation_failure(
                valuation_data,
                provider_run_log,
                symbol=symbol,
                error=exc,
            )
        except Exception as exc:
            wrapped = ProviderDataQualityError(
                f"Industry valuation failed without blocking base valuation: {exc}"
            )
            self._record_industry_valuation_failure(
                valuation_data,
                provider_run_log,
                symbol=symbol,
                error=wrapped,
            )

    def _record_industry_valuation_failure(
        self,
        valuation_data: dict,
        provider_run_log: list[dict],
        *,
        symbol: str,
        error: BaseException,
    ) -> None:
        warnings = valuation_data.setdefault("industry_valuation_warnings", [])
        warnings.append(str(error))
        provider_run_log.append(
            {
                "provider": "qmt",
                "dataset": "industry_valuation",
                "symbol": symbol,
                "status": "failed",
                "rows": 0,
                "error": str(error),
                "error_type": get_provider_error_type(error),
                "as_of": str(date.today()),
            }
        )

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
