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
| P0 | 运行态集成验收与 CI 服务矩阵 | 已完成；验收矩阵骨架、统一入口脚本、pytest marker 分层、runtime smoke 测试、真实运行验收、CI workflow 和本地 offline CI 脚本均已落地 | 一条命令或一组固定命令完成服务启动、核心 smoke、artifact 归档和失败定位 |
| P1 | 观察池条件触发器真实行情验收 | 已完成；全链路验收通过，含 WebSocket 进度推送、条件触发器 UI、集成测试、验收脚本、3 个 bug 修复 | 小型真实观察池覆盖触发/未触发、批量扫描、进度推送、报告关联和失败降级 |
| P2 | 网页新闻/舆情连续运行验证 | 代码层全部就绪（趋势分析、分层治理、Task Scheduler、Celery Beat）；需要安装每日任务并连续运行 7 天以上 | 通过 Windows Task Scheduler 或 Celery Beat 连续运行，确认 provider 稳定性和阈值 |
| P3 | 系统设置页面 | 已完成；8 Tab 完整配置页 + 敏感字段掩码 + 运维状态检查，待验收 | 把常用 `.env` 配置迁移到可视化设置页，并保留安全边界 |
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

**已完成：**

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
- [x] 真实运行验收：启动全部服务后执行 verify_runtime_matrix.ps1 并归档 artifact（latest.json 显示 pass）
- [x] CI 集成：GitHub Actions workflow（`.github/workflows/ci.yml`）+ 本地 offline CI 脚本（`scripts/run_offline_ci.ps1`）+ CI workflow contract 测试（`tests/test_ci_workflow_contract.py`）

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

**已完成：**

- [x] WebSocket 进度推送接入：`scan_single_watchlist_item` 完成/失败时调用 `publish_batch_progress` + `update_batch_progress`
- [x] 批量扫描 batch 管理：`watchlist_scheduler_check`、`scan_watchlist`、`trigger_scan` 均创建 batch 并传入 batch_id
- [x] Dashboard 条件触发器配置 UI：添加/编辑观察项时可配置 price_change_pct、score_threshold、volume_spike_ratio
- [x] Dashboard 条件触发器展示：详情面板显示当前配置，支持编辑
- [x] 端到端集成测试：`tests/integration/test_watchlist_scan_e2e.py` 覆盖创建→扫描→结果关联、batch 进度、条件评估、防重复、owner 隔离（15/15 passed）
- [x] 真实行情验收脚本：`scripts/verify_watchlist_triggers.py` 支持 QMT/AKShare 数据源
- [x] Bug 修复：`get_scan_progress` batch_id 字段映射、`next_scan_at` 无法清除、扫描历史不显示

**全链路验收（已完成）：**

- [x] 启动 FastAPI + Celery worker + Redis，在 Dashboard 添加观察项并配置条件触发器，手动触发扫描验证全链路
- [x] 运行 `python scripts/verify_watchlist_triggers.py --data-source qmt` 验证真实行情触发判断
- [x] 准备小型观察池样本，覆盖触发和未触发两类结果
- [x] 修复 `batch_id` 字段映射（`get_scan_progress` 返回 `id` → `batch_id`）
- [x] 修复 `next_scan_at` 无法清除（store `allowed` 字段缺少 `next_scan_at`）
- [x] 修复扫描历史不显示（`WatchlistItemResponse` 缺少 `scan_history` 字段）

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

**已完成：**

- [x] 新建 `apps/dashboard/pages/4_系统设置.py`：8 个 Tab 分组（LLM / 数据源 / QMT / 行业分类 / CSMAR / 新闻 / 基础设施 / 认证）+ 状态检查
- [x] 敏感字段掩码处理：密码型字段显示为 ****，保存时跳过未修改的值
- [x] 保存流程：直接写 .env 文件，提示重启生效
- [x] 访问控制：仅 admin 可访问
- [x] 运维检查面板：Redis / FastAPI / QMT 连接检查、缓存目录大小、.env 修改时间
- [x] Home.py 添加系统设置入口

验收标准：

- [x] 敏感配置不直接明文展示（密码型字段用 type="password"）
- [x] 修改配置有明确保存位置（.env）和重启提示
- [x] 默认单机自用模式保持简单

**待验收：**

- [ ] 启动 Streamlit → 导航到系统设置 → 修改配置 → 保存 → 检查 .env 已更新
- [ ] 重启 FastAPI → 确认新配置生效

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

## 公网访问方案（讨论中）

目标：将系统访问权限从本地扩展到公网，5-10 个用户通过互联网访问，使用本机配置（DeepSeek API Key 等）。按需启动，不 24/7 运行。

当前架构：FastAPI (localhost:8000) + Streamlit (localhost:8501) + Redis/Celery，JWT 认证 + RBAC 已就位。

### 方案 A：内网穿透（最快，免费）

用 ngrok 或 frp 把本地端口暴露到公网，获得临时 URL。

- 优点：5 分钟搞定，不需要云服务器，不需要改代码
- 缺点：URL 每次重启会变（免费版），速度取决于穿透服务，不适合长期使用
- 适合：临时分享给朋友试用
- 成本：免费

### 方案 B：云服务器部署（最稳定）

把整个系统部署到云服务器（阿里云/腾讯云/AWS），绑定域名 + HTTPS。

- 优点：稳定、专业、可绑定域名、固定 IP
- 缺点：需要云服务器（~50-100 元/月），需要域名（~50 元/年），需要配置 Nginx + SSL，数据不在本地
- 适合：长期对外提供服务，多人同时使用
- 成本：~100 元/月

### 方案 C：Cloudflare Tunnel + 本地反向代理（推荐）

```
外部用户 → Cloudflare Tunnel → 本地 Caddy (:80/443) → Streamlit (:8501) / FastAPI (:8000)
```

- 优点：免费，稳定，全球 CDN，自动 HTTPS，不需要公网 IP，不需要端口映射，按需启动
- 缺点：依赖本机开机，上行带宽有限，需要安装 cloudflared + Caddy
- 适合：5-10 用户按需访问，数据在本地
- 成本：免费

实现步骤：

1. 注册 Cloudflare 账号，安装 `cloudflared`
2. 配置 Caddy 反向代理（Streamlit + FastAPI 统一入口）
3. 创建 Cloudflare Tunnel，绑定域名
4. 修改 CORS 配置（`.env` 中 `CORS_ORIGINS` 加上 Cloudflare 域名）
5. Streamlit 启动参数加 `--server.address 0.0.0.0`
6. 创建外部用户账号

注意事项：

- QMT 数据源可被外部用户使用：数据获取发生在本机 Celery Worker 进程中，只要本机 XtMiniQMT 在后台运行，外部用户提交的任务会自动通过 QMT 获取行情数据。无需外部用户安装 QMT。
- DeepSeek API Key 用本机配置，所有用户共享
- JWT Secret 需要重新生成强密码（公网环境）
- Rate Limiting 需要收紧（防暴力破解）
