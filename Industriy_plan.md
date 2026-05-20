# Dandelions_investment_agent 行业功能改造计划 v3

> 适用仓库：`DandelionYe/Dandelions_investment_agent`  
> 参考版本：本地commit 哈希值 '59b5070'（2026-05-19），并结合 2026-05-20 本机 QMT 财务缓存排查结果更新  
> 计划目标：将“行业分类与同行池”从 QMT sector 接口迁移到本地国泰安 `TRD_Co.csv` 清洗库；价格、股本、财务、同行估值输入继续优先使用 QMT，但必须先解决 MiniQMT 可读财务缓存不足的问题。

---

## 1. 结论摘要

本轮行业功能改造不应理解为“全面替换 QMT”。更合理的设计是：

```text
行业分类 / 同行池来源：local_csmar，也就是国泰安 TRD_Co 清洗后的本地库
同行价格 / 股本 / 财务 / 估值输入来源：qmt，但仅在 MiniQMT 可读缓存满足预检时启用
行业估值计算逻辑：继续沿用现有 IndustryValuationService
LLM 上下文输出：只输出行业摘要、样本数量、估值分位和 warning，不输出完整同行列表
```

这样做的好处是：

1. 避免继续依赖 QMT 的 sector 行业接口。
2. 保留 QMT 在行情、股本、财务数据方面的优势，但不再假设完整版 QMT 下载数据会自动被 MiniQMT 接口读取。
3. 不需要一次性重建完整行情财务数据库，只需要让 QMT peer loader 能稳定读到 MiniQMT 的本地财务缓存。
4. 降低 LLM token 占用，避免把大表或完整同行列表塞进 prompt。
5. 行业增强失败时仍然保持主研究流程可用。

2026-05-20 本机验证结论必须纳入方案边界：

```text
xtdata.connect() 当前连接：127.0.0.1:58610
MiniQMT 服务返回数据目录：
D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir

完整版 QMT 全量财务下载目录：
D:\迅投QMT极速交易系统交易终端 万联证券版\datadir\Finance

实测结果：
1. 完整版 datadir\Finance 中存在全量财务 .DAT 文件。
2. MiniQMT userdata_mini\datadir\Finance 中仅有少量财务 .DAT 文件。
3. xtdata.get_financial_data() 只返回 MiniQMT 可读缓存中的数据。
4. 设置 xtdata.data_dir 指向完整版 datadir 后，财务接口返回结果不变。
5. 因此，行业同行估值在第一阶段必须增加 QMT 财务缓存预检；缓存不足时只能输出 warning 或降级，不能静默给出行业分位。
```

---

## 2. 当前项目行业功能现状

在当前项目中，行业相关功能主要服务于“行业横截面估值增强”，不是单纯展示行业名称。

当前链路大致是：

```text
用户输入股票代码
    ↓
QMTIndustryProvider 通过 QMT sector 解析行业与行业成分
    ↓
IndustryValuationService 调用 peer valuation loader
    ↓
QMTPeerValuationLoader 批量读取同行价格、股本、财务数据
    ↓
计算 PE / PB / PS 行业分位
    ↓
写入 valuation_data，供后续报告使用
```

当前问题是：

1. QMT sector 行业接口并不稳定，也不一定符合用户希望采用的行业口径。
2. 行业自动下载已经默认关闭，但行业分类本身仍然强依赖 QMT sector 数据。
3. 用户已经拥有国泰安公司基本信息数据，其中包含更适合作为本地行业参考库的行业字段。

因此，下一步不应继续强化 QMT 行业接口，而应把行业分类与同行池解析从 QMT 中拆出来。

---

## 3. 新版总体设计

新版设计采用“双 provider”架构：

```text
IndustryClassificationProvider：负责回答“股票属于哪个行业、同行有哪些”
PeerValuationDataProvider：负责回答“这些同行的价格、市值、利润、收入、BPS 等估值输入是什么”
```

第一阶段采用：

```text
IndustryClassificationProvider = LocalCSMARIndustryProvider
PeerValuationDataProvider      = QMTPeerValuationLoader
```

也就是：

```text
国泰安 TRD_Co 清洗库：只负责行业分类与同行池
QMT：继续负责价格、股本、财务、估值输入
```

