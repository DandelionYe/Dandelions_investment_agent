"""Live Celery and Redis integration tests.

These tests require Redis and a Celery worker started locally. They are skipped
unless RUN_LIVE_INTEGRATION=1 is set.
"""

from __future__ import annotations

import os

import pytest
import redis

# Import task definitions so custom task names are registered on the app.
import apps.api.task_manager.celery_tasks  # noqa: F401
from apps.api.celery_app import REDIS_URL, celery_app
from apps.api.task_manager.celery_tasks import health_check_beat

pytestmark = [pytest.mark.integration, pytest.mark.live]


def test_redis_broker_is_reachable(require_live_integration: None):
    client = redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_worker_registered_tasks_and_active_queue(require_live_integration: None):
    inspector = celery_app.control.inspect(timeout=3)

    registered = inspector.registered() or {}
    assert registered, "no Celery worker replied to inspect registered"
    flattened_registered = {task for tasks in registered.values() for task in tasks}
    assert "research.run_single" in flattened_registered
    assert "beat.daily_health_check" in flattened_registered
    assert "beat.watchlist_scheduler_check" in flattened_registered
    assert "beat.watchlist_scan" in flattened_registered

    active_queues = inspector.active_queues() or {}
    assert active_queues, "no Celery worker replied to inspect active_queues"
    queue_names = {
        queue["name"]
        for worker_queues in active_queues.values()
        for queue in worker_queues
    }
    scheduled_queues = {
        entry.get("options", {}).get("queue", "celery")
        for entry in celery_app.conf.beat_schedule.values()
    }
    assert scheduled_queues <= queue_names


def test_health_check_task_can_roundtrip_through_worker(require_live_integration: None):
    result = health_check_beat.delay()
    payload = result.get(timeout=float(os.getenv("LIVE_CELERY_RESULT_TIMEOUT", "30")))

    assert payload["db_ok"] is True
    assert payload["message"] == "daily health check completed"

