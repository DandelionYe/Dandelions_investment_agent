# Dandelions Investment Agent

投研智能体 MVP：输入单只沪深京 A 股或 ETF，经过 LangGraph 双层图编排——辩论子图（8 节点多轮辩论 + Supervisor + 三标准收敛）+ 完整端到端 pipeline 图（数据加载→评分→辩论→HITL→决策保护→验证），输出量化评分、买卖建议、决策保护器说明，以及 JSON/Markdown/HTML/PDF 报告。支持 Streamlit 看板 HITL 人工审核、异步实时进度、JWT 登录认证。已构建 FastAPI 后端网关（Celery + Redis + JWT + WebSocket + 37 端点全保护）和观察池批量研究系统。

## 当前边界

- 主数据源：QMT/xtquant，本地 Windows 环境优先。
- fallback 数据源：AKShare，只在 QMT 不可用或调试时使用。
- 离线测试数据源：mock。
- LLM：DeepSeek OpenAI-compatible API（deepseek-v4-flash / deepseek-v4-pro）。
- 编排：LangGraph 双层图 —— 辩论子图（8 节点多轮辩论 + Supervisor + HITL）+ 完整 pipeline 图（6 节点端到端：数据→评分→辩论→HITL→决策保护→验证）。
- 看板：Streamlit。
- 报告：JSON → Markdown → HTML → Playwright PDF。
- 当前不会自动下单，也不会调用 QMT 交易接口。

## 项目结构

```
services/
  agents/
    bull_analyst.py          BullAnalyst 类 — 多头分析（支持质询回应）
    bear_analyst.py          BearAnalyst 类 — 空头分析（支持质询回应）
    risk_officer.py          RiskOfficer 类 — 风险评估（支持质询回应）
    committee_secretary.py   CommitteeSecretary 类 — 投委会收敛（含辩论历史）
    supervisor.py            Supervisor 类 — LLM 辩论主持人
    debate_agent.py          编排入口（委托 LangGraph）
    langgraph_orchestrator.py 双层图（辩论子图 + 完整 pipeline 图）+ HITL API
  data/                      数据层（3 源 + 聚合器 + 标准化 + 缓存）
  research/                  研究引擎（评分 / 决策保护 / 基本面 / 估值 / 事件）
  llm/                       DeepSeek 客户端
  orchestrator/              单票研究主流程（含 HITL 启动/恢复）
  report/                    报告生成（JSON / Markdown / HTML / PDF）
  protocols/                 6 JSON Schemas + 验证
configs/                     评分权重 / 数据源 / 应用配置
apps/
  dashboard/                 Streamlit 看板（Home 引导页 + 单票研究 + 报告库 + 观察池）
    Home.py                  入口引导页（导航到各子页面）
    pages/
      1_Single_Asset_Research.py  单票研究（参数输入 + 生成 + 6 维度渲染）
      2_Report_Library.py         报告库
      3_观察池.py                  观察池管理（分组/标签/条件触发器/批量扫描）
    components/
      progress_poller.py    进度轮询组件
      login.py              登录组件（JWT token 管理 + 自动刷新）
  api/                       FastAPI 网关（Celery + Redis + JWT + WS + 37 端点全保护）
    auth/
      security.py            JWT 签发/验证 + bcrypt 密码哈希
      dependencies.py        get_current_user FastAPI Depends 依赖
    routers/
      auth.py                认证端点（4 个：login/refresh/me/register）
      watchlist.py           观察池端点（17 个：文件夹/项/标签 CRUD + 扫描）
      ws.py                  WebSocket 端点（3 个：task/batch/events + token 验证）
    schemas/
      auth.py                认证 Pydantic 模型
      watchlist.py           观察池 Pydantic 模型
    websocket/
      redis_pubsub.py        Redis Pub/Sub 客户端（async 长连接 + sync 发布）
      progress_publisher.py  进度消息发布工具（task + batch 两套）
      connection_manager.py  WebSocket 连接管理器
    task_manager/
      manager.py             TaskManager + WatchlistManager
      celery_tasks.py        研究任务 + 观察池扫描 + 8 进度发布点
      store.py               TaskStore + WatchlistStore + UserStore
tests/                       223 测试用例（10 文件）
protocols/                   6 JSON Schemas
```

## 环境准备

建议使用 Windows 原生 Python 3.11+。项目当前在 Python 3.13 环境下做过基础验证。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

