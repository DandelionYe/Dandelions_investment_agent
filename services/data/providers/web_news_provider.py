import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse

from dotenv import load_dotenv

from services.data.provider_contracts import (
    ProviderMetadata,
    ProviderResult,
    ProviderUnavailableError,
    get_provider_error_type,
)
from services.network.proxy_policy import disable_proxy_for_current_process

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", text).strip()


LOW_QUALITY_NEWS_KEYWORDS = (
    "广告",
    "推广",
    "赞助",
    "福利",
    "优惠",
    "抽奖",
    "直播预告",
    "报名",
)

HOTRANK_TITLE_KEYS = (
    "title",
    "Title",
    "name",
    "Name",
    "bookName",
    "articleTitle",
    "article_title",
    "word",
    "sentence",
    "event_word",
    "display_name",
    "mobileTitle",
    "contName",
    "NewsTitle",
)
HOTRANK_URL_KEYS = (
    "url",
    "URL",
    "link",
    "LinkUrl",
    "appUrl",
    "jumpUrl",
    "jump_url",
    "share_url",
    "shareUrl",
    "short_link_v2",
    "articleDetailUrl",
    "article_url",
    "mobileUrl",
    "uri",
)
HOTRANK_SUMMARY_KEYS = (
    "summary",
    "Summary",
    "desc",
    "description",
    "Abstract",
    "content",
    "brief",
    "intro",
    "digest",
)
HOTRANK_TIME_KEYS = (
    "publish_time",
    "publishTime",
    "PubTime",
    "pubTime",
    "pubdate",
    "updateTime",
    "event_time",
    "display_time",
    "created_at",
    "ctime",
)
HOTRANK_SCORE_KEYS = (
    "hotScore",
    "hot_score",
    "hot_value",
    "heat",
    "score",
    "view",
    "readCount",
    "top_num",
    "watchCount",
)


def _is_low_quality_news(title: str) -> bool:
    cleaned = _strip_html(title)
    if len(cleaned) < 8:
        return True
    return any(keyword in cleaned for keyword in LOW_QUALITY_NEWS_KEYWORDS)


