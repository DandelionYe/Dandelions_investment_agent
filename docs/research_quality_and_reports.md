# P2：研究质量与报告能力

## 范围

P2 分为多个阶段推进：

| 阶段 | 目标 | 状态 |
|------|------|------|
| Phase 1 | 8 个离线构造样本 + 报告模板 + evidence schema + 新闻质量 | ✅ 已完成 |
| Phase 2 | 50+ 真实历史样本池 + 可重复质量报告 + 验收阈值 | 进行中：QMT 价格、CSMAR 估值、EVA 股本/BPS 已落地；严格行业和盈利基本面仍阻塞 |
| Phase 3 | 全链路 evidence schema | 待规划 |
| Phase 4 | 报告产品化 | 待规划 |
| Phase 5 | 真实新闻长期监控 | 待规划 |
| Phase 6 | 质量治理基线 | 待规划 |

---

## P2 Phase 1：基础能力

### 1. 历史回测与压力测试

### 运行方式

```bash
python scripts/run_research_quality_backtest.py
```

输出：
- `storage/artifacts/research_quality/backtest_summary.json`
- `storage/artifacts/research_quality/backtest_summary.md`

### 样本验收规则

| 样本 | 场景 | 验收条件 |
|------|------|---------|
| high_quality_low_valuation | 高质量低估值上涨 | score >= 70，禁止回避/谨慎观察 |
| high_valuation_strong_trend | 高估值但趋势强 | score <= 90 |
| large_drawdown_high_volatility | 大回撤高波动 | action 不高于观察 |
| loss_making_invalid_pe | 亏损或PE无效 | 禁止买入/分批买入 |
| industry_insufficient_peers | 行业样本不足 | 正常评分不报错 |
| critical_event | critical事件 | action 必须为回避 |
| placeholder_blocking | 数据质量阻断 | action 限制为观察 |
| etf_no_fundamental | ETF无股票基本面 | score >= 50 |

### 确定性规则（不依赖收益预测）

- 所有样本 score 在 0-100。
- 所有样本 `score_breakdown` 包含 6 个维度。
- 所有样本应用 `apply_decision_guard()` 后必须包含 `decision_guard`。
- critical / placeholder / blocking 样本不得输出买入或分批买入。
- 高质量样本 score 必须高于大回撤高波动样本。
- ETF 样本不能因为缺少股票 fundamental/valuation 失败。

## 2. 报告模板体系升级

### 配置说明

```python
from services.report.template_config import ReportTemplateConfig

cfg = ReportTemplateConfig(
    template_id="default",
    theme_id="institutional_light",  # institutional_light / institutional_dark / compact_blue
    sections=["basic_info", "committee_conclusion", ...],
    show_evidence=True,       # 关闭后报告不包含 EvidenceBundle 摘要
    show_data_quality=True,   # 关闭后报告不包含数据质量表格
    show_decision_guard=True, # 关闭后报告不包含决策保护器章节
    show_disclaimer=True,     # 关闭后报告不包含免责声明
    table_density="normal",   # compact / normal
    language="zh-CN",
)
```

### 使用方式

```python
# Markdown 报告（向后兼容，不传 config 等同默认）
md = build_markdown_report(result)
md = build_markdown_report(result, template_config=cfg)
md = build_markdown_report(result, template_config={"show_evidence": False})

# HTML 报告（向后兼容，不传 theme 等同默认）
html = build_html_report(markdown_text, title="报告")
html = build_html_report(markdown_text, title="报告", theme=get_theme("institutional_dark"))
```

### 主题

| 主题 | 说明 |
|------|------|
| institutional_light | 默认浅色主题 |
| institutional_dark | 深色主题 |
| compact_blue | 紧凑蓝色主题，较小页边距 |

### 章节标识

`basic_info`, `committee_conclusion`, `data_source_and_price`, `scorecard`, `bull_case`, `bear_case`, `risk_officer`, `decision_guard`, `debate_convergence`, `follow_up`, `disclaimer`

## 3. 数据证据结构统一

### 统一结构

