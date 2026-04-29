from pathlib import Path
import json
import sys
import asyncio

# Windows + Streamlit + Playwright 场景下，需要使用 ProactorEventLoop，
# 否则 Playwright 启动 Chromium 子进程时可能触发 NotImplementedError。
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except AttributeError:
        pass

import streamlit as st


# 让 Streamlit 能找到项目根目录下的 services 包
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))


from services.orchestrator.single_asset_research import run_single_asset_research
from services.report.json_builder import save_json_result
from services.report.markdown_builder import save_markdown_report
from services.report.html_builder import save_html_report
from services.report.pdf_builder_playwright import save_pdf_report_with_playwright
from services.data.data_quality import (
    build_data_quality_notes,
    format_money_like_value,
    format_number,
    format_percent,
    localize_asset_type,
    localize_bool,
    localize_data_source,
    localize_data_vendor,
    localize_ma_position,
    localize_risk_level,
)


st.set_page_config(
    page_title="Dandelions 投研智能体",
    page_icon="📈",
    layout="wide",
)


def run_research(symbol: str, data_source: str, use_llm: bool) -> dict:
    """
    执行单票研究，并生成 JSON / Markdown / HTML / PDF 报告。
    """
    result = run_single_asset_research(
        symbol=symbol,
        use_llm=use_llm,
        data_source=data_source,
    )

    json_path = save_json_result(result)
    markdown_path = save_markdown_report(result)
    html_path = save_html_report(markdown_path)
    pdf_path = save_pdf_report_with_playwright(html_path)

    result["_artifact_paths"] = {
        "json": json_path,
        "markdown": markdown_path,
        "html": html_path,
        "pdf": pdf_path,
    }

    return result


def read_file_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def read_file_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def render_summary(result: dict):
    price_data = result.get("price_data", {})
    decision_guard = result.get("decision_guard", {})

    st.subheader("一、投委会结论")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("综合评分", f'{result.get("score", "暂无")} / 100')

    with col2:
        st.metric("评级", result.get("rating", "暂无"))

    with col3:
        st.metric("操作建议", result.get("action", "暂无"))

    with col4:
        st.metric("建议仓位", result.get("max_position", "暂无"))

    with col5:
        st.metric("数据源", localize_data_source(result.get("data_source", "暂无")))

    st.info(result.get("final_opinion", "暂无最终观点"))

    if decision_guard:
        st.caption(
            "决策保护器："
            f'模型原始建议「{decision_guard.get("llm_action", "暂无")}」；'
            f'系统允许最高建议「{decision_guard.get("max_allowed_action", "暂无")}」；'
            f'最终建议「{decision_guard.get("final_action", result.get("action", "暂无"))}」。'
        )

    st.subheader("二、行情摘要")

    col_a, col_b, col_c, col_d = st.columns(4)

    with col_a:
        st.metric("最新收盘价", format_number(price_data.get("close")))

    with col_b:
        st.metric("近20日涨跌幅", format_percent(price_data.get("change_20d")))

    with col_c:
        st.metric("近60日涨跌幅", format_percent(price_data.get("change_60d")))

    with col_d:
        st.metric("行情供应商", localize_data_vendor(price_data.get("data_vendor", "暂无")))


def render_price_data(result: dict):
    st.subheader("三、数据来源与行情数据")

    price_data = result.get("price_data", {})
    data_vendor_raw = price_data.get("data_vendor", "")

    rows = [
        {"指标": "资产类型", "数值": localize_asset_type(result.get("asset_type"))},
        {"指标": "数据来源", "数值": localize_data_source(result.get("data_source"))},
        {"指标": "行情供应商", "数值": localize_data_vendor(data_vendor_raw)},
        {"指标": "最新收盘价", "数值": format_number(price_data.get("close"))},
        {"指标": "近20日涨跌幅", "数值": format_percent(price_data.get("change_20d"))},
        {"指标": "近60日涨跌幅", "数值": format_percent(price_data.get("change_60d"))},
        {"指标": "MA20 位置", "数值": localize_ma_position(price_data.get("ma20_position"))},
        {"指标": "MA60 位置", "数值": localize_ma_position(price_data.get("ma60_position"))},
        {"指标": "近60日最大回撤", "数值": format_percent(price_data.get("max_drawdown_60d"))},
        {"指标": "近60日年化波动率", "数值": format_percent(price_data.get("volatility_60d"))},
        {
            "指标": "近20日平均成交额/成交量原始值",
            "数值": format_money_like_value(price_data.get("avg_turnover_20d"), data_vendor_raw),
        },
    ]

    st.table(rows)

    with st.expander("数据质量提示", expanded=True):
        for note in build_data_quality_notes(price_data):
            st.write(f"- {note}")


def render_scorecard(result: dict):
    st.subheader("四、量化因子打分卡")

    score_breakdown = result.get("score_breakdown", {})

    rows = [
        {"因子": "趋势动量", "得分": score_breakdown.get("trend_momentum", "暂无")},
        {"因子": "流动性", "得分": score_breakdown.get("liquidity", "暂无")},
        {"因子": "基本面质量", "得分": score_breakdown.get("fundamental_quality", "暂无")},
        {"因子": "估值性价比", "得分": score_breakdown.get("valuation", "暂无")},
        {"因子": "风险控制", "得分": score_breakdown.get("risk_control", "暂无")},
        {"因子": "事件/政策", "得分": score_breakdown.get("event_policy", "暂无")},
    ]

    st.table(rows)


