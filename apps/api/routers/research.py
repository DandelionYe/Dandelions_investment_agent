"""研究任务 API 路由。"""

from fastapi import APIRouter, Query, HTTPException, Depends

from apps.api.schemas.research import (
    ResearchRequest,
    ResearchAcceptResponse,
    TaskStatusResponse,
    TaskHistoryResponse,
)
from apps.api.task_manager.manager import TaskManager, TaskQueueUnavailableError
from apps.api.auth.dependencies import get_current_user

router = APIRouter(tags=["research"])


def _manager() -> TaskManager:
    return TaskManager()


@router.post(
    "/api/v1/research/single",
    response_model=ResearchAcceptResponse,
    status_code=202,
)
async def submit_research(req: ResearchRequest, user: dict = Depends(get_current_user)):
    """提交单票研究任务。

    任务提交后立即返回 task_id，研究过程在 Celery worker 中异步执行。
    使用 GET /api/v1/research/{task_id} 查询进度。
    """
    try:
        return _manager().submit(req, created_by=user["username"])
    except TaskQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get(
    "/api/v1/research/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: str, user: dict = Depends(get_current_user)):
    """查询研究任务状态和进度。

    - pending: 排队中
    - running: 执行中（含 progress 0.0-1.0）
    - completed: 已完成（含 score/rating/action）
    - failed: 失败（含 error_message）
    - cancelled: 已取消
    """
    try:
        return _manager().get_status(task_id, username=user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}")


@router.get("/api/v1/research/{task_id}/result")
async def get_task_result(task_id: str, user: dict = Depends(get_current_user)):
    """获取完整研究结果（JSON）。仅 completed 状态可用。"""
    try:
        return _manager().get_result(task_id, username=user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/api/v1/research/{task_id}")
async def cancel_task(task_id: str, user: dict = Depends(get_current_user)):
    """取消进行中的研究任务。"""
    try:
        return _manager().cancel(task_id, username=user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/api/v1/research/history",
    response_model=TaskHistoryResponse,
)
async def list_task_history(
    symbol: str | None = Query(None, description="按标的代码筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    user: dict = Depends(get_current_user),
):
    """查询历史研究任务列表（分页）。非管理员用户仅可查看自己的任务。"""
    username = user["username"] if user.get("role") != "admin" else None
    return _manager().list_history(
        symbol=symbol,
        status=status,
        username=username,
        page=page,
        page_size=page_size,
    )
