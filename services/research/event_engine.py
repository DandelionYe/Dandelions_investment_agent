from datetime import date

from services.data.supplemental_provider import get_placeholder_supplemental_data


class EventService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        supplemental = get_placeholder_supplemental_data(symbol)
        event_data = dict(asset_data.get("event_data") or supplemental["event_data"])
        metadata = dict(
            asset_data.get("source_metadata", {}).get("event_data")
            or supplemental["source_metadata"]["event_data"]
        )

        events = event_data.setdefault("events", [])
        event_data.setdefault("lookback_days", 90)
        event_data.setdefault("event_summary", self._summarize(events))

        return {
            "data": {"event_data": event_data},
            "source_metadata": {"event_data": metadata},
            "provider_run_log": [
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
