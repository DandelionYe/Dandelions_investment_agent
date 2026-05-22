"""RBAC 报告访问控制测试。

覆盖：
- bob 知道 alice 的 task_id 也不能下载 alice report（通过 manager 层）。
- admin 可以下载。
- path traversal 校验仍有效。
- 不要因为 report file 存在就绕过 task owner。
"""

import pytest
import tempfile
from pathlib import Path

from apps.api.task_manager.store import TaskStore
from apps.api.task_manager.manager import TaskManager


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


@pytest.fixture
def task_store(db_path):
    return TaskStore(db_path=db_path)


@pytest.fixture
def manager(task_store):
    return TaskManager(store=task_store)


class TestReportAccess:

    def test_bob_cannot_get_alice_report_info(self, task_store, manager):
        """bob 不能获取 alice task 的报告信息。"""
        task_store.create_task(
            task_id="task-alice",
            symbol="600519.SH",
            data_source="mock",
            use_llm=False,
            created_at="2026-01-01T00:00:00Z",
            created_by="alice",
        )
        task_store.update_status("task-alice", "completed", progress=1.0)
        task_store.update_result("task-alice", score=85.0, report_paths={"json": "/tmp/test.json"})

        with pytest.raises(KeyError):
            manager.get_report_info("task-alice", username="bob")

    def test_alice_can_get_own_report_info(self, task_store, manager):
        """alice 可以获取自己 task 的报告信息。"""
        task_store.create_task(
            task_id="task-alice",
            symbol="600519.SH",
            data_source="mock",
            use_llm=False,
            created_at="2026-01-01T00:00:00Z",
            created_by="alice",
        )
        task_store.update_status("task-alice", "completed", progress=1.0)
        task_store.update_result("task-alice", report_paths={"json": "/tmp/test.json"})

        info = manager.get_report_info("task-alice", username="alice")
        assert info["task_id"] == "task-alice"

    def test_admin_can_get_any_report_info(self, task_store, manager):
        """管理员可以获取任何 task 的报告信息。"""
        task_store.create_task(
            task_id="task-bob",
            symbol="000001.SZ",
            data_source="mock",
            use_llm=False,
            created_at="2026-01-01T00:00:00Z",
            created_by="bob",
        )
        task_store.update_status("task-bob", "completed", progress=1.0)
        task_store.update_result("task-bob", report_paths={"json": "/tmp/test.json"})

        info = manager.get_report_info("task-bob", username=None)
        assert info["task_id"] == "task-bob"

    def test_path_traversal_blocked(self):
        """路径遍历攻击被阻止。"""
        from apps.api.routers.reports import _validate_report_path
        import fastapi

        # 尝试遍历到项目根目录
        with pytest.raises(fastapi.HTTPException):
            _validate_report_path("../../etc/passwd")

        with pytest.raises(fastapi.HTTPException):
            _validate_report_path("/etc/passwd")

    def test_nonexistent_task_returns_404(self, task_store, manager):
        """访问不存在的 task 返回 KeyError。"""
        with pytest.raises(KeyError):
            manager.get_report_info("nonexistent", username="alice")
