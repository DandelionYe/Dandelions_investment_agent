"""Task state constants and status model for Celery task tracking."""

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Celery 任务名常量
CELERY_RESEARCH_TASK = "research.run_single"

# Celery Beat 定时任务名
BEAT_DAILY_HEALTH_CHECK = "beat.daily_health_check"
BEAT_WATCHLIST_SCAN = "beat.watchlist_scan"  # 预留，观察池实现后启用
