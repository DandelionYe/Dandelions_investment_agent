下面是按你最新约束重写后的**全新投研智能体方案**。它不再包含 Ollama、本地模型、Open WebUI、本地模型路由等设计；统一改为 **DeepSeek API Key + QMT 本地数据 + AKShare 补充数据 + Web 信息检索 + Streamlit 看板 + Markdown/PDF 报告**。

---

# 0. 新版结论

这次方案应从“本地模型投研 Agent”改成：

> **基于 DeepSeek API 的 A 股/ETF 私募投委会式投研智能体。**

第一版目标非常清晰：

```text
输入：单只沪深京 A 股个股或 ETF
输出：
1. Streamlit 投研看板
2. 结构化个股/ETF 打分卡
3. 多头/空头/风险官三方辩论过程
4. 收敛后的买卖建议，但不下单
5. Markdown 报告
6. PDF 报告
```

上一版方案里“拼装而非找单一仓库”的判断仍然保留；但“本地 Ollama / Open WebUI / 本地模型路由”这条线全部砍掉。原稿中的核心价值仍是：QMT 做主数据、Agent 做投研辩论、报告服务做导出。

---

# 1. 新版技术选型

## 1.1 LLM 接口层：DeepSeek API

DeepSeek 官方 API 当前支持 OpenAI/Anthropic 兼容格式，OpenAI 格式的 `base_url` 是 `https://api.deepseek.com`，因此系统里可以直接使用 OpenAI SDK 风格封装 `DeepSeekClient`。官方文档当前列出的模型包括 `deepseek-v4-flash` 和 `deepseek-v4-pro`，并提示旧的 `deepseek-chat` / `deepseek-reasoner` 名称将在未来废弃，所以新方案里建议直接面向 V4 模型名设计。([DeepSeek API Docs][1])

DeepSeek 官方还支持 JSON Output 与 Tool Calls；JSON Output 需要设置 `response_format={"type":"json_object"}`，并在 prompt 中明确要求 JSON 格式。这对你的系统很关键，因为 Agent 之间必须传结构化 JSON，而不是大段自然语言。([DeepSeek API Docs][2])

建议模型分工：

| 场景                  | 推荐模型                |
| ------------------- | ------------------- |
| 常规分析、摘要、工具调用        | `deepseek-v4-flash` |
| 多头/空头/风险官辩论、最终投委会结论 | `deepseek-v4-pro`   |
| JSON 修复、报告润色、格式化    | `deepseek-v4-flash` |
| 高置信度深度报告            | `deepseek-v4-pro`   |

原因很简单：你现在不再受本地显存限制，真正需要控制的是 **API 成本、结构化稳定性、失败重试和证据可追溯性**。DeepSeek 官方价格页按 1M token 计费，并明确提示价格可能变化，所以系统里应记录每次任务的 token 消耗和模型成本。([DeepSeek API Docs][3])

---

## 1.2 主编排层：LangGraph

仍然建议使用 **LangGraph**，但用途变了：不再做本地模型编排，而是做“DeepSeek API Agent 工作流编排”。

LangGraph 适合你的原因是：它支持 durable execution、human-in-the-loop 和 memory，适合“数据收集 → 多方辩论 → 风控复核 → 报告生成 → 人工查看”的有状态流程。([LangChain 文档][4])

---

## 1.3 后端 API：FastAPI

建议新增一个 **FastAPI 后端服务**，作为 Streamlit、任务队列、报告服务和数据服务之间的统一入口。FastAPI 官方定位是基于 Python 类型标注构建 API 的现代高性能 Web 框架，适合做系统内部服务边界。([FastAPI][5])

---

## 1.4 前端：Streamlit

这版不再需要 Open WebUI。你的核心入口应该是 **Streamlit 投研看板**。

Streamlit 适合快速搭建数据应用和 AI/ML 交互应用，可以把股票输入、因子表、辩论过程、报告预览、PDF 下载集中在一个页面里。([docs.streamlit.io][6])

---

## 1.5 报告导出：Markdown + Jinja2 + WeasyPrint

报告生成链路建议固定为：

