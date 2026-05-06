"""认证路由 — 登录 / 刷新 / 用户信息 / 注册。"""

import os

from fastapi import APIRouter, Depends, HTTPException

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
    hash_password,
    verify_password,
)
from apps.api.auth.dependencies import get_current_user
from apps.api.task_manager.store import get_user_store

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 公开端点
router_no_prefix = APIRouter(tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
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


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest):
    """使用 refresh_token 换取新的 access_token + refresh_token。"""
    try:
        payload = decode_token(req.refresh_token)
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

    access_token = create_access_token(user["username"], user.get("role", "user"))
    refresh_token = create_refresh_token(user["username"])
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


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
async def register(req: RegisterRequest, user: dict = Depends(get_current_user)):
    """注册新用户（需已登录，后续可限定 admin 角色）。"""
    # 目前允许任意已登录用户注册，后续可按需限制为 admin
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
