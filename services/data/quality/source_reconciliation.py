from typing import Any


def _diff_pct(a: float, b: float) -> float | None:
    if a in (None, 0) or b in (None, 0):
        return None
    return abs(float(a) - float(b)) / abs(float(a))


class SourceReconciliation:
    # ── price ──────────────────────────────────────────────

    def compare_price_close(
        self,
        primary_source: str,
        primary_close: float | None,
        fallback_source: str,
        fallback_close: float | None,
    ) -> dict:
        if primary_close in (None, 0) or fallback_close in (None, 0):
            return {"cross_source_verified": False, "warnings": [], "blocking_issues": []}

        diff = _diff_pct(float(primary_close), float(fallback_close))
        if diff is None:
            return {"cross_source_verified": False, "warnings": [], "blocking_issues": []}

        if diff <= 0.01:
            return {"cross_source_verified": True, "warnings": [], "blocking_issues": []}
        if diff <= 0.05:
            return {
                "cross_source_verified": False,
                "warnings": [
                    f"{primary_source} 与 {fallback_source} 收盘价差异为 {diff:.2%}。"
                ],
                "blocking_issues": [],
            }
        return {
            "cross_source_verified": False,
            "warnings": [],
            "blocking_issues": [
                f"{primary_source} 与 {fallback_source} 收盘价差异超过 5%。"
            ],
        }

    # ── financial ──────────────────────────────────────────

    def compare_fundamental(
        self,
        primary_source: str,
        primary_fields: dict[str, float | None],
        fallback_source: str,
        fallback_fields: dict[str, float | None],
    ) -> dict:
        """Compare key fundamental fields across sources."""
        warnings: list[str] = []
        confidence_discount = 0.0
        compared = 0

        for field, label in {
            "roe": "ROE",
            "net_profit_growth": "净利润同比增速",
            "revenue_growth": "营收同比增速",
            "gross_margin": "毛利率",
        }.items():
            primary_val = primary_fields.get(field)
            fallback_val = fallback_fields.get(field)
            diff = _diff_pct(primary_val, fallback_val)
            if diff is None:
                continue
            compared += 1
            if diff > 0.10:
                warnings.append(
                    f"{primary_source} 与 {fallback_source} 的{label}差异为 {diff:.2%}。"
                )
                confidence_discount = max(confidence_discount, 0.15)

        return {
            "cross_source_verified": compared > 0 and len(warnings) == 0,
            "warnings": warnings,
            "confidence_discount": confidence_discount,
            "fields_compared": compared,
        }

    # ── valuation ──────────────────────────────────────────

    def compare_valuation(
        self,
        primary_source: str,
        primary_fields: dict[str, float | None],
        fallback_source: str,
        fallback_fields: dict[str, float | None],
    ) -> dict:
        """Compare key valuation fields across sources."""
        warnings: list[str] = []
        confidence_discount = 0.0
        compared = 0

        for field, label in {
            "pe_ttm": "PE TTM",
            "pb_mrq": "PB MRQ",
            "ps_ttm": "PS TTM",
        }.items():
            primary_val = primary_fields.get(field)
            fallback_val = fallback_fields.get(field)
            diff = _diff_pct(primary_val, fallback_val)
            if diff is None:
                continue
            compared += 1
            if diff > 0.15:
                warnings.append(
                    f"{primary_source} 与 {fallback_source} 的{label}差异为 {diff:.2%}。"
                )
                confidence_discount = max(confidence_discount, 0.12)

        return {
            "cross_source_verified": compared > 0 and len(warnings) == 0,
            "warnings": warnings,
            "confidence_discount": confidence_discount,
            "fields_compared": compared,
        }

    # ── event ──────────────────────────────────────────────

    def resolve_event_conflict(
        self,
        official_events: list[dict],
        news_events: list[dict],
    ) -> dict:
        """
        Resolve conflicts between official announcements and web news.

        Rules:
        - Official announcements always take priority over news.
        - News that reports the same event as an announcement is dropped.
        - Negative news without official confirmation is kept but capped
          at medium severity with neutral_negative sentiment.
        """
        warnings: list[str] = []
        resolved_events: list[dict] = list(official_events)

        for news in news_events:
            title = str(news.get("title", ""))
            # check if any official event confirms this news
            matched = any(
                any(keyword in title for keyword in off.get("keywords", []))
                or any(keyword in str(off.get("title", "")) for keyword in news.get("keywords", []))
                for off in official_events
            )
            if matched:
                continue

            if news.get("sentiment") in {"negative", "neutral_negative"} and news.get(
                "source_type"
            ) in {"web_news", "media_news"}:
                warnings.append(
                    f"媒体负面传闻「{title}」未经官方公告确认，已降级为 neutral_negative。"
                )
                news["sentiment"] = "neutral_negative"
                news["severity"] = min(
                    {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(
                        str(news.get("severity")), 1
                    ),
                    1,
                )
                severity_map = {0: "low", 1: "medium", 2: "high", 3: "critical"}
                news["severity"] = severity_map.get(
                    {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(
                        str(news.get("severity")), 1
                    ),
                    "medium",
                )
                news["summary"] = f"媒体报道「{title}」，需等待公司公告确认。"

            resolved_events.append(news)

        return {
            "events": resolved_events,
            "warnings": warnings,
            "official_count": len(official_events),
            "news_count": len(news_events),
        }
