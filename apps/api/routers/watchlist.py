"""观察池 API 路由 — 文件夹 / 观察项 / 标签 CRUD + 扫描操作。"""

from fastapi import APIRouter, Query, HTTPException, Depends

from apps.api.auth.dependencies import get_current_user

from apps.api.schemas.watchlist import (
    WatchlistFolderCreate,
    WatchlistFolderUpdate,
    WatchlistFolderResponse,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    WatchlistItemResponse,
    WatchlistItemListResponse,
    WatchlistTagCreate,
    WatchlistTagUpdate,
    WatchlistTagResponse,
    ScanRequest,
    ScanAcceptResponse,
    ScanProgressResponse,
    ScanHistoryResponse,
)
from apps.api.task_manager.manager import WatchlistManager

router = APIRouter(tags=["watchlist"])


def _manager() -> WatchlistManager:
    return WatchlistManager()


# ── 文件夹 ────────────────────────────────────────────────────

@router.get(
    "/api/v1/watchlist/folders",
    response_model=list[WatchlistFolderResponse],
)
async def list_folders(user: dict = Depends(get_current_user)):
    """列出所有文件夹，附带各文件夹下的标的数量。"""
    return _manager().list_folders()


@router.post(
    "/api/v1/watchlist/folders",
    response_model=WatchlistFolderResponse,
    status_code=201,
)
async def create_folder(req: WatchlistFolderCreate, user: dict = Depends(get_current_user)):
    """创建文件夹。"""
    return _manager().create_folder(
        name=req.name,
        description=req.description,
        icon=req.icon,
        sort_order=req.sort_order,
    )


@router.put(
    "/api/v1/watchlist/folders/{folder_id}",
    response_model=WatchlistFolderResponse,
)
async def update_folder(folder_id: str, req: WatchlistFolderUpdate, user: dict = Depends(get_current_user)):
    """更新文件夹。"""
    try:
        kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
        return _manager().update_folder(folder_id, **kwargs)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"文件夹不存在：{folder_id}")


@router.delete("/api/v1/watchlist/folders/{folder_id}")
async def delete_folder(folder_id: str, user: dict = Depends(get_current_user)):
    """删除文件夹（仅当为空时可删除）。"""
    try:
        _manager().delete_folder(folder_id)
        return {"detail": "已删除"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"文件夹不存在：{folder_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── 观察项 ────────────────────────────────────────────────────

@router.get(
    "/api/v1/watchlist/items",
    response_model=WatchlistItemListResponse,
)
async def list_items(
    folder_id: str | None = Query(None, description="按文件夹筛选"),
    tag_id: str | None = Query(None, description="按标签筛选"),
    enabled: bool | None = Query(None, description="按启用状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=100, description="每页数量"),
    user: dict = Depends(get_current_user),
):
    """列出观察项（分页 + 筛选）。"""
    items, total = _manager().list_items(
        folder_id=folder_id,
        tag_id=tag_id,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post(
    "/api/v1/watchlist/items",
    response_model=WatchlistItemResponse,
    status_code=201,
)
async def add_item(req: WatchlistItemCreate, user: dict = Depends(get_current_user)):
    """添加标的到观察池。"""
    try:
        sc = req.schedule_config.model_dump() if req.schedule_config else None
        return _manager().add_item(
            symbol=req.symbol,
            asset_type=req.asset_type,
            folder_id=req.folder_id,
            schedule_config=sc,
            notes=req.notes,
            target_action=req.target_action,
            asset_name=req.asset_name,
            tag_ids=req.tag_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/api/v1/watchlist/items/{item_id}",
    response_model=WatchlistItemResponse,
)
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    """获取观察项详情（含标签和历史扫描记录）。"""
    try:
        return _manager().get_item(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"观察项不存在：{item_id}")


@router.put(
    "/api/v1/watchlist/items/{item_id}",
    response_model=WatchlistItemResponse,
)
async def update_item(item_id: str, req: WatchlistItemUpdate, user: dict = Depends(get_current_user)):
    """更新观察项。"""
    try:
        kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
        # 将 ScheduleConfig 转为 dict
        if "schedule_config" in kwargs and hasattr(kwargs["schedule_config"], "model_dump"):
            kwargs["schedule_config"] = kwargs["schedule_config"].model_dump()
        return _manager().update_item(item_id, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/api/v1/watchlist/items/{item_id}")
async def remove_item(item_id: str, user: dict = Depends(get_current_user)):
    """从观察池移除标的。"""
    try:
        _manager().remove_item(item_id)
        return {"detail": "已移除"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"观察项不存在：{item_id}")


# ── 标签 ──────────────────────────────────────────────────────

@router.get(
    "/api/v1/watchlist/tags",
    response_model=list[WatchlistTagResponse],
)
async def list_tags(user: dict = Depends(get_current_user)):
    """列出所有标签，附带各标签下的标的数量。"""
    return _manager().list_tags()


@router.post(
    "/api/v1/watchlist/tags",
    response_model=WatchlistTagResponse,
    status_code=201,
)
async def create_tag(req: WatchlistTagCreate, user: dict = Depends(get_current_user)):
    """创建标签。"""
    try:
        return _manager().create_tag(name=req.name, color=req.color)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put(
    "/api/v1/watchlist/tags/{tag_id}",
    response_model=WatchlistTagResponse,
)
async def update_tag(tag_id: str, req: WatchlistTagUpdate, user: dict = Depends(get_current_user)):
    """更新标签。"""
    try:
        kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
        return _manager().update_tag(tag_id, **kwargs)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"标签不存在：{tag_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/api/v1/watchlist/tags/{tag_id}")
async def delete_tag(tag_id: str, user: dict = Depends(get_current_user)):
    """删除标签。"""
    try:
        _manager().delete_tag(tag_id)
        return {"detail": "已删除"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"标签不存在：{tag_id}")


# ── 扫描操作 ──────────────────────────────────────────────────

@router.post(
    "/api/v1/watchlist/scan",
    response_model=ScanAcceptResponse,
    status_code=202,
)
async def trigger_scan(req: ScanRequest, user: dict = Depends(get_current_user)):
    """触发批量扫描。

    可指定 item_ids 或 folder_id，不指定则扫描所有启用的标的。
    """
    try:
        return _manager().trigger_scan(
            item_ids=req.item_ids,
            folder_id=req.folder_id,
            trigger_type=req.trigger_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/api/v1/watchlist/scan/{batch_id}",
    response_model=ScanProgressResponse,
)
async def get_scan_progress(batch_id: str, user: dict = Depends(get_current_user)):
    """查询批量扫描进度。"""
    try:
        return _manager().get_scan_progress(batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"扫描批次不存在：{batch_id}")


@router.get(
    "/api/v1/watchlist/results",
    response_model=ScanHistoryResponse,
)
async def list_scan_results(
    symbol: str | None = Query(None, description="按标的代码筛选"),
    min_score: float | None = Query(None, description="最低评分"),
    max_score: float | None = Query(None, description="最高评分"),
    rating: str | None = Query(None, description="按评级筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    user: dict = Depends(get_current_user),
):
    """查询扫描历史结果。"""
    return _manager().get_scan_history(
        symbol=symbol,
        min_score=min_score,
        max_score=max_score,
        rating=rating,
        page=page,
        page_size=page_size,
    )
