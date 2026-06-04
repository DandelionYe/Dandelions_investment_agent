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
    localize_price_history_source,
    localize_price_source,
    localize_price_status,
    localize_risk_level,
)

_MISSING_REASON_CODES: dict[str, str] = {
    "missing_close": "收盘价缺失",
    "missing_total_volume": "股本数据缺失",
    "missing_market_cap": "市值数据缺失",
    "share_capital_fallback_unavailable": "股本备用来源不可用",
    "missing_net_profit_ttm": "净利润TTM缺失",
    "loss_making_or_invalid_pe": "亏损或PE无效",
    "missing_bps": "每股净资产缺失",
    "invalid_bps": "每股净资产无效",
    "missing_revenue_ttm": "营收TTM缺失",
    "invalid_revenue_ttm": "营收TTM无效",
    "provider_disabled": "数据源未启用",
    "missing_dividend_yield_source": "股息数据缺失",
    "stale_local_csmar_daily_derived": "本地CSMAR数据过期",
    "peer_cache_preflight_failed": "同行缓存预检未通过",
    "missing_peer_close": "同行价格缺失",
    "missing_peer_finance": "同行财务数据缺失",
    "missing_peer_share_capital": "同行股本数据缺失",
    "insufficient_peer_samples": "行业有效样本不足",
    "insufficient_history_samples": "历史样本不足",
    "target_not_in_peer_inputs": "标的不在有效同行中",
    "field_not_supported": "字段不支持",
    "provider_unavailable": "数据源不可用",
    "unknown": "未知原因",
}


def _as_bullets(items: list[Any] | None) -> str:
    """
    把列表转换成 Markdown bullet。
    """
    if not items:
        return "- 暂无"

    return "\n".join(f"- {item}" for item in items)


def _build_missing_reason_cell(
    value: Any,
    valuation_data: dict,
    reason_key: str,
    formatter: Any,
) -> str:
    """Format a valuation cell, appending missing reason when value is None."""
    if value is not None:
        return formatter(value)
    reason_code = valuation_data.get(reason_key)
    if reason_code:
        reason_text = _MISSING_REASON_CODES.get(reason_code, reason_code)
        return f"暂无（原因：{reason_text}）"
    return formatter(value)


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


def _build_evidence_fields_summary(evidence_fields: dict) -> str:
    """Build a concise evidence fields summary for the report.

    Shows coverage rate, source distribution, and key quality issues.
    Does NOT dump full evidence_fields.
    """
    if not evidence_fields:
        return "暂无 evidence_fields 数据。"

    from services.data.evidence_schema import is_strict_source, summarize_evidence_coverage

    summary = summarize_evidence_coverage({"evidence_fields": evidence_fields})

    lines = [
        f"- 核心字段覆盖率：{summary['coverage_rate']:.0%}"
        f"（{summary['covered']}/{summary['total_required']}）",
    ]

    # Source distribution
    by_source = summary.get("by_source", {})
    if by_source:
        source_parts = [
            f"{src}({cnt})" for src, cnt in
            sorted(by_source.items(), key=lambda x: -x[1])
        ]
        lines.append("- 来源分布：" + "、".join(source_parts))
        strict_count = sum(cnt for src, cnt in by_source.items() if is_strict_source(src))
        total_sources = sum(by_source.values())
        strict_rate = strict_count / total_sources if total_sources else 0.0
        lines.append(f"- strict source 覆盖率：{strict_rate:.0%}（{strict_count}/{total_sources}）")

    # Quality distribution
    by_quality = summary.get("by_quality", {})
    if by_quality:
        quality_parts = [
            f"{q}({cnt})" for q, cnt in
            sorted(by_quality.items(), key=lambda x: -x[1])
        ]
        lines.append("- 质量分布：" + "、".join(quality_parts))

    # Missing reasons
    missing_reasons = summary.get("missing_reasons", {})
    if missing_reasons:
        reason_parts = [
            f"{reason}({cnt})" for reason, cnt in
            sorted(missing_reasons.items(), key=lambda x: -x[1])[:5]
        ]
        lines.append("- 主要缺失原因：" + "、".join(reason_parts))

    return "\n".join(lines)


