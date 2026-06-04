"""研究报告库 — 通过 API 获取当前用户可见的报告列表。

RBAC：不再直接扫描 storage/reports 目录，改用 API 获取任务列表和报告信息。
下载按钮走 /api/v1/reports/{task_id}/{fmt}，受 task owner 权限控制。
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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

# 每 120 秒自动刷新，确保新完成的报告及时显示
st_autorefresh(interval=120_000, key="report_library_refresh")

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


def download_report_via_api(task_id: str, fmt: str) -> bytes | None:
    """通过 API 下载报告文件。"""
    try:
        resp = authenticated_request("GET", f"/api/v1/reports/{task_id}/{fmt}", timeout=30)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception:
        return None


_CACHE_MAX_ENTRIES = 20  # LRU 驱逐阈值
_CACHE_MISS_TTL = 300    # 负结果缓存 TTL（秒）


def _get_cached_report(task_id: str, fmt: str) -> bytes | None:
    """从 session_state 缓存获取报告，未命中则从 API 下载并缓存。

    缓存策略：
    - LRU 驱逐：缓存超过 _CACHE_MAX_ENTRIES 条目时删除最早访问的条目
    - 负结果缓存：下载失败缓存 _CACHE_MISS_TTL 秒，避免 autorefresh 重复请求
    """
    import time

    cache_key = f"_dl_{task_id}_{fmt}"
    order_key = "_dl_cache_order"
    miss_key = "_dl_cache_misses"

    # 检查正缓存
    data = st.session_state.get(cache_key)
    if data is not None:
        # LRU：移到末尾
        order = [k for k in st.session_state.get(order_key, []) if k != cache_key]
        order.append(cache_key)
        st.session_state[order_key] = order
        return data

    # 检查负缓存（未过期则跳过请求）
    misses = dict(st.session_state.get(miss_key, {}))
    if cache_key in misses:
        if time.time() < misses[cache_key]:
            return None
        misses.pop(cache_key, None)
        st.session_state[miss_key] = misses

    # 下载
    data = download_report_via_api(task_id, fmt)
    if data:  # 非空字节才缓存为正结果；b'' 视为失败
        # 正缓存 + LRU 驱逐
        st.session_state[cache_key] = data
        order = list(st.session_state.get(order_key, []))
        order.append(cache_key)
        # 驱逐最旧条目
        while len(order) > _CACHE_MAX_ENTRIES:
            evict_key = order.pop(0)
            st.session_state.pop(evict_key, None)
        st.session_state[order_key] = order
    else:
        # 负缓存（None 或 b'' 都视为失败）
        misses = dict(st.session_state.get(miss_key, {}))
        misses[cache_key] = time.time() + _CACHE_MISS_TTL
        st.session_state[miss_key] = misses

    return data


_MIME_TYPES = {
    "pdf": "application/pdf",
    "markdown": "text/markdown",
    "json": "application/json",
    "html": "text/html",
}

_FMT_MAP = {
    "pdf": ("PDF", "pdf"),
    "markdown": ("Markdown", "md"),
    "json": ("JSON", "json"),
    "html": ("HTML", "html"),
}


def render_download_buttons(task_id: str, available_formats: list[str], key_prefix: str):
    cols = st.columns(len(_FMT_MAP))
    for col, (fmt_key, (label, api_fmt)) in zip(cols, _FMT_MAP.items()):
        with col:
            if fmt_key not in available_formats:
                st.button(f"{label} 不存在", disabled=True, key=f"{key_prefix}_{fmt_key}_missing")
                continue
            data = _get_cached_report(task_id, api_fmt)
            if data is None:
                if st.button(f"准备下载 {label}", key=f"{key_prefix}_{fmt_key}_prep"):
                    data = download_report_via_api(task_id, api_fmt)
                    if data:
                        st.session_state[f"_dl_{task_id}_{api_fmt}"] = data
                        st.rerun()
                    else:
                        st.error(f"{label} 下载失败")
            else:
                st.download_button(
                    f"下载 {label}",
                    data=data,
                    file_name=f"report_{task_id}.{api_fmt}",
                    mime=_MIME_TYPES.get(fmt_key, "application/octet-stream"),
                    key=f"{key_prefix}_{fmt_key}",
                )


st.title("📚 研究报告库")
st.caption("查看、筛选和下载已经生成的投研报告。")

# 通过 API 获取任务列表
tasks = fetch_task_history(page=1, page_size=100)

if not tasks:
    st.info("当前还没有生成过报告。请先到 Home 页面生成一份单票研究报告。")
    st.stop()


@st.cache_data(ttl=3600)
def _resolve_company_names(symbols: tuple[str, ...]) -> dict[str, str]:
    """批量解析 symbol → 公司名称。优先 QMT → AKShare → symbol 本身。"""
    result: dict[str, str] = {}
    unresolved: list[str] = []

    # 1. 尝试 QMT
    try:
        from xtquant import xtdata
        for sym in symbols:
            try:
                detail = xtdata.get_instrument_detail(sym)
                if isinstance(detail, dict):
                    name = (
                        detail.get("InstrumentName")
                        or detail.get("instrument_name")
                        or detail.get("name")
                    )
                    if name:
                        result[sym] = name
                        continue
            except Exception:
                pass
            unresolved.append(sym)
    except ImportError:
        unresolved = list(symbols)

    # 2. AKShare 降级
    if unresolved:
        try:
            from services.data.akshare_provider import get_company_name_akshare
            for sym in unresolved:
                name = get_company_name_akshare(sym)
                result[sym] = name if name else sym
        except Exception:
            for sym in unresolved:
                if sym not in result:
                    result[sym] = sym

    return result


# 收集所有 unique symbols 并批量解析公司名称
all_symbols = list({t.get("symbol", "") for t in tasks if t.get("status") == "completed"})
name_map = _resolve_company_names(tuple(sorted(all_symbols)))

# 构建报告列表
rows = []
for t in tasks:
    if t.get("status") != "completed":
        continue
    task_id = t["task_id"]
    symbol = t.get("symbol", "")

    rows.append({
        "task_id": task_id,
        "symbol": symbol,
        "company_name": name_map.get(symbol, symbol),
        "score": t.get("score"),
        "rating": t.get("rating"),
        "action": t.get("action"),
        "status": t.get("status"),
        "created_by": t.get("created_by", ""),
        "created_at": t.get("created_at"),
        "completed_at": t.get("completed_at"),
        "available_formats": t.get("report_formats", []),
    })

if not rows:
    st.info("当前还没有已完成的报告。请先到 Home 页面生成一份单票研究报告。")
    st.stop()

df = pd.DataFrame(rows)

with st.sidebar:
    st.header("筛选条件")

    keyword = st.text_input(
        "搜索代码或名称",
        value="",
        placeholder="例如：600519 或 贵州茅台",
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
        | filtered_df["company_name"].astype(str).str.lower().str.contains(kw)
    ]

if selected_rating != "全部":
    filtered_df = filtered_df[filtered_df["rating"].astype(str) == selected_rating]

if selected_action != "全部":
    filtered_df = filtered_df[filtered_df["action"].astype(str) == selected_action]

st.subheader("报告列表")

display_columns = [
    "symbol",
    "company_name",
    "score",
    "rating",
    "action",
    "completed_at",
]

# admin 用户额外显示"生成者"列
if is_admin():
    display_columns.insert(2, "created_by")

st.dataframe(
    filtered_df[display_columns],
    use_container_width=True,
    hide_index=True,
)

if filtered_df.empty:
    st.warning("没有符合筛选条件的报告。")
    st.stop()

symbol_options = [
    f'{row["symbol"]} {row.get("company_name", "")} - {row.get("rating", "-")} - {row.get("completed_at", "-")}'
    for _, row in filtered_df.iterrows()
]

selected_label = st.selectbox("选择一份报告查看详情", symbol_options)

selected_index = symbol_options.index(selected_label)
selected_row = filtered_df.iloc[selected_index]

task_id = selected_row["task_id"]
available_formats = selected_row["available_formats"]

st.subheader(f"报告详情 — {selected_row['symbol']} {selected_row.get('company_name', '')}")

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
    json_data = _get_cached_report(task_id, "json")
    if json_data:
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
    md_data = _get_cached_report(task_id, "md")
    if md_data:
        with st.expander("预览 Markdown 报告"):
            st.markdown(md_data.decode("utf-8", errors="replace"))