```python
{
    "value": ...,           # 原始值，None 表示缺失
    "source": "qmt|akshare|local_csmar|web_news|mock|unknown",
    "as_of": "YYYY-MM-DD", # 数据日期
    "quality": {
        "available": bool,
        "confidence": float | None,  # 0-1
        "freshness": "fresh|stale|unknown|not_applicable",
        "missing_reason": str | None,
    },
    "warnings": list[str],
}
```

### 使用方式

```python
from services.data.evidence_schema import (
    make_evidence_field,
    is_evidence_field,
    normalize_evidence_field,
    extract_display_value,
    normalize_key_fields,
)

# 构造证据字段
ev = make_evidence_field(42, source="qmt", as_of="2026-05-01")

# 判断是否为证据字段
is_evidence_field(ev)  # True
is_evidence_field(42)  # False

# 标准化（幂等）
normalize_evidence_field(ev)    # 已是 evidence field → 补齐缺失 key
normalize_evidence_field(42)    # 裸值 → 包装为 evidence field

# 提取显示值
extract_display_value(ev)  # 42
extract_display_value(42)  # 42

# 关键字段统一（写入 result["evidence_fields"]，不修改原始裸值）
normalize_key_fields(result)
```

### 覆盖的字段路径

- `price_data.close`, `change_20d`, `change_60d`, `avg_turnover_20d`
- `valuation_data.pe_ttm`, `pb_mrq`, `ps_ttm`, `pe_percentile`, `pb_percentile`, `ps_percentile`, `industry_pe_percentile`, `industry_pb_percentile`, `industry_ps_percentile`
- `fundamental_data.roe`, `gross_margin`, `net_profit_growth`
- `event_data.major_event`

## 4. 网页新闻/舆情质量验收

### 运行方式

```bash
python scripts/run_web_news_quality_check.py
```

输出：
- `storage/artifacts/web_news_quality/summary.json`
- `storage/artifacts/web_news_quality/summary.md`

### 质量规则

**去重：**
- URL 完全相同 → 保留第一条。
- 标题归一化后相同 → 保留第一条。

**相关性：**
- 公司名/简称/代码匹配 → 高相关。
- 纯泛财经热榜、娱乐、广告、福利 → 低相关。

**低质量过滤：**
- 标题过短（<6字）→ 低质量。
- 推广/福利/广告模式 → 低质量。

**失败降级：**
- provider timeout/unavailable → 记录 failure，不抛异常。

### 验收样本

| 样本 | 说明 |
|------|------|
| relevant_company_news | 相关公司新闻，应高相关 |
| duplicate_title_news | 同标题重复，应去重为1条 |
| duplicate_url_news | 同URL重复，应去重为1条 |
| low_quality_promotion | 低质量推广，应被识别 |
| irrelevant_hotrank | 泛财经热榜，与标的无关 |
| provider_unavailable | provider不可用，应记录失败 |
| provider_timeout | provider超时，应记录失败 |

## 测试

```bash
# 新增测试
python -m pytest tests/test_research_quality_backtest.py -q
python -m pytest tests/test_report_template_config.py -q
python -m pytest tests/test_evidence_schema_contract.py -q
python -m pytest tests/test_web_news_quality_contract.py -q

# 已有测试（不应被破坏）
python -m pytest tests/test_report_builders.py tests/test_report_pipeline.py -q
python -m pytest tests/test_scoring_engine.py tests/test_decision_guard.py -q
python -m pytest tests/test_valuation_percentile.py tests/test_web_news_provider.py -q
```

---

## P2 Phase 2A：手动快照历史回测（已完成）

### 概述

Phase 2A 将 Phase 1 的 8 个离线构造样本升级为 52 个基于公开行情模式的真实历史快照样本，覆盖 13 个场景标签，并提供可配置验收阈值和结构化质量报告。

**已知限制**：样本来源为 `manual_snapshot`，forward_metrics 为合理估计值，行业分位基于平均水平。

---

## P2 Phase 2B：真实 QMT 历史样本池（进行中）

### 概述

