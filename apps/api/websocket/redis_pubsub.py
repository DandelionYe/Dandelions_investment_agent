"""Redis 发布/订阅 客户端封装。

双客户端设计：
- 同步客户端：供 Celery worker 发布进度消息（短连接，每次 publish 创建/关闭）
- 异步客户端：供 FastAPI WebSocket handler 订阅频道（长连接，进程级单例）
"""

import os
import json
import redis
import redis.asyncio as aioredis
from dotenv import load_dotenv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
PUBSUB_DB = 2  # 独立 DB：0=Celery broker, 1=Celery backend, 2=WebSocket pub/sub

# ── 异步客户端（FastAPI 侧，进程级单例）───────────────────────

_async_redis: aioredis.Redis | None = None


async def get_async_redis() -> aioredis.Redis:
    """获取或创建异步 Redis 客户端（进程级单例）。"""
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            REDIS_URL, db=PUBSUB_DB, decode_responses=True
        )
    return _async_redis


async def close_async_redis() -> None:
    """关闭异步 Redis 客户端。"""
    global _async_redis
    if _async_redis:
        await _async_redis.close()
        _async_redis = None


# ── 同步发布函数（Celery 侧）───────────────────────────────────


_sync_pool: redis.ConnectionPool | None = None


def _get_sync_pool() -> redis.ConnectionPool:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis.ConnectionPool.from_url(REDIS_URL, db=PUBSUB_DB, decode_responses=True)
    return _sync_pool


def publish_progress_sync(channel: str, message: dict) -> None:
    """Celery worker 调用此函数发布进度消息到 Redis Pub/Sub。

    使用连接池复用连接，发布失败不抛异常，保证主研究流程不受影响。
    """
    try:
        r = redis.Redis(connection_pool=_get_sync_pool())
        r.publish(channel, json.dumps(message, ensure_ascii=False))
    except Exception:
        pass
