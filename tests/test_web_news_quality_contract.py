"""网页新闻/舆情质量验收测试。

覆盖：
- 去重、相关性、低质量过滤、失败降级都被测试覆盖。
- web news quality script 离线运行成功。
"""

import json
from pathlib import Path

from services.data.news_quality import (
    classify_news_quality,
    dedupe_news_items,
    evaluate_news_provider_result,
    score_news_relevance,
    summarize_news_quality,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "web_news_quality_samples.json"


def _load_samples():
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["samples"]


class TestDedupeNewsItems:

    def test_url_dedup(self):
        items = [
            {"title": "消息A", "url": "https://example.com/1"},
            {"title": "消息B", "url": "https://example.com/1"},
        ]
        result = dedupe_news_items(items)
        assert len(result) == 1
        assert result[0]["title"] == "消息A"

    def test_title_dedup(self):
        items = [
            {"title": "茅台集团宣布新战略", "url": "https://a.com/1"},
            {"title": "茅台集团宣布新战略", "url": "https://b.com/2"},
        ]
        result = dedupe_news_items(items)
        assert len(result) == 1

    def test_no_dedup_different(self):
        items = [
            {"title": "消息A", "url": "https://a.com/1"},
            {"title": "消息B", "url": "https://b.com/2"},
        ]
        result = dedupe_news_items(items)
        assert len(result) == 2

    def test_empty_list(self):
        assert dedupe_news_items([]) == []


class TestScoreNewsRelevance:

    def test_company_name_match(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "贵州茅台一季度净利润增长", "summary": ""}
        score = score_news_relevance(item, symbol_info)
        assert score >= 0.4

    def test_code_match(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "600519行情分析", "summary": ""}
        score = score_news_relevance(item, symbol_info)
        assert score >= 0.3

    def test_irrelevant(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "今日A股大盘指数大涨3%", "summary": ""}
        score = score_news_relevance(item, symbol_info)
        assert score < 0.4

    def test_low_quality_pattern(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "茅台福利大放送，免费领取品鉴酒", "summary": ""}
        score = score_news_relevance(item, symbol_info)
        assert score < 0.3


class TestClassifyNewsQuality:

    def test_high_quality(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "贵州茅台一季度净利润同比增长15%", "summary": ""}
        result = classify_news_quality(item, symbol_info)
        assert result["quality_tier"] == "high"
        assert result["is_relevant"] is True

    def test_low_quality_promotion(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "茅台福利大放送，免费领取品鉴酒", "summary": ""}
        result = classify_news_quality(item, symbol_info)
        assert result["quality_tier"] == "low"

    def test_short_title(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        item = {"title": "茅台", "summary": ""}
        result = classify_news_quality(item, symbol_info)
        assert "标题过短" in result["reasons"]


class TestEvaluateNewsProviderResult:

    def test_relevant_company_news(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "relevant_company_news")
        result = evaluate_news_provider_result(
            {"data": sample["items"], "metadata": {"success": True}},
            sample["symbol_info"],
        )
        assert result["success"] is True
        assert result["relevant_count"] >= sample["expected"]["relevant_count_min"]
        assert result["deduped_total"] == sample["expected"]["deduped_total"]

    def test_duplicate_title_deduped(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "duplicate_title_news")
        result = evaluate_news_provider_result(
            {"data": sample["items"], "metadata": {"success": True}},
            sample["symbol_info"],
        )
        assert result["deduped_total"] == sample["expected"]["deduped_total"]

    def test_duplicate_url_deduped(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "duplicate_url_news")
        result = evaluate_news_provider_result(
            {"data": sample["items"], "metadata": {"success": True}},
            sample["symbol_info"],
        )
        assert result["deduped_total"] == sample["expected"]["deduped_total"]

    def test_low_quality_promotion_detected(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "low_quality_promotion")
        result = evaluate_news_provider_result(
            {"data": sample["items"], "metadata": {"success": True}},
            sample["symbol_info"],
        )
        assert result["low_quality_count"] >= sample["expected"]["low_quality_count_min"]

    def test_irrelevant_hotrank(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "irrelevant_hotrank")
        result = evaluate_news_provider_result(
            {"data": sample["items"], "metadata": {"success": True}},
            sample["symbol_info"],
        )
        assert result["deduped_total"] == sample["expected"]["deduped_total"]

    def test_provider_unavailable(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "provider_unavailable")
        meta = sample["provider_metadata"]
        result = evaluate_news_provider_result(
            {"data": [], "metadata": meta},
            sample["symbol_info"],
        )
        assert result["success"] is False
        assert result["failure_count"] == 1
        assert len(result["warnings"]) > 0

    def test_provider_timeout(self):
        samples = _load_samples()
        sample = next(s for s in samples if s["id"] == "provider_timeout")
        meta = sample["provider_metadata"]
        result = evaluate_news_provider_result(
            {"data": [], "metadata": meta},
            sample["symbol_info"],
        )
        assert result["success"] is False
        assert result["failure_count"] == 1


class TestSummarizeNewsQuality:

    def test_summarize_multiple(self):
        symbol_info = {"name": "贵州茅台", "plain_code": "600519", "normalized_symbol": "600519.sh"}
        eval1 = evaluate_news_provider_result(
            {"data": [{"title": "贵州茅台一季度净利润增长", "url": "https://a.com/1", "query_provider": "eastmoney"}],
             "metadata": {"success": True}}, symbol_info)
        eval2 = evaluate_news_provider_result(
            {"data": [], "metadata": {"success": False, "error": "timeout", "error_type": "provider_unavailable"}},
            symbol_info)
        summary = summarize_news_quality([eval1, eval2])
        assert summary["total_evaluations"] == 2
        assert summary["total_failures"] == 1
        assert summary["total_relevant"] >= 1

    def test_empty_evaluations(self):
        summary = summarize_news_quality([])
        assert summary["total_evaluations"] == 0
        assert summary["overall_relevance_rate"] == 0.0


class TestFixtureContract:

    def test_fixture_loads(self):
        samples = _load_samples()
        assert len(samples) == 7

    def test_each_sample_has_expected(self):
        samples = _load_samples()
        for s in samples:
            assert "id" in s
            assert "items" in s
            assert "symbol_info" in s
            assert "expected" in s
