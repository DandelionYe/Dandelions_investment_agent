from datetime import date

from services.data.normalizers.common import _to_float
from services.data.normalizers.valuation_normalizer import ValuationNormalizer
from services.research.industry_valuation_engine import (
    WARN_INSUFFICIENT_SAMPLES,
    WARN_TARGET_NOT_IN_PEERS,
)
from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderError,
    get_provider_error_type,
)
from services.data.providers.akshare_share_capital_provider import (
    AKShareShareCapitalProvider,
    is_share_capital_fallback_enabled,
)
from services.data.providers.akshare_valuation_provider import AKShareValuationProvider
from services.data.providers.local_csmar_daily_derived_provider import (
    LocalCSMARDailyDerivedProvider,
    is_csmar_daily_derived_enabled,
)
from services.data.providers.local_csmar_eva_structure_provider import (
    LocalCSMAREVAStructureProvider,
    is_eva_structure_enabled,
)
from services.data.supplemental_provider import get_placeholder_supplemental_data
from services.research.industry_valuation_engine import IndustryValuationService


class ValuationService:
    def __init__(
        self,
        normalizer: ValuationNormalizer | None = None,
        akshare_provider: AKShareValuationProvider | None = None,
        industry_service: IndustryValuationService | None = None,
        share_capital_provider: AKShareShareCapitalProvider | None = None,
        csmar_provider: LocalCSMARDailyDerivedProvider | None = None,
        eva_provider: LocalCSMAREVAStructureProvider | None = None,
    ):
        self.normalizer = normalizer or ValuationNormalizer()
        self.akshare_provider = akshare_provider or AKShareValuationProvider()
        self.industry_service = industry_service or IndustryValuationService()
        self.share_capital_provider = share_capital_provider or AKShareShareCapitalProvider()
        self.csmar_provider = csmar_provider or LocalCSMARDailyDerivedProvider()
        self.eva_provider = eva_provider or LocalCSMAREVAStructureProvider()

    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]

        if asset_data.get("data_source") == "mock":
            return self._placeholder_result(symbol, "mock data source selected", [])

        symbol_info = asset_data.get("symbol_info", {})
        provider_run_log = []

        valuation_data = self.normalizer.derive_from_qmt(asset_data)

        # Store QMT input references for missing_reason computation later.
        price_data = asset_data.get("price_data", {})
        basic_info = asset_data.get("basic_info", {})
        fundamental = asset_data.get("fundamental_data", {})
        valuation_data["_close_ref"] = _to_float(price_data.get("close"))
        valuation_data["_total_volume_ref"] = _to_float(
            basic_info.get("total_volume") or basic_info.get("TotalVolume")
        )
        valuation_data["_net_profit_ttm_ref"] = _to_float(
            fundamental.get("net_profit_ttm")
        )
        valuation_data["_revenue_ttm_ref"] = _to_float(
            fundamental.get("revenue_ttm")
        )
        valuation_data["_bps_ref"] = _to_float(fundamental.get("bps"))

        metadata = {
            "source": "qmt_derived",
            "confidence": 0.72 if valuation_data.get("market_cap") else 0.45,
            "as_of": str(date.today()),
            "calculation_method": valuation_data.get("calculation_method"),
        }
        self._append_csmar_percentile_run_log(
            symbol=symbol,
            valuation_data=valuation_data,
            provider_run_log=provider_run_log,
        )

        # Share capital fallback: if QMT total_volume is missing/zero,
        # try AKShare to get total_volume or market_cap.
        if not valuation_data.get("market_cap"):
            self._try_share_capital_fallback(
                asset_data=asset_data,
                valuation_data=valuation_data,
                metadata=metadata,
                provider_run_log=provider_run_log,
                symbol=symbol,
            )

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

        # CSMAR daily-derived fallback: fill remaining missing fields
        # (dividend_yield, pe, pb, ps, pcf) from local SQLite snapshot.
        # Uses setdefault — never overwrites fields already populated by QMT/AKShare.
        self._try_csmar_daily_derived_fallback(
            symbol=symbol,
            valuation_data=valuation_data,
            metadata=metadata,
            provider_run_log=provider_run_log,
        )

        if not self._has_core_fields(valuation_data):
            return self._placeholder_result(
                symbol,
                (akshare_result.metadata.error if akshare_result else None)
                or "QMT-derived valuation core fields are missing.",
                provider_run_log,
                missing_reason_source=valuation_data,
            )

        valuation_data.setdefault("valuation_label", self._label(valuation_data))
        self._attach_industry_valuation(
            asset_data=asset_data,
            valuation_data=valuation_data,
            provider_run_log=provider_run_log,
        )

        _compute_missing_reasons(valuation_data)

        # Remove internal reference fields before returning.
        for key in list(valuation_data):
            if key.startswith("_"):
                valuation_data.pop(key, None)

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

    def _try_share_capital_fallback(
        self,
        *,
        asset_data: dict,
        valuation_data: dict,
        metadata: dict,
        provider_run_log: list[dict],
        symbol: str,
    ) -> None:
        price_data = asset_data.get("price_data", {})
        close = _to_float(price_data.get("close"))
        if not close or close <= 0:
            return

        basic_info = asset_data.get("basic_info", {})
        existing_total_volume = _to_float(
            basic_info.get("total_volume") or basic_info.get("TotalVolume")
        )
        if existing_total_volume and existing_total_volume > 0:
            return

        # Priority: EVA local fallback -> AKShare fallback
        eva_applied = self._try_eva_share_capital_fallback(
            symbol=symbol,
            asset_data=asset_data,
            valuation_data=valuation_data,
            metadata=metadata,
            provider_run_log=provider_run_log,
            close=close,
            basic_info=basic_info,
        )
        if eva_applied:
            return

        if not is_share_capital_fallback_enabled():
            return

        result = self.share_capital_provider.fetch_share_capital(symbol)
        provider_run_log.append({
            "provider": result.provider,
            "dataset": result.dataset,
            "symbol": symbol,
            "status": "success" if result.metadata.success else "failed",
            "rows": 1 if result.metadata.success else 0,
            "error": result.metadata.error,
            "error_type": result.metadata.error_type,
            "as_of": str(date.today()),
        })

        if not result.metadata.success:
            return

        data = result.data
        sc_total_volume = _to_float(data.get("total_volume"))
        sc_market_cap = _to_float(data.get("market_cap"))
        sc_float_volume = _to_float(data.get("float_volume"))

        derived = False
        if sc_total_volume and sc_total_volume > 0:
            basic_info["total_volume"] = sc_total_volume
            if sc_float_volume and sc_float_volume > 0:
                existing_float_volume = _to_float(
                    basic_info.get("float_volume") or basic_info.get("FloatVolume")
                )
                if not existing_float_volume or existing_float_volume <= 0:
                    basic_info["float_volume"] = sc_float_volume
            derived = True
        elif sc_market_cap and sc_market_cap > 0:
            inferred_tv = sc_market_cap / close
            if inferred_tv > 0:
                basic_info["total_volume"] = inferred_tv
                derived = True

        if derived:
            valuation_data.update(self.normalizer.derive_from_qmt(asset_data))
            metadata["source"] = "qmt_derived+share_capital_fallback"
            metadata["confidence"] = 0.70
            calc = valuation_data.get("calculation_method", "")
            if "share_capital_from_akshare" not in str(calc):
                calculation_method = (
                    str(calc) + " + share_capital_from_akshare"
                ).strip()
                valuation_data["calculation_method"] = calculation_method
                metadata["calculation_method"] = calculation_method

    def _try_eva_share_capital_fallback(
        self,
        *,
        symbol: str,
        asset_data: dict,
        valuation_data: dict,
        metadata: dict,
        provider_run_log: list[dict],
        close: float,
        basic_info: dict,
    ) -> bool:
        """Try EVA_Structure as local share capital fallback.

        Returns True if EVA successfully provided data (so AKShare is skipped).
        """
        if not is_eva_structure_enabled():
            return False

        result = self.eva_provider.get_latest_share_capital(symbol)
        data = result.data
        eva_total_volume = _to_float(data.get("total_volume"))
        eva_market_cap = _to_float(data.get("market_cap"))
        eva_float_volume = _to_float(data.get("float_volume"))
        available_fields = [
            field
            for field in ("total_volume", "market_cap", "float_volume")
            if _to_float(data.get(field)) is not None
        ]
        applied_fields = []

        derived = False
        source_tag = "local_csmar_eva_structure"
        method_tag = "share_capital_from_local_csmar_eva_structure"

        if eva_total_volume and eva_total_volume > 0:
            basic_info["total_volume"] = eva_total_volume
            applied_fields.append("total_volume")
            if eva_float_volume and eva_float_volume > 0:
                existing_float_volume = _to_float(
                    basic_info.get("float_volume") or basic_info.get("FloatVolume")
                )
                if not existing_float_volume or existing_float_volume <= 0:
                    basic_info["float_volume"] = eva_float_volume
                    applied_fields.append("float_volume")
            derived = True
        elif eva_market_cap and eva_market_cap > 0 and close > 0:
            inferred_tv = eva_market_cap / close
            if inferred_tv > 0:
                basic_info["total_volume"] = inferred_tv
                applied_fields.extend(["market_cap", "total_volume_inferred"])
                derived = True
                source_tag = "local_csmar_eva_structure+inferred_from_market_value"
                method_tag = "share_capital_from_local_csmar_eva_structure_inferred"

        if not derived:
            provider_run_log.append(
                self._eva_run_log_entry(
                    result=result,
                    symbol=symbol,
                    status="available_not_applied" if available_fields else "no_usable_data",
                    available_fields=available_fields,
                    applied_fields=applied_fields,
                )
            )
            return False

        valuation_data.update(self.normalizer.derive_from_qmt(asset_data))
        metadata["source"] = f"qmt_derived+{source_tag}"
        metadata["confidence"] = 0.70
        calc = str(valuation_data.get("calculation_method", ""))
        if method_tag not in calc:
            calculation_method = (calc + " + " + method_tag).strip()
            valuation_data["calculation_method"] = calculation_method
            metadata["calculation_method"] = calculation_method
        provider_run_log.append(
            self._eva_run_log_entry(
                result=result,
                symbol=symbol,
                status="success",
                available_fields=available_fields,
                applied_fields=applied_fields,
            )
        )
        return True

    def _eva_run_log_entry(
        self,
        *,
        result,
        symbol: str,
        status: str,
        available_fields: list[str],
        applied_fields: list[str],
    ) -> dict:
        return {
            "provider": result.provider,
            "dataset": result.dataset,
            "symbol": symbol,
            "status": status,
            "rows": 1 if result.raw is not None else 0,
            "error": result.metadata.error,
            "error_type": result.metadata.error_type,
            "as_of": str(date.today()),
            "fields_available": available_fields,
            "fields_applied": applied_fields,
        }

    def _try_csmar_daily_derived_fallback(
        self,
        *,
        symbol: str,
        valuation_data: dict,
        metadata: dict,
        provider_run_log: list[dict],
    ) -> None:
        if not is_csmar_daily_derived_enabled():
            return

        valuation_data["_csmar_enabled"] = True
        result = self.csmar_provider.get_latest_metrics(symbol)
        data = result.data
        available_fields = [
            field
            for field in ("dividend_yield", "pe", "pb", "ps", "pcf")
            if isinstance(data, dict) and data.get(field) is not None
        ]
        csmar_warnings = list(data.get("warnings", [])) if isinstance(data, dict) else []
        if _has_warning(csmar_warnings, "dividend_yield is") or _has_warning(
            csmar_warnings, "dividend_yield has unparseable date"
        ):
            valuation_data["_csmar_stale_dividend_yield"] = True
        csmar_fields_applied = []

        if not result.metadata.success:
            valuation_data["_csmar_failed"] = True
            provider_run_log.append(
                self._csmar_run_log_entry(
                    result=result,
                    symbol=symbol,
                    status="failed",
                    available_fields=available_fields,
                    applied_fields=csmar_fields_applied,
                )
            )
            return

        # dividend_yield: CSMAR is the preferred fallback (often more reliable
        # than QMT which may not compute it daily).
        csmar_dy = _to_float(data.get("dividend_yield"))
        if csmar_dy is not None and valuation_data.get("dividend_yield") is None:
            valuation_data["dividend_yield"] = csmar_dy
            valuation_data["dividend_yield_source"] = self.csmar_provider.provider
            valuation_data["dividend_yield_date"] = data.get("dividend_yield_date")
            csmar_fields_applied.append("dividend_yield")

        # PE / PB / PS / PCF: fill if currently None.
        # pe_ttm: CSMAR 优先覆盖（QMT 跨表 report_period 错配可能导致计算值偏差）
        # 仅当 CSMAR pe > 0 时覆盖，避免 pe=0（数据缺失哨兵值）覆盖有效 QMT 值
        csmar_pe = _to_float(data.get("pe"))
        if csmar_pe is not None and csmar_pe > 0:
            had_qmt_pe = valuation_data.get("pe_ttm") is not None
            valuation_data["pe_ttm"] = csmar_pe
            valuation_data["pe_ttm_source"] = self.csmar_provider.provider
            valuation_data["pe_ttm_date"] = data.get("pe_date")
            if had_qmt_pe:
                valuation_data["pe_ttm_override_by_csmar"] = True
            csmar_fields_applied.append("pe")
        # pb / ps: 仅在缺失时填充（无跨表错配风险）
        for csmar_key, val_key in [("pb", "pb_mrq"), ("ps", "ps_ttm")]:
            csmar_val = _to_float(data.get(csmar_key))
            if csmar_val is not None and valuation_data.get(val_key) is None:
                valuation_data[val_key] = csmar_val
                valuation_data[f"{val_key}_source"] = self.csmar_provider.provider
                valuation_data[f"{val_key}_date"] = data.get(f"{csmar_key}_date")
                csmar_fields_applied.append(csmar_key)

        pcf_val = _to_float(data.get("pcf"))
        if pcf_val is not None and valuation_data.get("pcf") is None:
            valuation_data["pcf"] = pcf_val
            valuation_data["pcf_source"] = self.csmar_provider.provider
            valuation_data["pcf_date"] = data.get("pcf_date")
            csmar_fields_applied.append("pcf")

        if csmar_fields_applied:
            existing_method = str(metadata.get("calculation_method", ""))
            if "csmar_daily_derived" not in existing_method:
                metadata["calculation_method"] = (
                    existing_method + " + csmar_daily_derived_fallback"
                ).strip()
            if "csmar" not in str(metadata.get("source", "")):
                metadata["source"] = metadata["source"] + "+csmar_daily_derived"

        if csmar_fields_applied:
            status = "success"
        elif available_fields:
            status = "available_not_applied"
        else:
            status = "no_usable_data"
            valuation_data["_csmar_no_data"] = True

        provider_run_log.append(
            self._csmar_run_log_entry(
                result=result,
                symbol=symbol,
                status=status,
                available_fields=available_fields,
                applied_fields=csmar_fields_applied,
            )
        )

    def _csmar_run_log_entry(
        self,
        *,
        result,
        symbol: str,
        status: str,
        available_fields: list[str],
        applied_fields: list[str],
    ) -> dict:
        return {
            "provider": result.provider,
            "dataset": result.dataset,
            "symbol": symbol,
            "status": status,
            "rows": 1 if result.raw is not None else 0,
            "error": result.metadata.error,
            "error_type": result.metadata.error_type,
            "as_of": str(date.today()),
            "fields_available": available_fields,
            "fields_applied": applied_fields,
        }

    def _append_csmar_percentile_run_log(
        self,
        *,
        symbol: str,
        valuation_data: dict,
        provider_run_log: list[dict],
    ) -> None:
        applied_fields = list(valuation_data.get("percentile_fields_from_csmar", []))
        warnings = list(valuation_data.get("percentile_warnings", []))
        if not applied_fields and not warnings:
            return

        if applied_fields and warnings:
            status = "partial_success"
        elif applied_fields:
            status = "success"
        else:
            status = "no_usable_data"

        provider_run_log.append(
            {
                "provider": "local_csmar_daily_derived",
                "dataset": "monthly_snapshots",
                "symbol": symbol,
                "status": status,
                "rows": valuation_data.get("percentile_sample_count", 0),
                "error": "; ".join(warnings) if warnings else None,
                "error_type": ProviderDataQualityError.error_type if warnings else None,
                "as_of": str(date.today()),
                "fields_applied": applied_fields,
            }
        )

    def _placeholder_result(
        self,
        symbol: str,
        error: str | None,
        provider_run_log: list[dict],
        *,
        missing_reason_source: dict | None = None,
    ) -> dict:
        supplemental = get_placeholder_supplemental_data(symbol)
        valuation_data = dict(supplemental["valuation_data"])
        if missing_reason_source is not None:
            _copy_missing_reasons_to_placeholder(valuation_data, missing_reason_source)
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
                "provider": self.industry_service.industry_provider.provider
                if hasattr(self.industry_service, "industry_provider")
                else "unknown",
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


