# P2：研究质量与报告能力

## 范围

P2 分为多个阶段推进：

| 阶段 | 目标 | 状态 |
|------|------|------|
| Phase 1 | 8 个离线构造样本 + 报告模板 + evidence schema + 新闻质量 | ✅ 已完成 |
| Phase 2 | 50+ 真实历史样本池 + 可重复质量报告 + 验收阈值 | ✅ 已完成：QMT 价格、CSMAR 估值、EVA 股本/BPS、本地 CSMAR 财务报表、严格历史行业；严格 Phase 2B 验收通过 |
| Phase 3 | 全链路 evidence schema | ✅ 已完成 |
| Phase 4 | 报告产品化 | ✅ 已完成 |
| Phase 5 | 真实新闻长期监控 | ✅ 代码层已完成 |
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
    "source": "qmt_xtdata|local_csmar_daily_derived|local_csmar_financial_statements|"
              "local_csmar_industry_history|local_csmar_eva_structure_partial|"
              "akshare|web_news|derived|missing|mock|unknown",
    "as_of": "YYYY-MM-DD", # 数据日期
    "quality": {
        "available": bool,
        "confidence": float | None,  # 0-1
        "freshness": "fresh|stale|historical|estimated|missing|unknown|not_applicable",
        "missing_reason": str | None,
    },
    "warnings": list[str],
}
```

### Source 层级

| Source | 严格性 | 说明 |
|--------|--------|------|
| `qmt_xtdata` | strict | QMT 本地历史日 K 线 |
| `local_csmar_daily_derived` | strict | CSMAR 个股日交易衍生指标（PE/PB/PS/dividend_yield） |
| `local_csmar_financial_statements` | strict | CSMAR 财务报表（ROE/毛利率/净利率/收入增长/净利润增长/资产负债率/经营现金流质量） |
| `local_csmar_industry_history` | strict | CSMAR 历史行业分类（EndDate <= as_of） |
| `local_csmar_eva_structure_partial` | non-strict | EVA 股本/BPS，仅资本结构补充，不等同盈利质量基本面 |
| `local_csmar_industry_non_strict` | non-strict | 行业分类最新快照 fallback |
| `akshare` | strict | AKShare 东方财富/腾讯/新浪行情 |
| `derived` | 视上下文 | 衍生计算值 |
| `missing` | non-strict | 数据缺失 |

### 使用方式

```python
from services.data.evidence_schema import (
    make_evidence_field,
    is_evidence_field,
    is_strict_source,
    normalize_evidence_field,
    extract_display_value,
    normalize_key_fields,
    validate_evidence_fields,
    summarize_evidence_coverage,
)

# 构造证据字段
ev = make_evidence_field(42, source="qmt_xtdata", as_of="2026-05-01")

# 判断是否为证据字段
is_evidence_field(ev)  # True
is_evidence_field(42)  # False

# 判断 source 是否为严格来源
is_strict_source("qmt_xtdata")                        # True
is_strict_source("local_csmar_eva_structure_partial")  # False

# 标准化（幂等）
normalize_evidence_field(ev)    # 已是 evidence field → 补齐缺失 key
normalize_evidence_field(42)    # 裸值 → 包装为 evidence field

# 提取显示值
extract_display_value(ev)  # 42
extract_display_value(42)  # 42

# 关键字段统一（写入 result["evidence_fields"]，不修改原始裸值）
normalize_key_fields(result)

# 校验 evidence_fields 结构
errors = validate_evidence_fields(result)  # 返回 [{path, error, detail}, ...]

