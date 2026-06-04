"""Pydantic models for portfolio analysis API."""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

# 权重合计上限容忍度：允许浮点舍入误差（如 0.1+0.2+0.3+0.4 = 1.0000000000000002）
MAX_WEIGHT_TOTAL = 1.0001


class PortfolioPosition(BaseModel):
    symbol: str = Field(
        ...,
        min_length=1,
        max_length=20,
        pattern=r"^[0-9A-Za-z._-]+$",
        description="股票/ETF 代码（如 600519.SH，自动去除首尾空格并转大写）"
    )
    asset_type: Literal["stock", "etf"] = Field(default="stock", description="资产类型")
    asset_name: str = Field(default="", description="资产名称（可选）")
    current_weight: Optional[float] = Field(
        default=None, ge=0, le=1,
        description="当前权重（可选，0-1 之间）"
    )

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Strip whitespace and uppercase symbol."""
        return str(v).strip().upper()


class PortfolioAnalyzeRequest(BaseModel):
    # Source A: explicit positions
    positions: list[PortfolioPosition] = Field(
        default_factory=list,
        description="显式持仓列表（与 watchlist_folder_id 二选一）"
    )
    # Source B: from watchlist
    watchlist_folder_id: Optional[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    ] = Field(
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

    @model_validator(mode="after")
    def validate_request(self):
        """Validate source exclusivity and weight constraints."""
        has_positions = len(self.positions) > 0
        has_folder = self.watchlist_folder_id is not None
        has_all = self.use_watchlist_all

        sources = sum([has_positions, has_folder, has_all])
        if sources == 0:
            raise ValueError(
                "请提供 positions 或 watchlist_folder_id 或 use_watchlist_all 之一"
            )
        if sources > 1:
            raise ValueError(
                "positions、watchlist_folder_id、use_watchlist_all 互斥，请只指定一种来源"
            )
        # Validate total current_weight does not exceed 100%
        if has_positions:
            total = sum(p.current_weight for p in self.positions if p.current_weight is not None)
            if total > MAX_WEIGHT_TOTAL:
                raise ValueError(
                    f"当前权重合计为 {total:.1%}，不能超过 100%"
                )
        return self


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
    current_weight: float = 0.0
    target_weight: float = 0.0
    delta_weight: float = 0.0
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
    cash_weight: float = Field(
        default=0.0,
        deprecated=True,
        description="现金权重兼容别名，等同 target_cash_weight。请使用 target_cash_weight。",
    )
    target_cash_weight: float = Field(default=0.0, description="目标现金权重")
    current_cash_weight: Optional[float] = Field(default=None, description="当前现金权重（仅在提供当前权重时有值）")
    holdings: list[HoldingResponse] = Field(default_factory=list)
    industry_exposure: dict[str, float] = Field(default_factory=dict)
    asset_type_exposure: dict[str, float] = Field(default_factory=dict)
    rebalance_suggestions: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
