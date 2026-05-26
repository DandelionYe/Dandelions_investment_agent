# Dandelions 后续开发报告

本文件只记录 README 已覆盖能力之外的未完成事项和后续开发顺序。已落地、已能运行或已在 README 中说明的能力，不再在这里重复维护。

## 维护口径

- 不再沿用旧版 `report.md` 的版本完成度、历史模块清单和百分比。
- README 是当前可运行能力的说明入口；本文件只作为 backlog 和验收提醒。
- MiniQMT 数据同步保持手工运维步骤，不单独开发模块。当前使用的增量命令为：

```powershell
robocopy "D:\迅投QMT极速交易系统交易终端 万联证券版\datadir" "D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir" /E /XC /XN /XO /R:1 /W:1 /COPY:DAT /DCOPY:DAT /MT:8
```

## 当前结论

围绕 `Industriy_plan.md` 推进的行业估值、QMT 缓存预检、同行 K 线补齐、本地 CSMAR 行业库、本地 EVA 股本/市值、本地 CSMAR 日衍生指标 fallback、缺失原因披露和 LLM 输入瘦身，已可视为落地。后续开发重点不应继续堆数据 fallback，而应转向真实运行验收、生产安全边界和研究质量验证。

## 后续开发优先级

| 优先级 | 开发项 | 当前状态 | 推进理由 |
|---|---|---|---|
| P0 | 运行态集成验收与 CI 服务矩阵 | 已有 `docs/verification.md`、`docs/integration_testing.md` 和 opt-in live 测试，但需要形成稳定验收流程 | 外部依赖较多，必须确认 FastAPI、Celery/Redis、WebSocket、QMT、AKShare、PDF、Streamlit 在真实环境中可复现运行 |
| P0 | 真实数据质量回归样本集 | 部分手工验证已完成，但缺少固定样本基线 | 防止 QMT 缓存、CSMAR 快照、EVA 股本、AKShare fallback 或 missing_reason 在后续修改中漂移 |
| P1 | 观察池条件触发器真实行情验收 | 代码和测试存在，但仍偏单元层 | 观察池是持续使用入口，需要验证真实行情、批量扫描、进度推送和报告生成链路 |
| P1 | 生产部署与运维安全 | 开发环境启动脚本已存在，生产部署体系不足 | Redis/Celery 持久化、日志、备份、密钥、进程守护、异常恢复需要明确方案 |
| P1 | 多用户隔离与 RBAC | ✅ 已完成 | owner_username 隔离、RBAC helper、API/Streamlit/存储层统一权限、57 项 RBAC 测试 |
| P2 | 历史回测与压力测试 | ✅ Phase 2B 已完成：100 个 QMT 历史样本、本地 CSMAR 财报、历史行业库、严格 as_of、质量阈值和 artifact 均已落地 | 后续重点转向 evidence 全链路化和质量基线治理 |
| P2 | 报告模板体系升级 | 当前 Markdown/HTML/PDF 可用，但模板能力有限 | 后续若需要更正式的机构报告，应引入更清晰的模板、版式和主题配置 |
| P2 | 数据证据结构进一步统一 | 已有 evidence bundle 和 provider 日志，但并非所有字段都严格统一 | 长期需要把关键字段稳定表达为 value/source/as_of/quality/warnings，方便审计和调试 |
| P2 | 网页新闻/舆情长期质量验收 | provider 已有，网络 smoke 已有 | 需要持续观察来源稳定性、去重质量、相关性过滤和反爬失败表现 |
| P3 | 系统设置页面 | 尚未实现完整 UI | 可把环境配置、数据源开关、LLM 模型、报告选项从 `.env` 部分迁移到可视化配置 |
| P3 | 组合优化 / 多资产配置 | 尚未实现 | 当前以单票研究为核心，组合层能力属于扩展项 |
| P4 | Qlib 接入 | 尚未实现 | 价值取决于后续是否需要模型训练、因子研究和批量回测，不是当前主链路必需项 |
| P4 | 自动交易 / QMT 下单 | 当前明确不自动下单 | 必须等权限隔离、审计、风控和人工确认链路充分成熟后再考虑 |

## P0：运行态集成验收与 CI 服务矩阵

