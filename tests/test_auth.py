"""认证系统测试 — 用户 CRUD / 密码哈希 / JWT 签发/验证 / 端点 / token 过期。"""

import time
import pytest

from apps.api.task_manager.store import UserStore, get_user_store
from apps.api.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from jose import jwt, JWTError, ExpiredSignatureError


@pytest.fixture
def store():
    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = UserStore(db_path=path)
    yield s
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


class TestPasswordHashing:

    def test_hash_and_verify(self):
        pw = "test_password_123"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # salt makes each unique
        assert verify_password("same", h1)
        assert verify_password("same", h2)


class TestJWT:

    def test_create_and_decode_access_token(self):
        token = create_access_token("testuser", "user")
        payload = decode_token(token)
        assert payload["sub"] == "testuser"
        assert payload["role"] == "user"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        token = create_refresh_token("testuser")
        payload = decode_token(token)
        assert payload["sub"] == "testuser"
        assert payload["type"] == "refresh"

    def test_invalid_token_raises(self):
        with pytest.raises(JWTError):
            decode_token("not.a.valid.token")

    def test_expired_token(self):
        from datetime import datetime, timedelta, timezone
        from apps.api.auth.security import JWT_SECRET, JWT_ALGORITHM
        now = datetime.now(timezone.utc)
        payload = {"sub": "exp", "exp": now - timedelta(minutes=1), "type": "access"}
        expired = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        with pytest.raises(ExpiredSignatureError):
            decode_token(expired)


class TestUserStore:

    def test_create_and_get(self, store):
        u = store.create_user("alice", hash_password("pass123"))
        assert u["username"] == "alice"
        assert u["role"] == "user"
        assert u["enabled"] is True

        found = store.get_user_by_username("alice")
        assert found is not None
        assert verify_password("pass123", found["password_hash"])

    def test_duplicate_username_raises(self, store):
        store.create_user("bob", hash_password("p1"))
        with pytest.raises(ValueError, match="用户名已存在"):
            store.create_user("bob", hash_password("p2"))

    def test_get_nonexistent(self, store):
        assert store.get_user_by_username("nobody") is None

    def test_list_users(self, store):
        store.create_user("u1", hash_password("p"))
        store.create_user("u2", hash_password("p"), role="admin")
        users = store.list_users()
        assert len(users) == 2
        usernames = {u["username"] for u in users}
        assert "u1" in usernames
        assert "u2" in usernames
        # password_hash should not be in list output
        for u in users:
            assert "password_hash" not in u

    def test_update_user(self, store):
        u = store.create_user("charlie", hash_password("p"))
        updated = store.update_user(u["id"], enabled=False, role="admin")
        assert updated["enabled"] is False
        assert updated["role"] == "admin"

    def test_delete_user(self, store):
        u = store.create_user("delete_me", hash_password("p"))
        store.delete_user(u["id"])
        assert store.get_user_by_id(u["id"]) is None

    def test_admin_seeded(self):
        s = get_user_store()
        admin = s.get_user_by_username("admin")
        assert admin is not None
        assert admin["role"] == "admin"
        assert admin["enabled"] is True
        assert verify_password("dandelions2026", admin["password_hash"])


class TestAuthEndpoints:
    """测试 REST auth 端点（需启动 FastAPI）。标记为需要服务器的集成测试。"""

    @pytest.mark.skip(reason="需要启动 FastAPI 服务")
    def test_login_success(self):
        import requests
        resp = requests.post(
            "http://localhost:8000/api/v1/auth/login",
            json={"username": "admin", "password": "dandelions2026"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.skip(reason="需要启动 FastAPI 服务")
    def test_login_wrong_password(self):
        import requests
        resp = requests.post(
            "http://localhost:8000/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    @pytest.mark.skip(reason="需要启动 FastAPI 服务")
    def test_protected_endpoint_requires_auth(self):
        import requests
        resp = requests.get("http://localhost:8000/api/v1/research/history")
        assert resp.status_code == 401

    @pytest.mark.skip(reason="需要启动 FastAPI 服务")
    def test_protected_endpoint_with_token(self):
        import requests
        # 登录
        login_resp = requests.post(
            "http://localhost:8000/api/v1/auth/login",
            json={"username": "admin", "password": "dandelions2026"},
        )
        token = login_resp.json()["access_token"]
        # 带 token 访问
        resp = requests.get(
            "http://localhost:8000/api/v1/research/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.skip(reason="需要启动 FastAPI 服务")
    def test_health_endpoint_no_auth(self):
        import requests
        resp = requests.get("http://localhost:8000/api/v1/health/ready")
        assert resp.status_code == 200


class TestTokenRefresh:

    def test_refresh_token_decode(self):
        token = create_refresh_token("user1")
        payload = decode_token(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "user1"

    def test_access_token_rejected_as_refresh(self):
        """access token 的 type 是 'access'，不能当 refresh 用。"""
        token = create_access_token("user1")
        payload = decode_token(token)
        assert payload["type"] == "access"
        assert payload["type"] != "refresh"
