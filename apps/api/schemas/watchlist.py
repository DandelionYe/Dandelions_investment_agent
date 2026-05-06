"""Pydantic models for watchlist API requests and responses."""

from typing import Optional, Literal
from pydantic import BaseModel, Field


# ── Schedule Config ────────────────────────────────────────────

class ConditionTriggers(BaseModel):
    price_change_pct: Optional[float] = Field(
        default=None, description="价格变动百分比阈值（暂未启用）"
    )
    score_threshold: Optional[float] = Field(
        default=None, description="评分阈值（暂未启用）"
    )
    volume_spike_ratio: Optional[float] = Field(
        default=None, description="成交量异动倍数（暂未启用）"
    )


class ScheduleConfig(BaseModel):
    mode: Literal["cron", "interval", "manual_only"] = Field(
        default="cron", description="调度模式：cron / interval / manual_only"
    )
    cron_expression: str = Field(
        default="0 9 * * 1-5",
        description="crontab 表达式（Asia/Shanghai 时区，仅在 mode=cron 时生效）",
    )
    condition_triggers: ConditionTriggers = Field(
        default_factory=ConditionTriggers, description="条件触发器（暂未启用）"
    )
    pause_until: Optional[str] = Field(
        default=None, description="暂停到指定时间（ISO 8601），null 表示未暂停"
    )


# ── Folder ─────────────────────────────────────────────────────

class WatchlistFolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="文件夹名称")
    description: str = Field(default="", description="描述")
    icon: str = Field(default="folder", description="图标（emoji 或图标名）")
    sort_order: int = Field(default=0, description="排序顺序")


class WatchlistFolderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class WatchlistFolderResponse(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    sort_order: int
    item_count: int = 0
    created_at: str
    updated_at: str


# ── Tag ────────────────────────────────────────────────────────

class WatchlistTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=30, description="标签名称")
    color: str = Field(default="#6366f1", description="标签颜色（hex）")


class WatchlistTagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=30)
    color: Optional[str] = None


class WatchlistTagResponse(BaseModel):
    id: str
    name: str
    color: str
    item_count: int = 0
    created_at: str


# ── Item ───────────────────────────────────────────────────────

class WatchlistItemCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, description="股票/ETF 代码")
    asset_type: Literal["stock", "etf"] = Field(..., description="资产类型")
    asset_name: str = Field(default="", description="资产名称（可留空自动识别）")
    folder_id: str = Field(..., description="所属文件夹 ID")
    tag_ids: list[str] = Field(default_factory=list, description="关联标签 ID 列表")
    schedule_config: ScheduleConfig = Field(
        default_factory=ScheduleConfig, description="扫描调度配置"
    )
    notes: str = Field(default="", description="备注")
    target_action: str = Field(default="观察", description="目标操作建议")


class WatchlistItemUpdate(BaseModel):
    symbol: Optional[str] = Field(default=None, min_length=1, max_length=20)
    asset_type: Optional[Literal["stock", "etf"]] = None
    asset_name: Optional[str] = None
    folder_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    schedule_config: Optional[ScheduleConfig] = None
    notes: Optional[str] = None
    target_action: Optional[str] = None
    enabled: Optional[bool] = None


class TagSummary(BaseModel):
    id: str
    name: str
    color: str


class WatchlistItemResponse(BaseModel):
    id: str
    symbol: str
    asset_type: str
    asset_name: str
    folder_id: str
    folder_name: str
    schedule_config: ScheduleConfig
    notes: str
    target_action: str
    enabled: bool
    tags: list[TagSummary]
    last_scan_task_id: Optional[str] = None
    last_score: Optional[float] = None
    last_rating: Optional[str] = None
    last_action: Optional[str] = None
    last_scan_at: Optional[str] = None
    next_scan_at: Optional[str] = None
    created_at: str
    updated_at: str


class WatchlistItemListResponse(BaseModel):
    items: list[WatchlistItemResponse]
    total: int
    page: int
    page_size: int


# ── Scan ───────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    item_ids: Optional[list[str]] = Field(
        default=None, description="要扫描的 item ID 列表（不指定则扫描全部启用的）"
    )
    folder_id: Optional[str] = Field(
        default=None, description="按文件夹扫描（与 item_ids 二选一）"
    )
    trigger_type: Literal["manual", "scheduled"] = Field(
        default="manual", description="触发类型"
    )


class ScanAcceptResponse(BaseModel):
    batch_id: str
    trigger_type: str
    total_items: int
    status: str = "running"
    created_at: str


class ScanProgressResponse(BaseModel):
    batch_id: str
    trigger_type: str
    status: str
    total_items: int
    completed_items: int
    failed_items: int
    created_at: str
    completed_at: Optional[str] = None


class ScanHistoryItem(BaseModel):
    task_id: str
    symbol: str
    score: Optional[float] = None
    rating: Optional[str] = None
    action: Optional[str] = None
    status: str
    created_at: str
    completed_at: Optional[str] = None


class ScanHistoryResponse(BaseModel):
    results: list[ScanHistoryItem]
    total: int
    page: int
    page_size: int
