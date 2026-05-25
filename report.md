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
| P2 | 历史回测与压力测试 | 进行中：QMT 价格、CSMAR 估值、EVA 股本/BPS 的严格 as_of 已落地；历史行业库、利润表、现金流量表等本地 CSMAR 原始数据已补充，剩余工作转为代码接入和验收恢复 | 行业估值、评分、决策保护器需要用历史样本验证稳定性，尤其是极端行情和行业轮动场景 |
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

**P2 第二阶段：真实历史回测落地** 进行中

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
10. **行业库接入完成但非严格**：`LocalCSMARIndustryProvider.resolve_industry()` 可提供行业分类和同行列表，用于诊断性计算行业 PE/PB/PS 分位；由于本地行业库只有 2026-05-20 单一快照，2021-2025 样本行业来源全部为 `local_csmar_industry_non_strict`。
11. 严格 Phase 2B 验收已恢复真实阈值，当前应失败而不是假通过：基本面来源覆盖率 0%、严格行业来源覆盖率 0%、严格行业分位有效率 0%、完整研究输入覆盖率 0%。

已确认推进口径：

- 运行环境以 XtMiniQMT 后台登录为前提；不要求额外开发或调用完整 QMT 客户端。
- 完整 QMT 到 MiniQMT 的数据补充继续作为手工运维动作，通过本文开头记录的 `robocopy` 命令同步 `datadir`，不纳入自动化开发范围。
- Phase 2B 不接入 QMT financial 下载/补充流程；EVA 只作为股本/BPS/资本结构来源，不伪装为 ROE、毛利率、利润增速等盈利质量基本面。
- 历史样本采用严格 as_of 口径：只能使用 `as_of` 当日或之前已经可见的数据。
- 样本范围聚焦 A 股沪深主板上市公司，时间范围 2021-2026，基准为沪深300；ETF、北交所、港股通不作为本阶段范围。
- 历史回测模块不依赖历史新闻倒查；新闻/舆情 provider 的长期质量验收仍保留在 P2 第五阶段，不作为 Phase 2B 的阻塞项。

未完成/阻塞：

- **数据文件已补充，剩余主要是代码层面接入**：`data/raw/csmar/industry_history/Basic Information Table/DEBT_INSTITUTIONINFO.csv` 可提供历史行业分类；`data/raw/csmar/financial_statements/Income Statement/FS_Comins.csv`、`Cash Flow Statement (Direct Method)/FS_Comscfd.csv`、`Cash Flow Statement (Indirect Method)/FS_Comscfi.csv`、`Balance Sheet/FS_Combas.csv` 可提供公司级利润、现金流和资产负债数据。
- **严格行业来源覆盖率当前仍为 0%**：现有代码仍在使用单一快照行业 provider，尚未接入 `DEBT_INSTITUTIONINFO.csv`。该 CSV 有一行地址字段引号异常，读取时需要容错或预清洗。
- **盈利质量基本面覆盖率当前仍为 0%**：现有代码仍未从利润表、现金流量表、资产负债表推导 ROE、毛利率、净利率、收入增长、净利润增长、经营现金流质量、资产负债率等字段。
- **严格 as_of 披露口径需要代码实现**：这些财报文件中的 `DeclareDate` 字段为“差错更正披露日期”，不能直接作为普通财报公告日。代码应采用保守可见规则：年报下一年 04-30 后可用，一季报当年 04-30 后可用，半年报当年 08-31 后可用，三季报当年 10-31 后可用，并过滤 `Accper = 01-01` 这类期初行。
- **data_complete 当前仍为 0%**：完整研究输入要求价格、估值、盈利基本面和行业均满足严格 `as_of`。在上述 provider 接入并重新生成 fixture 前，严格验收仍应失败。
- **评级/动作分桶有限**：由于当前样本缺少盈利指标和严格行业输入，评分集中在 D/C 评级和回避/谨慎观察动作；接入财务和行业历史后需要重新验证分布是否恢复。

后续代码层面工作备注：