目标：把“能启动、能联通、能生成报告”变成可重复验证流程。

需要覆盖：

- FastAPI 健康检查、认证、任务提交、报告读取。
- Celery worker、Celery Beat、Redis 队列和任务状态流转。
- WebSocket 任务进度推送。
- Streamlit 登录、单票研究、异步任务、报告库、观察池页面。
- QMT 本地接口、AKShare 网络 fallback、PDF 生成。
- 默认 CI 只运行稳定离线测试；真实环境测试保留为手动或计划任务触发。

验收标准：

- 文档中给出一套从启动服务到完成 smoke 的命令顺序。
- `tests/integration/` 的 live 测试能按环境变量分组运行。
- CI 明确区分离线必跑测试和外部依赖测试。
- 每次关键发布前能留下可复现的本地验收记录。

## P0：真实数据质量回归样本集 ✅

目标：固定一组代表性股票，用于检测数据源和 fallback 行为是否符合预期。

建议样本：

- 财务和行情缓存较完整的大市值股票。
- QMT 股本缺失但 EVA 可补齐的股票。
- CSMAR 日衍生指标可补股息率或估值分位的股票。
- 停牌、亏损、收入缺失、BPS 异常、上市时间较短的边界样本。
- 行业同行样本不足或预检失败的样本。

验收标准：

- 每个样本记录预期字段、预期来源和允许缺失原因。
- 输出报告中的 PE、PB、PS、股息率、历史分位、行业分位与 `*_missing_reason` 可被回归检查。
- 不要求数值永久不变，但要求来源链路和缺失解释稳定。

## P1：观察池条件触发器真实行情验收

目标：确认观察池不是只能 CRUD，而是能在真实数据下完成批量扫描和条件触发。

需要验证：

- 价格、涨跌幅、估值、评分、风险、事件类条件是否能被实际触发。
- 批量扫描时任务状态、进度推送、失败项记录是否稳定。
- 扫描结果是否能正确关联到报告库和用户数据。

验收标准：

- 至少准备一个小型观察池样本，覆盖触发和未触发两类结果。
- 扫描结果可复现，并能解释数据来源。
- 单个标的失败不影响整批任务完成。

## P1：生产部署与运维安全 ✅

目标：让当前开发环境服务具备可长期运行的部署说明。

需要补齐：

- Redis、Celery worker、Celery Beat、FastAPI、Streamlit 的进程守护方式。
- 日志目录、报告目录、运行态 SQLite/缓存目录的备份和清理策略。
- `.env`、JWT secret、DeepSeek key、QMT 路径等敏感配置管理。
- 服务异常退出、Redis 不可用、QMT 未启动、PDF 渲染失败时的恢复流程。

验收标准：

- 能在一台 Windows 工作站上按文档完成部署和重启。
- 明确哪些目录必须备份，哪些目录可以清理。
- 生产配置与开发配置有清晰边界。

## P1：多用户隔离与 RBAC ✅

已在 JWT 基础上完成多用户数据隔离和 RBAC。详见 `docs/rbac_multi_user.md`。

完成内容：

- watchlist_folders/items/tags/batches 新增 `owner_username` 字段，按 owner 隔离。
- research_tasks 的 `created_by` 字段用于任务隔离。
- RBAC helper (`apps/api/auth/rbac.py`)：`is_admin()`、`scope_username()`、`require_owner_or_admin()`。
- API 路由统一权限语义：普通用户 404、管理员可跨用户访问。
- WebSocket 端点增加 owner 校验，`/ws/events` 仅管理员可用。
- 管理员用户管理接口：`GET /users`、`PATCH /users/{id}`。
- Streamlit 报告库改用 API 而非直接文件扫描。
- 观察池本地 fallback 默认关闭（需 `STREAMLIT_LOCAL_STORE_FALLBACK=true`）。
- 57 项 RBAC 测试覆盖任务/观察池/报告/WebSocket/管理员接口/迁移。
- 旧数据幂等迁移，归属 `'default'` owner。

## P2：研究质量与报告能力（第一阶段已完成）✅

详见 `docs/research_quality_and_reports.md`。

已完成：

