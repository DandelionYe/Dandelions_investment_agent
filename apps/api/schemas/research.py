"""Pydantic models for research API requests and responses."""

import uuid
from typing import Optional
from pydantic import BaseModel, Field

from apps.api.utils.time_utils import utc_now_iso


class ResearchRequest(BaseModel):
    symbol: str = Field(
        default="600519.SH",
        description="股票或 ETF 代码，如 600519.SH / 000001.SZ / 510300.SH",
        min_length=1,
        max_length=20,
    )
    data_source: str = Field(
        default="mock",
        pattern="^(qmt|akshare|mock)$",
        description="数据源：qmt / akshare / mock",
    )
    use_llm: bool = Field(default=True, description="是否启用 DeepSeek 辩论")
    max_debate_rounds: int = Field(
        default=3, ge=1, le=4, description="最大辩论轮次"
    )
    use_graph: bool = Field(
        default=True, description="是否使用 LangGraph 完整 pipeline"
    )


class TaskSummary(BaseModel):
    task_id: str
    symbol: str
    data_source: str
    use_llm: bool
    status: str
    score: Optional[float] = None
    rating: Optional[str] = None
    action: Optional[str] = None
    final_opinion: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class ResearchAcceptResponse(BaseModel):
    task_id: str
    status: str
    created_at: str


class TaskStatusResponse(BaseModel):
    task_id: str
    symbol: str
    status: str
    progress: float = 0.0
    progress_message: Optional[str] = None
    score: Optional[float] = None
    rating: Optional[str] = None
    action: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class TaskHistoryResponse(BaseModel):
    tasks: list[TaskSummary]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    detail: str
    error_code: str = "internal_error"
    task_id: Optional[str] = None


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]