# 汇总覆盖率
summary = summarize_evidence_coverage(result)
# {total_required, covered, missing, coverage_rate, by_source, by_quality, missing_reasons}
```

### 覆盖的字段路径（37 个）

**price_data（8 个）**：`close`, `change_20d`, `change_60d`, `ma20_position`, `ma60_position`, `max_drawdown_60d`, `volatility_60d`, `avg_turnover_20d`

**valuation_data（11 个）**：`pe_ttm`, `pb_mrq`, `ps_ttm`, `dividend_yield`, `market_cap`, `pe_percentile`, `pb_percentile`, `ps_percentile`, `industry_pe_percentile`, `industry_pb_percentile`, `industry_ps_percentile`

**fundamental_data（12 个）**：盈利质量（`roe`, `gross_margin`, `net_margin`, `revenue_ttm`, `net_profit_ttm`, `revenue_growth`, `net_profit_growth`, `debt_ratio`, `operating_cashflow_quality`）+ 资本结构（`total_volume`, `float_volume`, `bps`）

**industry（7 个）**：`industry_code`, `industry_name`, `classification_system`, `peer_count`, `valid_peer_count_pe`, `valid_peer_count_pb`, `valid_peer_count_ps`

**event_data（2 个）**：`recent_news_sentiment`, `policy_risk`

### Source/as_of 推导规则

1. **price_data.\***：source 来自 `source_metadata.price_data`，通常为 `qmt_xtdata`。
2. **valuation_data.pe_ttm/pb_mrq/ps_ttm/dividend_yield**：source 来自 `source_metadata.valuation_data`。
3. **valuation_data.industry_\*_percentile**：优先使用 `valuation_data.industry_percentile_source`。只有 `local_csmar_industry_history` 才能标为 strict。non_strict 时 freshness 为 `estimated` 并加 warning。
4. **fundamental_data 盈利质量字段**：source 来自 `source_metadata.fundamental_source`。EVA partial 不能作为这些字段来源。
5. **fundamental_data 资本结构字段**：source 来自 `source_metadata.capital_structure_source`。EVA partial 可作为资本结构 source。
6. **industry.\***：source 来自 `source_metadata.industry_source`。non_strict 必须带 warning。
7. **event_data.\***：历史样本中缺失时允许，但要有 missing_reason。

### 报告接入

Markdown 报告在 `show_evidence=true` 时展示"数据证据字段摘要"：覆盖率、来源分布、质量分布、主要缺失原因。`show_evidence=false` 时不展示。

### LLM compact context 接入

`compact_research_result_for_llm()` 将 `evidence_fields` 替换为紧凑的 `evidence_summary`（覆盖率、source 分布、最多 15 条 quality_issues），不塞完整 evidence_fields。

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

## P2 Phase 2B：真实 QMT 历史样本池 ✅

### 概述

Phase 2B 将样本来源从 `manual_snapshot` 升级为真实 QMT 历史行情数据 + 本地 CSMAR/EVA/行业库/财务报表。通过 `--use-qmt --require-qmt` 参数，从 MiniQMT 获取真实日 K 线，精确计算 20/60/120 交易日前瞻收益、相对沪深300收益、最大回撤。

当前状态：100 个 `qmt_xtdata` 样本已生成，严格 Phase 2B 验收通过。

**验收结果**：
- 基本面来源覆盖率：100%（阈值 60%）✅
- 行业来源覆盖率：99%（阈值 60%）✅
- 估值来源覆盖率：72%（阈值 60%）✅
- 完整研究输入覆盖率：71%（阈值 50%）✅
- 行业分位有效率：70.71%（阈值 60%）✅
- 评级分桶数：3（阈值 3）✅
- 动作分桶数：3（阈值 3）✅

**数据来源**：
- 价格：`qmt_xtdata`（100%）
- 盈利基本面：`local_csmar_financial_statements`（100%）
- 资本结构：`local_csmar_eva_structure_partial`（100%）
- 估值：`local_csmar_daily_derived`（72%）
- 行业：`local_csmar_industry_history`（99%）

**已知限制**：
- 估值覆盖率 72%：28% 样本因 CSMAR 日衍生指标缺失而无 PE/PB/PS 数据。
- data_complete 覆盖率 71%：要求价格、估值、盈利基本面、行业均满足严格 as_of。
- 行业分位基于历史行业同行池 + CSMAR Daily Derived 月度快照计算，行业分类和同行池按 `as_of` 严格选择。

### 与 Phase 2A 的区别

| 维度 | Phase 2A | Phase 2B |
|------|----------|----------|
| 价格来源 | manual_snapshot | qmt_xtdata |
| forward_metrics | 合理估计值 | 从真实行情精确计算 |
| 基准对比 | 无 | 相对沪深300 (000300.SH) |
| 数据来源证明 | 无 | source_metadata 完整 provenance |
| 资产范围 | 混合 | 沪深主板 A 股 + 边界例外 |
| 基本面/估值 | 手工构造 | 本地 CSMAR 财务报表（100%）+ CSMAR PE/PB/PS（72%）+ 严格历史行业（99%） |

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
  "fundamental_source": "local_csmar_financial_statements",
  "capital_structure_source": "local_csmar_eva_structure_partial",
  "valuation_source": "local_csmar_daily_derived|missing",
  "industry_source": "local_csmar_industry_history|local_csmar_industry_history_non_strict",
  "as_of": "2023-06-30",
  "symbol": "600519.SH"
}
```

