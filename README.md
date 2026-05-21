# Dandelions Investment Agent

投研智能体 MVP：输入单只沪深京 A 股或 ETF，经过 LangGraph 双层图编排——辩论子图（8 节点多轮辩论 + Supervisor + 三标准收敛）+ 完整端到端 pipeline 图（数据加载→评分→辩论→HITL→决策保护→验证），输出量化评分、买卖建议、决策保护器说明，以及 JSON/Markdown/HTML/PDF 报告。支持 Streamlit 看板 HITL 人工审核、异步实时进度、JWT 登录认证。已构建 FastAPI 后端网关（Celery + Redis + JWT + WebSocket + 37 端点全保护）和观察池批量研究系统。

## 当前边界

- 主数据源：QMT/xtquant，本地 Windows + MiniQMT 环境优先。
- 本地参考数据：CSMAR 行业分类、EVA_Structure 股本/市值、个股日交易衍生指标快照库，用于行业同行池、股本补齐、股息率、估值倍数和历史分位 fallback。
- fallback 数据源：AKShare，主要用于 QMT 不可用、调试或本地参考库缺口补充；不作为行业分类默认 fallback。
- 离线测试数据源：mock。
- 新闻/政策/舆情增强：默认关闭；启用后以东方财富、巨潮/公告源为主，叠加新浪财经、新华网、百度新闻，以及华尔街见闻、第一财经、腾讯新闻、新浪热门、澎湃、B站、抖音、CSDN、微信读书等国内热榜舆情 fallback。GitHub/Google 等非国内源默认不启用，不建议在中国大陆环境开启。
- LLM：DeepSeek OpenAI-compatible API（deepseek-v4-flash / deepseek-v4-pro）。进入 LLM prompt 和 audit metadata 的研究数据会先做瘦身，只保留摘要字段，不传完整同行池、provider_run_log 或原始数据。
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
    research_context.py      LLM 输入瘦身白名单，避免完整同行池/原始数据进入上下文
    debate_agent.py          编排入口（委托 LangGraph）
    langgraph_orchestrator.py 双层图（辩论子图 + 完整 pipeline 图）+ HITL API
  data/                      数据层（QMT/AKShare/mock + 本地 CSMAR/EVA provider + 新闻舆情 provider + 聚合器 + 标准化 + 缓存）
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
tests/                       单元测试 + 默认跳过的 opt-in live 集成测试
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

如果需要复现当前验证环境，可改用锁定文件：

```powershell
python -m pip install -r requirements.lock
```

工程化配置文件已放在根目录：`pyproject.toml` 管理 pytest/Ruff 基础配置，`mypy.ini` 保留类型检查配置，GitHub Actions 使用 `requirements.lock` 做可复现安装和核心测试。

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

行业横截面估值会在股票估值成功后轻量接入。当前默认使用本地 CSMAR `TRD_Co.csv` 构建出的行业参考库解析行业和同行池，再读取 MiniQMT 可见缓存中的同行价格、财务表，并结合本地 EVA_Structure 股本数据计算 PE/PB/PS 行业分位。该能力只对 A 股股票启用，ETF 会跳过；如果同行价格、财务、股本或样本数不足，只会写入 `industry_valuation_warnings`、缺失原因和 `provider_run_log`，不会阻断主研究流程。

```text
INDUSTRY_CLASSIFICATION_PROVIDER=local_csmar
QMT_INDUSTRY_PROVIDER_EXPERIMENTAL=false
LOCAL_CSMAR_INDUSTRY_DB=storage/reference/csmar_industry.sqlite
LOCAL_CSMAR_INDUSTRY_LEVEL=CSMAR_ZX
LOCAL_CSMAR_INDUSTRY_MIN_PEERS=20
LOCAL_CSMAR_INDUSTRY_FALLBACK_TO_SECTION=true
QMT_INDUSTRY_LEVEL=SW1
QMT_INDUSTRY_AUTO_DOWNLOAD=false
QMT_INDUSTRY_MIN_VALID_PEERS=20
QMT_INDUSTRY_PEER_CHUNK_SIZE=80
QMT_INDUSTRY_FINANCIAL_AUTO_DOWNLOAD=false
QMT_INDUSTRY_MAX_PE=300
QMT_INDUSTRY_MAX_PB=50
QMT_INDUSTRY_MAX_PS=100
QMT_PEER_CACHE_PREFLIGHT=true
QMT_PEER_CACHE_MIN_COVERAGE=0.8
CSMAR_EVA_STRUCTURE_PROVIDER=enabled
CSMAR_EVA_STRUCTURE_DB=storage/reference/csmar_eva_structure.sqlite
CSMAR_EVA_STRUCTURE_MAX_STALE_DAYS=460
CSMAR_DAILY_DERIVED_PROVIDER=enabled
CSMAR_DAILY_DERIVED_DB=storage/reference/csmar_daily_derived_snapshots.sqlite
CSMAR_DAILY_DERIVED_MAX_STALE_DAYS=370
CSMAR_DAILY_DERIVED_VALUATION_MAX_STALE_DAYS=45
```

