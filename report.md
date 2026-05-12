# Dandelions 投研智能体 - v0.2.21 实现情况报告

## 0. 核验范围与口径

- **核验版本**：tag `v0.2.21`
- **对应提交**：`0075e99`
- **提交主题**：`feat: 接入 QMT 行业横截面估值分位`
- **报告口径**：本报告只评价 `v0.2.21` 版本的仓库状态，不沿用旧版 `report.md` 中已过时的百分比和进度描述。
- **当前工作区补充修正**：2026-05-12 已修正 Celery Beat schedule 使用的任务名，使其匹配 worker 实际注册名；移除 Beat 对未监听 `beat` 队列的投递；新增 `tests/test_celery_schedule.py` 防止再次漂移；新增 `tests/integration/` opt-in live 集成测试基线；新增 `docs/verification.md` 和 `docs/integration_testing.md` 记录本地验证方法；新增默认关闭的 `WebNewsProvider`，用于国内新闻/政策/舆情事件增强，并在代码层强制新闻抓取禁用代理。
- **测试口径说明**：
  - “有测试验证”指仓库内存在对应测试文件，且部分测试被 CI 定向执行；不等同于我已经在本地完整运行过全部测试。
  - “静态/手动验证”指代码、配置、页面或脚本已经存在，但缺少稳定自动化测试或缺少真实外部环境的可复现验收。
  - QMT、AKShare、Redis、Celery、Playwright、DeepSeek 等外部依赖能力，即使代码存在，也需要在真实环境中单独验收。

## 1. 总体结论

截至 `v0.2.21`，项目已经具备比较完整的投研智能体 MVP：可以围绕单只 A 股/ETF 进行数据加载、评分、Agent 辩论、决策保护和报告生成；同时仓库中已经存在 FastAPI 后端、Celery/Redis 异步任务、观察池、JWT 登录认证、WebSocket/进度推送、Streamlit 页面和测试体系。

但是，当前版本不宜再写“总体完成度约 98%”。更客观的判断是：

- **MVP 主链路已基本完成**：单票研究、评分、报告、Agent 辩论、决策保护器已经形成闭环。
- **工程化框架已较完整**：FastAPI、任务队列、观察池、认证、进度推送均已有代码实现。
- **生产级验收仍不足**：真实 QMT/AKShare 数据源、Redis/Celery/WebSocket 跨进程链路、PDF 生成、Streamlit 登录与异步模式、API 全端点联调，需要补充集成测试或手动验收记录。
- **研究能力仍有明显边界**：网页搜索、新闻/政策/舆情增强、Qlib、组合优化、历史回测、系统设置 UI 等尚未完成。

## 2. v0.2.21 的关键变化

`v0.2.21` 的核心新增点是 **QMT 行业横截面估值分位**。该版本新增或修改了：

- `.env.example`：新增 QMT 行业估值相关环境变量。
- `QMT_SETUP.md`：新增行业/板块读取与行业估值验证说明。
- `README.md`：更新项目边界和运行说明。
- `services/data/providers/qmt_industry_provider.py`：新增 QMT 行业/板块信息 provider。
- `services/data/providers/qmt_peer_valuation_loader.py`：新增同行成分股估值数据加载器。
- `services/research/industry_valuation_engine.py`：新增行业横截面估值分位计算逻辑。
- `services/research/valuation_engine.py`：接入行业估值分位。
- `services/data/aggregator/evidence_builder.py`：扩展估值证据。
- `services/report/markdown_builder.py`：报告中补充行业估值信息。
- `tests/test_industry_valuation.py`、`tests/test_report_builders.py`、`tests/test_report_pipeline.py`：补充相关测试或断言。

该功能的准确表述应为：

> 已在代码层接入 QMT 行业横截面 PE/PB/PS 分位，并有单元测试覆盖核心计算与报告输出；但真实 QMT 行业成分、同行财务表批量读取、样本数不足等生产数据场景仍需要本地 QMT 环境验收。

## 3. 四类状态总览

| 分类 | 含义 | 当前判断 |
|---|---|---|
| 已实现且有测试验证 | 有明确代码模块，并有对应测试文件或 CI 定向测试覆盖 | 单票研究主流程、评分、决策保护、报告构建、LLM JSON guard、CLI、部分估值分位、部分行业估值、部分协议/错误处理 |
| 已实现但仅静态验证/手动验证 | 代码存在，但缺少完整自动化集成测试或依赖真实外部环境 | FastAPI 运行态、Celery/Redis、WebSocket 跨进程推送、Streamlit 页面、QMT/AKShare 真实数据、PDF 生成、JWT 全链路运行 |
| 部分实现 | 有基础能力，但还没有达到完整设计目标或生产目标 | 统一数据证据结构、报告模板体系、RBAC/多用户隔离、网页新闻/政策舆情增强、条件触发器真实行情联动、文档体系 |
| 未实现 | 仓库中没有可用实现，或当前版本明确不做 | Qlib、系统设置页面、自动交易、组合优化、历史回测、生产部署体系 |