```text
结构化 JSON
  -> Markdown 报告
  -> Jinja2 HTML 模板
  -> WeasyPrint PDF
```

WeasyPrint 官方定位就是把 HTML/CSS 转换为 PDF 文档，非常适合投委会纪要、量化打分卡、固定版式报告。([WeasyPrint][7])

---

## 1.6 数据层：QMT 为主，AKShare 和网页为补充

你的主链路仍然是 QMT 本地数据。AKShare 只做补充，不做主链路。

AKShare 官方说明它是 Python 财经数据接口库，支持 Python 3.9+，并提供 A 股历史行情等接口示例；它可以补充公告、公开行情、部分 ETF/市场数据，但不应该覆盖 QMT 的主数据地位。([GitHub][8])

---

# 2. 推荐运行方式

我建议采用：

> **Windows 原生运行 + 单机本地服务 + 不强依赖 WSL/Docker。**

理由是：你的 QMT 终端在 Windows 侧，第一版目标是单只股票/ETF分析和 PDF 报告，不需要复杂容器化。你已有 Windows、VS Code、Python、PostgreSQL、Docker、WSL2 等环境，但这版不应该为了“看起来工程化”而全部用上。你的硬件信息显示 Windows 环境、Python 3.13.7、PostgreSQL、Docker、WSL2 都已经存在，但磁盘可用空间小于 50GB，所以第一版应减少 Docker 镜像和多环境复制。

新版推荐：

```text
Windows 原生：
- QMT / xtquant 数据服务
- FastAPI 后端
- LangGraph 编排
- Streamlit 看板
- Report Service
- PostgreSQL 或 SQLite
```

第一版可以先用 SQLite，等观察池、任务历史、报告库变复杂后再切 PostgreSQL。

不建议第一版使用：

```text
- Open WebUI
- Ollama
- 本地模型服务
- Docker Compose 全家桶
- WSL 内部跑 QMT 相关服务
- Qlib 全量接入
```

---

# 3. 新版系统架构

```text
┌──────────────────────────────┐
│        Streamlit 投研看板      │
│ 股票输入 / ETF输入 / 报告查看  │
└───────────────┬──────────────┘
                │
                ▼
┌──────────────────────────────┐
│          FastAPI Gateway      │
│ 任务创建 / 状态查询 / 报告下载 │
└───────────────┬──────────────┘
                │
                ▼
┌──────────────────────────────┐
│       LangGraph Orchestrator  │
│ 任务状态 / Agent编排 / 辩论收敛│
└───────┬────────┬────────┬─────┘
        │        │        │
        ▼        ▼        ▼
┌──────────┐ ┌──────────┐ ┌────────────┐
│ 数据服务 │ │ 研究计算 │ │ Web研究服务 │
│ QMT/AK   │ │ 因子/风控│ │ 新闻/公告/政策│
└────┬─────┘ └────┬─────┘ └──────┬─────┘
     │            │              │
     └────────────┴──────────────┘
                  │
                  ▼
┌──────────────────────────────┐
│        DeepSeek Agent Runtime │
│ 多头 / 空头 / 风险官 / 主笔    │
└───────────────┬──────────────┘
                │
                ▼
┌──────────────────────────────┐
│          Report Service       │
│ JSON -> Markdown -> HTML -> PDF│
└──────────────────────────────┘
```

---

# 4. 模块目录树

