"""报告下载 API 路由。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from apps.api.task_manager.manager import TaskManager
from apps.api.auth.dependencies import get_current_user

STORAGE_ROOT = Path("storage/reports").resolve()

router = APIRouter(tags=["reports"])


def _manager() -> TaskManager:
    return TaskManager()


def _validate_report_path(file_path: str) -> Path:
    """验证报告路径在 storage/reports 目录下，防止路径遍历攻击。"""
    resolved = Path(file_path).resolve()
    if not resolved.is_relative_to(STORAGE_ROOT):
        raise HTTPException(status_code=400, detail="非法的文件路径")
    return resolved


@router.get("/api/v1/reports/{task_id}/info")
async def get_report_info(task_id: str, user: dict = Depends(get_current_user)):
    """获取任务关联的报告文件信息。"""
    try:
        return _manager().get_report_info(task_id, username=user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}")


@router.get("/api/v1/reports/{task_id}/{fmt}")
async def download_report(task_id: str, fmt: str, user: dict = Depends(get_current_user)):
    """下载指定格式的报告文件。

    支持的格式：json / md / html / pdf
    """
    if fmt not in ("json", "md", "html", "pdf"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的格式：{fmt}。支持的格式：json, md, html, pdf",
        )

    try:
        info = _manager().get_report_info(task_id, username=user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在：{task_id}")

    path_key = {
        "json": "json_path",
        "md": "markdown_path",
        "html": "html_path",
        "pdf": "pdf_path",
    }[fmt]

    file_path = info.get(path_key)
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=f"任务 {task_id} 的 {fmt} 格式报告不存在（任务可能尚未完成）。",
        )

    resolved = _validate_report_path(file_path)
    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=f"任务 {task_id} 的 {fmt} 格式报告文件未找到。",
        )

    media_types = {
        "json": "application/json",
        "md": "text/markdown",
        "html": "text/html",
        "pdf": "application/pdf",
    }

    return FileResponse(
        path=str(resolved),
        media_type=media_types.get(fmt, "application/octet-stream"),
        filename=f"report_{task_id}.{fmt}",
    )
