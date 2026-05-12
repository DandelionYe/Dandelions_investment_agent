from pathlib import Path
from typing import Any

from services.data.data_quality import (
    build_data_quality_notes,
    format_confidence,
    format_money_like_value,
    format_number,
    format_percent,
    localize_asset_type,
    localize_bool,
    localize_data_source,
    localize_data_vendor,
    localize_ma_position,
    localize_risk_level,
)


def _as_bullets(items: list[Any] | None) -> str:
    """
    把列表转换成 Markdown bullet。
    """
    if not items:
        return "- 暂无"

    return "\n".join(f"- {item}" for item in items)


def _build_field_quality_table(field_quality: dict) -> str:
    if not field_quality:
        return "| 字段 | 可用 | 来源 | 置信度 | 新鲜度 |\n|---|---:|---|---:|---|\n| 暂无 | 暂无 | 暂无 | 暂无 | 暂无 |"

    rows = ["| 字段 | 可用 | 来源 | 置信度 | 新鲜度 |", "|---|---:|---|---:|---|"]
    for field, quality in field_quality.items():
        available = "是" if quality.get("available") else "否"
        confidence = format_confidence(quality.get("confidence"))
        rows.append(
            f"| {field} | {available} | {quality.get('source', '暂无')} | "
            f"{confidence} | {quality.get('freshness', '暂无')} |"
        )
    return "\n".join(rows)


def _build_evidence_preview(evidence_bundle: dict, limit: int = 8) -> str:
    items = evidence_bundle.get("items", [])
    if not items:
        return "| 证据 | 类别 | 数值 | 来源 | 置信度 |\n|---|---|---|---|---:|\n| 暂无 | 暂无 | 暂无 | 暂无 | 暂无 |"

    rows = ["| 证据 | 类别 | 数值 | 来源 | 置信度 |", "|---|---|---|---|---:|"]
    for item in items[:limit]:
        rows.append(
            f"| {item.get('title', '暂无')} | {item.get('category', '暂无')} | "
            f"{item.get('display_value', item.get('value', '暂无'))} | "
            f"{item.get('source', '暂无')} | {format_confidence(item.get('confidence'))} |"
        )
    return "\n".join(rows)


