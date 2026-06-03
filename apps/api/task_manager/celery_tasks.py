"""Celery 任务定义。

- run_research_task: 执行完整单票研究 pipeline
- health_check_beat: Celery Beat 定时健康检查
- watchlist_scheduler_check: 观察池高频调度检查
- scan_single_watchlist_item: 扫描单个观察项
- scan_watchlist: 收盘后批量扫描
"""

import logging
import shutil
import sys
from pathlib import Path

from apps.api.celery_app import celery_app
from apps.api.schemas.research import new_task_id, utc_now_iso
from apps.api.schemas.task import TaskStatus
from apps.api.task_manager.store import get_task_store, get_watchlist_store
from apps.api.websocket.progress_publisher import publish_batch_progress, publish_task_progress

logger = logging.getLogger(__name__)

# 将项目根目录添加到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

def _generate_and_store_reports(
    result: dict,
    task_id: str,
    *,
    report_template: str | None = None,
    report_theme: str | None = None,
) -> dict[str, str]:
    """生成 JSON/MD/HTML/PDF 报告并复制到 storage/reports/<task_id>/。

    返回 report_paths dict（pdf key 在失败时为空字符串）。
    JSON/MD/HTML 失败会抛异常；PDF 失败静默降级。
    """
    from services.report.html_builder import save_html_report
    from services.report.json_builder import save_json_result
    from services.report.markdown_builder import save_markdown_report
    from services.report.pdf_builder_playwright import save_pdf_report_with_playwright
    from services.report.template_config import resolve_report_config

    cfg, theme = resolve_report_config(report_template, report_theme)
    json_path = Path(save_json_result(result))
    md_path = Path(save_markdown_report(result, template_config=cfg))
    html_path = Path(save_html_report(str(md_path), theme=theme))

    reports_dir = PROJECT_ROOT / "storage" / "reports" / task_id
    reports_dir.mkdir(parents=True, exist_ok=True)

    for src, dst_name in [
        (json_path, "result.json"),
        (md_path, "report.md"),
        (html_path, "report.html"),
    ]:
        dst = reports_dir / dst_name
        if src.exists() and not dst.exists():
            shutil.copy2(str(src), str(dst))

    pdf_path = None
    try:
        pdf_src = Path(save_pdf_report_with_playwright(str(html_path)))
        pdf_dst = reports_dir / "report.pdf"
        if pdf_src.exists() and not pdf_dst.exists():
            shutil.copy2(str(pdf_src), str(pdf_dst))
        if pdf_dst.exists():
            pdf_path = str(pdf_dst)
    except Exception as exc:
        logger.warning("PDF 生成失败（task %s）: %s", task_id, exc)

    return {
        "json": str(reports_dir / "result.json"),
        "markdown": str(reports_dir / "report.md"),
        "html": str(reports_dir / "report.html"),
        "pdf": pdf_path,
    }


