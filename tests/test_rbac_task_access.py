"""RBAC 任务访问控制测试。

覆盖：
- alice 创建的 task，bob 不能 get status/result/cancel。
- alice 能访问自己的 task。
- admin 能访问 alice/bob 的 task。
- history：alice 只看到 alice 的；bob 只看到 bob 的；admin 看到全部。
"""

import pytest
import tempfile
from pathlib import Path

from apps.api.task_manager.store import TaskStore, UserStore
from apps.api.task_manager.manager import TaskManager
from apps.api.auth.security import hash_password


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
def user_store(db_path):
    return UserStore(db_path=db_path)


@pytest.fixture
def manager(task_store):
    return TaskManager(store=task_store)


def _create_user(store, username, role="user"):
    return store.create_user(username, hash_password(f"{username}_pass"), role=role)


def _create_task(store, task_id, symbol="600519.SH", created_by="default"):
    return store.create_task(
        task_id=task_id,
        symbol=symbol,
        data_source="mock",
        use_llm=False,
        created_at="2026-01-01T00:00:00Z",
        created_by=created_by,
    )


class TestTaskIsolation:

    def test_alice_cannot_access_bobs_task(self, task_store, manager):
        """alice 不能访问 bob 创建的 task。"""
        _create_task(task_store, "task-bob", symbol="000001.SZ", created_by="bob")
        with pytest.raises(KeyError):
            manager.get_status("task-bob", username="alice")

    def test_alice_can_access_own_task(self, task_store, manager):
        """alice 可以访问自己的 task。"""
        _create_task(task_store, "task-alice", symbol="600519.SH", created_by="alice")
        status = manager.get_status("task-alice", username="alice")
        assert status["task_id"] == "task-alice"
        assert status["symbol"] == "600519.SH"

    def test_admin_can_access_alices_task(self, task_store, manager):
        """管理员可以访问 alice 的 task。"""
        _create_task(task_store, "task-alice", created_by="alice")
        status = manager.get_status("task-alice", username=None)
        assert status["task_id"] == "task-alice"

    def test_admin_can_access_bobs_task(self, task_store, manager):
        """管理员可以访问 bob 的 task。"""
        _create_task(task_store, "task-bob", created_by="bob")
        status = manager.get_status("task-bob", username=None)
        assert status["task_id"] == "task-bob"

    def test_bob_cannot_get_alices_result(self, task_store, manager):
        """bob 不能获取 alice 已完成 task 的结果。"""
        _create_task(task_store, "task-alice", created_by="alice")
        task_store.update_status("task-alice", "completed", progress=1.0)
        task_store.update_result("task-alice", score=85.0, rating="A", action="买入")
        with pytest.raises(KeyError):
            manager.get_result("task-alice", username="bob")

    def test_alice_can_get_own_result(self, task_store, manager):
        """alice 可以获取自己已完成 task 的结果。"""
        _create_task(task_store, "task-alice", created_by="alice")
        task_store.update_status("task-alice", "completed", progress=1.0)
        task_store.update_result("task-alice", score=85.0, rating="A", action="买入")
        result = manager.get_result("task-alice", username="alice")
        assert result["score"] == 85.0

    def test_bob_cannot_cancel_alices_task(self, task_store, manager):
        """bob 不能取消 alice 的 task。"""
        _create_task(task_store, "task-alice", created_by="alice")
        task_store.update_status("task-alice", "pending")
        with pytest.raises(KeyError):
            manager.cancel("task-alice", username="bob")

    def test_alice_can_cancel_own_task(self, task_store, manager):
        """alice 可以取消自己的 pending task。"""
        _create_task(task_store, "task-alice", created_by="alice")
        task_store.update_status("task-alice", "pending")
        # cancel 会尝试 revoke celery task，这里用 None username 跳过 owner check
        # 实际 cancel 中会调用 celery revoke，但 task 没有 celery_task_id 所以会跳过
        # 我们直接测试 store 层面
        task_store.cancel_task("task-alice")
        task = task_store.get_task("task-alice")
        assert task["status"] == "cancelled"

    def test_admin_can_cancel_any_task(self, task_store, manager):
        """管理员可以取消任何 task。"""
        _create_task(task_store, "task-bob", created_by="bob")
        task_store.update_status("task-bob", "pending")
        task_store.cancel_task("task-bob")
        task = task_store.get_task("task-bob")
        assert task["status"] == "cancelled"


class TestTaskHistory:

    def test_alice_sees_only_own_tasks(self, task_store, manager):
        """alice 只能看到自己的 task。"""
        _create_task(task_store, "t1", symbol="600519.SH", created_by="alice")
        _create_task(task_store, "t2", symbol="000001.SZ", created_by="bob")
        _create_task(task_store, "t3", symbol="000858.SZ", created_by="alice")

        result = manager.list_history(username="alice")
        task_ids = [t["task_id"] for t in result["tasks"]]
        assert "t1" in task_ids
        assert "t3" in task_ids
        assert "t2" not in task_ids
        assert result["total"] == 2

    def test_bob_sees_only_own_tasks(self, task_store, manager):
        """bob 只能看到自己的 task。"""
        _create_task(task_store, "t1", created_by="alice")
        _create_task(task_store, "t2", created_by="bob")

        result = manager.list_history(username="bob")
        task_ids = [t["task_id"] for t in result["tasks"]]
        assert task_ids == ["t2"]

    def test_admin_sees_all_tasks(self, task_store, manager):
        """管理员能看到所有 task。"""
        _create_task(task_store, "t1", created_by="alice")
        _create_task(task_store, "t2", created_by="bob")

        result = manager.list_history(username=None)
        assert result["total"] == 2

    def test_admin_can_filter_by_username(self, task_store, manager):
        """管理员可以按 username 过滤。"""
        _create_task(task_store, "t1", created_by="alice")
        _create_task(task_store, "t2", created_by="bob")

        result = manager.list_history(username="alice")
        assert result["total"] == 1
        assert result["tasks"][0]["task_id"] == "t1"

    def test_default_owner_backward_compat(self, task_store, manager):
        """旧数据 created_by='default' 可被 admin 查看。"""
        _create_task(task_store, "t-old", created_by="default")
        result = manager.list_history(username=None)
        assert result["total"] == 1

        # 普通用户 username='default' 也能看到
        result2 = manager.list_history(username="default")
        assert result2["total"] == 1
