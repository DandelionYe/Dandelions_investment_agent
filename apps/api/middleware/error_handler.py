"""全局异常处理中间件。"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("error_handler")


async def global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一将未捕获异常转为通用错误响应，防止内部细节泄露。

    完整异常信息仅记录在服务端日志中，客户端收到通用错误消息。
    """
    logger.error("未处理异常 [%s %s]: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误",
            "error_code": "internal_error",
        },
    )


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": f"Not Found: {request.url.path}",
            "error_code": "not_found",
        },
        media_type="application/json; charset=utf-8",
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