```text
a-share-investment-agent/
├─ apps/
│  └─ dashboard/
│     ├─ Home.py
│     ├─ pages/
│     │  ├─ 1_单票研究.py
│     │  ├─ 2_研究报告库.py
│     │  ├─ 3_观察池.py
│     │  └─ 4_系统设置.py
│     └─ components/
│        ├─ factor_card.py
│        ├─ debate_view.py
│        ├─ risk_panel.py
│        └─ report_preview.py
│
├─ services/
│  ├─ api/
│  │  ├─ main.py
│  │  ├─ routes/
│  │  │  ├─ research.py
│  │  │  ├─ report.py
│  │  │  ├─ watchlist.py
│  │  │  └─ system.py
│  │  └─ schemas/
│  │
│  ├─ orchestrator/
│  │  ├─ stock_research_graph.py
│  │  ├─ etf_research_graph.py
│  │  ├─ states.py
│  │  ├─ stop_rules.py
│  │  └─ cost_guard.py
│  │
│  ├─ agents/
│  │  ├─ supervisor.py
│  │  ├─ bull_analyst.py
│  │  ├─ bear_analyst.py
│  │  ├─ risk_officer.py
│  │  ├─ committee_secretary.py
│  │  └─ report_writer.py
│  │
│  ├─ llm/
│  │  ├─ deepseek_client.py
│  │  ├─ json_guard.py
│  │  ├─ prompt_templates.py
│  │  └─ token_usage.py
│  │
│  ├─ data/
│  │  ├─ qmt_provider.py
│  │  ├─ akshare_provider.py
│  │  ├─ web_provider.py
│  │  ├─ symbol_resolver.py
│  │  └─ data_quality.py
│  │
│  ├─ research/
│  │  ├─ factor_engine.py
│  │  ├─ scoring_engine.py
│  │  ├─ risk_engine.py
│  │  ├─ etf_engine.py
│  │  └─ backtest_stub.py
│  │
│  └─ report/
│     ├─ markdown_builder.py
│     ├─ html_builder.py
│     ├─ pdf_builder.py
│     ├─ templates/
│     │  ├─ committee_note.html
│     │  └─ factor_scorecard.html
│     └─ assets/
│
├─ protocols/
│  ├─ research_task.schema.json
│  ├─ evidence_bundle.schema.json
│  ├─ factor_score.schema.json
│  ├─ debate_round.schema.json
│  ├─ risk_opinion.schema.json
│  ├─ final_decision.schema.json
│  └─ report_manifest.schema.json
│
├─ storage/
│  ├─ market_cache/
│  ├─ reports/
│  ├─ artifacts/
│  ├─ logs/
│  └─ app.db
│
├─ configs/
│  ├─ app.yaml
│  ├─ deepseek.yaml
│  ├─ data_sources.yaml
│  ├─ scoring.yaml
│  └─ report.yaml
│
└─ docs/
   ├─ architecture.md
   ├─ agent_protocol.md
   ├─ data_schema.md
   └─ future_qmt_trading.md
```

---

# 5. 服务边界

## 5.1 Streamlit Dashboard

职责：

```text
- 输入股票/ETF代码
- 选择研究周期：默认 1–3 个月
- 展示行情、因子、打分、风险
- 展示多头/空头/风险官辩论过程
- 展示最终建议
- 预览 Markdown 报告
- 下载 PDF 报告
```

不负责：

```text
- 不直接调用 DeepSeek
- 不直接读取 QMT
- 不直接生成最终结论
```

---

## 5.2 FastAPI Gateway

职责：

```text
- 接收 Streamlit 请求
- 创建研究任务
- 查询任务状态
- 返回报告文件
- 管理观察池
- 管理系统配置
```

核心接口：

```text
POST /research/single
GET  /research/{task_id}
GET  /reports/{report_id}
GET  /reports/{report_id}/pdf
POST /watchlist
GET  /watchlist
```

---

## 5.3 Orchestrator

职责：

```text
- 管理一次研究任务的状态
- 调用数据服务
- 调用因子/风控计算
- 组织多头、空头、风险官辩论
- 判断是否收敛
- 生成最终投委会意见
- 触发报告生成
```

状态机：

```text
PENDING
COLLECTING_DATA
CALCULATING_FACTORS
BULL_ANALYSIS
BEAR_ANALYSIS
RISK_REVIEW
DEBATE_CONVERGENCE
FINAL_DECISION
REPORTING
COMPLETED
FAILED
```

---

## 5.4 Data Service

主数据来自 QMT。

第一版需要支持：

```text
- 沪深京 A 股代码识别
- ETF 代码识别
- 日 K / 周 K
- 近 1 年行情
- 近 3 年财务摘要
- 股票基础信息
- ETF 基础信息
- 行业/板块字段预留
```

AKShare 补充：

```text
- 公开行情校验
- ETF 补充信息
- 公告/新闻辅助数据
- 宏观/政策类公开数据
```

