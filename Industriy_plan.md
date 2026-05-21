# 行业功能现状与后续计划

本文档只记录 `Industriy_plan.md` 多轮开发后形成的行业相关能力、当前边界，以及仍有必要推进的开发项。已完成的历史实现过程不再展开。

## 当前可用能力

### 1. 本地行业分类与同行池

仓库当前已经可以使用本地 CSMAR `TRD_Co.csv` 构建行业参考库，并通过 `LocalCSMARIndustryProvider` 解析股票所属行业和同行池。

当前设计边界：

```text
行业分类 / 同行池来源：local_csmar
同行价格 / 股本 / 财务 / 估值输入来源：QMT / MiniQMT 可读缓存
```

也就是说，本地 CSMAR 数据负责“这只股票属于哪个行业、同行有哪些”；QMT 仍负责“同行当前价格、股本、财务数据、估值输入”。

### 2. 行业估值前置预检

行业横截面 PE / PB / PS 分位计算前，系统会先检查同行池所需数据是否可用，主要包括：

```text
close
total_volume
net_profit_ttm
revenue_ttm
bps
peer_valuation_complete
```

当 MiniQMT 本地缓存不足时，行业估值不会强行输出分位结论，而是返回结构化 warning、同行数量、有效样本数量和预检摘要。

### 3. QMT 同行价格缓存补齐工具

仓库已有同行 K 线 / 最新价缓存维护工具，可对行业同行池做 dry-run 检查，也可在用户显式确认后调用 QMT 接口补齐缺失 K 线缓存。

该工具的定位是“手工维护 / 诊断工具”，不是主研究流程的一部分。主流程不会自动批量下载同行 K 线，避免运行时阻塞。

### 4. 股本备用来源

当 QMT `get_instrument_detail()` 返回 `TotalVolume=0` 或缺失时，系统可通过 AKShare 个股信息补充：

```text
total_volume
float_volume
market_cap
float_market_cap
```

该 fallback 用于修复因股本缺失导致的 `market_cap`、`PE_TTM`、`PS_TTM` 为空问题。同行估值 loader 和预检共用同一套 fallback 逻辑，并通过最大请求数量限制避免批量滥用。

### 4.1 本地 CSMAR 股本 / 市值数据

2026-05-21 已确认：`data/raw/csmar/EVA_Structure.csv` 可以作为本地股本与市值补充数据源。该文件包含：

```text
Symbol
EndDate
ShortName
CirculatedMarketValue
MarketValue
TotalShares
NegotiableShares
EquityPerShare
```

关键覆盖情况：

```text
总行数：274693
股票数：5831
最新日期：2026-03-31
最新期记录数：5496
最新期 TotalShares 正值：5496 / 5496
最新期 MarketValue 正值：5496 / 5496
本地行业库 securities 覆盖：5489 / 5519，约 99.46%
600410.SH、002624.SZ、000419.SZ 三个样例行业合并同行池覆盖：513 / 513，100%
```

结论：

```text
1. 对行业 PE / PB / PS 横截面分位来说，当前核心数据已经基本齐全：
   行业同行池来自 TRD_Co；
   财务字段来自 MiniQMT Finance；
   最新 close 来自 MiniQMT K 线；
   total_volume / market_cap 可由 EVA_Structure 本地补充。

2. EVA_Structure 更适合作为 total_volume / market_cap 的本地权威补充源，
   优先级应高于 AKShare 网络 fallback。

3. 计算当前估值时，优先使用 TotalShares × 当前 close 得到当前 market_cap；
   MarketValue 可作为校验或在缺少 close 时的备用字段。

4. NegotiableShares 在最新期覆盖较弱，不应作为第一阶段 float_volume 的主要来源。
```

因此，后续推进重点已经从“数据是否存在”转为“把 EVA_Structure 接入现有估值与预检链路”。

### 4.2 本地 CSMAR 个股日交易衍生指标快照库

2026-05-21 已完成对 `data/raw/csmar/个股日交易衍生指标*` 原始日频数据的压缩处理方案。原始数据规模较大，不适合在研究流程中直接扫描；当前已新增构建脚本：

```text
scripts/build_csmar_daily_derived_snapshots.py
```

该脚本按本地 CSMAR 行业库中的 A 股证券范围过滤数据，并生成以下本地快照文件：

```text
storage/reference/csmar_daily_derived_snapshots.sqlite
storage/reference/csmar_daily_derived_latest.csv
storage/reference/csmar_daily_derived_latest_metrics.csv
storage/reference/csmar_daily_derived_build_report.md
```

SQLite 表结构定位：

