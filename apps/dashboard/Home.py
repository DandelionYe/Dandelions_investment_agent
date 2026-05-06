"""Dandelions 投研智能体 — 入口引导页。"""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from apps.dashboard.components.login import require_login

st.set_page_config(page_title="Dandelions 投研智能体", page_icon="📈", layout="wide")
require_login()

st.title("Dandelions 投研智能体")
st.caption("量化研究 + LLM 辩论 + 决策保护器 + 报告生成")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    with st.container(border=True):
        st.subheader("🔬 单票研究")
        st.caption("输入沪深京 A 股或 ETF 代码，经过数据加载 → 六维度评分 → 多轮 LLM 辩论 → 决策保护，生成 JSON/MD/HTML/PDF 报告。")
        st.page_link("pages/1_Single_Asset_Research.py", label="进入单票研究 →", icon="🔬")

with col2:
    with st.container(border=True):
        st.subheader("📋 观察池")
        st.caption("管理关注标的：文件夹 + 标签两级分组、逐票自定义 cron 定时扫描、条件触发器、批量扫描和评分历史追踪。")
        st.page_link("pages/3_观察池.py", label="进入观察池 →", icon="📋")

with col3:
    with st.container(border=True):
        st.subheader("📊 报告库")
        st.caption("浏览历史生成的研究报告，按评级/操作建议筛选，查看详细评分和辩论结果。")
        st.page_link("pages/2_Report_Library.py", label="进入报告库 →", icon="📊")