---

# 一、已实现且有测试验证

## 1.1 CLI 单票研究入口 ✅ 已完成

**状态**：已完成，有 `tests/test_cli.py`，CI 中也定向执行 `test_cli.py`。

**实际实现**：

- `main.py` 支持：
  - `--symbol`
  - `--no-llm`
  - `--data-source {qmt,akshare,mock}`
  - `--pdf`
  - `--use-graph`
- CLI 默认生成 JSON、Markdown、HTML。
- PDF 默认关闭，需要显式加 `--pdf`。
- `--use-graph` 用于切换完整 LangGraph 编排流程。

**注意**：

旧报告中写的 `--no-pdf` 是错误的。`v0.2.21` 的正确参数是 `--pdf`。

## 1.2 单票研究主流程 ✅ 已完成

**状态**：已完成，有 `tests/test_report_pipeline.py` 覆盖主流程相关场景。

**实际实现**：

- 主入口位于 `services/orchestrator/single_asset_research.py`。
- 支持顺序流水线和完整 LangGraph pipeline 两种运行方式。
- 输出研究结果后，调用 report builder 保存 JSON、Markdown、HTML，必要时保存 PDF。
- 支持 `mock` 离线数据源，用于 smoke test 和 CI 场景。

**边界**：

- 对 QMT、AKShare 的真实数据可用性不能仅凭 mock 测试确认。
- DeepSeek 真实调用需要 API Key 和网络环境，测试中主要以 mock 或 JSON guard 的方式验证。

## 1.3 评分引擎 ✅ 已完成

**状态**：已完成，有 `tests/test_scoring_engine.py`。

**实际实现**：

- `services/research/scoring_engine.py` 提供评分逻辑。
- 评分维度包括趋势动量、流动性、基本面质量、估值性价比、风险控制、事件/政策。
- 支持股票和 ETF 的不同评分路径。
- 测试覆盖边界值、异常数据、placeholder 数据上限、正负事件影响等场景。

**边界**：

- 评分权重和阈值目前是规则体系，不是回测校准后的统计模型。
- 行业分位加入后，估值分数解释性增强，但仍需要实盘样本验证有效性。

## 1.4 决策保护器 ✅ 已完成

**状态**：已完成，有 `tests/test_decision_guard.py`。

**实际实现**：

- `services/research/decision_guard.py` 用于限制 LLM 或投委会建议的激进程度。
- 约束来源包括：
  - 本地评分阈值；
  - 风险等级；
  - 数据质量；
  - placeholder 数据；
  - critical 事件；
  - 缺失 fundamental/valuation 数据。
- 能记录降级原因，并在报告中展示。

**结论**：

这是当前项目中比较成熟的风险约束模块，建议后续继续作为所有 Agent 建议的最终保护层。

## 1.5 报告构建模块 ✅ 已完成

**状态**：已完成，有 `tests/test_report_builders.py`。

**实际实现**：

- `services/report/json_builder.py`
- `services/report/markdown_builder.py`
- `services/report/html_builder.py`
- `services/report/pdf_builder.py`
- `services/report/pdf_builder_playwright.py`

当前支持 JSON、Markdown、HTML、PDF 四类输出。Markdown 报告包含基本信息、投委会结论、数据来源、评分卡、多空观点、风险官意见、决策保护器说明、辩论收敛纪要、后续跟踪建议和免责声明。

**边界**：

- PDF 生成依赖 Playwright/Chromium 或 WeasyPrint，真实运行需要本地依赖完整。
- 报告样式仍以 Markdown + CSS 为主，不是完整的 Jinja2 模板体系。

## 1.6 LLM JSON 输出防护 ✅ 已完成

**状态**：已完成，有 `tests/test_llm_json_guard.py`，CI 定向执行。

**实际实现**：

- `services/llm/json_guard.py` 提供 JSON 提取、校验、重试或 fallback 相关逻辑。
- Agent 调用中增加 JSON 输出稳定性控制。
- Agent 输出包含一定审计 metadata，例如 prompt 版本、prompt hash、input snapshot 等。

**边界**：

- 该模块能降低 LLM 输出格式错误风险，但不能保证 LLM 内容本身完全准确。
- 对 DeepSeek 真实 API 的异常、限速、网络错误仍需要端到端测试补充。

## 1.7 Agent 拆分与多轮辩论 ✅ 已完成

