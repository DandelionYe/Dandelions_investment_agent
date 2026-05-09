"""Dandelions 投研智能体 — FastAPI 网关入口。

启动:
    uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from apps.api.limiter import limiter

import os

from apps.api.routers import research, reports, health, watchlist, ws, auth
from apps.api.middleware.error_handler import (
    global_error_handler,
    key_error_handler,
    not_found_handler,
    value_error_handler,
)
from apps.api.task_manager.store import get_task_store, get_watchlist_store, get_user_store
from apps.api.auth.security import hash_password
from apps.api.websocket.redis_pubsub import get_async_redis, close_async_redis


def _seed_admin_user() -> None:
    """首次启动时自动创建管理员用户（通过环境变量配置凭据）。

    要求 AUTH_ADMIN_USER 和 AUTH_ADMIN_PASS 两个环境变量均已设置。
    若未设置 AUTH_ADMIN_PASS，应用将拒绝启动。
    """
    admin_user = os.getenv("AUTH_ADMIN_USER", "admin")
    admin_pass = os.getenv("AUTH_ADMIN_PASS")
    if not admin_pass:
        print("⚠  AUTH_ADMIN_PASS 未设置。")
        print("   请设置环境变量，例如：$env:AUTH_ADMIN_PASS = 'your-secure-password'")
        print("   或生成随机密码：python -c \"import secrets; print(secrets.token_urlsafe(16))\"")
        raise RuntimeError(
            "AUTH_ADMIN_PASS 环境变量未设置。"
            "请生成一个安全的管理员密码并设置该环境变量后重新启动。"
        )
    store = get_user_store()
    if not store.get_user_by_username(admin_user):
        store.create_user(
            username=admin_user,
            password_hash=hash_password(admin_pass),
            role="admin",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB/Redis/Admin，关闭时清理资源。"""
    get_task_store()
    get_watchlist_store()
    get_user_store()
    _seed_admin_user()
    await get_async_redis()
    yield
    await close_async_redis()


app = FastAPI(
    title="Dandelions 投研智能体 API",
    description="单票量化研究 + LLM 辩论 + 报告生成 REST API",
    version="1.0.0",
    lifespan=lifespan,
)

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 速率限制
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 全局异常处理
app.add_exception_handler(Exception, global_error_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(KeyError, key_error_handler)
app.add_exception_handler(404, not_found_handler)

# 挂载路由
app.include_router(research.router)
app.include_router(reports.router)
app.include_router(health.router)
app.include_router(watchlist.router)
app.include_router(ws.router)
app.include_router(auth.router)


@app.get("/")
async def root():
    return {
        "service": "Dandelions 投研智能体 API",
        "version": "1.0.0",
        "docs": "/docs",
    }
