from pathlib import Path
import json
import sys
from datetime import datetime

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "storage" / "reports"


st.set_page_config(
    page_title="Report Library - Dandelions",
    page_icon="📚",
    layout="wide",
)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def safe_get(data: dict, key: str, default="暂无"):
    value = data.get(key, default)
    if value is None or value == "":
        return default
    return value


def find_report_files(symbol: str) -> dict:
    """
    根据 symbol 查找对应的 JSON / Markdown / HTML / PDF 文件。
    """
    return {
        "json": REPORTS_DIR / f"{symbol}_result.json",
        "markdown": REPORTS_DIR / f"{symbol}_report.md",
        "html": REPORTS_DIR / f"{symbol}_report.html",
        "pdf": REPORTS_DIR / f"{symbol}_report.pdf",
    }


def file_mtime(path: Path) -> str:
    if not path.exists():
        return "暂无"

    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def scan_reports() -> list[dict]:
    """
    扫描 storage/reports 下所有 *_result.json 文件。
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    rows = []

    for json_path in REPORTS_DIR.glob("*_result.json"):
        data = read_json(json_path)
        if not data:
            continue

        symbol = safe_get(data, "symbol", json_path.stem.replace("_result", ""))
        files = find_report_files(symbol)

        decision_guard = data.get("decision_guard", {})
        debate_result = data.get("debate_result", {})
        committee = debate_result.get("committee_conclusion", {})

        rows.append(
            {
                "symbol": symbol,
                "name": safe_get(data, "name"),
                "asset_type": safe_get(data, "asset_type"),
                "as_of": safe_get(data, "as_of"),
                "data_source": safe_get(data, "data_source"),
                "score": safe_get(data, "score"),
                "rating": safe_get(data, "rating"),
                "action": safe_get(data, "action"),
                "stance": committee.get("stance", "暂无"),
                "confidence": committee.get("confidence", "暂无"),
                "risk_level": decision_guard.get("risk_level", "暂无"),
                "updated_at": file_mtime(json_path),
                "json_path": str(files["json"]),
                "markdown_path": str(files["markdown"]),
                "html_path": str(files["html"]),
                "pdf_path": str(files["pdf"]),
            }
        )

    rows.sort(key=lambda x: x["updated_at"], reverse=True)

    return rows


def read_text_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""

    return p.read_text(encoding="utf-8")


def read_binary_file(path: str) -> bytes:
    p = Path(path)
    if not p.exists():
        return b""

    return p.read_bytes()


def render_download_buttons(row: dict, key_prefix: str):
    col1, col2, col3, col4 = st.columns(4)

    pdf_path = Path(row["pdf_path"])
    md_path = Path(row["markdown_path"])
    json_path = Path(row["json_path"])
    html_path = Path(row["html_path"])

    with col1:
        if pdf_path.exists():
            st.download_button(
                "下载 PDF",
                data=read_binary_file(str(pdf_path)),
                file_name=pdf_path.name,
                mime="application/pdf",
                key=f"{key_prefix}_pdf",
            )
        else:
            st.button("PDF 不存在", disabled=True, key=f"{key_prefix}_pdf_missing")

    with col2:
        if md_path.exists():
            st.download_button(
                "下载 Markdown",
                data=read_text_file(str(md_path)),
                file_name=md_path.name,
                mime="text/markdown",
                key=f"{key_prefix}_md",
            )
        else:
            st.button("Markdown 不存在", disabled=True, key=f"{key_prefix}_md_missing")

    with col3:
        if json_path.exists():
            st.download_button(
                "下载 JSON",
                data=read_text_file(str(json_path)),
                file_name=json_path.name,
                mime="application/json",
                key=f"{key_prefix}_json",
            )
        else:
            st.button("JSON 不存在", disabled=True, key=f"{key_prefix}_json_missing")

    with col4:
        if html_path.exists():
            st.download_button(
                "下载 HTML",
                data=read_text_file(str(html_path)),
                file_name=html_path.name,
                mime="text/html",
                key=f"{key_prefix}_html",
            )
        else:
            st.button("HTML 不存在", disabled=True, key=f"{key_prefix}_html_missing")


def render_report_detail(row: dict):
    symbol = row["symbol"]
    json_path = Path(row["json_path"])
    data = read_json(json_path)

    if not data:
        st.error("无法读取该报告的 JSON 文件。")
        return

    st.subheader(f"{data.get('name', '未知标的')}（{symbol}）")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("综合评分", f"{data.get('score', '暂无')} / 100")

    with col2:
        st.metric("评级", data.get("rating", "暂无"))

    with col3:
        st.metric("操作建议", data.get("action", "暂无"))

    with col4:
        st.metric("数据源", data.get("data_source", "暂无"))

    with col5:
        st.metric("研究日期", data.get("as_of", "暂无"))

    st.markdown("### 投委会最终观点")
    st.info(data.get("final_opinion", "暂无"))

    decision_guard = data.get("decision_guard", {})
    if decision_guard:
        st.markdown("### 决策保护器")
        st.table(
            [
                {"项目": "本地评分", "内容": str(decision_guard.get("score", "暂无"))},
                {"项目": "本地评级", "内容": decision_guard.get("rating", "暂无")},
                {"项目": "风险等级", "内容": decision_guard.get("risk_level", "暂无")},
                {"项目": "模型原始建议", "内容": decision_guard.get("llm_action", "暂无")},
                {"项目": "系统允许最高建议", "内容": decision_guard.get("max_allowed_action", "暂无")},
                {"项目": "最终建议", "内容": decision_guard.get("final_action", "暂无")},
            ]
        )

    debate_result = data.get("debate_result", {})
    if debate_result:
        st.markdown("### 多头 / 空头 / 风险官摘要")

        bull_case = debate_result.get("bull_case", {})
        bear_case = debate_result.get("bear_case", {})
        risk_review = debate_result.get("risk_review", {})

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("#### 多头观点")
            st.write(bull_case.get("thesis", "暂无"))

        with c2:
            st.markdown("#### 空头观点")
            st.write(bear_case.get("thesis", "暂无"))

        with c3:
            st.markdown("#### 风险官意见")
            st.write(risk_review.get("risk_summary", "暂无"))

    st.markdown("### 报告文件")
    render_download_buttons(row, key_prefix=f"detail_{symbol}")

    with st.expander("查看完整 JSON"):
        st.json(data)

    markdown_path = Path(row["markdown_path"])
    if markdown_path.exists():
        with st.expander("预览 Markdown 报告"):
            st.markdown(read_text_file(str(markdown_path)))


st.title("📚 研究报告库")
st.caption("查看、筛选和下载已经生成的投研报告。")

rows = scan_reports()

if not rows:
    st.info("当前还没有生成过报告。请先到 Home 页面生成一份单票研究报告。")
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
        | filtered_df["name"].astype(str).str.lower().str.contains(kw)
    ]

if selected_rating != "全部":
    filtered_df = filtered_df[filtered_df["rating"].astype(str) == selected_rating]

if selected_action != "全部":
    filtered_df = filtered_df[filtered_df["action"].astype(str) == selected_action]

st.subheader("报告列表")

display_columns = [
    "symbol",
    "name",
    "asset_type",
    "as_of",
    "data_source",
    "score",
    "rating",
    "action",
    "risk_level",
    "updated_at",
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
    f'{row["symbol"]} - {row["name"]} - {row["updated_at"]}'
    for _, row in filtered_df.iterrows()
]

selected_label = st.selectbox("选择一份报告查看详情", symbol_options)

selected_index = symbol_options.index(selected_label)
selected_row = filtered_df.iloc[selected_index].to_dict()

render_report_detail(selected_row)