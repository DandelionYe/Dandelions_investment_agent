import os
from datetime import date

from services.data.aggregator.evidence_builder import EvidenceBuilder
from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.provider_contracts import ProviderMetadata, ProviderResult
from services.data.providers.web_news_provider import WebNewsProvider
from services.research.event_engine import EventService


class _FakeRssResponse:
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
    text = content.decode("utf-8")

    def raise_for_status(self):
        return None


class _FakeEastmoneyResponse:
    text = """jQueryDandelionsWebNews({
  "result": {
    "cmsArticleWebOld": [
      {
        "title": "贵州茅台回应渠道价格波动",
        "content": "公司回应市场关注。",
        "date": "2026-05-12 09:30:00",
        "mediaName": "东方财富",
        "code": "202605122222"
      }
    ]
  }
})"""
    content = text.encode("utf-8")

    def raise_for_status(self):
        return None


class _FakeXinhuanetResponse:
    text = """({
  "status": 0,
  "data": {
    "list": [
      {
        "Title": "贵州茅台召开业绩说明会回应经营变化",
        "PubTime": "2026-05-13 09:30:00",
        "LinkUrl": "http://www.xinhuanet.com/fortune/2026-05/13/c_test.htm",
        "Abstract": "公司回应投资者关切。",
        "SourceName": "新华网"
      },
      {
        "Title": "早知道·财讯热搜榜TOP10",
        "PubTime": "2026-05-13 08:00:00",
        "LinkUrl": "http://www.xinhuanet.com/fortune/2026-05/13/c_other.htm",
        "Abstract": "市场综合新闻。",
        "SourceName": "新华网"
      }
    ]
  }
})"""
    content = text.encode("utf-8")

    def raise_for_status(self):
        return None


class _FakeJsonResponse:
    content = b""
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class _FakeTextResponse:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self):
        self.trust_env = True
        self.last_url = None
        self.last_proxies = None

    def get(self, url, timeout, headers, proxies, params=None):
        self.last_url = url
        self.last_timeout = timeout
        self.last_headers = headers
        self.last_proxies = proxies
        self.last_params = params
        if "eastmoney" in url:
            return _FakeEastmoneyResponse()
        if "news.cn" in url:
            return _FakeXinhuanetResponse()
        if "thepaper.cn" in url:
            return _FakeJsonResponse(
                {
                    "data": {
                        "hotNews": [
                            {
                                "name": "贵州茅台回应渠道价格波动登上财经热榜",
                                "contId": "123456",
                                "pubTime": "2026-05-13 10:00:00",
                            },
                            {
                                "name": "国际体育赛事最新动态",
                                "contId": "999999",
                            },
                        ]
                    }
                }
            )
        if "bilibili.com" in url:
            return _FakeJsonResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "title": "贵州茅台回应年轻消费者讨论",
                                "desc": "品牌和渠道变化受到关注。",
                                "bvid": "BV1test",
                                "pubdate": 1778647200,
                                "stat": {"view": 168000},
                            },
                            {
                                "title": "热门游戏更新内容",
                                "bvid": "BV2test",
                            },
                        ]
                    },
                }
            )
        if "douyin.com" in url:
            return _FakeJsonResponse(
                {
                    "data": {
                        "word_list": [
                            {
                                "word": "贵州茅台渠道价格波动",
                                "hot_value": 985000,
                                "event_time": 1778650800,
                            },
                            {
                                "word": "普通娱乐热搜",
                                "hot_value": 100000,
                            },
                        ]
                    }
                }
            )
        if "api-one-wscn" in url:
            return _FakeJsonResponse(
                {
                    "data": {
                        "items": [
                            {
                                "title": "贵州茅台进入华尔街见闻市场热议",
                                "resource_id": "123",
                                "summary": "市场关注白酒龙头估值。",
                            }
                        ]
                    }
                }
            )
        if "weread.qq.com" in url:
            return _FakeJsonResponse(
                {
                    "books": [
                        {
                            "bookInfo": {
                                "title": "贵州茅台品牌研究",
                                "bookId": "wr123",
                                "intro": "商业案例阅读榜。",
                            }
                        }
                    ]
                }
            )
        if "36kr.com" in url:
            return _FakeTextResponse(
                '<div class="article-wrapper"><p><a href="/p/123">贵州茅台数字化转型案例</a></p></div>'
            )
        if "csdn.net" in url:
            return _FakeJsonResponse(
                {
                    "data": [
                        {
                            "articleTitle": "贵州茅台数据分析项目登上技术热榜",
                            "articleDetailUrl": "https://blog.csdn.net/test/article/details/1",
                        }
                    ]
                }
            )
        if "yicai.com" in url:
            return _FakeJsonResponse(
                {
                    "newsRank": {
                        "week": [
                            {
                                "NewsTitle": "贵州茅台位列第一财经热门公司榜",
                                "url": "/news/123.html",
                            }
                        ]
                    }
                }
            )
        if "github.com" in url:
            return _FakeTextResponse(
                """
                <article>
                  <h2><a href="/example/guizhou-maotai">example / 贵州茅台-data</a></h2>
                  <p>开源趋势项目。</p>
                </article>
                """
            )
        if "trends.google.com" in url:
            return _FakeTextResponse(
                """)]}'{
                  "storySummaries": {
                    "trendingStories": [
                      {
                        "articles": [
                          {
                            "articleTitle": "贵州茅台 overseas trend",
                            "url": "https://example.com/google-trend",
                            "source": "Example"
                          }
                        ]
                      }
                    ]
                  }
                }"""
            )
        if "r.inews.qq.com" in url:
            return _FakeJsonResponse(
                {
                    "idlist": [
                        {
                            "title": "贵州茅台登上腾讯新闻热点榜",
                            "url": "https://new.qq.com/rain/a/test",
                        }
                    ]
                }
            )
        if "sinanews.sina.cn" in url:
            return _FakeTextResponse(
                'SM = {"data":{"data":{"hotList":[{"info":{"title":"贵州茅台进入新浪热门话题","hotValue":"100"}}]}}};'
            )
        if "top.finance.sina.com.cn" in url:
            return _FakeTextResponse(
                'all_1_data = {"data":[{"title":"贵州茅台进入新浪新闻热门榜","url":"https://finance.sina.com.cn/test.shtml","top_num":"88"}]};'
            )
        return _FakeRssResponse()


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
        source_order=["baidu"],
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
    assert result.dataset == "baidu_news_rss"
    assert session.trust_env is False
    assert session.last_proxies == {"http": None, "https": None}
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["NO_PROXY"] == "*"


