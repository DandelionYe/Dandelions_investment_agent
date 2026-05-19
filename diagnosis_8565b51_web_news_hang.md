# 诊断报告：股票分析卡在 30%

**目标 commit:** `8565b51` (feat: 扩展网页新闻与热榜舆情源)
**诊断日期:** 2026-05-19
**诊断结论:** 卡住的根因不是 Web 新闻/热榜源，而是 QMT 行业数据自动下载挂起。

---

## 1. 结论摘要

- **卡在 30% 是 Celery 任务内部阻塞**，不是前端问题、API 问题或 Celery 调度问题。
- **根因是 `QMTIndustryProvider.list_sectors()` 调用了 `xtdata.download_sector_data()`，该调用在 QMT 端无限挂起。**
- **与新增 Web 新闻/热榜舆情源无关。** `.env` 中未设置 `WEB_NEWS_ENABLED`，默认为 `False`，WebNewsProvider 根本没有被调用。
- **WebNewsProvider 默认包含 github/google 热榜源**（在 `WEB_NEWS_HOTRANK_SOURCES` 的默认值中），但因为 provider 默认关闭，实际未被触发。
- **建议默认关闭 github/google 热榜源**，即使 WebNewsProvider 被启用。
- **建议把 `QMT_INDUSTRY_AUTO_DOWNLOAD` 设为 `false`**，这是当前卡住的直接修复。
- **Web 新闻/热榜源作为增强项设计正确**——`EventService.build()` 中 web news 是可选步骤，失败不阻塞主流程。
- **但 `download_sector_data()` 阻塞了整个研究管道**，因为行业估值是评分的必经路径。

---

## 2. 复现环境与当前代码状态

| 项目 | 状态 |
|------|------|
| 当前分支 | `main` |
| 当前 commit | `8565b51` (与目标一致) |
| 未提交改动 | 无（工作树干净） |
| FastAPI | 运行中 (port 8000) |
| Streamlit | 运行中 (port 8501) |
| Redis | 运行中 (port 6379, 多个 ESTABLISHED 连接) |
| Celery Worker | 运行中 (`celery@Dandelion`, solo pool, 已注册 `research.run_single`) |
| XtMiniQMT | 用户确认已启动 |
| `WEB_NEWS_ENABLED` | 未设置（默认 `False`） |
| `QMT_INDUSTRY_AUTO_DOWNLOAD` | 未设置（默认 `True`） |

---

## 3. 任务执行链路

```
Streamlit (1_Single_Asset_Research.py:425)
  → submit_research_task() (progress_poller.py:168)
    → POST /api/v1/research/single (research.py:24)
      → TaskManager.submit() → Celery task published
        → run_research_task() (celery_tasks.py:32)
          → progress=0.1 "开始加载数据..."
          → progress=0.3 "执行研究中..." ← 进度停在这里
          → run_full_research_graph() (langgraph_orchestrator.py:992)
            → _full_node_load_research_data() (line 606)
              → _load_asset_data() (single_asset_research.py:28)
                → get_qmt_asset_data() [正常, ~2.5s]
                → ResearchDataAggregator().enrich()
                  → fundamental_service.build() [正常]
                  → valuation_service.build() [卡住！]
                    → _attach_industry_valuation()
                      → IndustryValuationService.build()
                        → QMTIndustryProvider.resolve_industry()
                          → list_sectors()
                            → download_sector_data() ← 无限挂起
```

进度对应关系：

| 进度 | 代码位置 | 说明 |
|------|---------|------|
| 10% | celery_tasks.py:53 | 任务开始 |
| 30% | celery_tasks.py:65 | 调用 run_full_research_graph 前 |
| **卡住** | **langgraph_orchestrator.py:606** | **load_research_data → enrich → valuation → QMT download_sector_data()** |
| 70% | celery_tasks.py:92 | 研究完成后（永远到不了） |
| 100% | celery_tasks.py:143 | 报告生成后（永远到不了） |

