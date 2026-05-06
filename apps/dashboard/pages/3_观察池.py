"""观察池 — 批量标的监控与管理。

使用方式：
  - 当 FastAPI 后端运行时自动走 API 调用
  - 后端不可用时直接访问 SQLite 存储（独立模式）
"""

import json
import sys
from pathlib import Path

import streamlit as st
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

st.set_page_config(page_title="观察池", page_icon="📋", layout="wide")

# ── API / 独立模式检测 ────────────────────────────────────────

API_BASE = "http://localhost:8000"


def _api_available() -> bool:
    try:
        import requests
        resp = requests.get(f"{API_BASE}/api/v1/health/ready", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _api_call(method: str, path: str, **kwargs) -> dict | list | None:
    import requests
    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(method, url, timeout=10, **kwargs)
        if resp.status_code >= 400:
            st.error(f"API 错误 [{resp.status_code}]: {resp.text[:300]}")
            return None
        return resp.json()
    except Exception as exc:
        st.error(f"API 请求失败: {exc}")
        return None


# ── 独立模式 store ────────────────────────────────────────────

def _get_store():
    from apps.api.task_manager.store import get_watchlist_store
    return get_watchlist_store()


# ── Session 初始化 ─────────────────────────────────────────────

if "wl_api_ok" not in st.session_state:
    st.session_state["wl_api_ok"] = _api_available()
if "wl_selected_folder" not in st.session_state:
    st.session_state["wl_selected_folder"] = None
if "wl_selected_tag" not in st.session_state:
    st.session_state["wl_selected_tag"] = None
if "wl_selected_item" not in st.session_state:
    st.session_state["wl_selected_item"] = None
if "wl_show_add_item" not in st.session_state:
    st.session_state["wl_show_add_item"] = False
if "wl_show_add_folder" not in st.session_state:
    st.session_state["wl_show_add_folder"] = False
if "wl_show_add_tag" not in st.session_state:
    st.session_state["wl_show_add_tag"] = False


# ── 数据加载 ───────────────────────────────────────────────────

def _load_folders() -> list[dict]:
    if st.session_state["wl_api_ok"]:
        result = _api_call("GET", "/api/v1/watchlist/folders")
        return result if isinstance(result, list) else []
    return _get_store().list_folders()


def _load_tags() -> list[dict]:
    if st.session_state["wl_api_ok"]:
        result = _api_call("GET", "/api/v1/watchlist/tags")
        return result if isinstance(result, list) else []
    return _get_store().list_tags()


def _load_items(folder_id=None, tag_id=None, enabled=None) -> list[dict]:
    if st.session_state["wl_api_ok"]:
        params = {}
        if folder_id:
            params["folder_id"] = folder_id
        if tag_id:
            params["tag_id"] = tag_id
        if enabled is not None:
            params["enabled"] = str(enabled).lower()
        params["page_size"] = 200
        result = _api_call("GET", "/api/v1/watchlist/items", params=params)
        if result and "items" in result:
            return result["items"]
        return []
    items, _ = _get_store().list_items(folder_id=folder_id, tag_id=tag_id,
                                        enabled=enabled, page=1, page_size=200)
    return items


# ── 操作 ───────────────────────────────────────────────────────

def _trigger_scan(item_ids=None, folder_id=None):
    if st.session_state["wl_api_ok"]:
        body = {"trigger_type": "manual"}
        if item_ids:
            body["item_ids"] = item_ids
        if folder_id:
            body["folder_id"] = folder_id
        return _api_call("POST", "/api/v1/watchlist/scan", json=body)
    else:
        from apps.api.task_manager.manager import WatchlistManager
        wm = WatchlistManager()
        return wm.trigger_scan(item_ids=item_ids, folder_id=folder_id)


# ── 渲染 ───────────────────────────────────────────────────────

st.title("📋 观察池")

# 顶部概览
items_all = _load_items()
folders = _load_folders()
tags = _load_tags()

enabled_count = sum(1 for i in items_all if i.get("enabled"))
api_label = "🔗 API 模式" if st.session_state["wl_api_ok"] else "💾 本地模式"

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("总标的", len(items_all))
with col2:
    st.metric("已启用", enabled_count)
with col3:
    st.metric("文件夹", len(folders))
with col4:
    st.metric("模式", api_label)

st.divider()

# ── 侧边栏 ────────────────────────────────────────────────────

with st.sidebar:
    st.subheader("📁 文件夹")

    if st.button("📋 全部", use_container_width=True,
                 type="secondary" if st.session_state["wl_selected_folder"] else "primary"):
        st.session_state["wl_selected_folder"] = None
        st.session_state["wl_selected_tag"] = None
        st.rerun()

    for f in folders:
        label = f"{f.get('icon', '📁')} {f['name']} ({f.get('item_count', 0)})"
        is_active = st.session_state["wl_selected_folder"] == f["id"]
        if st.button(label, key=f"folder_{f['id']}", use_container_width=True,
                     type="primary" if is_active else "secondary"):
            st.session_state["wl_selected_folder"] = f["id"]
            st.session_state["wl_selected_tag"] = None
            st.rerun()

    if st.button("➕ 新建文件夹", use_container_width=True):
        st.session_state["wl_show_add_folder"] = True
        st.session_state["wl_show_add_tag"] = False
        st.rerun()

    st.divider()
    st.subheader("🏷 标签")

    if tags:
        for t in tags:
            label = f"{t['name']} ({t.get('item_count', 0)})"
            is_active = st.session_state["wl_selected_tag"] == t["id"]
            if st.button(label, key=f"tag_{t['id']}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state["wl_selected_tag"] = t["id"]
                st.session_state["wl_selected_folder"] = None
                st.rerun()
    else:
        st.caption("暂无标签")

    if st.button("➕ 新建标签", use_container_width=True):
        st.session_state["wl_show_add_tag"] = True
        st.session_state["wl_show_add_folder"] = False
        st.rerun()

    st.divider()

    st.subheader("🔍 操作")
    if st.button("🔬 扫描启用的全部", use_container_width=True, type="primary"):
        result = _trigger_scan()
        if result:
            batch_id = result.get("batch_id")
            if batch_id and st.session_state["wl_api_ok"]:
                from apps.dashboard.components.progress_poller import poll_batch_progress
                poll_batch_progress(batch_id)
            else:
                st.success(f"已触发扫描 {result.get('total_items', 0)} 个标的（离线模式，无法显示进度）")
        else:
            st.error("扫描触发失败")

    if st.button("➕ 添加观察标的", use_container_width=True):
        st.session_state["wl_show_add_item"] = True
        st.rerun()

# ── 添加文件夹对话框 ──────────────────────────────────────────

if st.session_state.get("wl_show_add_folder"):
    with st.sidebar:
        with st.container(border=True):
            name = st.text_input("名称", key="new_folder_name")
            desc = st.text_input("描述", key="new_folder_desc")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("保存", use_container_width=True):
                    if name:
                        if st.session_state["wl_api_ok"]:
                            _api_call("POST", "/api/v1/watchlist/folders",
                                      json={"name": name, "description": desc})
                        else:
                            _get_store().create_folder(name=name, description=desc)
                        st.session_state["wl_show_add_folder"] = False
                        st.rerun()
            with c2:
                if st.button("取消", use_container_width=True):
                    st.session_state["wl_show_add_folder"] = False
                    st.rerun()

# ── 添加标签对话框 ────────────────────────────────────────────

if st.session_state.get("wl_show_add_tag"):
    with st.sidebar:
        with st.container(border=True):
            name = st.text_input("标签名", key="new_tag_name")
            color = st.color_picker("颜色", "#6366f1", key="new_tag_color")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("保存", key="save_tag", use_container_width=True):
                    if name:
                        if st.session_state["wl_api_ok"]:
                            _api_call("POST", "/api/v1/watchlist/tags",
                                      json={"name": name, "color": color})
                        else:
                            try:
                                _get_store().create_tag(name=name, color=color)
                            except ValueError as exc:
                                st.error(str(exc))
                        st.session_state["wl_show_add_tag"] = False
                        st.rerun()
            with c2:
                if st.button("取消", key="cancel_tag", use_container_width=True):
                    st.session_state["wl_show_add_tag"] = False
                    st.rerun()

# ── 主区域 ────────────────────────────────────────────────────

# 筛选后的 items
selected_folder = st.session_state["wl_selected_folder"]
selected_tag = st.session_state["wl_selected_tag"]
items = _load_items(folder_id=selected_folder, tag_id=selected_tag)

# 状态筛选
status_filter = st.radio("状态", ["全部", "已启用", "已暂停"], horizontal=True,
                         key="status_filter")
if status_filter == "已启用":
    items = [i for i in items if i.get("enabled")]
elif status_filter == "已暂停":
    items = [i for i in items if not i.get("enabled")]

# 数据表
if items:
    df_data = []
    for it in items:
        tag_names = ", ".join(t["name"] for t in (it.get("tags") or []))
        df_data.append({
            "id": it["id"],
            "代码": it["symbol"],
            "名称": it.get("asset_name", ""),
            "文件夹": it.get("folder_name", ""),
            "标签": tag_names,
            "调度": it.get("schedule_config", {}).get("mode", "cron"),
            "最近评分": f"{it.get('last_score', '-'):.0f}" if it.get("last_score") else "-",
            "评级": it.get("last_rating") or "-",
            "操作建议": it.get("last_action") or "-",
            "状态": "✅" if it.get("enabled") else "⏸",
        })

    df = pd.DataFrame(df_data)
    st.dataframe(
        df.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="medium"),
            "文件夹": st.column_config.TextColumn(width="small"),
            "标签": st.column_config.TextColumn(width="small"),
            "调度": st.column_config.TextColumn(width="small"),
            "最近评分": st.column_config.TextColumn(width="small"),
            "评级": st.column_config.TextColumn(width="small"),
            "操作建议": st.column_config.TextColumn(width="medium"),
            "状态": st.column_config.TextColumn(width="small"),
        },
    )

    # 详情面板
    st.divider()
    st.subheader("📊 标的详情")
    selected_symbol = st.selectbox(
        "选择标的查看详情",
        options=[it["id"] for it in items],
        format_func=lambda x: next((f"{it['symbol']} {it.get('asset_name', '')}" for it in items if it["id"] == x), x),
        key="item_detail_select",
    )

    if selected_symbol:
        item = next((it for it in items if it["id"] == selected_symbol), None)
        if item:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("最近评分", f"{item.get('last_score', '-'):.0f}" if item.get("last_score") else "-")
            with c2:
                st.metric("评级", item.get("last_rating") or "-")
            with c3:
                st.metric("操作建议", item.get("last_action") or "-")
            with c4:
                sc = item.get("schedule_config", {})
                st.metric("调度模式", sc.get("mode", "-"))

            # 调度详情
            sc = item.get("schedule_config", {})
            if sc.get("mode") == "cron":
                st.caption(f"⏰ Crontab: `{sc.get('cron_expression', '-')}` | 下次扫描: {item.get('next_scan_at', '-')}")

            # 标签
            tag_names = [t["name"] for t in (item.get("tags") or [])]
            if tag_names:
                st.write("🏷 " + " · ".join(tag_names))

            # 备注
            if item.get("notes"):
                st.caption(f"📝 {item['notes']}")

            # 操作按钮
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                if st.button("🔬 立即扫描", use_container_width=True):
                    result = _trigger_scan(item_ids=[item["id"]])
                    if result:
                        batch_id = result.get("batch_id")
                        if batch_id and st.session_state["wl_api_ok"]:
                            from apps.dashboard.components.progress_poller import poll_batch_progress
                            poll_batch_progress(batch_id)
                            st.rerun()
                        else:
                            st.success("已触发扫描")
                            st.rerun()
            with col_b:
                new_enabled = not item.get("enabled", True)
                label = "▶ 启用" if new_enabled else "⏸ 暂停"
                if st.button(label, use_container_width=True):
                    if st.session_state["wl_api_ok"]:
                        _api_call("PUT", f"/api/v1/watchlist/items/{item['id']}",
                                  json={"enabled": new_enabled})
                    else:
                        _get_store().update_item(item["id"], enabled=new_enabled)
                    st.rerun()
            with col_c:
                if st.button("🗑 移除", use_container_width=True):
                    if st.session_state["wl_api_ok"]:
                        _api_call("DELETE", f"/api/v1/watchlist/items/{item['id']}")
                    else:
                        _get_store().remove_item(item["id"])
                    st.success("已移除")
                    st.rerun()
            with col_d:
                target = item.get("target_action", "观察")
                new_target = st.selectbox("目标操作", ["观察", "回调关注", "持有", "回避"],
                                          index=["观察", "回调关注", "持有", "回避"].index(target)
                                          if target in ["观察", "回调关注", "持有", "回避"] else 0,
                                          key=f"target_{item['id']}",
                                          label_visibility="collapsed")
                if new_target != target:
                    if st.session_state["wl_api_ok"]:
                        _api_call("PUT", f"/api/v1/watchlist/items/{item['id']}",
                                  json={"target_action": new_target})
                    else:
                        _get_store().update_item(item["id"], target_action=new_target)
                    st.rerun()

            # 历史扫描记录
            st.divider()
            st.subheader("📜 扫描历史")
            history = item.get("scan_history") or []
            if history:
                hist_df = pd.DataFrame(history)
                hist_df = hist_df.rename(columns={
                    "symbol": "代码", "score": "评分", "rating": "评级",
                    "action": "建议", "status": "状态", "created_at": "时间",
                })
                st.dataframe(hist_df[["时间", "评分", "评级", "建议", "状态"]],
                             use_container_width=True, hide_index=True)
            else:
                st.caption("暂无扫描记录")