`INDUSTRY_CLASSIFICATION_PROVIDER=qmt` 仍保留为 legacy/experimental 入口，但默认禁用；只有同时设置 `QMT_INDUSTRY_PROVIDER_EXPERIMENTAL=true` 才会使用 QMT sector provider。推荐保持 `local_csmar`。

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

### 本地 CSMAR / EVA 参考库

行业估值相关的本地数据不要求放在仓库根目录。原始 CSMAR 文件建议放在 `data/raw/csmar/`，清洗后的 SQLite 参考库放在 `storage/reference/`：

```text
data/raw/csmar/TRD_Co.csv                         # 行业分类与同行池原始数据
data/raw/csmar/EVA_Structure.csv                  # 本地股本 / 市值原始数据
data/raw/csmar/个股日交易衍生指标*/               # CSMAR 日交易衍生指标原始数据

storage/reference/csmar_industry.sqlite
storage/reference/csmar_eva_structure.sqlite
storage/reference/csmar_daily_derived_snapshots.sqlite
```

构建脚本：

```powershell
python scripts/build_csmar_industry_reference.py
python scripts/build_csmar_eva_structure_reference.py
python scripts/build_csmar_daily_derived_snapshots.py
```

对应运行时能力：

- `LocalCSMARIndustryProvider`：从 `csmar_industry.sqlite` 解析行业和同行池。
- `LocalCSMAREVAStructureProvider`：在 QMT `TotalVolume=0` 或缺失时，优先用 `TotalShares` 补齐 `total_volume`，并用当前 close 派生市值。
- `LocalCSMARDailyDerivedProvider`：在 QMT/AKShare 缺失时，使用本地快照补充 `dividend_yield`、PE/PB/PS/PCF 当前值，并用月度快照计算 PE/PB/PS 历史分位。

所有本地 provider 都是非阻断式：SQLite 不存在、字段缺失或数据过期时会记录 warning / missing_reason，并允许 QMT、EVA、AKShare 链路继续运行。

### MiniQMT 缓存同步

已验证：完整版 QMT 的 `datadir` 同步到 MiniQMT 的 `userdata_mini\datadir` 后，MiniQMT 接口可以读取其中的 Finance 与 K 线缓存。推荐作为手工维护步骤执行，不放进主研究流程。常用增量同步命令：

```powershell
robocopy "D:\迅投QMT极速交易系统交易终端 万联证券版\datadir" "D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir" /E /XC /XN /XO /R:1 /W:1 /COPY:DAT /DCOPY:DAT /MT:8
```

同步后重启 MiniQMT，并使用预检脚本验证可读性：

```powershell
python scripts/check_qmt_finance_cache.py --symbols 600410.SH 002624.SZ 000419.SZ 600519.SH
python scripts/warm_qmt_peer_price_cache.py --symbols 600410.SH
```

### 网页新闻 / 热榜舆情增强

网页新闻和热榜舆情 provider 默认关闭，适合作为官方公告之外的事件补充源。启用后，事件引擎会把命中的新闻/热榜记录写入 `event_data`、`provider_run_log` 和 `evidence_bundle`；抓取失败或当前热榜不含公司相关内容时，不会阻断主研究流程。

```text
WEB_NEWS_ENABLED=true
WEB_NEWS_FORCE_NO_PROXY=true
WEB_NEWS_SOURCES=eastmoney,sina,xinhuanet,hotrank,baidu
WEB_NEWS_HOTRANK_SOURCES=wallstreetcn,yicai,36kr,tencent,sina_news,sina_hot,pengpai
```

当前新闻/热榜源分层：

