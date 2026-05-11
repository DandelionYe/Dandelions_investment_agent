from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo


class ProviderError(Exception):
    """Base class for provider-layer failures."""

    error_type = "provider_error"


class ProviderUnavailableError(ProviderError):
    """Provider is unavailable, so a configured fallback may be used."""

    error_type = "provider_unavailable"


class ProviderSchemaError(ProviderError):
    """Provider response shape is incompatible with the expected schema."""

    error_type = "provider_schema"


class ProviderDataQualityError(ProviderError):
    """Provider returned data, but it is not good enough for safe use."""

    error_type = "provider_data_quality"


def get_provider_error_type(error: BaseException | None) -> str | None:
    if error is None:
        return None
    return getattr(error, "error_type", error.__class__.__name__)


def now_beijing_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


@dataclass
class ProviderMetadata:
    source_url: str | None = None
    request_time: str = field(default_factory=now_beijing_iso)
    success: bool = True
    error: str | None = None
    error_type: str | None = None
    latency_ms: int | None = None


@dataclass
class ProviderResult:
    provider: str
    dataset: str
    symbol: str
    as_of: str
    data: dict[str, Any] | list[dict[str, Any]]
    raw: Any
    metadata: ProviderMetadata = field(default_factory=ProviderMetadata)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["metadata"] = asdict(self.metadata)
        return payload


class FundamentalProvider(Protocol):
    def fetch_fundamental(self, symbol_info: dict) -> ProviderResult:
        ...


class ValuationProvider(Protocol):
    def fetch_valuation(self, symbol_info: dict) -> ProviderResult:
        ...


class EventProvider(Protocol):
    def fetch_events(self, symbol_info: dict, lookback_days: int = 90) -> ProviderResult:
        ...


class ETFProvider(Protocol):
    def fetch_etf_data(self, symbol_info: dict) -> ProviderResult:
        ...
