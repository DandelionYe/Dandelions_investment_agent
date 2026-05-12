"""Celery Beat schedule configuration tests."""

# Import task definitions so custom task names are registered on the app.
import apps.api.task_manager.celery_tasks  # noqa: F401
from apps.api.celery_app import celery_app


def test_beat_schedule_tasks_are_registered():
    scheduled_tasks = {
        entry["task"]
        for entry in celery_app.conf.beat_schedule.values()
    }

    missing = scheduled_tasks - set(celery_app.tasks.keys())

    assert missing == set()


def test_beat_schedule_uses_default_worker_queue():
    routed_queues = {
        entry.get("options", {}).get("queue")
        for entry in celery_app.conf.beat_schedule.values()
    }

    assert routed_queues <= {None, "celery"}