- `eastmoney`：东方财富个股新闻，优先使用，股票相关性最高。
- `sina`、`xinhuanet`、`baidu`：新浪财经滚动新闻、新华网财经、百度新闻 RSS fallback。
- `hotrank`：华尔街见闻、第一财经、36氪、腾讯新闻、新浪热门、新浪新闻热门、澎湃等国内财经热榜补充源。B站、抖音、CSDN、微信读书等源与股票基本面/政策舆情相关性较弱，默认不启用，可通过 `WEB_NEWS_HOTRANK_SOURCES` 显式配置。

`hotrank` 源会严格按公司名/股票代码过滤；如果当前热榜没有命中标的，会返回 0 条并继续 fallback，这是预期行为。新闻抓取代码会强制直连：清理代理环境变量、设置 `NO_PROXY=*`、并让 HTTP session 忽略系统代理，避免用户开启 VPN 时影响国内新闻接口。所有请求均有总超时预算（`WEB_NEWS_MAX_SECONDS`/`WEB_NEWS_HOTRANK_MAX_SECONDS`），超时后自动跳过，不阻塞主研究流程。GitHub/Google 等非国内源默认不启用，不建议在中国大陆环境开启；如需启用可通过环境变量显式配置。


## 命令行运行

离线 smoke test，不调用 DeepSeek，不依赖 QMT/AKShare：

```powershell
python main.py --symbol 600519.SH --data-source mock --no-llm
```

CLI 默认只生成 JSON、Markdown 和 HTML，避免 Playwright/Chromium 环境问题影响 smoke test。若确认本机 Playwright 可用，可显式生成 PDF：

```powershell
python main.py --symbol 600519.SH --data-source mock --no-llm --pdf
```

CLI 默认使用顺序单资产流水线；如需运行完整 LangGraph 编排流程，可增加 `--use-graph`：

```powershell
python main.py --symbol 600519.SH --data-source mock --use-graph
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

需要本地运行 Redis（Celery 消息 broker + WebSocket Pub/Sub）。Windows 下通过 WSL2 启动：

**一键启动Redis（推荐）：**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1
```

脚本会自动拉起 WSL Ubuntu、启动 Redis、验证连通性。

**手动启动：**

```powershell
wsl -d Ubuntu -- sudo service redis-server start
```

如果本机 Docker 网络可用，也可以使用仓库内的 `docker-compose.yml` 启动 Redis：

```powershell
docker compose up -d redis
```

> **注意**：WSL2 虚拟机在所有 shell 退出后会自动关闭，Redis 也随之停止。每次电脑重启后需要用上述命令重新启动 Redis。Docker 方案在国内网络环境可能因无法访问 Docker Hub 而失败。

**验证 Redis 连通性：**

```powershell
python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379/0'); print(r.ping())"
# 应输出: True
```

安装依赖（首次）：

```powershell
pip install fastapi "uvicorn[standard]" celery redis aiosqlite croniter requests
```

### 启动

开发测试时可一键启动 Redis、FastAPI、Celery worker、Celery Beat 和 Streamlit。脚本会先在当前窗口启动并验证 Redis，然后为其余服务分别打开独立 PowerShell 窗口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dev_services.ps1
```

如需跳过定时调度，可加 `-SkipBeat`；如 Redis 已经运行，可加 `-SkipRedis`。

也可以手动分别启动：

```powershell
# 终端 1：FastAPI 服务
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：Celery worker（异步执行研究任务）
celery -A apps.api.celery_app worker --loglevel=info --concurrency=2

# 终端 3（可选）：Celery Beat（定时调度）
celery -A apps.api.celery_app beat --loglevel=info --schedule storage/runtime/celerybeat-schedule
```

启动后访问 `http://127.0.0.1:8000/docs` 查看交互式 API 文档。

### API 测试脚本

项目提供了 PowerShell 测试脚本，覆盖健康检查、登录、观察池、任务提交等核心流程：

```powershell
# 1. 先启动 Redis
powershell -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1

# 2. 启动 FastAPI（另开终端）
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 运行测试
powershell -ExecutionPolicy Bypass -File .\scripts\API_Test.ps1
```

> **注意**：测试脚本需要先启动 FastAPI 服务。健康检查返回 503 通常意味着 Redis 未启动——运行 `scripts\start_redis.ps1` 然后重启 uvicorn 即可。

### 核心端点（研究任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/research/single` | 提交异步研究任务 |
| `GET` | `/api/v1/research/{task_id}` | 查询任务进度 |
| `GET` | `/api/v1/research/{task_id}/result` | 获取研究结果 JSON |
| `GET` | `/api/v1/reports/{task_id}/{fmt}` | 下载报告（json/md/html/pdf） |
| `GET` | `/api/v1/health` | 健康检查 |