def _format_count(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _format_text(value: Any) -> str:
    if value in (None, ""):
        return "暂无"
    return str(value)


def _build_valuation_summary_table(valuation_data: dict) -> str:
    rows = ["| 指标 | 数值 |", "|---|---:|"]
    for field, title, formatter in [
        ("pe_ttm", "PE TTM", format_number),
        ("pb_mrq", "PB MRQ", format_number),
        ("ps_ttm", "PS TTM", format_number),
        ("market_cap", "总市值", format_number),
        ("pe_percentile", "PE 历史分位", format_percent),
        ("pb_percentile", "PB 历史分位", format_percent),
        ("ps_percentile", "PS 历史分位", format_percent),
        ("dividend_yield", "股息率", format_percent),
        ("valuation_label", "估值标签", _format_text),
    ]:
        rows.append(f"| {title} | {formatter(valuation_data.get(field))} |")
    return "\n".join(rows)


def _build_industry_valuation_table(valuation_data: dict) -> str:
    display_fields = [
        "industry_name",
        "industry_level",
        "industry_peer_count",
        "industry_valid_peer_count",
        "industry_valid_peer_count_pe",
        "industry_valid_peer_count_pb",
        "industry_valid_peer_count_ps",
        "industry_pe_percentile",
        "industry_pb_percentile",
        "industry_ps_percentile",
        "industry_valuation_label",
        "industry_valuation_source",
    ]
    if not any(valuation_data.get(field) not in (None, "") for field in display_fields):
        return "暂无行业横截面估值数据。"

    rows = ["| 指标 | 数值 |", "|---|---:|"]
    for field, title, formatter in [
        ("industry_name", "行业名称", _format_text),
        ("industry_level", "行业层级", _format_text),
        ("industry_peer_count", "行业样本数", _format_count),
        ("industry_valid_peer_count", "行业有效估值样本数", _format_count),
        ("industry_valid_peer_count_pe", "PE 有效样本数", _format_count),
        ("industry_valid_peer_count_pb", "PB 有效样本数", _format_count),
        ("industry_valid_peer_count_ps", "PS 有效样本数", _format_count),
        ("industry_pe_percentile", "PE 行业分位", format_percent),
        ("industry_pb_percentile", "PB 行业分位", format_percent),
        ("industry_ps_percentile", "PS 行业分位", format_percent),
        ("industry_valuation_label", "行业估值标签", _format_text),
        ("industry_valuation_source", "行业估值来源", _format_text),
    ]:
        rows.append(f"| {title} | {formatter(valuation_data.get(field))} |")
    return "\n".join(rows)


def build_markdown_report(result: dict) -> str:
    """
    把研究结果转换成 Markdown 报告。
    支持展示完整 DeepSeek 辩论结果、行情摘要、数据质量提示和决策保护器结果。
    """

    score_breakdown = result.get("score_breakdown", {})
    price_data = result.get("price_data", {})
    valuation_data = result.get("valuation_data", {})
    decision_guard = result.get("decision_guard", {})
    debate_result = result.get("debate_result", {})
    data_quality = result.get("data_quality", {})
    evidence_bundle = result.get("evidence_bundle", {})
    analysis_mode = result.get("analysis_mode")
    analysis_warnings = result.get("analysis_warnings", [])

    bull_case = debate_result.get("bull_case", {})
    bear_case = debate_result.get("bear_case", {})
    risk_review = debate_result.get("risk_review", {})
    committee = debate_result.get("committee_conclusion", {})

    bull_thesis = bull_case.get("thesis", result.get("bull_case", "暂无"))
    bear_thesis = bear_case.get("thesis", result.get("bear_case", "暂无"))
    risk_summary = risk_review.get("risk_summary", result.get("risk_review", "暂无"))
    final_opinion = committee.get("final_opinion", result.get("final_opinion", "暂无"))

    action = result.get("action", committee.get("action", "暂无"))
    stance = committee.get("stance", "暂无")
    confidence = format_confidence(committee.get("confidence"))
    max_position = risk_review.get("max_position", result.get("max_position", "暂无"))

    data_source_raw = result.get("data_source", "暂无")
    data_vendor_raw = price_data.get("data_vendor", "暂无")

    data_source = localize_data_source(data_source_raw)
    data_vendor = localize_data_vendor(data_vendor_raw)
    asset_type = localize_asset_type(result.get("asset_type", "unknown"))

    guard_enabled = decision_guard.get("enabled", False)
    guard_score = decision_guard.get("score", result.get("score", "暂无"))
    guard_rating = decision_guard.get("rating", result.get("rating", "暂无"))
    guard_risk_level = localize_risk_level(decision_guard.get("risk_level"))
    guard_llm_action = decision_guard.get("llm_action", "暂无")
    guard_max_allowed_action = decision_guard.get("max_allowed_action", "暂无")
    guard_final_action = decision_guard.get("final_action", action)
    guard_reasons = decision_guard.get("guard_reasons", [])

    risk_level_display = localize_risk_level(risk_review.get("risk_level"))
    blocking_display = localize_bool(risk_review.get("blocking"))

    guard_enabled_display = localize_bool(guard_enabled)

    if guard_enabled:
        guard_summary = (
            f"系统已启用决策保护器。本次标的本地评分为 {guard_score} 分，"
            f"评级为 {guard_rating}，风险等级为 {guard_risk_level}。"
            f"模型原始建议为“{guard_llm_action}”，"
            f"在当前评分和风险约束下，系统允许的最高建议为“{guard_max_allowed_action}”，"
            f"最终建议为“{guard_final_action}”。"
        )
    else:
        guard_summary = "本次未启用决策保护器。"

    data_quality_notes = build_data_quality_notes(price_data)
    field_quality_table = _build_field_quality_table(data_quality.get("field_quality", {}))
    evidence_preview_table = _build_evidence_preview(evidence_bundle)
    valuation_summary_table = _build_valuation_summary_table(valuation_data)
    industry_valuation_table = _build_industry_valuation_table(valuation_data)
    industry_valuation_warnings = valuation_data.get("industry_valuation_warnings", [])
    analysis_notice = ""
    if analysis_mode in {"template_no_llm", "llm_json_fallback_template"}:
        if not analysis_warnings:
            analysis_warnings = [
                "本报告为无 LLM 模式生成，观点部分为规则/模板化输出，不构成完整投研分析。"
            ]
        analysis_notice = "\n".join(
            f"> **模式提示**：{item}" for item in analysis_warnings
        ) + "\n\n"

    markdown = f"""# {result.get("name", "未知标的")}（{result.get("symbol", "UNKNOWN")}）投研报告

## 一、基本信息

- 标的代码：{result.get("symbol", "UNKNOWN")}
- 标的名称：{result.get("name", "未知标的")}
- 资产类型：{asset_type}
- 研究日期：{result.get("as_of", "未知")}
- 研究周期：1–3个月
- 数据来源：{data_source}
- 行情供应商：{data_vendor}

## 二、投委会结论

- 综合评分：{result.get("score", "暂无")} / 100
- 评级：{result.get("rating", "暂无")}
- 立场：{stance}
- 操作建议：{action}
- 置信度：{confidence}
- 建议仓位上限：{max_position}

最终观点：

> {final_opinion}

## 三、数据来源与行情摘要

| 指标 | 数值 |
|---|---:|
| 数据来源 | {data_source} |
| 行情供应商 | {data_vendor} |
| 最新收盘价 | {format_number(price_data.get("close"))} |
| 近20日涨跌幅 | {format_percent(price_data.get("change_20d"))} |
| 近60日涨跌幅 | {format_percent(price_data.get("change_60d"))} |
| MA20 位置 | {localize_ma_position(price_data.get("ma20_position"))} |
| MA60 位置 | {localize_ma_position(price_data.get("ma60_position"))} |
| 近60日最大回撤 | {format_percent(price_data.get("max_drawdown_60d"))} |
| 近60日年化波动率 | {format_percent(price_data.get("volatility_60d"))} |
| 近20日平均成交额/成交量原始值 | {format_money_like_value(price_data.get("avg_turnover_20d"), data_vendor_raw)} |

### 3.1 数据质量提示

{_as_bullets(data_quality_notes)}

### 3.2 研究数据层质量报告

- 整体置信度：{format_confidence(data_quality.get("overall_confidence"))}
- 是否存在 placeholder：{localize_bool(data_quality.get("has_placeholder"))}
- 阻断项：{len(data_quality.get("blocking_issues", []))}

{field_quality_table}

#### 数据质量警告

{_as_bullets(data_quality.get("warnings"))}

#### 数据质量阻断项

{_as_bullets(data_quality.get("blocking_issues"))}

### 3.3 EvidenceBundle 摘要

{evidence_preview_table}

### 3.4 行情解读

- 若价格位于 MA20 和 MA60 下方，说明短中期趋势仍偏弱，需要等待趋势修复。
- 若近60日最大回撤较大，说明中线波动风险需要重点关注。
- 若波动率偏高，则仓位建议应相应保守。

## 四、量化因子打分卡

| 因子 | 得分 |
|---|---:|
| 趋势动量 | {score_breakdown.get("trend_momentum", "暂无")} |
| 流动性 | {score_breakdown.get("liquidity", "暂无")} |
| 基本面质量 | {score_breakdown.get("fundamental_quality", "暂无")} |
| 估值性价比 | {score_breakdown.get("valuation", "暂无")} |
| 风险控制 | {score_breakdown.get("risk_control", "暂无")} |
| 事件/政策 | {score_breakdown.get("event_policy", "暂无")} |

### 4.1 估值概览

{valuation_summary_table}

### 4.2 行业横截面估值

{industry_valuation_table}

#### 行业估值提示

{_as_bullets(industry_valuation_warnings)}

## 五、多头观点

### 5.1 多头核心结论

> {bull_thesis}

### 5.2 多头主要理由

{_as_bullets(bull_case.get("key_arguments"))}

### 5.3 潜在催化因素

{_as_bullets(bull_case.get("catalysts"))}

### 5.4 多头观点失效条件

{_as_bullets(bull_case.get("invalidation_conditions"))}

## 六、空头观点

### 6.1 空头核心结论

> {bear_thesis}

### 6.2 空头主要理由

{_as_bullets(bear_case.get("key_arguments"))}

### 6.3 主要担忧

{_as_bullets(bear_case.get("main_concerns"))}

### 6.4 空头观点失效条件

{_as_bullets(bear_case.get("invalidation_conditions"))}

## 七、风险官意见

### 7.1 风险等级

- 风险等级：{risk_level_display}
- 是否阻断买入建议：{blocking_display}
- 建议仓位上限：{max_position}

### 7.2 风险官总结

> {risk_summary}

### 7.3 风险触发条件

{_as_bullets(risk_review.get("risk_triggers"))}

## 八、决策保护器说明

### 8.1 保护器状态

- 是否启用：{guard_enabled_display}
- 本地评分：{guard_score}
- 本地评级：{guard_rating}
- 风险等级：{guard_risk_level}
- 模型原始建议：{guard_llm_action}
- 系统允许最高建议：{guard_max_allowed_action}
- 最终操作建议：{guard_final_action}
- 降级/限制原因：{"; ".join(guard_reasons) if guard_reasons else "暂无"}

### 8.2 保护器解释

> {guard_summary}

## 九、辩论收敛纪要

### 9.1 收敛立场

- 投委会立场：{stance}
- 最终操作建议：{action}
- 置信度：{confidence}

### 9.2 最终意见

> {final_opinion}

## 十、后续跟踪建议

- 跟踪价格是否重新站上 MA20 和 MA60。
- 跟踪近20日和近60日涨跌幅是否继续改善。
- 跟踪最大回撤和波动率是否继续扩大。
- 跟踪下一期财报是否验证盈利质量。
- 跟踪估值分位是否继续抬升。
- 若出现重大公告、政策变化或异常放量，应重新评估。

## 十一、免责声明

本报告由 Dandelions Investment Agent 自动生成，仅用于研究和复盘，不构成任何投资建议。
"""

    if analysis_notice:
        first_break = markdown.find("\n\n")
        if first_break != -1:
            markdown = (
                markdown[: first_break + 2]
                + analysis_notice
                + markdown[first_break + 2 :]
            )

    return markdown


def save_markdown_report(result: dict, output_dir: str = "storage/reports") -> str:
    """
    保存 Markdown 报告。
    """

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    filename = f'{result["symbol"]}_report.md'
    output_path = Path(output_dir) / filename

    markdown = build_markdown_report(result)

    output_path.write_text(markdown, encoding="utf-8")

    return str(output_path)