这必须写进代码注释、README 和配置说明中，避免后续 Agent 误解成“完全去 QMT 化”。

---

## 4. 本地国泰安行业库的职责边界

国泰安 `TRD_Co.csv` 这类公司基本信息文件适合承担：

```text
1. 股票代码标准化
2. 股票简称、公司名称
3. 上市状态过滤
4. 交易市场过滤
5. 当前 A 股股票池过滤
6. 当前行业分类
7. 行业名称
8. 行业成员列表
9. 行业样本数量
10. 行业口径版本记录
```

它不适合单独承担：

```text
1. 最新收盘价
2. 总市值
3. PE_TTM
4. PB_MRQ
5. PS_TTM
6. 净利润 TTM
7. 营业收入 TTM
8. 每股净资产 BPS
9. 停牌状态
10. 最新交易日期
```

这些字段第一阶段仍由 QMT 提供。

---

## 5. QMT 继续保留的字段职责

本项目仍然可以、也应该继续优先使用 QMT 获取以下字段。

但这里的“QMT”必须更精确地定义为：`xtquant.xtdata` 当前连接的 MiniQMT 服务及其返回的 `userdata_mini\datadir`。完整版 QMT 界面中通过“数据管理/补充数据”下载到根目录 `datadir\Finance` 的文件，实测不会被 `xtdata.get_financial_data()` 自动读取。

因此，后续实现中必须把 QMT 数据能力拆成两个状态：

```text
qmt_connected              MiniQMT 本地服务可连接
qmt_finance_cache_ready    MiniQMT 可读财务缓存覆盖目标股票池或目标同行池
```

`qmt_connected=true` 只能说明接口连通；不能说明同行财务数据可用于 PE/PB/PS 行业分位。

### 5.1 行情价格类

```text
close             最新收盘价
pre_close         前收盘价
volume            成交量
amount            成交额
price_history     历史价格序列
trade_date        交易日期
```

### 5.2 股本与证券基础信息类

```text
instrument_name   证券名称
exchange_id       交易所 ID
instrument_id     证券 ID
product_id        产品类型
total_volume      总股本
float_volume      流通股本
```

### 5.3 财务基本面类

```text
report_period                 报告期
ann_date                      公告日期
currency                      币种
roe                           净资产收益率
roe_weighted                  加权 ROE
gross_margin                  毛利率
net_margin                    净利率
revenue_growth                营收增长率
net_profit_growth             净利润增长率
deducted_net_profit_growth    扣非净利润增长率
operating_cashflow_quality    经营现金流质量
debt_ratio                    资产负债率
current_ratio                 流动比率
eps                           每股收益
bps                           每股净资产
revenue_ttm                   营业收入 TTM
net_profit_ttm                净利润 TTM
operating_cashflow_ttm        经营现金流 TTM
```

### 5.4 行业同行估值输入类

行业估值分位计算最核心需要：

```text
symbol            股票代码
name              股票简称
asset_type        资产类型
close             最新收盘价
total_volume      总股本
float_volume      流通股本
net_profit_ttm    净利润 TTM
revenue_ttm       营业收入 TTM
bps               每股净资产
is_st             是否 ST
is_suspended      是否停牌
```

根据这些字段可派生：

```text
market_cap = close * total_volume
pe_ttm     = market_cap / net_profit_ttm
pb_mrq     = close / bps
ps_ttm     = market_cap / revenue_ttm
```

因此，方案中必须明确：**本地行业库不负责提供这些估值输入字段，同行估值输入仍由 QMT 读取。**

同时必须明确：**同行估值输入只在 MiniQMT 可读财务缓存足够时才视为可用。** 若缓存不足，应返回：

```text
industry_valuation_warnings += [
  "qmt_finance_cache_insufficient_for_peer_valuation"
]
```

并保留 `industry_valid_peer_count_pe/pb/ps`，样本不足时不输出强结论。

---

## 6. 国泰安 TRD_Co 数据清理方案

### 6.1 输入文件

```text
TRD_Co.csv
```

当前文件已经位于仓库根目录，编码为 `utf-8-sig`，字段包含：