完整端点列表见 `/docs` 交互式文档，覆盖研究任务、观察池、认证和 WebSocket 相关接口。

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

生产部署安全项：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- `JWT_SECRET` 至少 32 字符，生产环境应使用上面命令生成的随机值。
- `AUTH_REVOCATION_FAIL_MODE=open|closed` 控制 Redis 撤销表异常时的行为；生产环境建议 `closed`，Redis 不可用时拒绝依赖 token 撤销状态的认证请求。
- 反向代理后启用限流真实 IP 识别时，只配置可信代理：`TRUSTED_PROXY_IPS=127.0.0.1,10.0.0.10`，并设置 `RATE_LIMIT_CLIENT_IP_HEADER=X-Forwarded-For`。不要在未受信任网络中直接信任该 header。
- `CORS_ORIGINS` 使用逗号分隔的明确来源，例如 `http://localhost:8501`，生产环境不要使用通配来源。

### 观察池与定时调度

观察池支持逐票自定义 cron 调度。Celery Beat 每 5 分钟检查到期项并派发扫描任务，同时每个工作日 15:07 触发全线收盘扫描。

```powershell
# 启动 beat（含 3 个定时任务：健康检查 + 调度检查 + 收盘扫描）
celery -A apps.api.celery_app beat --loglevel=info --schedule storage/runtime/celerybeat-schedule

# 同时启动 worker + beat（开发用）
celery -A apps.api.celery_app worker --beat --loglevel=info --concurrency=2 --schedule storage/runtime/celerybeat-schedule
```

## 测试

```powershell
# 全量默认测试；live 集成测试默认 skip
python -m pytest -q -p no:cacheprovider

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
python -m pytest tests/test_web_news_provider.py -v   # 网页新闻/热榜舆情 provider
python -m pytest tests/test_local_csmar_industry_provider.py -v        # 本地 CSMAR 行业库
python -m pytest tests/test_local_csmar_eva_structure_provider.py -v   # 本地 EVA 股本/市值
python -m pytest tests/test_local_csmar_daily_derived_provider.py -v   # CSMAR 日衍生快照 provider
python -m pytest tests/test_qmt_peer_cache_preflight.py -v             # QMT 同行缓存预检
python -m pytest tests/test_qmt_peer_price_cache_maintenance.py -v     # QMT 同行 K 线缓存维护
python -m pytest tests/test_valuation_missing_reasons.py -v            # 报告“暂无原因”披露
python -m pytest tests/test_llm_input_slimming.py -v                   # LLM 输入瘦身
```

Live 集成测试默认跳过，需要按需开启环境变量。网页新闻/热榜真实网络 smoke：

```powershell
$env:RUN_WEB_NEWS_NETWORK='1'
python -m pytest tests/integration/test_web_news_network_live.py -q -p no:cacheprovider
```

手动数据源验证脚本位于 `scripts/manual_tests/`：

