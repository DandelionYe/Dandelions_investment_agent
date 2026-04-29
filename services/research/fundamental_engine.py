from datetime import date

from services.data.supplemental_provider import get_placeholder_supplemental_data


class FundamentalService:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        supplemental = get_placeholder_supplemental_data(symbol)
        fundamental_data = dict(asset_data.get("fundamental_data") or supplemental["fundamental_data"])
        metadata = dict(
            asset_data.get("source_metadata", {}).get("fundamental_data")
            or supplemental["source_metadata"]["fundamental_data"]
        )

        analysis = self._analyze(fundamental_data, metadata)

        return {
            "data": {
                "fundamental_data": fundamental_data,
                "fundamental_analysis": analysis,
            },
            "source_metadata": {"fundamental_data": metadata},
            "provider_run_log": [
                {
                    "provider": metadata.get("source", "unknown"),
                    "dataset": "fundamental_data",
                    "symbol": symbol,
                    "status": "placeholder" if metadata.get("source") == "mock_placeholder" else "success",
                    "rows": 1 if fundamental_data else 0,
                    "error": None,
                    "as_of": str(date.today()),
                }
            ],
        }

    def _analyze(self, data: dict, metadata: dict) -> dict:
        roe = data.get("roe")
        net_margin = data.get("net_margin")
        gross_margin = data.get("gross_margin")
        net_profit_growth = data.get("net_profit_growth")
        revenue_growth = data.get("revenue_growth")
        cashflow_quality = data.get("operating_cashflow_quality")
        debt_ratio = data.get("debt_ratio")
        warnings = []
        key_points = []

        if metadata.get("source") == "mock_placeholder":
            warnings.append("基本面数据仍为 placeholder，需要接入真实财务数据验证。")

        quality_label = "low"
        if roe is not None and roe >= 0.15 and (net_margin is None or net_margin > 0.10):
            quality_label = "high"
            key_points.append("ROE 高于 15%，盈利能力较强。")
        elif roe is not None and roe >= 0.08:
            quality_label = "medium"

        if gross_margin is not None and gross_margin > 0.4:
            key_points.append("毛利率处于较高水平。")

        growth_label = "stable"
        if (revenue_growth is not None and revenue_growth < 0) or (
            net_profit_growth is not None and net_profit_growth < 0
        ):
            growth_label = "negative"
            warnings.append("收入或净利润增速为负。")
        elif (revenue_growth or 0) > 0 and (net_profit_growth or 0) > 0:
            growth_label = "moderate_growth"
            key_points.append("收入和净利润保持正增长。")

        cashflow_label = "unknown"
        if isinstance(cashflow_quality, (int, float)):
            cashflow_label = "good" if cashflow_quality >= 1.0 else "weak"
        elif cashflow_quality == "good":
            cashflow_label = "good"

        leverage_label = "normal"
        if debt_ratio is not None and debt_ratio > 0.70:
            leverage_label = "high"
            warnings.append("非金融企业资产负债率偏高。")

        return {
            "quality_label": quality_label,
            "growth_label": growth_label,
            "cashflow_label": cashflow_label,
            "leverage_label": leverage_label,
            "key_points": key_points,
            "warnings": warnings,
        }
