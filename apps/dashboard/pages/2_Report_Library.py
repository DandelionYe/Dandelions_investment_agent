"""研究报告库 — 通过 API 获取当前用户可见的报告列表。

RBAC：不再直接扫描 storage/reports 目录，改用 API 获取任务列表和报告信息。
下载按钮走 /api/v1/reports/{task_id}/{fmt}，受 task owner 权限控制。
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

from apps.dashboard.components.login import (
    require_login,
    authenticated_request,
    is_admin,
    current_user,
)

st.set_page_config(
    page_title="Report Library - Dandelions",
    page_icon="📚",
    layout="wide",
)

require_login()

API_BASE = "http://localhost:8000"


def _api_get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = authenticated_request("GET", path, params=params, timeout=10)
        if resp.status_code >= 400:
            st.warning(f"API 请求失败 [{resp.status_code}]: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as exc:
        st.warning(f"API 请求异常: {exc}")
        return None


def fetch_task_history(page: int = 1, page_size: int = 50) -> list[dict]:
    """通过 API 获取当前用户可见的任务历史。"""
    result = _api_get("/api/v1/research/history", {"page": page, "page_size": page_size})
    if not result or not isinstance(result, dict):
        return []
    return result.get("tasks", [])


def fetch_report_info(task_id: str) -> dict | None:
    """通过 API 获取报告信息。"""
    return _api_get(f"/api/v1/reports/{task_id}/info")


def download_report_via_api(task_id: str, fmt: str) -> bytes | None:
    """通过 API 下载报告文件。"""
    try:
        resp = authenticated_request("GET", f"/api/v1/reports/{task_id}/{fmt}", timeout=30)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception:
        return None


def render_download_buttons(task_id: str, available_formats: list[str], key_prefix: str):
    col1, col2, col3, col4 = st.columns(4)

    fmt_map = {
        "pdf": ("PDF", "pdf"),
        "markdown": ("Markdown", "md"),
        "json": ("JSON", "json"),
        "html": ("HTML", "html"),
    }

    for col, (fmt_key, (label, api_fmt)) in zip(
        [col1, col2, col3, col4], fmt_map.items()
    ):
        with col:
            if fmt_key in available_formats:
                data = download_report_via_api(task_id, api_fmt)
                if data:
                    ext = api_fmt if api_fmt != "md" else "md"
                    st.download_button(
                        f"下载 {label}",
                        data=data,
                        file_name=f"report_{task_id}.{ext}",
                        mime={
                            "pdf": "application/pdf",
                            "md": "text/markdown",
                            "json": "application/json",
                            "html": "text/html",
                        }.get(fmt_key, "application/octet-stream"),
                        key=f"{key_prefix}_{fmt_key}",
                    )
                else:
                    st.button(f"{label} 下载失败", disabled=True, key=f"{key_prefix}_{fmt_key}_fail")
            else:
                st.button(f"{label} 不存在", disabled=True, key=f"{key_prefix}_{fmt_key}_missing")


st.title("📚 研究报告库")
st.caption("查看、筛选和下载已经生成的投研报告。")

# 通过 API 获取任务列表
tasks = fetch_task_history(page=1, page_size=100)

if not tasks:
    st.info("当前还没有生成过报告。请先到 Home 页面生成一份单票研究报告。")
    st.stop()

# 构建报告列表
rows = []
for t in tasks:
    if t.get("status") != "completed":
        continue
    task_id = t["task_id"]
    report_info = fetch_report_info(task_id)
    available_formats = report_info.get("formats", []) if report_info else []

    rows.append({
        "task_id": task_id,
        "symbol": t.get("symbol", ""),
        "score": t.get("score"),
        "rating": t.get("rating"),
        "action": t.get("action"),
        "status": t.get("status"),
        "created_at": t.get("created_at"),
        "completed_at": t.get("completed_at"),
        "available_formats": available_formats,
    })

if not rows:
    st.info("当前还没有已完成的报告。请先到 Home 页面生成一份单票研究报告。")
    st.stop()

df = pd.DataFrame(rows)

with st.sidebar:
    st.header("筛选条件")

    keyword = st.text_input(
        "搜索代码",
        value="",
        placeholder="例如：600519",
    )

    rating_options = ["全部"] + sorted(df["rating"].dropna().astype(str).unique().tolist())
    selected_rating = st.selectbox("评级", rating_options)

    action_options = ["全部"] + sorted(df["action"].dropna().astype(str).unique().tolist())
    selected_action = st.selectbox("操作建议", action_options)

filtered_df = df.copy()

if keyword.strip():
    kw = keyword.strip().lower()
    filtered_df = filtered_df[
        filtered_df["symbol"].astype(str).str.lower().str.contains(kw)
    ]

if selected_rating != "全部":
    filtered_df = filtered_df[filtered_df["rating"].astype(str) == selected_rating]

if selected_action != "全部":
    filtered_df = filtered_df[filtered_df["action"].astype(str) == selected_action]

st.subheader("报告列表")

display_columns = [
    "symbol",
    "score",
    "rating",
    "action",
    "completed_at",
]

st.dataframe(
    filtered_df[display_columns],
    use_container_width=True,
    hide_index=True,
)

if filtered_df.empty:
    st.warning("没有符合筛选条件的报告。")
    st.stop()

symbol_options = [
    f'{row["symbol"]} - {row.get("rating", "-")} - {row.get("completed_at", "-")}'
    for _, row in filtered_df.iterrows()
]

selected_label = st.selectbox("选择一份报告查看详情", symbol_options)

selected_index = symbol_options.index(selected_label)
selected_row = filtered_df.iloc[selected_index]

task_id = selected_row["task_id"]
available_formats = selected_row["available_formats"]

st.subheader(f"报告详情 — {selected_row['symbol']}")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("综合评分", f"{selected_row.get('score', '-')} / 100")
with col2:
    st.metric("评级", selected_row.get("rating", "-"))
with col3:
    st.metric("操作建议", selected_row.get("action", "-"))

st.markdown("### 报告文件")
render_download_buttons(task_id, available_formats, key_prefix=f"detail_{task_id}")

# JSON 预览
if "json" in available_formats:
    json_data = download_report_via_api(task_id, "json")
    if json_data:
        import json
        try:
            data = json.loads(json_data)
            if data.get("final_opinion"):
                st.markdown("### 投委会最终观点")
                st.info(data["final_opinion"])
            with st.expander("查看完整 JSON"):
                st.json(data)
        except Exception:
            pass

# Markdown 预览
if "markdown" in available_formats:
    md_data = download_report_via_api(task_id, "md")
    if md_data:
        with st.expander("预览 Markdown 报告"):
            st.markdown(md_data.decode("utf-8", errors="replace"))