---

## 4. 30% 卡住位置分析

### 4.1 哪段代码把进度更新到 30%

`celery_tasks.py:65-72`：
```python
store.update_status(task_id, TaskStatus.RUNNING, progress=0.3,
                    progress_message=f"执行研究中（{symbol}，数据源：{data_source}）...")
```

### 4.2 30% 后等待哪个函数返回

`celery_tasks.py:76`：
```python
result = run_full_research_graph(symbol=symbol, data_source=data_source, ...)
```

该函数内部调用链最终到达 `xtdata.download_sector_data()`，该调用在 QMT 端无限挂起。

### 4.3 为什么前端不会立即报错

`progress_poller.py:58-101` 的轮询循环每 1 秒查询一次进度，但进度一直是 0.3（30%），状态一直是 `running`。前端不会报错，因为任务状态既不是 `completed` 也不是 `failed`。

### 4.4 为什么 API 后台面板没有明显请求数量增加

研究任务通过 Celery 异步执行，只有提交和轮询两个 API 调用。任务执行本身不产生额外的 API 请求。

### 4.5 为什么其他终端没有明显报错

`download_sector_data()` 不是抛出异常，而是无限挂起（阻塞）。没有错误日志产生。

---

## 5. 新闻/热榜源配置与默认值分析

### 5.1 当前 .env 配置

`.env` 文件中**没有任何 `WEB_NEWS_*` 配置项**。所有值使用代码默认值。

### 5.2 代码默认值

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `WEB_NEWS_ENABLED` | `False` | **默认关闭** — 当前未被触发 |
| `WEB_NEWS_FORCE_NO_PROXY` | `True` | 强制禁用代理 |
| `WEB_NEWS_SOURCES` | `eastmoney,sina,xinhuanet,hotrank,baidu` | 国内新闻源 |
| `WEB_NEWS_HOTRANK_SOURCES` | `wallstreetcn,yicai,36kr,tencent,sina_news,sina_hot,pengpai,bilibili,douyin,csdn,github,google,weread` | **包含 github 和 google** |
| `WEB_NEWS_TIMEOUT_SECONDS` | `8` | 单请求超时 8 秒 |
| `WEB_NEWS_LIMIT` | `10` | 每源最多 10 条 |

### 5.3 源分类

**国内稳定源（可保留）：**
- eastmoney, sina, xinhuanet, baidu（新闻源）
- wallstreetcn, yicai, tencent, sina_news, sina_hot, pengpai, bilibili, douyin（热榜源）

**国内但可能不稳定源（可保留但应可降级）：**
- 36kr, csdn, weread（热榜源）

**不应默认启用的源：**
- **github** (`https://github.com/trending`) — 非国内源，`force_no_proxy=True` 时可能无法访问
- **google** (`https://trends.google.com/...`) — 非国内源，在中国大陆无法直接访问

### 5.4 WebNewsProvider 的串行执行问题

`_fetch_hotrank_public_opinion()` 串行遍历所有 hotrank 源（`web_news_provider.py:548-581`），每个源最多等待 `timeout_seconds`（默认 8 秒）。13 个源理论最大耗时：13 × 8 = 104 秒。

实测（含 github/google，`force_no_proxy=True`）：**16.6 秒**。虽然每个源有 try/except 保护不会无限阻塞，但总耗时仍然可观。

---

## 6. 对照实验结果

### 实验 A：当前配置（QMT, no-llm, 默认配置）

| 项目 | 结果 |
|------|------|
| 配置 | `data_source=qmt`, `use_llm=False`, 无 `WEB_NEWS_ENABLED` 设置, 无 `QMT_INDUSTRY_AUTO_DOWNLOAD` 设置 |
| 是否卡住 | **是，卡在 30%** |
| 最后日志位置 | `run_full_research_graph()` → `load_research_data()` → `enrich()` → `valuation_service.build()` |
| 根因 | `xtdata.download_sector_data()` 无限挂起 |
| LLM API 请求 | 无（`use_llm=False`） |

