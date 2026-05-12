from datetime import date

from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.provider_contracts import ProviderDataQualityError
from services.data.providers.akshare_event_provider import AKShareEventProvider
from services.data.providers.cninfo_event_provider import CninfoEventProvider
from services.data.providers.web_news_provider import WebNewsProvider
from services.data.supplemental_provider import get_placeholder_supplemental_data


class EventService:
    def __init__(self):
        self.cninfo_provider = CninfoEventProvider()
        self.akshare_provider = AKShareEventProvider()
        self.web_news_provider = WebNewsProvider()
        self.normalizer = EventNormalizer()

    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]

        if asset_data.get("data_source") == "mock":
            return self._placeholder_result(symbol, "mock data source selected", [])

        symbol_info = asset_data.get("symbol_info", {})
        symbol_info_for_news = {
            **symbol_info,
            "name": asset_data.get("name") or symbol_info.get("name"),
        }
        provider_run_log = []
        events = []
        source_parts = []
        confidence = 0.0
        primary_error = None

        # 1. Primary: 巨潮资讯 Cninfo (via AKShare)
        cninfo_result = self.cninfo_provider.fetch_events(symbol_info, lookback_days=90)
        provider_run_log.append(self._provider_log(cninfo_result, symbol))

        if cninfo_result.metadata.success and cninfo_result.data:
            events.extend(
                self.normalizer.normalize_cninfo(
                    cninfo_result.to_dict(),
                    symbol=symbol,
                    lookback_days=90,
                )
            )
            source_parts.append("cninfo")
            confidence = max(confidence, 0.92)
        else:
            primary_error = cninfo_result.metadata.error

            # 2. Fallback: AKShare 东方财富公告
            akshare_result = self.akshare_provider.fetch_events(symbol_info, lookback_days=90)
            provider_run_log.append(self._provider_log(akshare_result, symbol))

            if akshare_result.metadata.success and akshare_result.data:
                events.extend(
                    self.normalizer.normalize_akshare(
                        akshare_result.to_dict(),
                        symbol=symbol,
                        lookback_days=90,
                    )
                )
                source_parts.append("akshare")
                confidence = max(confidence, 0.72)
            else:
                primary_error = primary_error or akshare_result.metadata.error

        # 3. Optional enhancement: domestic web news RSS. This is intentionally
        # separate from official announcements and never blocks the main flow.
        if getattr(self.web_news_provider, "enabled", False):
            web_news_result = self.web_news_provider.fetch_events(
                symbol_info_for_news,
                lookback_days=14,
            )
            provider_run_log.append(self._provider_log(web_news_result, symbol))
            if web_news_result.metadata.success and web_news_result.data:
                events = self._merge_events(
                    events,
                    self.normalizer.normalize_web_news(
                        web_news_result.to_dict(),
                        symbol=symbol,
                        lookback_days=14,
                    ),
                )
                source_parts.append("web_news")
                confidence = max(confidence, 0.55)

        if events:
            source = "+".join(dict.fromkeys(source_parts)) or "event_data"
            event_data = self._build_event_data(events)
            metadata = {
                "source": source,
                "confidence": confidence,
                "as_of": str(date.today()),
                "provider": source,
                "dataset": "event_data",
            }
            return self._build_result(symbol, event_data, metadata, provider_run_log)

        # 4. Placeholder
        error = primary_error or "Cninfo, AKShare and optional web news event data unavailable."
        return self._placeholder_result(symbol, error, provider_run_log)

    def _provider_log(self, result, symbol: str) -> dict:
        return {
            "provider": result.provider,
            "dataset": result.dataset,
            "symbol": symbol,
            "status": "success" if result.metadata.success else "failed",
            "rows": len(result.data) if isinstance(result.data, list) else 0,
            "error": result.metadata.error,
            "error_type": result.metadata.error_type,
            "as_of": str(date.today()),
        }

    def _merge_events(self, primary: list[dict], secondary: list[dict]) -> list[dict]:
        seen = {item.get("dedupe_key") for item in primary if item.get("dedupe_key")}
        merged = list(primary)
        for item in secondary:
            dedupe_key = item.get("dedupe_key")
            if dedupe_key and dedupe_key in seen:
                continue
            if dedupe_key:
                seen.add(dedupe_key)
            merged.append(item)
        return merged

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
                "error_type": ProviderDataQualityError.error_type if error else None,
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
                    "error_type": None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _summarize(self, events: list[dict]) -> dict:
        return {
            "positive_count": sum(1 for item in events if item.get("sentiment") in {"positive", "neutral_positive"}),
            "negative_count": sum(1 for item in events if item.get("sentiment") in {"negative", "neutral_negative"}),
            "neutral_count": sum(1 for item in events if item.get("sentiment") in {"neutral", "unknown"}),
            "high_severity_count": sum(1 for item in events if item.get("severity") in {"high", "critical"}),
            "critical_count": sum(1 for item in events if item.get("severity") == "critical"),
            "risk_flags": [],
        }

    def _build_event_data(self, events: list[dict]) -> dict:
        return {
            "lookback_days": 90,
            "recent_news_sentiment": self._overall_sentiment(events),
            "policy_risk": "low"
            if not any(item["severity"] in {"high", "critical"} for item in events)
            else "medium",
            "major_event": self._major_event_text(events),
            "events": events,
            "event_summary": self._summarize(events),
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