```text
monthly_snapshots：
  每只股票每个自然月只保留最后一个可用交易日记录。

latest_snapshot：
  每只股票保留最新交易日记录。

latest_non_null_metrics：
  每只股票按字段保留“最新非空值 + 对应日期”，用于处理股息率这类非每日更新字段。
```

本次构建结果：

```text
原始扫描行数：11811258
过滤后覆盖股票数：5519
monthly_snapshots：560316 行
latest_snapshot：5519 行
latest_non_null_metrics：5519 行
最新交易日范围：2026-04-13 至 2026-05-18

latest_non_null_metrics 覆盖：
  dividend_yield：5127 / 5519
  pe：5485 / 5519
  pb：5519 / 5519
  ps：5518 / 5519
  circulated_market_value：5519 / 5519
```

字段含义：

```text
dividend_yield：由 CSMAR Ret 转换而来，原始 Ret 是百分数，快照库中除以 100 后存储为小数。
pe / pb / pcf / ps：直接保留 CSMAR 日交易衍生指标中的估值倍数。
turnover：换手率。
circulated_market_value：流通市值。
change_ratio：涨跌幅。
amount：成交金额。
liquidility：流动性指标。
```

这批快照库可以作为后续接入行业估值与报告字段的本地数据源，尤其适合补充：

```text
股息率
PE / PB / PCF / PS 当前值
PE / PB / PS 历史分位所需的月度历史样本
换手率、流通市值、涨跌幅、成交金额、流动性指标
```

当前边界：数据已经压缩并验证，但主估值链路和报告层尚未读取 `csmar_daily_derived_snapshots.sqlite`。因此它目前是“已准备好的本地数据底座”，不是已经自动出现在报告里的字段。

推荐接入方式：

```text
1. 新增本地 provider
   建议新增 LocalCSMARDailyDerivedProvider，默认读取：
   storage/reference/csmar_daily_derived_snapshots.sqlite

   provider 至少提供两个查询接口：
   - get_latest_metrics(symbol)
     从 latest_non_null_metrics 读取当前可用指标及 value_date。
   - get_monthly_history(symbols, metrics, start_date=None, end_date=None)
     从 monthly_snapshots 读取月度历史样本，用于历史分位。

2. 当前估值字段接入
   对单只股票报告字段，优先读取 latest_non_null_metrics：
   - dividend_yield
   - pe
   - pb
   - pcf
   - ps
   - turnover
   - circulated_market_value
   - change_ratio
   - amount
   - liquidility

   每个字段都应同时保留对应的 *_date，避免把过旧数据当成当前值。

3. 行业历史分位接入
   PE / PB / PS 历史分位不要扫描原始 CSMAR CSV，也不要只用 latest_snapshot。
   应按行业同行池读取 monthly_snapshots，并按 symbol + period 形成月度横截面样本。

   建议第一阶段只接入：
   - pe historical percentile
   - pb historical percentile
   - ps historical percentile

   pcf、turnover、流通市值等字段可以作为后续扩展。

4. 数据源优先级
   当前值：
   - close：仍优先使用 MiniQMT K 线最新价。
   - total_volume / market_cap：优先使用 EVA_Structure 本地股本 / 市值补充。
   - dividend_yield、pe、pb、pcf、ps：优先使用 CSMAR daily derived latest_non_null_metrics。
   - QMT / AKShare 对应字段可作为缺口 fallback，但不应覆盖更新且可信的本地 CSMAR 快照字段。

   行业分位：
   - 同行池：local_csmar 行业库。
   - 同行当前横截面估值：优先使用现有 QMT 财务 + close + 股本链路。
   - 历史分位样本：优先使用 CSMAR daily derived monthly_snapshots。

5. 新鲜度校验
   latest_non_null_metrics 中每个指标都有独立日期。
   建议接入时增加最大陈旧天数或最大陈旧月份配置，例如：
   - dividend_yield 可允许更长窗口，因为通常随分红或年报更新。
   - pe / pb / ps 应要求更接近当前交易日。

   若字段超过新鲜度阈值，不应静默输出，应在 provider_run_log / source_metadata 中记录 stale warning。

6. 失败策略
   本地 SQLite 不存在、表不存在、字段缺失或查询失败时，不阻断主流程。
   provider 应返回结构化 warning，并允许现有 QMT / EVA / AKShare 链路继续运行。
```

### 5. MiniQMT Finance 同步边界

已确认的边界是：

```text
xtdata.get_financial_data() 读取的是 MiniQMT 当前服务可读的数据目录。
完整版 QMT datadir\Finance 中的数据不会因为设置 xtdata.data_dir 而自动被 get_financial_data 读取。
```