```text
Stkcd, Stknme, Listdt, Conme, Indcd, Indnme,
Nindcd, Nindnme, Nnindcd, Nnindnme,
IndcdZX, IndnmeZX,
PROVINCE, CITY, OWNERSHIPTYPE,
Curtrd, Sctcd, Statco, Statdt, Markettype, FormerCode
```

正式构建时建议仍迁移或复制到：

```text
data/raw/csmar/TRD_Co.csv
```

构建脚本应支持 `--input TRD_Co.csv` 和 `--input data/raw/csmar/TRD_Co.csv` 两种路径，避免开发阶段因为文件位置阻塞。

### 6.2 输出文件

推荐输出为 SQLite：

```text
storage/reference/csmar_industry.sqlite
storage/reference/csmar_industry_build_report.md
```

不建议运行时直接读取原始 CSV。理由是：

1. 原始 CSV 字段过多。
2. 包含退市、历史、非当前交易股票。
3. 不利于快速查询单票行业和行业成员。
4. 容易被错误塞进 LLM 上下文。
5. SQLite 无需额外服务，适合本地投研系统。

### 6.3 股票范围过滤规则

默认保留当前人民币交易 A 股：

```text
Curtrd == CNY
Markettype in 1, 4, 16, 32, 64
Statco != D
```

当前 `TRD_Co.csv` 中，`Statco` 的实测分布为：

```text
A    5578
D     365
N      20
```

不能简单使用 `Statco == A`，因为样例中仍在交易的特殊状态股票可能标记为 `N`。第一阶段推荐规则是：

```text
is_active = Statco in {"A", "N"}
is_delisted = Statco == "D"
```

构建报告必须记录 `A/N/D` 各自数量。按当前文件过滤：

```text
Curtrd == CNY
Markettype in {1, 4, 16, 32, 64}
Statco != D
```

得到约 `5519` 条当前 A 股记录，其中 `A=5500`、`N=19`。若后续发现 `N` 不是可交易状态，再通过配置收紧过滤，不应在第一版硬编码剔除。

其中：

```text
1   上交所 A 股
4   深交所 A 股
16  创业板
32  科创板
64  北交所
```

如短期不处理北交所，可以配置：

```text
LOCAL_CSMAR_INDUSTRY_UNIVERSE=sh_sz
```

长期建议支持：

```text
LOCAL_CSMAR_INDUSTRY_UNIVERSE=sh_sz_bj
```

### 6.4 股票代码标准化

原始 `Stkcd` 统一补齐 6 位：

```text
1      → 000001
858    → 000858
600519 → 600519
```

生成 QMT 可识别的标准 symbol：

```text
Sctcd=1 → .SH
Sctcd=2 → .SZ
Sctcd=3 → .BJ
```

示例：

```text
000858 → 000858.SZ
600519 → 600519.SH
430047 → 430047.BJ
```

这是关键要求。否则本地行业库能找到同行，但 QMT 无法读取同行价格和财务数据。

---

## 7. 行业字段口径选择

### 7.1 主口径

建议主口径使用：

```text
IndcdZX  → primary_industry_code
IndnmeZX → primary_industry_name
```

理由：它更适合作为当前投研使用的现行行业口径。

### 7.2 备用口径

保留：

```text
Nnindcd  → alt_industry_code
Nnindnme → alt_industry_name
```

用途：

1. 主行业字段缺失时 fallback。
2. 未来对比行业口径差异。
3. 保留数据可解释性。

### 7.3 不建议作为主口径

不建议使用：

```text
Indcd / Indnme
```

原因是它过粗，对同行估值和投研分析帮助有限。

### 7.4 上级行业回退

从 `primary_industry_code` 提取首字母作为行业门类：

```text
C15 → C
I65 → I
J66 → J
K70 → K
```

当细分行业样本不足时，可以回退到上级门类，但报告中必须明确披露：

```text
细分行业样本不足，本次行业估值分位使用上级行业口径。
```

不能静默回退。

---

## 8. 清洗后字段设计

清洗后的行业参考库只保留运行时必要字段。

### 8.1 securities 表