1. 新增或扩展本地 CSMAR 财务 provider，读取 `FS_Comins.csv`、`FS_Comscfd.csv`、`FS_Comscfi.csv`、`FS_Combas.csv`，只选择公司级、合并报表 `Typrep = A` 的记录。
2. 实现严格 `as_of` 财报快照选择：按 `Stkcd + Accper` 查找在 `as_of` 时点已经“保守可见”的最近一期或 TTM 窗口，不允许使用 `as_of` 之后才应可见的报表。
3. 从本地财报推导评分需要的盈利质量字段：`revenue_ttm`、`net_profit_ttm`、`roe`、`gross_margin`、`net_margin`、`revenue_growth`、`net_profit_growth`、`debt_ratio`、`operating_cashflow_quality`。缺少营业成本或现金流时必须记录 missing reason，不得用未来数据或行业均值填充。
4. 新增历史行业 provider，读取 `DEBT_INSTITUTIONINFO.csv`，按 `Symbol + EndDate <= as_of` 取最近历史行业分类。2021-2022 优先使用 `P0207`，2023 以后优先使用 `P0221`；需要记录 `industry_source = local_csmar_industry_history` 和实际分类标准。
5. 将历史行业 provider 接入行业同行和行业分位计算，使严格行业来源覆盖率、严格行业分位有效率从 0% 恢复为可验收指标。non-strict 单一快照只能作为 fallback 诊断，不能计入严格验收。
6. 更新 `historical_sample_builder.py` 的 enrichment 流程：价格来自 QMT，估值来自 CSMAR Daily Derived/EVA fallback，盈利质量来自本地 CSMAR 财报，行业来自历史行业库；样本 `source_metadata` 必须区分 `fundamental_source`、`capital_structure_source`、`valuation_source`、`industry_source`。
7. 重新生成 `tests/fixtures/research_quality_historical_samples.json`，目标仍为 100 个 A 股沪深主板样本，覆盖 2021-2025、沪深300基准、13 个边界股票和不同市场环境。
8. 恢复并验证严格 Phase 2B 验收：`fundamental_source_coverage >= 60%`、`industry_source_coverage >= 60%`、`industry_percentile_valid_rate >= 60%`、`data_complete_coverage >= 50%`、评级/动作分桶数不少于 3，且高风险样本不得出现激进建议。
9. 补充测试：provider 字段映射测试、坏行容错测试、严格 `as_of` 防未来函数测试、TTM/同比计算测试、边界股票覆盖测试、fixture schema/source contract 测试和严格/price-only 双模式验收测试。
10. 更新 artifact 输出：在 `historical_backtest_summary.json` 和 Markdown 报告中展示财务字段覆盖率、行业历史覆盖率、strict vs fallback 来源占比、data_complete 样本占比和主要 missing reason。

**P2 第三阶段：Evidence Schema 全链路化**
目标：从“新增 `evidence_fields`”升级为“所有关键字段都有可信证据链”。

需要推进：
- 各 provider 直接产出或补齐 `value/source/as_of/quality/warnings`，而不是只在聚合后包装裸值。
- 评分引擎、估值引擎、报告、LLM compact context 都优先读取 evidence 结构。
- 明确字段级质量规则：过期、缺失、fallback、样本不足、估算值、placeholder。
- 为 `evidence_fields` 增加 schema 校验和覆盖率检查。
- 报告中展示关键结论对应的数据证据，而不只是 EvidenceBundle 摘要。

验收标准：
- 真实研究结果中关键字段 evidence 覆盖率达到明确阈值，比如核心字段 95% 以上。
- 每个买入/回避/降级结论能追溯到来源、日期和质量状态。
- provider 差异不再靠隐式字段名解释。

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

总结：现在 P2 已经完成“第一阶段基础框架”。真正完全落地，还需要重点推进真实历史样本、全链路 evidence、报告产品化、真实新闻长期监控和质量基线治理。下一步最值得做的是“真实历史回测样本池”，因为它会直接检验评分、估值分位和决策保护器是否可信。


## P3/P4：可延后事项

- 系统设置页面：适合在配置项继续增多后再做。
- 组合优化 / 多资产配置：适合在单票研究和观察池稳定后推进。
- Qlib：只有在需要因子研究、模型训练或批量回测时再接入。
- 自动交易 / QMT 下单：当前不建议推进。至少应等权限隔离、审计、人工确认、风控限额和异常回滚机制成熟后再讨论。
