class SourceReconciliation:
    def compare_price_close(
        self,
        primary_source: str,
        primary_close: float | None,
        fallback_source: str,
        fallback_close: float | None,
    ) -> dict:
        if primary_close in (None, 0) or fallback_close in (None, 0):
            return {"cross_source_verified": False, "warnings": [], "blocking_issues": []}

        diff = abs(float(primary_close) - float(fallback_close)) / abs(float(primary_close))

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