def test_web_news_provider_maps_eastmoney_fetcher_records(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")

    def fake_fetcher(symbol: str):
        assert symbol == "600519"
        return [
            {
                "新闻标题": "营收确认规则会变吗？茅台回应",
                "新闻内容": "公司在业绩说明会上回应收入确认规则。",
                "发布时间": "2026-05-11 21:15:00",
                "文章来源": "国际金融报",
                "新闻链接": "http://finance.eastmoney.com/a/202605113733371558.html",
            }
        ]

    provider = WebNewsProvider(
        enabled=True,
        force_no_proxy=True,
        source_order=["eastmoney"],
        eastmoney_fetcher=fake_fetcher,
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
    assert result.dataset == "eastmoney_stock_news"
    assert result.data[0]["publisher"] == "国际金融报"
    assert "HTTP_PROXY" not in os.environ


def test_web_news_provider_filters_low_quality_titles():
    def fake_fetcher(symbol: str):
        return [
            {
                "新闻标题": "福利活动报名",
                "新闻内容": "营销内容。",
                "发布时间": "2026-05-11 08:00:00",
                "文章来源": "东方财富",
                "新闻链接": "http://example.com/ad.html",
            },
            {
                "新闻标题": "贵州茅台召开业绩说明会回应合同负债变化",
                "新闻内容": "管理层回应投资者关切。",
                "发布时间": "2026-05-11 21:15:00",
                "文章来源": "国际金融报",
                "新闻链接": "http://finance.eastmoney.com/a/202605113733371558.html",
            },
        ]

    provider = WebNewsProvider(
        enabled=True,
        source_order=["eastmoney"],
        eastmoney_fetcher=fake_fetcher,
    )
    result = provider.fetch_events(
        {
            "normalized_symbol": "600519.SH",
            "plain_code": "600519",
            "name": "贵州茅台",
            "asset_type": "stock",
        }
    )

    assert [item["title"] for item in result.data] == [
        "贵州茅台召开业绩说明会回应合同负债变化"
    ]


def test_web_news_provider_can_use_baidu_source_order():
    session = _FakeSession()
    provider = WebNewsProvider(
        enabled=True,
        force_no_proxy=False,
        source_order=["baidu"],
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
    assert result.dataset == "baidu_news_rss"
    assert result.data[0]["publisher"] == "示例财经"


def test_web_news_provider_falls_back_for_malformed_rss():
    provider = WebNewsProvider(enabled=True, limit=5)
    records = provider._parse_rss(
        """<?xml version="1.0" encoding="utf-8"?>
<rss>
  <channel>
    <item>
      <title><![CDATA[贵州茅台新闻标题]]></title>
      <link>https://example.com/news/4</link>
      <pubDate>2026-05-13</pubDate>
      <description><![CDATA[摘要里包含不闭合标签 <b>重点]]></description>
      <source>示例财经</source>
    </item>
  </channel>
</rss>""".encode("utf-8")
    )

    assert records[0]["title"] == "贵州茅台新闻标题"
    assert records[0]["url"] == "https://example.com/news/4"
    assert records[0]["publisher"] == "示例财经"


def test_web_news_provider_parses_sina_roll_html():
    provider = WebNewsProvider(enabled=True, source_order=["sina"], limit=5)
    records = provider._parse_sina_roll_html(
        """
        <ul class="seo_data_list">
          <li><a href="https://cj.sina.cn/article/norm_detail?url=https%3A%2F%2Ffinance.sina.com.cn%2Fstock%2F2026-05-13%2Fdoc-test.shtml">贵州茅台召开业绩说明会</a></li>
          <li><a href="https://finance.sina.com.cn/stock/2026-05-13/doc-ad.shtml">福利活动报名</a></li>
        </ul>
        """
    )

    assert records == [
        {
            "title": "贵州茅台召开业绩说明会",
            "url": "https://finance.sina.com.cn/stock/2026-05-13/doc-test.shtml",
            "publish_time": "2026-05-13",
            "summary": "贵州茅台召开业绩说明会",
            "publisher": "新浪财经",
            "query_provider": "sina",
        }
    ]


def test_web_news_provider_can_use_xinhuanet_source_order():
    session = _FakeSession()
    provider = WebNewsProvider(
        enabled=True,
        source_order=["xinhuanet"],
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
    assert result.dataset == "xinhuanet_finance_latest"
    assert result.data == [
        {
            "title": "贵州茅台召开业绩说明会回应经营变化",
            "url": "http://www.xinhuanet.com/fortune/2026-05/13/c_test.htm",
            "publish_time": "2026-05-13 09:30:00",
            "summary": "公司回应投资者关切。",
            "publisher": "新华网",
            "query_provider": "xinhuanet",
        }
    ]


def test_web_news_provider_can_use_hotrank_source_order():
    session = _FakeSession()
    provider = WebNewsProvider(
        enabled=True,
        source_order=["hotrank"],
        hotrank_sources=[
            "wallstreetcn",
            "yicai",
            "36kr",
            "tencent",
            "sina_news",
            "sina_hot",
            "pengpai",
            "bilibili",
            "douyin",
            "csdn",
            "github",
            "google",
            "weread",
        ],
        session_factory=lambda: session,
        limit=20,
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
    assert result.dataset == "hotrank_public_opinion"
    assert [item["query_provider"] for item in result.data] == [
        "wallstreetcn",
        "yicai",
        "36kr",
        "tencent",
        "sina_news",
        "sina_hot",
        "pengpai",
        "bilibili",
        "douyin",
        "csdn",
        "github",
        "google",
        "weread",
    ]
    assert result.data[0]["publisher"] == "华尔街见闻"
    assert result.data[0]["url"] == "https://wallstreetcn.com/articles/123"
    assert result.data[6]["url"] == "https://www.thepaper.cn/newsDetail_forward_123456"
    assert result.data[7]["url"] == "https://www.bilibili.com/video/BV1test"
    assert result.data[8]["url"].startswith("https://www.douyin.com/search/")
    assert result.data[-1]["url"] == "https://weread.qq.com/web/bookDetail/wr123"


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
