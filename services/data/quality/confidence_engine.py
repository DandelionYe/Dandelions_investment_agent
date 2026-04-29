from services.data.source_registry import get_source_score


class ConfidenceEngine:
    def field_confidence(
        self,
        source: str | None,
        freshness_score: float = 0.5,
        completeness_score: float = 0.5,
        cross_source_score: float = 0.5,
    ) -> float:
        score = (
            get_source_score(source) * 0.40
            + freshness_score * 0.25
            + completeness_score * 0.20
            + cross_source_score * 0.15
        )
        return round(max(0.0, min(1.0, score)), 4)
