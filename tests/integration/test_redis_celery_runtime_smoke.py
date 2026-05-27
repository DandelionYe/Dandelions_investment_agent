"""Live Redis and Celery runtime smoke tests.

Requires Redis and Celery worker running locally. Skipped unless RUN_RUNTIME_INTEGRATION=1.
"""

from __future__ import annotations

import os

import pytest
import redis

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.redis, pytest.mark.celery, pytest.mark.runtime]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def require_runtime_integration():
    if not _env_enabled("RUN_RUNTIME_INTEGRATION"):
        pytest.skip("set RUN_RUNTIME_INTEGRATION=1 to run runtime smoke tests")


def test_redis_ping():
    from apps.api.celery_app import REDIS_URL  # noqa: PLC0415

    client = redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_celery_worker_responds_to_ping():
    from apps.api.celery_app import celery_app  # noqa: PLC0415

    inspector = celery_app.control.inspect(timeout=5)
    ping_result = inspector.ping()
    assert ping_result, "No Celery workers responded to ping"


def test_celery_worker_has_registered_tasks():
    import apps.api.task_manager.celery_tasks  # noqa: F401, PLC0415
    from apps.api.celery_app import celery_app  # noqa: PLC0415

    inspector = celery_app.control.inspect(timeout=5)
    registered = inspector.registered() or {}
    assert registered, "No Celery workers responded"
    all_tasks = {task for tasks in registered.values() for task in tasks}
    assert "research.run_single" in all_tasks
