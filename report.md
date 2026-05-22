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
| P2 | 历史回测与压力测试 | 尚未形成系统能力 | 行业估值、评分、决策保护器需要用历史样本验证稳定性，尤其是极端行情和行业轮动场景 |
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

## P3/P4：可延后事项

- 系统设置页面：适合在配置项继续增多后再做。
- 组合优化 / 多资产配置：适合在单票研究和观察池稳定后推进。
- Qlib：只有在需要因子研究、模型训练或批量回测时再接入。
- 自动交易 / QMT 下单：当前不建议推进。至少应等权限隔离、审计、人工确认、风控限额和异常回滚机制成熟后再讨论。
