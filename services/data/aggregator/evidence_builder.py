from datetime import date
from typing import Any


def _format_percent(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)


def _format_number(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_integer(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


class EvidenceBuilder:
    def build(self, asset_data: dict) -> dict:
        symbol = asset_data["symbol"]
        as_of = asset_data.get("as_of", str(date.today()))
        items = []

        self._add_price_items(items, asset_data)
        if asset_data.get("asset_type") == "etf":
            self._add_etf_items(items, asset_data)
        else:
            self._add_fundamental_items(items, asset_data)
            self._add_valuation_items(items, asset_data)
        self._add_event_items(items, asset_data)

        return {
            "bundle_id": f"evb_{symbol.replace('.', '_')}_{as_of.replace('-', '')}",
            "symbol": symbol,
            "as_of": as_of,
            "items": items,
        }

    def _metadata(self, asset_data: dict, section: str) -> dict:
        return asset_data.get("source_metadata", {}).get(section, {})

    def _append(
        self,
        items: list[dict],
        asset_data: dict,
        section: str,
        evidence_id: str,
        category: str,
        title: str,
        value: Any,
        display_value: str,
        source: str | None = None,
    ) -> None:
        metadata = self._metadata(asset_data, section)
        items.append(
            {
                "evidence_id": evidence_id,
                "category": category,
                "title": title,
                "value": value,
                "display_value": display_value,
                "source": source or metadata.get("source", "unknown"),
                "source_date": metadata.get("as_of", asset_data.get("as_of")),
                "confidence": metadata.get("confidence", 0.0),
            }
        )

    def _add_price_items(self, items: list[dict], asset_data: dict) -> None:
        price = asset_data.get("price_data", {})
        self._append(
            items,
            asset_data,
            "price_data",
            "ev_price_close",
            "price",
            "最新收盘价",
            price.get("close"),
            str(price.get("close", "暂无")),
        )
        self._append(
            items,
            asset_data,
            "price_data",
            "ev_price_change_60d",
            "price",
            "近60日涨跌幅",
            price.get("change_60d"),
            _format_percent(price.get("change_60d")),
        )

    def _add_fundamental_items(self, items: list[dict], asset_data: dict) -> None:
        fundamental = asset_data.get("fundamental_data", {})
        for field, title in {
            "roe": "ROE",
            "gross_margin": "毛利率",
            "revenue_growth": "营收同比增速",
            "net_profit_growth": "净利润同比增速",
            "debt_ratio": "资产负债率",
        }.items():
            self._append(
                items,
                asset_data,
                "fundamental_data",
                f"ev_fin_{field}",
                "fundamental",
                title,
                fundamental.get(field),
                _format_percent(fundamental.get(field)),
            )

    def _add_valuation_items(self, items: list[dict], asset_data: dict) -> None:
        valuation = asset_data.get("valuation_data", {})
        for field, title in {
            "pe_ttm": "PE TTM",
            "pb_mrq": "PB MRQ",
            "market_cap": "总市值",
            "pe_percentile": "PE 历史分位",
            "pb_percentile": "PB 历史分位",
            "dividend_yield": "股息率",
        }.items():
            self._append(
                items,
                asset_data,
                "valuation_data",
                f"ev_val_{field}",
                "valuation",
                title,
                valuation.get(field),
                _format_percent(valuation.get(field))
                if field in {"pe_percentile", "pb_percentile", "dividend_yield"}
                else _format_number(valuation.get(field)),
            )

        industry_source = valuation.get("industry_valuation_source")
        industry_fields = {
            "industry_name": ("申万行业", str),
            "industry_peer_count": ("行业样本数", _format_integer),
            "industry_valid_peer_count": ("行业有效估值样本数", _format_integer),
            "industry_valid_peer_count_pe": ("行业 PE 有效样本数", _format_integer),
            "industry_valid_peer_count_pb": ("行业 PB 有效样本数", _format_integer),
            "industry_valid_peer_count_ps": ("行业 PS 有效样本数", _format_integer),
            "industry_pe_percentile": ("PE 行业分位", _format_percent),
            "industry_pb_percentile": ("PB 行业分位", _format_percent),
            "industry_ps_percentile": ("PS 行业分位", _format_percent),
            "industry_valuation_label": ("行业估值标签", str),
        }
        for field, (title, formatter) in industry_fields.items():
            value = valuation.get(field)
            if value in (None, ""):
                continue
            self._append(
                items,
                asset_data,
                "valuation_data",
                f"ev_val_{field}",
                "valuation",
                title,
                value,
                formatter(value),
                source=industry_source,
            )

    def _add_etf_items(self, items: list[dict], asset_data: dict) -> None:
        etf_data = asset_data.get("etf_data", {})
        for field, title in {
            "market_price": "ETF 市价",
            "premium_discount": "折溢价",
            "avg_turnover_20d": "20日平均成交额",
            "fund_size": "基金规模",
        }.items():
            self._append(
                items,
                asset_data,
                "etf_data",
                f"ev_etf_{field}",
                "etf",
                title,
                etf_data.get(field),
                _format_percent(etf_data.get(field))
                if field == "premium_discount"
                else _format_number(etf_data.get(field)),
            )

    def _add_event_items(self, items: list[dict], asset_data: dict) -> None:
        event = asset_data.get("event_data", {})
        self._append(
            items,
            asset_data,
            "event_data",
            "ev_event_major_event",
            "event",
            "重大事件摘要",
            event.get("major_event"),
            str(event.get("major_event", "暂无")),
        )
