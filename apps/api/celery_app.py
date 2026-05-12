"""Celery 应用定义，含 Beat 定时调度配置。

启动 worker:
    celery -A apps.api.celery_app worker --loglevel=info --concurrency=2

启动 beat（另开终端）:
    celery -A apps.api.celery_app beat --loglevel=info --schedule storage/runtime/celerybeat-schedule

同时启动 worker + beat（开发用）:
    celery -A apps.api.celery_app worker --beat --loglevel=info --concurrency=2 --schedule storage/runtime/celerybeat-schedule
"""

import os
import sys
import platform
from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
REDIS_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")

celery_app = Celery(
    "dandelions_api",
    broker=REDIS_URL,
    backend=REDIS_BACKEND,
    include=["apps.api.task_manager.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_timeout=3,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "retry_on_timeout": False,
    },
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },
    result_backend_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "retry_on_timeout": False,
    },
    task_soft_time_limit=600,   # 10 min 软超时
    task_time_limit=900,        # 15 min 硬超时
    broker_connection_retry_on_startup=True,
    result_expires=3600,        # 结果 1 小时后自动清理
)

if platform.system() == "Windows":
    celery_app.conf.update(worker_pool="solo")

celery_app.conf.beat_schedule = {
    "daily-health-check": {
        "task": "beat.daily_health_check",
        "schedule": crontab(hour=3, minute=17),
        "options": {"queue": "beat"},
    },
    # 观察池调度检查：每 5 分钟检查逐票自定义 cron
    "watchlist-scheduler-check": {
        "task": "beat.watchlist_scheduler_check",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "beat"},
    },
    # 观察池收盘扫描：工作日 15:07
    "watchlist-scan-weekday-close": {
        "task": "beat.watchlist_scan",
        "schedule": crontab(hour=15, minute=7, day_of_week="1-5"),
        "options": {"queue": "beat"},
    },
}
