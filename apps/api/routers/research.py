"""研究任务 API 路由。

权限规则：
- 普通用户只能访问 created_by == 自己的任务。
- 管理员可访问所有任务。
- history 列表：普通用户只看自己的；管理员默认看全部，可按 username 过滤。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.auth.dependencies import get_current_user
from apps.api.auth.rbac import is_admin, scope_username
from apps.api.schemas.research import (
    ResearchAcceptResponse,
    ResearchRequest,
    TaskHistoryResponse,
    TaskStatusResponse,
)
from apps.api.task_manager.manager import TaskManager, TaskQueueUnavailableError

router = APIRouter(tags=["research"])
CurrentUser = Annotated[dict, Depends(get_current_user)]


def _manager() -> TaskManager:
    return TaskManager()


@router.post(
    "/api/v1/research/single",
    response_model=ResearchAcceptResponse,
    status_code=202,
)
async def submit_research(req: ResearchRequest, user: CurrentUser):
    """提交单票研究任务（created_by = 当前用户）。"""
    try:
        return _manager().submit(req, created_by=user["username"])
    except TaskQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/api/v1/research/history",
    response_model=TaskHistoryResponse,
)
async def list_task_history(
    user: CurrentUser,
    symbol: str | None = Query(None, description="按标的代码筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    username: str | None = Query(None, description="管理员可指定用户名过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """查询历史研究任务列表。普通用户只看自己的，管理员可看全部。"""
    owner = _resolve_owner(user, username)
    return _manager().list_history(
        symbol=symbol,
        status=status,
        username=owner,
        page=page,
        page_size=page_size,
    )


def _resolve_owner(user: dict, username_param: str | None) -> str | None:
    """解析 owner 过滤参数。"""
    if is_admin(user):
        return username_param  # None → 全部
    return user["username"]


@router.get(
    "/api/v1/research/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: str, user: CurrentUser):
    """查询研究任务状态。普通用户只能访问自己的任务。"""
    try:
        if is_admin(user):
            return _manager().get_status(task_id, username=None)
        return _manager().get_status(task_id, username=user["username"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}") from exc


@router.get("/api/v1/research/{task_id}/result")
async def get_task_result(task_id: str, user: CurrentUser):
    """获取完整研究结果。普通用户只能访问自己的任务。"""
    try:
        if is_admin(user):
            return _manager().get_result(task_id, username=None)
        return _manager().get_result(task_id, username=user["username"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/v1/research/{task_id}")
async def cancel_task(task_id: str, user: CurrentUser):
    """取消进行中的研究任务。普通用户只能取消自己的任务。"""
    try:
        if is_admin(user):
            return _manager().cancel(task_id, username=None)
        return _manager().cancel(task_id, username=user["username"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
