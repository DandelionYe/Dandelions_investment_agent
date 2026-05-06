"""Streamlit 登录组件。

在侧边栏渲染登录表单。登录后 token 存储在 st.session_state 中。
所有后续 API 调用自动携带 token，过期时自动刷新。
"""

import streamlit as st
import requests

API_BASE = "http://localhost:8000"


def require_login() -> str | None:
    """在侧边栏渲染登录表单，阻止未登录用户访问。

    Returns:
        如果已登录（或登录成功），返回 access_token。
        如果未登录，调用 st.stop() 阻止页面渲染，返回 None。
    """
    # 已登录
    if "auth_token" in st.session_state:
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


def auth_headers() -> dict:
    """返回包含 Bearer token 的 HTTP headers。"""
    token = st.session_state.get("auth_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def api_get(path: str, **kwargs) -> dict | list | None:
    """带认证的 GET 请求。token 过期时自动刷新。"""
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers=auth_headers(),
            timeout=10,
            **kwargs,
        )
        if resp.status_code == 401:
            return _try_refresh_and_retry("GET", path, **kwargs)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def api_post(path: str, json_data: dict | None = None) -> dict | None:
    """带认证的 POST 请求。"""
    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            json=json_data,
            headers=auth_headers(),
            timeout=10,
        )
        if resp.status_code == 401:
            return _try_refresh_and_retry("POST", path, json_data=json_data)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def _try_refresh_and_retry(method: str, path: str, **kwargs) -> dict | None:
    """尝试刷新 token 并重试请求。"""
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        _logout()
        return None
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
            # 重试原请求
            if method == "GET":
                r = requests.get(
                    f"{API_BASE}{path}",
                    headers=auth_headers(),
                    timeout=10,
                )
            else:
                r = requests.post(
                    f"{API_BASE}{path}",
                    json=kwargs.get("json_data"),
                    headers=auth_headers(),
                    timeout=10,
                )
            if r.status_code < 400:
                return r.json()
        else:
            _logout()
    except Exception:
        _logout()
    return None


def _logout() -> None:
    """清除登录状态。"""
    st.session_state.pop("auth_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state.pop("auth_user", None)
    st.rerun()
