"""组合分析 API 路由。

读取观察池或显式持仓，调用 portfolio_analyzer 生成组合分析。
遵守 RBAC：普通用户只能分析自己的观察池和研究结果；admin 可指定 username。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth.dependencies import get_current_user
from apps.api.auth.rbac import is_admin, scope_username
from apps.api.schemas.portfolio import (
    PortfolioAnalyzeRequest,
    PortfolioAnalyzeResponse,
    HoldingResponse,
)
from apps.api.task_manager.store import get_task_store, get_watchlist_store
from services.portfolio.portfolio_analyzer import Constraints, analyze_portfolio, normalize_symbol
from services.portfolio.report_builder import save_portfolio_report

router = APIRouter(tags=["portfolio"])


@router.post("/api/v1/portfolio/analyze", response_model=PortfolioAnalyzeResponse)
def analyze(
    req: PortfolioAnalyzeRequest,
    user: dict = Depends(get_current_user),
    username: str | None = None,
) -> PortfolioAnalyzeResponse:
    """Execute portfolio analysis.

    Input sources (mutually exclusive, enforced by schema validator):
    A. positions: explicit list of holdings
    B. watchlist_folder_id: load from a specific folder
    C. use_watchlist_all: load all enabled items
    """
    owner = scope_username(user) if not is_admin(user) else username

    # ── Resolve positions (schema validator ensures exactly one source) ──
    if req.positions:
        positions = [
            {
                "symbol": p.symbol,
                "asset_type": p.asset_type,
                "asset_name": p.asset_name,
                "current_weight": p.current_weight if p.current_weight is not None else 0.0,
            }
            for p in req.positions
        ]
    else:
        positions = _load_positions_from_watchlist(
            req.watchlist_folder_id, owner
        )
        if not positions:
            raise HTTPException(
                status_code=404,
                detail="观察池中无启用的标的，请先添加观察项",
            )

    # ── Load research results with watchlist fallback ──────────
    wl_snapshot_map = _build_watchlist_snapshot_map(owner)
    research_results = _load_research_results(positions, owner, wl_snapshot_map)

    # ── Analyze ───────────────────────────────────────────────
    constraints = Constraints(
        max_single_weight=req.max_single_weight,
        max_industry_weight=req.max_industry_weight,
        min_cash_weight=req.min_cash_weight,
    )
    analysis = analyze_portfolio(
        positions, research_results,
        risk_profile=req.risk_profile,
        constraints=constraints,
    )

    # ── Save artifacts ────────────────────────────────────────
    artifact_paths = save_portfolio_report(analysis)

    # ── Build response ────────────────────────────────────────
    return PortfolioAnalyzeResponse(
        analysis_id=analysis.analysis_id,
        generated_at=analysis.generated_at,
        risk_profile=analysis.risk_profile,
        total_holdings=analysis.total_holdings,
        portfolio_score=analysis.portfolio_score,
        portfolio_rating=analysis.portfolio_rating,
        risk_level=analysis.risk_level,
        cash_weight=analysis.cash_weight,
        target_cash_weight=analysis.target_cash_weight,
        current_cash_weight=analysis.current_cash_weight,
        holdings=[
            HoldingResponse(
                symbol=h.symbol,
                asset_type=h.asset_type,
                asset_name=h.asset_name,
                score=h.score,
                rating=h.rating,
                action=h.action,
                risk_level=h.risk_level,
                volatility_60d=h.volatility_60d,
                max_drawdown_60d=h.max_drawdown_60d,
                industry=h.industry,
                pe_percentile=h.pe_percentile,
                pb_percentile=h.pb_percentile,
                current_weight=h.current_weight,
                target_weight=h.target_weight,
                delta_weight=h.delta_weight,
                rebalance_action=h.rebalance_action,
                rebalance_reason=h.rebalance_reason,
                data_warnings=h.data_warnings,
                missing_reasons=h.missing_reasons,
            )
            for h in analysis.holdings
        ],
        industry_exposure=analysis.industry_exposure,
        asset_type_exposure=analysis.asset_type_exposure,
        rebalance_suggestions=analysis.rebalance_suggestions,
        missing_reasons=analysis.missing_reasons,
        data_warnings=analysis.data_warnings,
        artifact_paths=artifact_paths,
    )


def _load_positions_from_watchlist(
    folder_id: str | None, owner: str | None
) -> list[dict]:
    """Load positions from watchlist store."""
    wl = get_watchlist_store()
    if folder_id:
        items, _ = wl.list_items(folder_id=folder_id, enabled=True, owner_username=owner)
    else:
        if owner:
            items = [
                it for it in wl.get_all_enabled_items()
                if it.get("owner_username", "default") == owner
            ]
        else:
            items = wl.get_all_enabled_items()

    return [
        {
            "symbol": normalize_symbol(it["symbol"]),
            "asset_type": it.get("asset_type", "stock"),
            "asset_name": it.get("asset_name", ""),
            "current_weight": 0.0,  # watchlist doesn't track current_weight
        }
        for it in items
    ]


def _build_watchlist_snapshot_map(owner: str | None) -> dict[str, dict]:
    """Build a map of symbol → watchlist item data for fallback."""
    wl = get_watchlist_store()
    if owner:
        items = [
            it for it in wl.get_all_enabled_items()
            if it.get("owner_username", "default") == owner
        ]
    else:
        items = wl.get_all_enabled_items()

    snapshot: dict[str, dict] = {}
    for it in items:
        sym = normalize_symbol(it["symbol"])
        entry: dict = {}
        if it.get("last_score") is not None:
            entry["score"] = it["last_score"]
        if it.get("last_rating"):
            entry["rating"] = it["last_rating"]
        if it.get("last_action"):
            entry["action"] = it["last_action"]
        snap = it.get("last_trigger_snapshot")
        if isinstance(snap, dict):
            # Merge trigger snapshot data (valuation_data, risk_review, event_data)
            for key in ("valuation_data", "risk_review", "event_data", "score"):
                if key in snap and snap[key] is not None:
                    entry[key] = snap[key]
        if entry:
            entry["_snapshot_updated_at"] = it.get("updated_at", "")
            snapshot[sym] = entry
    return snapshot


def _load_research_results(
    positions: list[dict], owner: str | None, wl_snapshot_map: dict[str, dict]
) -> dict[str, dict]:
    """Load research results with fallback chain.

    Priority: result JSON > task summary > watchlist last fields > missing.
    """
    task_store = get_task_store()
    results: dict[str, dict] = {}

    for pos in positions:
        symbol = normalize_symbol(pos["symbol"])

        # Find latest completed task for this symbol
        tasks, _ = task_store.list_tasks(
            symbol=symbol, status="completed", username=owner, page=1, page_size=1
        )

        # Priority 1: result JSON file
        if tasks:
            task = tasks[0]
            report_paths = task.get("report_paths") or {}
            json_path = report_paths.get("json", "")
            if json_path and Path(json_path).exists():
                try:
                    results[symbol] = json.loads(
                        Path(json_path).read_text(encoding="utf-8")
                    )
                    continue
                except (json.JSONDecodeError, OSError):
                    pass

            # Priority 2: task summary fields, enriched with watchlist snapshot for
            # fields that task rows do not carry (valuation/risk/event snapshots).
            snapshot_entry = wl_snapshot_map.get(symbol, {})
            summary: dict = {k: v for k, v in snapshot_entry.items() if k != "_snapshot_updated_at"}
            if task.get("score") is not None:
                summary["score"] = task["score"]
            if task.get("rating"):
                summary["rating"] = task["rating"]
            if task.get("action"):
                summary["action"] = task["action"]
            # Warn when merging data from different sources/times
            snapshot_has_enrichment = any(
                snapshot_entry.get(k) is not None for k in ("valuation_data", "risk_review", "event_data")
            )
            if snapshot_has_enrichment:
                snapshot_ts = snapshot_entry.get("_snapshot_updated_at") or "未知"
                task_ts = task.get("completed_at") or "未知"
                summary.setdefault("data_quality", {}).setdefault("warnings", []).append(
                    f"研究结果来自混合来源：评分来自任务({task_ts})，"
                    f"估值/风险/事件来自观察池快照({snapshot_ts})，可能存在时间不一致"
                )
            if summary:
                results[symbol] = summary
                continue

        # Priority 3: watchlist last fields
        if symbol in wl_snapshot_map:
            results[symbol] = {k: v for k, v in wl_snapshot_map[symbol].items() if k != "_snapshot_updated_at"}
            continue

        # Priority 4: no data → analyzer will record missing_reasons

    return results
