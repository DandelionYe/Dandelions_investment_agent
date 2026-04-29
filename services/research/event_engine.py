from datetime import date

from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.providers.akshare_event_provider import AKShareEventProvider
from services.data.supplemental_provider import get_placeholder_supplemental_data


class EventService:
    def __init__(self):
        self.provider = AKShareEventProvider()
        self.normalizer = EventNormalizer()

    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]

        if asset_data.get("data_source") == "mock":
            return self._placeholder_result(symbol, "mock data source selected", [])

        symbol_info = asset_data.get("symbol_info", {})
        provider_result = self.provider.fetch_events(symbol_info, lookback_days=90)
        provider_run_log = [
            {
                "provider": provider_result.provider,
                "dataset": provider_result.dataset,
                "symbol": symbol,
                "status": "success" if provider_result.metadata.success else "failed",
                "rows": len(provider_result.data) if isinstance(provider_result.data, list) else 0,
                "error": provider_result.metadata.error,
                "as_of": str(date.today()),
            }
        ]

        if not provider_result.metadata.success:
            return self._placeholder_result(symbol, provider_result.metadata.error, provider_run_log)

        events = self.normalizer.normalize_akshare(
            provider_result.to_dict(),
            symbol=symbol,
            lookback_days=90,
        )
        event_data = {
            "lookback_days": 90,
            "recent_news_sentiment": self._overall_sentiment(events),
            "policy_risk": "low"
            if not any(item["severity"] in {"high", "critical"} for item in events)
            else "medium",
            "major_event": self._major_event_text(events),
            "events": events,
            "event_summary": self._summarize(events),
        }
        metadata = {
            "source": "akshare",
            "confidence": 0.72,
            "as_of": str(date.today()),
            "provider": provider_result.provider,
            "dataset": provider_result.dataset,
        }
        return self._build_result(symbol, event_data, metadata, provider_run_log)

    def _placeholder_result(self, symbol: str, error: str | None, provider_run_log: list[dict]) -> dict:
        supplemental = get_placeholder_supplemental_data(symbol)
        event_data = dict(supplemental["event_data"])
        metadata = dict(supplemental["source_metadata"]["event_data"])
        provider_run_log = provider_run_log + [
            {
                "provider": "mock_placeholder",
                "dataset": "event_data",
                "symbol": symbol,
                "status": "fallback_placeholder",
                "rows": 0,
                "error": error,
                "as_of": str(date.today()),
            }
        ]
        return self._build_result(symbol, event_data, metadata, provider_run_log)

    def _build_result(
        self,
        symbol: str,
        event_data: dict,
        metadata: dict,
        provider_run_log: list[dict],
    ) -> dict:
        events = event_data.setdefault("events", [])
        event_data.setdefault("lookback_days", 90)
        event_data.setdefault("event_summary", self._summarize(events))
        return {
            "data": {"event_data": event_data},
            "source_metadata": {"event_data": metadata},
            "provider_run_log": provider_run_log
            + [
                {
                    "provider": metadata.get("source", "unknown"),
                    "dataset": "event_data",
                    "symbol": symbol,
                    "status": "placeholder" if metadata.get("source") == "mock_placeholder" else "success",
                    "rows": len(events),
                    "error": None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _summarize(self, events: list[dict]) -> dict:
        return {
            "positive_count": sum(1 for item in events if item.get("sentiment") == "positive"),
            "negative_count": sum(1 for item in events if item.get("sentiment") == "negative"),
            "neutral_count": sum(1 for item in events if item.get("sentiment") == "neutral"),
            "high_severity_count": sum(1 for item in events if item.get("severity") == "high"),
            "critical_count": sum(1 for item in events if item.get("severity") == "critical"),
            "risk_flags": [],
        }

    def _overall_sentiment(self, events: list[dict]) -> str:
        if any(item.get("sentiment") == "negative" for item in events):
            return "neutral_negative"
        if any(item.get("sentiment") == "neutral_positive" for item in events):
            return "neutral_positive"
        return "neutral"

    def _major_event_text(self, events: list[dict]) -> str:
        high_events = [item for item in events if item.get("severity") in {"high", "critical"}]
        if high_events:
            return high_events[0].get("title", "近90日存在高风险公告")
        if events:
            return f"近90日共发现 {len(events)} 条公告，未发现 critical 事件"
        return "近90日未发现重大负面公告"