def _copy_missing_reasons_to_placeholder(target: dict, source: dict) -> None:
    reason_source = dict(source)
    _compute_missing_reasons(reason_source)
    for reason_field, reason in reason_source.items():
        if not reason_field.endswith("_missing_reason"):
            continue
        value_field = reason_field.removesuffix("_missing_reason")
        if target.get(value_field) is None:
            target.setdefault(reason_field, reason)


def _compute_missing_reasons(valuation_data: dict) -> None:
    """Attach machine-readable *_missing_reason to valuation fields that are None.

    Called once after all fallbacks have been tried.
    """
    _compute_market_cap_reason(valuation_data)
    _compute_pe_reason(valuation_data)
    _compute_pb_reason(valuation_data)
    _compute_ps_reason(valuation_data)
    _compute_percentile_missing_reasons(valuation_data)
    _compute_dividend_yield_reason(valuation_data)
    _compute_industry_missing_reasons(valuation_data)


def _compute_market_cap_reason(vd: dict) -> None:
    if vd.get("market_cap") is not None or "market_cap_missing_reason" in vd:
        return
    if not _to_float(vd.get("_close_ref")):
        vd["market_cap_missing_reason"] = "missing_close"
    elif not _to_float(vd.get("_total_volume_ref")):
        vd["market_cap_missing_reason"] = "missing_total_volume"
    else:
        vd["market_cap_missing_reason"] = "share_capital_fallback_unavailable"