else:
    st.info("还没有观察标的。点击左侧「添加观察标的」开始。")

# ── 添加观察项对话框 ──────────────────────────────────────────

if st.session_state.get("wl_show_add_item"):
    with st.sidebar:
        with st.container(border=True):
            st.subheader("添加观察标的")
            symbol = st.text_input("代码（如 600519.SH）", key="add_symbol")
            asset_name = st.text_input("名称（可选）", key="add_asset_name")
            asset_type = st.selectbox("类型", ["stock", "etf"], key="add_asset_type",
                                      format_func=lambda x: "股票" if x == "stock" else "ETF")

            folder_options = {f["id"]: f["name"] for f in folders}
            if not folder_options:
                st.error("请先创建文件夹")
            else:
                folder_id = st.selectbox("文件夹", options=list(folder_options.keys()),
                                         format_func=lambda x: folder_options[x],
                                         key="add_folder_id")
                notes = st.text_area("备注", key="add_notes")
                target_action = st.selectbox("目标动作", ["观察", "回调关注", "持有", "回避"],
                                             key="add_target_action")

                st.caption("调度配置")
                mode = st.selectbox("模式", ["cron", "manual_only"],
                                    key="add_schedule_mode",
                                    format_func=lambda x: {"cron": "定时扫描", "manual_only": "仅手动"}[x])
                cron_expr = "0 9 * * 1-5"
                if mode == "cron":
                    cron_expr = st.text_input("Crontab", value="0 9 * * 1-5",
                                              key="add_cron",
                                              help="工作日 9:00 = 0 9 * * 1-5")

                tag_options = {t["id"]: t["name"] for t in tags}
                tag_ids = []
                if tag_options:
                    selected_tags = st.multiselect("标签", options=list(tag_options.keys()),
                                                   format_func=lambda x: tag_options[x],
                                                   key="add_tags")
                    tag_ids = selected_tags

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("确认添加", use_container_width=True):
                        if symbol and folder_id:
                            body = {
                                "symbol": symbol,
                                "asset_type": asset_type,
                                "asset_name": asset_name,
                                "folder_id": folder_id,
                                "notes": notes,
                                "target_action": target_action,
                                "schedule_config": {
                                    "mode": mode,
                                    "cron_expression": cron_expr,
                                    "condition_triggers": {},
                                },
                                "tag_ids": tag_ids,
                            }
                            if st.session_state["wl_api_ok"]:
                                result = _api_call("POST", "/api/v1/watchlist/items", json=body)
                            else:
                                from apps.api.task_manager.manager import WatchlistManager
                                wm = WatchlistManager()
                                result = wm.add_item(**{k: v for k, v in body.items()
                                                          if k != "schedule_config"},
                                                       schedule_config=body["schedule_config"])
                            if result:
                                st.success(f"已添加 {symbol}")
                                st.session_state["wl_show_add_item"] = False
                                st.rerun()
                with c2:
                    if st.button("取消", key="cancel_add_item", use_container_width=True):
                        st.session_state["wl_show_add_item"] = False
                        st.rerun()

# ── 底部操作 ──────────────────────────────────────────────────

st.divider()
col_a, col_b = st.columns(2)
with col_a:
    if st.button("🔬 扫描选中文件夹", use_container_width=True):
        if selected_folder:
            result = _trigger_scan(folder_id=selected_folder)
            if result:
                st.success(f"已触发扫描 {result.get('total_items', 0)} 个标的")
        else:
            st.warning("请先在左侧选择一个文件夹")

with col_b:
    if st.button("🗂️ 转到报告库", use_container_width=True):
        st.switch_page("pages/2_Report_Library.py")
