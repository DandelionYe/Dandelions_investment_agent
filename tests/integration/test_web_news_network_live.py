"""Opt-in live smoke test for domestic web news fetching."""

import os

import pytest

from services.data.normalizers.event_normalizer import EventNormalizer
from services.data.providers.web_news_provider import WebNewsProvider


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.network
def test_web_news_can_fetch_domestic_news_without_proxy(require_web_news_network):
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"

    provider = WebNewsProvider(
        enabled=True,
        force_no_proxy=True,
        limit=5,
        timeout_seconds=12,
    )
    result = provider.fetch_events(
        {
            "normalized_symbol": "600519.SH",
            "plain_code": "600519",
            "name": "贵州茅台",
            "asset_type": "stock",
        }
    )

    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["NO_PROXY"] == "*"
    assert result.metadata.success is True, result.metadata.error
    assert result.provider == "web_news"
    assert result.dataset in {
        "eastmoney_stock_news",
        "sina_finance_roll",
        "xinhuanet_finance_latest",
        "hotrank_public_opinion",
        "baidu_news_rss",
    }
    assert result.data
    assert result.data[0]["title"]
    assert result.data[0]["url"]

    events = EventNormalizer().normalize_web_news(result.to_dict(), "600519.SH")

    assert events
    assert events[0]["source"] == "web_news"
    assert events[0]["source_type"] == "web_news"
    assert events[0]["relevance"] <= 0.62
