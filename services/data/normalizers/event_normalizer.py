import hashlib
import re
from datetime import date

from services.data.normalizers.common import _first_present

# Order matters: first-match-wins for titles that hit multiple keyword sets.
# Higher-severity categories must appear before lower-severity ones.
EVENT_TYPE_KEYWORDS = {
    "delisting_risk": ["退市", "终止上市"],
    "regulatory_penalty": ["处罚", "行政监管"],
    "regulatory_inquiry": ["问询函", "监管函"],
    "risk_warning": ["风险提示", "风险警示", "留置", "立案", "调查"],
    "lawsuit": ["诉讼", "仲裁"],
    "suspension_resumption": ["停牌", "复牌"],
    "pledge": ["质押"],
    "ma_restructuring": ["重组", "收购", "并购"],
    "refinancing": ["增发", "配股", "可转债", "融资"],
    "earnings_forecast": ["业绩预告", "预增", "预减", "预亏"],
    "earnings_express": ["业绩快报"],
    "earnings_report": ["年报", "年度报告", "季报", "季度报告", "半年报", "财务报告", "经营数据"],
    "buyback": ["回购"],
    "dividend": ["分红", "权益分派", "利润分配"],
    "major_contract": ["重大合同", "中标"],
    "management_change": ["董事", "监事", "高管", "高级管理人员", "辞职", "聘任"],
}


def _clean_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title)


class EventNormalizer:
    def normalize_cninfo(self, provider_result: dict, symbol: str, lookback_days: int = 90) -> list[dict]:
        return self._normalize(provider_result, symbol, lookback_days, source="cninfo", source_type="official_announcement")

    def normalize_akshare(self, provider_result: dict, symbol: str, lookback_days: int = 90) -> list[dict]:
        return self._normalize(provider_result, symbol, lookback_days, source="akshare", source_type="announcement")

    def normalize_web_news(self, provider_result: dict, symbol: str, lookback_days: int = 14) -> list[dict]:
        return self._normalize(
            provider_result,
            symbol,
            lookback_days,
            source="web_news",
            source_type="web_news",
            allow_critical=False,
        )

    def _normalize(
        self,
        provider_result: dict,
        symbol: str,
        lookback_days: int,
        source: str,
        source_type: str,
        allow_critical: bool = True,
    ) -> list[dict]:
        records = provider_result.get("data", [])
        events = []
        for row in records:
            title = str(_first_present(row, ["公告标题", "公告名称", "title", "新闻标题"]) or "")
            if not title:
                continue
            publish_time = str(
                _first_present(row, ["公告时间", "公告日期", "publish_time", "date", "pubDate"])
                or date.today().isoformat()
            )
            event_type = self.classify_event_type(title)
            severity, sentiment = self.map_risk(event_type, title)
            if severity == "critical" and not allow_critical:
                severity = "high"
            dedupe_key = hashlib.sha1(
                f"{symbol}|{_clean_title(title)}|{publish_time[:10]}|{event_type}".encode("utf-8")
            ).hexdigest()
            events.append(
                {
                    "event_id": f"{source}_{symbol.replace('.', '_')}_{dedupe_key[:12]}",
                    "symbol": symbol,
                    "event_type": event_type,
                    "title": title,
                    "publish_time": publish_time,
                    "source": source,
                    "source_type": source_type,
                    "url": _first_present(row, ["公告链接", "url", "URL", "link"]),
                    "severity": severity,
                    "sentiment": sentiment,
                    "relevance": self._relevance(source),
                    "summary": _first_present(row, ["summary", "摘要", "description"]) or title,
                    "publisher": _first_present(row, ["publisher", "source_name", "媒体", "来源"]),
                    "keywords": self._keywords(title),
                    "dedupe_key": dedupe_key,
                }
            )
        return events

    def classify_event_type(self, title: str) -> str:
        for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
            if any(keyword in title for keyword in keywords):
                return event_type
        return "other"

    def map_risk(self, event_type: str, title: str) -> tuple[str, str]:
        if event_type == "delisting_risk":
            return "critical", "negative"
        if "留置" in title or "立案" in title or "调查" in title:
            return "high", "neutral_negative"
        if event_type in {"regulatory_penalty", "risk_warning"}:
            return "high", "negative"
        if event_type == "regulatory_inquiry":
            return "medium", "neutral_negative"
        if event_type == "earnings_forecast" and any(word in title for word in ["预亏", "预减"]):
            return "high", "negative"
        if event_type in {"buyback", "dividend", "major_contract"}:
            return "medium", "neutral_positive"
        if event_type == "earnings_report":
            return "medium", "neutral"
        if event_type == "ma_restructuring":
            return "high", "unknown"
        if event_type == "lawsuit":
            return "high", "neutral_negative"
        if event_type == "suspension_resumption":
            return "high", "unknown"
        return "low", "unknown"

    def _keywords(self, title: str) -> list[str]:
        return [
            keyword
            for keywords in EVENT_TYPE_KEYWORDS.values()
            for keyword in keywords
            if keyword in title
        ][:5]

    def _relevance(self, source: str) -> float:
        if source == "cninfo":
            return 0.95
        if source == "akshare":
            return 0.85
        if source == "web_news":
            return 0.62
        return 0.50
