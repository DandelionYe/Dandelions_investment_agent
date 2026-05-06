"""FastAPI 认证依赖 — get_current_user。

用法：
    @router.get("/protected")
    async def endpoint(user: dict = Depends(get_current_user)):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, ExpiredSignatureError

from apps.api.auth.security import decode_token
from apps.api.task_manager.store import get_user_store

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> dict:
    """解码 JWT Bearer token，返回当前用户信息。

    Raises:
        HTTPException(401): token 无效、过期、或用户已被禁用。
    """
    try:
        payload = decode_token(token)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token 已过期", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=401, detail="token 无效", headers={"WWW-Authenticate": "Bearer"})

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="无效的 token 类型", headers={"WWW-Authenticate": "Bearer"})

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="token 缺少用户标识", headers={"WWW-Authenticate": "Bearer"})

    user = get_user_store().get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在", headers={"WWW-Authenticate": "Bearer"})
    if not user.get("enabled"):
        raise HTTPException(status_code=403, detail="用户已被禁用")

    return user


async def get_current_active_user(
    user: dict = Depends(get_current_user),
) -> dict:
    """等同于 get_current_user（已隐式检查 enabled 状态）。"""
    return user
