# Dandelions 后续开发报告

本文件只记录尚未完成、尚未形成稳定验收，或明确延后推进的开发事项。已经落地并可运行的能力统一维护在 `README.md`，包括数据质量回归、生产运维脚本、RBAC、真实历史回测、Evidence Schema、报告产品化、新闻质量监控和研究质量治理。

## 维护口径

- `README.md` 是当前能力说明入口；`report.md` 只作为 backlog。
- 代码层可运行但还缺少连续运行验证的事项仍保留在这里，因为它们还没有形成稳定运营闭环。
- MiniQMT 数据同步维持为手工运维动作，不单独开发自动同步模块：

```powershell
robocopy "D:\迅投QMT极速交易系统交易终端 万联证券版\datadir" "D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir" /E /XC /XN /XO /R:1 /W:1 /COPY:DAT /DCOPY:DAT /MT:8
```

## 下一步建议

最适合优先推进：**P0 运行态集成验收与 CI 服务矩阵**。

理由：P0/P1/P2 的主要功能已经落地，当前最大风险不再是单点模块缺失，而是 FastAPI、Redis/Celery、WebSocket、Streamlit、MiniQMT、本地 CSMAR/EVA、PDF、新闻网络源在真实 Windows 工作站上是否能被稳定复现。先把验收矩阵固化，后续修改才有可靠回归入口。

## 未完成事项总览

| 优先级 | 开发项 | 当前状态 | 验收目标 |
|---|---|---|---|
| P0 | 运行态集成验收与 CI 服务矩阵 | 代码层已完成；验收矩阵骨架、统一入口脚本、pytest marker 分层、runtime smoke 测试已落地，待真实运行验收 | 一条命令或一组固定命令完成服务启动、核心 smoke、artifact 归档和失败定位 |
| P1 | 观察池条件触发器真实行情验收 | 未完成；CRUD、批量扫描和权限已具备，真实行情触发链路仍需验收 | 小型真实观察池覆盖触发/未触发、批量扫描、进度推送、报告关联和失败降级 |
| P2 | 网页新闻/舆情连续运行验证 | 代码层全部就绪（趋势分析、分层治理、Task Scheduler、Celery Beat）；需要安装每日任务并连续运行 7 天以上 | 通过 Windows Task Scheduler 或 Celery Beat 连续运行，确认 provider 稳定性和阈值 |
| P3 | 系统设置页面 | 未开始 | 把常用 `.env` 配置迁移到可视化设置页，并保留安全边界 |
| P3 | 组合优化 / 多资产配置 | 未开始 | 在单票研究和观察池稳定后，支持组合层评分、仓位建议和风险汇总 |
| P4 | Qlib 接入 | 延后 | 仅在需要因子研究、模型训练或批量回测时再推进 |
| P4 | 自动交易 / QMT 下单 | 明确不推进 | 需等待权限隔离、审计、风控限额、人工确认和回滚机制成熟后再讨论 |

## P0：运行态集成验收与 CI 服务矩阵

目标：把”能启动、能联通、能生成报告”变成可重复验证流程。

需要覆盖：

- FastAPI 健康检查、认证、任务提交、报告读取。
- Celery worker、Celery Beat、Redis 队列和任务状态流转。
- WebSocket 单任务进度、观察池批次进度和 admin 全局事件流。
- Streamlit 登录、单票研究、异步任务、报告库、观察池页面。
- MiniQMT 本地接口、本地 CSMAR/EVA 参考库、AKShare fallback、PDF 生成。
- 默认 CI 只运行稳定离线测试；真实环境测试按环境变量 opt-in。

验收标准：

- 文档给出从启动服务到完成 smoke 的固定命令顺序。
- `tests/integration/` 按依赖类型分组：network、qmt、redis/celery、api、websocket、streamlit。
- CI 明确区分离线必跑测试和外部依赖测试。
- 每次关键发布前能生成本地验收记录，保存到 `storage/artifacts/verification/` 或等价目录。

**代码层已完成（待真实运行验收）：**

- [x] pytest markers 分层：integration / live / qmt / network / data_quality / api / redis / celery / websocket / streamlit / pdf / runtime / slow
- [x] 统一验收入口脚本：`scripts/verify_runtime_matrix.ps1` + `scripts/run_runtime_verification.py`
- [x] artifact 输出到 `storage/artifacts/verification/<timestamp>/`，含 summary.json / summary.md / service_status.json / environment_snapshot.json
- [x] runtime smoke 测试按依赖分组，全部 opt-in：
  - `test_runtime_matrix_contract.py`（默认运行，静态契约）
  - `test_api_runtime_smoke.py`（RUN_RUNTIME_INTEGRATION=1）
  - `test_redis_celery_runtime_smoke.py`（RUN_RUNTIME_INTEGRATION=1）
  - `test_websocket_runtime_smoke.py`（RUN_RUNTIME_INTEGRATION=1）
  - `test_streamlit_runtime_smoke.py`（RUN_STREAMLIT_INTEGRATION=1）
  - `test_qmt_runtime_smoke.py`（RUN_QMT_INTEGRATION=1）
