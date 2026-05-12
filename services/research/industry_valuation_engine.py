import os
from dataclasses import asdict, dataclass
from typing import Sequence

from services.data.provider_contracts import ProviderDataQualityError
from services.data.providers.qmt_industry_provider import QMTIndustryProvider
from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader


@dataclass(frozen=True)
class PeerValuationInput:
    symbol: str
    name: str | None
    asset_type: str
    close: float | None
    total_volume: float | None
    float_volume: float | None
    net_profit_ttm: float | None
    revenue_ttm: float | None
    bps: float | None
    is_st: bool = False
    is_suspended: bool = False


@dataclass(frozen=True)
class IndustryValuationResult:
    industry_level: str
    industry_name: str
    industry_peer_count: int
    industry_valid_peer_count: int
    industry_valid_peer_count_pe: int
    industry_valid_peer_count_pb: int
    industry_valid_peer_count_ps: int
    industry_pe_percentile: float | None
    industry_pb_percentile: float | None
    industry_ps_percentile: float | None
    industry_valuation_label: str
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class IndustryValuationService:
    def __init__(
        self,
        industry_provider: QMTIndustryProvider | None = None,
        peer_valuation_loader: QMTPeerValuationLoader | None = None,
        peer_loader=None,
    ) -> None:
        self.industry_provider = industry_provider or QMTIndustryProvider()
        self.peer_valuation_loader = peer_valuation_loader or QMTPeerValuationLoader()
        self.peer_loader = peer_loader

    def build(self, asset_data: dict, valuation_data: dict) -> dict:
        if asset_data.get("asset_type") != "stock":
            return {"fields": {}, "provider_run_log": []}

        symbol = asset_data["symbol"]
        level = os.getenv("QMT_INDUSTRY_LEVEL", "SW1")
        min_valid_peers = int(os.getenv("QMT_INDUSTRY_MIN_VALID_PEERS", "20"))
        max_pe = float(os.getenv("QMT_INDUSTRY_MAX_PE", "300"))
        max_pb = float(os.getenv("QMT_INDUSTRY_MAX_PB", "50"))
        max_ps = float(os.getenv("QMT_INDUSTRY_MAX_PS", "100"))

        industry_result = self.industry_provider.resolve_industry(
            symbol=symbol,
            level=level,
            as_of=asset_data.get("as_of"),
        )
        if not industry_result.metadata.success:
            raise ProviderDataQualityError(
                industry_result.metadata.error
                or f"QMT industry could not resolve sector for {symbol}"
            )

        industry_payload = industry_result.data
        if not isinstance(industry_payload, dict):
            raise ProviderDataQualityError(
                f"QMT industry payload must be dict, got {type(industry_payload).__name__}"
            )

        members = industry_payload.get("industry_members") or []
        if not members:
            raise ProviderDataQualityError(
                f"QMT industry sector has no members for {symbol}"
            )

        peers = self._load_peer_inputs(asset_data, valuation_data, industry_payload)
        result = calculate_industry_valuation_percentiles(
            target_symbol=symbol,
            industry_level=industry_payload.get("industry_level", level),
            industry_name=industry_payload.get("industry_name", ""),
            industry_members=members,
            peers=peers,
            min_valid_peers=min_valid_peers,
            max_pe=max_pe,
            max_pb=max_pb,
            max_ps=max_ps,
        )

        fields = result.to_dict()
        warnings = fields.pop("warnings")
        fields["industry_valuation_warnings"] = warnings
        fields["industry_valuation_source"] = "qmt_sector+qmt_financial+qmt_price"

        status = "success" if not warnings else "partial_success"
        return {
            "fields": fields,
            "provider_run_log": [
                {
                    "provider": "qmt",
                    "dataset": "industry_valuation",
                    "symbol": symbol,
                    "status": status,
                    "rows": result.industry_peer_count,
                    "error": "; ".join(warnings) if warnings else None,
                    "error_type": ProviderDataQualityError.error_type if warnings else None,
                    "as_of": asset_data.get("as_of"),
                }
            ],
        }

    def _load_peer_inputs(
        self,
        asset_data: dict,
        valuation_data: dict,
        industry_payload: dict,
    ) -> list[PeerValuationInput]:
        if self.peer_loader is not None:
            return list(self.peer_loader(asset_data, valuation_data, industry_payload))

        raw_peers = asset_data.get("industry_peer_inputs")
        if raw_peers:
            return [self._coerce_peer_input(item) for item in raw_peers]

        members = industry_payload.get("industry_members") or []
        if members:
            loaded = self.peer_valuation_loader.load_peer_inputs(
                members,
                as_of=asset_data.get("as_of"),
            )
            return [self._coerce_peer_input(item) for item in loaded]

        return [self._target_peer_from_current_data(asset_data, valuation_data)]

    def _coerce_peer_input(self, item: PeerValuationInput | dict) -> PeerValuationInput:
        if isinstance(item, PeerValuationInput):
            return item
        return PeerValuationInput(
            symbol=item["symbol"],
            name=item.get("name"),
            asset_type=item.get("asset_type", "stock"),
            close=item.get("close"),
            total_volume=item.get("total_volume"),
            float_volume=item.get("float_volume"),
            net_profit_ttm=item.get("net_profit_ttm"),
            revenue_ttm=item.get("revenue_ttm"),
            bps=item.get("bps"),
            is_st=bool(item.get("is_st", False)),
            is_suspended=bool(item.get("is_suspended", False)),
        )

    def _target_peer_from_current_data(
        self,
        asset_data: dict,
        valuation_data: dict,
    ) -> PeerValuationInput:
        price_data = asset_data.get("price_data", {})
        fundamental = asset_data.get("fundamental_data", {})
        basic_info = asset_data.get("basic_info", {})
        close = price_data.get("close")
        market_cap = valuation_data.get("market_cap")
        pe_ttm = valuation_data.get("pe_ttm")
        pb_mrq = valuation_data.get("pb_mrq")
        ps_ttm = valuation_data.get("ps_ttm")

        total_volume = basic_info.get("total_volume")
        if total_volume is None and close and market_cap:
            total_volume = market_cap / close

        net_profit_ttm = fundamental.get("net_profit_ttm")
        if net_profit_ttm is None and market_cap and pe_ttm and pe_ttm > 0:
            net_profit_ttm = market_cap / pe_ttm

        revenue_ttm = fundamental.get("revenue_ttm")
        if revenue_ttm is None and market_cap and ps_ttm and ps_ttm > 0:
            revenue_ttm = market_cap / ps_ttm

        bps = fundamental.get("bps")
        if bps is None and close and pb_mrq and pb_mrq > 0:
            bps = close / pb_mrq

        return PeerValuationInput(
            symbol=asset_data["symbol"],
            name=asset_data.get("name"),
            asset_type=asset_data.get("asset_type", "stock"),
            close=close,
            total_volume=total_volume,
            float_volume=basic_info.get("float_volume"),
            net_profit_ttm=net_profit_ttm,
            revenue_ttm=revenue_ttm,
            bps=bps,
        )


