from services.data.quality.confidence_engine import ConfidenceEngine


class DataQualityService:
    def __init__(self):
        self.confidence_engine = ConfidenceEngine()

    def build_report(self, asset_data: dict) -> dict:
        source_metadata = asset_data.get("source_metadata", {})
        asset_type = asset_data.get("asset_type", "stock")
        warnings = list(asset_data.get("data_warnings", []))
        blocking_issues: list[str] = []
        field_quality: dict[str, dict] = {}
        has_placeholder = False

        required_sections = ["price_data", "fundamental_data", "valuation_data", "event_data"]
        if asset_type == "etf":
            required_sections.append("etf_data")

        for section in required_sections:
            metadata = source_metadata.get(section, {})
            source = metadata.get("source")
            available = bool(asset_data.get(section))
            confidence = metadata.get("confidence")
            if confidence is None:
                confidence = self.confidence_engine.field_confidence(
                    source=source,
                    freshness_score=1.0 if available else 0.0,
                    completeness_score=1.0 if available else 0.0,
                    cross_source_score=0.5,
                )

            if source == "mock_placeholder":
                has_placeholder = True
                warnings.append(f"{section} 仍使用 placeholder，占位数据不能作为强证据。")

            field_quality[section] = {
                "available": available,
                "source": source or "unknown",
                "confidence": round(float(confidence), 4),
                "freshness": "unknown" if source == "mock_placeholder" else "fresh",
            }

        if not asset_data.get("price_data"):
            blocking_issues.append("price_data 缺失。")
        if asset_type == "stock" and source_metadata.get("fundamental_data", {}).get("source") == "mock_placeholder":
            blocking_issues.append("股票 fundamental_data 仍为 placeholder。")
        valuation_data = asset_data.get("valuation_data", {})
        if not valuation_data:
            blocking_issues.append("valuation_data 缺失。")
        elif not any(valuation_data.get(field) is not None for field in ("pe_ttm", "pb_mrq", "market_cap")):
            blocking_issues.append("valuation_data 核心字段全部缺失。")
        if source_metadata.get("event_data", {}).get("source") == "mock_placeholder":
            warnings.append("event_data 未能确认近90日真实公告风险，当前为 placeholder。")

        event_data = asset_data.get("event_data", {})
        if event_data.get("event_summary", {}).get("critical_count", 0) > 0:
            blocking_issues.append("存在 critical 事件。")

        confidence_values = [
            item["confidence"]
            for item in field_quality.values()
            if item.get("available")
        ]
        overall_confidence = (
            round(sum(confidence_values) / len(confidence_values), 4)
            if confidence_values
            else 0.0
        )

        return {
            "overall_confidence": overall_confidence,
            "has_placeholder": has_placeholder,
            "blocking_issues": blocking_issues,
            "warnings": list(dict.fromkeys(warnings)),
            "field_quality": field_quality,
        }
