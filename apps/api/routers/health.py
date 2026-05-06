"""健康检查路由。"""

import json

from fastapi import APIRouter, Response
from apps.api.task_manager.store import get_task_store
from apps.api.celery_app import REDIS_URL

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health_check():
    """服务健康检查。检查项：API、DB、Redis。"""
    import redis

    checks = {
        "api": {"status": "ok"},
        "db": {"status": "unknown"},
        "redis": {"status": "unknown"},
    }

    try:
        store = get_task_store()
        store.list_tasks(page=1, page_size=1)
        checks["db"] = {"status": "ok"}
    except Exception as exc:
        checks["db"] = {"status": "error", "detail": str(exc)}

    try:
        r = redis.from_url(REDIS_URL)
        r.ping()
        r.close()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": str(exc)}

    all_ok = all(c["status"] == "ok" for c in checks.values())
    status_code = 200 if all_ok else 503

    return Response(
        content=json.dumps(checks),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/api/v1/health/ready")
async def readiness_check():
    """Kubernetes 风格的就绪检查（仅 DB）。"""
    try:
        store = get_task_store()
        store.list_tasks(page=1, page_size=1)
        return {"status": "ready"}
    except Exception as exc:
        return Response(
            content=json.dumps({"status": "not_ready", "detail": str(exc)}),
            status_code=503,
            media_type="application/json",
        )
