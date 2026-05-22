import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from services.data.market_data_utils import (
    build_price_data_from_frame,
    build_price_source_metadata,
    guess_asset_type,
    normalize_symbol,
)
from services.data.provider_contracts import (
    ProviderSchemaError,
    ProviderUnavailableError,
)

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


if load_dotenv:
    load_dotenv()


@dataclass(frozen=True)
class QMTSettings:
    period: str = "1d"
    history_days: int = 1500
    auto_download: bool = True
    dividend_type: str = "front"
    suppress_hello: bool = True
    max_stale_days: int = 3
    stale_refresh_days: int = 90
    use_full_tick_for_stale: bool = True


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_qmt_settings() -> QMTSettings:
    return QMTSettings(
        period=os.getenv("QMT_PERIOD", "1d"),
        history_days=int(os.getenv("QMT_HISTORY_DAYS", "1500")),
        auto_download=_env_bool("QMT_AUTO_DOWNLOAD", True),
        dividend_type=os.getenv("QMT_DIVIDEND_TYPE", "front"),
        suppress_hello=_env_bool("QMT_SUPPRESS_HELLO", True),
        max_stale_days=int(os.getenv("QMT_PRICE_MAX_STALE_DAYS", "3")),
        stale_refresh_days=int(os.getenv("QMT_STALE_REFRESH_DAYS", "90")),
        use_full_tick_for_stale=_env_bool("QMT_USE_FULL_TICK_FOR_STALE_PRICE", True),
    )


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise ProviderUnavailableError(
            "QMT/xtquant 不可用。请确认已在 Windows 环境安装 QMT 客户端和 xtquant。"
        ) from exc

    return xtdata


def connect_qmt(settings: QMTSettings | None = None):
    xtdata = _import_xtdata()
    effective_settings = settings or load_qmt_settings()

    if effective_settings.suppress_hello and hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False

    try:
        return xtdata.connect()
    except Exception as exc:
        raise ProviderUnavailableError(
            "无法连接 QMT 本地行情服务。请确认 miniQMT/QMT 投研服务已启动并登录。"
        ) from exc


def _format_qmt_time(value: date) -> str:
    return value.strftime("%Y%m%d")


def _to_dataframe(raw: Any, symbol: str) -> pd.DataFrame:
    if isinstance(raw, dict):
        if symbol in raw:
            df = raw[symbol]
        elif raw:
            df = next(iter(raw.values()))
        else:
            return pd.DataFrame()
    else:
        df = raw

    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception as exc:
            raise ProviderSchemaError(
                f"QMT daily history response cannot be converted to DataFrame: {type(df).__name__}"
            ) from exc

    return df


def _query_qmt_daily_history(
    symbol: str,
    start: str,
    end: str,
    settings: QMTSettings,
) -> pd.DataFrame:
    xtdata = _import_xtdata()

    try:
        raw = xtdata.get_market_data_ex(
            field_list=["time", "close", "amount", "volume"],
            stock_list=[symbol],
            period=settings.period,
            start_time=start,
            end_time=end,
            count=-1,
            dividend_type=settings.dividend_type,
            fill_data=True,
        )
    except Exception as exc:
        raise ProviderUnavailableError(
            f"QMT daily history query failed for {symbol}: {exc}"
        ) from exc

    return _to_dataframe(raw, symbol)


def _extract_latest_trade_date(df: pd.DataFrame) -> date | None:
    """Extract the latest trade date from a daily history DataFrame.

    Supports both QMT and AKShare column naming conventions.

    Tries date-like columns first (``time``, ``日期``, ``date``, ``trade_date``),
    then the DataFrame index.  Only considers rows where ``close`` is non-NaN so
    that a trailing placeholder row does not skew the result.
    """
    if df is None or df.empty:
        return None

    close_col = _find_column(df, ["close", "收盘"])
    if close_col is None:
        return None

    valid = df[df[close_col].notna()]
    if valid.empty:
        return None

    # --- attempt 1: date-like column ---
    date_col = _find_column(df, ["time", "日期", "date", "trade_date"])
    if date_col and date_col in valid.columns:
        try:
            raw = valid[date_col].iloc[-1]
            dt = _parse_timestamp_like(raw)
            if dt is not None:
                return dt
        except Exception:
            pass

    # --- attempt 2: index ---
    try:
        idx_val = valid.index[-1]
        dt = _parse_timestamp_like(idx_val)
        if dt is not None:
            return dt
    except Exception:
        pass

    return None