如需使用 QMT 主数据源，还需要安装 `xtquant` 并启动本机 QMT mini 服务。完整步骤见 [QMT_SETUP.md](QMT_SETUP.md)。

```powershell
python -m pip install xtquant
python -c "from xtquant import xtdata; xtdata.connect(); print('qmt connected')"
```

QMT provider 默认会在读取日 K 为空时自动调用一次 `xtdata.download_history_data()`。可在 `.env` 中调整：

```text
QMT_AUTO_DOWNLOAD=true
QMT_HISTORY_DAYS=420
QMT_PERIOD=1d
QMT_DIVIDEND_TYPE=front
QMT_FINANCIAL_AUTO_DOWNLOAD=false
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```


## 命令行运行

离线 smoke test，不调用 DeepSeek，不依赖 QMT/AKShare：

```powershell
python main.py --symbol 600519.SH --data-source mock --no-llm
```

如果当前终端或沙箱环境不允许 Playwright 启动 Chromium，可跳过 PDF，只验证核心流水线：

```powershell
python main.py --symbol 600519.SH --data-source mock --no-llm --no-pdf
```

使用 QMT 主数据源。若 QMT 不可用，主流程会尝试回退 AKShare：

```powershell
python main.py --symbol 600519.SH --data-source qmt
```

成功走 QMT 时，输出 JSON 应包含：

```json
"data_source": "qmt",
"data_source_chain": ["qmt"],
"source_metadata": {
  "price_data": {
    "source": "qmt",
    "vendor": "qmt"
  }
}
```

如果看到 `"data_source_chain": ["qmt_failed", "akshare_fallback"]`，说明 QMT 未成功提供行情，项目已回退 AKShare。

显式使用 AKShare 调试：

```powershell
python main.py --symbol 600519.SH --data-source akshare --no-llm
```

报告会写入 `storage/reports/`，该目录默认不入库。

## Streamlit 看板

```powershell
streamlit run apps/dashboard/Home.py
```

页面左侧选择代码、数据源和是否启用 DeepSeek。报告库在 `pages/2_Report_Library.py`，观察池在 `pages/3_观察池.py`。

### 人工审核模式（HITL）

在侧边栏勾选「启用人工审核模式」后，多轮辩论完成后会自动暂停，展示审核面板：

1. **审阅三方输出**：展开查看 Bull/Bear/Risk 最终观点和辩论历程
2. **人工调整**：可覆盖最终操作建议（买入/分批买入/持有/观察/回避）并附审核备注
3. **确认或放弃**：「确认审核并生成报告」提交修改后生成完整报告；「放弃审核，自动通过」跳过人工干预

HITL 启动失败时自动回退到非 HITL 模式，不影响正常使用。

### 异步模式（实时进度）

在侧边栏勾选「异步模式（显示实时进度）」（默认启用）后：

1. 研究任务通过 API 异步提交，立即返回 task_id
2. 前端 1 秒间隔轮询进度，`st.progress()` 实时展示进度条和阶段文字
3. 完成后自动拉取完整结果并渲染报告

取消勾选则回退到原有的同步阻塞模式。异步模式下 HITL 暂不可用。

### 登录认证

Streamlit 看板启动时自动展示登录表单。输入 API 凭据登录后，所有 API 调用自动携带 Bearer token。Token 过期时自动调用 `/api/v1/auth/refresh` 无感刷新，无需手动重新登录。

### 观察池管理

导航到「观察池」页面（`pages/3_观察池.py`）可进行以下操作：

1. **管理文件夹和标签**：左侧栏新建/切换文件夹，按标签筛选标的
2. **添加观察标的**：输入代码 → 选文件夹 → 加标签 → 配置调度 cron 表达式
3. **批量扫描**：一键扫描启用的全部标的、当前文件夹或单个标的
4. **查看详情**：点击标的查看最近评分、评级、操作建议、调度配置和扫描历史

观察池页面支持双模式运行：FastAPI 在线时自动走 REST API；后端离线时直接访问本地 SQLite 存储。

## FastAPI 后端

除 Streamlit 看板和 CLI 外，项目还提供了 REST API 入口，支持异步任务队列和编程式集成。

### 前置依赖

需要本地运行 Redis。Windows 下可在 WSL 中启动：

```powershell
wsl -d Ubuntu -- redis-server --daemonize yes
```

或使用 Docker：

```powershell
docker run -d -p 6379:6379 redis:7-alpine
```

安装依赖（首次）：