- [x] README.md 运行态验收矩阵章节
- [ ] 真实运行验收：启动全部服务后执行 verify_runtime_matrix.ps1 并归档 artifact
- [ ] CI 集成：GitHub Actions 或等价 CI 中区分 offline / opt-in 测试

## P1：观察池条件触发器真实行情验收

目标：确认观察池不是只能 CRUD，而是能在真实数据下完成批量扫描和条件触发。

需要验证：

- 价格、涨跌幅、估值、评分、风险、事件类条件是否能被实际触发。
- 批量扫描时任务状态、进度推送、失败项记录是否稳定。
- 扫描结果是否能正确关联到报告库、任务 owner 和用户数据。
- 单个标的失败时，整批任务可继续完成并记录失败原因。

验收标准：

- 至少准备一个小型观察池样本，覆盖触发和未触发两类结果。
- 扫描结果可复现，并能解释数据来源和 missing_reason。
- 普通用户只能看到自己的观察池、批次和报告；admin 范围明确。

## P2：网页新闻/舆情连续运行验证

目标：把”新闻质量监控脚本可运行”升级为”真实网络 provider 稳定性可长期观察”。

代码基础已全部落地：

- `services/data/news_quality_monitor.py`：监控核心模块
- `services/data/news_quality_trends.py`：趋势分析模块（从 history.jsonl 聚合 provider 趋势）
- `configs/web_news_quality_targets.json`：10 个核心标的
- `configs/web_news_quality_policy.json`：provider 分层治理策略（core/secondary/weak）
- `scripts/run_web_news_quality_monitor.py`：监控脚本
- `scripts/analyze_web_news_quality_trends.py`：趋势分析脚本
- `scripts/prod/install_web_news_quality_task.ps1`：Windows Task Scheduler 安装
- `scripts/prod/uninstall_web_news_quality_task.ps1`：Windows Task Scheduler 卸载
- `scripts/prod/run_web_news_quality_daily.ps1`：每日运行脚本
- Celery Beat 集成（默认关闭，`WEB_NEWS_QUALITY_BEAT_ENABLED=true` 启用）

Provider 分层：

| 层级 | Provider | 失败影响 |
|------|----------|---------|
| core | eastmoney | warning / blocker（连续失败 >= 3 次） |
| secondary | sina, xinhuanet, baidu | watch / warning |
| weak | hotrank | watch（不阻断） |

治理脚本 `--include-web-news-live` 优先读取 `trend_summary.json`，fallback 到 `latest.json`。

验收标准：

- [x] 连续运行期间脚本不因单 provider 失败中断。
- [x] `provider_health.json` 能反映来源健康状态。
- [x] `manual_review_candidates.jsonl` 能持续产出可抽样复核的候选。
- [x] 治理脚本 `--include-web-news-live` 优先读取趋势数据，fallback 时有明确 warning。
- [x] Windows Task Scheduler 和 Celery Beat 均已支持。
- [ ] 连续积累至少 7 天真实网络 artifact，验证 provider 稳定性（需要每日定时运行）。

当前状态：代码层和基础设施已全部就绪，需要安装每日任务并连续运行 7 天以上，根据真实趋势调优阈值后，方可标记为完全完成。

## P3：系统设置页面

目标：减少直接编辑 `.env` 的日常操作，把高频配置迁移到可视化页面。

候选配置：

- 数据源开关：QMT、AKShare、网页新闻、本地 CSMAR/EVA。
- 报告选项：模板、主题、PDF 开关、证据章节。
- LLM 选项：模型、温度、是否启用 LLM。
- 运维检查：Redis、MiniQMT、参考库路径、artifact 路径。

验收标准：

- 敏感配置不直接明文展示。
- 修改配置有明确保存位置和重启提示。
- 默认单机自用模式保持简单，不引入过重的管理界面。

## P3：组合优化 / 多资产配置

目标：在单票研究稳定后，扩展到组合层判断。

候选能力：

- 多标的评分汇总。
- 行业/风格/风险暴露统计。
- 仓位建议和再平衡提示。
- 组合报告输出。

验收标准：

- 不改变当前单票研究主链路。
- 明确区分“研究建议”和“交易指令”。
- 不自动下单。

## P4：Qlib 接入

当前不建议主动推进。只有在需要因子研究、模型训练、批量回测或统一数据集管理时再评估。

## P4：自动交易 / QMT 下单

当前明确不推进自动交易。至少需要先完成：

- 多用户权限和操作审计的生产验证。
- 风控限额、人工确认、撤销/回滚机制。
- QMT 下单接口隔离和模拟盘验收。
- 异常处理和日志归档。
