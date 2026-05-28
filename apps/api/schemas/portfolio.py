"""Pydantic models for portfolio analysis API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, description="股票/ETF 代码")
    asset_type: Literal["stock", "etf"] = Field(default="stock", description="资产类型")
    asset_name: str = Field(default="", description="资产名称（可选）")
    current_weight: Optional[float] = Field(
        default=None, ge=0, le=1,
        description="当前权重（可选，0-1 之间）"
    )


class PortfolioAnalyzeRequest(BaseModel):
    # Source A: explicit positions
    positions: list[PortfolioPosition] = Field(
        default_factory=list,
        description="显式持仓列表（与 watchlist_folder_id 二选一）"
    )
    # Source B: from watchlist
    watchlist_folder_id: Optional[str] = Field(
        default=None,
        description="从观察池文件夹读取持仓（与 positions 二选一）"
    )
    use_watchlist_all: bool = Field(
        default=False,
        description="使用当前用户所有启用的观察项（与 watchlist_folder_id 互斥）"
    )
    # Analysis config
    risk_profile: Literal["conservative", "balanced", "aggressive"] = Field(
        default="balanced",
        description="风险偏好：conservative / balanced / aggressive"
    )
    max_single_weight: float = Field(
        default=0.25, ge=0.05, le=1.0,
        description="单标的权重上限（0.05-1.0）"
    )
    max_industry_weight: float = Field(
        default=0.35, ge=0.1, le=1.0,
        description="单行业权重上限（0.1-1.0）"
    )
    min_cash_weight: float = Field(
        default=0.05, ge=0, le=0.5,
        description="最低现金比例（0-0.5）"
    )


class HoldingResponse(BaseModel):
    symbol: str
    asset_type: str
    asset_name: str
    score: Optional[float] = None
    rating: Optional[str] = None
    action: Optional[str] = None
    risk_level: Optional[str] = None
    volatility_60d: Optional[float] = None
    max_drawdown_60d: Optional[float] = None
    industry: Optional[str] = None
    pe_percentile: Optional[float] = None
    pb_percentile: Optional[float] = None
    target_weight: float = 0.0
    rebalance_action: Optional[str] = None
    rebalance_reason: Optional[str] = None
    data_warnings: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)


class PortfolioAnalyzeResponse(BaseModel):
    analysis_id: str
    generated_at: str
    risk_profile: str
    total_holdings: int
    portfolio_score: Optional[float] = None
    portfolio_rating: Optional[str] = None
    risk_level: Optional[str] = None
    cash_weight: float = 0.0
    holdings: list[HoldingResponse] = Field(default_factory=list)
    industry_exposure: dict[str, float] = Field(default_factory=dict)
    asset_type_exposure: dict[str, float] = Field(default_factory=dict)
    rebalance_suggestions: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
