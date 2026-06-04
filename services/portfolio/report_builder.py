"""Portfolio report builder — generate JSON + Markdown artifacts.

Saves to storage/artifacts/portfolio/<analysis_id>/analysis.json and analysis.md.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from services.portfolio.portfolio_analyzer import PortfolioAnalysis

# Chinese labels for rebalance_action values (shared with dashboard)
REBALANCE_LABELS: dict[str | None, str] = {
    "add": "加仓",
    "reduce": "减仓",
    "hold": "维持",
    None: "-",
}

_ARTIFACTS_ROOT = Path(__file__).resolve().parents[2] / "storage" / "artifacts" / "portfolio"


def save_portfolio_report(analysis: PortfolioAnalysis) -> dict[str, str]:
    """Save portfolio analysis as JSON + Markdown. Returns {json, markdown} paths."""
    out_dir = _ARTIFACTS_ROOT / analysis.analysis_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = out_dir / "analysis.json"
    json_path.write_text(
        json.dumps(dataclasses.asdict(analysis), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Markdown
    md_path = out_dir / "analysis.md"
    md_path.write_text(_build_markdown(analysis), encoding="utf-8")

    return {"json": str(json_path), "markdown": str(md_path)}


def _build_markdown(a: PortfolioAnalysis) -> str:
    lines = [
        "# 组合分析报告",
        "",
        f"**分析 ID:** {a.analysis_id}",
        f"**生成时间:** {a.generated_at}",
        f"**风险偏好:** {a.risk_profile}",
        "",
        "---",
        "",
        "## 重要声明",
        "",
        "> 本报告为研究建议，不是交易指令。系统不会自动下单。",
        "> 所有投资决策需由用户自行判断和执行。",
        "",
        "---",
        "",
        "## 组合概览",
        "",
        f"- **持仓数量:** {a.total_holdings}",
        f"- **组合评分:** {a.portfolio_score if a.portfolio_score is not None else 'N/A'}",
        f"- **组合评级:** {a.portfolio_rating or 'N/A'}",
        f"- **风险等级:** {a.risk_level or 'N/A'}",
        f"- **目标现金比例:** {a.target_cash_weight:.1%}",
        f"- **当前现金比例:** {a.current_cash_weight:.1%}" if a.current_cash_weight is not None else "- **当前现金比例:** N/A（未提供当前权重）",
        "",
    ]

    # Holdings table
    lines.append("## 持仓明细")
    lines.append("")
    lines.append("| 标的 | 名称 | 评分 | 评级 | 建议 | 风险 | 当前权重 | 目标权重 | 变动 | 再平衡 |")
    lines.append("|------|------|------|------|------|------|----------|----------|------|--------|")
    for h in a.holdings:
        has_score = h.score is not None
        has_weight = h.current_weight is not None
        score_str = f"{h.score:.0f}" if has_score else "N/A"
        target_str = f"{h.target_weight:.1%}" if has_score else "N/A"
        current_str = f"{h.current_weight:.1%}" if has_weight else "N/A"
        if not has_score or not has_weight:
            delta_str = "N/A"
        elif h.current_weight > 0:
            delta_str = f"{h.delta_weight:+.1%}"
        else:
            delta_str = "-"
        rebal_str = REBALANCE_LABELS.get(h.rebalance_action, "-")
        lines.append(
            f"| {h.symbol} | {h.asset_name} | {score_str} | {h.rating or '-'} "
            f"| {h.action or '-'} | {h.risk_level or '-'} "
            f"| {current_str} | {target_str} "
            f"| {delta_str} | {rebal_str} |"
        )
    lines.append("")

    # Rebalance details
    rebal_items = [h for h in a.holdings if h.rebalance_reason]
    if rebal_items:
        lines.append("### 再平衡详情")
        lines.append("")
        for h in rebal_items:
            lines.append(f"- **{h.symbol}**: {h.rebalance_reason}")
        lines.append("")

    # Industry exposure
    lines.append("## 行业暴露")
    lines.append("")
    lines.append("| 行业 | 权重 |")
    lines.append("|------|------|")
    for ind, w in a.industry_exposure.items():
        lines.append(f"| {ind} | {w:.1%} |")
    lines.append("")

    # Asset type exposure
    lines.append("## 资产类型暴露")
    lines.append("")
    for at, w in a.asset_type_exposure.items():
        lines.append(f"- **{at}:** {w:.1%}")
    lines.append("")

    # Rebalance suggestions
    if a.rebalance_suggestions:
        lines.append("## 再平衡建议")
        lines.append("")
        for s in a.rebalance_suggestions:
            lines.append(f"- {s}")
        lines.append("")

    # Missing data
    if a.missing_reasons:
        lines.append("## 缺失数据提示")
        lines.append("")
        for m in a.missing_reasons:
            lines.append(f"- {m}")
        lines.append("")

    # Data warnings
    if a.data_warnings:
        lines.append("## 数据质量警告")
        lines.append("")
        for w in a.data_warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Constraints
    lines.append("## 约束条件")
    lines.append("")
    lines.append(f"- 单标的上限: {a.constraints.max_single_weight:.0%}")
    lines.append(f"- 行业上限: {a.constraints.max_industry_weight:.0%}")
    lines.append(f"- 最低现金比例: {a.constraints.min_cash_weight:.0%}")
    lines.append("")

    return "\n".join(lines)
