"""系统设置页面 — 可视化编辑 .env 配置。

仅 admin 可访问。修改后需重启 FastAPI / Celery worker 生效。
"""

import sys
from pathlib import Path

import streamlit as st

from apps.dashboard.settings_config import read_env, resolve_project_root, write_env

PROJECT_ROOT = resolve_project_root(Path(__file__))
sys.path.append(str(PROJECT_ROOT))

from apps.dashboard.components.login import is_admin, require_login

st.set_page_config(page_title="系统设置", page_icon="⚙️", layout="wide")
require_login()

if not is_admin():
    st.error("仅管理员可访问系统设置。")
    st.stop()

st.title("⚙️ 系统设置")
st.caption("编辑 .env 配置。修改后需重启 FastAPI 和 Celery worker 生效。")

ENV_PATH = PROJECT_ROOT / ".env"

# ── 配置定义 ──────────────────────────────────────────────────

SENSITIVE_KEYS = {
    "DEEPSEEK_API_KEY", "DEEPSEEK_HTTP_PROXY", "JWT_SECRET",
    "AUTH_ADMIN_PASS", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
}

# (key, label, help_text, input_type)
# input_type: "text" | "password" | "number" | "toggle" | "select"
# options 仅对 select 有效
CONFIG_GROUPS = {
    "LLM": [
        ("DEEPSEEK_API_KEY", "DeepSeek API Key", "DeepSeek API 密钥", "password"),
        ("DEEPSEEK_BASE_URL", "API Base URL", "DeepSeek API 地址", "text"),
        ("DEEPSEEK_MODEL_FAST", "快速模型", "用于轻量任务的模型名", "text"),
        ("DEEPSEEK_MODEL_REASONING", "推理模型", "用于复杂推理的模型名", "text"),
        ("LLM_JSON_REPAIR_RETRIES", "JSON 修复重试次数", "LLM 输出 JSON 解析失败时的重试次数", "number"),
        ("DEEPSEEK_USE_PROXY", "使用代理", "DeepSeek API 是否走代理", "toggle"),
        ("DEEPSEEK_HTTP_PROXY", "代理地址", "HTTP 代理地址（如 http://127.0.0.1:7890）", "password"),
    ],
    "数据源": [
        ("DEFAULT_DATA_SOURCE", "默认数据源", "qmt / akshare / mock", "select",
         ["qmt", "akshare", "mock"]),
        ("MARKET_DATA_DISABLE_PROXY", "禁用代理", "行情数据获取时禁用代理（推荐）", "toggle"),
    ],
    "QMT": [
        ("QMT_AUTO_DOWNLOAD", "自动下载日线", "启动时自动下载 QMT 日线数据", "toggle"),
        ("QMT_HISTORY_DAYS", "历史天数", "下载的日线天数（约 6 年 = 1500）", "number"),
        ("QMT_PERIOD", "K 线周期", "1d / 1w / 1m", "select", ["1d", "1w", "1m"]),
        ("QMT_DIVIDEND_TYPE", "复权类型", "front=前复权 / back=后复权 / none=不复权",
         "select", ["front", "back", "none"]),
        ("QMT_SUPPRESS_HELLO", "抑制连接信息", "隐藏 xtdata 连接成功提示", "toggle"),
        ("QMT_PRICE_MAX_STALE_DAYS", "过期判定天数", "K 线超过此天数视为过期", "number"),
        ("QMT_STALE_REFRESH_DAYS", "刷新窗口天数", "过期时下载的较短天数", "number"),
        ("QMT_USE_FULL_TICK_FOR_STALE_PRICE", "Full Tick 覆盖", "过期时用实时行情覆盖", "toggle"),
        ("QMT_PRICE_AKSHARE_FALLBACK", "AKShare 降级", "QMT 过期时降级到 AKShare", "toggle"),
        ("QMT_FINANCIAL_AUTO_DOWNLOAD", "财务表自动下载", "自动下载 QMT 财务表（慢）", "toggle"),
    ],
    "行业分类": [
        ("INDUSTRY_CLASSIFICATION_PROVIDER", "分类提供者", "local_csmar / disabled / qmt",
         "select", ["local_csmar", "disabled", "qmt"]),
        ("QMT_INDUSTRY_LEVEL", "行业级别", "SW1=申万一级 / SW2=申万二级", "text"),
        ("QMT_INDUSTRY_AUTO_DOWNLOAD", "自动下载行业数据", "自动下载行业分类数据", "toggle"),
        ("QMT_INDUSTRY_MIN_VALID_PEERS", "最小有效同行数", "同行数量低于此值跳过估值", "number"),
        ("QMT_INDUSTRY_PEER_CHUNK_SIZE", "同行分块大小", "批量查询同行时的分块大小", "number"),
        ("QMT_INDUSTRY_MAX_PE", "PE 上限", "PE 超过此值剔除", "number"),
        ("QMT_INDUSTRY_MAX_PB", "PB 上限", "PB 超过此值剔除", "number"),
        ("QMT_INDUSTRY_MAX_PS", "PS 上限", "PS 超过此值剔除", "number"),
        ("QMT_PEER_CACHE_PREFLIGHT", "缓存预检", "运行前验证财务/价格/股本覆盖率", "toggle"),
        ("QMT_PEER_CACHE_MIN_COVERAGE", "最小覆盖率", "缓存预检的最低覆盖率阈值", "number"),
    ],
    "CSMAR": [
        ("CSMAR_DAILY_DERIVED_PROVIDER", "日线快照降级", "启用 CSMAR 日线快照降级", "toggle"),
        ("CSMAR_DAILY_DERIVED_DB", "快照数据库路径", "CSMAR 日线快照 SQLite 路径", "text"),
        ("CSMAR_DAILY_DERIVED_MAX_STALE_DAYS", "过期天数（通用）", "非估值字段的过期天数", "number"),
        ("CSMAR_DAILY_DERIVED_VALUATION_MAX_STALE_DAYS", "过期天数（估值）", "PE/PB/PS/PCF 的过期天数", "number"),
        ("CSMAR_EVA_STRUCTURE_PROVIDER", "EVA 股本降级", "启用 EVA_Structure 股本降级", "toggle"),
        ("CSMAR_EVA_STRUCTURE_DB", "EVA 数据库路径", "EVA_Structure SQLite 路径", "text"),
        ("CSMAR_EVA_STRUCTURE_MAX_STALE_DAYS", "EVA 过期天数", "EVA 数据的过期天数", "number"),
        ("LOCAL_CSMAR_INDUSTRY_DB", "行业分类数据库", "本地 CSMAR 行业分类 SQLite 路径", "text"),
        ("LOCAL_CSMAR_INDUSTRY_LEVEL", "行业分类级别", "CSMAR_ZX / CSMAR_DL 等", "text"),
        ("LOCAL_CSMAR_INDUSTRY_UNIVERSE", "市场范围", "sh_sz_bj / sh_sz 等", "text"),
        ("LOCAL_CSMAR_INDUSTRY_MIN_PEERS", "最小同行数", "行业分类最小同行数", "number"),
        ("LOCAL_CSMAR_INDUSTRY_FALLBACK_TO_SECTION", "降级到板块", "同行不足时降级到板块分类", "toggle"),
    ],
    "新闻": [
        ("WEB_NEWS_ENABLED", "启用网页新闻", "启用网页新闻/舆情数据源", "toggle"),
        ("WEB_NEWS_FORCE_NO_PROXY", "强制禁用代理", "新闻请求强制禁用代理", "toggle"),
        ("WEB_NEWS_SOURCES", "新闻源列表", "逗号分隔的新闻源（eastmoney,sina,...）", "text"),
        ("WEB_NEWS_LIMIT", "每个源返回条数", "每个新闻源返回的最大条数", "number"),
        ("WEB_NEWS_TIMEOUT_SECONDS", "单源超时（秒）", "单个新闻源的超时时间", "number"),
        ("WEB_NEWS_MAX_SECONDS", "总超时（秒）", "所有新闻源的总超时预算", "number"),
        ("WEB_NEWS_HOTRANK_MAX_SECONDS", "热搜超时（秒）", "热搜源的超时时间", "number"),
        ("WEB_NEWS_EXTRA_KEYWORDS", "额外关键词", "逗号分隔的额外搜索关键词", "text"),
    ],
    "基础设施": [
        ("CELERY_BROKER_URL", "Redis Broker URL", "Celery 消息队列地址", "password"),
        ("CELERY_RESULT_BACKEND", "Redis Backend URL", "Celery 结果存储地址", "password"),
        ("RESEARCH_CACHE_ENABLED", "启用研究缓存", "启用本地 SQLite 缓存", "toggle"),
        ("RESEARCH_CACHE_DB", "缓存数据库路径", "研究缓存 SQLite 路径", "text"),
        ("CORS_ORIGINS", "CORS 来源", "允许的跨域来源（逗号分隔）", "text"),
        ("TRUSTED_PROXY_IPS", "可信代理 IP", "反向代理 IP（逗号分隔）", "text"),
        ("RATE_LIMIT_CLIENT_IP_HEADER", "限流 IP Header", "限流使用的请求头名", "text"),
    ],
    "认证": [
        ("JWT_SECRET", "JWT 密钥", "签名密钥（≥32 字符）", "password"),
        ("JWT_ALGORITHM", "签名算法", "HS256 / HS384 / HS512",
         "select", ["HS256", "HS384", "HS512"]),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "Token 过期（分钟）", "访问令牌过期时间", "number"),
        ("REFRESH_TOKEN_EXPIRE_DAYS", "刷新 Token 过期（天）", "刷新令牌过期时间", "number"),
        ("AUTH_REVOCATION_FAIL_MODE", "吊销失败模式", "open=放行 / closed=拒绝",
         "select", ["open", "closed"]),
        ("AUTH_ADMIN_USER", "管理员用户名", "初始管理员用户名", "text"),
        ("AUTH_ADMIN_PASS", "管理员密码", "初始管理员密码", "password"),
    ],
}