```text
symbol                       标准证券代码，例如 000858.SZ
symbol_qmt                   QMT 可识别代码，第一阶段与 symbol 相同
stkcd                        6 位股票代码
exchange                     SH / SZ / BJ
market_type                  原始 Markettype
board                        主板 / 创业板 / 科创板 / 北交所
short_name                   股票简称
company_name                 公司全称
list_date                    上市日期
status_code                  状态代码
status_date                  状态日期
is_active                    是否当前正常上市
is_delisted                  是否退市
is_a_share                   是否 A 股
is_st_name                   简称是否包含 ST
primary_industry_code        主行业代码
primary_industry_name        主行业名称
alt_industry_code            备用行业代码
alt_industry_name            备用行业名称
industry_section_code        行业门类代码
industry_section_name        行业门类名称
province                     省份
city                         城市
ownership_type               所有制类型
source_file                  来源文件名
source_hash                  来源文件 hash
source_row_hash              单行 hash，用于后续增量比对
snapshot_date                构建日期
```

### 8.2 industry_members 表

```text
industry_level               ZX / SECTION
industry_code                行业代码
industry_name                行业名称
symbol                       标准证券代码
short_name                   股票简称
is_active                    是否当前正常上市
is_st_name                   是否 ST
board                        板块
```

### 8.3 metadata 表

```text
key
value
```

至少记录：

```text
source_file
source_hash
build_time
raw_rows
active_a_share_rows
industry_count
section_count
min_peer_threshold
universe
```

---

## 9. 新增代码模块设计

### 9.1 新增构建脚本

新增：

```text
scripts/build_csmar_industry_reference.py
```

职责：

```text
1. 读取 TRD_Co.csv 或 data/raw/csmar/TRD_Co.csv
2. 检查必要字段是否存在
3. 标准化股票代码
4. 过滤当前 A 股股票池，默认保留 Statco in {"A", "N"}
5. 生成 SQLite 行业参考库
6. 生成构建报告
7. 输出行业样本统计
```

命令示例：

```powershell
python scripts/build_csmar_industry_reference.py ^
  --input data/raw/csmar/TRD_Co.csv ^
  --output storage/reference/csmar_industry.sqlite ^
  --universe sh_sz_bj ^
  --industry-level ZX
```

### 9.2 新增 LocalCSMARIndustryProvider

新增：

```text
services/data/providers/local_csmar_industry_provider.py
```

核心方法：

```python
resolve_industry(symbol: str) -> dict
```

返回结构应与现有 QMTIndustryProvider 尽量兼容：

```python
{
    "industry_level": "CSMAR_ZX",
    "industry_code": "C15",
    "industry_name": "酒、饮料和精制茶制造业",
    "industry_members": ["000858.SZ", "600519.SH"],
    "peer_count": 38,
    "source": "local_csmar_trd_co",
    "snapshot_date": "2026-05-19",
    "fallback_used": False,
    "fallback_reason": None,
}
```

如果使用上级行业回退：

```python
{
    "industry_level": "CSMAR_SECTION",
    "industry_code": "C",
    "industry_name": "制造业",
    "industry_members": [...],
    "peer_count": 3000,
    "source": "local_csmar_trd_co",
    "fallback_used": True,
    "fallback_reason": "primary_industry_peer_count_below_threshold",
}
```

### 9.3 新增 industry provider factory

新增或修改：

```text
services/data/providers/industry_provider_factory.py
```

根据配置返回：

```text
local_csmar → LocalCSMARIndustryProvider
qmt         → QMTIndustryProvider
disabled    → 不做行业估值增强
```

### 9.4 新增 QMT 财务缓存预检脚本

新增：

```text
scripts/check_qmt_finance_cache.py
```

职责：

```text
1. 连接 xtquant.xtdata。
2. 打印 xtdata.get_data_dir() 返回的 MiniQMT 数据目录。
3. 对目标股票池或目标同行池调用 get_financial_data。
4. 统计 Balance / Income / CashFlow / PershareIndex 的覆盖率、最新报告期、最新公告日。
5. 输出 machine-readable JSON 和人类可读 Markdown。
6. 当覆盖率低于阈值时返回非 0 exit code，供集成测试或手工验收使用。
```

命令示例：

```powershell
.\.venv\Scripts\python.exe scripts/check_qmt_finance_cache.py ^
  --symbols 600410.SH,002624.SZ,000419.SZ ^
  --tables Balance,Income,CashFlow,PershareIndex ^
  --start 20100101 ^
  --end 20260520 ^
  --min-coverage 0.8
```