**状态**：已完成，有 `tests/test_langgraph_orchestrator.py` 和 `tests/test_multi_round_debate.py`。

**实际实现**：

Agent 文件包括：

- `services/agents/bull_analyst.py`
- `services/agents/bear_analyst.py`
- `services/agents/risk_officer.py`
- `services/agents/committee_secretary.py`
- `services/agents/supervisor.py`
- `services/agents/debate_agent.py`
- `services/agents/langgraph_orchestrator.py`

`langgraph_orchestrator.py` 中实现了辩论子图和完整 pipeline 图：

- 辩论子图：初始三方分析、Supervisor 判断、按 next speaker 质询、投委会收敛、结果组装、错误处理。
- 完整 pipeline 图：数据加载、评分、辩论子图、HITL 审核、决策保护器、协议验证与组装。

**修正旧报告错误**：

旧报告中“多头/空头/风险官辩论已完成但未使用 LangGraph 编织”的说法已经不符合 `v0.2.21`。当前版本已经有 LangGraph 编排，是否启用完整 pipeline 取决于 CLI 或调用参数中的 `use_graph`。

## 1.8 协议 Schema 与验证 ✅ 已完成

**状态**：已完成，有协议文件和相关流程测试。

**实际实现**：

`protocols/` 下包含：

- `research_task.schema.json`
- `factor_score.schema.json`
- `debate_result.schema.json`
- `final_decision.schema.json`
- `data_quality.schema.json`
- `evidence_bundle.schema.json`

**边界**：

- 目前 schema 能约束结构，但不能完全约束金融含义、数据时点一致性和外部数据质量。
- 后续应把 schema 验证结果纳入 API 响应和报告审计部分。

## 1.9 估值分位与行业横截面估值 ✅ 已完成，但真实数据需验收

**状态**：核心计算已完成，有 `tests/test_valuation_percentile.py` 和 `tests/test_industry_valuation.py`。

**实际实现**：

- `services/research/valuation_engine.py` 负责估值服务。
- `services/research/industry_valuation_engine.py` 负责行业横截面分位计算。
- `services/data/providers/qmt_industry_provider.py` 和 `qmt_peer_valuation_loader.py` 接入 QMT 行业成分和同行估值数据。
- 报告层已经展示行业估值信息。
- `.env.example` 增加了 QMT 行业估值配置。

**边界**：

- 单元测试能够验证核心计算逻辑，但不能替代真实 QMT 终端环境测试。
- 行业成分解析、同行财务表可用性、样本数不足、极端估值过滤等场景，需要本地 QMT 验收并记录结果。
- ETF 会跳过行业估值，该行为是合理边界，不是缺陷。

## 1.10 安全配置与认证基础逻辑 ✅ 已完成

**状态**：基础逻辑有测试，相关测试包括 `tests/test_auth.py` 和 `tests/test_security_config.py`；CI 定向执行 `test_security_config.py`。

**实际实现**：

- `apps/api/auth/security.py`：JWT 签发/验证、bcrypt 密码哈希。
- `apps/api/auth/dependencies.py`：FastAPI Depends 鉴权依赖。
- `apps/api/routers/auth.py`：登录、刷新、当前用户、注册接口。
- `apps/api/task_manager/store.py`：包含 UserStore 和 users 表相关逻辑。
- Streamlit 中有 `apps/dashboard/components/login.py`。

**边界**：

- 已经有 JWT 认证，不等于完整 RBAC。
- 当前主要是“登录后可访问”的保护，不应夸大为严格多租户权限体系。
- register 端点需要已登录用户，这属于基础管控，但仍需明确管理员权限边界。

---

# 二、已实现但仅静态验证/手动验证

## 2.1 FastAPI 后端网关 ✅ 已实现，需运行态验收

**状态**：已实现，但整体运行态需要启动服务后验收。

**实际实现**：

- `apps/api/main.py` 创建 FastAPI 应用。
- 注册 router：
  - `auth`
  - `health`
  - `reports`
  - `research`
  - `watchlist`
  - `ws`
- 存在全局异常处理和 lifespan 管理。
- `apps/api/routers/research.py` 提供异步研究任务接口。
- `apps/api/routers/reports.py` 提供报告查询/下载接口。
- `apps/api/routers/health.py` 提供健康检查接口。

**边界**：

- CI 没有完整启动 FastAPI 服务并跑全量 HTTP 集成测试。
- `tests/integration/test_fastapi_research_live.py` 已覆盖 health、鉴权边界、mock 任务提交、结果查询和报告信息查询，但默认 skip，需要 `RUN_LIVE_INTEGRATION=1`。
- `/redoc`、更多异常路径、并发任务和取消任务仍需继续补充。
- 旧报告中“缺少 FastAPI Gateway”的说法应删除。