因此，完整版 QMT 下载的 `datadir\Finance` 如需被接口读到，仍需要同步到 MiniQMT 的 `userdata_mini\datadir\Finance` 后重启 MiniQMT 再复验。

### 6. 已验证的 MiniQMT 本地缓存复用效果

2026-05-20 已验证：将完整版 QMT 中下载的数据复制到以下 MiniQMT 数据目录后，MiniQMT 接口确实可以读到其中相当一部分数据。

```text
D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir
```

接口确认结果：

```text
xtdata.get_data_dir()
  -> D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir

userdata_mini\datadir\Finance 文件数：41932
userdata_mini\datadir\SH\86400 文件数：4888
userdata_mini\datadir\SZ\86400 文件数：6202
```

抽样验证结果：

```text
600410.SH / 002624.SZ / 000419.SZ / 600519.SH / 601728.SH
  get_financial_data 均可读到 Balance / Income / CashFlow / PershareIndex。
  最新财务报告期均可读到 20260331。
  get_market_data_ex(count=1) 均可读到最新 close。
```

这说明：把完整版 QMT 已下载的数据同步到 MiniQMT `userdata_mini\datadir`，确实能显著提升本仓库通过 MiniQMT 接口读取财务和 K 线缓存的能力。

对行业估值的实际帮助：

```text
600410.SH、002624.SZ、000419.SZ 三个样例对应的合并同行池：
  同行数：513
  close 覆盖率：488 / 513，约 95.1%
  net_profit_ttm 覆盖率：488 / 513，约 95.1%
  revenue_ttm 覆盖率：488 / 513，约 95.1%
  bps 覆盖率：488 / 513，约 95.1%
  QMT 原生 total_volume 覆盖率：384 / 513，约 74.9%
```

结论：

```text
1. 复制到 userdata_mini\datadir 后，Finance 和 K 线缓存已经能被 MiniQMT 接口实际调用。
2. 这能解决此前“Finance 同步后接口仍读不到”以及“同行 close 样本严重不足”的主要问题。
3. 当前剩余瓶颈主要是部分股票 get_instrument_detail() 的 TotalVolume 仍为 0 或缺失。
4. 因此行业估值仍需要保留 total_volume fallback 和预检机制。
```

推荐维护方式：

```text
1. 在完整版 QMT 中完成数据下载。
2. 关闭 QMT / MiniQMT 相关进程。
3. 将完整版 datadir 中需要复用的数据目录同步到 MiniQMT userdata_mini\datadir。
4. 重启 MiniQMT。
5. 使用预检脚本确认 Finance / close / total_volume 覆盖率。
```

当前不建议把这一步做进主研究流程；它应作为手工维护或独立脚本执行，避免研究任务运行时阻塞或误删缓存。

## 当前不能可靠实现的能力

### 1. 不能保证所有股票都有行业估值分位

即使行业分类和同行池可用，行业 PE / PB / PS 分位仍依赖 MiniQMT 本地缓存。以下任一条件不足时，行业分位会返回“不可用 / warning”：

```text
同行最新价不足
同行财务数据不足
同行股本数据不足，且备用来源也未补齐
目标股票自身估值输入不足
有效同行样本数低于阈值
```

这是当前设计的预期行为，不应改成静默给出低质量分位。

在已同步完整版 QMT 数据到 MiniQMT `userdata_mini\datadir` 后，Finance 和 close 覆盖率已经明显改善。新增的 `EVA_Structure.csv` 又基本补齐了 A 股 `TotalShares / MarketValue`。因此，对于行业 PE / PB / PS 横截面估值，当前所需核心数据已经基本齐全；剩余风险主要是接入逻辑、少量新股覆盖缺口，以及异常字段校验。

### 2. CSMAR 派生指标尚未接入主估值链路

`个股日交易衍生指标` 已经被压缩为本地快照库，底层数据可以覆盖大部分 A 股的股息率、PE、PB、PS、PCF、换手率、流通市值等字段。

但当前主估值链路和报告层尚未接入该快照库。因此，在 UI 或报告中，`dividend_yield`、历史 PE / PB / PS 分位等字段仍可能显示“暂无”。这不再主要是“没有数据源”的问题，而是“本地数据源尚未接入现有 provider / valuation engine / report pipeline”的问题。

接入时应优先读取 `latest_non_null_metrics`，避免直接使用 `latest_snapshot` 导致股息率这类非每日更新字段误判为空；历史分位计算则应读取 `monthly_snapshots`。

### 3. “暂无”的原因披露还不够细