# ── 渲染 ──────────────────────────────────────────────────────

env_values = read_env(ENV_PATH)

tab_names = list(CONFIG_GROUPS.keys()) + ["状态"]
tabs = st.tabs(tab_names)

for i, (group_name, fields) in enumerate(CONFIG_GROUPS.items()):
    with tabs[i]:
        st.subheader(group_name)
        changes: dict[str, str] = {}

        for field_def in fields:
            key = field_def[0]
            label = field_def[1]
            help_text = field_def[2]
            input_type = field_def[3]
            options = field_def[4] if len(field_def) > 4 else None

            current_value = env_values.get(key, "")
            is_sensitive = key in SENSITIVE_KEYS
            display_value = "****" if is_sensitive and current_value else current_value

            if input_type == "password":
                val = st.text_input(
                    label, value=display_value, type="password",
                    key=f"env_{key}", help=help_text,
                )
            elif input_type == "number":
                try:
                    num_val = int(current_value) if current_value else 0
                except ValueError:
                    num_val = 0
                val = str(st.number_input(
                    label, value=num_val, key=f"env_{key}", help=help_text,
                ))
            elif input_type == "toggle":
                bool_val = current_value.lower() in ("true", "1", "yes")
                val = str(st.checkbox(
                    label, value=bool_val, key=f"env_{key}", help=help_text,
                )).lower()
            elif input_type == "select" and options:
                idx = options.index(current_value) if current_value in options else 0
                val = st.selectbox(
                    label, options=options, index=idx,
                    key=f"env_{key}", help=help_text,
                )
            else:
                val = st.text_input(
                    label, value=display_value if is_sensitive else current_value,
                    key=f"env_{key}", help=help_text,
                    type="password" if is_sensitive else "default",
                )

            changes[key] = val

        st.divider()
        if st.button(f"💾 保存 {group_name} 配置", key=f"save_{group_name}",
                     use_container_width=True):
            write_env(ENV_PATH, changes, SENSITIVE_KEYS)
            st.success(f"✅ {group_name} 配置已保存到 .env。需重启 FastAPI 和 Celery worker 生效。")