注意：AKShare 只能作为补充源。若 QMT 和 AKShare 数据冲突，第一版默认以 QMT 为准。

---

## 5.5 Research Engine

第一版不接 Qlib，先做轻量研究引擎。

它负责生成“私募投委会 + 量化打分卡”所需的硬指标：

```text
价格趋势：
- 20日涨跌幅
- 60日涨跌幅
- 120日涨跌幅
- MA20 / MA60 位置
- 趋势强度

量能：
- 20日平均成交额
- 近5日成交额变化
- 放量/缩量状态

波动风险：
- 20日波动率
- 60日波动率
- 最大回撤
- 下行波动

流动性：
- 平均成交额
- 成交额稳定性
- 是否低流动性标的

基本面：
- ROE
- 毛利率
- 净利率
- 营收增速
- 净利润增速
- 经营现金流质量
- 资产负债率

估值：
- PE 分位
- PB 分位
- 股息率
- 估值与成长匹配度

ETF 专属：
- 跟踪标的
- 规模
- 成交额
- 折溢价
- 跟踪误差字段预留
```

---

# 6. Agent 设计

新版不需要太多 Agent。第一版建议 5 个角色。

## 6.1 Supervisor

职责：

```text
- 判断输入是股票还是 ETF
- 确定研究任务类型
- 决定需要哪些数据
- 检查数据是否足够
- 分配给多头、空头、风险官
```

输出：

```json
{
  "task_type": "stock_research",
  "symbol": "600519.SH",
  "horizon": "1-3m",
  "required_modules": ["price", "fundamental", "valuation", "risk", "web"],
  "research_question": "未来1-3个月是否具备较好的风险收益比？"
}
```

---

## 6.2 Bull Analyst 多头分析师

职责：

```text
- 找上涨逻辑
- 找基本面支撑
- 找技术趋势支撑
- 找估值修复或催化逻辑
- 给出正面论证
```

输出重点：

```text
- 核心多头观点
- 主要证据
- 上涨催化
- 适合介入的条件
- 观点失效条件
```

---

## 6.3 Bear Analyst 空头分析师

职责：

```text
- 找下跌风险
- 找估值过高风险
- 找基本面瑕疵
- 找趋势破坏风险
- 反驳多头观点
```

输出重点：

```text
- 核心空头观点
- 主要反证
- 不宜买入的理由
- 需要回避的条件
- 空头观点失效条件
```

---

## 6.4 Risk Officer 风险官

职责：

```text
- 不负责看多或看空
- 只负责风险定级
- 判断是否允许给买入建议
- 给出仓位上限和风险触发条件
```

风险官可以否决：

```text
- 数据缺失
- 流动性不足
- 波动过大
- 最大回撤过高
- 单一题材驱动
- 估值与成长明显不匹配
- 近期新闻/政策风险未消化
```

---

## 6.5 Committee Secretary 投委会秘书 / 报告主笔

职责：

```text
- 汇总多头、空头、风险官意见
- 形成收敛结论
- 生成私募投委会纪要
- 生成量化打分卡
- 输出 Markdown 和 PDF
```

它不是“拍脑袋给结论”，而是只能基于前面几个 Agent 的结构化输出进行总结。

---

# 7. 多方辩论机制

你的要求是：多头/空头/风险官三方结构化辩论，展示过程，并收敛观点。

第一版建议只做 **一轮主辩论 + 一轮收敛**，不要无限多轮。

```text
第 0 步：系统生成证据包
第 1 步：多头分析师输出 bull_case
第 2 步：空头分析师输出 bear_case
第 3 步：风险官输出 risk_review
第 4 步：多头回应空头最强反驳
第 5 步：空头回应多头最强论点
第 6 步：风险官给最终风险约束
第 7 步：投委会秘书收敛结论
```

看板展示形式：

```text
左栏：多头观点
中栏：空头观点
右栏：风险官意见
底部：最终投委会结论
```

---

# 8. 打分体系

第一版建议总分 100 分，分成 6 类。

```text
1. 趋势动量：20分
2. 量能与流动性：15分
3. 基本面质量：20分
4. 估值性价比：15分
5. 风险控制：20分
6. 新闻/政策/事件：10分
```

