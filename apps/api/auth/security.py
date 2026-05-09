"""JWT 签发/验证 + 密码哈希 + Token 撤销。

配置从环境变量读取。
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import redis
from dotenv import load_dotenv
from jose import jwt, JWTError, ExpiredSignatureError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

_raw_secret = os.getenv("JWT_SECRET")
if not _raw_secret:
    raise RuntimeError(
        "JWT_SECRET 环境变量未设置。请生成一个随机密钥："
        "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )
if len(_raw_secret) < 16:
    raise RuntimeError("JWT_SECRET 太短（最小 16 字符），请使用更强的密钥。")
JWT_SECRET = _raw_secret

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

REVOCATION_DB = 3
REVOCATION_PREFIX = "revoked:"


def _get_revocation_redis():
    return redis.from_url(
        os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
        db=REVOCATION_DB,
        decode_responses=True,
    )


def _is_token_revoked(jti: str) -> bool:
    """检查 token 是否已被撤销。"""
    try:
        r = _get_revocation_redis()
        result = r.exists(f"{REVOCATION_PREFIX}{jti}")
        r.close()
        return bool(result)
    except Exception:
        return False


def _revoke_token(jti: str, ttl_seconds: int) -> None:
    """将 token 加入撤销黑名单，TTL 过期后自动清理。"""
    try:
        r = _get_revocation_redis()
        r.setex(f"{REVOCATION_PREFIX}{jti}", ttl_seconds, "1")
        r.close()
    except Exception:
        pass


def create_access_token(username: str, role: str = "user") -> str:
    """签发 access token（短期，用于 API 请求认证）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(username: str) -> str:
    """签发 refresh token（长期，用于无感刷新 access token）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码并验证 token，失败时抛出 JWTError 或 ExpiredSignatureError。

    同时检查 token 是否已被撤销。
    """
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    jti = payload.get("jti")
    if jti and _is_token_revoked(jti):
        raise JWTError("token 已被撤销")
    return payload


def decode_token_without_revocation_check(token: str) -> dict:
    """解码 token（不检查撤销状态），用于首次验证后获取 jti 以执行撤销。"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def revoke_token_by_jti(jti: str, ttl_seconds: int = 7 * 86400) -> None:
    """撤销指定 jti 的 token（默认 TTL 与 refresh token 生命周期一致）。"""
    _revoke_token(jti, ttl_seconds)


def hash_password(password: str) -> str:
    """bcrypt 哈希密码。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