@celery_app.task(
    bind=True,
    name="research.run_single",
    max_retries=1,
    default_retry_delay=60,
    acks_late=True,
)
def run_research_task(self, task_id: str, params: dict) -> dict:
    """Celery 任务：执行完整单票研究 pipeline。

    Args:
        task_id: 任务 UUID
        params: {symbol, data_source, use_llm, max_debate_rounds, use_graph,
                 report_template, report_theme}

    Returns:
        包含 score/rating/action/final_opinion 的摘要 dict。
    """
    store = get_task_store()

    store.update_status(
        task_id,
        TaskStatus.RUNNING,
        started_at=utc_now_iso(),
        progress=0.1,
        progress_message="开始加载数据...",
    )

    symbol = params["symbol"]
    data_source = params.get("data_source", "mock")
    use_llm = params.get("use_llm", True)
    max_debate_rounds = params.get("max_debate_rounds", 3)
    use_graph = params.get("use_graph", True)
    report_template = params.get("report_template")
    report_theme = params.get("report_theme")
    publish_task_progress(task_id, TaskStatus.RUNNING, 0.1, "开始加载数据...", symbol)

    try:
        store.update_status(
            task_id,
            TaskStatus.RUNNING,
            progress=0.3,
            progress_message=f"执行研究中（{symbol}，数据源：{data_source}）...",
        )
        publish_task_progress(task_id, TaskStatus.RUNNING, 0.3,
                              f"执行研究中（{symbol}，数据源：{data_source}）...", symbol)

        if use_graph:
            from services.agents.langgraph_orchestrator import run_full_research_graph
            result = run_full_research_graph(
                symbol=symbol,
                data_source=data_source,
                use_llm=use_llm,
                max_debate_rounds=max_debate_rounds,
            )
        else:
            from services.orchestrator.single_asset_research import (
                run_single_asset_research,
            )
            result = run_single_asset_research(
                symbol=symbol,
                use_llm=use_llm,
                data_source=data_source,
            )

        store.update_status(
            task_id,
            TaskStatus.RUNNING,
            progress=0.7,
            progress_message="生成报告文件...",
        )
        publish_task_progress(task_id, TaskStatus.RUNNING, 0.7, "生成报告文件...", symbol)

        report_paths = _generate_and_store_reports(
            result, task_id,
            report_template=report_template,
            report_theme=report_theme,
        )

        completed_at = utc_now_iso()
        store.update_result(
            task_id,
            score=result.get("score"),
            rating=result.get("rating"),
            action=result.get("action"),
            final_opinion=result.get("final_opinion"),
            report_paths=report_paths,
            completed_at=completed_at,
        )
        store.update_status(
            task_id,
            TaskStatus.COMPLETED,
            progress=1.0,
            progress_message="研究完成。",
            completed_at=completed_at,
        )
        publish_task_progress(
            task_id, TaskStatus.COMPLETED, 1.0, "研究完成。", symbol,
            score=result.get("score"), rating=result.get("rating"),
            action=result.get("action"),
        )

        return {
            "task_id": task_id,
            "status": TaskStatus.COMPLETED,
            "score": result.get("score"),
            "rating": result.get("rating"),
            "action": result.get("action"),
            "final_opinion": result.get("final_opinion"),
        }

    except Exception as exc:
        store.update_status(
            task_id,
            TaskStatus.FAILED,
            progress=0.0,
            completed_at=utc_now_iso(),
            error_message=str(exc),
        )
        publish_task_progress(
            task_id, TaskStatus.FAILED, 0.0, "", symbol, error_message=str(exc))
        raise


@celery_app.task(name="beat.daily_health_check")
def health_check_beat() -> dict:
    """Celery Beat 定时健康检查（每日 3:17 AM 执行）。

    验证：
    - Celery worker 在线
    - Redis 连通
    - SQLite 可写
    """
    store = get_task_store()
    try:
        # 测试 SQLite 连通性
        store.list_tasks(page=1, page_size=1)
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "timestamp": utc_now_iso(),
        "db_ok": db_ok,
        "message": "daily health check completed",
    }


# ═══════════════════════════════════════════════════════════════
# 观察池扫描任务
# ═══════════════════════════════════════════════════════════════

