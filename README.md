# Dandelions Investment Agent

投研智能体 MVP：输入单只沪深京 A 股或 ETF，输出量化评分、多头/空头/风险官辩论、最终建议，以及 JSON/Markdown/HTML/PDF 报告。

## 当前边界

- 主数据源：QMT/xtquant，本地 Windows 环境优先。
- fallback 数据源：AKShare，只在 QMT 不可用或调试时使用。
- 离线测试数据源：mock。
- LLM：DeepSeek OpenAI-compatible API。
- 看板：Streamlit。
- 报告：JSON -> Markdown -> HTML -> Playwright PDF。
- 当前不会自动下单，也不会调用 QMT 交易接口。

## 环境准备

建议使用 Windows 原生 Python 3.11+。项目当前在 Python 3.13 环境下做过基础验证。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写 `DEEPSEEK_API_KEY`。不要提交 `.env`，它已在 `.gitignore` 中排除。

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
python -m pytest
```

测试覆盖当前最小闭环：mock 主流程、AKShare 行情转换、评分协议、decision_guard、JSON/Markdown/HTML 报告生成。

## 数据可信度

当前 QMT 和 AKShare provider 只负责行情、成交额和基础信息。基本面、估值、事件字段在真实数据源接入前由 `services/data/supplemental_provider.py` 补低置信度占位数据，并在 `source_metadata` 中标记为 `mock_placeholder`。报告和 LLM 输入必须保留这些来源标记。
