"""TaskManager / WatchlistManager — 业务逻辑层，封装任务创建/查询/取消 和 观察池管理。

供 FastAPI routers 调用，连接 Store + Celery。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from apps.api.task_manager.store import get_task_store, get_watchlist_store, TaskStore, WatchlistStore
from apps.api.schemas.research import ResearchRequest, utc_now_iso, new_task_id
from apps.api.schemas.task import TaskStatus


class TaskManager:
    """研究任务管理器。"""

    def __init__(self, store: TaskStore | None = None):
        self.store = store or get_task_store()

    def submit(self, req: ResearchRequest, created_by: str = "default") -> dict:
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
            celery_task_id=None,
            created_at=created_at,
            created_by=created_by,
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

    def get_status(self, task_id: str, username: str | None = None) -> dict:
        """查询任务状态。"""
        task = self.store.get_task_for_user(task_id, username) if username else self.store.get_task(task_id)
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

    def get_result(self, task_id: str, username: str | None = None) -> dict:
        """获取完整研究结果（需已完成的 task）。"""
        task = self.store.get_task_for_user(task_id, username) if username else self.store.get_task(task_id)
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

    def cancel(self, task_id: str, username: str | None = None) -> dict:
        """取消任务（pending 或 running 状态）。"""
        from apps.api.celery_app import celery_app

        task = self.store.get_task_for_user(task_id, username) if username else self.store.get_task(task_id)
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
        username: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """查询历史任务列表（分页）。"""
        tasks, total = self.store.list_tasks(
            symbol=symbol,
            status=status,
            username=username,
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

    def get_report_info(self, task_id: str, username: str | None = None) -> dict:
        """获取任务关联的报告文件信息。"""
        task = self.store.get_task_for_user(task_id, username) if username else self.store.get_task(task_id)
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


# ═══════════════════════════════════════════════════════════════
# 观察池管理器
# ═══════════════════════════════════════════════════════════════


def _compute_next_cron(cron_expression: str) -> Optional[str]:
    """基于 crontab 表达式计算下次扫描时间（Asia/Shanghai 时区）。

    使用当前时间作为基准，调用 croniter 计算下一次匹配时间。
    返回 ISO 8601 UTC 字符串。
    """
    try:
        from croniter import croniter
    except ImportError:
        return None
    tz = ZoneInfo("Asia/Shanghai")
    now_cst = datetime.now(tz)
    cron = croniter(cron_expression, now_cst)
    next_cst = cron.get_next(datetime)
    return next_cst.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WatchlistManager:
    """观察池业务逻辑层。"""

    def __init__(self, store: WatchlistStore | None = None):
        self.store = store or get_watchlist_store()

    # ── 文件夹 ──────────────────────────────────────────────

    def create_folder(self, name: str, description: str = "", icon: str = "folder",
                      sort_order: int = 0) -> dict:
        return self.store.create_folder(name, description, icon, sort_order)

    def list_folders(self) -> list[dict]:
        return self.store.list_folders()

    def get_folder(self, folder_id: str) -> dict:
        return self.store.get_folder(folder_id)

    def update_folder(self, folder_id: str, **kwargs) -> dict:
        return self.store.update_folder(folder_id, **kwargs)

    def delete_folder(self, folder_id: str) -> None:
        self.store.delete_folder(folder_id)

    # ── 观察项 ──────────────────────────────────────────────

    def add_item(
        self,
        symbol: str,
        asset_type: str,
        folder_id: str,
        schedule_config: dict | None = None,
        notes: str = "",
        target_action: str = "观察",
        asset_name: str = "",
        tag_ids: list[str] | None = None,
    ) -> dict:
        item = self.store.add_item(
            symbol=symbol,
            asset_type=asset_type,
            folder_id=folder_id,
            schedule_config=schedule_config,
            notes=notes,
            target_action=target_action,
            asset_name=asset_name,
            tag_ids=tag_ids,
        )
        # 计算初始 next_scan_at
        sc = item.get("schedule_config", {})
        if sc.get("mode") == "cron":
            next_scan = _compute_next_cron(sc.get("cron_expression", "0 9 * * 1-5"))
            if next_scan:
                self.store.update_item(item["id"], next_scan_at=next_scan)
                item["next_scan_at"] = next_scan
        return item

    def get_item(self, item_id: str) -> dict:
        item = self.store.get_item(item_id)
        item["scan_history"] = self.store.get_item_scan_history(item_id)
        return item

    def list_items(
        self,
        folder_id: str | None = None,
        tag_id: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        return self.store.list_items(folder_id, tag_id, enabled, page, page_size)

    def update_item(self, item_id: str, **kwargs) -> dict:
        if "schedule_config" in kwargs:
            sc = kwargs["schedule_config"]
            if isinstance(sc, dict) and sc.get("mode") == "cron":
                next_scan = _compute_next_cron(sc.get("cron_expression", "0 9 * * 1-5"))
                kwargs["next_scan_at"] = next_scan
            elif isinstance(sc, dict) and sc.get("mode") == "manual_only":
                kwargs["next_scan_at"] = None
        if "tag_ids" in kwargs:
            tag_ids = kwargs.pop("tag_ids")
            self.store.set_item_tags(item_id, tag_ids)
        return self.store.update_item(item_id, **kwargs)

    def remove_item(self, item_id: str) -> None:
        self.store.remove_item(item_id)

    # ── 标签 ────────────────────────────────────────────────

    def create_tag(self, name: str, color: str = "#6366f1") -> dict:
        return self.store.create_tag(name, color)

    def list_tags(self) -> list[dict]:
        return self.store.list_tags()

    def update_tag(self, tag_id: str, **kwargs) -> dict:
        return self.store.update_tag(tag_id, **kwargs)

    def delete_tag(self, tag_id: str) -> None:
        self.store.delete_tag(tag_id)

    # ── 扫描 ────────────────────────────────────────────────

    def trigger_scan(self, item_ids: list[str] | None = None,
                     folder_id: str | None = None,
                     trigger_type: str = "manual") -> dict:
        items: list[dict] = []
        if item_ids:
            items = [self.store.get_item(iid) for iid in item_ids]
        elif folder_id:
            items, _ = self.store.list_items(folder_id=folder_id, enabled=True)
        else:
            items = self.store.get_all_enabled_items()

        if not items:
            raise ValueError("没有可扫描的标的。")

        item_id_list = [it["id"] for it in items]
        batch_id = self.store.create_batch(trigger_type, item_id_list)

        from apps.api.task_manager.celery_tasks import scan_single_watchlist_item
        for item in items:
            scan_single_watchlist_item.delay(item["id"], trigger_type=trigger_type)

        return {
            "batch_id": batch_id,
            "trigger_type": trigger_type,
            "total_items": len(items),
            "status": "running",
            "created_at": self.store.get_batch(batch_id)["created_at"],
        }

    def get_scan_progress(self, batch_id: str) -> dict:
        return self.store.get_batch(batch_id)

    def get_scan_history(
        self,
        symbol: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        rating: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """查询已完成的扫描结果。

        由于扫描结果存储在 research_tasks 中（schedule_id 链接到 watchlist item），
        我们通过 task_store 来查询。"""
        task_store = get_task_store()
        tasks, total = task_store.list_tasks(
            symbol=symbol,
            status=TaskStatus.COMPLETED,
            page=page,
            page_size=page_size,
        )
        results = []
        for t in tasks:
            if (min_score is not None and (t.get("score") or 0) < min_score):
                continue
            if (max_score is not None and (t.get("score") or 0) > max_score):
                continue
            if rating and t.get("rating") != rating:
                continue
            results.append({
                "task_id": t["id"],
                "symbol": t["symbol"],
                "score": t.get("score"),
                "rating": t.get("rating"),
                "action": t.get("action"),
                "status": t["status"],
                "created_at": t["created_at"],
                "completed_at": t.get("completed_at"),
            })
        return {"results": results, "total": len(results), "page": page, "page_size": page_size}
