SOURCE_SCORES = {
    "qmt": 0.95,
    "tushare": 0.90,
    "cninfo": 0.95,
    "sse": 0.95,
    "szse": 0.95,
    "akshare": 0.75,
    "eastmoney": 0.75,
    "web_news": 0.55,
    "mock": 0.20,
    "mock_placeholder": 0.25,
}


def get_source_score(source: str | None) -> float:
    if not source:
        return 0.0
    return SOURCE_SCORES.get(str(source).lower(), 0.5)