def render_debate(result: dict):
    st.subheader("五、多头 / 空头 / 风险官辩论")

    debate_result = result.get("debate_result", {})

    bull_case = debate_result.get("bull_case", {})
    bear_case = debate_result.get("bear_case", {})
    risk_review = debate_result.get("risk_review", {})

    if not debate_result:
        st.warning("当前未启用 DeepSeek，因此没有生成结构化辩论结果。")
        st.write("多头观点：", result.get("bull_case", "暂无"))
        st.write("空头观点：", result.get("bear_case", "暂无"))
        st.write("风险官意见：", result.get("risk_review", "暂无"))
        return

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 多头观点")
        st.write(bull_case.get("thesis", "暂无"))
        st.markdown("**主要理由**")
        for item in bull_case.get("key_arguments", []):
            st.write(f"- {item}")
        st.markdown("**潜在催化**")
        for item in bull_case.get("catalysts", []):
            st.write(f"- {item}")
        st.markdown("**失效条件**")
        for item in bull_case.get("invalidation_conditions", []):
            st.write(f"- {item}")

    with col2:
        st.markdown("### 空头观点")
        st.write(bear_case.get("thesis", "暂无"))
        st.markdown("**主要理由**")
        for item in bear_case.get("key_arguments", []):
            st.write(f"- {item}")
        st.markdown("**主要担忧**")
        for item in bear_case.get("main_concerns", []):
            st.write(f"- {item}")
        st.markdown("**失效条件**")
        for item in bear_case.get("invalidation_conditions", []):
            st.write(f"- {item}")

    with col3:
        st.markdown("### 风险官意见")
        st.write(risk_review.get("risk_summary", "暂无"))
        st.write("风险等级：", localize_risk_level(risk_review.get("risk_level")))
        st.write("是否阻断：", localize_bool(risk_review.get("blocking")))
        st.write("建议仓位：", risk_review.get("max_position", result.get("max_position", "暂无")))
        st.markdown("**风险触发条件**")
        for item in risk_review.get("risk_triggers", []):
            st.write(f"- {item}")


def render_decision_guard(result: dict):
    st.subheader("六、决策保护器")

    guard = result.get("decision_guard", {})

    if not guard:
        st.warning("当前没有 decision_guard 信息。")
        return

    rows = [
        {"项目": "是否启用", "内容": localize_bool(guard.get("enabled"))},
        {"项目": "本地评分", "内容": guard.get("score", "暂无")},
        {"项目": "本地评级", "内容": guard.get("rating", "暂无")},
        {"项目": "风险等级", "内容": localize_risk_level(guard.get("risk_level"))},
        {"项目": "模型原始建议", "内容": guard.get("llm_action", "暂无")},
        {"项目": "系统允许最高建议", "内容": guard.get("max_allowed_action", "暂无")},
        {"项目": "最终操作建议", "内容": guard.get("final_action", result.get("action", "暂无"))},
    ]

    st.table(rows)


def render_downloads(result: dict):
    st.subheader("七、报告文件")

    paths = result.get("_artifact_paths", {})

    col1, col2, col3, col4 = st.columns(4)

    if paths.get("pdf") and Path(paths["pdf"]).exists():
        with col1:
            st.download_button(
                label="下载 PDF 报告",
                data=read_file_bytes(paths["pdf"]),
                file_name=Path(paths["pdf"]).name,
                mime="application/pdf",
            )

    if paths.get("markdown") and Path(paths["markdown"]).exists():
        with col2:
            st.download_button(
                label="下载 Markdown",
                data=read_file_text(paths["markdown"]),
                file_name=Path(paths["markdown"]).name,
                mime="text/markdown",
            )

    if paths.get("json") and Path(paths["json"]).exists():
        with col3:
            st.download_button(
                label="下载 JSON",
                data=read_file_text(paths["json"]),
                file_name=Path(paths["json"]).name,
                mime="application/json",
            )

    if paths.get("html") and Path(paths["html"]).exists():
        with col4:
            st.download_button(
                label="下载 HTML",
                data=read_file_text(paths["html"]),
                file_name=Path(paths["html"]).name,
                mime="text/html",
            )

    with st.expander("预览 Markdown 报告"):
        if paths.get("markdown") and Path(paths["markdown"]).exists():
            st.markdown(read_file_text(paths["markdown"]))
        else:
            st.write("暂无 Markdown 报告。")


st.title("Dandelions 投研智能体")
st.caption("单票研究 MVP：AKShare 行情 + DeepSeek 辩论 + 决策保护器 + PDF 报告")

with st.sidebar:
    st.header("研究参数")

    symbol = st.text_input(
        "股票 / ETF 代码",
        value="600519.SH",
        help="示例：600519.SH、000001.SZ、510300.SH",
    )

    data_source = st.selectbox(
        "数据源",
        options=["qmt", "akshare", "mock"],
        index=0,
        help="生产研究优先使用 qmt；akshare 仅作为 fallback/调试；mock 用于离线测试。",
    )

    use_llm = st.checkbox(
        "启用 DeepSeek 辩论",
        value=True,
    )

    run_button = st.button("生成研究报告", type="primary")


if run_button:
    if not symbol.strip():
        st.error("请输入股票或 ETF 代码。")
    else:
        with st.spinner("正在生成研究报告，请稍候……"):
            try:
                result = run_research(
                    symbol=symbol.strip(),
                    data_source=data_source,
                    use_llm=use_llm,
                )
                st.session_state["last_result"] = result
                st.success("研究报告生成成功。")
            except Exception as exc:
                st.exception(exc)


result = st.session_state.get("last_result")

if result:
    render_summary(result)
    render_price_data(result)
    render_scorecard(result)
    render_debate(result)
    render_decision_guard(result)
    render_downloads(result)
else:
    st.info("请在左侧输入股票/ETF代码，然后点击“生成研究报告”。")