```powershell
pip install fastapi "uvicorn[standard]" celery redis aiosqlite croniter requests
```

### 启动

```powershell
# 终端 1：FastAPI 服务
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：Celery worker（异步执行研究任务）
celery -A apps.api.celery_app worker --loglevel=info --concurrency=2

# 终端 3（可选）：Celery Beat（定时调度）
celery -A apps.api.celery_app beat --loglevel=info
```

启动后访问 `http://127.0.0.1:8000/docs` 查看交互式 API 文档。

### 核心端点（研究任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/research/single` | 提交异步研究任务 |
| `GET` | `/api/v1/research/{task_id}` | 查询任务进度 |
| `GET` | `/api/v1/research/{task_id}/result` | 获取研究结果 JSON |
| `GET` | `/api/v1/reports/{task_id}/{fmt}` | 下载报告（json/md/html/pdf） |
| `GET` | `/api/v1/health` | 健康检查 |

完整端点列表（30 个）见 `/docs` 交互式文档。研究任务（13 个）+ 观察池（17 个）。

任务提交后立即返回 `task_id`，研究在 Celery worker 中异步执行，客户端轮询进度即可。所有端点均生成 OpenAPI 文档。

### 观察池端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/watchlist/folders` | 列出所有文件夹（含标的计数） |
| `POST` | `/api/v1/watchlist/folders` | 创建文件夹 |
| `PUT` | `/api/v1/watchlist/folders/{id}` | 更新文件夹 |
| `DELETE` | `/api/v1/watchlist/folders/{id}` | 删除空文件夹 |
| `GET` | `/api/v1/watchlist/items` | 列出观察项（支持 ?folder_id=&tag_id=&enabled=） |
| `POST` | `/api/v1/watchlist/items` | 添加标的（含标签 + schedule_config） |
| `GET` | `/api/v1/watchlist/items/{id}` | 查看详情（含标签 + 扫描历史） |
| `PUT` | `/api/v1/watchlist/items/{id}` | 更新观察项 |
| `DELETE` | `/api/v1/watchlist/items/{id}` | 从观察池移除 |
| `GET` | `/api/v1/watchlist/tags` | 列出所有标签（含计数） |
| `POST` | `/api/v1/watchlist/tags` | 创建标签 |
| `PUT` | `/api/v1/watchlist/tags/{id}` | 更新标签 |
| `DELETE` | `/api/v1/watchlist/tags/{id}` | 删除标签 |
| `POST` | `/api/v1/watchlist/scan` | 触发批量扫描 |
| `GET` | `/api/v1/watchlist/scan/{batch_id}` | 查询扫描进度 |
| `GET` | `/api/v1/watchlist/results` | 查询扫描历史结果 |

### WebSocket 实时进度推送

除 REST 轮询外，API 还提供 WebSocket 端点用于实时进度推送。底层使用 Redis Pub/Sub（独立 DB#2）跨进程传递 Celery Worker 的进度事件。

| 端点 | 说明 |
|------|------|
| `ws://host:8000/ws/task/{task_id}` | 单票研究任务实时进度（先推当前状态，再增量推送） |
| `ws://host:8000/ws/batch/{batch_id}` | 观察池批量扫描实时进度 |
| `ws://host:8000/ws/events` | 全局事件流（所有任务的进度事件） |

消息格式（JSON）：
```json
{
  "type": "progress",
  "task_id": "abc123",
  "symbol": "600519.SH",
  "status": "running",
  "progress": 0.5,
  "progress_message": "执行研究中...",
  "score": null,
  "rating": null,
  "action": null,
  "error_message": null,
  "timestamp": "2026-05-06T..."
}
```

Streamlit 看板中勾选「异步模式（显示实时进度）」后，前端通过 1 秒间隔轮询 GET endpoint 实现同等的实时进度条体验。

### JWT 用户认证

所有 API 端点（除 `/api/v1/health/*` 和 `/api/v1/auth/login|refresh`）均需 Bearer Token 认证。WebSocket 端点通过 `?token=...` 查询参数验证。

| 端点 | 认证 | 说明 |
|------|------|------|
| `POST /api/v1/auth/login` | 公开 | 用户名+密码 → access_token + refresh_token |
| `POST /api/v1/auth/refresh` | 公开 | refresh_token → 新 token 对 |
| `GET /api/v1/auth/me` | 需认证 | 当前用户信息 |
| `POST /api/v1/auth/register` | 需认证 | 注册新用户 |

