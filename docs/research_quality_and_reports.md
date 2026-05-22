# P2：研究质量与报告能力

## 范围

P2 第一阶段覆盖四个方向：

1. **历史回测与压力测试** — 离线验证评分、估值分位、决策保护器表现。
2. **报告模板体系升级** — 模板配置、主题切换、章节开关。
3. **数据证据结构统一** — 关键字段统一为 `value/source/as_of/quality/warnings`。
4. **网页新闻/舆情质量验收** — 离线去重、相关性、低质量过滤、失败降级。

## 1. 历史回测与压力测试

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

## 后续事项

本阶段不承诺收益预测准确性，只验证评分/估值/保护器/数据证据/新闻质量链路的一致性和防退化。

以下内容仍属于后续真实数据/长期运行验证：
- 真实 QMT 历史行情回测
- 真实网络新闻 provider 长期稳定性监控
- 行业轮动场景下的估值分位漂移
- 极端行情下的评分/保护器边界行为