## 2.2 Celery + Redis 异步任务 ✅ 已实现，需跨进程验收

**状态**：代码已实现，真实任务队列运行需要 Redis、Celery worker 和 API 同时启动。

**实际实现**：

- `apps/api/celery_app.py`
- `apps/api/task_manager/celery_tasks.py`
- `apps/api/task_manager/manager.py`
- `apps/api/task_manager/store.py`

支持研究任务提交、状态持久化、进度更新、观察池扫描任务和 Celery Beat 调度配置。2026-05-12 已修正 Beat schedule 的任务名，使 `daily-health-check`、`watchlist-scheduler-check`、`watchlist-scan-weekday-close` 分别指向 worker 实际注册的 `beat.daily_health_check`、`beat.watchlist_scheduler_check`、`beat.watchlist_scan`；同时移除 Beat schedule 对 `beat` 队列的投递，避免一键启动的默认 worker 只监听 `celery` 队列时无人消费。

**边界**：

- 单元测试不能充分验证跨进程消息队列。
- Beat 任务名和默认队列已有 `tests/test_celery_schedule.py` 覆盖；`tests/integration/test_celery_redis_live.py` 已覆盖 Redis 可达、worker 注册任务、active queue 和 health-check task roundtrip。
- 真实 Beat 按时间触发、观察池定时扫描和异常重试仍需继续记录执行结果。
- 需要补充：
  - Redis 不可用时降级行为；
  - Celery worker 超时行为；
  - 任务取消行为；
  - 多任务并发；
  - DeepSeek 限速或异常时的状态流转。

## 2.3 WebSocket / 进度推送 ✅ 已实现，需运行态验收

**状态**：模块和测试存在，并已新增 opt-in live WebSocket 任务进度测试；Streamlit 前端仍以轮询为主。

**实际实现**：

- `apps/api/routers/ws.py`
- `apps/api/websocket/redis_pubsub.py`
- `apps/api/websocket/progress_publisher.py`
- `apps/api/websocket/connection_manager.py`
- `tests/test_websocket.py`

**边界**：

- 后端 WebSocket 端点存在。
- Streamlit 侧主要采用短间隔 HTTP 轮询展示进度，而不是原生 WebSocket 前端连接。
- `tests/integration/test_websocket_progress_live.py` 已覆盖“任务提交 → WebSocket 订阅 → completed 终态消息”。
- Streamlit 页面仍主要采用短间隔 HTTP 轮询展示进度，前端原生 WebSocket 展示不属于当前已验收范围。

## 2.4 Streamlit 看板 ✅ 已实现，需 UI 手动验收

**状态**：页面文件存在，功能需要运行 `streamlit` 后手动验收。

**实际实现**：

- `apps/dashboard/Home.py`
- `apps/dashboard/pages/1_Single_Asset_Research.py`
- `apps/dashboard/pages/2_Report_Library.py`
- `apps/dashboard/pages/3_观察池.py`
- `apps/dashboard/components/login.py`
- `apps/dashboard/components/progress_poller.py`

支持单票研究、报告库、观察池、登录和进度展示。

**边界**：

- 当前没有稳定的 UI 自动化测试。
- HITL 页面、异步模式、登录刷新、API 离线 fallback 等需要手动验收记录。
- 不存在 `4_系统设置.py`。

## 2.5 QMT 主数据源 ✅ 已实现，需本地 QMT 验收

**状态**：provider 和配置已实现；已新增 opt-in QMT 本地 smoke test，但完整行业同行估值仍需更多本地样本验收。

**实际实现**：

- `services/data/qmt_provider.py`
- `services/data/providers/qmt_financial_provider.py`
- `services/data/qmt_realtime_quote.py`
- `services/data/providers/qmt_industry_provider.py`
- `services/data/providers/qmt_peer_valuation_loader.py`
- `QMT_SETUP.md`

**边界**：

- `tests/integration/test_qmt_local_live.py` 已覆盖 XtMiniQMT 打开时的最小本地连接、价格数据、行数和 provider run log。
- 历史数据下载、财务表批量读取、行业成分读取、实时行情读取和行业同行估值有效样本，仍需要本地环境继续验收。
- 如果 QMT 环境不可用，系统应 fallback 至 AKShare 或 mock；该 fallback 行为也需要实际验证。

## 2.6 AKShare / 巨潮资讯数据源 ✅ 已实现，需网络集成测试

**状态**：provider 代码存在；已新增 opt-in AKShare 网络 smoke test，但真实网络稳定性仍需按需运行记录。

**实际实现**：