默认管理员：`admin` / `dandelions2026`（通过 `AUTH_ADMIN_USER` / `AUTH_ADMIN_PASS` 环境变量配置）。

```bash
# 登录获取 token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"dandelions2026"}'

# 带 token 访问 API
curl http://localhost:8000/api/v1/research/history \
  -H "Authorization: Bearer <access_token>"
```

Token 有效期：access_token 30 分钟，refresh_token 7 天。Streamlit 看板启动时自动展示登录表单，token 过期时自动无感刷新。

### 观察池与定时调度

观察池支持逐票自定义 cron 调度。Celery Beat 每 5 分钟检查到期项并派发扫描任务，同时每个工作日 15:07 触发全线收盘扫描。

```powershell
# 启动 beat（含 3 个定时任务：健康检查 + 调度检查 + 收盘扫描）
celery -A apps.api.celery_app beat --loglevel=info

# 同时启动 worker + beat（开发用）
celery -A apps.api.celery_app worker --beat --loglevel=info --concurrency=2
```

## 测试

```powershell
# 全部 223 个测试用例
python -m pytest

# 按模块运行
python -m pytest tests/test_decision_guard.py -v      # 决策保护器边界（25 用例）
python -m pytest tests/test_scoring_engine.py -v      # 评分引擎边缘值（28 用例）
python -m pytest tests/test_report_builders.py -v     # 报告生成验证（22 用例）
python -m pytest tests/test_langgraph_orchestrator.py -v  # LangGraph 多轮编排（29 用例）
python -m pytest tests/test_multi_round_debate.py -v  # 多轮辩论专用（15 用例）
python -m pytest tests/test_report_pipeline.py -v     # 端到端流程（11 用例）
python -m pytest tests/test_watchlist_store.py -v     # 观察池存储（32 用例）
python -m pytest tests/test_websocket.py -v           # WebSocket 推送（8 用例）
python -m pytest tests/test_auth.py -v                # JWT 认证（16 用例）
python -m pytest tests/test_valuation_percentile.py -v  # 估值分位（13 用例）
python -m pytest tests/test_condition_triggers.py -v  # 条件触发器（16 用例）
```

覆盖范围：决策保护器全部边界/评分引擎边缘值/报告生成降级/LangGraph 多轮辩论与 HITL/观察池 CRUD 与调度/WebSocket 消息格式与降级/JWT 认证与密码哈希/用户 CRUD/QMT-AKShare-mock 数据链路/估值事件标准化。

## Agent 架构与 LangGraph 编排

当前 Agent 系统由 5 个独立角色类 + LangGraph 多轮辩论工作流组成：

```
generate_debate_result()                     # 编排入口（向后兼容）
  └─ LangGraph StateGraph（多轮循环）
       ├── run_initial_round                # Bull/Bear/Risk 并行初始分析
       │     └── [条件边] → error_handler
       ├── supervisor_judge                 # Supervisor LLM 评估收敛/指定质询
       │     ├── 收敛 → committee_convergence
       │     └── 未收敛 → bull/bear/risk_challenge → supervisor_judge (循环)
       ├── committee_convergence            # CommitteeSecretary 收敛（含辩论历史）
       │     └── [HITL] interrupt() 暂停点
       └── assemble_result                  # 协议验证 + debate_history
```

每个 Agent 有专属 system prompt，可独立调用和测试。LangGraph 不可用时自动回退到顺序编排。

### 多轮辩论机制

- **Round 1**：Bull/Bear/Risk 并行生成初始立场（ThreadPoolExecutor）
- **Supervisor 评估**：LLM 读取三方观点 + 辩论历史，判断收敛或生成质询
- **质询循环**：Supervisor → 被质询 Agent → Supervisor（循环直到收敛或 max_rounds 上限）
- **三轮收敛标准**：立场一致(all_agree) / 无新论据(no_new_arguments) / 达上限(max_rounds_reached)
- **max_rounds 可配置**：通过 `generate_debate_result_langgraph(research_result, max_rounds=3)` 传入

### Human-in-the-Loop

低层级 API（LangGraph 编排器）：

```python
from services.agents.langgraph_orchestrator import start_hitl_debate, resume_hitl_debate

# 启动多轮辩论 → 辩论完成后在 committee_convergence 暂停
interrupted = start_hitl_debate(research_result, thread_id="task-001", max_rounds=3)
# → 返回 bull_case / bear_case / risk_review / debate_history + __interrupt__

# 人工审核后恢复（可覆盖结论）
final = resume_hitl_debate(thread_id="task-001")
# 或传入 modified_state
final = resume_hitl_debate(thread_id="task-001", modified_state={
    "action": "持有",
    "reviewer_notes": "估值偏高，暂不宜追高",
})
```