### 9.5 可选新增 QMT 财务缓存同步脚本

新增：

```text
scripts/sync_qmt_finance_cache.ps1
```

职责：

```text
1. 校验完整版 QMT Finance 源目录存在。
2. 校验 MiniQMT Finance 目标目录存在或可创建。
3. 提醒用户关闭 XtMiniQmt / miniquote / XtItClient / QMT 主程序。
4. 备份目标 Finance 目录。
5. 使用 robocopy 将完整版 datadir\Finance 同步到 userdata_mini\datadir\Finance。
6. 同步后提示重启 MiniQMT，并调用 check_qmt_finance_cache.py 复验。
```

脚本默认应采用“增量复制”而不是强制镜像删除：

```powershell
robocopy "$FullFinanceDir" "$MiniFinanceDir" /E /XO /R:2 /W:1
```

只有在用户显式传入 `-Mirror` 且已经完成备份时，才允许使用：

```powershell
robocopy "$FullFinanceDir" "$MiniFinanceDir" /MIR /R:2 /W:1
```

---

## 10. 配置项设计

建议新增以下配置：

```env
# 行业分类来源：local_csmar / qmt / disabled
INDUSTRY_CLASSIFICATION_PROVIDER=local_csmar

# 同行估值数据来源：第一阶段继续使用 qmt
INDUSTRY_PEER_DATA_PROVIDER=qmt

# 本地国泰安行业库
LOCAL_CSMAR_INDUSTRY_DB=storage/reference/csmar_industry.sqlite
LOCAL_CSMAR_INDUSTRY_LEVEL=ZX
LOCAL_CSMAR_INDUSTRY_UNIVERSE=sh_sz_bj
LOCAL_CSMAR_INDUSTRY_MIN_PEERS=20
LOCAL_CSMAR_INDUSTRY_FALLBACK_TO_SECTION=true

# QMT 行业自动下载保持关闭，因为行业分类不再依赖 QMT sector
QMT_INDUSTRY_AUTO_DOWNLOAD=false

# QMT 同行财务自动下载默认关闭，优先读取本地 QMT 已有财务数据
QMT_INDUSTRY_FINANCIAL_AUTO_DOWNLOAD=false

# MiniQMT 当前服务返回的数据目录，通常由 xtdata.get_data_dir() 自动发现
QMT_MINI_DATADIR=

# 完整版 QMT 下载目录，仅用于手工/脚本同步，不直接传给 get_financial_data
QMT_FULL_DATADIR=

# 是否在行业估值前检查 MiniQMT 财务缓存覆盖率
QMT_FINANCE_CACHE_PREFLIGHT=true
QMT_FINANCE_CACHE_MIN_COVERAGE=0.8

# 财务缓存同步策略：none / manual_copy / robocopy
QMT_FINANCE_CACHE_SYNC_MODE=none
```

兼容性处理：

```text
如果 INDUSTRY_CLASSIFICATION_PROVIDER 未设置：默认 qmt，保持历史行为。
如果设置为 local_csmar 但 SQLite 不存在：记录 warning，并降级为 qmt 或 disabled，具体由配置控制。
如果设置为 disabled：跳过行业估值增强，主流程继续。
```

可选新增：

```env
INDUSTRY_CLASSIFICATION_FALLBACK_PROVIDER=qmt
```

含义：本地行业库不可用时是否回退 QMT。建议第一阶段默认：

```env
INDUSTRY_CLASSIFICATION_FALLBACK_PROVIDER=disabled
```

这样可以避免又悄悄回到不稳定的 QMT sector。

QMT 财务缓存相关配置的处理原则：

```text
1. QMT_MINI_DATADIR 为空时，运行时以 xtdata.get_data_dir() 为准。
2. QMT_FULL_DATADIR 只用于同步工具，不能误以为 get_financial_data 会读取它。
3. QMT_FINANCE_CACHE_PREFLIGHT=true 时，行业估值前先检查目标同行池财务覆盖率。
4. 覆盖率不足时，行业估值降级为 warning，不触发同步下载，不阻断主流程。
5. 不在主研究流程中同步调用 xtdata.download_financial_data 批量下载同行财务数据；该接口可能耗时较长或卡住。
```