- `services/data/akshare_provider.py`
- `services/data/providers/akshare_fundamental_provider.py`
- `services/data/providers/akshare_valuation_provider.py`
- `services/data/providers/akshare_event_provider.py`
- `services/data/providers/cninfo_event_provider.py`
- `services/data/providers/etf_provider.py`

**边界**：

- `tests/integration/test_akshare_network_live.py` 已提供默认 skip 的网络 smoke test，需要 `RUN_AKSHARE_NETWORK=1` 才执行。
- AKShare 接口字段、数据源可用性、网络代理、限流、空结果等问题，仍需要在可联网环境定期记录。
- 巨潮资讯/东方财富公告接口变化会影响事件数据稳定性。

## 2.7 PDF 生成 ✅ 已实现，需本地依赖验收

**状态**：代码已实现，但真实生成依赖 Playwright/Chromium 或 WeasyPrint 环境。

**实际实现**：

- `services/report/pdf_builder_playwright.py`
- `services/report/pdf_builder.py`

**边界**：

- CLI 默认不生成 PDF，目的是避免 Chromium 环境问题影响 smoke test。
- 报告中应写“PDF 能力已实现，但运行环境需单独安装并验证”，不应写成无条件完成。

## 2.8 Docker / Redis 启动脚本 ✅ 已实现，需运行验证

**状态**：配置存在，但未确认跨平台稳定性。

**实际实现**：

- `docker-compose.yml`
- `scripts/start_redis.ps1`
- `scripts/API_Test.ps1`

**边界**：

- Windows + WSL2、Docker Desktop、国内网络环境下的可用性不同。
- 应在文档中明确推荐 WSL2 Redis，并记录每次重启后的启动步骤。

---

# 三、部分实现

## 3.1 数据证据结构和质量追踪 ⚠️ 部分实现

**状态**：部分实现。

**已有能力**：

- `source_metadata`
- `data_quality`
- `evidence_bundle`
- `provider_run_log`
- provider contract 与错误类型
- SQLite cache / normalized snapshot 的基础能力

**未完全达到的目标**：

还没有把所有数据层输出统一重构为严格的：

```json
{
  "value": "...",
  "source": "...",
  "as_of": "...",
  "quality": "...",
  "warnings": []
}
```

**结论**：

当前证据能力已经足够支撑报告和决策保护器，但尚未完成全链路统一数据包装。这个方向会牵涉 provider、scoring、report、cache 多处协议变化，不适合作为小修。

## 3.2 报告模板体系 ⚠️ 部分实现

**状态**：部分实现。

**已有能力**：

- JSON、Markdown、HTML、PDF 输出完整。
- `services/report/templates` 目录存在。
- Markdown + CSS 已经能生成可读报告。

**未完全达到的目标**：

- 还不是完整 Jinja2 模板驱动的报告体系。
- 专业 PDF 版式、图表、分页控制、页眉页脚、模板版本管理仍不足。

**结论**：

当前报告系统满足 MVP，但不应写成“专业模板体系已完成”。

## 3.3 观察池条件触发器 ⚠️ 部分实现

**状态**：观察池 CRUD 和批量扫描较完整；条件触发器真实行情联动仍需验收。

**已有能力**：

- `apps/api/routers/watchlist.py`
- `apps/api/task_manager/manager.py`
- `apps/api/task_manager/store.py`
- `apps/dashboard/pages/3_观察池.py`
- `tests/test_watchlist_store.py`
- `tests/test_condition_triggers.py`

**未完全达到的目标**：

- 条件触发器需要真实行情源验证。
- 实时行情优先、日线 fallback、价格/成交量异动触发，在生产场景中需要更多样本测试。

## 3.4 认证与授权 ⚠️ 部分实现

**状态**：JWT 登录认证已实现；细粒度授权仍不足。

**已有能力**：

- JWT access/refresh token。
- bcrypt 密码哈希。
- REST/WS 端点鉴权。
- Streamlit 登录表单与 token 刷新。
- users 表和 UserStore。

**未完全达到的目标**：

- 不是完整 RBAC。
- 不确定是否已经按用户隔离任务、报告、观察池数据。
- 管理员权限、普通用户权限、注册权限的边界需要更严格定义和测试。

## 3.5 文档体系 ⚠️ 部分实现

**状态**：部分实现。

**已有文档**：

- `README.md`
- `QMT_SETUP.md`
- `.env.example`
- `report.md`
- 部分脚本说明

**缺少文档**：

- `docs/architecture.md`
- `docs/agent_protocol.md`
- `docs/data_schema.md`
- `docs/api.md`
- `docs/verification.md`
- `docs/qmt_industry_valuation.md`
- `docs/deployment.md`

**结论**：

README 已经包含较多使用说明，但还不能替代正式架构文档和验证文档。