```powershell
python scripts/manual_tests/test_announcement.py
python scripts/manual_tests/test_etf_code_format.py
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

每个 Agent 有专属 system prompt，可独立调用和测试。LangGraph 不可用时自动回退到顺序编排。所有进入 LLM 的 `research_result` 都会先经过 `services/agents/research_context.py` 的白名单瘦身，只保留价格、基本面、估值、行业样本摘要、少量 evidence 和事件摘要；完整同行池、`provider_run_log`、raw provider payload、内部 `_` 字段不会进入 prompt 或 audit metadata。

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

当前主数据链路是“MiniQMT 可读缓存 + 本地 CSMAR/EVA 参考库 + 网络 fallback”：

- 行情、成交额、基础证券信息优先走 `xtdata`。
- 基本面优先读取 QMT 本地财务表 `Balance`、`Income`、`CashFlow`、`PershareIndex`。
- 行业分类和同行池默认来自本地 CSMAR `TRD_Co.csv` 构建的 `csmar_industry.sqlite`，不再默认使用 QMT sector。
- 股本/市值在 QMT `TotalVolume=0` 或缺失时，优先使用本地 `EVA_Structure.csv` 构建的 `csmar_eva_structure.sqlite` 补齐，再考虑 AKShare。
- 股息率、PE/PB/PS/PCF 当前值和 PE/PB/PS 历史分位 fallback 来自 `csmar_daily_derived_snapshots.sqlite`。
- AKShare/东方财富/巨潮/网页新闻只作为缺口 fallback 或事件源使用，不覆盖更新且可信的本地数据。

QMT 财务表不会在每次启动时强制下载，因为 `xtdata.download_financial_data()` 在首次拉取时可能较慢。默认行为是只读 MiniQMT 当前服务可见的本地缓存：

```text
QMT_FINANCIAL_AUTO_DOWNLOAD=false
```

如果你希望项目自动尝试下载 QMT 财务表，可在 `.env` 中设置：

```text
QMT_FINANCIAL_AUTO_DOWNLOAD=true
```

行业横截面估值与历史估值分位是两个不同概念：

- 行业横截面估值：同一行业同行池内，使用当前 PE/PB/PS 对标的股票做行业分位。
- 历史估值分位：使用标的自身历史 PE/PB/PS 样本计算所处历史位置。

当前两条链路均已落地。报告会展示“估值概览”和“行业横截面估值”；当字段不可用时，会尽量展示结构化 `*_missing_reason`，例如股本缺失、财务字段缺失、历史样本不足、同行缓存预检不通过、CSMAR 数据过期等。

行业估值前会运行同行缓存预检，检查 `close`、`total_volume`、`net_profit_ttm`、`revenue_ttm`、`bps` 和 `peer_valuation_complete` 覆盖率。覆盖不足时不会强行输出低质量分位，而是返回 `industry_peer_cache_insufficient`、有效样本数、预检摘要和 warning。

事件/公告数据目前没有在 `xtdata` 中发现稳定的公告查询接口，因此官方事件仍以 AKShare/东方财富/巨潮公告链路为主；网页新闻与热榜舆情只作为补充证据源。若新闻/热榜接口失败、反爬或当前热榜不含标的关键词，会记录 provider 状态并继续 fallback，不会阻断主研究流程。

当前已验证的数据能力：

- `xtdata.connect()` 可连接本地 `127.0.0.1:58610` MiniQMT 服务。
- 完整版 QMT `datadir` 同步到 MiniQMT `userdata_mini\datadir` 后，`get_financial_data()` 和 `get_market_data_ex()` 可以读到更多 Finance 与 K 线缓存。
- QMT 财务表已接入读取链路；本地未下载财务表时会显式降级并给出 warning / missing_reason。
- 估值已支持 QMT 派生核心字段、本地 EVA 股本补齐、本地 CSMAR 日衍生指标 fallback 和历史分位 fallback。
- 行业估值默认使用本地 CSMAR 行业库 + QMT 同行财务/价格 + EVA 股本 fallback，并带前置预检。
- LLM 输入已经做瘦身，不会把完整同行池、provider_run_log、raw provider payload 写入 prompt 或 audit metadata。
- 公告事件暂用 AKShare/东方财富/巨潮接口；QMT 未确认有稳定公告 API。

## 常见问题

### FastAPI 健康检查返回 503

症状：`curl http://127.0.0.1:8000/api/v1/health` 返回 `"redis": {"status": "error", "detail": "Error 10061 connecting to 127.0.0.1:6379..."}`

**原因**：Redis 未运行。Celery 消息队列和 WebSocket Pub/Sub 依赖 Redis，健康检查会验证 Redis 连通性。

**解决**：
```powershell
# 1. 启动 Redis
powershell -ExecutionPolicy Bypass -File .\scripts\start_redis.ps1

# 2. 重启 FastAPI（Ctrl+C 停掉后重新启动）
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Redis 在电脑重启后无法连接

**原因**：WSL2 虚拟机在所有 shell 退出后会自动关闭，Redis 随之停止。

**解决**：每次电脑重启后运行 `scripts\start_redis.ps1` 即可。该脚本会自动拉起 WSL 并启动 Redis 服务。

### Docker 无法拉取 Redis 镜像

**原因**：国内网络环境可能无法直连 Docker Hub (`registry-1.docker.io`)。

**解决**：使用 WSL2 方案替代 Docker，在 WSL Ubuntu 中通过 `apt install redis-server` 安装。

### scripts\API_Test.ps1 测试脚本报"无法连接到 API 服务"

**原因**：`Invoke-RestMethod` 在收到 HTTP 503（而非 200）时会直接抛异常。503 通常是 Redis 未启动导致。

**解决**：先确认健康检查端点返回 200（`curl http://127.0.0.1:8000/api/v1/health`），再运行测试脚本。