**来源说明**：
- `qmt_xtdata`：QMT 历史日 K 线（价格、成交额、forward metrics）
- `local_csmar_financial_statements`：本地 CSMAR 财务报表（ROE/毛利率/净利率/收入增长/净利润增长/资产负债率/经营现金流质量），严格 as_of 可见性规则
- `local_csmar_eva_structure_partial`：CSMAR EVA 股本结构（total_volume/float_volume/market_cap/bps），严格 as_of，但不等同于盈利质量基本面
- `local_csmar_daily_derived`：CSMAR 个股日交易衍生指标（PE/PB/PS/dividend_yield/分位），严格 as_of
- `local_csmar_industry_history`：CSMAR 历史行业分类（DEBT_INSTITUTIONINFO.csv），严格 as_of（EndDate <= as_of），并提供同一历史行业下的同行池
- `local_csmar_industry_history_non_strict`：CSMAR 历史行业分类，fallback（无法验证 as_of）
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
- 行业分位必须来自 `local_csmar_industry_history` 同行池，并在 `valuation_data.industry_percentile_source` 中显式记录
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

# Provider 测试（读取本地 CSV，不需要 QMT）
python -m pytest tests/test_local_csmar_financial_statement_provider.py -q
python -m pytest tests/test_local_csmar_industry_history_provider.py -q