def _compute_pe_reason(vd: dict) -> None:
    if vd.get("pe_ttm") is not None or "pe_ttm_missing_reason" in vd:
        return
    if vd.get("market_cap") is None:
        vd["pe_ttm_missing_reason"] = (
            vd.get("market_cap_missing_reason") or "missing_market_cap"
        )
    elif _to_float(vd.get("_net_profit_ttm_ref")) is None:
        vd["pe_ttm_missing_reason"] = "missing_net_profit_ttm"
    else:
        vd["pe_ttm_missing_reason"] = "loss_making_or_invalid_pe"


def _compute_pb_reason(vd: dict) -> None:
    if vd.get("pb_mrq") is not None or "pb_mrq_missing_reason" in vd:
        return
    if not _to_float(vd.get("_close_ref")):
        vd["pb_mrq_missing_reason"] = "missing_close"
    elif _to_float(vd.get("_bps_ref")) is None:
        vd["pb_mrq_missing_reason"] = "missing_bps"
    else:
        vd["pb_mrq_missing_reason"] = "invalid_bps"


def _compute_ps_reason(vd: dict) -> None:
    if vd.get("ps_ttm") is not None or "ps_ttm_missing_reason" in vd:
        return
    if vd.get("market_cap") is None:
        vd["ps_ttm_missing_reason"] = (
            vd.get("market_cap_missing_reason") or "missing_market_cap"
        )
    elif _to_float(vd.get("_revenue_ttm_ref")) is None:
        vd["ps_ttm_missing_reason"] = "missing_revenue_ttm"
    else:
        vd["ps_ttm_missing_reason"] = "invalid_revenue_ttm"


