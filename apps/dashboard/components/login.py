"""Streamlit 登录组件。

在侧边栏渲染登录表单。登录后 token 存储在 st.session_state 中，
同时持久化到 URL query params，刷新页面后自动恢复登录状态。
每个浏览器的 URL 是独立的，不会跨用户共享。

RBAC 支持：
- 登录后调用 /api/v1/auth/me 获取并保存 auth_role。
- 提供 current_user()、current_role()、is_admin() helper。
"""

import base64
import json
import logging

import requests
import streamlit as st
from requests import Response

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"

_AUTH_PARAM = "auth"


def _restore_from_query_params() -> bool:
    """尝试从 URL query params 恢复登录状态（每个浏览器独立）。"""
    auth_param = st.query_params.get(_AUTH_PARAM)
    if not auth_param:
        return False
    try:
        data = json.loads(base64.b64decode(auth_param))
        if data.get("access_token"):
            st.session_state["auth_token"] = data["access_token"]
            st.session_state["refresh_token"] = data.get("refresh_token", "")
            st.session_state["auth_user"] = data.get("username", "")
            _fetch_user_info(data["access_token"])
            return True
    except Exception:
        pass
    return False


def _save_to_query_params(access_token: str, refresh_token: str, username: str) -> None:
    """将登录信息持久化到 URL query params（每个浏览器独立）。"""
    auth_data = base64.b64encode(json.dumps({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "username": username,
    }).encode()).decode()
    st.query_params[_AUTH_PARAM] = auth_data


def _clear_query_params() -> None:
    """清除 URL query params 中的登录信息。"""
    st.query_params.clear()


def _clear_session_only() -> None:
    """清除 session_state 中的登录信息，但保留 URL query params。

    用于 token 刷新失败时——URL 中的旧 token 仍可尝试恢复，
    避免刷新浏览器后因 URL 被清掉而必须重新登录。
    只有用户主动退出时才同时清 URL。
    """
    st.session_state.pop("auth_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state.pop("auth_user", None)
    st.session_state.pop("auth_role", None)


def require_login() -> str | None:
    """在侧边栏渲染登录表单，阻止未登录用户访问。

    Returns:
        如果已登录（或登录成功），返回 access_token。
        如果未登录，调用 st.stop() 阻止页面渲染，返回 None。
    """
    # 已登录
    if "auth_token" in st.session_state:
        return st.session_state["auth_token"]

    # 尝试从 URL 恢复（每个浏览器独立，不会跨用户共享）
    if _restore_from_query_params():
        return st.session_state["auth_token"]

    # 未登录：渲染登录表单
    with st.sidebar:
        st.subheader("🔐 登录")
        st.caption("请使用 API 凭据登录")

        username = st.text_input("用户名", key="login_user")
        password = st.text_input("密码", type="password", key="login_pass")

        if st.button("登录", use_container_width=True, type="primary"):
            try:
                resp = requests.post(
                    f"{API_BASE}/api/v1/auth/login",
                    json={"username": username, "password": password},
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state["auth_token"] = data["access_token"]
                    st.session_state["refresh_token"] = data["refresh_token"]
                    st.session_state["auth_user"] = username
                    # 持久化到 URL（每个浏览器独立）
                    _save_to_query_params(data["access_token"], data["refresh_token"], username)
                    # 获取用户角色
                    _fetch_user_info(data["access_token"])
                    st.success(f"欢迎，{username}！")
                    st.rerun()
                elif resp.status_code == 401:
                    st.error("用户名或密码错误")
                elif resp.status_code == 403:
                    st.error("用户已被禁用")
                else:
                    st.error(f"登录失败 [{resp.status_code}]")
            except requests.ConnectionError:
                st.error("无法连接 API 服务，请确认 FastAPI 已启动。")
            except Exception as exc:
                st.error(f"登录异常：{exc}")

        st.divider()
        st.stop()
    return None


def _fetch_user_info(token: str) -> None:
    """登录后调用 /me 获取用户角色信息。"""
    try:
        resp = requests.get(
            f"{API_BASE}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["auth_role"] = data.get("role", "user")
    except Exception as exc:
        logger.warning("获取用户信息失败，默认角色为 user: %s", exc)
        st.session_state["auth_role"] = "user"


def current_user() -> str | None:
    """返回当前登录用户名。"""
    return st.session_state.get("auth_user")


def current_role() -> str:
    """返回当前用户角色（'admin' 或 'user'）。"""
    return st.session_state.get("auth_role", "user")


def is_admin() -> bool:
    """判断当前用户是否为管理员。"""
    return current_role() == "admin"


def auth_headers() -> dict:
    """返回包含 Bearer token 的 HTTP headers。"""
    token = st.session_state.get("auth_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def authenticated_request(
    method: str,
    path: str,
    *,
    timeout: float = 10,
    **kwargs,
) -> Response:
    """发送带认证的 API 请求，401 时尝试刷新 token 后重试一次。"""
    headers = dict(auth_headers())
    extra_headers = kwargs.pop("headers", None)
    if extra_headers:
        headers.update(extra_headers)

    resp = requests.request(
        method,
        f"{API_BASE}{path}",
        headers=headers,
        timeout=timeout,
        **kwargs,
    )
    if resp.status_code != 401:
        return resp

    if not _refresh_auth_token():
        return resp

    retry_headers = dict(auth_headers())
    if extra_headers:
        retry_headers.update(extra_headers)
    return requests.request(
        method,
        f"{API_BASE}{path}",
        headers=retry_headers,
        timeout=timeout,
        **kwargs,
    )


def api_get(path: str, **kwargs) -> dict | list | None:
    """带认证的 GET 请求。token 过期时自动刷新。"""
    try:
        resp = authenticated_request("GET", path, **kwargs)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("api_get(%s) 失败: %s", path, exc)
        return None


def api_post(path: str, json_data: dict | None = None) -> dict | None:
    """带认证的 POST 请求。"""
    try:
        resp = authenticated_request("POST", path, json=json_data)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("api_post(%s) 失败: %s", path, exc)
        return None


def _refresh_auth_token() -> bool:
    """刷新 access token，成功时更新 session_state 并同步 URL。"""
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        _clear_session_only()
        return False
    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["auth_token"] = data["access_token"]
            st.session_state["refresh_token"] = data["refresh_token"]
            _fetch_user_info(data["access_token"])
            # 同步更新 URL，确保刷新浏览器后能用最新 token 恢复
            username = st.session_state.get("auth_user", "")
            _save_to_query_params(data["access_token"], data["refresh_token"], username)
            return True
        else:
            # 401/403：服务端明确拒绝 token，清除 URL 防止僵尸循环
            _logout()
    except Exception as exc:
        # 网络异常：保留 URL，下次刷新可重试恢复
        logger.warning("token 刷新失败: %s", exc)
        _clear_session_only()
    return False


def _logout() -> None:
    """主动退出登录：清除 session 和 URL，跳转到登录页。"""
    _clear_query_params()
    _clear_session_only()
    st.rerun()