@celery_app.task(name="beat.watchlist_scheduler_check")
def watchlist_scheduler_check() -> dict:
    """高频调度检查：cron 到期检查 + 条件触发器评估。

    由 Celery Beat 每 5 分钟触发一次。
    1. 检查 next_scan_at 到期的 items（cron 模式）
    2. 检查 condition_triggers 配置的 items（实时行情条件）
    3. 防重复：同一 item 30 分钟内不重复触发
    """
    from datetime import datetime, timezone
    store = get_watchlist_store()

    # 1. cron 到期检查 — 按 owner 分组创建 batch
    due_items = store.get_due_items()
    triggered_ids: set = set()
    due_by_owner: dict[str, list[dict]] = {}
    for item in due_items:
        owner = item.get("owner_username", "default")
        due_by_owner.setdefault(owner, []).append(item)
        triggered_ids.add(str(item["id"]))
    for owner, owner_items in due_by_owner.items():
        item_ids = [it["id"] for it in owner_items]
        batch_id = store.create_batch("scheduled", item_ids, owner_username=owner)
        for item in owner_items:
            scan_single_watchlist_item.delay(str(item["id"]), trigger_type="scheduled",
                                             batch_id=batch_id)

    # 2. 条件触发器检查 — use centralized evaluator
    from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers

    condition_triggered: dict[str, list[dict]] = {}  # owner -> items
    all_enabled = store.get_all_enabled_items()
    for item in all_enabled:
        item_id = str(item["id"])
        if item_id in triggered_ids:
            continue  # 已被 cron 触发，跳过

        sc = item.get("schedule_config") or {}
        ct = sc.get("condition_triggers") or {}
        if not ct or all(v is None or v == [] for v in ct.values()):
            continue

        # 防重复：距上次扫描至少 30 分钟
        last_scan = item.get("last_scan_at")
        if last_scan:
            try:
                last_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 1800:
                    continue
            except (ValueError, TypeError):
                pass

        # Fetch quote if needed
        quote = None
        need_quote = any(
            ct.get(k) is not None
            for k in ("price_change_pct", "volume_spike_ratio")
        )
        if need_quote:
            try:
                from services.data.qmt_realtime_quote import get_latest_price_data
                quote = get_latest_price_data(item["symbol"])
            except Exception as exc:
                logger.warning("获取实时行情失败（%s）: 条件触发器将无法评估价格/成交量条件: %s", item["symbol"], exc)

        # Use centralized evaluator
        eval_result = evaluate_condition_triggers(
            item, quote=quote, latest_result=item.get("last_trigger_snapshot")
        )

        if eval_result.triggered:
            owner = item.get("owner_username", "default")
            condition_triggered.setdefault(owner, []).append(item)
            triggered_ids.add(item_id)

    for owner, owner_items in condition_triggered.items():
        item_ids = [it["id"] for it in owner_items]
        batch_id = store.create_batch("condition", item_ids, owner_username=owner)
        for item in owner_items:
            scan_single_watchlist_item.delay(str(item["id"]), trigger_type="condition",
                                             batch_id=batch_id)

    return {"due_count": len(due_items), "condition_count": len(condition_triggered)}


@celery_app.task(
    name="beat.watchlist_scan",
    acks_late=True,
)
def scan_watchlist() -> dict:
    """收盘后批量扫描：扫描所有启用的观察项。

    由 Celery Beat 在工作日 15:07 触发。
    按 owner 分组创建批次，每个 owner 一个独立批次。
    """
    store = get_watchlist_store()
    items = store.get_all_enabled_items()
    if not items:
        return {"batch_id": None, "total": 0}

    # 按 owner 分组
    by_owner: dict[str, list[dict]] = {}
    for it in items:
        owner = it.get("owner_username", "default")
        by_owner.setdefault(owner, []).append(it)

    batch_ids = []
    for owner, owner_items in by_owner.items():
        item_ids = [it["id"] for it in owner_items]
        batch_id = store.create_batch("scheduled", item_ids, owner_username=owner)
        batch_ids.append(batch_id)
        for item in owner_items:
            scan_single_watchlist_item.delay(str(item["id"]), trigger_type="scheduled",
                                             batch_id=batch_id)

    return {"batch_ids": batch_ids, "total": len(items)}


def _update_and_publish_batch(
    wl_store, batch_id: str, item_id: str, symbol: str,
    status: str = "completed",
    item_score: float | None = None,
    item_rating: str | None = None,
) -> None:
    """更新 batch 进度计数并推送 WebSocket 消息。"""
    try:
        batch = wl_store.get_batch(batch_id)
        completed = batch.get("completed_items", 0)
        failed = batch.get("failed_items", 0)
        if status == "completed":
            completed += 1
        else:
            failed += 1
        updated = wl_store.update_batch_progress(batch_id, completed, failed)
        publish_batch_progress(
            batch_id=batch_id,
            status=updated.get("status", "running"),
            total_items=updated.get("total_items", 0),
            completed_items=completed,
            failed_items=failed,
            item_id=item_id,
            item_symbol=symbol,
            item_status=status,
            item_score=item_score,
            item_rating=item_rating,
        )
    except Exception:
        pass  # batch 进度更新失败不阻断主流程


