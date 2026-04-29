from datetime import date


PLACEHOLDER_CONFIDENCE = 0.25


def get_placeholder_supplemental_data(symbol: str) -> dict:
    """
    Temporary non-price research inputs.

    These values keep the MVP pipeline runnable before QMT/fundamental data is
    fully connected. They are explicitly marked as mock placeholders so reports
    and downstream guards can treat them as low-confidence evidence.
    """
    return {
        "fundamental_data": {
            "roe": 0.31,
            "gross_margin": 0.91,
            "net_profit_growth": 0.16,
            "revenue_growth": 0.15,
            "debt_ratio": 0.22,
            "operating_cashflow_quality": "good",
        },
        "valuation_data": {
            "pe_percentile": 0.62,
            "pb_percentile": 0.58,
            "dividend_yield": 0.025,
        },
        "event_data": {
            "recent_news_sentiment": "neutral_positive",
            "policy_risk": "low",
            "major_event": "无重大负面事件",
        },
        "source_metadata": {
            "fundamental_data": {
                "source": "mock_placeholder",
                "confidence": PLACEHOLDER_CONFIDENCE,
                "as_of": str(date.today()),
                "note": f"{symbol} fundamental data is placeholder data for MVP tests.",
            },
            "valuation_data": {
                "source": "mock_placeholder",
                "confidence": PLACEHOLDER_CONFIDENCE,
                "as_of": str(date.today()),
                "note": f"{symbol} valuation data is placeholder data for MVP tests.",
            },
            "event_data": {
                "source": "mock_placeholder",
                "confidence": PLACEHOLDER_CONFIDENCE,
                "as_of": str(date.today()),
                "note": f"{symbol} event data is placeholder data for MVP tests.",
            },
        },
    }


def merge_supplemental_data(asset_data: dict) -> dict:
    supplemental = get_placeholder_supplemental_data(asset_data["symbol"])
    merged = dict(asset_data)

    source_metadata = dict(merged.get("source_metadata", {}))
    source_metadata.update(supplemental["source_metadata"])

    for key in ("fundamental_data", "valuation_data", "event_data"):
        merged.setdefault(key, supplemental[key])

    merged["source_metadata"] = source_metadata
    return merged
