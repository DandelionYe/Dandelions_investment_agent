from datetime import date

from services.data.normalizers.fundamental_normalizer import FundamentalNormalizer
from services.data.provider_contracts import ProviderDataQualityError
from services.data.providers.akshare_fundamental_provider import AKShareFundamentalProvider
from services.data.providers.qmt_financial_provider import QMTFinancialProvider
from services.data.supplemental_provider import get_placeholder_supplemental_data


class FundamentalService:
    def __init__(self):
        self.qmt_provider = QMTFinancialProvider()
        self.akshare_provider = AKShareFundamentalProvider()
        self.normalizer = FundamentalNormalizer()

    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        symbol_info = asset_data.get("symbol_info", {})

        if asset_data.get("data_source") == "mock":
            return self._placeholder_result(symbol, "mock data source selected", [])

        provider_run_log = []

        # 1. Try QMT financial tables
        qmt_result = self.qmt_provider.fetch_fundamental(symbol_info)
        provider_run_log.append(
            {
                "provider": qmt_result.provider,
                "dataset": qmt_result.dataset,
                "symbol": symbol,
                "status": "success" if qmt_result.metadata.success else "failed",
                "rows": sum(len(rows) for rows in qmt_result.data.values()) if isinstance(qmt_result.data, dict) else 0,
                "error": qmt_result.metadata.error,
                "error_type": qmt_result.metadata.error_type,
                "as_of": str(date.today()),
            }
        )

        if qmt_result.metadata.success:
            normalized = self.normalizer.normalize_qmt(qmt_result.to_dict())
            fundamental_data = normalized["normalized"]
            if self._has_core_fields(fundamental_data):
                metadata = {
                    "source": "qmt_financial",
                    "confidence": 0.78,
                    "as_of": str(date.today()),
                    "provider": qmt_result.provider,
                    "dataset": qmt_result.dataset,
                    "field_sources": normalized["field_sources"],
                }
                return self._build_result(
                    symbol=symbol,
                    fundamental_data=fundamental_data,
                    metadata=metadata,
                    status="success",
                    rows=sum(len(rows) for rows in qmt_result.data.values()),
                    error=None,
                )

        # 2. Fallback to AKShare
        akshare_result = self.akshare_provider.fetch_fundamental(symbol_info)
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
            normalized = self.normalizer.normalize_akshare(akshare_result.to_dict())
            fundamental_data = normalized["normalized"]
            if self._has_core_fields(fundamental_data):
                metadata = {
                    "source": "akshare",
                    "confidence": 0.68,
                    "as_of": str(date.today()),
                    "provider": akshare_result.provider,
                    "dataset": akshare_result.dataset,
                    "field_sources": normalized["field_sources"],
                }
                return self._build_result(
                    symbol=symbol,
                    fundamental_data=fundamental_data,
                    metadata=metadata,
                    status="success",
                    rows=len(akshare_result.data) if isinstance(akshare_result.data, list) else 0,
                    error=None,
                )

        error = qmt_result.metadata.error or "QMT and AKShare fundamental data unavailable."
        return self._placeholder_result(symbol, error, provider_run_log)

    def _placeholder_result(
        self,
        symbol: str,
        error: str | None,
        provider_run_log: list[dict],
    ) -> dict:
        supplemental = get_placeholder_supplemental_data(symbol)
        fundamental_data = dict(supplemental["fundamental_data"])
        metadata = dict(supplemental["source_metadata"]["fundamental_data"])
        result = self._build_result(
            symbol=symbol,
            fundamental_data=fundamental_data,
            metadata=metadata,
            status="fallback_placeholder",
            rows=0,
            error=error,
        )
        result["provider_run_log"] = provider_run_log + result["provider_run_log"]
        return result

    def _build_result(
        self,
        symbol: str,
        fundamental_data: dict,
        metadata: dict,
        status: str,
        rows: int,
        error: str | None,
    ) -> dict:
        analysis = self._analyze(fundamental_data, metadata)
        return {
            "data": {
                "fundamental_data": fundamental_data,
                "fundamental_analysis": analysis,
            },
            "source_metadata": {"fundamental_data": metadata},
            "provider_run_log": [
                {
                    "provider": metadata.get("source", "unknown"),
                    "dataset": "fundamental_data",
                    "symbol": symbol,
                    "status": status,
                    "rows": rows,
                    "error": error,
                    "error_type": ProviderDataQualityError.error_type if error else None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _has_core_fields(self, data: dict) -> bool:
        return any(data.get(field) is not None for field in ("roe", "net_profit_ttm", "revenue_ttm"))

    def _analyze(self, data: dict, metadata: dict) -> dict:
        roe = data.get("roe")
        net_margin = data.get("net_margin")
        gross_margin = data.get("gross_margin")
        net_profit_growth = data.get("net_profit_growth")
        revenue_growth = data.get("revenue_growth")
        cashflow_quality = data.get("operating_cashflow_quality")
        debt_ratio = data.get("debt_ratio")
        warnings = []
        key_points = []

        if metadata.get("source") == "mock_placeholder":
            warnings.append("基本面数据仍为 placeholder，需要接入真实财务数据验证。")

        quality_label = "low"
        if roe is not None and roe >= 0.15 and (net_margin is None or net_margin > 0.10):
            quality_label = "high"
            key_points.append("ROE 高于 15%，盈利能力较强。")
        elif roe is not None and roe >= 0.08:
            quality_label = "medium"

        if gross_margin is not None and gross_margin > 0.4:
            key_points.append("毛利率处于较高水平。")

        growth_label = "stable"
        if (revenue_growth is not None and revenue_growth < 0) or (
            net_profit_growth is not None and net_profit_growth < 0
        ):
            growth_label = "negative"
            warnings.append("收入或净利润增速为负。")
        elif (revenue_growth or 0) > 0 and (net_profit_growth or 0) > 0:
            growth_label = "moderate_growth"
            key_points.append("收入和净利润保持正增长。")

        cashflow_label = "unknown"
        if isinstance(cashflow_quality, (int, float)):
            cashflow_label = "good" if cashflow_quality >= 1.0 else "weak"
        elif cashflow_quality == "good":
            cashflow_label = "good"

        leverage_label = "normal"
        if debt_ratio is not None and debt_ratio > 0.70:
            leverage_label = "high"
            warnings.append("非金融企业资产负债率偏高。")

        return {
            "quality_label": quality_label,
            "growth_label": growth_label,
            "cashflow_label": cashflow_label,
            "leverage_label": leverage_label,
            "key_points": key_points,
            "warnings": warnings,
        }