def _extract_structured_risk_review(result: dict) -> dict | None:
    """Return structured risk_review for condition triggers, if available."""
    risk_review = result.get("risk_review")
    if isinstance(risk_review, dict):
        return risk_review

    debate_result = result.get("debate_result")
    if isinstance(debate_result, dict):
        debate_risk = debate_result.get("risk_review")
        if isinstance(debate_risk, dict):
            return debate_risk

    return None


@celery_app.task(
    name="watchlist.scan_single_item",
    max_retries=1,
    default_retry_delay=120,
    acks_late=True,
)
def scan_single_watchlist_item(item_id: str, trigger_type: str = "scheduled",
                                batch_id: str | None = None) -> dict:
    """扫描单个观察项。

    1. 创建 research_task 记录（关联 schedule_id = item_id）
    2. 调用现有研究 pipeline
    3. 更新观察项的扫描结果和 next_scan_at
    4. 更新 batch 进度并推送 WebSocket（如果提供了 batch_id）

    由 watchlist_scheduler_check / scan_watchlist / 手动触发共用。
    """
    wl_store = get_watchlist_store()
    task_store = get_task_store()

    try:
        item = wl_store.get_item(item_id)
    except KeyError:
        return {"item_id": item_id, "status": "skipped", "reason": "item not found"}

    symbol = item["symbol"]
    schedule_config = item.get("schedule_config") or {}

    # 检查暂停
    pause_until = schedule_config.get("pause_until")
    if pause_until and pause_until > utc_now_iso():
        return {"item_id": item_id, "status": "paused", "until": pause_until}

    # 创建 research_task 记录，created_by 继承 item 的 owner
    task_id = new_task_id()
    created_at = utc_now_iso()
    item_owner = item.get("owner_username", "default")
    task_store.create_task(
        task_id=task_id,
        symbol=symbol,
        data_source="qmt",
        use_llm=True,
        max_debate_rounds=3,
        use_graph=True,
        schedule_id=item_id,
        created_at=created_at,
        created_by=item_owner,
    )

    task_store.update_status(task_id, TaskStatus.RUNNING, started_at=utc_now_iso(),
                             progress=0.1, progress_message="开始加载数据...")
    publish_task_progress(task_id, TaskStatus.RUNNING, 0.1, "开始加载数据...", symbol)

    try:
        from services.orchestrator.single_asset_research import run_single_asset_research

        result = run_single_asset_research(
            symbol=symbol,
            use_llm=True,
            data_source="qmt",
            use_graph=True,
        )

        # 报告生成单独 try/except，失败不丢弃研究结果
        report_paths = {}
        try:
            report_paths = _generate_and_store_reports(result, task_id)
        except Exception as exc:
            logger.warning("报告生成失败（watchlist item %s, task %s）: %s", item_id, task_id, exc)

        completed_at = utc_now_iso()
        task_store.update_result(
            task_id,
            score=result.get("score"),
            rating=result.get("rating"),
            action=result.get("action"),
            final_opinion=result.get("final_opinion"),
            report_paths=report_paths or None,
            completed_at=completed_at,
        )
        task_store.update_status(task_id, TaskStatus.COMPLETED, progress=1.0,
                                 progress_message="研究完成。", completed_at=completed_at)
        publish_task_progress(
            task_id, TaskStatus.COMPLETED, 1.0, "研究完成。", symbol,
            score=result.get("score"), rating=result.get("rating"),
            action=result.get("action"),
        )

        wl_store.update_item_scan_result(
            item_id, task_id=task_id,
            score=result.get("score"),
            rating=result.get("rating"),
            action=result.get("action"),
        )

        # Build trigger snapshot for future condition evaluation
        trigger_snapshot = {
            "valuation_data": result.get("valuation_data"),
            "risk_review": _extract_structured_risk_review(result),
            "event_data": result.get("event_data"),
            "score": result.get("score"),
        }
        wl_store.update_item_trigger_snapshot(item_id, trigger_snapshot)

        # 计算下次扫描时间
        mode = schedule_config.get("mode", "cron")
        if mode == "cron":
            cron_expr = schedule_config.get("cron_expression", "0 9 * * 1-5")
            from apps.api.task_manager.manager import _compute_next_cron
            next_scan = _compute_next_cron(cron_expr)
            if next_scan:
                wl_store.update_item(item_id, next_scan_at=next_scan)

        # 更新 batch 进度并推送 WebSocket
        if batch_id:
            _update_and_publish_batch(wl_store, batch_id, item_id, symbol,
                                      status="completed",
                                      item_score=result.get("score"),
                                      item_rating=result.get("rating"))

        return {
            "item_id": item_id,
            "symbol": symbol,
            "task_id": task_id,
            "status": TaskStatus.COMPLETED,
            "score": result.get("score"),
            "rating": result.get("rating"),
        }

    except Exception as exc:
        task_store.update_status(task_id, TaskStatus.FAILED, progress=0.0,
                                 completed_at=utc_now_iso(), error_message=str(exc))
        publish_task_progress(
            task_id, TaskStatus.FAILED, 0.0, "", symbol, error_message=str(exc))
        # 更新 batch 进度（失败）
        if batch_id:
            _update_and_publish_batch(wl_store, batch_id, item_id, symbol,
                                      status="failed")
        raise