---

## 11. IndustryValuationService 改造方案

当前逻辑应从：

```python
self.industry_provider = industry_provider or QMTIndustryProvider()
```

调整为：

```python
self.industry_provider = industry_provider or create_industry_provider()
self.peer_valuation_loader = peer_valuation_loader or create_peer_valuation_loader()
```

第一阶段：

```text
create_industry_provider()       → LocalCSMARIndustryProvider
create_peer_valuation_loader()   → QMTPeerValuationLoader
```

这一步的重点是解耦，而不是重写估值算法。

新增 QMT 财务缓存预检逻辑：

```text
1. LocalCSMARIndustryProvider 先返回完整同行池。
2. IndustryValuationService 对同行池做数量截断/批量分片，避免一次性请求过大。
3. 若 QMT_FINANCE_CACHE_PREFLIGHT=true，先用 check_qmt_finance_cache 同等逻辑抽样或全量检查同行财务覆盖率。
4. 覆盖率达到阈值，才调用 QMTPeerValuationLoader 计算 PE/PB/PS 分位。
5. 覆盖率不足，跳过分位计算，返回行业信息、peer_count、valid_peer_count=0 和 warning。
```

示例 warning：

```json
{
  "industry_source": "local_csmar_trd_co",
  "industry_peer_count": 38,
  "industry_valid_peer_count_pe": 0,
  "industry_valid_peer_count_pb": 0,
  "industry_valid_peer_count_ps": 0,
  "industry_valuation_warnings": [
    "qmt_finance_cache_insufficient_for_peer_valuation",
    "mini_qmt_finance_dir_missing_peer_files"
  ]
}
```

### 11.1 QMT 财务缓存同步与 MiniQMT 补充入口判断

本机排查结论：

```text
完整版 QMT 可通过“操作 - 数据管理 - 补充数据”或“智能下载/批量下载”补充财务数据。
MiniQMT 功能说明文档没有发现等价的“数据管理/补充数据”界面入口。
xtquant 提供 download_financial_data 接口，但实测单票 4 表下载 180 秒未返回，不适合放进主研究流程。
```

因此第一阶段按以下策略处理：

```text
1. 把“完整版 QMT 下载财务数据”视为可用的源数据。
2. 把“MiniQMT userdata_mini\datadir\Finance”视为 xtdata.get_financial_data 的唯一可靠读取目标。
3. 通过停机后的文件同步，把完整版 datadir\Finance 补到 MiniQMT userdata_mini\datadir\Finance。
4. 同步完成后重启 MiniQMT，再用 check_qmt_finance_cache.py 验证接口是否能读到。
```

推荐同步命令模板：

```powershell
$full = 'D:\迅投QMT极速交易系统交易终端 万联证券版\datadir\Finance'
$mini = 'D:\迅投QMT极速交易系统交易终端 万联证券版\userdata_mini\datadir\Finance'

# 先关闭 QMT / XtMiniQmt / miniquote / XtItClient，再执行。
robocopy $full $mini /E /XO /R:2 /W:1
```

如果需要完全镜像，必须先备份目标目录，再使用 `/MIR`：

```powershell
robocopy $full $mini /MIR /R:2 /W:1
```

`/MIR` 会删除目标中源目录不存在的文件，只能在确认两个目录属于同一 QMT 版本、同一券商安装包且已备份后使用。

---

## 12. LLM 上下文控制方案

禁止把完整行业成员列表直接交给 LLM。

内部计算可以使用完整同行池，但进入 LLM prompt 的内容只允许是摘要：

```json
{
  "industry_source": "local_csmar_trd_co",
  "industry_level": "CSMAR_ZX",
  "industry_code": "C15",
  "industry_name": "酒、饮料和精制茶制造业",
  "industry_peer_count": 38,
  "industry_valid_peer_count_pe": 31,
  "industry_valid_peer_count_pb": 34,
  "industry_valid_peer_count_ps": 30,
  "industry_pe_percentile": 0.72,
  "industry_pb_percentile": 0.81,
  "industry_ps_percentile": 0.66,
  "industry_valuation_label": "industry_expensive",
  "fallback_used": false,
  "industry_valuation_warnings": []
}
```

