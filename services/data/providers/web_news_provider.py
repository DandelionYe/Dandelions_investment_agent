import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

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


class WebNewsProvider:
    """Domestic web news provider backed by Baidu News RSS.

    News crawlers in this project must not inherit user VPN/proxy settings:
    several domestic news endpoints only work reliably through direct CN
    network access. The provider therefore disables proxy environment variables
    and also makes the requests session ignore environment proxies.
    """

    provider = "web_news"
    dataset = "baidu_news_rss"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        endpoint: str | None = None,
        limit: int | None = None,
        timeout_seconds: int | None = None,
        force_no_proxy: bool | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self.enabled = _env_bool("WEB_NEWS_ENABLED", False) if enabled is None else enabled
        self.endpoint = endpoint or os.getenv("WEB_NEWS_BAIDU_RSS_URL", "https://news.baidu.com/ns")
        self.limit = limit or _env_int("WEB_NEWS_LIMIT", 10)
        self.timeout_seconds = timeout_seconds or _env_int("WEB_NEWS_TIMEOUT_SECONDS", 8)
        self.force_no_proxy = (
            _env_bool("WEB_NEWS_FORCE_NO_PROXY", True)
            if force_no_proxy is None
            else force_no_proxy
        )
        self.session_factory = session_factory

    def fetch_events(self, symbol_info: dict, lookback_days: int = 14) -> ProviderResult:
        started = perf_counter()
        symbol = symbol_info.get("normalized_symbol") or symbol_info.get("qmt_code") or ""

        if not self.enabled:
            error = ProviderUnavailableError("web news provider is disabled")
            return self._result(
                symbol=symbol,
                data=[],
                success=False,
                error=str(error),
                error_type=error.error_type,
                started=started,
            )

        try:
            if self.force_no_proxy:
                disable_proxy_for_current_process()

            query = self._build_query(symbol_info)
            records = self._fetch_baidu_news(query)
            return self._result(
                symbol=symbol,
                data=records,
                success=len(records) > 0,
                error=None if records else "web news provider returned no records",
                error_type=None if records else ProviderUnavailableError.error_type,
                started=started,
            )
        except Exception as exc:
            return self._result(
                symbol=symbol,
                data=[],
                success=False,
                error=str(exc),
                error_type=get_provider_error_type(exc),
                started=started,
            )

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
        root = ET.fromstring(content)
        records = []
        for item in root.findall(".//item")[: self.limit]:
            title = _strip_html(self._child_text(item, "title"))
            if not title:
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
        success: bool,
        error: str | None,
        error_type: str | None,
        started: float,
    ) -> ProviderResult:
        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=str(date.today()),
            data=data,
            raw={},
            metadata=ProviderMetadata(
                source_url=self.endpoint,
                success=success,
                error=error,
                error_type=error_type,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )
