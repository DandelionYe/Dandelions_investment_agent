"""WebSocket 实时进度推送测试。

覆盖：
- Redis Pub/Sub 发布/订阅
- 进度消息格式验证
- WebSocket 端点连接/断开
- 批量扫描进度消息
"""

import json
import pytest
import threading
import time


class TestProgressPublisher:

    def test_publish_progress_sync_no_redis(self, monkeypatch):
        """无 Redis 时 publish 不抛异常（优雅降级）。"""
        from apps.api.websocket.progress_publisher import publish_task_progress
        from apps.api.websocket.redis_pubsub import publish_progress_sync

        def mock_publish(channel, message):
            raise ConnectionRefusedError("mock redis down")

        monkeypatch.setattr(
            "apps.api.websocket.redis_pubsub.publish_progress_sync",
            mock_publish,
        )
        # 不应抛异常
        publish_task_progress("test-123", "running", 0.5, "测试进度", "TEST")

    def test_progress_message_format(self):
        """验证进度消息包含所有必需字段。"""
        from apps.api.websocket.progress_publisher import publish_task_progress

        # 使用 mock 捕获消息
        captured = []

        def mock_publish(channel, message):
            captured.append((channel, message))  # message 已是 dict

        # patch 本地引用（progress_publisher 模块内 import 的绑定）
        import apps.api.websocket.progress_publisher as pp
        orig = pp.publish_progress_sync
        pp.publish_progress_sync = mock_publish
        try:
            publish_task_progress(
                "task-abc", "running", 0.5, "正在研究...", "600519.SH",
            )
            assert len(captured) == 2  # task channel + events channel
            channels = {c[0] for c in captured}
            assert "task:task-abc" in channels
            assert "events" in channels

            msg = captured[0][1]
            assert msg["type"] == "progress"
            assert msg["task_id"] == "task-abc"
            assert msg["symbol"] == "600519.SH"
            assert msg["status"] == "running"
            assert msg["progress"] == 0.5
            assert msg["progress_message"] == "正在研究..."
            assert msg["score"] is None
            assert msg["rating"] is None
            assert msg["error_message"] is None
            assert "timestamp" in msg
        finally:
            pp.publish_progress_sync = orig

    def test_completed_message_includes_score(self):
        """验证完成消息包含评分/评级/建议。"""
        from apps.api.websocket.progress_publisher import publish_task_progress

        captured = []

        def mock_publish(channel, message):
            captured.append((channel, message))  # message 已是 dict

        import apps.api.websocket.progress_publisher as pp
        orig = pp.publish_progress_sync
        pp.publish_progress_sync = mock_publish
        try:
            publish_task_progress(
                "task-xyz", "completed", 1.0, "完成", "000001.SZ",
                score=85.5, rating="A", action="买入",
            )
            msg = captured[0][1]
            assert msg["type"] == "completed"
            assert msg["score"] == 85.5
            assert msg["rating"] == "A"
            assert msg["action"] == "买入"
        finally:
            pp.publish_progress_sync = orig

    def test_failed_message_includes_error(self):
        """验证失败消息包含错误信息。"""
        from apps.api.websocket.progress_publisher import publish_task_progress

        captured = []

        def mock_publish(channel, message):
            captured.append((channel, message))  # message 已是 dict

        import apps.api.websocket.progress_publisher as pp
        orig = pp.publish_progress_sync
        pp.publish_progress_sync = mock_publish
        try:
            publish_task_progress(
                "task-fail", "failed", 0.0, "", "ERROR",
                error_message="QMT 连接超时",
            )
            msg = captured[0][1]
            assert msg["type"] == "failed"
            assert msg["error_message"] == "QMT 连接超时"
        finally:
            pp.publish_progress_sync = orig


class TestBatchProgressPublisher:

    def test_batch_progress_format(self):
        """验证批量扫描进度消息格式。"""
        from apps.api.websocket.progress_publisher import publish_batch_progress

        captured = []

        def mock_publish(channel, message):
            captured.append((channel, message))  # message 已是 dict

        import apps.api.websocket.progress_publisher as pp
        orig = pp.publish_progress_sync
        pp.publish_progress_sync = mock_publish
        try:
            publish_batch_progress(
                "batch-001", "running", 10, 3, 1,
                item_id="item-1", item_symbol="600519.SH",
                item_status="completed", item_score=88.0, item_rating="A",
            )
            assert len(captured) == 2
            channels = {c[0] for c in captured}
            assert "batch:batch-001" in channels
            assert "events" in channels

            msg = captured[0][1]
            assert msg["batch_id"] == "batch-001"
            assert msg["total_items"] == 10
            assert msg["completed_items"] == 3
            assert msg["failed_items"] == 1
            assert msg["item_symbol"] == "600519.SH"
            assert msg["item_score"] == 88.0
        finally:
            pp.publish_progress_sync = orig


class TestStatusTypeMapping:

    def test_status_to_type(self):
        """验证状态到消息类型的映射。"""
        from apps.api.websocket.progress_publisher import _status_to_type

        assert _status_to_type("pending") == "progress"
        assert _status_to_type("running") == "progress"
        assert _status_to_type("completed") == "completed"
        assert _status_to_type("failed") == "failed"
        assert _status_to_type("cancelled") == "cancelled"
        assert _status_to_type("unknown") == "progress"


class TestRedisPubSubConnectivity:
    """需要 Redis 运行的集成测试。"""

    @pytest.mark.skip(reason="需要本地 Redis 运行")
    def test_sync_publish_and_subscribe(self):
        """同步发布 + 异步订阅端到端测试。"""
        import redis
        import redis.asyncio as aioredis
        import asyncio

        REDIS_URL = "redis://127.0.0.1:6379/2"

        async def _test():
            # 订阅
            ar = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = ar.pubsub()
            await pubsub.subscribe("test-channel")

            # 发布（同步）
            r = redis.from_url(REDIS_URL, decode_responses=True)
            r.publish("test-channel", json.dumps({"hello": "world"}))
            r.close()

            # 接收
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = json.loads(msg["data"])
                    assert data["hello"] == "world"
                    break

            await pubsub.unsubscribe("test-channel")
            await ar.close()

        asyncio.run(_test())

    @pytest.mark.skip(reason="需要本地 Redis 运行")
    def test_progress_publisher_with_real_redis(self):
        """完整端到端：publish_task_progress + Redis Pub/Sub 接收。"""
        import redis.asyncio as aioredis
        import asyncio
        from apps.api.websocket.progress_publisher import publish_task_progress

        REDIS_URL = "redis://127.0.0.1:6379/2"

        async def _test():
            ar = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = ar.pubsub()
            await pubsub.subscribe("task:test-real")

            # 发布
            publish_task_progress("test-real", "running", 0.75, "测试消息", "TEST.SH")

            # 接收
            received = None
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received = json.loads(msg["data"])
                    break

            assert received is not None
            assert received["task_id"] == "test-real"
            assert received["progress"] == 0.75
            assert received["type"] == "progress"

            await pubsub.unsubscribe("task:test-real")
            await ar.close()

        asyncio.run(_test())


class TestConnectionManager:

    def test_manager_connect_disconnect(self):
        """连接管理器基本操作验证（不涉及真实 WebSocket）。"""
        from apps.api.websocket.connection_manager import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.connection_count == 0
        assert mgr.active_channels == []

    def test_manager_singleton(self):
        """验证模块级单例。"""
        from apps.api.websocket.connection_manager import manager
        assert manager is not None
        assert manager.connection_count == 0