def _escape_table_cell(value: Any) -> str:
    text = "暂无" if value is None else str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def _build_evidence_index(evidence_fields: dict, limit: int = 15) -> str:
    """Build an evidence index table showing key fields with provenance.

    Shows field path, display value, source, as_of, freshness, and warnings.
    Prioritizes fields with warnings or missing data.
    """
    if not evidence_fields:
        return "暂无 evidence_fields 数据。"

    from services.data.evidence_schema import is_evidence_field

    # Separate into problematic and normal fields
    problematic: list[tuple[str, dict]] = []
    normal: list[tuple[str, dict]] = []

    for path, ev in evidence_fields.items():
        if not is_evidence_field(ev):
            continue
        quality = ev.get("quality", {})
        warnings = ev.get("warnings", [])
        has_issue = (
            not quality.get("available", False)
            or quality.get("freshness") in ("estimated", "missing", "unknown")
            or warnings
        )
        if has_issue:
            problematic.append((path, ev))
        else:
            normal.append((path, ev))

    # Show problematic first, then normal, up to limit
    ordered = problematic + normal
    shown = ordered[:limit]

    rows = [
        "| 字段路径 | 数值 | 来源 | 日期 | 质量 | 备注 |",
        "|---|---|---|---|---|---|",
    ]

    for path, ev in shown:
        value = ev.get("value")
        source = ev.get("source", "unknown")
        as_of = ev.get("as_of") or "-"
        quality = ev.get("quality", {})
        freshness = quality.get("freshness", "unknown")
        warnings = ev.get("warnings", [])

        # Format value
        if value is None:
            display_val = "缺失"
        elif isinstance(value, float):
            if abs(value) >= 1e8:
                display_val = f"{value/1e8:.2f}亿"
            elif abs(value) >= 1e4:
                display_val = f"{value/1e4:.2f}万"
            else:
                display_val = f"{value:.4f}"
        else:
            display_val = str(value)[:20]

        # Format freshness
        freshness_map = {
            "fresh": "新鲜", "stale": "过期", "historical": "历史",
            "estimated": "估算", "missing": "缺失", "unknown": "未知",
        }
        freshness_display = freshness_map.get(freshness, freshness)

        # Format notes
        notes = []
        if not quality.get("available", False):
            mr = quality.get("missing_reason")
            if mr:
                notes.append(f"缺失: {mr}")
        for w in warnings[:1]:
            notes.append(w[:30])
        note_display = "; ".join(notes) if notes else "-"

        rows.append(
            f"| {_escape_table_cell(path)} | {_escape_table_cell(display_val)} | "
            f"{_escape_table_cell(source)} | {_escape_table_cell(as_of)} | "
            f"{_escape_table_cell(freshness_display)} | {_escape_table_cell(note_display)} |"
        )

    remaining = len(ordered) - len(shown)
    if remaining > 0:
        rows.append(f"| ...另有 {remaining} 个字段 | ... | ... | ... | ... | ... |")

    return "\n".join(rows)


def _build_percentile_explanation(valuation_data: dict) -> str:
    """Build an explanation of percentile values in the report.

    Explains what each percentile means, the data source, as_of, and sample info.
    """
    if not valuation_data:
        return ""

    lines: list[str] = []

    # Historical percentiles
    for metric, label in [
        ("pe_percentile", "PE 历史分位"),
        ("pb_percentile", "PB 历史分位"),
        ("ps_percentile", "PS 历史分位"),
    ]:
        val = valuation_data.get(metric)
        if val is None:
            continue
        source = valuation_data.get(f"{metric}_source", "未记录")
        sample_count = valuation_data.get(f"{metric}_sample_count")
        reason = valuation_data.get(f"{metric}_missing_reason")

        line = f"- **{label}**：{val:.0%}"
        if sample_count:
            line += f"（基于 {sample_count} 个月度样本）"
        line += f"，数据来源：{source}"
        if reason:
            line += f"，缺失原因：{reason}"
        lines.append(line)

    # Industry percentiles
    for metric, label in [
        ("industry_pe_percentile", "PE 行业分位"),
        ("industry_pb_percentile", "PB 行业分位"),
        ("industry_ps_percentile", "PS 行业分位"),
    ]:
        val = valuation_data.get(metric)
        if val is None:
            continue
        ind_source = valuation_data.get("industry_valuation_source", "未记录")
        peer_count = valuation_data.get("industry_valid_peer_count")
        reason = valuation_data.get(f"{metric}_missing_reason")

        line = f"- **{label}**：{val:.0%}"
        if peer_count:
            line += f"（同行有效样本 {peer_count} 只）"
        line += f"，行业估值来源：{ind_source}"
        if reason:
            line += f"，缺失原因：{reason}"
        lines.append(line)

    if not lines:
        return "暂无估值分位数据。"

    lines.insert(0, "**分位值含义**：0% 表示历史/行业最低，100% 表示历史/行业最高。50% 表示处于中位水平。")
    return "\n".join(lines)


