"""全局异常处理中间件。"""

from fastapi import Request
from fastapi.responses import JSONResponse


async def global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一将未捕获异常转为 ErrorResponse 格式。"""
    detail = str(exc) if str(exc) else type(exc).__name__
    return JSONResponse(
        status_code=500,
        content={
            "detail": detail,
            "error_code": "internal_error",
        },
    )


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": f"路径不存在：{request.url.path}",
            "error_code": "not_found",
        },
    )


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": str(exc),
            "error_code": "bad_request",
        },
    )


async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc),
            "error_code": "not_found",
        },
    )