Phase 2B 将样本来源从 `manual_snapshot` 升级为真实 QMT 历史行情数据 + 本地 CSMAR/EVA/行业库。通过 `--use-qmt --require-qmt` 参数，从 MiniQMT 获取真实日 K 线，精确计算 20/60/120 交易日前瞻收益、相对沪深300收益、最大回撤。

当前状态：100 个 `qmt_xtdata` 样本已生成，价格来源 100% QMT、EVA 股本/BPS 覆盖 100%、CSMAR 严格估值覆盖 72%。严格 Phase 2B 验收不会再假通过：盈利质量基本面覆盖率 0%、严格行业来源覆盖率 0%、严格行业分位有效率 0%、完整研究输入覆盖率 0%。

**当前阻塞**：
- 行业库只有单一快照（2026-05-20），历史样本行业来源为 non-strict，不能计入严格 as_of。
- EVA 只提供股本/BPS/市值等资本结构字段，缺少 ROE、毛利率、利润增速等盈利质量指标。
- 评级/动作分桶有限（D/C 为主），严格验收应失败并暴露这些缺口。

### 与 Phase 2A 的区别

| 维度 | Phase 2A | Phase 2B |
|------|----------|----------|
| 价格来源 | manual_snapshot | qmt_xtdata |
| forward_metrics | 合理估计值 | 从真实行情精确计算 |
| 基准对比 | 无 | 相对沪深300 (000300.SH) |
| 数据来源证明 | 无 | source_metadata 完整 provenance |
| 资产范围 | 混合 | 沪深主板 A 股 + 边界例外 |
| 基本面/估值 | 手工构造 | EVA 股本/BPS + CSMAR PE/PB/PS/分位；盈利基本面和严格行业仍缺失 |

### 运行方式

```bash
# 构建真实 QMT 样本（需要 MiniQMT 运行）
python scripts/build_historical_research_samples.py \
    --use-qmt --require-qmt \
    --asset-scope mainboard-a \
    --start-year 2021 --end-year 2026 \
    --benchmark 000300.SH \
    --min-samples 50 \
    --overwrite

# 严格 Phase 2B 验收：缺少基本面/估值/行业时应失败
python scripts/run_historical_research_quality_backtest.py

# 仅验证 QMT 价格链路 smoke，不代表 Phase 2B 完成
python scripts/run_historical_research_quality_backtest.py --allow-price-only
```

### 新增 CLI 参数

| 参数 | 说明 |
|------|------|
| `--require-qmt` | QMT 不可用时 exit 1，不回退 manual_snapshot |
| `--asset-scope mainboard-a` | 只选沪深主板 A 股 |
| `--start-year N` | as_of 起始年份 |
| `--end-year N` | as_of 结束年份 |
| `--benchmark SYMBOL` | 基准指数（默认 000300.SH） |
| `--boundary-symbols` | 边界样本股票列表（逗号分隔） |

### 主板过滤规则

| 交易所 | 前缀 | 说明 |
|--------|------|------|
| SH 主板 | 600, 601, 603, 605 | 上交所主板 |
| SZ 主板 | 000, 001, 002 | 深交所主板 |
| 排除 | 300/301 | 创业板 |
| 排除 | 688/689 | 科创板 |
| 排除 | BJ | 北交所 |
| 排除 | ETF codes | ETF |
| 例外 | 688646.SH | 用户指定边界例外，标记 out_of_scope_exception |

### 边界样本股票（13只）

603778.SH, 600410.SH, 000008.SZ, 000029.SZ, 000002.SZ, 000158.SZ, 000488.SZ, 000547.SZ, 002816.SZ, 002485.SZ, 002496.SZ, 688646.SH, 000711.SZ

### 数据来源 Provenance

每个样本的 `source_metadata` 记录数据来源：

```json
{
  "price_source": "qmt_xtdata",
  "fundamental_source": "missing",
  "capital_structure_source": "local_csmar_eva_structure_partial|missing",
  "valuation_source": "local_csmar_daily_derived|missing",
  "industry_source": "local_csmar_industry|local_csmar_industry_non_strict|missing",
  "as_of": "2023-06-30",
  "symbol": "600519.SH"
}
```