def _build_risk_degradation_explanation(result: dict) -> str:
    """Build a risk degradation explanation section.

    Explains whether the decision guard was triggered, why, and the impact.
    """
    decision_guard = result.get("decision_guard", {})
    data_quality = result.get("data_quality", {})
    event_data = result.get("event_data", {})
    event_summary = event_data.get("event_summary", {})

    lines: list[str] = []

    # Check if guard was enabled and caused degradation
    guard_enabled = decision_guard.get("enabled", False)
    llm_action = decision_guard.get("llm_action", "")
    final_action = decision_guard.get("final_action", "")
    was_degraded = guard_enabled and llm_action and final_action and llm_action != final_action

    if was_degraded:
        lines.append(f"**本次建议被降级**：模型原始建议为「{llm_action}」，"
                     f"经决策保护器约束后降级为「{final_action}」。")
    elif guard_enabled:
        lines.append("**本次建议未被降级**：模型建议在评分和风险约束范围内。")
    else:
        lines.append("**决策保护器未启用**。")

    # Explain degradation reasons
    guard_reasons = decision_guard.get("guard_reasons", [])
    if guard_reasons:
        lines.append("")
        lines.append("**降级/限制原因**：")
        for reason in guard_reasons:
            lines.append(f"- {reason}")

    # Data quality impact
    has_placeholder = data_quality.get("has_placeholder", False)
    blocking_issues = data_quality.get("blocking_issues", [])
    if has_placeholder:
        lines.append("")
        lines.append("- **存在 placeholder 数据**：部分字段使用占位值，评分可信度受限。")
    if blocking_issues:
        lines.append(f"- **存在 {len(blocking_issues)} 个数据质量阻断项**。")

    # Event impact
    critical_count = event_summary.get("critical_count", 0) or 0
    if critical_count > 0:
        lines.append(f"- **存在 {critical_count} 个 critical 级别事件**，系统强制建议为「回避」。")

    # Risk level impact
    risk_level = decision_guard.get("risk_level")
    if risk_level == "high":
        lines.append("- **风险等级为 high**：系统限制最高建议为「观察」。")

    if not lines:
        return "暂无风险降级信息。"

    return "\n".join(lines)


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
        reason_key = f"{field}_missing_reason"
        cell = _build_missing_reason_cell(
            valuation_data.get(field), valuation_data, reason_key, formatter
        )
        # Show CSMAR override note for PE TTM (only when PE value exists)
        if field == "pe_ttm" and valuation_data.get("pe_ttm") is not None and valuation_data.get("pe_ttm_override_by_csmar"):
            cell += " ⚠️ CSMAR覆盖"
        rows.append(f"| {title} | {cell} |")
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
        reason_key = f"{field}_missing_reason"
        cell = _build_missing_reason_cell(
            valuation_data.get(field), valuation_data, reason_key, formatter
        )
        rows.append(f"| {title} | {cell} |")
    return "\n".join(rows)


def _build_price_freshness_warning(price_data: dict, report_as_of: str | None = None) -> str | None:
    """Build a staleness warning blockquote for the price section.

    Returns ``None`` when price data is not stale.
    """
    is_stale = price_data.get("price_is_stale")
    if not isinstance(is_stale, bool) or not is_stale:
        return None

    trade_date = price_data.get("latest_trade_date") or "未知"
    report_date = report_as_of or _today_str()
    return (
        f"> **行情数据可能过期**：最新行情日期为 {trade_date}，"
        f"报告日期为 {report_date}。"
        f"价格、均线、涨跌幅、回撤和波动率可能不代表最新交易日。"
    )


def _today_str() -> str:
    from datetime import date

    return str(date.today())


def _build_price_chain_summary(qmt_status: dict) -> str:
    """Build a one-line price chain summary from qmt_status."""
    if not qmt_status:
        return ""

    download_attempted = qmt_status.get("download_attempted", False)
    tick_applied = qmt_status.get("full_tick_applied", False)
    akshare_attempted = qmt_status.get("akshare_price_fallback_attempted", False)
    akshare_applied = qmt_status.get("akshare_price_fallback_applied", False)

    parts = ["QMT 日 K"]

    if download_attempted:
        reason = qmt_status.get("download_reason", "")
        if reason == "stale":
            parts.append("stale 重下载")

    if tick_applied:
        parts.append("full tick 临时 bar")
    elif qmt_status.get("full_tick_attempted") and not tick_applied:
        parts.append("full tick 未修复")

    if akshare_applied:
        parts.append("AKShare fallback")
    elif akshare_attempted and not akshare_applied:
        reason = qmt_status.get("akshare_price_fallback_reason", "")
        parts.append(f"AKShare fallback 未成功（{reason}）")

    return " -> ".join(parts)


