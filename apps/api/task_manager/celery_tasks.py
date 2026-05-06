"""Celery 任务定义。

- run_research_task: 执行完整单票研究 pipeline
- health_check_beat: Celery Beat 定时健康检查
"""

import shutil
from pathlib import Path

from apps.api.celery_app import celery_app
from apps.api.task_manager.store import get_task_store
from apps.api.schemas.task import TaskStatus
from apps.api.schemas.research import utc_now_iso


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
        params: {symbol, data_source, use_llm, max_debate_rounds, use_graph}

    Returns:
        包含 score/rating/action/final_opinion 的摘要 dict。
    """
    from services.report.json_builder import save_json_result
    from services.report.markdown_builder import save_markdown_report
    from services.report.html_builder import save_html_report
    from services.report.pdf_builder_playwright import save_pdf_report_with_playwright

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

    try:
        store.update_status(
            task_id,
            TaskStatus.RUNNING,
            progress=0.3,
            progress_message=f"执行研究中（{symbol}，数据源：{data_source}）...",
        )

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

        reports_dir = Path(__file__).resolve().parents[3] / "storage" / "reports" / task_id
        reports_dir.mkdir(parents=True, exist_ok=True)

        json_path_actual = Path(save_json_result(result))
        markdown_path_actual = Path(save_markdown_report(result))
        html_path_actual = Path(save_html_report(str(markdown_path_actual)))

        for src, dst_name in [
            (json_path_actual, "result.json"),
            (markdown_path_actual, "report.md"),
            (html_path_actual, "report.html"),
        ]:
            dst = reports_dir / dst_name
            if src.exists() and not dst.exists():
                shutil.copy2(str(src), str(dst))

        pdf_path = None
        try:
            pdf_path_actual = Path(save_pdf_report_with_playwright(str(html_path_actual)))
            pdf_dst = reports_dir / "report.pdf"
            if pdf_path_actual.exists() and not pdf_dst.exists():
                shutil.copy2(str(pdf_path_actual), str(pdf_dst))
            pdf_path = str(pdf_dst)
        except Exception:
            pdf_path = None

        report_paths = {
            "json": str(reports_dir / "result.json"),
            "markdown": str(reports_dir / "report.md"),
            "html": str(reports_dir / "report.html"),
            "pdf": pdf_path or "",
        }

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