可选展示代表性同行：

```json
{
  "sample_peers": [
    {"symbol": "600519.SH", "name": "贵州茅台"},
    {"symbol": "000568.SZ", "name": "泸州老窖"},
    {"symbol": "600809.SH", "name": "山西汾酒"}
  ]
}
```

代表性同行最多 5 个，不允许输出完整同行池。

---

## 13. 实现阶段划分

### 阶段 0：文档和配置修正

目标：先消除误导。

任务：

```text
1. README 中如仍有 QMT_INDUSTRY_AUTO_DOWNLOAD=true 示例，改为 false。
2. 明确说明 QMT 行业自动下载默认关闭。
3. 增加“行业分类来源”和“同行估值数据来源”两层概念说明。
4. 增加 QMT 财务缓存目录说明：完整版 datadir\Finance 需要同步到 MiniQMT userdata_mini\datadir\Finance 后，get_financial_data 才可能读到。
5. 增加 MiniQMT 财务缓存预检命令，避免行业估值样本不足时静默输出错误分位。
```

### 阶段 1：构建本地行业参考库

目标：把 TRD_Co.csv 转成稳定、窄字段、可快速查询的 SQLite。

交付：

```text
scripts/build_csmar_industry_reference.py
storage/reference/csmar_industry.sqlite
storage/reference/csmar_industry_build_report.md
scripts/check_qmt_finance_cache.py
```

验收标准：

```text
1. 可输入 000858.SZ 查询到行业代码和行业名称。
2. 可返回该行业全部成员。
3. 可统计行业样本数量。
4. 构建报告记录原始行数、保留行数、行业数量、缺失值数量。
5. 当前 TRD_Co.csv 过滤后约保留 5519 条当前 A 股记录，实际数量写入构建报告。
```

### 阶段 2：新增 LocalCSMARIndustryProvider

目标：用本地库替代 QMT sector 做行业分类。

交付：

```text
services/data/providers/local_csmar_industry_provider.py
services/data/providers/industry_provider_factory.py
```

验收标准：

```text
1. resolve_industry("000858.SZ") 返回行业和成员。
2. 返回结构与 QMTIndustryProvider 兼容。
3. SQLite 不存在时不阻塞主流程。
4. 行业成员 symbol 可直接传给 QMT peer loader。
```

### 阶段 3：接入现有行业估值流程

目标：使用本地行业池 + QMT 估值输入。

交付：

```text
IndustryValuationService 支持 LocalCSMARIndustryProvider + QMTPeerValuationLoader
```

验收标准：

```text
1. 行业分类来源显示为 local_csmar_trd_co。
2. 同行价格、股本、财务数据仍由 QMT 读取。
3. MiniQMT 财务缓存覆盖率达标时，能计算 PE / PB / PS 行业分位。
4. 行业增强失败不阻断主研究流程。
5. MiniQMT 财务缓存不足时，只输出 warning 和有效样本数，不输出强分位结论。
```

### 阶段 4：LLM 输出瘦身

目标：控制 token，占用最小上下文。

验收标准：

```text
1. LLM prompt 不包含完整 industry_members。
2. 只包含行业摘要和估值分位结果。
3. 最多展示 5 个代表性同行。
```

### 阶段 5：后续扩展 CSMAR peer valuation loader

这不是第一阶段任务。

只有当你后续导出以下国泰安文件后，再考虑：

```text
日行情 / 估值指标文件
财务指标文件
利润表摘要
资产负债表摘要
现金流量表摘要
```

届时可新增：

```text
LocalCSMARPeerValuationLoader
```

用于逐步替代 QMT 同行估值输入。

---

## 14. 测试计划

### 14.1 构建脚本测试

```text
1. Stkcd 能补齐 6 位。
2. Sctcd 能正确映射 SH / SZ / BJ。
3. Statco == D 的股票被剔除，Statco == A/N 的股票默认保留。
4. Curtrd != CNY 的证券被剔除。
5. Markettype 过滤正确。
6. 缺失行业字段时有 warning。
7. 输出 SQLite 表结构正确。
8. 构建报告记录 Statco、Markettype、行业字段缺失数量。
```

### 14.2 LocalCSMARIndustryProvider 测试

