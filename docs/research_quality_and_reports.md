# P2：研究质量与报告能力

## 范围

P2 分为多个阶段推进：

| 阶段 | 目标 | 状态 |
|------|------|------|
| Phase 1 | 8 个离线构造样本 + 报告模板 + evidence schema + 新闻质量 | ✅ 已完成 |
| Phase 2 | 50+ 真实历史样本池 + 可重复质量报告 + 验收阈值 | ✅ 已完成 |
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

## P2 Phase 2：真实历史回测落地

### 概述

Phase 2 将 Phase 1 的 8 个离线构造样本升级为 52 个基于公开行情模式的真实历史快照样本，覆盖 10+ 场景标签，并提供可配置验收阈值和结构化质量报告。

### 与 Phase 1 的区别

| 维度 | Phase 1 | Phase 2 |
|------|---------|---------|
| 样本数 | 8 | 52 |
| 样本来源 | 手工构造 | 基于公开行情模式的固定快照 |
| 场景覆盖 | 8 个场景 | 13 个场景标签 |
| forward metrics | 部分样本有 | 所有样本都有 20/60/120 日收益和回撤 |
| 验收阈值 | 通过/失败二元 | 8 个可配置阈值指标 |
| 质量报告 | 基础表格 | 场景覆盖矩阵、分桶分析、维度统计 |

### 运行方式

```bash
# 构建样本（默认 dry-run，不覆盖 fixture）
python scripts/build_historical_research_samples.py

# 覆盖 fixture
python scripts/build_historical_research_samples.py --overwrite

# 尝试 QMT 真实数据（opt-in）
python scripts/build_historical_research_samples.py --use-qmt --overwrite

# 运行历史回测
python scripts/run_historical_research_quality_backtest.py

# 自定义阈值
python scripts/run_historical_research_quality_backtest.py --thresholds path/to/thresholds.json

# 探索模式（阈值失败不返回 exit code 1）
python scripts/run_historical_research_quality_backtest.py --no-fail-on-threshold
```

输出：
- `storage/artifacts/research_quality/historical_backtest_summary.json`
- `storage/artifacts/research_quality/historical_backtest_report.md`

### 样本 Fixture Schema

```json
{
  "version": 1,
  "generated_at": "ISO datetime",
  "source": {
    "price": "manual_snapshot",
    "fundamental": "manual_snapshot",
    "valuation": "manual_snapshot",
    "industry": "manual_snapshot"
  },
  "samples": [
    {
      "sample_id": "string",
      "symbol": "600519.SH",
      "name": "贵州茅台",
      "asset_type": "stock|etf",
      "as_of": "YYYY-MM-DD",
      "scenario_tags": ["stock", "large_cap", "earnings_window"],
      "industry": {
        "level": "SW1|SW2|unknown",
        "name": "string|null",
        "peer_count": 0,
        "valid_peer_count_pe": 0,
        "valid_peer_count_pb": 0,
        "valid_peer_count_ps": 0
      },
      "input_result": {
        "asset_type": "stock",
        "price_data": { "..." },
        "fundamental_data": { "..." },
        "valuation_data": { "..." },
        "event_data": { "..." },
        "source_metadata": {},
        "data_quality": { "..." }
      },
      "forward_metrics": {
        "return_20d": 0.0,
        "return_60d": 0.0,
        "return_120d": 0.0,
        "relative_return_20d": 0.0,
        "relative_return_60d": 0.0,
        "relative_return_120d": 0.0,
        "max_drawdown_20d": 0.0,
        "max_drawdown_60d": 0.0,
        "max_drawdown_120d": 0.0
      },
      "expected": { "..." },
      "quality": {
        "is_real_historical_sample": true,
        "data_complete": true,
        "known_limitations": []
      }
    }
  ]
}
```

### 场景覆盖矩阵

| 场景标签 | 说明 | 样本数 |
|---------|------|-------|
| stock | 股票样本 | 45 |
| etf | ETF 样本 | 7 |
| large_cap | 大盘蓝筹 | 20+ |
| small_or_mid_cap | 中小盘 | 10+ |
| earnings_window | 财报窗口 | 8 |
| low_valuation | 低估值 | 5+ |
| bear_market | 熊市 | 6+ |
| extreme_drawdown | 极端下跌 | 5+ |
| high_volatility | 高波动 | 5+ |
| loss_making_or_invalid_pe | 亏损/PE无效 | 3 |
| missing_fundamental | 缺失基本面 | 3 |
| industry_insufficient_peers | 行业样本不足 | 4 |
| defensive | 防御型 | 2+ |

### 验收阈值

```python
DEFAULT_ACCEPTANCE_THRESHOLDS = {
    "min_samples": 50,
    "max_aggressive_action_rate_for_high_risk": 0.0,
    "min_placeholder_guard_hit_rate": 1.0,
    "min_critical_guard_hit_rate": 1.0,
    "min_industry_percentile_valid_rate": 0.60,
    "max_single_score_bucket_ratio": 0.70,
    "min_rating_bucket_count": 3,
    "min_action_bucket_count": 3,
}
```

**阈值说明：**

- `min_samples`: 最少样本数，确保统计显著性。
- `max_aggressive_action_rate_for_high_risk`: 高风险场景下激进建议违规率必须为 0。
- `min_placeholder_guard_hit_rate`: placeholder 数据必须被保护器限制。
- `min_critical_guard_hit_rate`: critical 事件必须被保护器强制回避。
- `min_industry_percentile_valid_rate`: 至少 60% 的非行业样本不足样本有有效行业分位。
- `max_single_score_bucket_ratio`: 单一评分分桶占比不超过 70%，防止评分集中。
- `min_rating_bucket_count`: 至少覆盖 3 种评级。
- `min_action_bucket_count`: 至少覆盖 3 种动作。

### 测试

```bash
# Phase 2 新增测试
python -m pytest tests/test_historical_quality_backtest.py -q
python -m pytest tests/test_historical_samples_contract.py -q

# Phase 1 测试（不应被破坏）
python -m pytest tests/test_research_quality_backtest.py -q
python -m pytest tests/test_evidence_schema_contract.py -q
python -m pytest tests/test_report_template_config.py -q
```

### 已知限制

- 当前 52 个样本基于公开行情模式的手动快照，非 QMT 真实数据。
- `forward_metrics` 为基于历史走势的合理估计值，非精确计算。
- 行业分位数据基于行业平均水平，非逐只计算。
- 部分北交所样本行业分位不可用（样本不足）。
- 如需真实 QMT 数据，使用 `--use-qmt` 参数（需 MiniQMT 运行）。

### 后续事项

- 接入真实 QMT 历史数据替换手动快照。
- 增加 120 日 forward return 分析。
- 建立季度回归机制，检测评分漂移。
- 扩展样本覆盖：更多北交所、港股通、行业 ETF。
- 真实网络新闻 provider 长期稳定性监控。
- 行业轮动场景下的估值分位漂移检测。