## 3.6 CI / 自动化测试体系 ⚠️ 部分实现

**状态**：部分实现。

**已有能力**：

- `.github/workflows/ci.yml`
- Windows runner
- Python 3.13
- `requirements.lock`
- 定向 py_compile
- 定向 pytest
- opt-in live integration 测试目录 `tests/integration/`

**当前 CI 定向测试包括**：

- `tests/test_cli.py`
- `tests/test_llm_json_guard.py`
- `tests/test_security_config.py`
- `tests/test_celery_schedule.py`
- `tests/test_provider_errors.py`
- `tests/test_report_pipeline.py`
- `tests/test_valuation_percentile.py`
- `tests/test_scoring_engine.py`

**未完全达到的目标**：

- CI 当前没有跑全量测试文件。
- live 集成测试已存在，但默认 skip，尚未纳入 CI 服务矩阵。
- FastAPI/Celery/Redis/WebSocket 已有本地 live smoke，仍缺并发、取消、失败恢复和 Beat 定时触发覆盖。
- QMT/AKShare 已有 opt-in smoke，仍缺真实数据质量和多标的样本覆盖。
- 没有 Streamlit UI 测试。
- 没有 Playwright PDF 生成测试。

**结论**：

CI 已经具备基础保护，但不能作为全项目生产可用的证明。

---

# 四、未实现

## 4.1 网页搜索 / 新闻政策舆情服务 ⚠️ 基础实现

**状态**：已具备第一版基础能力，但默认关闭，仍需真实网络环境验收和更多来源扩展。

**当前情况**：

- 事件数据仍以 AKShare、巨潮资讯、东方财富公告等公告源为主。
- 已新增 `services/data/providers/web_news_provider.py`，第一版使用百度新闻 RSS 作为国内新闻增强源。
- `EventService` 会把官方公告和 `web_news` 事件合并、去重，并写入 `event_data`、`provider_run_log` 和 `evidence_bundle`。
- 新闻抓取默认关闭，需要 `WEB_NEWS_ENABLED=true` 才启用。
- 新闻抓取代码层强制禁用代理：清理常见代理环境变量，设置 `NO_PROXY=*`，并让 `requests.Session.trust_env=False`，避免用户开启 VPN 时影响国内新闻接口。

**影响**：

- 风险官和事件引擎已经可以消费公告以外的新闻事件，但第一版来源单一，不能视为完整舆情系统。
- 对政策、舆情、突发新闻敏感的标的，仍需增加多来源验证、时间过滤、去重质量和真实网络运行记录。

**建议优先级**：高。下一步应先验收真实网络抓取质量，再扩展更多国内新闻/政策来源。

## 4.2 Qlib 框架 ❌ 未完成

**状态**：未实现。

**当前情况**：

- 仓库没有接入 Qlib。
- 当前研究引擎是轻量规则引擎，不是 Qlib 因子研究/组合优化框架。

**建议优先级**：中低。只有在基础数据验证、网页信息增强和回测需求明确后再做。

## 4.3 系统设置页面 ❌ 未完成

**状态**：未实现。

**当前情况**：

- Dashboard 页面包括 Home、单票研究、报告库、观察池。
- 不存在 `4_系统设置.py`。
- API Key、数据源、代理、JWT、Redis、QMT 配置仍通过 `.env` 和配置文件管理。

**建议优先级**：中。适合在后端配置管理稳定后做。

## 4.4 自动交易 / QMT 下单 ❌ 未完成

**状态**：未实现，且当前版本明确不应实现自动下单。

**当前情况**：

- 当前系统只输出研究建议，不调用 QMT 交易接口。
- 没有委托下单、撤单、持仓同步、风控拦截、交易审计等模块。

**建议优先级**：低。除非先完成更严格风控、权限、审计和人工确认流程，否则不建议推进。

## 4.5 历史回测、行业估值回测、极端行情测试 ❌ 未完成

**状态**：未实现。

**当前情况**：

- 有评分规则和估值分位，但没有系统性回测。
- 没有行业估值分位对未来收益/回撤的有效性验证。
- 没有极端行情压力测试。

**建议优先级**：中。建议在数据源稳定后推进。

## 4.6 组合优化 / 多标的资产配置 ❌ 未完成

**状态**：未实现。

**当前情况**：

- 当前核心对象是单票 A 股或 ETF。
- 观察池支持批量扫描，但不是组合优化器。
- 没有组合层面的仓位、相关性、行业暴露、风险预算约束。

**建议优先级**：中低。应在单票研究质量稳定后再推进。

## 4.7 生产部署体系 ❌ 未完成

**状态**：未完成。

**当前情况**：

