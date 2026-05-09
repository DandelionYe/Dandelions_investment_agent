"""WebSocket 端点 — 实时进度推送。

端点：
- ws/task/{task_id}      — 单票研究任务进度
- ws/batch/{batch_id}    — 观察池批量扫描进度
- ws/events              — 全局事件流
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)

from apps.api.task_manager.store import get_task_store, get_watchlist_store
from apps.api.websocket.redis_pubsub import get_async_redis
from apps.api.auth.security import decode_token
from apps.api.task_manager.store import get_user_store

router = APIRouter(tags=["websocket"])


async def _ws_auth(websocket: WebSocket, token: str) -> dict | None:
    """验证 WebSocket token，失败时关闭连接并返回 None。"""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="无效的 token 类型")
            return None
        username = payload.get("sub")
        if not username:
            await websocket.close(code=4001, reason="token 无效")
            return None
        user = get_user_store().get_user_by_username(username)
        if not user or not user.get("enabled"):
            await websocket.close(code=4001, reason="用户不存在或已被禁用")
            return None
        return user
    except Exception:
        await websocket.close(code=4001, reason="token 无效或已过期")
        return None


def _build_progress_message(task: dict) -> dict:
    """从 SQLite task 行构建标准进度消息。"""
    status = task.get("status", "pending")
    type_map = {"pending": "progress", "running": "progress",
                "completed": "completed", "failed": "failed", "cancelled": "cancelled"}
    return {
        "type": type_map.get(status, "progress"),
        "task_id": task["id"],
        "symbol": task.get("symbol", ""),
        "status": status,
        "progress": task.get("progress", 0.0),
        "progress_message": task.get("progress_message", ""),
        "score": task.get("score"),
        "rating": task.get("rating"),
        "action": task.get("action"),
        "error_message": task.get("error_message"),
        "timestamp": task.get("completed_at") or task.get("started_at") or task.get("created_at", ""),
    }


@router.websocket("/ws/task/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: str, token: str = Query(...)):
    """订阅单票研究任务的实时进度。

    流程：
    0. 验证 query string 中的 token
    1. 接受连接后，先从 SQLite 读取当前最新状态并推送
    2. 若任务已终结（completed/failed/cancelled），推送后立即关闭
    3. 否则订阅 Redis 频道 task:{task_id}，持续推送增量更新
    4. 收到终结状态或客户端断开时关闭连接
    """
    if not await _ws_auth(websocket, token):
        return
    await websocket.accept()

    # 1. 推送当前最新状态
    try:
        task = get_task_store().get_task(task_id)
    except KeyError:
        await websocket.send_json({"type": "error", "detail": f"任务不存在：{task_id}"})
        await websocket.close()
        return

    current = _build_progress_message(task)
    await websocket.send_json(current)

    # 2. 如果任务已终结，推送后关闭
    if task["status"] in ("completed", "failed", "cancelled"):
        await websocket.close()
        return

    # 3. 订阅 Redis 频道
    redis = await get_async_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"task:{task_id}")

    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                await websocket.send_json(data)
                if data.get("status") in ("completed", "failed", "cancelled"):
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket 错误: %s", exc)
    finally:
        await pubsub.unsubscribe(f"task:{task_id}")
        await websocket.close()


@router.websocket("/ws/batch/{batch_id}")
async def ws_batch_progress(websocket: WebSocket, batch_id: str, token: str = Query(...)):
    """订阅观察池批量扫描的实时进度。

    流程与 ws_task_progress 类似，但订阅 batch:{batch_id} 频道。
    推送消息包含批量整体进度和各子任务的完成/失败事件。
    """
    if not await _ws_auth(websocket, token):
        return
    await websocket.accept()

    # 1. 推送当前最新批量状态
    try:
        batch = get_watchlist_store().get_batch(batch_id)
    except KeyError:
        await websocket.send_json({"type": "error", "detail": f"批次不存在：{batch_id}"})
        await websocket.close()
        return

    await websocket.send_json({
        "type": "progress",
        "batch_id": batch["id"],
        "status": batch["status"],
        "total_items": batch["total_items"],
        "completed_items": batch["completed_items"],
        "failed_items": batch["failed_items"],
        "item_ids": batch.get("item_ids", []),
        "timestamp": batch.get("completed_at") or batch.get("created_at", ""),
    })

    # 2. 如果批次已完成，关闭
    if batch["status"] == "completed":
        await websocket.close()
        return

    # 3. 订阅 Redis 频道
    redis = await get_async_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"batch:{batch_id}")

    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                await websocket.send_json(data)
                if data.get("status") == "completed":
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket 错误: %s", exc)
    finally:
        await pubsub.unsubscribe(f"batch:{batch_id}")
        await websocket.close()


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, token: str = Query(...)):
    """全局事件流 — 接收所有任务的进度事件。

    用于仪表盘等需要全局视图的场景。
    注意：此端点不推送历史状态，仅推送连接后的增量事件。
    """
    if not await _ws_auth(websocket, token):
        return
    await websocket.accept()
    redis = await get_async_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("events")

    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                await websocket.send_json(data)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket 错误: %s", exc)
    finally:
        await pubsub.unsubscribe("events")
        await websocket.close()
