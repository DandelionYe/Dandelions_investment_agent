"""TaskManager — 业务逻辑层，封装任务创建/查询/取消。

供 FastAPI routers 调用，连接 TaskStore + Celery。
"""

import json
from pathlib import Path

from apps.api.task_manager.store import get_task_store, TaskStore
from apps.api.schemas.research import ResearchRequest, utc_now_iso, new_task_id
from apps.api.schemas.task import TaskStatus


class TaskManager:
    """研究任务管理器。"""

    def __init__(self, store: TaskStore | None = None):
        self.store = store or get_task_store()

    def submit(self, req: ResearchRequest) -> dict:
        """提交研究任务，返回 {task_id, status, created_at}。

        1. 创建 task 记录（status=pending）
        2. 发送到 Celery 队列
        3. 立即返回 task_id
        """
        task_id = new_task_id()
        created_at = utc_now_iso()

        self.store.create_task(
            task_id=task_id,
            symbol=req.symbol,
            data_source=req.data_source,
            use_llm=req.use_llm,
            max_debate_rounds=req.max_debate_rounds,
            use_graph=req.use_graph,
            celery_task_id=None,  # 先创建记录，再发 celery
            created_at=created_at,
        )

        # 发送到 Celery
        from apps.api.task_manager.celery_tasks import run_research_task

        celery_result = run_research_task.apply_async(
            kwargs={
                "task_id": task_id,
                "params": req.model_dump(),
            },
            task_id=task_id,
        )

        # 回填 celery_task_id
        self.store.update_status(
            task_id,
            TaskStatus.PENDING,
            celery_task_id=celery_result.id,
        )

        return {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "created_at": created_at,
        }

    def get_status(self, task_id: str) -> dict:
        """查询任务状态。"""
        task = self.store.get_task(task_id)
        return {
            "task_id": task["id"],
            "symbol": task["symbol"],
            "status": task["status"],
            "progress": task.get("progress", 0.0),
            "progress_message": task.get("progress_message"),
            "score": task.get("score"),
            "rating": task.get("rating"),
            "action": task.get("action"),
            "created_at": task["created_at"],
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "error_message": task.get("error_message"),
        }

    def get_result(self, task_id: str) -> dict:
        """获取完整研究结果（需已完成的 task）。"""
        task = self.store.get_task(task_id)
        if task["status"] != TaskStatus.COMPLETED:
            raise ValueError(
                f"任务尚未完成（当前状态：{task['status']}），无法获取结果。"
            )

        report_paths = task.get("report_paths") or {}
        json_path = report_paths.get("json", "")
        if json_path and Path(json_path).exists():
            return json.loads(Path(json_path).read_text(encoding="utf-8"))

        # fallback：如果没有单独 JSON，返回 DB 摘要
        return {
            "task_id": task["id"],
            "symbol": task["symbol"],
            "score": task.get("score"),
            "rating": task.get("rating"),
            "action": task.get("action"),
            "final_opinion": task.get("final_opinion"),
            "status": task["status"],
            "created_at": task["created_at"],
            "completed_at": task.get("completed_at"),
        }

    def cancel(self, task_id: str) -> dict:
        """取消任务（pending 或 running 状态）。"""
        from apps.api.celery_app import celery_app

        task = self.store.get_task(task_id)
        if task["status"] in (TaskStatus.PENDING, TaskStatus.RUNNING):
            celery_task_id = task.get("celery_task_id")
            if celery_task_id:
                celery_app.control.revoke(celery_task_id, terminate=True)
        self.store.cancel_task(task_id)
        return self.get_status(task_id)

    def list_history(
        self,
        symbol: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """查询历史任务列表（分页）。"""
        tasks, total = self.store.list_tasks(
            symbol=symbol,
            status=status,
            page=page,
            page_size=page_size,
        )
        return {
            "tasks": [
                {
                    "task_id": t["id"],
                    "symbol": t["symbol"],
                    "data_source": t.get("data_source", ""),
                    "use_llm": t.get("use_llm", True),
                    "status": t["status"],
                    "score": t.get("score"),
                    "rating": t.get("rating"),
                    "action": t.get("action"),
                    "final_opinion": t.get("final_opinion"),
                    "created_at": t["created_at"],
                    "started_at": t.get("started_at"),
                    "completed_at": t.get("completed_at"),
                    "error_message": t.get("error_message"),
                }
                for t in tasks
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_report_info(self, task_id: str) -> dict:
        """获取任务关联的报告文件信息。"""
        task = self.store.get_task(task_id)
        report_paths = task.get("report_paths") or {}
        return {
            "task_id": task_id,
            "formats": [
                fmt
                for fmt in ["json", "markdown", "html", "pdf"]
                if report_paths.get(fmt) and Path(report_paths[fmt]).exists()
            ],
            "json_path": report_paths.get("json"),
            "markdown_path": report_paths.get("markdown"),
            "html_path": report_paths.get("html"),
            "pdf_path": report_paths.get("pdf"),
        }
