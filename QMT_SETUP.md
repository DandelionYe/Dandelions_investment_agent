# QMT 接入指南

本文用于把本项目连接到本机 QMT 行情服务。这里的“成功接入”分三层：Python 能导入 `xtquant`、能连接 QMT 本地服务、项目能读取 QMT 日 K 数据。三层都通过后，项目才算真正走 QMT。

## 1. 前置条件

- Windows 本机已安装“迅投 QMT 极速交易系统交易终端”或兼容的 miniQMT/QMT 投研服务。
- QMT 客户端已登录。
- 项目虚拟环境已激活。

```powershell
cd J:\Dandelions_investment_agent
.\.venv\Scripts\Activate.ps1
```

## 2. 安装 xtquant

```powershell
python -m pip install xtquant
```

验证 Python 包是否可用：

```powershell
python -c "from xtquant import xtdata; print('xtquant ok', xtdata)"
```

如果这里报 `ModuleNotFoundError: No module named 'xtquant'`，说明还停在 Python 包安装阶段，项目不可能调用 QMT。

## 3. 启动 QMT mini 服务

示例路径如下，按本机实际安装路径调整。不要把自己的真实安装路径、账号目录或券商账号信息写入公开仓库：

```powershell
Start-Process "D:\path\to\QMT\bin.x64\XtMiniQmt.exe"
```

检查进程：

```powershell
Get-Process XtMiniQmt,miniquote,minibroker -ErrorAction SilentlyContinue
```

检查默认端口：

```powershell
Get-NetTCPConnection -LocalPort 58609,58610 -ErrorAction SilentlyContinue
```

正常情况下，`58610` 可能处于 `Listen` 状态。

## 4. 验证 QMT 服务连接

```powershell
python -c "from xtquant import xtdata; xtdata.connect(); print('connected'); print(xtdata.get_data_dir()); print(xtdata.get_instrument_detail('600519.SH'))"
```

成功时应看到类似信息：

```text
xtdata连接成功
服务地址: 127.0.0.1:58610
数据路径: ...\userdata_mini\datadir
connected
{'ExchangeID': 'SH', 'InstrumentID': '600519', 'InstrumentName': '贵州茅台', ...}
```

如果报：

```text
无法连接xtquant服务，请检查QMT-投研版或QMT-极简版是否开启
```

说明 `xtquant` 包已安装，但本地 QMT 服务没有连上。此时先处理 QMT 客户端、miniQMT 服务、登录状态和端口，不要改投研代码。

## 5. 下载并验证日 K 行情

项目当前读取 QMT 的日 K、成交量、成交额。首次使用某个标的前，建议先下载历史数据：

```powershell
python -c "from xtquant import xtdata; xtdata.connect(); xtdata.download_history_data('600519.SH', '1d', '20250101', ''); data = xtdata.get_market_data_ex(['time','close','amount','volume'], ['600519.SH'], '1d', '20250101', '', -1, 'front', True); print(data); print(data.get('600519.SH').tail() if isinstance(data, dict) and '600519.SH' in data else '')"
```

成功时会看到类似：

```text
{'600519.SH':                    time     close  volume        amount
...
[215 rows x 4 columns]}
```

如果返回空 DataFrame 或项目报 `QMT 行情数据为空`，说明服务已经连上，但本地日 K 数据还没有准备好。先下载对应标的和周期的数据。

项目代码也内置了自动补下载：当 `--data-source qmt` 且首次读取日 K 为空时，会自动调用一次 `xtdata.download_history_data()`，然后再读取一次。可以在 `.env` 中调整行为：

```text
QMT_AUTO_DOWNLOAD=true
QMT_HISTORY_DAYS=420
QMT_HISTORY_START=
QMT_HISTORY_END=
QMT_PERIOD=1d
QMT_DIVIDEND_TYPE=front
QMT_SUPPRESS_HELLO=true
```

如果你希望完全手动管理 QMT 本地数据，可设置：

```text
QMT_AUTO_DOWNLOAD=false
```

## 6. 验证项目是否真正走 QMT

```powershell
python main.py --symbol 600519.SH --data-source qmt --no-llm --no-pdf
```

成功走 QMT 时，输出 JSON 应包含：

```json
{
  "data_source": "qmt",
  "data_source_chain": ["qmt"],
  "price_data": {
    "data_vendor": "qmt"
  },
  "source_metadata": {
    "price_data": {
      "source": "qmt",
      "vendor": "qmt"
    }
  }
}
```

同时 `source_metadata.qmt_status` 会记录本次 QMT 接入状态，例如：

```json
{
  "connected": true,
  "auto_download": true,
  "download_attempted": false,
  "history_start": "20250305",
  "history_end": "20260429",
  "period": "1d",
  "data_dir": "...\\userdata_mini\\datadir",
  "row_count": 215
}
```

如果看到：

```json
"data_source": "akshare",
"data_source_chain": ["qmt_failed", "akshare_fallback"]
```

说明项目没有成功读取 QMT 行情，已经回退到 AKShare。此时查看 `data_warnings` 中的失败原因。

## 7. 当前项目的 QMT 覆盖范围

已接入：

- 日 K 收盘价 `close`
- 成交量 `volume`
- 成交额 `amount`
- 基础证券信息 `get_instrument_detail`

尚未接入：

- 财务数据
- 估值分位
- 新闻、公告、政策事件
- QMT 下单或交易接口

因此当前报告中 `fundamental_data`、`valuation_data`、`event_data` 仍会标记为：

```json
"source": "mock_placeholder",
"confidence": 0.25
```

这表示它们只是保持 MVP 流程可运行的低置信度占位数据，不应当当作真实投研证据。

## 8. 常见问题

`scan_available_server_addr()` 返回空，但 `xtdata.connect()` 成功：

这是可以接受的。当前验证中出现过这种情况，最终仍连接到了默认地址 `127.0.0.1:58610`。

PowerShell 找不到 `xtquant`：

确认已经进入项目目录并激活虚拟环境：

```powershell
cd J:\Dandelions_investment_agent
.\.venv\Scripts\Activate.ps1
python -c "from xtquant import xtdata; print(xtdata)"
```

项目输出仍是 AKShare：

查看输出中的 `data_warnings`。如果是 `QMT 行情数据为空`，先执行第 5 步下载日 K。