报告层目前仍可能把不同原因的“暂无”混在一起，例如：

```text
亏损导致 PE 无效
历史样本不足
价格缺失
股本缺失
财务字段缺失
股息数据缺失
行业同行有效样本不足
```

后续报告层需要把这些原因拆开展示，避免用户误以为是同一个数据问题。

### 4. MiniQMT 数据同步仍偏手工

目前已经验证手工同步完整版 QMT 数据到 MiniQMT `userdata_mini\datadir` 是有效的，但仓库内尚未形成一个带备份、校验、复验的一键脚本。

## 后续必要开发计划

### P0. 接入 EVA_Structure 本地股本 / 市值数据

新增本地 CSMAR 股本数据 provider，将 `EVA_Structure.csv` 清洗成可快速查询的本地 SQLite 或缓存表。

第一阶段目标：

```text
1. 按 Symbol + EndDate 读取最新期记录。
2. 输出 normalized_symbol、as_of、total_volume、market_cap、equity_per_share。
3. 在 QMT TotalVolume 为 0 或缺失时，优先用 EVA_Structure 的 TotalShares 补齐。
4. 行业同行预检也使用同一套本地股本补充逻辑。
5. 只有本地 EVA_Structure 不覆盖时，才调用 AKShare 网络 fallback。
```

接入后，行业 PE / PB / PS 分位的数据基础应基本完整。

### P0. 接入 CSMAR 个股日交易衍生指标快照库

新增本地 CSMAR 日交易衍生指标 provider，读取 `storage/reference/csmar_daily_derived_snapshots.sqlite`，并接入估值与报告链路。

第一阶段目标：

```text
1. 按 normalized_symbol 读取 latest_non_null_metrics。
2. 补充 dividend_yield、pe、pb、pcf、ps、turnover、circulated_market_value 等当前指标。
3. 行业历史分位需要历史样本时，读取 monthly_snapshots，而不是扫描原始 CSV。
4. 对每个字段记录 value_date，避免使用过旧指标时没有提示。
5. 在 provider_run_log 和 source_metadata 中记录来源为 local_csmar_daily_derived。
6. 该 provider 失败时不阻断主流程，只返回结构化 warning。
```

接入后，报告中的股息率和 PE / PB / PS 历史分位应优先使用本地 CSMAR 快照库；AKShare 更适合作为缺口补充，而不是第一来源。

### P1. 报告层“暂无原因”披露

为估值字段增加原因标记，至少覆盖：

```text
pe_ttm_missing_reason
ps_ttm_missing_reason
dividend_yield_missing_reason
industry_percentile_missing_reason
```

报告中应区分“亏损 / 样本不足 / 价格缺失 / 股本缺失 / 财务缺失 / 股息缺失”。

### P1. MiniQMT 数据同步脚本

新增一个安全的 PowerShell 维护脚本，用于把完整版 QMT 已下载数据同步到 MiniQMT `userdata_mini\datadir`。

最低要求：

```text
默认增量复制，不默认 /MIR
同步前提示关闭 QMT / MiniQMT 相关进程
同步前备份目标目录
同步后调用预检脚本复验
```

第一版脚本可以优先覆盖：

```text
Finance
SH\86400
SZ\86400
```

如后续确认 `DividData` 可被 QMT 接口稳定读取，再把股息率相关目录纳入同步范围。

### P2. 行业 provider fallback 配置整理

当前主要路径已经使用 local_csmar。后续需要清理或真正实现本地行业库不可用时的 fallback 策略，避免配置项误导。

建议明确为：

```text
local_csmar 不可用时：disabled
不建议默认回退到 QMT sector
```

### P2. LLM 输出瘦身验收

继续确保 LLM prompt / evidence bundle 不包含完整同行池，只保留：

```text
行业名称
行业代码
同行数量
有效样本数
估值分位
warning
少量代表性同行
```

完整同行列表只应留在内部计算或本地调试输出中，不应进入 LLM 上下文。

## 推荐推进顺序

```text
1. 接入 EVA_Structure 本地股本 / 市值数据
2. 接入 CSMAR 个股日交易衍生指标快照库
3. 报告层“暂无原因”披露
4. MiniQMT 数据同步脚本
5. provider fallback 配置整理
6. LLM 输出瘦身验收
```

当前最值得优先做的是接入 `EVA_Structure.csv` 和 `csmar_daily_derived_snapshots.sqlite`。前者解决股本 / 市值本地补充，后者解决股息率、估值倍数和历史分位样本的本地化查询。两者接入后，行业估值链路对 QMT 缓存和网络 fallback 的依赖会明显下降。
