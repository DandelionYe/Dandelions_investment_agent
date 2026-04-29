from services.data.aggregator.evidence_builder import EvidenceBuilder
from services.data.quality.data_quality_rules import DataQualityService
from services.data.symbol_resolver import SymbolResolver
from services.research.etf_engine import ETFDataService
from services.research.event_engine import EventService
from services.research.fundamental_engine import FundamentalService
from services.research.valuation_engine import ValuationService
from services.protocols.validation import validate_protocol


class ResearchDataAggregator:
    def __init__(self):
        self.symbol_resolver = SymbolResolver()
        self.fundamental_service = FundamentalService()
        self.valuation_service = ValuationService()
        self.event_service = EventService()
        self.etf_service = ETFDataService()
        self.quality_service = DataQualityService()
        self.evidence_builder = EvidenceBuilder()

    def enrich(self, asset_data: dict) -> dict:
        symbol_info = self.symbol_resolver.resolve(asset_data["symbol"])
        merged = dict(asset_data)
        merged["symbol"] = symbol_info["normalized_symbol"]
        merged["asset_type"] = symbol_info["asset_type"]
        merged["symbol_info"] = symbol_info

        source_metadata = dict(merged.get("source_metadata", {}))
        provider_run_log = list(merged.get("provider_run_log", []))

        if merged["asset_type"] == "etf":
            etf_result = self.etf_service.build(merged)
            merged.update(etf_result["data"])
            source_metadata.update(etf_result["source_metadata"])
            provider_run_log.extend(etf_result["provider_run_log"])

        fundamental_result = self.fundamental_service.build(merged)
        merged.update(fundamental_result["data"])
        source_metadata.update(fundamental_result["source_metadata"])
        provider_run_log.extend(fundamental_result["provider_run_log"])

        valuation_result = self.valuation_service.build(merged)
        merged.update(valuation_result["data"])
        source_metadata.update(valuation_result["source_metadata"])
        provider_run_log.extend(valuation_result["provider_run_log"])

        event_result = self.event_service.build(merged)
        for result in (event_result,):
            merged.update(result["data"])
            source_metadata.update(result["source_metadata"])
            provider_run_log.extend(result["provider_run_log"])

        merged["source_metadata"] = source_metadata
        merged["provider_run_log"] = provider_run_log
        merged["data_quality"] = self.quality_service.build_report(merged)
        merged["evidence_bundle"] = self.evidence_builder.build(merged)
        validate_protocol("data_quality", merged["data_quality"])
        validate_protocol("evidence_bundle", merged["evidence_bundle"])

        return merged