def _compute_dividend_yield_reason(vd: dict) -> None:
    if vd.get("dividend_yield") is not None or "dividend_yield_missing_reason" in vd:
        return
    if not vd.get("_csmar_enabled"):
        vd["dividend_yield_missing_reason"] = "provider_disabled"
    elif vd.get("_csmar_failed"):
        vd["dividend_yield_missing_reason"] = "missing_dividend_yield_source"
    elif vd.get("_csmar_stale_dividend_yield"):
        vd["dividend_yield_missing_reason"] = "stale_local_csmar_daily_derived"
    elif vd.get("_csmar_no_data"):
        vd["dividend_yield_missing_reason"] = "missing_dividend_yield_source"
    else:
        vd["dividend_yield_missing_reason"] = "stale_local_csmar_daily_derived"


def _compute_percentile_missing_reasons(vd: dict) -> None:
    warnings = list(vd.get("percentile_warnings", []))
    for metric, percentile_field, current_field, invalid_reason in [
        ("pe", "pe_percentile", "pe_ttm", "loss_making_or_invalid_pe"),
        ("pb", "pb_percentile", "pb_mrq", "invalid_bps"),
        ("ps", "ps_percentile", "ps_ttm", "invalid_revenue_ttm"),
    ]:
        reason_field = f"{percentile_field}_missing_reason"
        if vd.get(percentile_field) is not None or reason_field in vd:
            continue

        current_value = _to_float(vd.get(current_field))
        if current_value is None:
            vd[reason_field] = (
                vd.get(f"{current_field}_missing_reason") or "field_not_supported"
            )
        elif current_value <= 0:
            vd[reason_field] = invalid_reason
        elif _has_warning(warnings, f"insufficient_{metric}_samples"):
            vd[reason_field] = "insufficient_history_samples"
        elif _has_warning(warnings, "insufficient"):
            vd[reason_field] = "insufficient_history_samples"
        elif _has_warning(warnings, "unavailable") or _has_warning(warnings, "failed"):
            vd[reason_field] = "provider_unavailable"
        else:
            vd[reason_field] = "insufficient_history_samples"