def _parse_timestamp_like(value: Any) -> date | None:
    """Parse various timestamp representations into a ``date``.

    Handles: 13-digit ms timestamps, 10-digit s timestamps,
    ``YYYYMMDD`` / ``YYYY-MM-DD`` strings, ``datetime``, ``date``,
    and ``pandas.Timestamp``.
    """
    if value is None:
        return None

    # pandas Timestamp / datetime / date
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    # numeric timestamps — must come BEFORE pd.Timestamp() fallback because
    # pd.Timestamp(int) silently interprets bare integers as nanoseconds.
    # Use numbers.Integral/Real to also catch numpy int64 etc.
    import numbers

    if isinstance(value, numbers.Integral):
        val = int(value)
        if val > 1_000_000_000_000:  # 13-digit ms
            return datetime.fromtimestamp(val / 1000).date()
        if val > 1_000_000_000:  # 10-digit s
            return datetime.fromtimestamp(val).date()
        # YYYYMMDD integer
        if 1990_01_01 <= val <= 2099_12_31:
            try:
                return datetime.strptime(str(val), "%Y%m%d").date()
            except ValueError:
                pass

    # string dates
    if isinstance(value, str):
        value = value.strip()
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue

    # pandas Timestamp may arrive as an object that pd.Timestamp can parse
    # (e.g. numpy datetime64).  Only reach here for non-int/non-string types.
    try:
        ts = pd.Timestamp(value)
        if ts is not pd.NaT:
            return ts.date()
    except Exception:
        pass

    return None


def _is_qmt_history_stale(
    latest_trade_date: date | None,
    today: date | None = None,
    max_stale_days: int = 3,
) -> bool:
    """Return ``True`` if the latest trade date is considered stale."""
    if latest_trade_date is None:
        return True
    effective_today = today or date.today()
    return (effective_today - latest_trade_date).days > max_stale_days