```text
1. 正常股票能返回行业。
2. 不存在股票返回 ProviderError 或明确 warning。
3. 行业成员数量正确。
4. 细分行业样本不足时可 fallback。
5. fallback_used 和 fallback_reason 正确。
```

### 14.3 集成测试

```text
1. INDUSTRY_CLASSIFICATION_PROVIDER=local_csmar 时，不调用 QMTIndustryProvider。
2. INDUSTRY_PEER_DATA_PROVIDER=qmt 时，仍调用 QMTPeerValuationLoader。
3. 行业库不存在时，主流程不崩。
4. use_llm=False 快速管道可越过 30%。
5. 正常 LLM 分析可生成报告。
6. QMT_FINANCE_CACHE_PREFLIGHT=true 且缓存不足时，不调用行业分位强计算，返回 qmt_finance_cache_insufficient warning。
7. 完整版 datadir\Finance 同步到 MiniQMT userdata_mini\datadir\Finance 后，check_qmt_finance_cache.py 能读到测试股票财务表。
```

### 14.4 LLM 上下文测试

```text
1. prompt 中不包含完整同行列表。
2. prompt 中包含行业代码、行业名称、peer_count、valid_peer_count、估值分位。
3. warning 能正常进入报告依据。
```

---

## 15. 风险与处理

### 风险 1：本地行业库过期

处理：

```text
构建报告记录 source_hash 和 snapshot_date。
报告中显示 industry_source_snapshot_date。
定期重新从国泰安导出 TRD_Co 并重建 SQLite。
```

### 风险 2：行业口径与市场常用口径不一致

处理：

```text
明确标记 industry_source=local_csmar_trd_co。
保留 primary 和 alt 两套行业字段。
后续可支持申万、中信、证监会等多口径切换。
```

### 风险 3：细分行业样本过少

处理：

```text
LOCAL_CSMAR_INDUSTRY_MIN_PEERS=20
LOCAL_CSMAR_INDUSTRY_FALLBACK_TO_SECTION=true
报告中明确披露 fallback。
```

### 风险 4：本地行业成员代码与 QMT 不兼容

处理：

```text
构建时生成 symbol_qmt。
集成测试随机抽样行业成员并调用 QMT peer loader 验证。
```

### 风险 5：QMT 同行财务数据不完整

处理：

```text
行业估值结果中保留 valid_peer_count_pe / pb / ps。
样本不足时只输出 warning，不强行给分位结论。
新增 QMT 财务缓存预检，不把 qmt_connected 误判为 qmt_finance_cache_ready。
```

### 风险 6：完整版 QMT 财务数据与 MiniQMT 财务接口目录分离

处理：

```text
文档明确记录：
完整版 QMT 下载目录是 datadir\Finance。
MiniQMT 接口读取目录是 userdata_mini\datadir\Finance。
第一阶段通过停机文件同步解决，不依赖 xtdata.data_dir 切换财务读取目录。
同步后必须用 get_financial_data 复验。
```

### 风险 7：MiniQMT 无可见财务补充入口

处理：

```text
不把 MiniQMT 界面补充数据作为方案依赖。
完整版 QMT 的“操作 - 数据管理 - 补充数据”和“智能下载/批量下载”是目前文档可确认的补充入口。
xtdata.download_financial_data 作为手工诊断工具保留，不进入主研究流程。
```

---

## 16. 最终推荐路线

第一阶段不要做“完全替换 QMT”。推荐路线是：

```text
1. 本地国泰安 TRD_Co → 清洗成 SQLite 行业参考库。
2. 新增 LocalCSMARIndustryProvider。
3. 行业分类与同行池改用 local_csmar。
4. 同步或预检 MiniQMT 可读 QMT 财务缓存。
5. 同行估值输入继续用 QMT，但只在财务缓存覆盖率达标时输出行业分位。
6. 行业估值计算沿用现有 IndustryValuationService。
7. LLM 只读取行业摘要，不读取完整行业成员表。
```

一句话概括：

```text
用本地国泰安库替代 QMT 的行业分类；QMT 继续提供行情、股本、财务和估值输入，但必须把 MiniQMT 财务缓存覆盖率作为行业估值的前置条件。
```

这就是当前最稳、风险最低、收益最高的改造方案。
