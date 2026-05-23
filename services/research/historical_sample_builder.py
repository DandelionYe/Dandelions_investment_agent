"""Phase 2B: 真实历史样本构建器。

从 QMT/xtdata 获取真实历史行情，计算 forward metrics，
构建带 provenance 的历史样本池。

不依赖 LLM、Redis、网络（QMT 为本地服务）。
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Provider enrichment (lazy imports to avoid circular deps) ─────


def _get_csmar_provider():
    from services.data.providers.local_csmar_daily_derived_provider import (
        LocalCSMARDailyDerivedProvider,
        is_csmar_daily_derived_enabled,
    )
    if not is_csmar_daily_derived_enabled():
        return None
    return LocalCSMARDailyDerivedProvider()


def _get_eva_provider():
    from services.data.providers.local_csmar_eva_structure_provider import (
        LocalCSMAREVAStructureProvider,
        is_eva_structure_enabled,
    )
    if not is_eva_structure_enabled():
        return None
    return LocalCSMAREVAStructureProvider()


def _get_industry_provider():
    try:
        from services.data.providers.local_csmar_industry_provider import (
            LocalCSMARIndustryProvider,
        )
        return LocalCSMARIndustryProvider()
    except Exception:
        return None


def _compute_percentile_from_values(current: float, values: list[float]) -> float:
    """Fraction of *values* that are <= current."""
    if not values:
        return 0.5
    below = sum(1 for v in values if v <= current)
    return below / len(values)


def enrich_valuation_from_csmar(
    symbol: str,
    as_of: str,
    close: float | None,
) -> tuple[dict[str, Any], str]:
    """Query CSMAR monthly_snapshots for PE/PB/PS/dividend_yield at as_of.

    Returns (valuation_data, source_label).
    source_label is one of: 'local_csmar_daily_derived', 'missing'.
    """
    provider = _get_csmar_provider()
    if provider is None:
        return {}, "missing"

    # Get the latest snapshot on or before as_of
    result = provider.get_as_of_metrics(
        symbol, as_of, metrics=["pe", "pb", "pcf", "ps", "dividend_yield"]
    )
    if not result.metadata.success or not result.data.get("pe"):
        return {}, "missing"

    data = result.data
    pe = data.get("pe")
    pb = data.get("pb")
    ps = data.get("ps")
    dividend_yield = data.get("dividend_yield")

    valuation: dict[str, Any] = {}
    if pe is not None and pe > 0:
        valuation["pe_ttm"] = round(float(pe), 4)
    if pb is not None and pb > 0:
        valuation["pb_mrq"] = round(float(pb), 4)
    if ps is not None and ps > 0:
        valuation["ps_ttm"] = round(float(ps), 4)
    if dividend_yield is not None:
        valuation["dividend_yield"] = round(float(dividend_yield), 6)

    valuation["_csmar_trading_date"] = data.get("trading_date")

    # Compute percentiles from historical monthly snapshots
    _enrich_valuation_percentiles(provider, symbol, as_of, valuation)

    return valuation, "local_csmar_daily_derived"


def _enrich_valuation_percentiles(
    provider,
    symbol: str,
    as_of: str,
    valuation: dict[str, Any],
) -> None:
    """Compute PE/PB/PS percentiles from CSMAR monthly history <= as_of."""
    for csmar_key, percentile_key, max_val in [
        ("pe", "pe_percentile", 300),
        ("pb", "pb_percentile", 50),
        ("ps", "ps_percentile", 100),
    ]:
        current_val = valuation.get(f"{csmar_key}_tmn" if csmar_key != "pb" else "pb_mrq")
        if csmar_key == "pe":
            current_val = valuation.get("pe_ttm")
        elif csmar_key == "pb":
            current_val = valuation.get("pb_mrq")
        elif csmar_key == "ps":
            current_val = valuation.get("ps_ttm")
        if current_val is None or current_val <= 0:
            continue

        # Fetch all monthly history <= as_of for this metric
        monthly_result = provider.get_monthly_history(
            symbols=[symbol],
            metrics=[csmar_key],
            end_date=as_of,
        )
        if not monthly_result.metadata.success or not monthly_result.data:
            continue

        series = [
            float(row[csmar_key])
            for row in monthly_result.data
            if row.get(csmar_key) is not None and 0 < float(row[csmar_key]) <= max_val
        ]
        if len(series) >= 12:
            valuation[percentile_key] = round(
                _compute_percentile_from_values(current_val, series), 4
            )
            valuation[f"{percentile_key}_source"] = "local_csmar_daily_derived"
            valuation[f"{percentile_key}_sample_count"] = len(series)


def enrich_fundamental_from_eva(
    symbol: str,
    as_of: str,
) -> tuple[dict[str, Any], str]:
    """Query EVA eva_structure_history for share capital data at as_of.

    Returns (fundamental_data, source_label).
    We only populate fields provably available from EVA: total_volume,
    float_volume, market_cap, float_market_cap, equity_per_share/bps.
    We do NOT fabricate ROE, gross_margin, net_profit_growth, revenue_growth.
    """
    provider = _get_eva_provider()
    if provider is None:
        return {}, "missing"

    result = provider.get_as_of_share_capital(symbol, as_of)
    if not result.metadata.success:
        return {}, "missing"

    data = result.data
    if not data.get("total_volume") and not data.get("market_cap"):
        return {}, "missing"

    fund: dict[str, Any] = {
        "_eva_end_date": data.get("as_of"),
        "source": "local_csmar_eva_structure",
    }
    # EVA provides share capital and market cap, not profitability metrics.
    # We explicitly do NOT set roe, gross_margin, net_profit_growth, revenue_growth.
    # These would need QMT financial which we are not integrating.
    if data.get("equity_per_share"):
        fund["bps"] = round(float(data["equity_per_share"]), 4)

    return fund, "local_csmar_eva_structure"


def enrich_valuation_from_eva(
    symbol: str,
    as_of: str,
    close: float | None,
) -> tuple[dict[str, Any], str]:
    """Use EVA share capital data + QMT close to derive market_cap fields.

    Returns (extra_valuation_fields, source_label).
    """
    provider = _get_eva_provider()
    if provider is None:
        return {}, "missing"

    result = provider.get_as_of_share_capital(symbol, as_of)
    if not result.metadata.success:
        return {}, "missing"

    data = result.data
    extra: dict[str, Any] = {}

    if data.get("market_cap"):
        extra["market_cap"] = float(data["market_cap"])
    if data.get("float_market_cap"):
        extra["float_market_cap"] = float(data["float_market_cap"])

    # Derive market_cap from close * total_volume if not directly available
    if close and data.get("total_volume") and "market_cap" not in extra:
        extra["market_cap"] = round(close * float(data["total_volume"]), 2)

    if extra:
        extra["_eva_end_date"] = data.get("as_of")
        return extra, "local_csmar_eva_structure"

    return {}, "missing"


def _enrich_industry_percentiles(
    symbol: str,
    as_of: str,
    industry_data: dict[str, Any],
    valuation_data: dict[str, Any],
    close: float | None,
) -> None:
    """Compute industry PE/PB/PS percentiles from peer monthly snapshots.

    Modifies industry_data and valuation_data in place.
    Only works when the industry provider has peer member data.
    """
    provider = _get_csmar_provider()
    if provider is None:
        return

    members = industry_data.get("_members", [])
    if not members:
        # Try to get members from industry provider
        ind_provider = _get_industry_provider()
        if ind_provider is None:
            return
        ind_result = ind_provider.resolve_industry(symbol, as_of=as_of)
        if not ind_result.metadata.success:
            return
        members = ind_result.data.get("industry_members", [])
        if not members:
            return

    # Fetch PE/PB/PS for all peers at as_of
    peer_values: dict[str, list[float]] = {"pe": [], "pb": [], "ps": []}
    valid_peers = {"pe": 0, "pb": 0, "ps": 0}

    for peer_sym in members[:200]:  # cap at 200 peers for performance
        if peer_sym == symbol:
            continue
        result = provider.get_as_of_metrics(
            peer_sym, as_of, metrics=["pe", "pb", "ps"]
        )
        if not result.metadata.success:
            continue
        for metric in ["pe", "pb", "ps"]:
            val = result.data.get(metric)
            if val is not None and 0 < float(val) < (300 if metric == "pe" else 50 if metric == "pb" else 100):
                peer_values[metric].append(float(val))
                valid_peers[metric] += 1

    # Update industry peer counts
    industry_data["valid_peer_count_pe"] = valid_peers["pe"]
    industry_data["valid_peer_count_pb"] = valid_peers["pb"]
    industry_data["valid_peer_count_ps"] = valid_peers["ps"]

    # Compute industry percentiles
    for csmar_key, percentile_key, val_key in [
        ("pe", "industry_pe_percentile", "pe_ttm"),
        ("pb", "industry_pb_percentile", "pb_mrq"),
        ("ps", "industry_ps_percentile", "ps_ttm"),
    ]:
        current_val = valuation_data.get(val_key)
        peers = peer_values[csmar_key]
        if current_val is not None and current_val > 0 and len(peers) >= 10:
            valuation_data[percentile_key] = round(
                _compute_percentile_from_values(current_val, peers), 4
            )


def enrich_industry_from_local(
    symbol: str,
    as_of: str,
) -> tuple[dict[str, Any], str, bool]:
    """Query CSMAR industry provider for industry classification.

    Returns (industry_data, source_label, is_strict).
    The industry provider only has a single snapshot (2026-05-20),
    so is_strict is True only if as_of >= snapshot_date.
    """
    provider = _get_industry_provider()
    if provider is None:
        return {}, "missing", False

    result = provider.resolve_industry(symbol, as_of=as_of)
    if not result.metadata.success or not result.data:
        return {}, "missing", False

    data = result.data
    snapshot_date = data.get("snapshot_date")

    # Strict as_of: only if the snapshot_date <= as_of
    is_strict = False
    if snapshot_date and snapshot_date <= as_of:
        is_strict = True

    industry: dict[str, Any] = {
        "level": data.get("industry_level", "unknown"),
        "name": data.get("industry_name"),
        "peer_count": data.get("peer_count", 0),
        "valid_peer_count_pe": 0,
        "valid_peer_count_pb": 0,
        "valid_peer_count_ps": 0,
        "_snapshot_date": snapshot_date,
        "_fallback_used": data.get("fallback_used", False),
    }

    source_label = "local_csmar_industry" if is_strict else "local_csmar_industry_non_strict"
    return industry, source_label, is_strict

# ── 用户指定的边界样本股票 ──────────────────────────────────────

BOUNDARY_SYMBOLS: list[str] = [
    "603778.SH",  # 乾景园林
    "600410.SH",  # 华胜天成
    "000008.SZ",  # 神州高铁
    "000029.SZ",  # 深深房A
    "000002.SZ",  # 万科A
    "000158.SZ",  # 常山北明
    "000488.SZ",  # 晨鸣纸业
    "000547.SZ",  # 航天发展
    "002816.SZ",  # 和科达
    "002485.SZ",  # 希努尔
    "002496.SZ",  # 辉丰股份
    "688646.SH",  # 逸飞激光 — 科创板，作为 out_of_scope_exception
    "000711.SZ",  # 京蓝科技
]

# 仅 688646.SH 是用户指定的主范围外例外
OUT_OF_SCOPE_EXCEPTION_SYMBOLS: set[str] = {"688646.SH"}

# ── 主板过滤 ──────────────────────────────────────────────────

_MAINBOARD_SH_PREFIXES = ("600", "601", "603", "605")
_MAINBOARD_SZ_PREFIXES = ("000", "001", "002")


def is_mainboard_a(symbol: str) -> bool:
    """判断 symbol 是否属于沪深主板 A 股。

    规则：
    - SH 主板：600/601/603/605 开头
    - SZ 主板：000/001/002 开头
    - 排除 300/301 创业板、688/689 科创板、北交所、ETF
    - OUT_OF_SCOPE_EXCEPTION_SYMBOLS 中的返回 False（由调用方特殊处理）
    """
    if symbol in OUT_OF_SCOPE_EXCEPTION_SYMBOLS:
        return False

    code = symbol.split(".")[0]

    if symbol.endswith(".SH"):
        return code.startswith(_MAINBOARD_SH_PREFIXES)
    if symbol.endswith(".SZ"):
        return code.startswith(_MAINBOARD_SZ_PREFIXES)

    return False


def is_boundary_symbol(symbol: str) -> bool:
    """判断是否为用户指定的边界样本股票。"""
    return symbol in BOUNDARY_SYMBOLS


def is_out_of_scope_exception(symbol: str) -> bool:
    """判断是否为主范围外的用户指定例外。"""
    return symbol in OUT_OF_SCOPE_EXCEPTION_SYMBOLS


def is_allowed_by_asset_scope(symbol: str, asset_scope: str | None = None) -> bool:
    """Return whether *symbol* belongs to the requested historical sample scope."""
    scope = (asset_scope or "all").strip().lower()
    if scope in {"", "all", "a-share", "a_share"}:
        return True
    if scope in {"mainboard-a", "mainboard_a", "mainboard"}:
        return is_mainboard_a(symbol) or is_out_of_scope_exception(symbol)
    raise ValueError(f"Unsupported asset scope: {asset_scope}")


# ── QMT 连接 ──────────────────────────────────────────────────

def _import_xtdata():
    """导入 xtquant.xtdata，失败时抛出 ImportError。"""
    from xtquant import xtdata  # type: ignore[import-untyped]
    return xtdata


def check_qmt_available() -> tuple[bool, str]:
    """检查 QMT/xtdata 是否可用。

    Returns
    -------
    tuple[bool, str]
        (可用, 描述信息)
    """
    try:
        xtdata = _import_xtdata()
    except ImportError:
        return False, "xtquant 未安装或导入失败"

    try:
        # 测试基本连接
        if hasattr(xtdata, "connect"):
            xtdata.connect()
        # 测试数据查询
        xtdata.get_market_data_ex([], period="1d", count=1)
        return True, "QMT 连接正常"
    except Exception as exc:
        return False, f"QMT 连接失败: {exc}"


# ── 股票池构建 ──────────────────────────────────────────────────

def get_mainboard_a_symbols_from_qmt() -> list[str]:
    """从 QMT 获取沪深主板 A 股列表。"""
    xtdata = _import_xtdata()

    symbols: list[str] = []

    # 尝试通过板块获取
    for sector in ["沪深A股", "沪深主板", "上证主板", "深证主板"]:
        try:
            sector_symbols = xtdata.get_stock_list_in_sector(sector)
            if sector_symbols:
                symbols.extend(sector_symbols)
                break
        except Exception:
            continue

    if not symbols:
        # 回退：直接用 instrument list
        try:
            for exchange in ["SH", "SZ"]:
                instruments = xtdata.get_stock_list_in_sector(exchange)
                if instruments:
                    symbols.extend(instruments)
        except Exception:
            pass

    # 标准化格式并过滤
    result: list[str] = []
    for sym in symbols:
        # xtdata 返回格式可能是 "600519.SH" 或 "sh600519"
        normalized = _normalize_xtdata_symbol(sym)
        if normalized and is_mainboard_a(normalized):
            result.append(normalized)

    return sorted(set(result))


def _normalize_xtdata_symbol(sym: str) -> str | None:
    """将 xtdata 返回的 symbol 标准化为 XX.XX 格式。"""
    if not sym:
        return None

    # 已经是标准格式
    if "." in sym and sym.endswith((".SH", ".SZ", ".BJ")):
        return sym

    # sh600519 / sz000001 格式
    sym_lower = sym.lower()
    if sym_lower.startswith("sh") and len(sym_lower) == 8:
        return f"{sym_lower[2:]}.SH"
    if sym_lower.startswith("sz") and len(sym_lower) == 8:
        return f"{sym_lower[2:]}.SZ"
    if sym_lower.startswith("bj") and len(sym_lower) == 8:
        return f"{sym_lower[2:]}.BJ"

    # 纯数字，猜测交易所
    code = sym.strip()
    if len(code) == 6 and code.isdigit():
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith(("4", "8", "9")):
            return f"{code}.BJ"

    return None


# ── 历史行情获取 ──────────────────────────────────────────────────

def fetch_daily_kline(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """从 QMT 获取日 K 线数据。

    Parameters
    ----------
    symbol : str
        标准格式 symbol，如 "600519.SH"
    start_date : str
        起始日期 "YYYY-MM-DD"
    end_date : str
        结束日期 "YYYY-MM-DD"

    Returns
    -------
    pd.DataFrame
        columns: open, high, low, close, volume, amount
        index: DatetimeIndex
    """
    xtdata = _import_xtdata()

    # 先下载历史数据到本地缓存
    try:
        xtdata.download_history_data(
            symbol, period="1d",
            start_time=start_date.replace("-", ""),
            end_time=end_date.replace("-", ""),
        )
    except Exception as exc:
        logger.warning("下载 %s 历史数据失败: %s", symbol, exc)

    # 使用 count=-1 获取所有可用数据（start_time/end_time 在某些版本不可靠）
    # 注意：fill_data=True 会导致某些股票数据缺失（如 600519.SH），必须用 False
    raw = xtdata.get_market_data_ex(
        field_list=["time", "open", "high", "low", "close", "volume", "amount"],
        stock_list=[symbol],
        period="1d",
        count=-1,
        dividend_type="front",
        fill_data=False,
    )

    if not raw or symbol not in raw:
        return pd.DataFrame()

    df = raw[symbol]
    if df is None or df.empty:
        return pd.DataFrame()

    # 标准化列名
    col_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower in ("open", "开盘"):
            col_map[col] = "open"
        elif col_lower in ("high", "最高"):
            col_map[col] = "high"
        elif col_lower in ("low", "最低"):
            col_map[col] = "low"
        elif col_lower in ("close", "收盘"):
            col_map[col] = "close"
        elif col_lower in ("volume", "成交量"):
            col_map[col] = "volume"
        elif col_lower in ("amount", "成交额"):
            col_map[col] = "amount"

    df = df.rename(columns=col_map)

    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col not in df.columns:
            df[col] = 0.0

    df = df[["open", "high", "low", "close", "volume", "amount"]].copy()

    # 转换 index 为 DatetimeIndex（QMT 返回 YYYYMMDD 字符串索引）
    df.index = pd.to_datetime(df.index, format="%Y%m%d", errors="coerce")
    df = df[df.index.notna()]
    # 去重：保留每个日期的最后一行
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    # 按请求的日期范围过滤
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]

    # 确保数值类型
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def fetch_benchmark_kline(
    benchmark_symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """获取基准指数日 K 线。"""
    return fetch_daily_kline(benchmark_symbol, start_date, end_date)


# ── 日期工具 ──────────────────────────────────────────────────

def _find_nearest_trading_date(
    index: pd.DatetimeIndex,
    target: str,
    direction: str = "backward",
    max_days: int = 10,
) -> pd.Timestamp | None:
    """在 index 中找到最接近 target 的交易日。

    Parameters
    ----------
    direction : str
        "backward" = 往前找（<= target），"forward" = 往后找（>= target）
    """
    target_ts = pd.Timestamp(target)

    if direction == "backward":
        candidates = index[index <= target_ts]
        if candidates.empty:
            return None
        return candidates[-1]
    else:
        candidates = index[index >= target_ts]
        if candidates.empty:
            return None
        return candidates[0]


def _find_forward_date(
    index: pd.DatetimeIndex,
    as_of_ts: pd.Timestamp,
    trading_days: int,
) -> pd.Timestamp | None:
    """从 as_of 往后找第 N 个交易日。"""
    mask = index > as_of_ts
    future_dates = index[mask]
    if len(future_dates) < trading_days:
        return None
    return future_dates[trading_days - 1]


# ── Forward Metrics 计算 ──────────────────────────────────────────

def compute_forward_metrics(
    close_series: pd.Series,
    as_of_date: str,
    benchmark_close: pd.Series | None = None,
) -> dict[str, Any]:
    """计算前瞻收益指标。

    Parameters
    ----------
    close_series : pd.Series
        日收盘价，index 为 DatetimeIndex
    as_of_date : str
        "YYYY-MM-DD"
    benchmark_close : pd.Series | None
        基准指数收盘价，用于计算相对收益

    Returns
    -------
    dict
        {
            return_20d, return_60d, return_120d,
            relative_return_20d, relative_return_60d, relative_return_120d,
            max_drawdown_20d, max_drawdown_60d, max_drawdown_120d,
            coverage_gap: str | None,  # 如 "insufficient_120d_data"
        }
    """
    result: dict[str, Any] = {
        "return_20d": None,
        "return_60d": None,
        "return_120d": None,
        "benchmark_return_20d": None,
        "benchmark_return_60d": None,
        "benchmark_return_120d": None,
        "relative_return_20d": None,
        "relative_return_60d": None,
        "relative_return_120d": None,
        "max_drawdown_20d": None,
        "max_drawdown_60d": None,
        "max_drawdown_120d": None,
        "coverage_gap": None,
    }

    if close_series.empty:
        result["coverage_gap"] = "empty_close_series"
        return result

    # 找到 as_of 对应的交易日
    as_of_ts = _find_nearest_trading_date(close_series.index, as_of_date, "backward")
    if as_of_ts is None:
        result["coverage_gap"] = f"as_of_date_{as_of_date}_not_found"
        return result

    as_of_val = close_series.loc[as_of_ts]
    # 处理可能的重复索引导致返回 Series 的情况
    if isinstance(as_of_val, pd.Series):
        as_of_val = as_of_val.iloc[-1]
    as_of_close = float(as_of_val)
    if as_of_close <= 0 or math.isnan(as_of_close):
        result["coverage_gap"] = "invalid_as_of_close"
        return result

    gaps: list[str] = []

    for horizon, days in [("20d", 20), ("60d", 60), ("120d", 120)]:
        target_ts = _find_forward_date(close_series.index, as_of_ts, days)

        if target_ts is None:
            gaps.append(f"insufficient_{horizon}_data")
            continue

        target_val = close_series.loc[target_ts]
        if isinstance(target_val, pd.Series):
            target_val = target_val.iloc[-1]
        target_close = float(target_val)
        if target_close <= 0 or math.isnan(target_close):
            gaps.append(f"invalid_{horizon}_close")
            continue

        # 收益率
        ret = (target_close / as_of_close) - 1.0
        result[f"return_{horizon}"] = round(ret, 6)

        # 最大回撤
        window = close_series.loc[as_of_ts:target_ts]
        if isinstance(window, pd.DataFrame):
            window = window.iloc[:, 0]
        if len(window) >= 2:
            rolling_max = window.cummax()
            drawdown = window / rolling_max - 1.0
            dd_min = drawdown.min()
            if isinstance(dd_min, pd.Series):
                dd_min = dd_min.iloc[0]
            result[f"max_drawdown_{horizon}"] = round(float(dd_min), 6)

        # 相对收益
        if benchmark_close is not None and not benchmark_close.empty:
            bench_as_of = _find_nearest_trading_date(
                benchmark_close.index, as_of_date, "backward"
            )
            bench_target = _find_forward_date(
                benchmark_close.index, as_of_ts, days
            )
            if bench_as_of is not None and bench_target is not None:
                bench_target_val = benchmark_close.loc[bench_target]
                if isinstance(bench_target_val, pd.Series):
                    bench_target_val = bench_target_val.iloc[-1]
                bench_as_of_val = benchmark_close.loc[bench_as_of]
                if isinstance(bench_as_of_val, pd.Series):
                    bench_as_of_val = bench_as_of_val.iloc[-1]
                bench_ret = (
                    float(bench_target_val)
                    / float(bench_as_of_val)
                    - 1.0
                )
                result[f"benchmark_return_{horizon}"] = round(bench_ret, 6)
                result[f"relative_return_{horizon}"] = round(ret - bench_ret, 6)

    if gaps:
        result["coverage_gap"] = ";".join(gaps)

    return result


# ── Price Data 计算 ──────────────────────────────────────────

def compute_price_data(
    close_series: pd.Series,
    amount_series: pd.Series | None,
    as_of_date: str,
) -> dict[str, Any]:
    """计算截至 as_of 的价格指标。

    Parameters
    ----------
    close_series : pd.Series
        日收盘价，index 为 DatetimeIndex
    amount_series : pd.Series | None
        日成交额
    as_of_date : str
        "YYYY-MM-DD"

    Returns
    -------
    dict
        price_data 结构
    """
    if close_series.empty:
        return {}

    as_of_ts = _find_nearest_trading_date(close_series.index, as_of_date, "backward")
    if as_of_ts is None:
        return {}

    # 截取到 as_of 之前的数据
    hist = close_series.loc[:as_of_ts]
    if len(hist) < 61:
        return {}

    close = hist
    latest = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())

    returns = close.pct_change().dropna()
    vol_60 = float(returns.tail(60).std() * (252 ** 0.5)) if len(returns) >= 60 else None

    # 成交额
    avg_turnover = 0.0
    if amount_series is not None and not amount_series.empty:
        hist_amount = amount_series.loc[:as_of_ts]
        if len(hist_amount) >= 20:
            avg_turnover = float(hist_amount.tail(20).mean())

    # 60 日最大回撤
    window_60 = close.tail(60)
    if isinstance(window_60, pd.DataFrame):
        window_60 = window_60.iloc[:, 0]
    rolling_max = window_60.cummax()
    drawdown_60 = window_60 / rolling_max - 1.0
    dd_min_60 = drawdown_60.min()
    if isinstance(dd_min_60, pd.Series):
        dd_min_60 = dd_min_60.iloc[0]
    max_dd_60 = float(dd_min_60)

    return {
        "close": latest,
        "change_20d": float(close.iloc[-1] / close.iloc[-21] - 1),
        "change_60d": float(close.iloc[-1] / close.iloc[-61] - 1),
        "ma20_position": "above" if latest >= ma20 else "below",
        "ma60_position": "above" if latest >= ma60 else "below",
        "max_drawdown_60d": max_dd_60,
        "volatility_60d": vol_60,
        "avg_turnover_20d": avg_turnover,
        "data_vendor": "qmt_xtdata",
    }


# ── 场景标签推断 ──────────────────────────────────────────────

def infer_scenario_tags(
    symbol: str,
    price_data: dict,
    fundamental_data: dict | None,
    valuation_data: dict | None,
) -> list[str]:
    """根据数据特征推断场景标签。"""
    tags: list[str] = ["stock"]

    # 主板/例外分类
    if is_out_of_scope_exception(symbol):
        tags.append("out_of_scope_exception")
    elif is_mainboard_a(symbol):
        tags.append("mainboard")
    else:
        tags.append("non_mainboard")

    # 市值分类
    market_cap = (valuation_data or {}).get("market_cap")
    if market_cap is not None:
        if market_cap >= 1e11:
            tags.append("large_cap")
        else:
            tags.append("small_or_mid_cap")

    # 波动/回撤
    vol = price_data.get("volatility_60d")
    if vol is not None and vol >= 0.30:
        tags.append("high_volatility")

    dd = price_data.get("max_drawdown_60d")
    if dd is not None and dd <= -0.20:
        tags.append("extreme_drawdown")

    # 亏损
    fund = fundamental_data or {}
    roe = fund.get("roe")
    if roe is not None and roe < 0:
        tags.append("loss_making_or_invalid_pe")

    pe = (valuation_data or {}).get("pe_ttm")
    if pe is None:
        tags.append("loss_making_or_invalid_pe")

    # 基本面缺失
    if not fund or all(v is None for v in fund.values()):
        tags.append("missing_fundamental")

    # 行业样本不足
    peer_count = (valuation_data or {}).get("_peer_count", 999)
    if peer_count < 10:
        tags.append("industry_insufficient_peers")

    # 财报窗口（3/6/9/12 月底）
    # 由调用方根据 as_of 判断

    return tags


# ── 样本组装 ──────────────────────────────────────────────────

def build_sample_from_qmt_data(
    sample_id: str,
    symbol: str,
    name: str,
    as_of: str,
    close_series: pd.Series,
    amount_series: pd.Series | None,
    benchmark_close: pd.Series | None,
    fundamental_data: dict | None,
    valuation_data: dict | None,
    industry_data: dict | None,
    scenario_tags: list[str] | None = None,
    expected: dict | None = None,
    *,
    fundamental_source: str = "missing",
    valuation_source: str = "missing",
    industry_source: str = "missing",
    industry_strict: bool = False,
) -> dict[str, Any]:
    """从 QMT 历史数据组装一个完整样本。

    Parameters
    ----------
    fundamental_source : str
        Provenance label for fundamental data.
    valuation_source : str
        Provenance label for valuation data.
    industry_source : str
        Provenance label for industry data.
    industry_strict : bool
        Whether industry data passes strict as_of validation.

    Returns
    -------
    dict
        完整的样本结构，包含 provenance
    """
    # 计算价格数据
    price_data = compute_price_data(close_series, amount_series, as_of)

    # 计算前瞻收益
    forward_metrics = compute_forward_metrics(close_series, as_of, benchmark_close)

    # 场景标签
    if scenario_tags is None:
        scenario_tags = infer_scenario_tags(
            symbol, price_data, fundamental_data, valuation_data
        )

    # 财报窗口标签
    try:
        month = int(as_of.split("-")[1])
        if month in (3, 6, 9, 12):
            if "earnings_window" not in scenario_tags:
                scenario_tags.append("earnings_window")
    except (ValueError, IndexError):
        pass

    # 行业信息
    industry = industry_data or {
        "level": "unknown", "name": None, "peer_count": 0,
        "valid_peer_count_pe": 0, "valid_peer_count_pb": 0,
        "valid_peer_count_ps": 0,
    }

    # 数据质量
    has_placeholder = False
    blocking_issues: list[str] = []
    confidence = 0.95

    fund = fundamental_data or {}
    has_meaningful_fund = fund and any(
        v is not None for k, v in fund.items() if not k.startswith("_")
    )
    if not has_meaningful_fund:
        has_placeholder = True
        blocking_issues.append("fundamental_data_missing")
        confidence -= 0.15

    val = valuation_data or {}
    if not val or val.get("pe_ttm") is None:
        has_placeholder = True
        blocking_issues.append("valuation_data_missing")
        confidence -= 0.05

    if not industry.get("name"):
        blocking_issues.append("industry_data_missing")
        confidence -= 0.05
    elif not industry_strict:
        blocking_issues.append("industry_as_of_unverifiable")

    if forward_metrics.get("coverage_gap"):
        blocking_issues.append(forward_metrics["coverage_gap"])

    # Provenance — use real source labels from enrichment
    source_metadata = {
        "price_source": "qmt_xtdata",
        "fundamental_source": fundamental_source,
        "valuation_source": valuation_source,
        "industry_source": industry_source if industry.get("name") else "missing",
        "as_of": as_of,
        "symbol": symbol,
    }
    sample_source = {
        "price": source_metadata["price_source"],
        "fundamental": source_metadata["fundamental_source"],
        "valuation": source_metadata["valuation_source"],
        "industry": source_metadata["industry_source"],
    }

    # 已知限制
    known_limitations: list[str] = []
    if forward_metrics.get("coverage_gap"):
        known_limitations.append(f"coverage_gap: {forward_metrics['coverage_gap']}")
    if not val:
        known_limitations.append("valuation_data unavailable")
    if not industry.get("name"):
        known_limitations.append("industry_data unavailable")
    elif not industry_strict:
        known_limitations.append("industry_as_of_unverifiable: latest snapshot fallback")
    if is_out_of_scope_exception(symbol):
        known_limitations.append("out_of_scope_exception: 科创板，非主板范围")
    if not has_meaningful_fund:
        known_limitations.append("fundamental_data partial (EVA share capital only)")

    # data_complete requires: price, valuation, fundamental/EVA, industry with strict as_of
    data_complete = (
        bool(price_data)
        and not has_placeholder
        and industry_strict
    )
    if forward_metrics.get("coverage_gap"):
        data_complete = False

    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "name": name,
        "asset_type": "stock",
        "as_of": as_of,
        "source": sample_source,
        "out_of_scope_exception": is_out_of_scope_exception(symbol),
        "scenario_tags": scenario_tags,
        "industry": industry,
        "input_result": {
            "asset_type": "stock",
            "price_data": price_data,
            "fundamental_data": {k: v for k, v in fund.items()
                                 if not k.startswith("_")},
            "valuation_data": {k: v for k, v in val.items()
                               if not k.startswith("_")},
            "event_data": {
                "recent_news_sentiment": "neutral",
                "policy_risk": "medium",
                "event_summary": {"critical_count": 0, "high_count": 0},
                "events": [],
            },
            "source_metadata": source_metadata,
            "data_quality": {
                "has_placeholder": has_placeholder,
                "blocking_issues": blocking_issues,
                "overall_confidence": round(confidence, 2),
            },
        },
        "forward_metrics": {
            "return_20d": forward_metrics.get("return_20d"),
            "return_60d": forward_metrics.get("return_60d"),
            "return_120d": forward_metrics.get("return_120d"),
            "benchmark_return_20d": forward_metrics.get("benchmark_return_20d"),
            "benchmark_return_60d": forward_metrics.get("benchmark_return_60d"),
            "benchmark_return_120d": forward_metrics.get("benchmark_return_120d"),
            "relative_return_20d": forward_metrics.get("relative_return_20d"),
            "relative_return_60d": forward_metrics.get("relative_return_60d"),
            "relative_return_120d": forward_metrics.get("relative_return_120d"),
            "max_drawdown_20d": forward_metrics.get("max_drawdown_20d"),
            "max_drawdown_60d": forward_metrics.get("max_drawdown_60d"),
            "max_drawdown_120d": forward_metrics.get("max_drawdown_120d"),
        },
        "expected": expected or {},
        "quality": {
            "is_real_historical_sample": True,
            "data_complete": data_complete,
            "known_limitations": known_limitations,
        },
    }


# ── AS OF 日期生成 ──────────────────────────────────────────────

def generate_as_of_dates(
    start_year: int,
    end_year: int,
) -> list[str]:
    """生成候选 as_of 日期列表。

    选择每季度末 + 额外的年中日期，覆盖财报窗口和非财报窗口。
    """
    dates: list[str] = []
    for year in range(start_year, end_year + 1):
        # 季度末
        for quarter_end in [
            f"{year}-03-29",  # Q1 财报前
            f"{year}-04-30",  # Q1 财报后
            f"{year}-06-28",  # Q2
            f"{year}-09-27",  # Q3
            f"{year}-10-31",  # Q3 财报后
            f"{year}-12-30",  # Q4
        ]:
            dates.append(quarter_end)
    return dates


# ── 主构建函数 ──────────────────────────────────────────────────

def try_build_from_qmt(
    symbols: list[str] | None = None,
    as_of_dates: list[str] | None = None,
    benchmark_symbol: str = "000300.SH",
    start_year: int = 2021,
    end_year: int = 2026,
    max_samples: int = 200,
    boundary_symbols: list[str] | None = None,
    asset_scope: str | None = None,
) -> dict[str, Any] | None:
    """尝试从 QMT 构建真实历史样本。

    Returns
    -------
    dict | None
        {
            "samples": list[dict],
            "included": list[str],
            "skipped": list[dict],  # {"symbol": ..., "reason": ...}
            "source": {...},
        }
        QMT 不可用时返回 None。
    """
    # 检查 QMT 可用性
    available, msg = check_qmt_available()
    if not available:
        logger.info("QMT 不可用: %s", msg)
        return None

    boundary = boundary_symbols or BOUNDARY_SYMBOLS

    # 获取股票池
    if symbols:
        pool = symbols
    else:
        pool = get_mainboard_a_symbols_from_qmt()

    # Boundary symbols first, then the scoped pool. Keep excluded symbols visible.
    skipped: list[dict] = []
    all_symbols: list[str] = []
    for raw_symbol in list(dict.fromkeys(boundary + pool)):
        normalized = _normalize_xtdata_symbol(raw_symbol) or raw_symbol
        if not is_allowed_by_asset_scope(normalized, asset_scope):
            skipped.append({
                "symbol": normalized,
                "reason": f"asset_scope_excluded:{asset_scope}",
            })
            continue
        all_symbols.append(normalized)

    # 生成 as_of 日期
    if as_of_dates is None:
        as_of_dates = generate_as_of_dates(start_year, end_year)

    # 获取基准数据
    # 需要足够长的历史：从 start_year-1 开始
    data_start = f"{start_year - 1}-01-01"
    # end_year + 1 确保有足够 forward 数据
    data_end = f"{end_year + 1}-06-30"

    benchmark_close: pd.Series | None = None
    try:
        bench_df = fetch_benchmark_kline(benchmark_symbol, data_start, data_end)
        if not bench_df.empty:
            benchmark_close = bench_df["close"]
    except Exception as exc:
        logger.warning("获取基准 %s 数据失败: %s", benchmark_symbol, exc)

    # 构建样本
    samples: list[dict] = []
    included: list[str] = []
    sample_counter = 0

    # 将 as_of 按年份分组，用于年份轮换
    as_of_by_year: dict[str, list[str]] = {}
    for d in as_of_dates:
        year = d[:4]
        as_of_by_year.setdefault(year, []).append(d)
    year_cycle = sorted(as_of_by_year.keys())

    # 每个年份的目标样本数（均匀分布）
    year_counts: dict[str, int] = {y: 0 for y in year_cycle}

    # 策略：对每个 symbol 从不同年份选取 as_of，实现年份多样化
    for symbol in all_symbols:
        if len(samples) >= max_samples:
            break

        try:
            kline = fetch_daily_kline(symbol, data_start, data_end)
        except Exception as exc:
            skipped.append({"symbol": symbol, "reason": f"kline_fetch_failed: {exc}"})
            continue

        if kline.empty or len(kline) < 120:
            skipped.append({"symbol": symbol, "reason": "insufficient_kline_data"})
            continue

        close_series = kline["close"]
        amount_series = kline.get("amount")

        # 确定当前应该填充的年份：选择计数最少的年份
        # 但如果边界股票还没全部处理完，先不限制年份
        if len(included) < len(boundary):
            # 边界股票阶段：不限制年份，找最佳
            preferred_years = year_cycle
        else:
            # 正常阶段：优先填充计数最少的年份
            sorted_years = sorted(year_counts.keys(), key=lambda y: year_counts[y])
            preferred_years = sorted_years

        # 从优先年份开始搜索
        chosen_as_of = None
        best_completeness = 0

        for year in preferred_years:
            for as_of in reversed(as_of_by_year.get(year, [])):
                hist = close_series.loc[:as_of]
                if len(hist) < 61:
                    continue

                fm = compute_forward_metrics(close_series, as_of, benchmark_close)

                has_120d = fm.get("return_120d") is not None
                has_60d = fm.get("return_60d") is not None
                has_20d = fm.get("return_20d") is not None

                if not has_20d:
                    continue

                completeness = 3 if has_120d else (2 if has_60d else 1)
                if completeness > best_completeness:
                    best_completeness = completeness
                    chosen_as_of = as_of
                    if completeness == 3:
                        break
            if best_completeness == 3:
                break

        # 更新年份计数
        if chosen_as_of:
            chosen_year = chosen_as_of[:4]
            year_counts[chosen_year] = year_counts.get(chosen_year, 0) + 1

        if chosen_as_of is None:
            skipped.append({"symbol": symbol, "reason": "no_valid_as_of_found"})
            continue

        # 构建样本
        name = symbol
        sample_counter += 1
        sample_id = f"qmt_{symbol.replace('.', '_')}_{chosen_as_of.replace('-', '')}"

        # ── Enrich from CSMAR / EVA / Industry ──
        close_val = float(close_series.loc[:chosen_as_of].iloc[-1]) if not close_series.loc[:chosen_as_of].empty else None

        # Valuation from CSMAR Daily Derived (strict as_of)
        val_data, val_source = enrich_valuation_from_csmar(symbol, chosen_as_of, close_val)

        # Fundamental from EVA (strict as_of): share capital, BPS only
        fund_data, fund_source = enrich_fundamental_from_eva(symbol, chosen_as_of)

        # Additional valuation fields from EVA (market_cap etc.)
        eva_val_extra, eva_val_source = enrich_valuation_from_eva(symbol, chosen_as_of, close_val)
        if eva_val_extra:
            val_data.update(eva_val_extra)
            if val_source == "missing":
                val_source = eva_val_source

        # Industry from local CSMAR (may be non-strict)
        ind_data, ind_source, ind_strict = enrich_industry_from_local(symbol, chosen_as_of)

        # Compute industry percentiles if we have peer data and valuation
        if ind_data.get("name") and val_data:
            _enrich_industry_percentiles(
                symbol, chosen_as_of, ind_data, val_data, close_val
            )

        sample = build_sample_from_qmt_data(
            sample_id=sample_id,
            symbol=symbol,
            name=name,
            as_of=chosen_as_of,
            close_series=close_series,
            amount_series=amount_series,
            benchmark_close=benchmark_close,
            fundamental_data=fund_data if fund_data else None,
            valuation_data=val_data if val_data else None,
            industry_data=ind_data if ind_data else None,
            fundamental_source=fund_source,
            valuation_source=val_source,
            industry_source=ind_source,
            industry_strict=ind_strict,
        )

        samples.append(sample)
        included.append(symbol)

    return {
        "samples": samples,
        "included": included,
        "skipped": skipped,
        "source": {
            "price": "qmt_xtdata",
            "fundamental": "local_csmar_eva_structure",
            "valuation": "local_csmar_daily_derived",
            "industry": "local_csmar_industry",
        },
    }