def _query_qmt_full_tick(symbol: str) -> dict | None:
    """Query QMT get_full_tick() for a single symbol.

    Returns a normalized dict with at least ``last_price``, ``prev_close``,
    ``amount``, ``volume``, ``tick_time``, ``tick_time_tag``,
    ``tick_trade_date``, ``source``.  Returns ``None`` if xtdata is
    unavailable, the symbol is not found, or the tick data is unusable.
    """
    try:
        xtdata = _import_xtdata()
    except Exception:
        return None

    try:
        raw = xtdata.get_full_tick([symbol])
    except Exception:
        return None

    if not raw or symbol not in raw:
        return None

    data = raw[symbol]

    last_price = _safe_float(data.get("lastPrice"))
    prev_close = _safe_float(data.get("lastClose"))
    amount = _safe_float(data.get("amount"))
    volume = _safe_float(data.get("volume"))
    tick_time_raw = data.get("time")
    timetag_raw = data.get("timetag")
    stock_status = data.get("stockStatus")

    # Parse trade date from timetag first, then from time
    tick_trade_date = _parse_tick_trade_date(timetag_raw, tick_time_raw)

    tick_time_tag = str(timetag_raw) if timetag_raw is not None else None

    return {
        "last_price": last_price,
        "prev_close": prev_close,
        "amount": amount,
        "volume": volume,
        "tick_time": tick_time_raw,
        "tick_time_tag": tick_time_tag,
        "tick_trade_date": tick_trade_date,
        "stock_status": stock_status,
        "source": "qmt_full_tick",
    }


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure or non-positive."""
    if value is None:
        return None
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_tick_trade_date(
    timetag_raw: Any,
    time_raw: Any,
) -> date | None:
    """Extract the trade date from tick timetag or time fields.

    ``timetag_raw`` is typically a string like ``"20260521 15:00:00"``.
    ``time_raw`` may be a 13-digit ms timestamp or 10-digit s timestamp.
    """
    # timetag: "YYYYMMDD HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
    if isinstance(timetag_raw, str):
        date_part = timetag_raw.strip().split(" ")[0]
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_part, fmt).date()
            except ValueError:
                continue

    # time: numeric ms or s timestamp
    if time_raw is not None:
        dt = _parse_timestamp_like(time_raw)
        if dt is not None:
            return dt

    return None


def _apply_intraday_tick_bar(
    df: pd.DataFrame,
    tick: dict,
    kline_latest_date: date | None,
) -> tuple[pd.DataFrame, str | None]:
    """Apply a tick as a temporary intraday bar to the daily K-line DataFrame.

    Returns ``(new_df, reason)`` where *reason* is ``None`` on success or a
    short explanation string when the tick is not applied.
    """
    tick_price = tick.get("last_price")
    tick_trade_date = tick.get("tick_trade_date")

    if tick_price is None or tick_price <= 0:
        return df, "tick_last_price_invalid"

    if tick_trade_date is None:
        return df, "tick_date_unparseable"

    if kline_latest_date is None:
        return df, "kline_latest_date_unknown"

    if tick_trade_date < kline_latest_date:
        return df, "tick_date_earlier_than_kline"

    close_col = _find_column(df, ["close", "收盘"])
    if close_col is None:
        return df, "no_close_column"

    amount_col = _find_column(df, ["amount", "成交额"])
    volume_col = _find_column(df, ["volume", "成交量"])

    new_df = df.copy()

    # Parse kline dates from index for comparison
    kline_dates = _parse_index_dates(new_df)

    if tick_trade_date == kline_latest_date:
        # Update existing row for the same day
        if kline_dates is not None:
            for i, dt in enumerate(kline_dates):
                if dt == tick_trade_date:
                    idx = new_df.index[i]
                    new_df.loc[idx, close_col] = tick_price
                    if amount_col and tick.get("amount") is not None:
                        new_df.loc[idx, amount_col] = tick["amount"]
                    if volume_col and tick.get("volume") is not None:
                        new_df.loc[idx, volume_col] = tick["volume"]
                    return new_df, None
        # If we can't find matching row, try last row
        last_idx = new_df.index[-1]
        new_df.loc[last_idx, close_col] = tick_price
        if amount_col and tick.get("amount") is not None:
            new_df.loc[last_idx, amount_col] = tick["amount"]
        if volume_col and tick.get("volume") is not None:
            new_df.loc[last_idx, volume_col] = tick["volume"]
        return new_df, None

    # tick_trade_date > kline_latest_date: append new row
    # Build new row with same columns as df
    new_row: dict[str, Any] = {}
    for col in new_df.columns:
        col_lower = str(col).lower()
        if col_lower in ("close", "收盘"):
            new_row[col] = tick_price
        elif col_lower in ("amount", "成交额") and tick.get("amount") is not None:
            new_row[col] = tick["amount"]
        elif col_lower in ("volume", "成交量") and tick.get("volume") is not None:
            new_row[col] = tick["volume"]
        elif col_lower == "data_vendor":
            new_row[col] = "qmt"
        else:
            new_row[col] = None

    # Use the tick trade date as the index value (same format as existing index)
    # Detect existing index format
    if len(new_df) > 0:
        sample_idx = str(new_df.index[0])
        if len(sample_idx) == 8 and sample_idx.isdigit():
            new_index_val = tick_trade_date.strftime("%Y%m%d")
        elif "-" in sample_idx:
            new_index_val = tick_trade_date.strftime("%Y-%m-%d")
        else:
            new_index_val = str(tick_trade_date)
    else:
        new_index_val = tick_trade_date.strftime("%Y%m%d")

    new_row_df = pd.DataFrame([new_row], index=[new_index_val])
    new_row_df.index.name = new_df.index.name

    new_df = pd.concat([new_df, new_row_df])

    return new_df, None


def _parse_index_dates(df: pd.DataFrame) -> list[date] | None:
    """Try to parse each index value as a date. Returns None on failure."""
    dates = []
    for val in df.index:
        dt = _parse_timestamp_like(val)
        if dt is None:
            return None
        dates.append(dt)
    return dates


def _download_qmt_daily_history(
    symbol: str,
    start: str,
    end: str,
    settings: QMTSettings,
) -> bool:
    xtdata = _import_xtdata()

    try:
        result = xtdata.download_history_data(
            symbol,
            settings.period,
            start,
            end,
        )
    except TypeError:
        try:
            result = xtdata.download_history_data(symbol, settings.period, start, end)
        except Exception as exc:
            raise ProviderUnavailableError(
                f"QMT daily history download failed for {symbol}: {exc}"
            ) from exc
    except Exception as exc:
        raise ProviderUnavailableError(
            f"QMT daily history download failed for {symbol}: {exc}"
        ) from exc

    return True if result is None else bool(result)


def _load_qmt_daily_history(symbol: str, settings: QMTSettings) -> tuple[pd.DataFrame, dict]:
    """
    Load daily K-line data from local QMT.

    Expected fields are close and amount. Different xtquant versions may return
    either a dict of DataFrames or a field-indexed object, so this function is
    deliberately defensive.
    """
    xtdata = _import_xtdata()
    connect_qmt(settings)

    end_date = date.today()
    start_date = end_date - timedelta(days=settings.history_days)
    start = os.getenv("QMT_HISTORY_START", _format_qmt_time(start_date))
    end = os.getenv("QMT_HISTORY_END", _format_qmt_time(end_date))

    today = date.today()

    qmt_status = {
        "connected": True,
        "auto_download": settings.auto_download,
        "download_attempted": False,
        "download_success": None,
        "download_reason": None,
        "history_start": start,
        "history_end": end,
        "period": settings.period,
        "data_dir": None,
        "latest_trade_date": None,
        "latest_trade_date_before_download": None,
        "latest_trade_date_after_download": None,
        "price_stale_before_download": None,
        "price_stale_after_download": None,
        "price_max_stale_days": settings.max_stale_days,
        "stale_refresh_days": None,
    }

    try:
        qmt_status["data_dir"] = xtdata.get_data_dir()
    except Exception:
        qmt_status["data_dir"] = None

    df = _query_qmt_daily_history(symbol, start, end, settings)

    # --- stale detection on first query ---
    latest_trade_date = _extract_latest_trade_date(df)
    is_stale = _is_qmt_history_stale(latest_trade_date, today, settings.max_stale_days)

    qmt_status["latest_trade_date"] = str(latest_trade_date) if latest_trade_date else None
    qmt_status["latest_trade_date_before_download"] = qmt_status["latest_trade_date"]
    qmt_status["price_stale_before_download"] = is_stale

    # Determine download reason: "empty" takes priority over "stale"
    download_reason: str | None = None
    if df.empty:
        download_reason = "empty"
    elif is_stale:
        download_reason = "stale"

    # --- forced download if empty or stale ---
    if download_reason and settings.auto_download:
        qmt_status["download_attempted"] = True
        qmt_status["download_reason"] = download_reason
        qmt_status["stale_refresh_days"] = settings.stale_refresh_days

        # Use a shorter window for stale refresh to avoid blocking on full history
        if download_reason == "stale":
            refresh_start = today - timedelta(days=settings.stale_refresh_days)
            dl_start = _format_qmt_time(refresh_start)
        else:
            dl_start = start

        qmt_status["download_success"] = _download_qmt_daily_history(
            symbol,
            dl_start,
            end,
            settings,
        )

        # Re-query with the original full window
        df = _query_qmt_daily_history(symbol, start, end, settings)

        # Re-evaluate stale status after download
        latest_trade_date = _extract_latest_trade_date(df)
        is_stale = _is_qmt_history_stale(latest_trade_date, today, settings.max_stale_days)
        qmt_status["latest_trade_date"] = str(latest_trade_date) if latest_trade_date else None
        qmt_status["latest_trade_date_after_download"] = qmt_status["latest_trade_date"]
        qmt_status["price_stale_after_download"] = is_stale

    if df.empty:
        raise ProviderUnavailableError(
            f"QMT 行情数据为空：{symbol}。"
            "请确认 QMT 已登录，且该标的日线数据可下载；"
            "也可手动执行 xtdata.download_history_data 后重试。"
        )

    df = df.copy()
    df["data_vendor"] = "qmt"
    qmt_status["row_count"] = int(len(df))
    return df, qmt_status


def _load_qmt_instrument_detail(symbol: str) -> dict[str, Any]:
    xtdata = _import_xtdata()

    try:
        detail = xtdata.get_instrument_detail(symbol)
    except Exception:
        detail = None

    if not isinstance(detail, dict):
        return {}

    return detail


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_columns = {str(column).lower(): column for column in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_columns:
            return lower_columns[candidate.lower()]

    return None


def _try_akshare_price_fallback(
    symbol: str,
    asset_type: str,
    qmt_latest_date: date | None,
    max_stale_days: int,
) -> tuple[dict | None, dict]:
    """Attempt to build price_data from AKShare when QMT is stale.

    Returns ``(price_data, metadata)`` where *price_data* is ``None`` when the
    fallback is not applied.  *metadata* always contains the qmt_status keys for
    the AKShare fallback attempt.
    """
    from services.data import akshare_provider

    fallback_meta: dict[str, Any] = {
        "akshare_price_fallback_enabled": True,
        "akshare_price_fallback_attempted": True,
        "akshare_price_fallback_success": None,
        "akshare_price_fallback_applied": False,
        "akshare_price_fallback_reason": None,
        "akshare_price_latest_trade_date": None,
        "akshare_price_vendor": None,
    }
    run_log_entry: dict[str, Any] = {
        "provider": "akshare",
        "dataset": "price_data",
        "symbol": symbol,
        "status": "failed",
        "rows": None,
        "latest_trade_date": None,
        "applied": False,
        "reason": None,
        "error": None,
        "error_type": None,
        "as_of": str(date.today()),
    }

    try:
        ak_result = akshare_provider.get_akshare_asset_data(symbol)
    except Exception as exc:
        fallback_meta["akshare_price_fallback_success"] = False
        fallback_meta["akshare_price_fallback_reason"] = "akshare_unavailable"
        run_log_entry["reason"] = "akshare_unavailable"
        run_log_entry["error"] = str(exc)[:200]
        run_log_entry["error_type"] = type(exc).__name__
        return None, {**fallback_meta, "_akshare_run_log": run_log_entry}

    ak_price_data = ak_result.get("price_data")
    if not ak_price_data:
        fallback_meta["akshare_price_fallback_success"] = False
        fallback_meta["akshare_price_fallback_reason"] = "akshare_unavailable"
        run_log_entry["reason"] = "akshare_unavailable"
        return None, {**fallback_meta, "_akshare_run_log": run_log_entry}

    fallback_meta["akshare_price_fallback_success"] = True

    ak_latest_str = ak_price_data.get("latest_trade_date")
    ak_latest: date | None = None
    if ak_latest_str:
        try:
            ak_latest = date.fromisoformat(ak_latest_str)
        except (ValueError, TypeError):
            pass
    if ak_latest is None:
        # Try extracting from the raw AKShare frame
        ak_df = ak_result.get("_raw_df")
        if ak_df is not None:
            ak_latest = _extract_latest_trade_date(ak_df)

    fallback_meta["akshare_price_latest_trade_date"] = (
        str(ak_latest) if ak_latest else None
    )
    fallback_meta["akshare_price_vendor"] = ak_price_data.get("data_vendor", "unknown")
    if ak_latest is not None:
        ak_price_data["latest_trade_date"] = str(ak_latest)

    run_log_entry["rows"] = ak_price_data.get("history_close")
    if isinstance(run_log_entry["rows"], list):
        run_log_entry["rows"] = len(run_log_entry["rows"])
    run_log_entry["latest_trade_date"] = str(ak_latest) if ak_latest else None

    if ak_latest is None:
        fallback_meta["akshare_price_fallback_reason"] = "akshare_date_unparseable"
        run_log_entry["reason"] = "akshare_date_unparseable"
        return None, {**fallback_meta, "_akshare_run_log": run_log_entry}

    # Conservative strategy: only apply when AKShare is not stale
    ak_is_stale = _is_qmt_history_stale(ak_latest, date.today(), max_stale_days)
    if ak_is_stale:
        fallback_meta["akshare_price_fallback_reason"] = "akshare_stale"
        run_log_entry["reason"] = "akshare_stale"
        return None, {**fallback_meta, "_akshare_run_log": run_log_entry}

    # Only apply when AKShare is strictly newer than QMT
    if qmt_latest_date is not None and ak_latest <= qmt_latest_date:
        fallback_meta["akshare_price_fallback_reason"] = "akshare_not_newer_than_qmt"
        run_log_entry["reason"] = "akshare_not_newer_than_qmt"
        return None, {**fallback_meta, "_akshare_run_log": run_log_entry}

    # AKShare is fresh and newer — adopt it
    ak_price_data["latest_price_source"] = "akshare_price_history_fallback"
    ak_price_data["price_history_source"] = "akshare"
    ak_price_data["price_uses_intraday_tick"] = False
    ak_price_data["price_is_stale"] = False

    fallback_meta["akshare_price_fallback_applied"] = True
    fallback_meta["akshare_price_fallback_reason"] = "applied"
    run_log_entry["status"] = "success"
    run_log_entry["applied"] = True
    run_log_entry["reason"] = "applied"

    return ak_price_data, {**fallback_meta, "_akshare_run_log": run_log_entry}


def _build_provider_run_log(
    symbol: str,
    qmt_status: dict,
    price_data: dict,
    akshare_run_log_entry: dict | None,
) -> list[dict]:
    """Build the provider_run_log list for get_qmt_asset_data."""
    qmt_log = {
        "provider": "qmt",
        "dataset": "price_data",
        "symbol": symbol,
        "status": "success",
        "rows": qmt_status.get("row_count"),
        "latest_trade_date": qmt_status.get("latest_trade_date"),
        "price_stale": price_data.get("price_is_stale"),
        "download_attempted": qmt_status.get("download_attempted"),
        "download_reason": qmt_status.get("download_reason"),
        "download_success": qmt_status.get("download_success"),
        "full_tick_attempted": qmt_status.get("full_tick_attempted"),
        "full_tick_applied": qmt_status.get("full_tick_applied"),
        "full_tick_trade_date": qmt_status.get("full_tick_trade_date"),
        "latest_price_source": price_data.get("latest_price_source"),
        "akshare_price_fallback_attempted": qmt_status.get("akshare_price_fallback_attempted"),
        "akshare_price_fallback_applied": qmt_status.get("akshare_price_fallback_applied"),
        "akshare_price_latest_trade_date": qmt_status.get("akshare_price_latest_trade_date"),
        "error": None,
        "error_type": None,
        "as_of": str(date.today()),
    }
    logs = [qmt_log]
    if akshare_run_log_entry is not None:
        logs.append(akshare_run_log_entry)
    return logs


def _build_effective_price_source_metadata(price_data: dict, qmt_status: dict) -> dict:
    if price_data.get("price_history_source") == "akshare":
        vendor = (
            qmt_status.get("akshare_price_vendor")
            or price_data.get("data_vendor")
            or "unknown"
        )
        return build_price_source_metadata(
            source="akshare",
            confidence=0.7,
            vendor=str(vendor),
        )

    return build_price_source_metadata(
        source="qmt",
        confidence=0.95,
        vendor="qmt",
    )


def get_qmt_asset_data(symbol: str) -> dict:
    """
    Primary data provider for production research.

    The first version connects daily K-line data, basic instrument details and
    turnover amount. Fundamental, valuation and event data are intentionally not
    fabricated here; the orchestrator adds low-confidence placeholders until
    real QMT/fundamental feeds are connected.
    """
    settings = load_qmt_settings()
    asset_type = guess_asset_type(symbol)
    df, qmt_status = _load_qmt_daily_history(symbol, settings)
    detail = _load_qmt_instrument_detail(symbol)

    close_col = _find_column(df, ["close", "收盘"])
    if not close_col:
        raise ProviderSchemaError(f"QMT price data missing close field: {list(df.columns)}")

    amount_col = _find_column(df, ["amount", "成交额"])

    # --- full tick overlay ---
    data_warnings: list[str] = []

    # Initialize tick metadata in qmt_status
    qmt_status["full_tick_attempted"] = False
    qmt_status["full_tick_success"] = None
    qmt_status["full_tick_applied"] = False
    qmt_status["full_tick_reason"] = None
    qmt_status["full_tick_trade_date"] = None
    qmt_status["full_tick_time_tag"] = None
    qmt_status["full_tick_last_price"] = None
    qmt_status["price_source"] = "qmt_kline"

    kline_latest_date = _extract_latest_trade_date(df)
    is_stale = _is_qmt_history_stale(kline_latest_date, date.today(), settings.max_stale_days)

    # Only attempt tick overlay when kline is stale AND config enables it
    if is_stale and settings.use_full_tick_for_stale:
        qmt_status["full_tick_attempted"] = True
        tick = _query_qmt_full_tick(symbol)

        if tick is not None:
            qmt_status["full_tick_success"] = True
            qmt_status["full_tick_trade_date"] = (
                str(tick["tick_trade_date"]) if tick["tick_trade_date"] else None
            )
            qmt_status["full_tick_time_tag"] = tick.get("tick_time_tag")
            qmt_status["full_tick_last_price"] = tick.get("last_price")

            new_df, reason = _apply_intraday_tick_bar(df, tick, kline_latest_date)

            if reason is None:
                # tick applied successfully
                df = new_df
                qmt_status["full_tick_applied"] = True
                qmt_status["price_source"] = "qmt_kline+full_tick"
                # Re-evaluate latest_trade_date
                new_latest = _extract_latest_trade_date(df)
                qmt_status["latest_trade_date"] = str(new_latest) if new_latest else None
                qmt_status["row_count"] = int(len(df))
            else:
                qmt_status["full_tick_reason"] = reason
                data_warnings.append(
                    f"QMT 日 K 仍过期，full tick 未应用（{reason}），未修正最新价。"
                )
        else:
            qmt_status["full_tick_success"] = False
            qmt_status["full_tick_reason"] = "tick_query_failed"
            data_warnings.append(
                "QMT 日 K 仍过期，full tick 无有效最新价格，未修正最新价。"
            )

    # Recompute price_data from (possibly tick-augmented) df
    price_data = build_price_data_from_frame(
        df=df,
        close_col=close_col,
        amount_col=amount_col,
        data_vendor="qmt",
    )

    # Final stale/tick status
    final_latest = _extract_latest_trade_date(df)
    tick_applied = qmt_status["full_tick_applied"]
    final_is_stale = _is_qmt_history_stale(
        final_latest, date.today(), settings.max_stale_days,
    )
    price_data["latest_trade_date"] = str(final_latest) if final_latest else None
    price_data["price_is_stale"] = final_is_stale
    price_data["price_uses_intraday_tick"] = tick_applied
    price_data["latest_price_source"] = (
        "qmt_full_tick_overlay" if tick_applied else "qmt_kline"
    )
    price_data["price_history_source"] = "qmt"

    # --- Layer 3: AKShare price history fallback ---
    akshare_fallback_enabled = _env_bool("QMT_PRICE_AKSHARE_FALLBACK", True)
    akshare_fallback_meta: dict[str, Any] = {
        "akshare_price_fallback_enabled": akshare_fallback_enabled,
        "akshare_price_fallback_attempted": False,
        "akshare_price_fallback_success": None,
        "akshare_price_fallback_applied": False,
        "akshare_price_fallback_reason": "disabled" if not akshare_fallback_enabled else None,
        "akshare_price_latest_trade_date": None,
        "akshare_price_vendor": None,
    }
    akshare_run_log_entry: dict[str, Any] | None = None

    if price_data["price_is_stale"] and akshare_fallback_enabled:
        qmt_latest = _extract_latest_trade_date(df)
        fallback_pd, fallback_meta = _try_akshare_price_fallback(
            symbol=symbol,
            asset_type=asset_type,
            qmt_latest_date=qmt_latest,
            max_stale_days=settings.max_stale_days,
        )
        akshare_run_log_entry = fallback_meta.pop("_akshare_run_log", None)
        akshare_fallback_meta.update(fallback_meta)

        if fallback_pd is not None:
            price_data = fallback_pd
    elif not akshare_fallback_enabled:
        pass  # already set reason=disabled above

    # Merge AKShare fallback metadata into qmt_status
    qmt_status.update(akshare_fallback_meta)

    # Stale warnings if the final sequence remains stale.
    if price_data["price_is_stale"]:
        if akshare_fallback_meta["akshare_price_fallback_applied"]:
            data_warnings.append(
                "QMT 日 K 行情仍可能过期，已使用 AKShare 行情历史重算价格指标。"
            )
        elif akshare_fallback_enabled and akshare_fallback_meta["akshare_price_fallback_attempted"]:
            reason = akshare_fallback_meta.get("akshare_price_fallback_reason", "unknown")
            data_warnings.append(
                f"QMT 日 K 行情仍过期，AKShare 行情 fallback 未应用（{reason}）。"
            )
        else:
            latest_str = price_data["latest_trade_date"]
            if latest_str:
                data_warnings.append(
                    f"QMT 日 K 行情可能过期：最后交易日为 {latest_str}，"
                    f"当前日期为 {date.today()}。"
                )
            else:
                data_warnings.append(
                    "无法识别 QMT 日 K 最新交易日，已按可能过期处理。"
                )

    # Tick success informational warning
    if tick_applied and not akshare_fallback_meta["akshare_price_fallback_applied"]:
        if price_data["price_is_stale"]:
            data_warnings.append(
                "已使用 QMT full tick 更新 K 线末尾 bar，但最新交易日仍可能过期。"
            )
        else:
            data_warnings.append(
                "当日日 K 未落盘，已使用 QMT full tick 构造临时行情 bar。"
            )

    name = (
        detail.get("InstrumentName")
        or detail.get("instrument_name")
        or detail.get("name")
        or (f"{normalize_symbol(symbol)} ETF" if asset_type == "etf" else symbol)
    )

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "name": name,
        "as_of": str(date.today()),
        "data_source": "qmt",
        "price_data": price_data,
        "data_warnings": data_warnings,
        "basic_info": {
            "exchange_id": detail.get("ExchangeID") or detail.get("exchange_id"),
            "product_id": detail.get("ProductID") or detail.get("product_id"),
            "instrument_id": detail.get("InstrumentID") or detail.get("instrument_id"),
            "instrument_name": detail.get("InstrumentName") or detail.get("instrument_name"),
            "float_volume": detail.get("FloatVolume") or detail.get("float_volume"),
            "total_volume": detail.get("TotalVolume") or detail.get("total_volume"),
            "pre_close": detail.get("PreClose") or detail.get("pre_close"),
        },
        "source_metadata": {
            "price_data": _build_effective_price_source_metadata(price_data, qmt_status),
            "qmt_status": qmt_status,
            "basic_info": {
                "source": "qmt",
                "confidence": 0.9 if detail else 0.0,
                "as_of": str(date.today()),
            },
        },
        "provider_run_log": _build_provider_run_log(
            symbol=symbol,
            qmt_status=qmt_status,
            price_data=price_data,
            akshare_run_log_entry=akshare_run_log_entry,
        ),
    }
