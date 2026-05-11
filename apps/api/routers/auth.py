"""认证路由 — 登录 / 刷新 / 用户信息 / 注册。"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from apps.api.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    UserResponse,
    RegisterRequest,
)
from apps.api.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    revoke_token_by_jti,
    hash_password,
    verify_password,
    JWT_SECRET,
    JWT_ALGORITHM,
    TokenRevocationUnavailableError,
)
from fastapi import Request

from apps.api.auth.dependencies import get_current_user, require_admin
from apps.api.task_manager.store import get_user_store
from apps.api.limiter import limiter
from jose import jwt as jose_jwt

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest):
    """用户登录，返回 access_token + refresh_token。"""
    user = get_user_store().get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.get("enabled"):
        raise HTTPException(status_code=403, detail="用户已被禁用")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    access_token = create_access_token(user["username"], user.get("role", "user"))
    refresh_token = create_refresh_token(user["username"])
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/token", response_model=TokenResponse)
@limiter.limit("5/minute")
async def token_login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 密码流登录（供 Swagger UI Authorize 按钮使用，接受表单格式）。"""
    user = get_user_store().get_user_by_username(form.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.get("enabled"):
        raise HTTPException(status_code=403, detail="用户已被禁用")
    if not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    access_token = create_access_token(user["username"], user.get("role", "user"))
    refresh_token = create_refresh_token(user["username"])
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(request: Request, req: RefreshRequest):
    """使用 refresh_token 换取新的 access_token + refresh_token。

    旧 refresh token 在使用后立即撤销，防止重放攻击。
    """
    # 先解码以获取 payload（不通过 decode_token 避免被撤销检查拦截）
    try:
        payload = jose_jwt.decode(req.refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的 token 类型")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="token 无效")

    user = get_user_store().get_user_by_username(username)
    if not user or not user.get("enabled"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    # 尝试通过 decode_token 检查是否已被撤销
    try:
        decode_token(req.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="refresh_token 已被撤销")

    # 撤销旧 refresh token（防止重放）
    jti = payload.get("jti")
    if jti:
        ttl = int((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            try:
                revoke_token_by_jti(jti, ttl)
            except TokenRevocationUnavailableError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="token 撤销存储不可用，请稍后重试",
                ) from exc

    access_token = create_access_token(user["username"], user.get("role", "user"))
    new_refresh_token = create_refresh_token(user["username"])
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """返回当前登录用户的信息。"""
    return UserResponse(
        id=user["id"],
        username=user["username"],
        role=user.get("role", "user"),
        enabled=user["enabled"],
        created_at=user["created_at"],
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest, user: dict = Depends(require_admin)):
    """注册新用户（仅管理员可操作）。"""
    try:
        password_hash = hash_password(req.password)
        new_user = get_user_store().create_user(
            username=req.username,
            password_hash=password_hash,
            role=req.role,
        )
        return UserResponse(
            id=new_user["id"],
            username=new_user["username"],
            role=new_user.get("role", "user"),
            enabled=new_user["enabled"],
            created_at=new_user["created_at"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
