"""WebSocket 端点 — 实时进度推送。

权限规则：
- /ws/task/{task_id}：普通用户只能订阅自己的任务；管理员可订阅任意任务。
- /ws/batch/{batch_id}：普通用户只能订阅自己的批次；管理员可订阅任意批次。
- /ws/events：仅管理员可订阅（全局事件流存在跨用户泄露风险）。
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

    权限：普通用户只能订阅自己的任务；管理员可订阅任意任务。
    """
    user = await _ws_auth(websocket, token)
    if not user:
        return

    # 权限校验：普通用户只能订阅自己的任务
    try:
        task = get_task_store().get_task(task_id)
    except KeyError:
        await websocket.accept()
        await websocket.send_json({"type": "error", "detail": f"任务不存在：{task_id}"})
        await websocket.close()
        return

    if user.get("role") != "admin" and task.get("created_by", "default") != user["username"]:
        await websocket.close(code=4003, reason="无权访问该任务")
        return

    await websocket.accept()

    current = _build_progress_message(task)
    await websocket.send_json(current)

    if task["status"] in ("completed", "failed", "cancelled"):
        await websocket.close()
        return

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

    权限：普通用户只能订阅自己的批次；管理员可订阅任意批次。
    """
    user = await _ws_auth(websocket, token)
    if not user:
        return

    # 权限校验
    try:
        batch = get_watchlist_store().get_batch(batch_id)
    except KeyError:
        await websocket.accept()
        await websocket.send_json({"type": "error", "detail": f"批次不存在：{batch_id}"})
        await websocket.close()
        return

    if user.get("role") != "admin" and batch.get("owner_username", "default") != user["username"]:
        await websocket.close(code=4003, reason="无权访问该批次")
        return

    await websocket.accept()

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

    if batch["status"] == "completed":
        await websocket.close()
        return

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
    """全局事件流 — 仅管理员可订阅。

    普通用户订阅此端点会被拒绝，避免跨用户事件泄露。
    """
    user = await _ws_auth(websocket, token)
    if not user:
        return

    if user.get("role") != "admin":
        await websocket.close(code=4003, reason="仅管理员可订阅全局事件流")
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