- 有 Docker Compose，但没有完整生产部署方案。
- SQLite 仍是本地持久化方案。
- 没有 PostgreSQL、对象存储、日志采集、监控告警、备份恢复、K8s deployment 等生产配置。

**建议优先级**：中。若只是个人本地投研工具，可暂缓；若要多人使用，应尽快规划。

---

# 五、模块级完成状态表

| 模块 | 完成状态 | 分类 | 说明 |
|---|---:|---|---|
| CLI 单票研究 | ✅ 已完成 | 已实现且有测试验证 | 参数应写 `--pdf`，不是 `--no-pdf` |
| 单票研究主流程 | ✅ 已完成 | 已实现且有测试验证 | 支持顺序和 LangGraph pipeline |
| Mock 数据源 | ✅ 已完成 | 已实现且有测试验证 | 可用于离线 smoke test |
| QMT 行情/财务/行业估值 | ✅ 已实现 | 静态/手动验证 + opt-in smoke | QMT 最小本地 smoke 已有，行业同行估值仍需验收 |
| AKShare / CNInfo 数据 | ✅ 已实现 | 静态/手动验证 + opt-in smoke | 网络 smoke 已有，稳定性仍需记录 |
| ETF 数据路径 | ✅ 已实现 | 已实现且有测试验证/部分手动 | ETF 行业估值跳过是合理边界 |
| 评分引擎 | ✅ 已完成 | 已实现且有测试验证 | 六维评分规则已实现 |
| 估值引擎 | ✅ 已完成 | 已实现且有测试验证 | v0.2.21 新增行业横截面分位 |
| 事件引擎 | ✅ 已实现 | 静态/手动验证 | 依赖公告/新闻数据源稳定性 |
| 风险引擎 | ✅ 已实现 | 已实现且有测试验证 | 与决策保护器配合 |
| 决策保护器 | ✅ 已完成 | 已实现且有测试验证 | 较成熟 |
| Agent 拆分 | ✅ 已完成 | 已实现且有测试验证 | Bull/Bear/Risk/Secretary/Supervisor |
| LangGraph 辩论子图 | ✅ 已完成 | 已实现且有测试验证 | 有多轮质询与收敛逻辑 |
| LangGraph 完整 pipeline | ✅ 已完成 | 已实现且有测试验证/静态验证 | 运行态仍需更多 e2e |
| HITL API | ✅ 已实现 | 静态/手动验证 | UI 流程需验收 |
| DeepSeek client | ✅ 已实现 | 静态/手动验证 | 真实 API 调用需环境验证 |
| LLM JSON guard | ✅ 已完成 | 已实现且有测试验证 | CI 覆盖 |
| JSON/Markdown/HTML 报告 | ✅ 已完成 | 已实现且有测试验证 | 可作为 MVP 输出 |
| PDF 报告 | ✅ 已实现 | 静态/手动验证 | 依赖 Playwright/Chromium |
| FastAPI 后端 | ✅ 已实现 | opt-in live 验证 | 已有 live smoke，缺 CI 服务矩阵 |
| Celery/Redis | ✅ 已实现 | opt-in live 验证 | Beat 任务名和队列已加测试，仍缺定时触发验收 |
| WebSocket 端点 | ✅ 已实现 | opt-in live 验证 | 后端 WS live smoke 已有，前端主要轮询 |
| JWT 认证 | ✅ 已实现 | 部分完成 | 基础认证完成，RBAC/隔离不足 |
| 观察池 CRUD | ✅ 已实现 | 已实现且有测试验证 | Store 层测试存在 |
| 观察池批量扫描 | ✅ 已实现 | 静态/手动验证 | Celery 运行态需验收 |
| 条件触发器 | ⚠️ 部分实现 | 部分实现 | 真实行情联动需测试 |
| 系统设置页面 | ❌ 未完成 | 未实现 | 不存在页面 |
| 网页搜索服务 | ⚠️ 基础实现 | 部分实现 | 默认关闭的国内新闻增强源已接入，真实网络质量仍需验收 |
| Qlib | ❌ 未完成 | 未实现 | 暂无接入 |
| 自动交易 | ❌ 未完成 | 未实现 | 当前版本不下单 |
| 回测/压力测试 | ❌ 未完成 | 未实现 | 规则有效性未验证 |
| 生产部署 | ❌ 未完成 | 未实现 | 仍偏本地工具形态 |

---

# 六、对旧版 report.md 的主要修正

旧版 `report.md` 不建议继续直接使用，主要问题包括：

1. **FastAPI 状态前后矛盾**  
   旧报告既写 FastAPI 已完成，又在架构对比处写“缺少 FastAPI Gateway”。`v0.2.21` 中 FastAPI 代码实际存在，应统一改为“已实现，但需运行态集成验收”。