股票评分输出：

```json
{
  "symbol": "600519.SH",
  "asset_type": "stock",
  "total_score": 76,
  "rating": "B+",
  "score_breakdown": {
    "trend_momentum": 14,
    "liquidity": 13,
    "fundamental_quality": 18,
    "valuation": 10,
    "risk_control": 15,
    "event_policy": 6
  },
  "stance": "谨慎看多",
  "suggested_action": "回调关注，不建议追高",
  "max_position": "5%-8%",
  "horizon": "1-3个月"
}
```

ETF 评分输出：

```json
{
  "symbol": "510300.SH",
  "asset_type": "etf",
  "total_score": 72,
  "rating": "B",
  "score_breakdown": {
    "underlying_trend": 15,
    "liquidity": 14,
    "tracking_quality": 10,
    "valuation_environment": 11,
    "risk_control": 15,
    "event_policy": 7
  },
  "stance": "中性偏多",
  "suggested_action": "适合分批配置",
  "max_position": "10%-15%",
  "horizon": "1-3个月"
}
```

---

# 9. 买卖建议边界

你明确说：**可以做买卖建议，但不下单**。

所以第一版建议只支持 5 类建议：

```text
1. 买入
2. 分批买入
3. 持有
4. 观察
5. 回避
```

不输出：

```text
- 自动下单
- 自动委托
- 自动调仓
- 必然涨跌判断
```

建议格式：

```json
{
  "decision": "分批买入",
  "confidence": 0.72,
  "entry_condition": "回调至20日均线附近且成交额不显著萎缩",
  "stop_loss_condition": "跌破60日均线或最大回撤超过预设阈值",
  "take_profit_condition": "达到目标区间或风险收益比下降",
  "max_position": "8%",
  "review_date": "10个交易日后复核"
}
```

---

# 10. 报告结构

报告风格：**私募投委会纪要 + 量化因子打分卡**。

建议 PDF 结构如下：

```text
封面
- 标的名称
- 代码
- 资产类型：股票 / ETF
- 研究日期
- 研究周期：1–3个月
- 最终评级

一、投委会结论
- 最终建议
- 置信度
- 仓位建议
- 核心理由
- 主要风险

二、量化因子打分卡
- 总分
- 分项得分
- 历史区间位置
- 同类比较字段预留

三、行情与趋势分析
- 价格趋势
- 均线结构
- 成交量变化
- 波动与回撤

四、基本面与估值分析
- 股票：财务质量、成长、估值
- ETF：跟踪标的、流动性、折溢价、跟踪质量

五、多头观点
- 核心上涨逻辑
- 证据
- 催化因素
- 失效条件

六、空头观点
- 核心反对逻辑
- 反证
- 下行风险
- 失效条件

七、风险官意见
- 风险等级
- 仓位约束
- 风险触发条件
- 是否否决买入

八、辩论收敛纪要
- 多头最强论点
- 空头最强反驳
- 风险官最终裁决
- 收敛后的最终判断

九、跟踪计划
- 后续观察指标
- 复核时间
- 触发重新评估的条件

免责声明
- 本系统仅供投研辅助，不构成投资建议
```

---

# 11. 核心协议设计

## 11.1 ResearchTask

```json
{
  "task_id": "task_20260429_0001",
  "asset_type": "stock",
  "symbol": "600519.SH",
  "market": "CN_A",
  "horizon": "1-3m",
  "objective": "评估未来1-3个月的风险收益比，并生成投委会纪要和量化打分卡",
  "outputs": ["dashboard", "markdown_report", "pdf_report"],
  "constraints": {
    "allow_qmt": true,
    "allow_akshare": true,
    "allow_web_search": true,
    "allow_trading": false,
    "show_debate": true
  }
}
```

---

## 11.2 EvidenceBundle

