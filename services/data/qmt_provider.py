import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from services.data.market_data_utils import (
    build_price_data_from_frame,
    build_price_source_metadata,
    guess_asset_type,
    normalize_symbol,
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
    )


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise RuntimeError(
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
        raise RuntimeError(
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
        df = pd.DataFrame(df)

    return df


def _query_qmt_daily_history(
    symbol: str,
    start: str,
    end: str,
    settings: QMTSettings,
) -> pd.DataFrame:
    xtdata = _import_xtdata()

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

    return _to_dataframe(raw, symbol)


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
        result = xtdata.download_history_data(symbol, settings.period, start, end)

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

    qmt_status = {
        "connected": True,
        "auto_download": settings.auto_download,
        "download_attempted": False,
        "download_success": None,
        "history_start": start,
        "history_end": end,
        "period": settings.period,
        "data_dir": None,
    }

    try:
        qmt_status["data_dir"] = xtdata.get_data_dir()
    except Exception:
        qmt_status["data_dir"] = None

    df = _query_qmt_daily_history(symbol, start, end, settings)

    if df.empty and settings.auto_download:
        qmt_status["download_attempted"] = True
        qmt_status["download_success"] = _download_qmt_daily_history(
            symbol,
            start,
            end,
            settings,
        )
        df = _query_qmt_daily_history(symbol, start, end, settings)

    if df.empty:
        raise RuntimeError(
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
        raise RuntimeError(f"QMT 行情数据缺少 close 字段，当前字段：{list(df.columns)}")

    amount_col = _find_column(df, ["amount", "成交额"])

    price_data = build_price_data_from_frame(
        df=df,
        close_col=close_col,
        amount_col=amount_col,
        data_vendor="qmt",
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
            "price_data": build_price_source_metadata(
                source="qmt",
                confidence=0.95,
                vendor="qmt",
            ),
            "qmt_status": qmt_status,
            "basic_info": {
                "source": "qmt",
                "confidence": 0.9 if detail else 0.0,
                "as_of": str(date.today()),
            },
        },
    }