1. 历史回测与压力测试：8 个离线样本覆盖高质量低估值、高估值趋势强、大回撤高波动、亏损PE无效、行业样本不足、critical事件、placeholder阻断、ETF无基本面。脚本 `scripts/run_research_quality_backtest.py` 输出 JSON/Markdown artifact。
2. 报告模板体系升级：`ReportTemplateConfig` 支持章节开关（evidence/data_quality/decision_guard/disclaimer）、3 个内置主题（institutional_light/dark/compact_blue）。`build_markdown_report` 和 `build_html_report` 向后兼容。
3. 数据证据结构统一：`evidence_schema.py` 提供 `make_evidence_field`/`is_evidence_field`/`normalize_evidence_field`/`extract_display_value`/`normalize_key_fields`。覆盖 17 个关键字段路径，不修改原始裸值。
4. 网页新闻/舆情质量验收：`news_quality.py` 提供去重、相关性评分、质量分类、provider 结果评估、汇总。7 个离线样本覆盖相关新闻、重复、低质量、不相关热榜、provider 失败/超时。脚本 `scripts/run_web_news_quality_check.py` 输出 JSON/Markdown artifact。

`第一阶段已完成` 不等于 `P2 完全落地`。

现在完成的是“离线契约与基础设施”：有样本、有脚本、有模板配置、有 evidence schema、有新闻质量评估函数。它能防止明显回归，但还不能证明真实行情、真实新闻、真实报告生产长期可靠。

我建议后续按这几阶段推进：

**P2 第二阶段：真实历史回测落地** ✅

已完成：

1. 100 个真实 QMT 价格样本已生成，价格来源为 `qmt_xtdata`，覆盖 2021-2025，13 个边界股票全部纳入，`688646.SH` 标记为 `out_of_scope_exception`。
2. 所有 QMT 样本包含完整的 `forward_metrics`：20/60/120 日收益、沪深300基准收益、相对收益、最大回撤。
3. `historical_sample_builder.py` 实现 MiniQMT 历史行情构建、主板 scope 过滤、边界股票处理和样本级 provenance。
4. `build_historical_research_samples.py` 支持 `--use-qmt --require-qmt --asset-scope mainboard-a`，已有 fixture 时不会在 require-qmt 模式下假成功。
5. `run_historical_research_quality_backtest.py` 区分严格 Phase 2B 验收和 `--allow-price-only` smoke 验收，默认严格验收会暴露缺口。
6. 验收阈值新增基本面/估值/行业来源覆盖率、完整研究输入覆盖率、placeholder/critical 实际样本数，避免无样本时命中率虚高。
7. 离线测试覆盖 schema、benchmark return、样本级 source、out-of-scope 例外、strict-vs-price-only 验收。
8. **CSMAR Daily Derived 接入完成**：`get_as_of_metrics()` 严格查询 `monthly_snapshots` 中 `trading_date <= as_of` 的最近记录，填充 PE/PB/PS/dividend_yield 及历史分位。72/100 样本获得 CSMAR 估值数据。
9. **EVA Structure 接入完成**：`get_as_of_share_capital()` 严格查询 `eva_structure_history` 中 `end_date <= as_of` 的最近记录，填充 total_volume/float_volume/market_cap/bps。100/100 样本获得 EVA 股本/BPS 数据，但不计入盈利质量基本面覆盖率。
10. **本地 CSMAR 财务报表接入完成**：`LocalCSMARFinancialStatementProvider` 读取 `FS_Comins.csv`、`FS_Comscfd.csv`、`FS_Comscfi.csv`、`FS_Combas.csv`，实现严格 as_of 可见性规则（年报次年 04-30 后可用，一季报当年 04-30 后可用，半年报当年 08-31 后可用，三季报当年 10-31 后可用），计算 TTM、同比增长、ROE、毛利率、净利率、资产负债率、经营现金流质量。100/100 样本获得盈利质量基本面数据。
11. **本地 CSMAR 历史行业库接入完成**：`LocalCSMARIndustryHistoryProvider` 读取 `DEBT_INSTITUTIONINFO.csv`，支持坏行容错、按 `EndDate <= as_of` 取最近历史行业记录、2021-2022 优先 P0207、2023+ 优先 P0221。99/100 样本获得严格历史行业分类。
12. **严格 Phase 2B 验收通过**：基本面来源覆盖率 100%、严格行业来源覆盖率 99%、估值来源覆盖率 72%、完整研究输入覆盖率 71%、严格行业分位有效率 70.71%、评级分桶数 3、动作分桶数 3。
13. **严格行业分位修复完成**：行业分位必须带有 `industry_percentile_source = local_csmar_industry_history` 才计入严格验收；旧的 latest-snapshot 行业分位只作为诊断，不再被误计入 strict。

