"""Dandelions 投研智能体 — FastAPI 网关入口。

启动:
    uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import research, reports, health
from apps.api.middleware.error_handler import (
    global_error_handler,
    key_error_handler,
    not_found_handler,
    value_error_handler,
)
from apps.api.task_manager.store import get_task_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB，关闭时清理资源。"""
    get_task_store()
    yield


app = FastAPI(
    title="Dandelions 投研智能体 API",
    description="单票量化研究 + LLM 辩论 + 报告生成 REST API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 开发阶段允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
app.add_exception_handler(Exception, global_error_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(KeyError, key_error_handler)
app.add_exception_handler(404, not_found_handler)

# 挂载路由
app.include_router(research.router)
app.include_router(reports.router)
app.include_router(health.router)


@app.get("/")
async def root():
    return {
        "service": "Dandelions 投研智能体 API",
        "version": "1.0.0",
        "docs": "/docs",
    }