class WebNewsProvider:
    """Domestic web news provider backed by Eastmoney and finance-news fallbacks.

    News crawlers in this project must not inherit user VPN/proxy settings:
    several domestic news endpoints only work reliably through direct CN
    network access. The provider therefore disables proxy environment variables
    and also makes the requests session ignore environment proxies.
    """

    provider = "web_news"
    dataset = "web_news_search"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        endpoint: str | None = None,
        eastmoney_endpoint: str | None = None,
        sina_endpoint: str | None = None,
        xinhuanet_endpoint: str | None = None,
        pengpai_endpoint: str | None = None,
        bilibili_endpoint: str | None = None,
        douyin_endpoint: str | None = None,
        douyin_home_endpoint: str | None = None,
        wallstreetcn_endpoint: str | None = None,
        weread_endpoint: str | None = None,
        kr36_endpoint: str | None = None,
        csdn_endpoint: str | None = None,
        yicai_endpoint: str | None = None,
        github_endpoint: str | None = None,
        google_trends_endpoint: str | None = None,
        tencent_endpoint: str | None = None,
        sina_hot_endpoint: str | None = None,
        sina_news_endpoint: str | None = None,
        hotrank_sources: str | list[str] | None = None,
        source_order: str | list[str] | None = None,
        limit: int | None = None,
        timeout_seconds: int | None = None,
        force_no_proxy: bool | None = None,
        session_factory: Any | None = None,
        eastmoney_fetcher: Any | None = None,
    ) -> None:
        self.enabled = _env_bool("WEB_NEWS_ENABLED", False) if enabled is None else enabled
        self.endpoint = endpoint or os.getenv("WEB_NEWS_BAIDU_RSS_URL", "https://news.baidu.com/ns")
        self.eastmoney_endpoint = eastmoney_endpoint or os.getenv(
            "WEB_NEWS_EASTMONEY_URL",
            "https://search-api-web.eastmoney.com/search/jsonp",
        )
        self.sina_endpoint = sina_endpoint or os.getenv(
            "WEB_NEWS_SINA_ROLL_URL",
            "https://finance.sina.com.cn/roll/",
        )
        self.xinhuanet_endpoint = xinhuanet_endpoint or os.getenv(
            "WEB_NEWS_XINHUANET_URL",
            "http://qc.wa.news.cn/nodeart/list",
        )
        self.pengpai_endpoint = pengpai_endpoint or os.getenv(
            "WEB_NEWS_PENGPAI_HOT_URL",
            "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar",
        )
        self.bilibili_endpoint = bilibili_endpoint or os.getenv(
            "WEB_NEWS_BILIBILI_RANKING_URL",
            "https://api.bilibili.com/x/web-interface/ranking/v2",
        )
        self.douyin_endpoint = douyin_endpoint or os.getenv(
            "WEB_NEWS_DOUYIN_HOT_URL",
            "https://www.douyin.com/aweme/v1/web/hot/search/list/",
        )
        self.douyin_home_endpoint = douyin_home_endpoint or os.getenv(
            "WEB_NEWS_DOUYIN_HOME_URL",
            "https://www.douyin.com/",
        )
        self.wallstreetcn_endpoint = wallstreetcn_endpoint or os.getenv(
            "WEB_NEWS_WALLSTREETCN_HOT_URL",
            "https://api-one-wscn.awtmt.com/apiv1/content/articles/hot?period=all",
        )
        self.weread_endpoint = weread_endpoint or os.getenv(
            "WEB_NEWS_WEREAD_RANK_URL",
            "https://weread.qq.com/web/bookListInCategory/rising?rank=1",
        )
        self.kr36_endpoint = kr36_endpoint or os.getenv(
            "WEB_NEWS_36KR_HOT_URL",
            "https://www.36kr.com/hot-list/renqi/",
        )
        self.csdn_endpoint = csdn_endpoint or os.getenv(
            "WEB_NEWS_CSDN_HOT_URL",
            "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=25&type=",
        )
        self.yicai_endpoint = yicai_endpoint or os.getenv(
            "WEB_NEWS_YICAI_HOT_URL",
            "https://www.yicai.com/api/ajax/getranklistbykeys?keys=newsRank%2CvideoRank%2CimageRank%2CliveRank",
        )
        self.github_endpoint = github_endpoint or os.getenv(
            "WEB_NEWS_GITHUB_TRENDING_URL",
            "https://github.com/trending",
        )
        self.google_trends_endpoint = google_trends_endpoint or os.getenv(
            "WEB_NEWS_GOOGLE_TRENDS_URL",
            "https://trends.google.com/trends/api/realtimetrends?hl=zh-CN&tz=-480&cat=all&fi=0&fs=0&geo=US&ri=300&rs=20&sort=0",
        )
        self.tencent_endpoint = tencent_endpoint or os.getenv(
            "WEB_NEWS_TENCENT_HOT_URL",
            "https://r.inews.qq.com/gw/event/pc_hot_ranking_list?ids_hash=&offset=0&page_size=50",
        )
        self.sina_hot_endpoint = sina_hot_endpoint or os.getenv(
            "WEB_NEWS_SINA_HOT_URL",
            "https://sinanews.sina.cn/h5/top_news_list.d.html",
        )
        self.sina_news_endpoint = sina_news_endpoint or os.getenv(
            "WEB_NEWS_SINA_NEWS_TOP_URL",
            "https://top.finance.sina.com.cn/ws/GetTopDataList.php",
        )
        self.hotrank_sources = self._hotrank_sources(hotrank_sources)
        self.source_order = self._source_order(source_order)
        self.limit = limit or _env_int("WEB_NEWS_LIMIT", 10)
        self.timeout_seconds = timeout_seconds or _env_int("WEB_NEWS_TIMEOUT_SECONDS", 8)
        self.force_no_proxy = (
            _env_bool("WEB_NEWS_FORCE_NO_PROXY", True)
            if force_no_proxy is None
            else force_no_proxy
        )
        self.session_factory = session_factory
        self.eastmoney_fetcher = eastmoney_fetcher

    def fetch_events(self, symbol_info: dict, lookback_days: int = 14) -> ProviderResult:
        started = perf_counter()
        symbol = symbol_info.get("normalized_symbol") or symbol_info.get("qmt_code") or ""

        if not self.enabled:
            error = ProviderUnavailableError("web news provider is disabled")
            return self._result(
                symbol=symbol,
                data=[],
                dataset=self.dataset,
                source_url=self.endpoint,
                success=False,
                error=str(error),
                error_type=error.error_type,
                started=started,
            )

        try:
            if self.force_no_proxy:
                disable_proxy_for_current_process()

            query = self._build_query(symbol_info)
            records, dataset, source_url = self._fetch_by_source_order(symbol_info, query)
            return self._result(
                symbol=symbol,
                data=records,
                dataset=dataset,
                source_url=source_url,
                success=len(records) > 0,
                error=None if records else "web news provider returned no records",
                error_type=None if records else ProviderUnavailableError.error_type,
                started=started,
            )
        except Exception as exc:
            return self._result(
                symbol=symbol,
                data=[],
                dataset=self.dataset,
                source_url=self.endpoint,
                success=False,
                error=str(exc),
                error_type=get_provider_error_type(exc),
                started=started,
            )

    def _source_order(self, value: str | list[str] | None) -> list[str]:
        if value is None:
            value = os.getenv("WEB_NEWS_SOURCES", "eastmoney,sina,xinhuanet,hotrank,baidu")
        if isinstance(value, str):
            sources = [item.strip().lower() for item in value.split(",")]
        else:
            sources = [str(item).strip().lower() for item in value]
        return [
            source
            for source in sources
            if source in {"eastmoney", "sina", "xinhuanet", "hotrank", "baidu"}
        ]

    def _hotrank_sources(self, value: str | list[str] | None) -> list[str]:
        if value is None:
            value = os.getenv(
                "WEB_NEWS_HOTRANK_SOURCES",
                (
                    "wallstreetcn,yicai,36kr,tencent,sina_news,sina_hot,"
                    "pengpai,bilibili,douyin,csdn,github,google,weread"
                ),
            )
        if isinstance(value, str):
            sources = [item.strip().lower() for item in value.split(",")]
        else:
            sources = [str(item).strip().lower() for item in value]
        return [
            source
            for source in sources
            if source
            in {
                "pengpai",
                "bilibili",
                "douyin",
                "wallstreetcn",
                "weread",
                "36kr",
                "csdn",
                "yicai",
                "github",
                "google",
                "tencent",
                "sina_hot",
                "sina_news",
            }
        ]

    def _build_query(self, symbol_info: dict) -> str:
        company_name = str(symbol_info.get("name") or "").strip()
        plain_code = str(symbol_info.get("plain_code") or "").strip()
        asset_type = str(symbol_info.get("asset_type") or "stock").strip()
        extra_keywords = os.getenv("WEB_NEWS_EXTRA_KEYWORDS", "").strip()

        parts = [part for part in (company_name, plain_code) if part]
        if asset_type == "etf":
            parts.append("ETF 新闻")
        else:
            parts.append("股票 新闻 政策 舆情")
        if extra_keywords:
            parts.append(extra_keywords)
        return " ".join(parts)

    def _fetch_by_source_order(self, symbol_info: dict, query: str) -> tuple[list[dict], str, str]:
        errors = []
        for source in self.source_order:
            try:
                if source == "eastmoney":
                    records = self._fetch_eastmoney_news(symbol_info)
                    if records:
                        return records, "eastmoney_stock_news", self.eastmoney_endpoint
                elif source == "sina":
                    records = self._fetch_sina_roll_news(symbol_info, query)
                    if records:
                        return records, "sina_finance_roll", self.sina_endpoint
                elif source == "xinhuanet":
                    records = self._fetch_xinhuanet_news(symbol_info)
                    if records:
                        return records, "xinhuanet_finance_latest", self.xinhuanet_endpoint
                elif source == "hotrank":
                    records = self._fetch_hotrank_public_opinion(symbol_info)
                    if records:
                        return records, "hotrank_public_opinion", self._hotrank_source_url()
                elif source == "baidu":
                    records = self._fetch_baidu_news(query)
                    if records:
                        return records, "baidu_news_rss", self.endpoint
            except Exception as exc:
                errors.append(f"{source}: {exc}")

        if errors:
            raise ProviderUnavailableError("; ".join(errors))
        return [], self.dataset, self.endpoint

    def _fetch_eastmoney_news(self, symbol_info: dict) -> list[dict]:
        plain_code = str(symbol_info.get("plain_code") or "").strip()
        if not plain_code:
            return []

        if self.eastmoney_fetcher:
            return self._eastmoney_frame_to_records(self.eastmoney_fetcher(plain_code))

        try:
            return self._fetch_eastmoney_news_via_akshare(plain_code)
        except Exception:
            return self._fetch_eastmoney_news_direct(plain_code)

    def _fetch_eastmoney_news_via_akshare(self, plain_code: str) -> list[dict]:
        import akshare as ak
        import pandas as pd

        # AkShare's current Eastmoney news cleaner can fail when pandas uses
        # pyarrow-backed inferred strings, because it passes literal unicode
        # escape patterns to regex replacement. Keep this call on the classic
        # string path and restore pandas' option after the fetch.
        with pd.option_context("future.infer_string", False):
            frame = ak.stock_news_em(symbol=plain_code)
        return self._eastmoney_frame_to_records(frame)

    def _fetch_eastmoney_news_direct(self, plain_code: str) -> list[dict]:
        import requests

        session = self.session_factory() if self.session_factory else requests.Session()
        session.trust_env = False
        callback = "jQueryDandelionsWebNews"
        inner_param = {
            "uid": "",
            "keyword": plain_code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": self.limit,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        response = session.get(
            self.eastmoney_endpoint,
            params={
                "cb": callback,
                "param": json.dumps(inner_param, ensure_ascii=False, separators=(",", ":")),
                "_": "0",
            },
            timeout=self.timeout_seconds,
            headers={
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": f"https://so.eastmoney.com/news/s?keyword={plain_code}",
                "User-Agent": "Mozilla/5.0 DandelionsInvestmentAgent/0.3",
            },
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        data = self._parse_jsonp(response.text)
        rows = data.get("result", {}).get("cmsArticleWebOld") or []
        return self._eastmoney_frame_to_records(rows)

    def _eastmoney_frame_to_records(self, value: Any) -> list[dict]:
        try:
            import pandas as pd

            if isinstance(value, pd.DataFrame):
                rows = value.where(pd.notna(value), None).to_dict(orient="records")
            else:
                rows = list(value or [])
        except Exception:
            rows = list(value or [])

        records = []
        for row in rows[: self.limit]:
            title = _strip_html(str(row.get("新闻标题") or row.get("title") or ""))
            if not title or _is_low_quality_news(title):
                continue
            article_code = str(row.get("code") or row.get("-") or "").strip()
            url = row.get("新闻链接") or row.get("url") or (
                f"http://finance.eastmoney.com/a/{article_code}.html" if article_code else None
            )
            records.append(
                {
                    "title": title,
                    "url": url,
                    "publish_time": str(row.get("发布时间") or row.get("date") or date.today().isoformat()),
                    "summary": _strip_html(str(row.get("新闻内容") or row.get("content") or "")),
                    "publisher": str(row.get("文章来源") or row.get("mediaName") or "东方财富"),
                    "query_provider": "eastmoney",
                }
            )
        return records

    def _fetch_xinhuanet_news(self, symbol_info: dict) -> list[dict]:
        import requests

        session = self.session_factory() if self.session_factory else requests.Session()
        session.trust_env = False
        response = session.get(
            self.xinhuanet_endpoint,
            params={
                "nid": "11147664",
                "pgnum": "1",
                "cnt": str(max(self.limit, 20)),
                "tp": "1",
                "orderby": "1",
            },
            timeout=self.timeout_seconds,
            headers={
                "Accept": "application/json,text/javascript,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "User-Agent": "Mozilla/5.0 DandelionsInvestmentAgent/0.3",
            },
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        data = self._parse_jsonp(response.text)
        rows = data.get("data", {}).get("list") or []
        records = []
        terms = self._relevance_terms(symbol_info)
        for row in rows[: max(self.limit, 20)]:
            title = _strip_html(str(row.get("Title") or ""))
            if not title or _is_low_quality_news(title):
                continue
            summary = _strip_html(str(row.get("Abstract") or ""))
            if terms and not any(term in f"{title} {summary}" for term in terms):
                continue
            records.append(
                {
                    "title": title,
                    "url": row.get("LinkUrl"),
                    "publish_time": str(row.get("PubTime") or date.today().isoformat()),
                    "summary": summary or title,
                    "publisher": str(row.get("SourceName") or "新华网"),
                    "query_provider": "xinhuanet",
                }
            )
            if len(records) >= self.limit:
                break
        return records

    def _fetch_hotrank_public_opinion(self, symbol_info: dict) -> list[dict]:
        records = []
        for source in self.hotrank_sources:
            try:
                if source == "pengpai":
                    records.extend(self._fetch_pengpai_hotrank(symbol_info))
                elif source == "bilibili":
                    records.extend(self._fetch_bilibili_hotrank(symbol_info))
                elif source == "douyin":
                    records.extend(self._fetch_douyin_hotrank(symbol_info))
                elif source == "wallstreetcn":
                    records.extend(self._fetch_wallstreetcn_hotrank(symbol_info))
                elif source == "weread":
                    records.extend(self._fetch_weread_hotrank(symbol_info))
                elif source == "36kr":
                    records.extend(self._fetch_36kr_hotrank(symbol_info))
                elif source == "csdn":
                    records.extend(self._fetch_csdn_hotrank(symbol_info))
                elif source == "yicai":
                    records.extend(self._fetch_yicai_hotrank(symbol_info))
                elif source == "github":
                    records.extend(self._fetch_github_hotrank(symbol_info))
                elif source == "google":
                    records.extend(self._fetch_google_hotrank(symbol_info))
                elif source == "tencent":
                    records.extend(self._fetch_tencent_hotrank(symbol_info))
                elif source == "sina_hot":
                    records.extend(self._fetch_sina_hotrank(symbol_info))
                elif source == "sina_news":
                    records.extend(self._fetch_sina_news_hotrank(symbol_info))
            except Exception:
                continue
            if len(records) >= self.limit:
                break
        return self._dedupe_records(records)[: self.limit]

    def _fetch_pengpai_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.pengpai_endpoint,
            headers={
                "Accept": "application/json,text/javascript,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.thepaper.cn/",
                "User-Agent": "Mozilla/5.0 DandelionsInvestmentAgent/0.3",
            },
        )
        return self._hotrank_items_to_records(
            self._extract_hotrank_items(data),
            source="pengpai",
            publisher="澎湃新闻",
            symbol_info=symbol_info,
            base_url="https://www.thepaper.cn",
        )

    def _fetch_bilibili_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.bilibili_endpoint,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.bilibili.com/v/popular/all/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
            impersonate_chrome=True,
        )
        rows = data.get("data", {}).get("list") if isinstance(data, dict) else []
        return self._hotrank_items_to_records(
            rows or [],
            source="bilibili",
            publisher="Bilibili 热榜",
            symbol_info=symbol_info,
            base_url="https://www.bilibili.com",
        )

    def _fetch_douyin_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.douyin_endpoint,
            params={
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "detail_list": "1",
                "round_trip_time": "50",
            },
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.douyin.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
            warmup_url=self.douyin_home_endpoint,
            impersonate_chrome=True,
        )
        rows = data.get("data", {}).get("word_list") if isinstance(data, dict) else []
        if not rows and isinstance(data, dict):
            rows = data.get("word_list") or []
        return self._hotrank_items_to_records(
            rows,
            source="douyin",
            publisher="抖音热搜",
            symbol_info=symbol_info,
            base_url="https://www.douyin.com",
        )

    def _fetch_wallstreetcn_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.wallstreetcn_endpoint,
            headers=self._browser_headers("https://wallstreetcn.com/"),
            impersonate_chrome=True,
        )
        return self._hotrank_items_to_records(
            self._extract_hotrank_items(data),
            source="wallstreetcn",
            publisher="华尔街见闻",
            symbol_info=symbol_info,
            base_url="https://wallstreetcn.com",
        )

    def _fetch_weread_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.weread_endpoint,
            headers=self._browser_headers("https://weread.qq.com/web/category/rising"),
        )
        return self._hotrank_items_to_records(
            self._extract_hotrank_items(data),
            source="weread",
            publisher="微信读书排行榜",
            symbol_info=symbol_info,
            base_url="https://weread.qq.com",
        )

    def _fetch_36kr_hotrank(self, symbol_info: dict) -> list[dict]:
        base = self.kr36_endpoint.rstrip("/") + "/"
        url = f"{base}{date.today().isoformat()}/1"
        text = self._request_text(
            url,
            headers=self._browser_headers("https://www.36kr.com/hot-list/renqi/"),
        )
        return self._hotrank_items_to_records(
            self._parse_36kr_html(text),
            source="36kr",
            publisher="36氪",
            symbol_info=symbol_info,
            base_url="https://www.36kr.com",
        )

    def _fetch_csdn_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.csdn_endpoint,
            headers=self._browser_headers("https://blog.csdn.net/rank/list"),
            impersonate_chrome=True,
        )
        return self._hotrank_items_to_records(
            self._extract_hotrank_items(data),
            source="csdn",
            publisher="CSDN 热榜",
            symbol_info=symbol_info,
            base_url="https://blog.csdn.net",
        )

    def _fetch_yicai_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.yicai_endpoint,
            headers=self._browser_headers("https://www.yicai.com/"),
        )
        rows = []
        news_rank = data.get("newsRank", {}) if isinstance(data, dict) else {}
        for key in ("week", "day", "month"):
            rows.extend(news_rank.get(key, []) or [])
        return self._hotrank_items_to_records(
            rows,
            source="yicai",
            publisher="第一财经",
            symbol_info=symbol_info,
            base_url="https://www.yicai.com",
        )

    def _fetch_github_hotrank(self, symbol_info: dict) -> list[dict]:
        text = self._request_text(
            self.github_endpoint,
            headers=self._browser_headers("https://github.com/trending"),
        )
        return self._hotrank_items_to_records(
            self._parse_github_trending_html(text),
            source="github",
            publisher="GitHub Trending",
            symbol_info=symbol_info,
            base_url="https://github.com",
        )

    def _fetch_google_hotrank(self, symbol_info: dict) -> list[dict]:
        text = self._request_text(
            self.google_trends_endpoint,
            headers=self._browser_headers("https://trends.google.com/trends/"),
        )
        return self._hotrank_items_to_records(
            self._parse_google_trends_text(text),
            source="google",
            publisher="Google 热搜",
            symbol_info=symbol_info,
            base_url="https://trends.google.com",
        )

    def _fetch_tencent_hotrank(self, symbol_info: dict) -> list[dict]:
        data = self._request_json(
            self.tencent_endpoint,
            headers=self._browser_headers("https://new.qq.com/"),
        )
        rows = data.get("idlist", []) if isinstance(data, dict) else []
        return self._hotrank_items_to_records(
            self._extract_hotrank_items(rows),
            source="tencent",
            publisher="腾讯新闻热点榜",
            symbol_info=symbol_info,
            base_url="https://new.qq.com",
        )

    def _fetch_sina_hotrank(self, symbol_info: dict) -> list[dict]:
        text = self._request_text(
            self.sina_hot_endpoint,
            headers=self._browser_headers("https://sina.cn/"),
        )
        return self._hotrank_items_to_records(
            self._parse_sina_hot_html(text),
            source="sina_hot",
            publisher="新浪热门",
            symbol_info=symbol_info,
            base_url="https://sina.cn",
        )

    def _fetch_sina_news_hotrank(self, symbol_info: dict) -> list[dict]:
        rows = []
        params_list = [
            {
                "top_type": "day",
                "top_cat": "finance_0_suda",
                "top_time": date.today().strftime("%Y%m%d"),
                "top_show_num": "20",
                "top_order": "DESC",
                "js_var": "all_1_data",
                "get_new": "1",
            },
            {
                "top_type": "day",
                "top_cat": "finance_news_0_suda",
                "top_time": date.today().strftime("%Y%m%d"),
                "top_show_num": "20",
                "top_order": "DESC",
                "js_var": "all_1_data",
                "get_new": "1",
            },
            {
                "top_not_url": "/ustock/",
                "top_type": "day",
                "top_cat": "finance_stock_conten_suda",
                "top_time": date.today().strftime("%Y%m%d"),
                "top_show_num": "20",
                "top_order": "DESC",
                "js_var": "stock_1_data",
                "get_new": "1",
            },
        ]
        for params in params_list:
            text = self._request_text(
                self.sina_news_endpoint,
                params=params,
                headers=self._browser_headers("https://finance.sina.com.cn/topnews/"),
            )
            rows.extend(self._parse_sina_news_top_text(text))
        return self._hotrank_items_to_records(
            rows,
            source="sina_news",
            publisher="新浪新闻热门",
            symbol_info=symbol_info,
            base_url="https://finance.sina.com.cn",
        )

    def _request_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        warmup_url: str | None = None,
        impersonate_chrome: bool = False,
    ) -> dict:
        import requests

        requests_module = requests
        use_impersonation = False
        if impersonate_chrome and self.session_factory is None:
            try:
                from curl_cffi import requests as curl_requests

                requests_module = curl_requests
                use_impersonation = True
            except ImportError:
                requests_module = requests

        session = self.session_factory() if self.session_factory else requests_module.Session()
        if hasattr(session, "trust_env"):
            session.trust_env = False
        request_kwargs = {
            "timeout": self.timeout_seconds,
            "headers": headers or {},
            "proxies": {"http": None, "https": None},
        }
        if use_impersonation:
            request_kwargs["impersonate"] = "chrome"
        if warmup_url:
            session.get(
                warmup_url,
                **request_kwargs,
            )
        response = session.get(
            url,
            params=params,
            **request_kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _request_text(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        impersonate_chrome: bool = False,
    ) -> str:
        import requests

        requests_module = requests
        use_impersonation = False
        if impersonate_chrome and self.session_factory is None:
            try:
                from curl_cffi import requests as curl_requests

                requests_module = curl_requests
                use_impersonation = True
            except ImportError:
                requests_module = requests

        session = self.session_factory() if self.session_factory else requests_module.Session()
        if hasattr(session, "trust_env"):
            session.trust_env = False
        request_kwargs = {
            "timeout": self.timeout_seconds,
            "headers": headers or {},
            "proxies": {"http": None, "https": None},
        }
        if use_impersonation:
            request_kwargs["impersonate"] = "chrome"
        response = session.get(
            url,
            params=params,
            **request_kwargs,
        )
        response.raise_for_status()
        return response.text or self._decode_content(response.content)

    def _browser_headers(self, referer: str) -> dict[str, str]:
        return {
            "Accept": "application/json,text/plain,text/html,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }

    def _extract_hotrank_items(self, value: Any) -> list[dict]:
        items = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if self._first_nonempty(node, HOTRANK_TITLE_KEYS):
                    items.append(node)
                    return
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return items

    def _parse_36kr_html(self, text: str) -> list[dict]:
        records = []
        pattern = re.compile(
            r"<a[^>]+href=[\"'](?P<url>/p/[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(text):
            title = _strip_html(match.group("title"))
            if title:
                records.append({"title": title, "url": match.group("url")})
        return self._dedupe_records(records)

    def _parse_github_trending_html(self, text: str) -> list[dict]:
        records = []
        article_pattern = re.compile(
            r"<article\b.*?</article>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        link_pattern = re.compile(
            r"<h2[^>]*>.*?<a[^>]+href=[\"'](?P<url>/[^\"']+/[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        for article in article_pattern.findall(text):
            match = link_pattern.search(article)
            if not match:
                continue
            title = _strip_html(match.group("title")).replace(" / ", "/").replace(" ", "")
            records.append(
                {
                    "title": title,
                    "url": match.group("url"),
                    "summary": _strip_html(self._tag_text(article, "p") or ""),
                }
            )
        return records

    def _parse_google_trends_text(self, text: str) -> list[dict]:
        data = self._loads_prefixed_json(text)
        rows = []
        stories = data.get("storySummaries", {}).get("trendingStories", [])
        for story in stories:
            title = _strip_html(str(story.get("title") or ""))
            url = None
            summary = ""
            articles = story.get("articles") or []
            if articles:
                article = articles[0]
                title = title or _strip_html(str(article.get("articleTitle") or ""))
                url = article.get("url")
                summary = _strip_html(str(article.get("snippet") or article.get("source") or ""))
            if title:
                rows.append({"title": title, "url": url, "summary": summary})
        return rows

    def _parse_sina_hot_html(self, text: str) -> list[dict]:
        match = re.search(r"SM\s*=\s*(\{.*?\});", text, flags=re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(1))
        rows = []
        for item in data.get("data", {}).get("data", {}).get("hotList", []):
            info = item.get("info", {})
            title = _strip_html(str(info.get("title") or ""))
            if title:
                rows.append(
                    {
                        "title": title,
                        "url": f"https://so.sina.cn/search/list.d.html?keyword={quote(title)}",
                        "hotScore": info.get("hotValue"),
                    }
                )
        return rows

    def _parse_sina_news_top_text(self, text: str) -> list[dict]:
        match = re.search(r"\w+_1_data\s*=\s*(\{.*?\});", text, flags=re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(1))
        return [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "hotScore": item.get("top_num"),
            }
            for item in data.get("data", [])
            if item.get("title")
        ]

    def _loads_prefixed_json(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith(")]}'"):
            cleaned = cleaned[4:].strip()
        return json.loads(cleaned)

    def _hotrank_items_to_records(
        self,
        rows: list[dict],
        *,
        source: str,
        publisher: str,
        symbol_info: dict,
        base_url: str,
    ) -> list[dict]:
        records = []
        terms = self._relevance_terms(symbol_info)
        for row in rows:
            title = _strip_html(str(self._first_nonempty(row, HOTRANK_TITLE_KEYS) or ""))
            if not title or _is_low_quality_news(title):
                continue
            summary = _strip_html(str(self._first_nonempty(row, HOTRANK_SUMMARY_KEYS) or ""))
            if terms and not any(term in f"{title} {summary}" for term in terms):
                continue
            url = self._hotrank_item_url(row, title=title, source=source, base_url=base_url)
            records.append(
                {
                    "title": title,
                    "url": url,
                    "publish_time": self._hotrank_publish_time(row),
                    "summary": summary or title,
                    "publisher": publisher,
                    "query_provider": source,
                    "hot_score": self._first_nonempty(row, HOTRANK_SCORE_KEYS),
                }
            )
        return records

    def _hotrank_item_url(self, row: dict, *, title: str, source: str, base_url: str) -> str:
        if source == "weread":
            book_id = self._first_nonempty(row, ("bookId", "book_id"))
            if book_id:
                return f"https://weread.qq.com/web/bookDetail/{book_id}"
        if source == "wallstreetcn":
            resource_id = self._first_nonempty(row, ("resource_id", "article_id", "id"))
            if resource_id:
                return f"https://wallstreetcn.com/articles/{resource_id}"
        value = self._first_nonempty(row, HOTRANK_URL_KEYS)
        if value:
            url = str(value)
            if url.startswith("//"):
                return f"https:{url}"
            if url.startswith("/"):
                return urljoin(base_url, url)
            return url
        if source == "pengpai":
            content_id = self._first_nonempty(row, ("contId", "contid", "id", "nodeId"))
            if content_id:
                return f"https://www.thepaper.cn/newsDetail_forward_{content_id}"
        if source == "bilibili":
            bvid = self._first_nonempty(row, ("bvid", "aid"))
            if bvid:
                return f"https://www.bilibili.com/video/{bvid}"
        if source == "douyin":
            return f"https://www.douyin.com/search/{quote(title)}"
        return base_url

    def _hotrank_publish_time(self, row: dict) -> str:
        value = self._first_nonempty(row, HOTRANK_TIME_KEYS)
        if isinstance(value, int | float):
            try:
                return datetime.fromtimestamp(value).isoformat(timespec="seconds")
            except (OverflowError, OSError, ValueError):
                return date.today().isoformat()
        if value:
            return str(value)
        return date.today().isoformat()

    def _first_nonempty(self, row: dict, keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    def _dedupe_records(self, records: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for record in records:
            key = (record.get("title"), record.get("url"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped

    def _hotrank_source_url(self) -> str:
        urls = {
            "pengpai": self.pengpai_endpoint,
            "bilibili": self.bilibili_endpoint,
            "douyin": self.douyin_endpoint,
            "wallstreetcn": self.wallstreetcn_endpoint,
            "weread": self.weread_endpoint,
            "36kr": self.kr36_endpoint,
            "csdn": self.csdn_endpoint,
            "yicai": self.yicai_endpoint,
            "github": self.github_endpoint,
            "google": self.google_trends_endpoint,
            "tencent": self.tencent_endpoint,
            "sina_hot": self.sina_hot_endpoint,
            "sina_news": self.sina_news_endpoint,
        }
        return ";".join(urls[source] for source in self.hotrank_sources if source in urls)

    def _fetch_sina_roll_news(self, symbol_info: dict, query: str) -> list[dict]:
        import requests

        session = self.session_factory() if self.session_factory else requests.Session()
        session.trust_env = False
        response = session.get(
            self.sina_endpoint,
            params={
                "pageid": "384",
                "lid": "2519",
                "k": query,
                "num": str(max(self.limit, 20)),
                "page": "1",
            },
            timeout=self.timeout_seconds,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "User-Agent": "Mozilla/5.0 DandelionsInvestmentAgent/0.3",
            },
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        text = self._decode_content(response.content)
        records = self._parse_sina_roll_html(text)
        terms = self._relevance_terms(symbol_info)
        relevant = [
            item
            for item in records
            if not terms or any(term in item.get("title", "") for term in terms)
        ]
        return relevant[: self.limit]

    def _parse_sina_roll_html(self, text: str) -> list[dict]:
        records = []
        pattern = re.compile(
            r"<li>\s*<a\s+[^>]*href=[\"'](?P<url>[^\"']+)[\"'][^>]*>"
            r"(?P<title>.*?)</a>\s*</li>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(text):
            title = _strip_html(match.group("title"))
            if not title or _is_low_quality_news(title):
                continue
            url = self._canonical_sina_url(match.group("url"))
            records.append(
                {
                    "title": title,
                    "url": url,
                    "publish_time": self._date_from_url(url) or date.today().isoformat(),
                    "summary": title,
                    "publisher": "新浪财经",
                    "query_provider": "sina",
                }
            )
        return records

    def _canonical_sina_url(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.netloc == "cj.sina.cn" and parsed.path.endswith("/norm_detail"):
            nested_url = parse_qs(parsed.query).get("url", [None])[0]
            if nested_url:
                return unquote(nested_url)
        return value

    def _date_from_url(self, value: str) -> str | None:
        match = re.search(r"/(\d{4}-\d{2}-\d{2})/", value)
        if match:
            return match.group(1)
        return None

    def _relevance_terms(self, symbol_info: dict) -> list[str]:
        return [
            term
            for term in (
                str(symbol_info.get("name") or "").strip(),
                str(symbol_info.get("plain_code") or "").strip(),
            )
            if term
        ]

    def _parse_jsonp(self, value: str) -> dict:
        text = value.strip()
        start = text.find("(")
        end = text.rfind(")")
        if start >= 0 and end > start:
            text = text[start + 1 : end]
        return json.loads(text)

    def _fetch_baidu_news(self, query: str) -> list[dict]:
        import requests

        session = self.session_factory() if self.session_factory else requests.Session()
        session.trust_env = False
        params = {
            "word": query,
            "tn": "newsrss",
            "sr": "0",
            "cl": "2",
            "rn": str(self.limit),
            "ct": "0",
        }
        url = f"{self.endpoint}?{urlencode(params)}"
        response = session.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "DandelionsInvestmentAgent/0.3"},
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        return self._parse_rss(response.content)

    def _parse_rss(self, content: bytes) -> list[dict]:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return self._parse_rss_fallback(content)

        records = []
        for item in root.findall(".//item")[: self.limit]:
            title = _strip_html(self._child_text(item, "title"))
            if not title or _is_low_quality_news(title):
                continue
            records.append(
                {
                    "title": title,
                    "url": self._child_text(item, "link"),
                    "publish_time": self._child_text(item, "pubDate") or date.today().isoformat(),
                    "summary": _strip_html(self._child_text(item, "description")),
                    "publisher": self._child_text(item, "source") or "百度新闻",
                    "query_provider": self.provider,
                }
            )
        return records

    def _parse_rss_fallback(self, content: bytes) -> list[dict]:
        text = self._decode_content(content)
        records = []
        for item_text in re.findall(r"<item\b[^>]*>(.*?)</item>", text, flags=re.IGNORECASE | re.DOTALL)[
            : self.limit
        ]:
            title = _strip_html(self._tag_text(item_text, "title"))
            if not title or _is_low_quality_news(title):
                continue
            records.append(
                {
                    "title": title,
                    "url": self._tag_text(item_text, "link"),
                    "publish_time": self._tag_text(item_text, "pubDate") or date.today().isoformat(),
                    "summary": _strip_html(self._tag_text(item_text, "description")),
                    "publisher": self._tag_text(item_text, "source") or "百度新闻",
                    "query_provider": self.provider,
                }
            )
        return records

    def _decode_content(self, content: bytes) -> str:
        for encoding in ("utf-8", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")

    def _tag_text(self, item_text: str, tag: str) -> str | None:
        match = re.search(
            rf"<{tag}\b[^>]*>(.*?)</{tag}>",
            item_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        value = match.group(1).strip()
        if value.startswith("<![CDATA[") and value.endswith("]]>"):
            value = value[9:-3]
        return value.strip()

    def _child_text(self, item: ET.Element, tag: str) -> str | None:
        child = item.find(tag)
        if child is None or child.text is None:
            return None
        return child.text.strip()

    def _result(
        self,
        *,
        symbol: str,
        data: list[dict],
        dataset: str,
        source_url: str | None,
        success: bool,
        error: str | None,
        error_type: str | None,
        started: float,
    ) -> ProviderResult:
        return ProviderResult(
            provider=self.provider,
            dataset=dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data=data,
            raw={},
            metadata=ProviderMetadata(
                source_url=source_url,
                success=success,
                error=error,
                error_type=error_type,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )
