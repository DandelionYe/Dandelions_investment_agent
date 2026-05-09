from datetime import date
from typing import Any

from services.data.normalizers.common import _to_float, _first_present, _ratio as _to_ratio


def _to_qmt_percent_ratio(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if abs(number) <= 0.2:
        return number
    return number / 100


def _annualize_statement_amount(value: float | None, report_period: Any) -> float | None:
    if value is None:
        return None
    period = str(report_period or "")
    if len(period) < 6:
        return value
    month = period[4:6]
    factors = {"03": 4.0, "06": 2.0, "09": 4.0 / 3.0, "12": 1.0}
    return value * factors.get(month, 1.0)


def _latest_record(records: list[dict]) -> dict:
    if not records:
        return {}

    def key(row: dict) -> tuple[str, str]:
        report_period = str(_first_present(row, REPORT_PERIOD_FIELDS) or "")
        ann_date = str(_first_present(row, ANN_DATE_FIELDS) or "")
        return report_period, ann_date

    return sorted(records, key=key, reverse=True)[0]


REPORT_PERIOD_FIELDS = ["m_timetag", "endDate", "end_date", "report_date", "REPORT_DATE", "报告期"]
ANN_DATE_FIELDS = ["m_anntime", "declareDate", "ann_date", "ANN_DATE", "公告日期", "披露日期"]

REVENUE_FIELDS = ["营业总收入", "营业收入", "tot_oper_rev", "total_revenue", "oper_rev", "revenue", "revenue_inc"]
NET_PROFIT_FIELDS = [
    "归属母公司股东的净利润",
    "归属于母公司所有者的净利润",
    "净利润",
    "net_profit_excl_min_int_inc",
    "net_profit_incl_min_int_inc_after",
    "net_profit_incl_min_int_inc",
    "net_profit",
    "n_income_attr_p",
]
OPERATING_CASHFLOW_FIELDS = [
    "经营活动产生的现金流量净额",
    "经营现金流量净额",
    "net_cash_flows_oper_act",
    "net_operate_cash_flow",
]
TOTAL_ASSETS_FIELDS = ["资产总计", "资产合计", "tot_assets", "total_assets"]
TOTAL_LIABILITIES_FIELDS = ["负债合计", "负债总计", "tot_liab", "total_liab", "total_liabilities"]


class FundamentalNormalizer:
    def normalize_qmt(self, provider_result: dict) -> dict:
        tables = provider_result.get("data", {})
        pershare = _latest_record(tables.get("PershareIndex", []))
        income = _latest_record(tables.get("Income", []))
        balance = _latest_record(tables.get("Balance", []))
        cashflow = _latest_record(tables.get("CashFlow", []))

        report_period = _first_present(
            pershare or income or balance or cashflow,
            REPORT_PERIOD_FIELDS,
        )
        ann_date = _first_present(
            pershare or income or balance or cashflow,
            ANN_DATE_FIELDS,
        )

        revenue = _to_float(_first_present(income, REVENUE_FIELDS))
        net_profit = _to_float(_first_present(income, NET_PROFIT_FIELDS))
        operating_cashflow = _to_float(_first_present(cashflow, OPERATING_CASHFLOW_FIELDS))
        total_assets = _to_float(_first_present(balance, TOTAL_ASSETS_FIELDS))
        total_liabilities = _to_float(_first_present(balance, TOTAL_LIABILITIES_FIELDS))

        net_margin = net_profit / revenue if revenue and net_profit is not None else None
        cashflow_quality = (
            operating_cashflow / net_profit
            if operating_cashflow is not None and net_profit not in (None, 0)
            else None
        )
        debt_ratio = (
            total_liabilities / total_assets
            if total_assets and total_liabilities is not None
            else _to_ratio(_first_present(pershare, ["资产负债率", "gear_ratio", "debt_to_assets", "debt_ratio"]))
        )

        normalized = {
            "report_period": str(report_period or ""),
            "ann_date": str(ann_date or ""),
            "report_type": "report",
            "currency": "CNY",
            "roe": _to_qmt_percent_ratio(
                _first_present(pershare, ["净资产收益率", "du_return_on_equity", "equity_roe", "net_roe", "ROE", "roe"])
            ),
            "roe_weighted": _to_qmt_percent_ratio(_first_present(pershare, ["加权净资产收益率", "roe_weighted"])),
            "gross_margin": _to_qmt_percent_ratio(
                _first_present(pershare, ["销售毛利率", "毛利率", "sales_gross_profit", "gross_profit", "gross_margin"])
            ),
            "net_margin": net_margin
            or _to_qmt_percent_ratio(_first_present(pershare, ["销售净利率", "净利率", "net_profit", "net_margin"])),
            "revenue_growth": _to_qmt_percent_ratio(
                _first_present(
                    pershare,
                    ["营业收入同比增长率", "营业收入同比增长", "inc_revenue_rate", "or_yoy", "revenue_growth"],
                )
            ),
            "net_profit_growth": _to_qmt_percent_ratio(
                _first_present(
                    pershare,
                    ["净利润同比增长率", "归母净利润同比增长", "inc_net_profit_rate", "netprofit_yoy", "net_profit_growth"],
                )
            ),
            "deducted_net_profit_growth": _to_qmt_percent_ratio(
                _first_present(pershare, ["扣非净利润同比增长率", "adjusted_net_profit_rate", "deducted_net_profit_growth"])
            ),
            "operating_cashflow_quality": cashflow_quality
            if cashflow_quality is not None
            else _to_float(_first_present(pershare, ["sales_cash_flow"])),
            "debt_ratio": debt_ratio,
            "current_ratio": _to_float(_first_present(pershare, ["流动比率", "current_ratio"])),
            "eps": _to_float(_first_present(pershare, ["基本每股收益", "s_fa_eps_basic", "eps"])),
            "bps": _to_float(_first_present(pershare, ["每股净资产", "s_fa_bps", "bps"])),
            "revenue_ttm": _annualize_statement_amount(revenue, report_period),
            "net_profit_ttm": _annualize_statement_amount(net_profit, report_period),
            "operating_cashflow_ttm": _annualize_statement_amount(operating_cashflow, report_period),
            "history": [],
        }

        field_sources = {
            key: "qmt.get_financial_data"
            for key, value in normalized.items()
            if value not in (None, "", [])
        }

        return {
            "normalized": {key: value for key, value in normalized.items() if value is not None},
            "field_sources": field_sources,
        }

    def normalize_akshare(self, provider_result: dict) -> dict:
        records = provider_result.get("data", [])
        provider = provider_result.get("provider", "akshare")
        dataset = provider_result.get("dataset", "unknown")

        active = [
            row for row in records
            if str(row.get("ann_date") or row.get("公告日期") or "") <= str(date.today())
        ]

        def sort_key(row: dict) -> tuple[str, str]:
            period = str(_first_present(row, REPORT_PERIOD_FIELDS) or "")
            ann = str(_first_present(row, ANN_DATE_FIELDS) or "")
            return period, ann

        active = sorted(active, key=sort_key, reverse=True)

        normalized = {}
        if not active:
            return {"normalized": normalized, "field_sources": {}}

        latest = active[0]
        period = _first_present(latest, REPORT_PERIOD_FIELDS)
        ann = _first_present(latest, ANN_DATE_FIELDS)

        normalized["report_period"] = str(period or "")
        normalized["ann_date"] = str(ann or "")
        normalized["report_type"] = "report"
        normalized["currency"] = "CNY"

        akshare_field_map = {
            "roe": ["净资产收益率", "ROE", "roe", "加权净资产收益率"],
            "roe_weighted": ["加权净资产收益率", "净资产收益率(加权)", "roe_weighted"],
            "gross_margin": ["销售毛利率", "毛利率", "grossprofit_margin", "gross_margin"],
            "net_margin": ["销售净利率", "净利率", "netprofit_margin", "net_margin"],
            "revenue_growth": [
                "营业总收入同比增长率", "营业收入同比增长率", "营业总收入同比增长",
                "or_yoy", "revenue_growth", "营业收入(同比增长率)",
            ],
            "net_profit_growth": [
                "归属母公司股东的净利润同比增长率", "归母净利润同比增长率",
                "归属母公司净利润同比增长率", "净利润同比增长率",
                "netprofit_yoy", "net_profit_growth", "净利润(同比增长率)",
            ],
            "deducted_net_profit_growth": [
                "扣非净利润同比增长率", "扣除非经常性损益净利润同比增长率",
                "deducted_net_profit_growth",
            ],
            "debt_ratio": ["资产负债率", "debt_to_assets", "debt_ratio"],
            "current_ratio": ["流动比率", "current_ratio"],
            "eps": ["基本每股收益", "eps", "每股收益"],
            "bps": ["每股净资产", "bps", "每股净资产_最新股数"],
        }

        for target_field, candidates in akshare_field_map.items():
            raw = _first_present(latest, candidates)
            if _is_missing(raw):
                continue
            if target_field in {
                "roe", "roe_weighted", "gross_margin", "net_margin",
                "revenue_growth", "net_profit_growth", "deducted_net_profit_growth",
                "debt_ratio",
            }:
                normalized[target_field] = _to_ratio(raw)
            else:
                normalized[target_field] = _to_float(raw)

        revenue = _to_float(_first_present(latest, REVENUE_FIELDS))
        net_profit = _to_float(_first_present(latest, NET_PROFIT_FIELDS))
        operating_cashflow = _to_float(_first_present(latest, OPERATING_CASHFLOW_FIELDS))

        if net_profit is not None and revenue and revenue != 0:
            normalized.setdefault("net_margin", net_profit / revenue)

        if operating_cashflow is not None and net_profit and net_profit != 0:
            normalized.setdefault("operating_cashflow_quality", operating_cashflow / net_profit)

        normalized.setdefault("revenue_ttm", _annualize_statement_amount(revenue, period))
        normalized.setdefault("net_profit_ttm", _annualize_statement_amount(net_profit, period))
        normalized.setdefault(
            "operating_cashflow_ttm",
            _annualize_statement_amount(operating_cashflow, period),
        )

        total_assets = _to_float(_first_present(latest, TOTAL_ASSETS_FIELDS))
        total_liabilities = _to_float(_first_present(latest, TOTAL_LIABILITIES_FIELDS))
        if total_assets and total_liabilities is not None:
            normalized.setdefault("debt_ratio", total_liabilities / total_assets)

        history = []
        for row in active[:20]:
            h_period = str(_first_present(row, REPORT_PERIOD_FIELDS) or "")
            h_revenue_growth = _to_ratio(_first_present(row, [
                "营业总收入同比增长率", "营业收入同比增长率", "or_yoy", "revenue_growth",
            ]))
            h_net_profit_growth = _to_ratio(_first_present(row, [
                "归属母公司股东的净利润同比增长率", "归母净利润同比增长率",
                "netprofit_yoy", "net_profit_growth",
            ]))
            h_roe_raw = _first_present(row, ["净资产收益率", "ROE", "roe"])
            h_gross_margin_raw = _first_present(row, ["销售毛利率", "毛利率", "gross_margin"])
            h_net_margin_raw = _first_present(row, ["销售净利率", "净利率", "net_margin"])
            history.append({
                key: value
                for key, value in {
                    "report_period": h_period,
                    "ann_date": str(_first_present(row, ANN_DATE_FIELDS) or ""),
                    "roe": _to_ratio(h_roe_raw),
                    "gross_margin": _to_ratio(h_gross_margin_raw),
                    "net_margin": _to_ratio(h_net_margin_raw),
                    "revenue_growth": h_revenue_growth,
                    "net_profit_growth": h_net_profit_growth,
                }.items()
                if value is not None
            })

        normalized["history"] = history

        field_sources = {
            key: f"{provider}.{dataset}"
            for key, value in normalized.items()
            if value not in (None, "", [])
        }

        return {
            "normalized": {key: value for key, value in normalized.items() if value is not None},
            "field_sources": field_sources,
        }