def _positive_float(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def calculate_peer_multiples(peer: PeerValuationInput) -> dict:
    close = _positive_float(peer.close)
    total_volume = _positive_float(peer.total_volume)
    net_profit_ttm = _positive_float(peer.net_profit_ttm)
    revenue_ttm = _positive_float(peer.revenue_ttm)
    bps = _positive_float(peer.bps)

    market_cap = close * total_volume if close is not None and total_volume is not None else None
    return {
        "symbol": peer.symbol,
        "asset_type": peer.asset_type,
        "pe_ttm": market_cap / net_profit_ttm if market_cap is not None and net_profit_ttm else None,
        "pb_mrq": close / bps if close is not None and bps else None,
        "ps_ttm": market_cap / revenue_ttm if market_cap is not None and revenue_ttm else None,
    }


def percentile_midrank(current: float | None, values: Sequence[float]) -> float | None:
    if current is None:
        return None
    valid_values = [float(value) for value in values if value is not None]
    if not valid_values:
        return None
    current_value = float(current)
    count_less = sum(1 for value in valid_values if value < current_value)
    count_equal = sum(1 for value in valid_values if value == current_value)
    return (count_less + 0.5 * count_equal) / len(valid_values)


def filter_peer_multiples(
    peers: Sequence[PeerValuationInput],
    *,
    max_pe: float = 300,
    max_pb: float = 50,
    max_ps: float = 100,
) -> tuple[list[dict], list[str]]:
    multiples: list[dict] = []
    warnings: list[str] = []

    for peer in peers:
        if peer.asset_type != "stock":
            continue
        if peer.is_st:
            continue
        if peer.is_suspended:
            continue

        item = calculate_peer_multiples(peer)
        if item["pe_ttm"] is not None and item["pe_ttm"] > max_pe:
            item["pe_ttm"] = None
            warnings.append(f"{peer.symbol} PE exceeds max_pe and was excluded.")
        if item["pb_mrq"] is not None and item["pb_mrq"] > max_pb:
            item["pb_mrq"] = None
            warnings.append(f"{peer.symbol} PB exceeds max_pb and was excluded.")
        if item["ps_ttm"] is not None and item["ps_ttm"] > max_ps:
            item["ps_ttm"] = None
            warnings.append(f"{peer.symbol} PS exceeds max_ps and was excluded.")

        multiples.append(item)

    return multiples, warnings


def calculate_industry_valuation_percentiles(
    target_symbol: str,
    industry_level: str,
    industry_name: str,
    industry_members: Sequence[str],
    peers: Sequence[PeerValuationInput],
    *,
    min_valid_peers: int = 20,
    max_pe: float = 300,
    max_pb: float = 50,
    max_ps: float = 100,
) -> IndustryValuationResult:
    multiples, warnings = filter_peer_multiples(
        peers,
        max_pe=max_pe,
        max_pb=max_pb,
        max_ps=max_ps,
    )
    by_symbol = {item["symbol"]: item for item in multiples}
    target = by_symbol.get(target_symbol)

    pe_values = [item["pe_ttm"] for item in multiples if item["pe_ttm"] is not None]
    pb_values = [item["pb_mrq"] for item in multiples if item["pb_mrq"] is not None]
    ps_values = [item["ps_ttm"] for item in multiples if item["ps_ttm"] is not None]

    valid_pe_count = len(pe_values)
    valid_pb_count = len(pb_values)
    valid_ps_count = len(ps_values)
    target_pe = target.get("pe_ttm") if target else None
    target_pb = target.get("pb_mrq") if target else None
    target_ps = target.get("ps_ttm") if target else None

    if target is None:
        warnings.append(f"Target symbol {target_symbol} is not in valid peer inputs.")
    if valid_pe_count < min_valid_peers:
        warnings.append(
            f"Industry PE valid peer count {valid_pe_count} is below {min_valid_peers}."
        )

    pe_percentile = (
        percentile_midrank(target_pe, pe_values)
        if valid_pe_count >= min_valid_peers
        else None
    )
    pb_percentile = (
        percentile_midrank(target_pb, pb_values)
        if valid_pb_count >= min_valid_peers
        else None
    )
    ps_percentile = (
        percentile_midrank(target_ps, ps_values)
        if valid_ps_count >= min_valid_peers
        else None
    )

    label = _industry_label(
        target_pe=target_pe,
        pe_percentile=pe_percentile,
        pb_percentile=pb_percentile,
        valid_pe_count=valid_pe_count,
        min_valid_peers=min_valid_peers,
    )

    return IndustryValuationResult(
        industry_level=industry_level,
        industry_name=industry_name,
        industry_peer_count=len(industry_members),
        industry_valid_peer_count=valid_pe_count,
        industry_valid_peer_count_pe=valid_pe_count,
        industry_valid_peer_count_pb=valid_pb_count,
        industry_valid_peer_count_ps=valid_ps_count,
        industry_pe_percentile=pe_percentile,
        industry_pb_percentile=pb_percentile,
        industry_ps_percentile=ps_percentile,
        industry_valuation_label=label,
        warnings=warnings,
    )


def _industry_label(
    *,
    target_pe: float | None,
    pe_percentile: float | None,
    pb_percentile: float | None,
    valid_pe_count: int,
    min_valid_peers: int,
) -> str:
    if target_pe is None:
        return "industry_loss_making_or_invalid_pe"
    if valid_pe_count < min_valid_peers:
        return "industry_insufficient_peers"
    if pe_percentile is None:
        return "industry_unavailable"
    if pe_percentile <= 0.35 and (pb_percentile is None or pb_percentile <= 0.35):
        return "industry_cheap"
    if pe_percentile > 0.80 and (pb_percentile is None or pb_percentile > 0.80):
        return "industry_expensive"
    if (pe_percentile <= 0.35 and pb_percentile is not None and pb_percentile > 0.80) or (
        pe_percentile > 0.80 and pb_percentile is not None and pb_percentile <= 0.35
    ):
        return "industry_mixed"
    return "industry_reasonable"