### 实验 B：mock 数据源

| 项目 | 结果 |
|------|------|
| 配置 | `data_source=mock`, `use_llm=False` |
| 是否卡住 | **否** |
| 总耗时 | ~0.3 秒 |
| 说明 | mock 跳过 QMT，不触发行业数据下载 |

### 实验 C：QMT + `QMT_INDUSTRY_AUTO_DOWNLOAD=false`

| 项目 | 结果 |
|------|------|
| 配置 | `data_source=qmt`, `use_llm=False`, `QMT_INDUSTRY_AUTO_DOWNLOAD=false` |
| 是否卡住 | **否** |
| 总耗时 | **4.4 秒** |
| 评分 | 49 / D |
| 行业估值 | `partial_success`（113 个成员，PE 有效同行数不足） |

### 实验 D：WebNewsProvider 全部默认 hotrank 源（含 github/google）

| 项目 | 结果 |
|------|------|
| 配置 | `enabled=True`, `source_order=['hotrank']`, 全部 13 个 hotrank 源, `timeout_seconds=8` |
| 是否卡住 | **否**（每个源有 try/except 保护） |
| 总耗时 | **16.6 秒** |
| 成功记录数 | 0（无匹配记录） |

---

## 7. 根因判断

### 已确认根因

**`xtdata.download_sector_data()` 在 QMT 端无限挂起。**

- 调用路径：`QMTIndustryProvider.list_sectors()` → `download_sector_data()`
- 代码位置：`services/data/providers/qmt_industry_provider.py:20-26` 和 `:32-33`
- 触发条件：`QMT_INDUSTRY_AUTO_DOWNLOAD` 默认为 `True`（代码默认值，.env 未覆盖）
- 表现：调用 `xtdata.download_sector_data()` 后进程无限阻塞，无超时、无异常、无日志

### 高概率原因

`download_sector_data()` 可能因为以下原因挂起：
1. XtMiniQMT 的 sector 数据下载接口在当前状态下无响应
2. QMT 服务端连接状态异常（虽然后续 `get_sector_list()` 能正常工作）
3. 需要重启 XtMiniQMT 或重新连接

### 仍需进一步验证

- `download_sector_data()` 在正常状态下是否能成功完成（可能需要重启 XtMiniQMT 后测试）
- 是否所有 Windows 环境下都存在此问题，还是特定 QMT 版本/状态导致

---

## 8. 最小修复建议

### 建议 1（最高优先级）：设置 `QMT_INDUSTRY_AUTO_DOWNLOAD=false`

**直接修复当前卡住问题。** 在 `.env` 中添加：
```
QMT_INDUSTRY_AUTO_DOWNLOAD=false
```
行业估值分位功能仍可用（`get_sector_list()` 不需要下载即可工作），只是数据可能不是最新的。

### 建议 2：默认移除 github/google 热榜源

修改 `web_news_provider.py:319-325` 中 `WEB_NEWS_HOTRANK_SOURCES` 的默认值，移除 `github` 和 `google`：

```python
# 修改前
"wallstreetcn,yicai,36kr,tencent,sina_news,sina_hot,"
"pengpai,bilibili,douyin,csdn,github,google,weread"

# 修改后
"wallstreetcn,yicai,36kr,tencent,sina_news,sina_hot,"
"pengpai,bilibili,douyin,csdn,weread"
```

### 建议 3：给 `download_sector_data()` 增加超时保护