验收结果：

| 指标 | 阈值 | 实际值 | 状态 |
|------|------|--------|------|
| 基本面来源覆盖率 | ≥ 60% | 100% | ✅ |
| 行业来源覆盖率 | ≥ 60% | 99% | ✅ |
| 估值来源覆盖率 | ≥ 60% | 72% | ✅ |
| 完整研究输入覆盖率 | ≥ 50% | 71% | ✅ |
| 行业分位有效率 | ≥ 60% | 70.71% | ✅ |
| 评级分桶数 | ≥ 3 | 3 | ✅ |
| 动作分桶数 | ≥ 3 | 3 | ✅ |

已确认推进口径：

- 运行环境以 XtMiniQMT 后台登录为前提；不要求额外开发或调用完整 QMT 客户端。
- 完整 QMT 到 MiniQMT 的数据补充继续作为手工运维动作，通过本文开头记录的 `robocopy` 命令同步 `datadir`，不纳入自动化开发范围。
- Phase 2B 不接入 QMT financial 下载/补充流程；EVA 只作为股本/BPS/资本结构来源，不伪装为 ROE、毛利率、利润增速等盈利质量基本面。
- 历史样本采用严格 as_of 口径：只能使用 `as_of` 当日或之前已经可见的数据。
- 样本范围聚焦 A 股沪深主板上市公司，时间范围 2021-2026，基准为沪深300；ETF、北交所、港股通不作为本阶段范围。
- 历史回测模块不依赖历史新闻倒查；新闻/舆情 provider 的长期质量验收仍保留在 P2 第五阶段，不作为 Phase 2B 的阻塞项。

已知限制：

- **估值覆盖率 72%**：28% 样本因 CSMAR 日衍生指标缺失而无 PE/PB/PS 数据，不影响严格验收（阈值 60%）。
- **data_complete 覆盖率 71%**：要求价格、估值、盈利基本面、行业均满足严格 as_of，当前因部分样本估值缺失而未达 100%。
- **行业分位基于历史行业同行池 + CSMAR 日衍生指标计算**：行业分类和同行池严格按 `as_of` 选择，同行 PE/PB/PS 来自 CSMAR Daily Derived 月度快照。
- **688646.SH 仍为科创板例外**：不计入主板覆盖率统计。

**P2 第三阶段：Evidence Schema 全链路化** ✅

目标：从”新增 `evidence_fields`”升级为”所有关键字段都有可信证据链”。

已完成：

1. **统一 Evidence Field 结构**：`evidence_schema.py` 中 `make_evidence_field()` 生成规范结构 `{value, source, as_of, quality{available, confidence, freshness, missing_reason}, warnings}`。新增 `qmt_xtdata`、`local_csmar_daily_derived`、`local_csmar_financial_statements`、`local_csmar_industry_history`、`local_csmar_eva_structure_partial`、`derived`、`missing` 等标准 source 标识。新增 `estimated`、`historical`、`missing` freshness 等级。
2. **关键字段全覆盖**：`normalize_key_fields()` 现在覆盖 37 个字段路径，包括 price_data(8)、fundamental_data(9，含 capital structure)、valuation_data(8，含 industry percentile)、industry(7)、event_data(2)。
3. **source/as_of 推导规则**：行业分位优先使用 `valuation_data.industry_percentile_source`，只有 `local_csmar_industry_history` 才标为 strict/high confidence；`local_csmar_industry_non_strict` 必须带 warning。EVA partial 只作为 capital structure source，不作为盈利质量来源。
4. **validate_evidence_fields()**：返回结构化错误列表 `{path, error, detail}`，检查缺字段、结构非法、source 缺失、confidence 越界、available/missing_reason 不一致、warnings 类型。
5. **summarize_evidence_coverage()**：输出 total_required/covered/missing/coverage_rate/by_source/by_quality/missing_reasons。
6. **报告接入**：Markdown 报告在 `show_evidence=true` 时展示”数据证据字段摘要”，包含覆盖率、来源分布、质量分布、主要缺失原因。`show_evidence=false` 时不展示。
7. **LLM compact context 接入**：`compact_research_result_for_llm()` 将 `evidence_fields` 替换为紧凑的 `evidence_summary`，包含覆盖率、source 分布、最多 15 条 quality_issues，不塞完整 evidence_fields。
8. **测试覆盖**：47 项 evidence schema 套约测试通过，覆盖 make/is/normalize/extract/normalize_key_fields/validate/summarize/strict source 规则/pipeline 集成。