# QMT 集成测试（需要 MiniQMT）
set RUN_HISTORICAL_QMT_BACKTEST=1
python -m pytest tests/test_historical_qmt_integration.py -q
```

### 已知限制

- **估值覆盖率 72%**：28% 样本因 CSMAR 日衍生指标缺失而无 PE/PB/PS 数据，不影响严格验收（阈值 60%）。
- **data_complete 覆盖率 71%**：要求价格、估值、盈利基本面、行业均满足严格 as_of，当前因部分样本估值缺失而未达 100%。
- **行业分位基于历史行业同行池 + CSMAR 日衍生指标计算**：行业分类和同行池严格按 `as_of` 选择，同行 PE/PB/PS 来自 CSMAR Daily Derived 月度快照。
- 2026 年部分 as_of 可能无法获得完整 120 交易日 forward 数据，标记 coverage_gap。
- 688646.SH 作为科创板边界例外，不计入主板覆盖比例。

---

## P2 Phase 3：Evidence Schema 全链路化 ✅

### 概述

Phase 3 将 Phase 1 的基础 evidence schema 升级为覆盖所有关键研究字段的统一证据结构。每个字段都有 `value/source/as_of/quality/warnings`，可追溯来源、日期和质量状态。

### 完成内容

1. **40 个核心字段路径全覆盖**：price_data、fundamental_data、valuation_data、industry、event_data 关键字段均写入 `evidence_fields`。
2. **15 种标准 source 标识**：包括 `qmt_xtdata`、`local_csmar_daily_derived`、`local_csmar_financial_statements`、`local_csmar_industry_history`、`local_csmar_eva_structure_partial`、`derived`、`missing` 等。
3. **7 种 freshness 等级**：`fresh`、`stale`、`historical`、`estimated`、`missing`、`unknown`、`not_applicable`。
4. **strict source 层级**：`is_strict_source()` 区分严格来源和 non-strict 来源（EVA partial、industry non_strict、mock、unknown 等）。
5. **结构化校验**：`validate_evidence_fields()` 返回 `[{path, error, detail}]`。
6. **覆盖率汇总**：`summarize_evidence_coverage()` 输出 total/covered/missing/by_source/by_quality/missing_reasons。
7. **报告接入**：`show_evidence=true` 时展示覆盖率、来源分布、质量分布、缺失原因。
8. **LLM compact context**：`evidence_summary` 替代完整 `evidence_fields`，保持 token 经济性。

### 测试

```bash
python -m pytest tests/test_evidence_schema_contract.py -q
# 47 tests covering make/is/normalize/extract/normalize_key_fields/validate/summarize/strict rules/pipeline
```

### 已知限制

- 估值覆盖率仍为 72%（CSMAR 日衍生指标覆盖），evidence schema 不能弥补数据缺失。
- event_data 在历史样本中统一为 placeholder，有 missing_reason。
- scoring_engine 仍直接读取裸值，未从 evidence_fields 取值（未来质量治理阶段再评估）。
- 不会把 non_strict 数据伪装成 strict evidence。

---

## P2 Phase 4：报告体系产品化 ✅

### 概述

Phase 4 将报告从“函数级模板开关”升级为正式产品化报告体系。Markdown 是内容真源，HTML 和 Playwright PDF 复用同一 Markdown/主题链路，避免多端内容漂移。

### 正式模板

内置模板由 `services/report/template_config.py` 管理：

| 模板 | 用途 | 主要特征 |
|------|------|----------|
| `default` | 默认单机和 API 报告 | 保持原报告结构，展示证据、数据质量、决策保护器和免责声明 |
| `institutional_full` | 长期归档 / 对外审阅 | 完整章节、完整证据摘要、风险降级解释、历史/行业分位解释 |
| `compact_review` | 快速审阅 | 保留结论、行情、评分、风险、保护器和关键证据，省略多空长文 |
| `risk_only` | 风险复核 | 聚焦风险官、保护器、数据质量和免责声明，省略多空叙述与跟踪建议 |

显式传入未知 `report_template` 或 `report_theme` 会抛出错误；API request schema 也会在入口校验，避免生产任务静默回退到错误模板。

### 配置入口

CLI：

```powershell
python main.py --symbol 600519.SH --data-source qmt --report-template institutional_full --report-theme institutional_light
```

FastAPI 异步任务：

```json
{
  "symbol": "600519.SH",
  "data_source": "qmt",
  "use_llm": true,
  "report_template": "compact_review",
  "report_theme": "compact_blue"
}
```

Streamlit 单票研究页侧边栏提供“报告模板”和“报告主题”选择；异步模式会把配置传入 FastAPI，HITL 和同步模式也会复用相同配置生成报告。

### 报告增强内容

Markdown/HTML/PDF 共享以下内容：

- **数据质量摘要**：展示整体置信度、placeholder、阻断项、`evidence_fields` 覆盖率、strict source 覆盖率、来源分布、质量分布和主要缺失原因。
- **证据索引**：列出关键字段路径、展示值、source、as_of、freshness 和 warning/missing reason，优先展示异常字段并限制输出数量。
- **风险降级解释**：说明决策保护器是否启用、是否降级、原始建议/最终建议、最高允许动作和触发原因。
- **历史分位解释**：解释 PE/PB/PS 历史分位、行业分位、同行有效样本和来源；缺失时保留结构化原因，不把 non-strict 数据伪装成 strict。

HTML 生成会转义原始 HTML 标签，PDF 使用 HTML 中的 `@page`、中文字体、表格和分页 CSS，避免 PDF 端另行硬编码版式。

### 测试

```bash
python -m pytest tests/test_report_template_config.py tests/test_report_builders.py tests/test_report_productization_contract.py -q
python -m pytest tests/test_evidence_schema_contract.py tests/test_historical_quality_backtest.py tests/test_historical_samples_contract.py -q
python -m ruff check services/report apps/api/schemas/research.py apps/api/task_manager/celery_tasks.py apps/dashboard/components/progress_poller.py apps/dashboard/pages/1_Single_Asset_Research.py main.py tests/test_report_productization_contract.py
```

### 仍不属于 Phase 4 的事项

- 评分漂移治理、阈值版本化和定期质量看板，保留在 Phase 6。

---

## P2 Phase 5：真实网页新闻/舆情长期监控 ✅

### 概述

Phase 5 将 Phase 1 的离线新闻质量样本升级为真实 provider 长期稳定性监控。对 10 个核心 A 股标的运行真实 WebNewsProvider 抓取，按 provider/source 维度评估稳定性，输出结构化 artifact。

### 核心模块

- `services/data/news_quality_monitor.py`：监控核心模块，复用 WebNewsProvider 和 news_quality.py
- `configs/web_news_quality_targets.json`：10 个核心标的配置
- `scripts/run_web_news_quality_monitor.py`：监控脚本，支持离线 fixture 和真实网络两种模式

### 运行方式

```bash
# 离线 fixture 模式（不发网络请求）
python scripts/run_web_news_quality_monitor.py \
    --offline-fixture tests/fixtures/web_news_quality_samples.json \
    --output-dir storage/artifacts/web_news_quality/live_test

