"""FastAPI 依赖注入。

提供共享依赖供 routers 使用。
"""

from apps.api.task_manager.manager import TaskManager
from apps.api.task_manager.store import get_task_store


def get_task_manager() -> TaskManager:
    return TaskManager(store=get_task_store())