# ── 状态 Tab ──────────────────────────────────────────────────

with tabs[-1]:
    st.subheader("服务状态")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**连接检查**")

        # Redis
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", 6379))
            s.close()
            st.success("Redis: 已连接 (127.0.0.1:6379)")
        except Exception:
            st.error("Redis: 未连接")

        # FastAPI
        try:
            import requests
            resp = requests.get("http://127.0.0.1:8000/api/v1/health/ready", timeout=2)
            if resp.status_code == 200:
                st.success("FastAPI: 运行中")
            else:
                st.warning(f"FastAPI: 响应异常 ({resp.status_code})")
        except Exception:
            st.error("FastAPI: 未连接")

        # QMT
        try:
            from xtquant import xtdata
            st.success("QMT/xtquant: 可导入")
        except Exception:
            st.warning("QMT/xtquant: 不可用（非 Windows 或未安装）")

    with col2:
        st.markdown("**存储状态**")

        # .env
        if ENV_PATH.exists():
            mtime = ENV_PATH.stat().st_mtime
            from datetime import datetime
            mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            st.info(f".env: {ENV_PATH}")
            st.caption(f"最后修改: {mtime_str}")
        else:
            st.warning(".env 文件不存在")

        # 缓存目录
        cache_dir = PROJECT_ROOT / "storage" / "cache"
        if cache_dir.exists():
            size_mb = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file()) / 1024 / 1024
            st.info(f"缓存目录: {size_mb:.1f} MB")
        else:
            st.info("缓存目录: 不存在")

        # Artifact 目录
        artifact_dir = PROJECT_ROOT / "storage" / "artifacts"
        if artifact_dir.exists():
            size_mb = sum(f.stat().st_size for f in artifact_dir.rglob("*") if f.is_file()) / 1024 / 1024
            st.info(f"Artifact 目录: {size_mb:.1f} MB")
        else:
            st.info("Artifact 目录: 不存在")
