"""JWT signing/verification, password hashing, and token revocation."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import redis
from dotenv import load_dotenv
from jose import ExpiredSignatureError, JWTError, jwt

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

_raw_secret = os.getenv("JWT_SECRET")
if not _raw_secret:
    raise RuntimeError(
        "JWT_SECRET is not set. Generate one with: "
        "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
if len(_raw_secret) < 32:
    raise RuntimeError(
        "JWT_SECRET is too short. Use at least 32 random characters; "
        "recommended: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
JWT_SECRET = _raw_secret

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
AUTH_REVOCATION_FAIL_MODE = os.getenv("AUTH_REVOCATION_FAIL_MODE", "open").strip().lower()

REVOCATION_DB = 3
REVOCATION_PREFIX = "revoked:"


class TokenRevocationUnavailableError(JWTError):
    """Raised when revocation storage is required but unavailable."""


def revocation_fail_closed() -> bool:
    return AUTH_REVOCATION_FAIL_MODE in {"closed", "fail_closed", "fail-closed"}


def _get_revocation_redis():
    return redis.from_url(
        os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
        db=REVOCATION_DB,
        decode_responses=True,
    )


def _is_token_revoked(jti: str) -> bool:
    """Check token revocation status."""
    try:
        r = _get_revocation_redis()
        try:
            return bool(r.exists(f"{REVOCATION_PREFIX}{jti}"))
        finally:
            r.close()
    except Exception as exc:
        if revocation_fail_closed():
            raise TokenRevocationUnavailableError(
                "token revocation store is unavailable"
            ) from exc
        return False


def _revoke_token(jti: str, ttl_seconds: int) -> None:
    """Add a token jti to the revocation blacklist."""
    try:
        r = _get_revocation_redis()
        try:
            r.setex(f"{REVOCATION_PREFIX}{jti}", ttl_seconds, "1")
        finally:
            r.close()
    except Exception as exc:
        if revocation_fail_closed():
            raise TokenRevocationUnavailableError(
                "token revocation store is unavailable"
            ) from exc


def create_access_token(username: str, role: str = "user") -> str:
    """Create a short-lived API access token."""
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
    """Create a long-lived refresh token."""
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
    """Decode a JWT and check revocation status."""
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    jti = payload.get("jti")
    if jti and _is_token_revoked(jti):
        raise JWTError("token has been revoked")
    return payload


def decode_token_without_revocation_check(token: str) -> dict:
    """Decode a JWT without checking token revocation status."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def revoke_token_by_jti(jti: str, ttl_seconds: int = 7 * 86400) -> None:
    """Revoke a token by jti."""
    _revoke_token(jti, ttl_seconds)


def hash_password(password: str) -> str:
    """Hash a plain text password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
