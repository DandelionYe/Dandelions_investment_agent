"""组合分析 — 多标的组合评分、风险汇总、仓位建议。

本页面为研究工作台，所有输出均为研究建议，不构成交易指令。
系统不会自动下单。
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

from apps.dashboard.components.login import (
    authenticated_request,
    require_login,
)

st.set_page_config(page_title="组合分析", page_icon="📊", layout="wide")
require_login()


def _api_call(method: str, path: str, **kwargs):
    try:
        resp = authenticated_request(method, path, timeout=30, **kwargs)
        if resp.status_code >= 400:
            st.error(f"API 错误 [{resp.status_code}]: {resp.text[:500]}")
            return None
        return resp.json()
    except Exception as exc:
        st.error(f"API 请求失败: {exc}")
        return None


# ── 页面标题 ──────────────────────────────────────────────────

st.title("📊 组合分析")
st.caption("多标的组合评分、风险汇总、仓位建议。所有输出为研究建议，不构成交易指令。")

# ── 侧边栏配置 ────────────────────────────────────────────────

with st.sidebar:
    st.subheader("分析配置")

    source_mode = st.radio(
        "持仓来源",
        ["观察池", "手动输入"],
        key="portfolio_source",
    )

    risk_profile = st.selectbox(
        "风险偏好",
        ["conservative", "balanced", "aggressive"],
        format_func=lambda x: {
            "conservative": "保守型",
            "balanced": "均衡型",
            "aggressive": "进取型",
        }[x],
        index=1,
        key="risk_profile",
    )

    st.caption("约束条件")
    max_single = st.slider("单标的上限", 5, 100, 25, 5,
                           key="max_single", format="%d%%") / 100
    max_industry = st.slider("行业上限", 10, 100, 35, 5,
                             key="max_industry", format="%d%%") / 100
    min_cash = st.slider("最低现金", 0, 50, 5, 5,
                         key="min_cash", format="%d%%") / 100

# ── 持仓输入 ──────────────────────────────────────────────────

positions = []

if source_mode == "观察池":
    # Load folders
    folders = _api_call("GET", "/api/v1/watchlist/folders") or []
    folder_options = {f["id"]: f["name"] for f in folders}

    col1, col2 = st.columns(2)
    with col1:
        use_all = st.checkbox("使用全部观察项", value=True, key="use_all_wl")
    with col2:
        if not use_all and folder_options:
            selected_folder = st.selectbox(
                "选择文件夹",
                options=list(folder_options.keys()),
                format_func=lambda x: folder_options[x],
                key="wl_folder",
            )
        else:
            selected_folder = None

    if st.button("🔍 生成组合分析", type="primary", use_container_width=True):
        body = {
            "risk_profile": risk_profile,
            "max_single_weight": max_single,
            "max_industry_weight": max_industry,
            "min_cash_weight": min_cash,
        }
        if use_all:
            body["use_watchlist_all"] = True
        elif selected_folder:
            body["watchlist_folder_id"] = selected_folder

        with st.spinner("正在分析组合..."):
            result = _api_call("POST", "/api/v1/portfolio/analyze", json=body)

        if result:
            st.session_state["portfolio_result"] = result
            st.rerun()

else:
    # Manual input
    st.subheader("手动输入持仓")
    num_positions = st.number_input("标的数量", min_value=1, max_value=20, value=3,
                                    key="num_positions")

    header_cols = st.columns([2, 1, 2, 1])
    for col, label in zip(header_cols, ["代码", "类型", "名称", "当前权重%"]):
        with col:
            st.caption(label)

    for i in range(num_positions):
        cols = st.columns([2, 1, 2, 1])
        with cols[0]:
            symbol = st.text_input(f"代码 {i+1}", key=f"sym_{i}",
                                   placeholder="600519.SH")
        with cols[1]:
            asset_type = st.selectbox(f"类型 {i+1}", ["stock", "etf"],
                                      key=f"type_{i}",
                                      format_func=lambda x: "股票" if x == "stock" else "ETF",
                                      label_visibility="collapsed")
        with cols[2]:
            asset_name = st.text_input(f"名称 {i+1}", key=f"name_{i}",
                                       label_visibility="collapsed")
        with cols[3]:
            current_weight = st.number_input(
                f"当前权重 {i+1}",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=1.0,
                key=f"weight_{i}",
                label_visibility="collapsed",
            )
        if symbol:
            positions.append({
                "symbol": symbol,
                "asset_type": asset_type,
                "asset_name": asset_name,
                "current_weight": current_weight / 100,
            })

    if st.button("🔍 生成组合分析", type="primary", use_container_width=True):
        if not positions:
            st.warning("请至少输入一个标的")
        else:
            body = {
                "positions": positions,
                "risk_profile": risk_profile,
                "max_single_weight": max_single,
                "max_industry_weight": max_industry,
                "min_cash_weight": min_cash,
            }
            with st.spinner("正在分析组合..."):
                result = _api_call("POST", "/api/v1/portfolio/analyze", json=body)

            if result:
                st.session_state["portfolio_result"] = result
                st.rerun()

# ── 结果展示 ──────────────────────────────────────────────────

result = st.session_state.get("portfolio_result")

if result:
    st.divider()

    # 声明
    st.info("📋 以下所有内容为研究建议，不构成交易指令。系统不会自动下单。")

    # 概览指标
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("组合评分",
                  f"{result['portfolio_score']:.0f}" if result.get('portfolio_score') else "N/A")
    with c2:
        st.metric("组合评级", result.get("portfolio_rating") or "N/A")
    with c3:
        risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            result.get("risk_level", ""), "⚪")
        st.metric("风险等级", f"{risk_emoji} {result.get('risk_level', 'N/A')}")
    with c4:
        st.metric("建议现金", f"{result.get('cash_weight', 0):.1%}")
    with c5:
        st.metric("持仓数量", result.get("total_holdings", 0))

    # 持仓表
    st.subheader("持仓明细")
    holdings = result.get("holdings", [])
    if holdings:
        df_data = []
        for h in holdings:
            df_data.append({
                "代码": h["symbol"],
                "名称": h.get("asset_name", ""),
                "评分": f"{h['score']:.0f}" if h.get("score") is not None else "N/A",
                "评级": h.get("rating") or "-",
                "建议": h.get("action") or "-",
                "风险": h.get("risk_level") or "-",
                "行业": h.get("industry") or "-",
                "当前权重": f"{h.get('current_weight', 0):.1%}",
                "目标权重": "N/A" if h.get("score") is None else f"{h.get('target_weight', 0):.1%}",
                "变动": "N/A" if h.get("score") is None else f"{h.get('delta_weight', 0):+.1%}",
                "再平衡": h.get("rebalance_action") or "-",
                "警告": "; ".join(h.get("data_warnings", [])) or "-",
            })
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # 行业暴露
    col_ind, col_type = st.columns(2)
    with col_ind:
        st.subheader("行业暴露")
        ind_exp = result.get("industry_exposure", {})
        if ind_exp:
            ind_df = pd.DataFrame([
                {"行业": k, "权重": f"{v:.1%}"} for k, v in ind_exp.items()
            ])
            st.dataframe(ind_df, use_container_width=True, hide_index=True)

    with col_type:
        st.subheader("资产类型暴露")
        type_exp = result.get("asset_type_exposure", {})
        if type_exp:
            for at, w in type_exp.items():
                st.write(f"- **{at}:** {w:.1%}")

    # 再平衡建议
    suggestions = result.get("rebalance_suggestions", [])
    if suggestions:
        st.subheader("再平衡建议")
        for s in suggestions:
            st.write(f"- {s}")

    rebal_details = [
        h for h in holdings
        if h.get("rebalance_reason")
    ]
    if rebal_details:
        st.subheader("再平衡明细")
        for h in rebal_details:
            st.write(f"- **{h['symbol']}**: {h['rebalance_reason']}")

    # 缺失数据
    missing = result.get("missing_reasons", [])
    if missing:
        st.subheader("缺失数据提示")
        for m in missing:
            st.warning(m)

    # 数据警告
    warnings = result.get("data_warnings", [])
    if warnings:
        st.subheader("数据质量警告")
        for w in warnings:
            st.warning(w)

    # 下载
    st.divider()
    st.subheader("下载报告")
    artifacts = result.get("artifact_paths", {})
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        if artifacts.get("json"):
            try:
                json_content = Path(artifacts["json"]).read_text(encoding="utf-8")
                st.download_button(
                    "📥 下载 JSON",
                    data=json_content,
                    file_name=f"portfolio_{result['analysis_id']}.json",
                    mime="application/json",
                )
            except Exception:
                st.caption("JSON 文件不可用")
    with col_dl2:
        if artifacts.get("markdown"):
            try:
                md_content = Path(artifacts["markdown"]).read_text(encoding="utf-8")
                st.download_button(
                    "📥 下载 Markdown",
                    data=md_content,
                    file_name=f"portfolio_{result['analysis_id']}.md",
                    mime="text/markdown",
                )
            except Exception:
                st.caption("Markdown 文件不可用")

else:
    st.info("请在左侧配置持仓来源和参数，点击「生成组合分析」开始。")