高层级 API（集成数据加载 + 评分 + HITL 辩论）：

```python
from services.orchestrator.single_asset_research import start_hitl_research, resume_hitl_research

# 一键启动：加载数据 → 评分 → HITL 辩论 → 中断
pkg = start_hitl_research("600519.SH", data_source="mock")
# → returns {"partial_result": ..., "hitl_state": ..., "thread_id": ...}

# 审核后恢复：完成 debate → decision_guard → 协议验证
result = resume_hitl_research(
    pkg["partial_result"],
    pkg["thread_id"],
    modified_state={"action": "观察"},
)
```

Streamlit 看板中可直接勾选「启用人工审核模式」走完整 GUI 流程。

### LangGraph 完整端到端 Pipeline

除了纯辩论段的 `build_debate_graph()`，项目还提供了覆盖完整研究链路的 `build_full_research_graph()`：

```
build_full_research_graph()
  ├── load_research_data        ← QMT/AKShare/Mock + aggregator.enrich
  ├── score_asset               ← 六维度评分
  ├── run_debate_subgraph       ← 调用 8 节点辩论子图
  ├── hitl_review               ← HITL 审核暂停点（可选）
  ├── apply_decision_guard      ← 决策保护器
  └── validate_and_assemble     ← 协议验证
```

错误降级路径：
- 数据加载失败 → `handle_data_error`（降级为 mock placeholder，action 强制"回避"）
- 辩论子图失败 → `handle_debate_error`（降级为 placeholder 辩论结果）

```python
from services.agents.langgraph_orchestrator import (
    run_full_research_graph,
    run_full_research_graph_hitl,
    resume_full_research_graph,
)

# 端到端（无中断）
result = run_full_research_graph("600519.SH", data_source="mock", use_llm=False)

# 端到端 + HITL（辩论后暂停）
pkg = run_full_research_graph_hitl("600519.SH", data_source="mock")
# → 审核辩论结果...
result = resume_full_research_graph(pkg["thread_id"],
    modified_state={"action": "观察"})
```

也可以通过 `run_single_asset_research(use_graph=True)` 切换。

### 决策保护器

LLM 的买卖建议受本地评分、风险等级、数据质量三重约束。即使 DeepSeek 建议"买入"，若本地评分不足或存在 placeholder/critical 事件，系统会自动降级。详见 `services/research/decision_guard.py`。

## 数据可信度

当前 QMT 是主数据源：行情、成交额、基础信息已经走 `xtdata`；基本面会优先读取 QMT 本地财务表 `Balance`、`Income`、`CashFlow`、`PershareIndex`；估值会优先使用 QMT 收盘价、股本和财务表派生总市值、PE、PB、PS。AKShare/东方财富只作为 fallback 或公告事件源使用。

QMT 财务表不会在每次启动时强制下载，因为 `xtdata.download_financial_data()` 在首次拉取时可能较慢。默认行为是只读本地已下载财务表：

```text
QMT_FINANCIAL_AUTO_DOWNLOAD=false
```

如果你希望项目自动尝试下载 QMT 财务表，可在 `.env` 中设置：

```text
QMT_FINANCIAL_AUTO_DOWNLOAD=true
```

事件/公告数据目前没有在 `xtdata` 中发现稳定的公告查询接口，因此第一版使用 AKShare/东方财富公告接口作为真实事件源；如果该接口失败，会降级为 `mock_placeholder`，并通过 `data_quality` 和 `decision_guard` 限制建议强度。

当前已验证 QMT 日 K 接入链路：

- `xtdata.connect()` 可连接本地 `127.0.0.1:58610` QMT 服务。
- `xtdata.download_history_data('600519.SH', '1d', '20250101', '')` 可下载日线。
- 项目使用 `--data-source qmt` 后会自动连接 QMT；若本地日 K 为空，会自动下载一次，然后读取 QMT 的 `close`、`volume`、`amount` 并进入评分。
- QMT 财务表已接入读取链路；本地未下载财务表时会显式降级为 placeholder。
- 估值已支持 QMT 派生核心字段；PE/PB 历史分位仍待后续实现。
- 公告事件暂用 AKShare/东方财富接口；QMT 未确认有稳定公告 API。