2. **测试数量不统一**  
   旧报告中同时出现 138、223 等不同测试数量说法。更负责任的写法是列出测试文件，并说明“未在本报告中重新执行 pytest，准确数量以 `pytest --collect-only -q` 输出为准”。

3. **CLI 参数错误**  
   旧报告写 `--no-pdf`，实际是 `--pdf`。CLI 默认不生成 PDF，显式 `--pdf` 才生成 PDF。

4. **LangGraph 表述过时**  
   旧报告写“辩论已完成但未使用 LangGraph 编织”，这与当前 `langgraph_orchestrator.py` 不一致。应改为“LangGraph 辩论子图和完整 pipeline 图已存在，是否启用取决于调用参数”。

5. **v0.2.21 最新变化未突出**  
   旧报告没有把 QMT 行业横截面估值分位作为核心更新。新版报告应单独说明该功能的实现范围、测试范围和真实数据边界。

6. **“完成度 98%”不够审慎**  
   项目功能很多，但还有真实数据源、集成测试、网页搜索、系统设置、Qlib、回测、生产部署等明显缺口。建议用四类状态替代单一百分比。

---

# 七、下一步开发建议

## 7.1 最高优先级：建立验证基线

已新增 `docs/verification.md` 作为初始验证基线。后续应持续追加以下命令的实际输出：

```bash
python -m pytest --collect-only -q
python -m pytest -q -p no:cacheprovider
python main.py --help
python main.py --symbol 600519.SH --data-source mock --no-llm
python main.py --symbol 600519.SH --data-source mock --no-llm --use-graph
```

如果本地 Playwright 可用，再追加：

```bash
python main.py --symbol 600519.SH --data-source mock --no-llm --pdf
```

## 7.2 第二优先级：扩展运行态集成测试

已新增 `tests/integration/` 初始基线。后续建议继续扩展以下测试分层：

- FastAPI：任务取消、失败任务、分页历史、报告下载内容校验。
- Celery/Redis：多任务并发、worker 超时、Redis 不可用降级、Beat 定时触发。
- WebSocket：任务运行中进度序列、断线重连、batch 频道。
- Streamlit：手动 checklist 或轻量页面 smoke。
- QMT：多标的、本地下载、行业同行估值有效样本。
- AKShare：网络代理、空结果、字段漂移和公告 fallback。

## 7.3 第三优先级：扩展网页搜索服务

当前已经具备第一版网页搜索/新闻政策舆情补充源，后续应继续沿现有链路扩展，而不是另起一套研究流程：

```text
WebSearchProvider
  -> News/Event Normalizer
  -> EvidenceBuilder
  -> EventEngine
  -> RiskOfficer
  -> DecisionGuard
  -> Report
```

已完成第一版基础能力：

- 输入 symbol / company name / industry keywords；
- 输出新闻标题、来源、发布时间、摘要、链接、情绪、风险等级；
- 写入 `evidence_bundle` 和 `provider_run_log`；
- 风险官和报告引用该证据；
- 所有搜索结果必须带来源和时间戳；
- 搜索失败不能阻断主流程。
- 新闻抓取强制禁用代理，避免 VPN 影响国内接口。

## 7.4 第四优先级：修正文档和 README

建议把 README、QMT_SETUP、report.md、未来 docs/ 中的状态统一，尤其避免以下说法：

- 不再写“无 FastAPI”。
- 不再写 `--no-pdf`。
- 不再写未经验证的测试总数。
- 不再写“未使用 LangGraph 编织”。
- 不再写“总体完成度 98%”。

---

# 八、当前版本最终判断

`v0.2.21` 是一个功能较丰富的本地投研智能体版本，已经具备 MVP 主链路和较完整的工程化外壳。最核心的已完成部分是：

- 单票研究闭环；
- 评分与决策保护；
- Agent 多轮辩论；
- JSON/Markdown/HTML/PDF 报告；
- QMT/AKShare/mock 数据源框架；
- QMT 行业横截面估值分位；
- FastAPI + Celery + Redis + JWT + 观察池 + 进度推送的工程框架。

但当前版本仍应谨慎标注为：

> **核心功能已基本实现，工程化框架已搭建，真实数据源和运行态集成验证仍需补齐。**

下一步最适合推进的不是继续堆大型功能，而是：

1. 持续维护 `docs/verification.md` 和 `docs/integration_testing.md`；
2. 扩展 FastAPI/Celery/Redis/WebSocket/QMT/AKShare 集成测试的异常和并发场景；
3. 将新增关键测试纳入 CI 定向测试或规划服务矩阵；
4. 然后开发网页搜索/新闻政策舆情服务。