在 `qmt_industry_provider.py:20-26` 中增加超时：
```python
def download_sector_data(self) -> None:
    xtdata = _import_xtdata()
    try:
        download = getattr(xtdata, "download_sector_data", None)
        if callable(download):
            import threading
            result = [None]
            def _do_download():
                try:
                    download()
                except Exception as e:
                    result[0] = e
            t = threading.Thread(target=_do_download, daemon=True)
            t.start()
            t.join(timeout=15)  # 15 秒超时
            if t.is_alive():
                raise ProviderUnavailableError("QMT sector data download timed out (15s)")
            if result[0]:
                raise result[0]
    except ProviderUnavailableError:
        raise
    except Exception as exc:
        raise ProviderUnavailableError(f"QMT sector data download failed: {exc}") from exc
```

### 建议 4：WebNewsProvider 增加总超时预算

在 `fetch_events()` 中增加总时间限制，而不是只依赖单请求 timeout。

### 建议 5：新闻/热榜增强失败时只记录 warning

当前 `EventService.build()` 中 web news 是可选的（`event_engine.py:71`），设计正确。但建议在 `WebNewsProvider` 内部对 hotrank 源增加总超时限制。

### 建议 6：给 30%-70% 阶段增加细粒度进度

在 `langgraph_orchestrator.py` 的 `_full_node_load_research_data` 和 `_full_node_score_asset` 中增加进度回调。

---

## 9. 建议修改点清单

| 文件路径 | 函数/类 | 问题 | 建议修改 | 风险等级 | 必须修改 |
|---------|---------|------|---------|---------|---------|
| `.env` | - | `QMT_INDUSTRY_AUTO_DOWNLOAD` 未设置，默认 True 导致 download_sector_data() 挂起 | 添加 `QMT_INDUSTRY_AUTO_DOWNLOAD=false` | 低 | **是** |
| `services/data/providers/qmt_industry_provider.py` | `download_sector_data()` | 无超时保护，可无限挂起 | 增加 15 秒超时 | 低 | 建议 |
| `services/data/providers/web_news_provider.py` | `_hotrank_sources()` | 默认包含 github/google 非国内源 | 从默认值中移除 | 低 | 建议 |
| `services/data/providers/web_news_provider.py` | `fetch_events()` | 无总超时预算，13 个源串行可能耗时 100+ 秒 | 增加总超时限制（如 30 秒） | 中 | 建议 |
| `.env.example` | - | `QMT_INDUSTRY_AUTO_DOWNLOAD=true` 建议改为 false | 修改默认值 | 低 | 建议 |
| `apps/api/task_manager/celery_tasks.py` | `run_research_task()` | 30%-70% 之间无细粒度进度更新 | 在 graph 节点间增加进度回调 | 中 | 可选 |

---

## 10. 附录：关键日志

### 实验 A：卡住时的状态
```
Task ID: f4e26cc38d2d
[2.0s] progress=0.3, status=running, msg=执行研究中（000858.SZ，数据源：qmt）...
（之后 120 秒无任何变化）
```

### 实验 C：修复后（QMT_INDUSTRY_AUTO_DOWNLOAD=false）
```
[0s] running full research graph (qmt, no-llm)...
[4.4s] DONE
  score=49, rating=D, action=回避
  data_source=qmt
```

### 实验 D：WebNewsProvider 全源测试
```
hotrank_sources=['wallstreetcn', 'yicai', '36kr', 'tencent', 'sina_news', 'sina_hot',
                 'pengpai', 'bilibili', 'douyin', 'csdn', 'github', 'google', 'weread']
timeout=8s, force_no_proxy=True
[16.6s] total: success=False, rows=0
```

### QMT 行业数据下载挂起
```
connecting qmt...  → OK
downloading sector data... → 无限挂起（>110 秒无响应）
get_sector_list() (不调用 download) → 0.0 秒，返回 853 个 sector
```

---

## 诊断总结

**一句话：** 股票分析卡在 30% 的根因是 `xtdata.download_sector_data()` 在 QMT 端无限挂起，与 Web 新闻/热榜源无关。修复方法：在 `.env` 中添加 `QMT_INDUSTRY_AUTO_DOWNLOAD=false`。
