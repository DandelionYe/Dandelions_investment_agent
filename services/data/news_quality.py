"""网页新闻/舆情长期质量验收模块。

对 web news provider 的结果做离线质量评价，不发真实请求。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _normalize_title(title: str) -> str:
    """归一化标题用于去重：去除空白、标点、特殊字符。"""
    t = re.sub(r"[\s　]+", "", title)
    t = re.sub(r"[，。！？、；：“”‘’（）【】《》\-—…\xb7.,!?;:'\"()\[\]<>]", "", t)
    return t.lower()


def dedupe_news_items(items: list[dict]) -> list[dict]:
    """去重新闻列表。

    规则：
    - URL 完全相同 → 保留第一条。
    - 标题归一化后相同 → 保留第一条。
    """
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[dict] = []
    for item in items:
        url = item.get("url", "")
        title = item.get("title", "")
        norm_title = _normalize_title(title)
        if url and url in seen_urls:
            continue
        if norm_title and norm_title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if norm_title:
            seen_titles.add(norm_title)
        result.append(item)
    return result


def score_news_relevance(item: dict, symbol_info: dict) -> float:
    """评估单条新闻与标的的相关性。

    Returns
    -------
    float
        0.0 ~ 1.0 的相关性分数。
    """
    title = item.get("title", "")
    summary = item.get("summary", "")
    text = f"{title} {summary}".lower()

    company_name = (symbol_info.get("name") or "").lower()
    plain_code = (symbol_info.get("plain_code") or "").lower()
    normalized_symbol = (symbol_info.get("normalized_symbol") or "").lower()
    symbol = (symbol_info.get("symbol") or "").lower()

    score = 0.0

    # 公司名匹配
    if company_name and company_name in text:
        score += 0.4

    # 代码匹配
    if plain_code and plain_code in text:
        score += 0.3
    elif normalized_symbol and normalized_symbol in text:
        score += 0.3
    elif symbol and symbol in text:
        score += 0.2

    # 标题长度合理性
    if len(title) >= 8:
        score += 0.1

    # 负面模式扣分
    low_quality_patterns = [
        "福利", "报名", "推广", "广告", "充值", "优惠券",
        "抽奖", "免费领", "秒杀", "薅羊毛", "娱乐",
        "八卦", "明星", "减肥", "丰胸", "彩票",
    ]
    for pat in low_quality_patterns:
        if pat in text:
            score -= 0.3
            break

    return max(0.0, min(1.0, score))


def classify_news_quality(item: dict, symbol_info: dict) -> dict:
    """对单条新闻进行质量分类。

    Returns
    -------
    dict
        {
            "relevance": float,
            "quality_tier": "high" | "medium" | "low",
            "is_relevant": bool,
            "reasons": list[str],
        }
    """
    relevance = score_news_relevance(item, symbol_info)
    reasons: list[str] = []

    title = item.get("title", "")
    if len(title) < 6:
        reasons.append("标题过短")
        relevance = min(relevance, 0.2)

    # 纯泛财经热榜（无公司信息）
    hot_score = item.get("hot_score")
    if hot_score and relevance < 0.2:
        reasons.append("泛财经热榜，与标的无关")

    if relevance >= 0.4:
        quality_tier = "high"
    elif relevance >= 0.2:
        quality_tier = "medium"
    else:
        quality_tier = "low"
        if not reasons:
            reasons.append("相关性不足")

    return {
        "relevance": round(relevance, 3),
        "quality_tier": quality_tier,
        "is_relevant": relevance >= 0.2,
        "reasons": reasons,
    }


def evaluate_news_provider_result(
    result: Any,
    symbol_info: dict,
) -> dict:
    """评估 provider 返回结果的质量。

    Parameters
    ----------
    result : ProviderResult | dict
        Provider 返回的结果，需要有 data/metadata 字段。
    symbol_info : dict
        标的信息，包含 name/plain_code/normalized_symbol/symbol。

    Returns
    -------
    dict
        质量评估结果。
    """
    # 兼容 ProviderResult 和 dict
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if hasattr(result, "data"):
        data = result.data if isinstance(result.data, list) else [result.data]
        metadata = result.metadata
        success = metadata.success if hasattr(metadata, "success") else True
        error = metadata.error if hasattr(metadata, "error") else None
        error_type = metadata.error_type if hasattr(metadata, "error_type") else None
    elif isinstance(result, dict):
        data = result.get("data", [])
        if isinstance(data, dict):
            data = [data]
        metadata = result.get("metadata", {})
        success = metadata.get("success", True) if isinstance(metadata, dict) else True
        error = metadata.get("error") if isinstance(metadata, dict) else None
        error_type = metadata.get("error_type") if isinstance(metadata, dict) else None
    else:
        return {"success": False, "error": "unknown result type", "total": 0}

    if not success:
        return {
            "success": False,
            "error": error,
            "error_type": error_type,
            "total": 0,
            "deduped_total": 0,
            "relevant_count": 0,
            "low_quality_count": 0,
            "source_counts": {},
            "failure_count": 1,
            "warnings": [f"provider 失败: {error_type or 'unknown'}"],
        }

    items = data if isinstance(data, list) else []
    deduped = dedupe_news_items(items)

    classified = [classify_news_quality(item, symbol_info) for item in deduped]
    relevant_count = sum(1 for c in classified if c["is_relevant"])
    low_quality_count = sum(1 for c in classified if c["quality_tier"] == "low")

    source_counts: dict[str, int] = Counter()
    for item in deduped:
        src = item.get("query_provider", item.get("source", "unknown"))
        source_counts[str(src)] = source_counts.get(str(src), 0) + 1

    return {
        "success": True,
        "total": len(items),
        "deduped_total": len(deduped),
        "relevant_count": relevant_count,
        "low_quality_count": low_quality_count,
        "source_counts": dict(source_counts),
        "failure_count": 0,
        "warnings": [],
    }


def summarize_news_quality(evaluations: list[dict]) -> dict:
    """汇总多次评估结果。

    Returns
    -------
    dict
        {
            "total_evaluations": int,
            "total_items": int,
            "total_deduped": int,
            "total_relevant": int,
            "total_low_quality": int,
            "total_failures": int,
            "overall_relevance_rate": float,
            "source_counts": dict,
            "warnings": list[str],
        }
    """
    total_items = 0
    total_deduped = 0
    total_relevant = 0
    total_low_quality = 0
    total_failures = 0
    all_sources: dict[str, int] = {}
    all_warnings: list[str] = []

    for ev in evaluations:
        total_items += ev.get("total", 0)
        total_deduped += ev.get("deduped_total", 0)
        total_relevant += ev.get("relevant_count", 0)
        total_low_quality += ev.get("low_quality_count", 0)
        total_failures += ev.get("failure_count", 0)
        for src, cnt in ev.get("source_counts", {}).items():
            all_sources[src] = all_sources.get(src, 0) + cnt
        all_warnings.extend(ev.get("warnings", []))

    relevance_rate = total_relevant / total_deduped if total_deduped > 0 else 0.0

    return {
        "total_evaluations": len(evaluations),
        "total_items": total_items,
        "total_deduped": total_deduped,
        "total_relevant": total_relevant,
        "total_low_quality": total_low_quality,
        "total_failures": total_failures,
        "overall_relevance_rate": round(relevance_rate, 4),
        "source_counts": all_sources,
        "warnings": all_warnings,
    }