def _filter_stale_warnings(data_warnings: list[str]) -> list[str]:
    """Remove stale-related warnings that are now covered by the freshness section."""
    stale_keywords = ["行情可能过期", "日 K 行情可能过期", "行情仍可能过期", "行情仍过期"]
    return [
        w for w in data_warnings
        if not any(kw in w for kw in stale_keywords)
    ]


_REPORT_SECTION_HEADINGS = {
    "## 一、基本信息": "basic_info",
    "## 二、投委会结论": "committee_conclusion",
    "## 三、数据来源与行情摘要": "data_source_and_price",
    "## 四、量化因子打分卡": "scorecard",
    "## 五、多头观点": "bull_case",
    "## 六、空头观点": "bear_case",
    "## 七、风险官意见": "risk_officer",
    "## 八、决策保护器说明": "decision_guard",
    "## 九、辩论收敛纪要": "debate_convergence",
    "## 十、后续跟踪建议": "follow_up",
    "## 十一、免责声明": "disclaimer",
}


def _filter_markdown_sections(markdown: str, enabled_sections: list[str]) -> str:
    """按模板配置过滤二级章节，保留报告标题和未知章节。"""
    enabled = set(enabled_sections)
    lines = markdown.splitlines()
    output: list[str] = []
    keep = True
    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            section_id = _REPORT_SECTION_HEADINGS.get(line.strip())
            keep = section_id is None or section_id in enabled
        if keep:
            output.append(line)
    return "\n".join(output).strip() + "\n"


def build_markdown_report(result: dict, template_config=None) -> str:
    """
    把研究结果转换成 Markdown 报告。
    支持展示完整 DeepSeek 辩论结果、行情摘要、数据质量提示和决策保护器结果。

    Parameters
    ----------
    result : dict
        研究结果。
    template_config : ReportTemplateConfig | dict | None
        模板配置。dict 会自动转换为 ReportTemplateConfig。
        None 使用默认配置（包含所有章节）。
    """
    from services.report.template_config import ReportTemplateConfig, template_config_from_dict

    if template_config is None:
        cfg = ReportTemplateConfig()
    elif isinstance(template_config, dict):
        cfg = template_config_from_dict(template_config)
    else:
        cfg = template_config

    score_breakdown = result.get("score_breakdown", {})
    price_data = result.get("price_data", {})
    valuation_data = result.get("valuation_data", {})
    decision_guard = result.get("decision_guard", {})
    debate_result = result.get("debate_result", {})
    data_quality = result.get("data_quality", {})
    evidence_bundle = result.get("evidence_bundle", {})
    evidence_fields = result.get("evidence_fields", {})
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
    field_quality_table = _build_field_quality_table(data_quality.get("field_quality", {})) if cfg.show_data_quality else ""
    evidence_preview_table = _build_evidence_preview(evidence_bundle) if cfg.show_evidence else ""
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

    # --- Price freshness display ---
    freshness_warning = _build_price_freshness_warning(price_data, result.get("as_of"))
    qmt_status = result.get("source_metadata", {}).get("qmt_status", {})
    price_chain = _build_price_chain_summary(qmt_status)

    latest_trade_date_display = price_data.get("latest_trade_date") or "暂无"
    price_source_display = localize_price_source(price_data.get("latest_price_source"))
    price_status_display = localize_price_status(price_data.get("price_is_stale"))
    price_history_display = localize_price_history_source(price_data.get("price_history_source"))

    # --- Build conditional sections (avoid nested triple-quoted f-strings) ---
    if cfg.show_data_quality:
        evidence_fields_summary = _build_evidence_fields_summary(evidence_fields)
        data_quality_section = (
            f"### 3.2 数据质量摘要\n\n"
            f"- 整体置信度：{format_confidence(data_quality.get('overall_confidence'))}\n"
            f"- 是否存在 placeholder：{localize_bool(data_quality.get('has_placeholder'))}\n"
            f"- 阻断项：{len(data_quality.get('blocking_issues', []))}\n\n"
            f"#### 数据证据字段摘要\n\n"
            f"{evidence_fields_summary}\n\n"
            f"#### 字段质量明细\n\n"
            f"{field_quality_table}\n\n"
            f"#### 数据质量警告\n\n"
            f"{_as_bullets(data_quality.get('warnings'))}\n\n"
            f"#### 数据质量阻断项\n\n"
            f"{_as_bullets(data_quality.get('blocking_issues'))}"
        )
    else:
        data_quality_section = ""

    if cfg.show_evidence:
        evidence_index = _build_evidence_index(evidence_fields)
        evidence_section = (
            f"### 3.3 EvidenceBundle 摘要\n\n{evidence_preview_table}\n\n"
            f"### 3.4 证据索引\n\n{evidence_index}"
        )
    else:
        evidence_section = ""

    # Percentile explanation (always shown when valuation data exists)
    percentile_explanation = _build_percentile_explanation(valuation_data)

    if cfg.show_decision_guard:
        guard_section = (
            f"## 八、决策保护器说明\n\n"
            f"### 8.1 保护器状态\n\n"
            f"- 是否启用：{guard_enabled_display}\n"
            f"- 本地评分：{guard_score}\n"
            f"- 本地评级：{guard_rating}\n"
            f"- 风险等级：{guard_risk_level}\n"
            f"- 模型原始建议：{guard_llm_action}\n"
            f"- 系统允许最高建议：{guard_max_allowed_action}\n"
            f"- 最终操作建议：{guard_final_action}\n"
            f"- 降级/限制原因：{'; '.join(guard_reasons) if guard_reasons else '暂无'}\n\n"
            f"### 8.2 保护器解释\n\n"
            f"> {guard_summary}\n\n"
            f"### 8.3 风险降级详解\n\n"
            f"{_build_risk_degradation_explanation(result)}"
        )
    else:
        guard_section = ""

    if cfg.show_disclaimer:
        disclaimer_section = (
            "## 十一、免责声明\n\n"
            "本报告由 Dandelions Investment Agent 自动生成，仅用于研究和复盘，不构成任何投资建议。"
        )
    else:
        disclaimer_section = ""

    # Filter stale warnings from data_warnings to avoid duplication
    filtered_data_warnings = _filter_stale_warnings(result.get("data_warnings", []))
    if filtered_data_warnings:
        provider_warnings_section = (
            "### 数据来源警告\n\n"
            + _as_bullets(filtered_data_warnings)
            + "\n"
        )
    else:
        provider_warnings_section = ""

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