# 真实网络模式
python scripts/run_web_news_quality_monitor.py \
    --targets configs/web_news_quality_targets.json \
    --sources eastmoney,sina,xinhuanet,hotrank,baidu \
    --lookback-days 14 --limit 5 --timeout-seconds 8 --max-seconds 15 \
    --output-dir storage/artifacts/web_news_quality/live

# 带阈值检查
python scripts/run_web_news_quality_monitor.py --fail-on-threshold
```

### 监控指标

| 指标 | 说明 |
|------|------|
| success_rate | provider 成功率 |
| timeout_rate | 超时率 |
| empty_rate | 空结果率 |
| relevance_rate | 相关性率（去重后条目中与标的相关的比例） |
| low_quality_rate | 低质量率 |
| avg_latency_seconds | 平均延迟 |
| duplicate_rate | 去重率（单次抓取内） |

### 默认阈值

| 阈值 | 默认值 | 说明 |
|------|--------|------|
| min_success_rate | 0.50 | 最低成功率 |
| max_timeout_rate | 0.50 | 最高超时率 |
| max_empty_rate | 0.70 | 最高空结果率 |
| min_relevance_rate | 0.20 | 最低相关性率 |
| max_low_quality_rate | 0.60 | 最高低质量率 |
| max_avg_latency_seconds | 15.0 | 最高平均延迟 |

### 状态分级

- `ok`：所有指标在阈值范围内
- `warn`：空结果率、相关性率或低质量率超出阈值
- `fail`：成功率、超时率或延迟超出阈值

### Artifact 输出

| 文件 | 说明 |
|------|------|
| `latest.json` | 最新运行完整报告 |
| `latest.md` | 最新运行 Markdown 报告 |
| `history.jsonl` | 历史运行摘要（每行一次运行） |
| `provider_health.json` | 按 provider 聚合的健康统计 |
| `manual_review_candidates.jsonl` | 需要人工复核的新闻样本 |

### 核心标的池（10 只）

600519.SH 贵州茅台、000001.SZ 平安银行、000002.SZ 万科A、600036.SH 招商银行、601318.SH 中国平安、601398.SH 工商银行、600030.SH 中信证券、600276.SH 恒瑞医药、000858.SZ 五粮液、601888.SH 中国中免

### 人工抽样候选

`manual_review_candidates.jsonl` 包含以下类型：
- 低相关但被判 high tier
- 高相关但低质量
- provider 返回但无公司名/代码命中

字段：`run_id`, `symbol`, `provider`, `title`, `url`, `summary`, `published_at`, `relevance`, `quality_tier`, `reasons`, `review_label`, `reviewer_notes`

### 测试

```bash
# 离线单元测试
python -m pytest tests/test_web_news_quality_monitor.py -q
# 33 tests covering thresholds/health/classify/fixture/mock-provider/artifacts

# 已有测试（不应被破坏）
python -m pytest tests/test_web_news_quality_contract.py tests/test_web_news_provider.py -q

# 真实网络 smoke（默认跳过）
RUN_WEB_NEWS_NETWORK=1 python -m pytest tests/integration/test_web_news_quality_monitor_live.py -q
```

### 已知限制

- 真实新闻 provider 天然不稳定，部分来源在特定网络环境下可能全部失败。
- 不会把空新闻结果解释为"无负面舆情"的强结论。
- 人工抽样候选只生成样本文件，不包含人工标注 UI。
- 默认脚本不阻断主研究链路；只有 `--fail-on-threshold` 才以阈值决定 exit code。