**来源说明**：
- `qmt_xtdata`：QMT 历史日 K 线（价格、成交额、forward metrics）
- `local_csmar_eva_structure_partial`：CSMAR EVA 股本结构（total_volume/float_volume/market_cap/bps），严格 as_of，但不等同于盈利质量基本面
- `local_csmar_daily_derived`：CSMAR 个股日交易衍生指标（PE/PB/PS/dividend_yield/分位），严格 as_of
- `local_csmar_industry`：CSMAR 行业分类（行业名称/同行列表），严格 as_of（仅当 snapshot_date <= as_of）
- `local_csmar_industry_non_strict`：CSMAR 行业分类，最新快照 fallback（历史日期不可严格验证）

### 验收阈值（Phase 2B 扩展）

在 Phase 2A 基础上新增：

- `min_price_source_coverage`: 价格来源为 QMT 的样本占比（真实模式默认 1.0）
- `min_fundamental_source_coverage`: 盈利质量基本面来源覆盖率，严格模式默认 0.60；EVA 股本/BPS 不计入
- `min_valuation_source_coverage`: 估值来源覆盖率，严格模式默认 0.60
- `min_industry_source_coverage`: 行业来源覆盖率，严格模式默认 0.60
- `min_data_complete_coverage`: 完整研究输入覆盖率，严格模式默认 0.50
- `capital_structure_source_coverage`: 诊断指标，记录 EVA 股本/BPS 覆盖率，不作为盈利基本面替代
- `min_placeholder_sample_count` / `min_critical_sample_count`: 没有对应样本时不再把保护器命中率记为 100%

### 验收标准

- 真实 QMT 样本 >= 50
- 价格来源 qmt_xtdata 覆盖率 = 100%
- 20/60/120 日 `benchmark_return_*`、`relative_return_*`、`max_drawdown_*` 均存在
- manual_snapshot 样本不计入真实样本数
- 盈利基本面/估值/行业来源覆盖率达到严格阈值；EVA 股本/BPS 只能算资本结构补充
- 高风险激进建议违规率 = 0
- placeholder 必须有实际样本且保护器命中率达标；历史新闻/critical event 不属于 Phase 2B 阻塞项
- 单一评分分桶占比 <= 70%
- 评级/动作分桶数 >= 3

### 测试

```bash
# 离线单元测试（不依赖 QMT）
python -m pytest tests/test_historical_sample_builder.py -q
python -m pytest tests/test_historical_quality_backtest.py -q
python -m pytest tests/test_historical_samples_contract.py -q

# QMT 集成测试（需要 MiniQMT）
set RUN_HISTORICAL_QMT_BACKTEST=1
python -m pytest tests/test_historical_qmt_integration.py -q
```

### 已知限制

- **行业库只有单一快照**（2026-05-20）：所有 2021-2025 历史样本的行业来源标记为 `local_csmar_industry_non_strict`，不计入严格行业来源覆盖率（0%）。行业分位仍可从同行 PE/PB/PS 诊断性计算（72% 样本有效），但严格行业分位有效率为 0%。
- **盈利质量基本面缺失**：EVA 提供 total_volume/float_volume/market_cap/bps，不提供 ROE/gross_margin/net_profit_growth/revenue_growth。Phase 2B 明确不接入 QMT financial，因此当前盈利基本面覆盖率为 0%。
- **评级/动作分桶有限**：由于缺少盈利指标，评分主要依赖价格趋势和估值，集中在 D/C 评级和回避/谨慎观察动作。这是当前数据能力的诚实反映。
- **data_complete = 0%**：`data_complete` 要求估值、盈利基本面、行业均严格 as_of，当前行业库和盈利基本面无法满足。
- 2026 年部分 as_of 可能无法获得完整 120 交易日 forward 数据，标记 coverage_gap。
- 688646.SH 作为科创板边界例外，不计入主板覆盖比例。