验收标准：
- 关键字段 evidence 覆盖率 ≥ 90%（37 个核心字段路径）。
- evidence_fields 不破坏原始裸值结构。
- source/as_of/quality/warnings/missing_reason 可被测试验证。
- 报告展示 evidence 摘要并受 show_evidence 控制。
- LLM compact context 携带简洁 source/quality 信息。
- Phase 2B strict backtest 仍通过。

已知限制：
- 估值覆盖率仍为 72%（CSMAR 日衍生指标覆盖），evidence schema 不能弥补数据缺失。
- event_data 在历史样本中统一为 placeholder（Phase 2B 不依赖历史新闻倒查），有 missing_reason。
- scoring_engine 仍直接读取裸值，未从 evidence_fields 取值（未来 Phase 4 可考虑）。

**P2 第四阶段：报告体系产品化**
目标：从“模板开关可用”升级为“报告可长期对外/归档使用”。

需要推进：
- 定义正式模板版本，例如 `default`, `institutional_full`, `compact_review`, `risk_only`。
- Markdown/HTML/PDF 三端版式一致，PDF 分页、表格、中文字体、页眉页脚稳定。
- 报告配置进入任务参数或环境配置，而不是只能函数调用传参。
- 报告中增加“证据索引”“数据质量摘要”“风险降级解释”“历史分位解释”。
- 给报告生成做视觉/内容快照测试，避免格式漂移。

验收标准：
- 同一结果生成 Markdown/HTML/PDF 内容一致。
- 模板变更有快照测试保护。
- 报告能清楚解释评分、估值、保护器和数据质量。

**P2 第五阶段：真实网页新闻/舆情长期验收**
目标：从“离线新闻样本”升级为“真实 provider 稳定性监控”。

需要推进：
- 定时对核心标的池运行真实新闻抓取验收。
- 统计成功率、超时率、重复率、相关性、低质量占比、平均延迟。
- 对 Eastmoney/其它来源分别记录 provider health。
- 建立去重/相关性人工抽样评估集，持续调阈值。
- provider 失败时验证报告能降级，而不是产生误导性舆情结论。

验收标准：
- 连续运行若干天后有趋势 artifact。
- provider 不可用不会中断研究主链路。
- 新闻相关性和去重质量有量化指标。

**P2 第六阶段：研究质量治理**
目标：让 P2 成为持续质量体系，而不是一次性功能。

需要推进：
- 建立 `research_quality_baseline.json`，保存关键指标基线。
- 每次评分、估值、报告、provider 改动后能比较质量漂移。
- 把失败样本分级：阻断、警告、观察。
- 维护真实样本扩充流程：新增 bug case 后必须沉淀为 fixture。
- 明确哪些检查进默认测试，哪些 opt-in 运行。

总结：现在 P2 已经完成“第一阶段基础框架”和“第二阶段真实历史回测样本池”。后续还需要重点推进全链路 evidence、报告产品化、真实新闻长期监控和质量基线治理。下一步最值得做的是“Evidence Schema 全链路化”，因为 Phase 2B 已经证明历史样本能跑通，下一层风险在字段级证据、质量和报告解释是否一致。


## P3/P4：可延后事项

- 系统设置页面：适合在配置项继续增多后再做。
- 组合优化 / 多资产配置：适合在单票研究和观察池稳定后推进。
- Qlib：只有在需要因子研究、模型训练或批量回测时再接入。
- 自动交易 / QMT 下单：当前不建议推进。至少应等权限隔离、审计、人工确认、风控限额和异常回滚机制成熟后再讨论。
