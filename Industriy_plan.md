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

在已同步完整版 QMT 数据到 MiniQMT `userdata_mini\datadir` 后，Finance 和 close 覆盖率已经明显改善；但 `total_volume` 仍可能不足。因此后续判断行业分位是否可用时，不能只看 Finance 和 K 线，还必须继续检查股本覆盖率。

### 2. 股息率仍未可靠实现

当前股息率不是 QMT 派生估值链路中的可靠字段。即使 PE / PB / PS 可用，`dividend_yield` 仍可能显示“暂无”。

后续需要明确股息率来源，例如 AKShare 估值接口、QMT 除权除息 / 分红数据，或本地分红数据表。

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

### P1. 股息率补充

实现可靠的 `dividend_yield` 来源，并允许补充来源覆盖当前值为 `None` 的字段。

建议优先级：

```text
1. 先接入 AKShare 估值接口中的股息率字段。
2. 保证 fallback 失败不阻断主流程。
3. 在 provider_run_log 和 source_metadata 中记录来源。
```

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
1. 股息率补充
2. 报告层“暂无原因”披露
3. MiniQMT 数据同步脚本
4. provider fallback 配置整理
5. LLM 输出瘦身验收
```

当前最值得优先做的是股息率补充。原因是行业分类、同行预检、价格缓存补齐、股本 fallback 都已基本落地；股息率是用户仍能直接看到“暂无”的主要剩余字段之一。