{freshness_warning if freshness_warning else ""}

| 指标 | 数值 |
|---|---:|
| 数据来源 | {data_source} |
| 行情供应商 | {data_vendor} |
| 行情日期 | {latest_trade_date_display} |
| 价格来源 | {price_source_display} |
| 价格历史序列 | {price_history_display} |
| 行情状态 | {price_status_display} |
| 最新收盘价 | {format_number(price_data.get("close"))} |
| 近20日涨跌幅 | {format_percent(price_data.get("change_20d"))} |
| 近60日涨跌幅 | {format_percent(price_data.get("change_60d"))} |
| MA20 位置 | {localize_ma_position(price_data.get("ma20_position"))} |
| MA60 位置 | {localize_ma_position(price_data.get("ma60_position"))} |
| 近60日最大回撤 | {format_percent(price_data.get("max_drawdown_60d"))} |
| 近60日年化波动率 | {format_percent(price_data.get("volatility_60d"))} |
| 近20日平均成交额/成交量原始值 | {format_money_like_value(price_data.get("avg_turnover_20d"), data_vendor_raw)} |

价格链路：{price_chain if price_chain else "暂无"}

{provider_warnings_section}
### 3.1 数据质量提示

{_as_bullets(data_quality_notes)}

{data_quality_section}

{evidence_section}

### 3.5 行情解读

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

### 4.3 估值分位解释

{percentile_explanation}

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

{guard_section}

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

{disclaimer_section}
"""

    if analysis_notice:
        first_break = markdown.find("\n\n")
        if first_break != -1:
            markdown = (
                markdown[: first_break + 2]
                + analysis_notice
                + markdown[first_break + 2 :]
            )

    return _filter_markdown_sections(markdown, cfg.sections)


def save_markdown_report(
    result: dict,
    output_dir: str = "storage/reports",
    template_config=None,
) -> str:
    """
    保存 Markdown 报告。
    """

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    filename = f'{result["symbol"]}_report.md'
    output_path = Path(output_dir) / filename

    markdown = build_markdown_report(result, template_config=template_config)

    output_path.write_text(markdown, encoding="utf-8")

    return str(output_path)