```json
{
  "bundle_id": "evb_0001",
  "symbol": "600519.SH",
  "asset_type": "stock",
  "as_of": "2026-04-29",
  "data_sources": ["QMT", "AKShare", "Web"],
  "items": [
    {
      "evidence_id": "ev_price_001",
      "category": "price",
      "title": "近60日涨跌幅",
      "value": 0.082,
      "source": "QMT",
      "as_of": "2026-04-29",
      "confidence": 0.98
    },
    {
      "evidence_id": "ev_risk_001",
      "category": "risk",
      "title": "近60日最大回撤",
      "value": -0.115,
      "source": "research_engine",
      "as_of": "2026-04-29",
      "confidence": 0.95
    }
  ]
}
```

---

## 11.3 DebateRound

```json
{
  "round_id": "debate_0001",
  "symbol": "600519.SH",
  "bull_case": {
    "thesis": "中线趋势改善，基本面质量仍具支撑。",
    "key_arguments": [
      "盈利质量稳定",
      "趋势结构修复",
      "资金承接较好"
    ],
    "evidence_ids": ["ev_price_001", "ev_fin_001"],
    "invalidation_conditions": [
      "跌破60日均线",
      "下一期盈利增速显著低于预期"
    ]
  },
  "bear_case": {
    "thesis": "估值弹性不足，赔率并不突出。",
    "key_arguments": [
      "估值分位偏高",
      "缺乏明显新增催化",
      "若市场风格切换则相对收益受压"
    ],
    "evidence_ids": ["ev_val_001", "ev_style_001"],
    "invalidation_conditions": [
      "估值回落到合理区间",
      "行业景气度上修"
    ]
  },
  "risk_review": {
    "risk_level": "medium",
    "blocking": false,
    "risk_summary": "可观察或小仓位参与，但不宜重仓追高。",
    "max_position": "5%-8%"
  }
}
```

---

## 11.4 FinalDecision

```json
{
  "decision_id": "final_0001",
  "symbol": "600519.SH",
  "asset_type": "stock",
  "horizon": "1-3m",
  "score": 76,
  "rating": "B+",
  "stance": "谨慎看多",
  "action": "分批买入",
  "confidence": 0.72,
  "position_advice": {
    "max_position": "5%-8%",
    "entry_condition": "回调但趋势未破坏",
    "stop_loss_condition": "跌破60日均线或风险评分降至60以下",
    "review_condition": "10个交易日后或出现重大公告后复核"
  },
  "core_reasons": [
    "趋势结构改善",
    "基本面质量较高",
    "风险官未否决"
  ],
  "major_risks": [
    "估值压缩",
    "市场风格切换",
    "业绩增速不及预期"
  ],
  "report_id": "report_20260429_0001"
}
```

---

# 12. 第一版开发范围

第一版只做这个闭环：

```text
单只股票/ETF输入
  -> 拉取 QMT 数据
  -> AKShare/Web 补充
  -> 计算因子和风险
  -> DeepSeek 生成多头观点
  -> DeepSeek 生成空头观点
  -> DeepSeek 生成风险官意见
  -> DeepSeek 收敛投委会结论
  -> 生成 Markdown
  -> 生成 PDF
  -> Streamlit 展示
```

第一版不做：

```text
- 自动交易
- QMT 下单
- 多账户
- 全市场扫描
- 指数/板块专题
- 可转债/期货/期权
- 复杂组合优化
- Qlib 全量研究框架
- RAG 研报库
```

但代码字段预留：

```text
asset_type:
- stock
- etf
- index_future
- convertible_bond
- sector
- option
- futures

execution_mode:
- research_only
- paper_trading
- qmt_manual_confirm
- qmt_auto_trade
```

---

# 13. 最终推荐方案一句话

你现在最合适的方案是：

> **Windows 原生部署的 DeepSeek API 投研智能体：QMT 做主数据源，AKShare 和网页搜索做补充，LangGraph 编排多头/空头/风险官辩论，Streamlit 展示投研看板，Jinja2 + WeasyPrint 生成私募投委会式 PDF 报告。**

第一版先完成：

```text
能分析单只沪深京 A 股个股或 ETF
能生成量化打分卡
能展示三方辩论过程
能给出买卖建议但不下单
能生成 Markdown + PDF 报告
```

这版比原方案更轻、更符合你现在的真实目标，也避免了本地模型、Docker、WSL、Open WebUI、Qlib 全量接入带来的不必要复杂度。