def _compute_industry_missing_reasons(vd: dict) -> None:
    # Skip if no industry valuation was computed at all.
    if "industry_valuation_warnings" not in vd and "industry_pe_percentile" not in vd:
        return

    warnings = vd.get("industry_valuation_warnings", [])
    preflight = vd.get("industry_cache_preflight")
    is_preflight_fail = (
        preflight is not None and not preflight.get("ready", True)
    )

    for field, reason_field in [
        ("industry_pe_percentile", "industry_pe_percentile_missing_reason"),
        ("industry_pb_percentile", "industry_pb_percentile_missing_reason"),
        ("industry_ps_percentile", "industry_ps_percentile_missing_reason"),
    ]:
        if vd.get(field) is not None or reason_field in vd:
            continue
        if is_preflight_fail:
            vd[reason_field] = "peer_cache_preflight_failed"
        elif _has_warning(warnings, "qmt_peer_price_cache_insufficient"):
            vd[reason_field] = "missing_peer_close"
        elif _has_warning(warnings, "qmt_finance_cache_insufficient_for_peer_valuation"):
            vd[reason_field] = "missing_peer_finance"
        elif _has_warning(warnings, "qmt_peer_share_capital_insufficient"):
            vd[reason_field] = "missing_peer_share_capital"
        elif _has_warning(warnings, WARN_INSUFFICIENT_SAMPLES):
            vd[reason_field] = "insufficient_peer_samples"
        elif _has_warning(warnings, WARN_TARGET_NOT_IN_PEERS):
            vd[reason_field] = "target_not_in_peer_inputs"
        elif _has_warning(warnings, "insufficient"):
            vd[reason_field] = "insufficient_peer_samples"
        else:
            vd[reason_field] = "unknown"

    # Aggregate field
    if "industry_percentile_missing_reason" not in vd:
        any_reason = (
            vd.get("industry_pe_percentile_missing_reason")
            or vd.get("industry_pb_percentile_missing_reason")
            or vd.get("industry_ps_percentile_missing_reason")
        )
        if any_reason:
            vd["industry_percentile_missing_reason"] = any_reason


def _has_warning(warnings: list[str], keyword: str) -> bool:
    return any(keyword in w for w in warnings)