# ═══════════════════════════════════════════════════════════════
# 网页新闻质量监控 Beat 任务（默认关闭）
# ═══════════════════════════════════════════════════════════════

@celery_app.task(name="beat.web_news_quality_monitor")
def web_news_quality_monitor_beat() -> dict:
    """网页新闻/舆情每日质量监控 + 趋势分析。

    默认关闭。通过环境变量 WEB_NEWS_QUALITY_BEAT_ENABLED=true 启用。
    不影响主研究链路，仅在后台运行监控脚本。
    """
    import os
    import subprocess

    if os.getenv("WEB_NEWS_QUALITY_BEAT_ENABLED", "").lower() not in ("1", "true", "yes"):
        return {"skipped": True, "reason": "WEB_NEWS_QUALITY_BEAT_ENABLED not set"}

    python_exe = sys.executable

    results = {"monitor": None, "trend": None}

    # Run monitor
    try:
        monitor_result = subprocess.run(
            [python_exe, str(PROJECT_ROOT / "scripts" / "run_web_news_quality_monitor.py"),
             "--output-dir", str(PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality" / "live")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
        )
        results["monitor"] = {
            "exit_code": monitor_result.returncode,
            "stdout_tail": monitor_result.stdout[-500:] if monitor_result.stdout else "",
            "stderr_tail": monitor_result.stderr[-500:] if monitor_result.stderr else "",
        }
    except Exception as exc:
        results["monitor"] = {"exit_code": -1, "error": str(exc)}

    # Run trend analyzer
    try:
        trend_result = subprocess.run(
            [python_exe, str(PROJECT_ROOT / "scripts" / "analyze_web_news_quality_trends.py"),
             "--output-dir", str(PROJECT_ROOT / "storage" / "artifacts" / "web_news_quality" / "live")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60,
        )
        results["trend"] = {
            "exit_code": trend_result.returncode,
            "stdout_tail": trend_result.stdout[-500:] if trend_result.stdout else "",
            "stderr_tail": trend_result.stderr[-500:] if trend_result.stderr else "",
        }
    except Exception as exc:
        results["trend"] = {"exit_code": -1, "error": str(exc)}

    return {
        "timestamp": utc_now_iso(),
        "results": results,
    }
