# Dandelions Investment Agent

投研智能体 MVP：输入单只沪深京 A 股或 ETF，经过 LangGraph 多轮辩论编排——LLM 驱动的 Supervisor 调度 BullAnalyst / BearAnalyst / RiskOfficer / CommitteeSecretary 五角色辩论（支持 Agent 间质询循环 + 三标准收敛），输出量化评分、买卖建议、决策保护器说明，以及 JSON/Markdown/HTML/PDF 报告。支持 human-in-the-loop 人工审核。

## 当前边界

- 主数据源：QMT/xtquant，本地 Windows 环境优先。
- fallback 数据源：AKShare，只在 QMT 不可用或调试时使用。
- 离线测试数据源：mock。
- LLM：DeepSeek OpenAI-compatible API（deepseek-v4-flash / deepseek-v4-pro）。
- 编排：LangGraph StateGraph（8 节点多轮辩论工作流 + Supervisor 动态调度 + 循环边 + HITL 中断）。
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
    langgraph_orchestrator.py 多轮辩论工作流 + HITL API
  data/                      数据层（3 源 + 聚合器 + 标准化 + 缓存）
  research/                  研究引擎（评分 / 决策保护 / 基本面 / 估值 / 事件）
  llm/                       DeepSeek 客户端
  orchestrator/              单票研究主流程
  report/                    报告生成（JSON / Markdown / HTML / PDF）
  protocols/                 6 JSON Schemas + 验证
configs/                     评分权重 / 数据源 / 应用配置
apps/dashboard/              Streamlit 看板 + 报告库
tests/                       138 测试用例（6 文件）
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

页面左侧选择代码、数据源和是否启用 DeepSeek。报告库在 `apps/dashboard/pages/2_Report_Library.py`。

## 测试

```powershell
# 全部 138 个测试用例
python -m pytest

# 按模块运行
python -m pytest tests/test_decision_guard.py -v      # 决策保护器边界（25 用例）
python -m pytest tests/test_scoring_engine.py -v      # 评分引擎边缘值（28 用例）
python -m pytest tests/test_report_builders.py -v     # 报告生成验证（22 用例）
python -m pytest tests/test_langgraph_orchestrator.py -v  # LangGraph 多轮编排（29 用例）
python -m pytest tests/test_multi_round_debate.py -v  # 多轮辩论专用（15 用例）
python -m pytest tests/test_report_pipeline.py -v     # 端到端流程（11 用例）
```

覆盖范围：决策保护器全部边界条件、评分引擎六维度正常/边界/异常值、报告生成结构完整性与降级、LangGraph 多轮辩论/Supervisor 收敛逻辑/HITL 中断恢复、向后兼容性、QMT/AKShare/mock 数据链路、估值/事件标准化。

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

```python
from services.agents.langgraph_orchestrator import start_hitl_debate, resume_hitl_debate

# 启动多轮辩论 → 辩论完成后在 committee_convergence 暂停
interrupted = start_hitl_debate(research_result, thread_id="task-001", max_rounds=3)
# → 返回 bull_case / bear_case / risk_review / debate_history + __interrupt__

# 人工审核后恢复（可覆盖结论）
final = resume_hitl_debate(thread_id="task-001")
# 或传入 modified_state 覆盖 committee 结论
final = resume_hitl_debate(thread_id="task-001", modified_state={
    "committee_conclusion": {"stance": "回避", "action": "回避", ...}
})
```

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
