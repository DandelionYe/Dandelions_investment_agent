import os
from datetime import date

from services.data.aggregator.evidence_builder import EvidenceBuilder
from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.data.providers.web_news_provider import WebNewsProvider
from services.research.event_engine import EventService


class _FakeResponse:
    content = """<?xml version="1.0" encoding="utf-8"?>
<rss>
  <channel>
    <item>
      <title>贵州茅台回应渠道价格波动</title>
      <link>https://example.com/news/1</link>
      <pubDate>Tue, 12 May 2026 09:30:00 +0800</pubDate>
      <description><![CDATA[公司回应市场关注。]]></description>
      <source>示例财经</source>
    </item>
  </channel>
</rss>""".encode("utf-8")

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self):
        self.trust_env = True
        self.last_url = None
        self.last_proxies = None

    def get(self, url, timeout, headers, proxies):
        self.last_url = url
        self.last_timeout = timeout
        self.last_headers = headers
        self.last_proxies = proxies
        return _FakeResponse()


def test_web_news_provider_disabled_returns_nonblocking_failure():
    provider = WebNewsProvider(enabled=False)

    result = provider.fetch_events({"normalized_symbol": "600519.SH", "plain_code": "600519"})

    assert result.metadata.success is False
    assert result.metadata.error_type == "provider_unavailable"
    assert result.data == []


def test_web_news_provider_forces_direct_connection(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    session = _FakeSession()
    provider = WebNewsProvider(
        enabled=True,
        force_no_proxy=True,
        session_factory=lambda: session,
    )

    result = provider.fetch_events(
        {
            "normalized_symbol": "600519.SH",
            "plain_code": "600519",
            "name": "贵州茅台",
            "asset_type": "stock",
        }
    )

    assert result.metadata.success is True
    assert result.data[0]["title"] == "贵州茅台回应渠道价格波动"
    assert session.trust_env is False
    assert session.last_proxies == {"http": None, "https": None}
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["NO_PROXY"] == "*"


def test_web_news_normalizer_downgrades_ordinary_news_critical_label():
    events = EventNormalizer().normalize_web_news(
        {
            "data": [
                {
                    "title": "某公司出现退市风险市场传闻",
                    "publish_time": "2026-05-12",
                    "url": "https://example.com/news/2",
                }
            ]
        },
        "600519.SH",
    )

    assert events[0]["source"] == "web_news"
    assert events[0]["source_type"] == "web_news"
    assert events[0]["event_type"] == "delisting_risk"
    assert events[0]["severity"] == "high"


class _FakeCninfoProvider:
    def fetch_events(self, symbol_info, lookback_days=90):
        return ProviderResult(
            provider="cninfo",
            dataset="stock_zh_a_disclosure_report_cninfo",
            symbol=symbol_info["normalized_symbol"],
            as_of=str(date.today()),
            data=[
                {
                    "公告标题": "关于收到交易所问询函的公告",
                    "公告时间": "2026-05-11",
                    "公告链接": "https://example.com/notice.pdf",
                }
            ],
            raw={},
            metadata=ProviderMetadata(success=True),
        )


class _FailIfCalledProvider:
    def fetch_events(self, symbol_info, lookback_days=90):
        raise AssertionError("AKShare should not be called when Cninfo has events")


class _FakeWebNewsProvider:
    enabled = True

    def fetch_events(self, symbol_info, lookback_days=14):
        return ProviderResult(
            provider="web_news",
            dataset="baidu_news_rss",
            symbol=symbol_info["normalized_symbol"],
            as_of=str(date.today()),
            data=[
                {
                    "title": "贵州茅台被监管部门立案调查传闻获关注",
                    "publish_time": "2026-05-12",
                    "url": "https://example.com/news/3",
                    "summary": "市场关注监管风险。",
                    "publisher": "示例财经",
                }
            ],
            raw={},
            metadata=ProviderMetadata(success=True),
        )


def test_event_service_merges_official_announcement_and_web_news():
    service = EventService()
    service.cninfo_provider = _FakeCninfoProvider()
    service.akshare_provider = _FailIfCalledProvider()
    service.web_news_provider = _FakeWebNewsProvider()

    result = service.build(
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "data_source": "qmt",
            "symbol_info": {
                "normalized_symbol": "600519.SH",
                "plain_code": "600519",
                "asset_type": "stock",
            },
        }
    )

    event_data = result["data"]["event_data"]
    evidence = EvidenceBuilder().build(
        {
            "symbol": "600519.SH",
            "as_of": "2026-05-12",
            "price_data": {},
            "fundamental_data": {},
            "valuation_data": {},
            **result["data"],
            "source_metadata": result["source_metadata"],
        }
    )

    assert result["source_metadata"]["event_data"]["source"] == "cninfo+web_news"
    assert len(event_data["events"]) == 2
    assert event_data["event_summary"]["high_severity_count"] == 1
    assert any(item["source"] == "web_news" for item in evidence["items"])
    assert any(log["provider"] == "web_news" for log in result["provider_run_log"])
