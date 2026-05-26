"""Local CSMAR financial statement provider.

Reads company-level financial statements from local CSV files,
applies strict as_of visibility rules, and computes TTM / growth metrics.

Only uses consolidated statements (Typrep = 'A').
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
    ProviderUnavailableError,
    get_provider_error_type,
)

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────

_DEFAULT_BASE = Path("data/raw/csmar/financial_statements")

_INCOME_PATH = _DEFAULT_BASE / "Income Statement" / "FS_Comins.csv"
_CFD_PATH = _DEFAULT_BASE / "Cash Flow Statement (Direct Method)" / "FS_Comscfd.csv"
_CFI_PATH = _DEFAULT_BASE / "Cash Flow Statement (Indirect Method)" / "FS_Comscfi.csv"
_BALANCE_PATH = _DEFAULT_BASE / "Balance Sheet" / "FS_Combas.csv"
_DEBT_PATH = _DEFAULT_BASE / "Debt repayment capacity" / "FI_T1.csv"

# ── Column mappings ────────────────────────────────────────────

_INCOME_COLS = [
    "Stkcd", "Accper", "Typrep",
    "B001100000",  # 营业总收入
    "B001101000",  # 营业收入
    "B001201000",  # 营业成本
    "B002000000",  # 净利润
    "B002000101",  # 归母净利润
    "B001000000",  # 利润总额
    "B001300000",  # 营业利润
]

_CFD_COLS = [
    "Stkcd", "Accper", "Typrep",
    "C001000000",  # 经营活动产生的现金流量净额 (direct)
]

_CFI_COLS = [
    "Stkcd", "Accper", "Typrep",
    "D000100000",  # 经营活动产生的现金流量净额 (indirect)
    "D000101000",  # 净利润 (indirect, for cross-check)
]

_BALANCE_COLS = [
    "Stkcd", "Accper", "Typrep",
    "A001000000",  # 资产总计
    "A002000000",  # 负债合计
    "A003100000",  # 归属于母公司所有者权益合计
    "A003000000",  # 所有者权益合计
]

_DEBT_COLS = [
    "Stkcd", "Accper", "Typrep",
    "F011201A",  # 资产负债率
    "F011601A",  # 权益乘数
    "F012301B",  # 经营现金流/负债合计
]

# ── As-of visibility rules ─────────────────────────────────────

# Annual report (Accper = YYYY-12-31): visible after YYYY+1-04-30
# Q1 report   (Accper = YYYY-03-31): visible after YYYY-04-30
# Half-year   (Accper = YYYY-06-30): visible after YYYY-08-31
# Q3 report   (Accper = YYYY-09-30): visible after YYYY-10-31

_VISIBILITY_RULES: dict[tuple[int, int], tuple[int, int]] = {
    (12, 31): (4, 30),   # annual → next year Apr 30
    (3, 31): (4, 30),    # Q1 → same year Apr 30
    (6, 30): (8, 31),    # half-year → same year Aug 31
    (9, 30): (10, 31),   # Q3 → same year Oct 31
}


def _accper_visibility_date(accper: str) -> date | None:
    """Return the date on which a financial report becomes visible.

    Returns None if the Accper is not a valid quarter-end or is 01-01 (initial period).
    """
    try:
        parts = accper.strip().split("-")
        if len(parts) != 3:
            return None
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None

    # Filter out initial-period rows (Accper = YYYY-01-01)
    if m == 1 and d == 1:
        return None

    key = (m, d)
    if key not in _VISIBILITY_RULES:
        return None

    vis_month, vis_day = _VISIBILITY_RULES[key]
    if key == (12, 31):
        # Annual: visible next year
        vis_year = y + 1
    else:
        vis_year = y

    return date(vis_year, vis_month, vis_day)


def _is_visible(accper: str, as_of: str) -> bool:
    """Check if a report with given Accper is visible by as_of date."""
    vis_date = _accper_visibility_date(accper)
    if vis_date is None:
        return False
    try:
        as_of_date = date.fromisoformat(as_of)
    except (ValueError, TypeError):
        return False
    return vis_date <= as_of_date


# ── Symbol normalization ───────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """Normalize to 6-digit code without exchange suffix for CSV matching."""
    value = str(symbol).strip().upper()
    if "." in value:
        code = value.split(".")[0]
    else:
        code = value
    return code.zfill(6)


def _add_exchange_suffix(code: str, original: str) -> str:
    """Add exchange suffix based on code prefix."""
    code = code.lstrip("0") or "0"
    if original.endswith((".SH", ".SZ", ".BJ")):
        return original
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


# ── CSV reading ────────────────────────────────────────────────

def _read_csv_safe(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    """Read a CSMAR CSV with error tolerance for bad rows."""
    if not path.exists():
        raise ProviderUnavailableError(f"CSV file not found: {path}")

    try:
        df = pd.read_csv(
            path,
            usecols=usecols,
            dtype=str,
            encoding="utf-8-sig",
            on_bad_lines="skip",
            engine="python",
        )
    except Exception:
        # Fallback: try with C engine and skip bad lines
        df = pd.read_csv(
            path,
            usecols=usecols,
            dtype=str,
            encoding="utf-8-sig",
            on_bad_lines="skip",
        )

    return df


def _to_float(val: Any) -> float | None:
    """Convert a string value to float, returning None for missing/empty."""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Quarter ordering for TTM ───────────────────────────────────

_QUARTER_ORDER = {
    (3, 31): 0,
    (6, 30): 1,
    (9, 30): 2,
    (12, 31): 3,
}


def _quarter_key(accper: str) -> tuple[int, int] | None:
    """Extract (year, quarter_index) from Accper for sorting."""
    try:
        parts = accper.strip().split("-")
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None
    qi = _QUARTER_ORDER.get((m, d))
    if qi is None:
        return None
    return (y, qi)


# ── Main Provider ──────────────────────────────────────────────

class LocalCSMARFinancialStatementProvider:
    """Reads CSMAR financial statements and computes TTM / growth metrics."""

    provider = "local_csmar"
    dataset = "financial_statements"

    def __init__(
        self,
        income_path: Path | str | None = None,
        cfd_path: Path | str | None = None,
        cfi_path: Path | str | None = None,
        balance_path: Path | str | None = None,
        debt_path: Path | str | None = None,
    ) -> None:
        self.income_path = Path(income_path or os.getenv("CSMAR_INCOME_CSV", _INCOME_PATH))
        self.cfd_path = Path(cfd_path or os.getenv("CSMAR_CFD_CSV", _CFD_PATH))
        self.cfi_path = Path(cfi_path or os.getenv("CSMAR_CFI_CSV", _CFI_PATH))
        self.balance_path = Path(balance_path or os.getenv("CSMAR_BALANCE_CSV", _BALANCE_PATH))
        self.debt_path = Path(debt_path or os.getenv("CSMAR_DEBT_CSV", _DEBT_PATH))
        self._cache: dict[str, pd.DataFrame] = {}

    def get_fundamentals(
        self,
        symbol: str,
        as_of: str,
    ) -> ProviderResult:
        """Get financial fundamentals for a symbol at as_of date.

        Returns a ProviderResult with computed TTM metrics, growth rates,
        margins, ROE, debt ratio, and cash flow quality.
        """
        started = perf_counter()
        code = _normalize_symbol(symbol)

        try:
            data = self._compute_fundamentals(code, as_of)
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=as_of,
                data=data,
                raw={},
                metadata=ProviderMetadata(
                    success=True,
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except (ProviderUnavailableError, ProviderDataQualityError) as exc:
            return ProviderResult(
                provider=self.provider,
                dataset=self.dataset,
                symbol=symbol,
                as_of=as_of,
                data={},
                raw={},
                metadata=ProviderMetadata(
                    success=False,
                    error=str(exc),
                    error_type=get_provider_error_type(exc),
                    latency_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _compute_fundamentals(self, code: str, as_of: str) -> dict[str, Any]:
        """Compute all fundamental metrics from financial statements."""
        warnings: list[str] = []
        missing_reasons: dict[str, str] = {}

        # Load data
        income_df = self._load_income(code)
        cfd_df = self._load_cfd(code)
        cfi_df = self._load_cfi(code)
        balance_df = self._load_balance(code)
        debt_df = self._load_debt(code)

        # Filter by as_of visibility
        income_vis = self._filter_visible(income_df, as_of)
        cfd_vis = self._filter_visible(cfd_df, as_of)
        cfi_vis = self._filter_visible(cfi_df, as_of)
        balance_vis = self._filter_visible(balance_df, as_of)
        debt_vis = self._filter_visible(debt_df, as_of)

        if income_vis.empty and balance_vis.empty:
            raise ProviderDataQualityError(
                f"No visible financial statements for {code} as of {as_of}"
            )

        # Get TTM values from income statement
        ttm = self._compute_ttm(income_vis)

        # Get latest balance sheet
        balance_latest = self._get_latest(balance_vis)

        # Get TTM cash flow
        cfd_ttm = self._compute_ttm_single(cfd_vis, "C001000000")
        cfi_ttm = self._compute_ttm_single(cfi_vis, "D000100000")

        # Get debt ratios from FI_T1
        debt_latest = self._get_latest(debt_vis)

        # ── Revenue TTM ──
        revenue_ttm = ttm.get("B001101000")  # 营业收入
        if revenue_ttm is None:
            revenue_ttm = ttm.get("B001100000")  # fallback: 营业总收入
            if revenue_ttm is not None:
                warnings.append("revenue_ttm uses 营业总收入 as fallback for 营业收入")

        # ── Net profit TTM ──
        net_profit_ttm = ttm.get("B002000101")  # 归母净利润
        if net_profit_ttm is None:
            net_profit_ttm = ttm.get("B002000000")  # fallback: 净利润
            if net_profit_ttm is not None:
                warnings.append("net_profit_ttm uses 净利润 as fallback for 归母净利润")

        # ── Previous year TTM for growth ──
        prev_ttm = self._compute_ttm_prev_year(income_vis)
        prev_revenue_ttm = prev_ttm.get("B001101000") or prev_ttm.get("B001100000")
        prev_net_profit_ttm = prev_ttm.get("B002000101") or prev_ttm.get("B002000000")

        # ── Operating cost TTM ──
        operating_cost_ttm = ttm.get("B001201000")

        # ── Gross margin ──
        gross_margin = None
        if revenue_ttm is not None and operating_cost_ttm is not None:
            if revenue_ttm > 0:
                gross_margin = (revenue_ttm - operating_cost_ttm) / revenue_ttm
            else:
                warnings.append("gross_margin unavailable: revenue_ttm <= 0")
                missing_reasons["gross_margin"] = "revenue_ttm_non_positive"
        elif revenue_ttm is not None and operating_cost_ttm is None:
            warnings.append("gross_margin unavailable: operating_cost missing")
            missing_reasons["gross_margin"] = "operating_cost_missing"

        # ── Net margin ──
        net_margin = None
        if net_profit_ttm is not None and revenue_ttm is not None and revenue_ttm > 0:
            net_margin = net_profit_ttm / revenue_ttm
        elif net_profit_ttm is not None:
            warnings.append("net_margin unavailable: revenue_ttm missing or non-positive")
            missing_reasons["net_margin"] = "revenue_unavailable"

        # ── ROE ──
        roe = None
        parent_equity = _to_float(balance_latest.get("A003100000")) if balance_latest is not None else None
        total_equity = _to_float(balance_latest.get("A003000000")) if balance_latest is not None else None
        avg_parent_equity = None
        avg_total_equity = None
        if balance_latest is not None:
            latest_balance_key = _quarter_key(str(balance_latest.get("Accper", "")))
            if latest_balance_key is not None:
                latest_year, latest_qi = latest_balance_key
                prior_balance = self._find_quarter(balance_vis, latest_year - 1, latest_qi)
                if prior_balance is not None:
                    prior_parent_equity = _to_float(prior_balance.get("A003100000"))
                    prior_total_equity = _to_float(prior_balance.get("A003000000"))
                    if parent_equity is not None and prior_parent_equity is not None:
                        avg_parent_equity = (parent_equity + prior_parent_equity) / 2
                    if total_equity is not None and prior_total_equity is not None:
                        avg_total_equity = (total_equity + prior_total_equity) / 2

        equity_for_roe = avg_parent_equity
        if equity_for_roe is None:
            equity_for_roe = avg_total_equity
            if equity_for_roe is not None and net_profit_ttm is not None:
                warnings.append("ROE uses average total equity as fallback for parent equity")
        if equity_for_roe is None:
            equity_for_roe = parent_equity
            if equity_for_roe is not None and net_profit_ttm is not None:
                warnings.append("ROE uses latest parent equity because prior same-period equity is missing")
        if equity_for_roe is None:
            equity_for_roe = total_equity
            if equity_for_roe is not None and net_profit_ttm is not None:
                warnings.append("ROE uses latest total equity as fallback")

        if net_profit_ttm is not None and equity_for_roe is not None and equity_for_roe > 0:
            roe = net_profit_ttm / equity_for_roe
        elif net_profit_ttm is not None:
            missing_reasons["roe"] = "equity_missing_or_non_positive"

        # ── Debt ratio ──
        debt_ratio = None
        if debt_latest is not None:
            dr = _to_float(debt_latest.get("F011201A"))
            if dr is not None:
                # CSMAR may return as ratio or percentage
                if dr > 1.0:
                    debt_ratio = dr / 100.0
                else:
                    debt_ratio = dr

        if debt_ratio is None:
            total_assets = _to_float(balance_latest.get("A001000000")) if balance_latest is not None else None
            total_liabilities = _to_float(balance_latest.get("A002000000")) if balance_latest is not None else None
            if total_assets is not None and total_assets > 0 and total_liabilities is not None:
                debt_ratio = total_liabilities / total_assets
                warnings.append("debt_ratio computed from balance sheet as fallback")

        # ── Operating cash flow quality ──
        operating_cashflow = cfd_ttm if cfd_ttm is not None else cfi_ttm
        operating_cashflow_quality = None
        if operating_cashflow is not None and net_profit_ttm is not None:
            if net_profit_ttm > 0:
                operating_cashflow_quality = operating_cashflow / net_profit_ttm
            else:
                warnings.append(
                    "operating_cashflow_quality unavailable: net_profit_ttm <= 0"
                )
                missing_reasons["operating_cashflow_quality"] = "net_profit_non_positive"

        # ── Revenue growth ──
        revenue_growth = None
        if revenue_ttm is not None and prev_revenue_ttm is not None and prev_revenue_ttm > 0:
            revenue_growth = (revenue_ttm - prev_revenue_ttm) / prev_revenue_ttm

        # ── Net profit growth ──
        net_profit_growth = None
        if net_profit_ttm is not None and prev_net_profit_ttm is not None:
            if prev_net_profit_ttm > 0:
                net_profit_growth = (net_profit_ttm - prev_net_profit_ttm) / prev_net_profit_ttm
            elif prev_net_profit_ttm < 0 and net_profit_ttm > prev_net_profit_ttm:
                # Loss narrowing
                net_profit_growth = abs(net_profit_ttm - prev_net_profit_ttm) / abs(prev_net_profit_ttm)

        # ── Assemble result ──
        result: dict[str, Any] = {}
        _safe_set(result, "revenue_ttm", revenue_ttm)
        _safe_set(result, "net_profit_ttm", net_profit_ttm)
        _safe_set(result, "roe", roe)
        _safe_set(result, "gross_margin", gross_margin)
        _safe_set(result, "net_margin", net_margin)
        _safe_set(result, "revenue_growth", revenue_growth)
        _safe_set(result, "net_profit_growth", net_profit_growth)
        _safe_set(result, "debt_ratio", debt_ratio)
        _safe_set(result, "operating_cashflow_quality", operating_cashflow_quality)

        if warnings:
            result["_warnings"] = warnings
        if missing_reasons:
            result["_missing_reasons"] = missing_reasons

        return result

    # ── Data loading ────────────────────────────────────────────

    def _load_income(self, code: str) -> pd.DataFrame:
        df = self._cached_read("income", self.income_path, _INCOME_COLS)
        return self._filter_by_code_and_type(df, code)

    def _load_cfd(self, code: str) -> pd.DataFrame:
        df = self._cached_read("cfd", self.cfd_path, _CFD_COLS)
        return self._filter_by_code_and_type(df, code)

    def _load_cfi(self, code: str) -> pd.DataFrame:
        df = self._cached_read("cfi", self.cfi_path, _CFI_COLS)
        return self._filter_by_code_and_type(df, code)

    def _load_balance(self, code: str) -> pd.DataFrame:
        df = self._cached_read("balance", self.balance_path, _BALANCE_COLS)
        return self._filter_by_code_and_type(df, code)

    def _load_debt(self, code: str) -> pd.DataFrame:
        df = self._cached_read("debt", self.debt_path, _DEBT_COLS)
        return self._filter_by_code_and_type(df, code)

    def _cached_read(self, key: str, path: Path, usecols: list[str]) -> pd.DataFrame:
        """Read CSV with caching to avoid re-reading large files."""
        if key not in self._cache:
            self._cache[key] = _read_csv_safe(path, usecols=usecols)
        return self._cache[key]

    def _filter_by_code_and_type(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Filter by Stkcd and Typrep = 'A' (consolidated)."""
        if df.empty:
            return df
        mask = (df["Stkcd"].str.strip() == code) & (df["Typrep"].str.strip() == "A")
        return df[mask].copy()

    def _filter_visible(self, df: pd.DataFrame, as_of: str) -> pd.DataFrame:
        """Filter to only rows visible by as_of date."""
        if df.empty:
            return df
        visible_mask = df["Accper"].apply(lambda x: _is_visible(str(x), as_of))
        result = df[visible_mask].copy()
        # Sort by Accper for TTM calculation
        if not result.empty:
            result["_qkey"] = result["Accper"].apply(_quarter_key)
            result = result.sort_values("_qkey")
            result = result.drop(columns=["_qkey"], errors="ignore")
        return result

    # ── TTM computation ─────────────────────────────────────────

    def _compute_ttm(self, df: pd.DataFrame) -> dict[str, float | None]:
        """Compute TTM values from quarterly cumulative data.

        For cumulative financial data (CSMAR style):
        - Q1 (03-31) = Q1 cumulative
        - Q2 (06-30) = H1 cumulative
        - Q3 (09-30) = 9-month cumulative
        - Q4 (12-31) = full year

        TTM = latest cumulative + (prior year same-period cumulative) - (prior year prior-period cumulative)
        But if we have Q4, TTM = Q4 value directly.
        If we have Q3, TTM = Q3 + Q4_prev - Q3_prev
        If we have Q2, TTM = Q2 + Q4_prev - Q2_prev
        If we have Q1, TTM = Q1 + Q4_prev - Q1_prev

        Simplified: TTM = latest Q4 if available, otherwise latest + delta from prior year.
        """
        if df.empty:
            return {}

        # Get numeric columns (exclude metadata)
        meta_cols = {"Stkcd", "Accper", "Typrep", "IfCorrect", "DeclareDate", "ShortName"}
        value_cols = [c for c in df.columns if c not in meta_cols and not c.startswith("_")]

        # Find latest row
        latest = df.iloc[-1]
        latest_accper = str(latest["Accper"]).strip()
        latest_key = _quarter_key(latest_accper)

        if latest_key is None:
            return {}

        latest_year, latest_qi = latest_key

        # If latest is Q4 (annual), TTM = annual value
        if latest_qi == 3:
            return {col: _to_float(latest.get(col)) for col in value_cols}

        # For Q1/Q2/Q3: TTM = current + prev_year_Q4 - prev_year_same_quarter
        result: dict[str, float | None] = {}
        for col in value_cols:
            current = _to_float(latest.get(col))
            if current is None:
                result[col] = None
                continue

            # Find prev year Q4
            prev_q4 = self._find_quarter(df, latest_year - 1, 3)
            prev_same = self._find_quarter(df, latest_year - 1, latest_qi)

            if prev_q4 is not None and prev_same is not None:
                pv4 = _to_float(prev_q4.get(col))
                pvs = _to_float(prev_same.get(col))
                if pv4 is not None and pvs is not None:
                    result[col] = current + pv4 - pvs
                    continue

            # Fallback: use latest value as-is (annualize not possible)
            result[col] = current

        return result

    def _compute_ttm_single(self, df: pd.DataFrame, col: str) -> float | None:
        """Compute TTM for a single column from a DataFrame."""
        ttm = self._compute_ttm(df)
        return ttm.get(col)

    def _compute_ttm_prev_year(self, df: pd.DataFrame) -> dict[str, float | None]:
        """Compute TTM for the period one year before the latest visible period."""
        if df.empty or len(df) < 2:
            return {}

        latest = df.iloc[-1]
        latest_accper = str(latest["Accper"]).strip()
        latest_key = _quarter_key(latest_accper)
        if latest_key is None:
            return {}

        latest_year, latest_qi = latest_key

        # Take rows up to the same quarter one year earlier. Using all rows in
        # the previous year would compare Q1/Q2/Q3 TTM against the prior annual
        # TTM, which understates or overstates true year-on-year growth.
        prev_year_mask = df["Accper"].apply(
            lambda x: _quarter_key(str(x)) is not None
            and _quarter_key(str(x)) <= (latest_year - 1, latest_qi)
        )
        prev_df = df[prev_year_mask]
        if prev_df.empty:
            return {}

        # Compute TTM on the previous year's data
        return self._compute_ttm(prev_df)

    def _find_quarter(self, df: pd.DataFrame, year: int, qi: int) -> pd.Series | None:
        """Find a row matching a specific year and quarter index."""
        for _, row in df.iterrows():
            key = _quarter_key(str(row["Accper"]).strip())
            if key == (year, qi):
                return row
        return None

    def _get_latest(self, df: pd.DataFrame) -> pd.Series | None:
        """Get the latest row from a sorted DataFrame."""
        if df.empty:
            return None
        return df.iloc[-1]


def _safe_set(d: dict, key: str, value: float | None) -> None:
    """Set a value in dict only if it is not None."""
    if value is not None:
        d[key] = round(value, 6) if isinstance(value, float) else value


# ── Convenience function ───────────────────────────────────────

def is_csmar_financial_enabled() -> bool:
    """Check if CSMAR financial statement data is available."""
    income_path = Path(os.getenv("CSMAR_INCOME_CSV", _INCOME_PATH))
    return income_path.exists()
