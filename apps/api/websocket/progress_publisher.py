"""进度消息发布工具 — 供 Celery 任务调用。

提供统一的进度消息格式和发布接口。
"""

from datetime import datetime, timezone

from apps.api.websocket.redis_pubsub import publish_progress_sync


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status_to_type(status: str) -> str:
    """将任务状态映射为 WebSocket 消息 type 字段。"""
    mapping = {
        "pending": "progress",
        "running": "progress",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "progress")


def publish_task_progress(
    task_id: str,
    status: str,
    progress: float,
    progress_message: str = "",
    symbol: str = "",
    score: float | None = None,
    rating: str | None = None,
    action: str | None = None,
    error_message: str | None = None,
) -> None:
    """发布单票研究任务进度到 Redis Pub/Sub。

    在 Celery 任务中每次 store.update_status() 后调用。
    """
    msg = {
        "type": _status_to_type(status),
        "task_id": task_id,
        "symbol": symbol,
        "status": status,
        "progress": progress,
        "progress_message": progress_message,
        "score": score,
        "rating": rating,
        "action": action,
        "error_message": error_message,
        "timestamp": _utc_now_iso(),
    }
    publish_progress_sync(f"task:{task_id}", msg)
    publish_progress_sync("events", msg)


def publish_batch_progress(
    batch_id: str,
    status: str,
    total_items: int,
    completed_items: int,
    failed_items: int,
    item_id: str = "",
    item_symbol: str = "",
    item_status: str = "",
    item_score: float | None = None,
    item_rating: str | None = None,
) -> None:
    """发布批量扫描进度到 Redis Pub/Sub。

    在 scan_single_watchlist_item 完成/失败时调用。
    """
    msg = {
        "type": _status_to_type(status),
        "batch_id": batch_id,
        "status": status,
        "total_items": total_items,
        "completed_items": completed_items,
        "failed_items": failed_items,
        "item_id": item_id,
        "item_symbol": item_symbol,
        "item_status": item_status,
        "item_score": item_score,
        "item_rating": item_rating,
        "timestamp": _utc_now_iso(),
    }
    publish_progress_sync(f"batch:{batch_id}", msg)
    publish_progress_sync("events", msg)
