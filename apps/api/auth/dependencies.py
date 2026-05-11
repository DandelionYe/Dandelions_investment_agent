"""FastAPI authentication dependencies."""

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError

from apps.api.auth.security import TokenRevocationUnavailableError, decode_token
from apps.api.task_manager.store import get_user_store

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=True,
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> dict:
    """Decode JWT bearer token and return the current enabled user."""
    try:
        payload = decode_token(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenRevocationUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="token 撤销存储不可用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="token 无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail="无效的 token 类型",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=401,
            detail="token 缺少用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_store().get_user_by_username(username)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("enabled"):
        raise HTTPException(status_code=403, detail="用户已被禁用")

    return user


async def require_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require the current user to be an admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
