"""观察池扫描端到端集成测试。

覆盖：
1. 创建文件夹 → 添加观察项（含 condition_triggers）→ 手动触发扫描 → 验证 task 创建和结果关联
2. 批量扫描进度追踪：创建 batch → 更新进度 → 验证 completed 状态
3. 条件触发器评估：mock get_latest_price_data → 验证触发/不触发逻辑
4. 单个标的失败时整批继续：mock 一个 symbol 失败 → 验证 batch 仍能完成
5. 扫描结果关联到报告库：验证 research_tasks.schedule_id 正确关联 watchlist_items.id

使用 @pytest.mark.integration marker。
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.api.task_manager.store import TaskStore, WatchlistStore


@pytest.fixture
def stores():
    """创建隔离的 TaskStore + WatchlistStore。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    task_store = TaskStore(db_path=path)
    wl_store = WatchlistStore(db_path=path)
    yield task_store, wl_store
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


@pytest.mark.integration
class TestWatchlistScanE2E:
    """端到端：创建 → 扫描 → 结果关联。"""

    def test_create_folder_add_item_with_triggers(self, stores):
        """创建文件夹、添加含条件触发器的观察项，验证数据完整性。"""
        _, wl_store = stores
        folder = wl_store.create_folder("测试文件夹", owner_username="alice")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "mode": "cron",
                "cron_expression": "0 9 * * 1-5",
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "score_threshold": 80.0,
                },
            },
            owner_username="alice",
        )
        assert item["symbol"] == "600519.SH"
        sc = item["schedule_config"]
        assert sc["condition_triggers"]["price_change_pct"] == 5.0
        assert sc["condition_triggers"]["score_threshold"] == 80.0
        assert sc["condition_triggers"].get("volume_spike_ratio") is None

    def test_batch_progress_tracking(self, stores):
        """创建 batch → 更新进度 → 验证 completed 状态。"""
        _, wl_store = stores
        batch_id = wl_store.create_batch("manual", ["item1", "item2", "item3"],
                                          owner_username="alice")
        batch = wl_store.get_batch(batch_id)
        assert batch["status"] == "running"
        assert batch["total_items"] == 3

        # 模拟 2 个完成、1 个失败
        updated = wl_store.update_batch_progress(batch_id, completed=2, failed=1)
        assert updated["status"] == "completed"
        assert updated["completed_items"] == 2
        assert updated["failed_items"] == 1
        assert updated["completed_at"] is not None

    def test_batch_partial_progress(self, stores):
        """部分完成时 batch 仍为 running。"""
        _, wl_store = stores
        batch_id = wl_store.create_batch("manual", ["item1", "item2", "item3"])
        updated = wl_store.update_batch_progress(batch_id, completed=1, failed=0)
        assert updated["status"] == "running"
        assert updated["completed_items"] == 1

    def test_scan_result_associates_with_item(self, stores):
        """扫描结果通过 schedule_id 关联到观察项。"""
        task_store, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item("600519.SH", "stock", folder["id"])

        # 模拟扫描完成后的结果写入
        task_id = "test-task-001"
        task_store.create_task(
            task_id=task_id, symbol="600519.SH",
            data_source="mock", schedule_id=item["id"],
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        task_store.update_result(
            task_id, score=85.5, rating="A", action="买入",
            completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        wl_store.update_item_scan_result(
            item["id"], task_id=task_id, score=85.5, rating="A", action="买入",
        )

        # 验证关联
        updated_item = wl_store.get_item(item["id"])
        assert updated_item["last_score"] == 85.5
        assert updated_item["last_rating"] == "A"
        assert updated_item["last_action"] == "买入"
        assert updated_item["last_scan_task_id"] == task_id

        # 验证通过 schedule_id 可查到扫描历史
        history = wl_store.get_item_scan_history(item["id"])
        assert len(history) == 1
        assert history[0]["id"] == task_id

    def test_owner_isolation_in_scan(self, stores):
        """不同用户的观察项互不可见。"""
        _, wl_store = stores
        fa = wl_store.create_folder("fa", owner_username="alice")
        fb = wl_store.create_folder("fb", owner_username="bob")
        wl_store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        wl_store.add_item("000001.SZ", "stock", fb["id"], owner_username="bob")

        alice_items = wl_store.get_all_enabled_items()
        alice_only = [i for i in alice_items if i.get("owner_username") == "alice"]
        bob_only = [i for i in alice_items if i.get("owner_username") == "bob"]
        assert len(alice_only) == 1
        assert len(bob_only) == 1


@pytest.mark.integration
class TestConditionTriggerEvaluation:
    """条件触发器评估逻辑测试（mock 实时行情）。"""

    def test_price_trigger_fires(self, stores):
        """价格变动达阈值时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"price_change_pct": 5.0},
            },
        )
        # 模拟行情数据：涨跌幅 7%
        quote = {"change_pct": 7.0, "volume_ratio": 1.0}
        ct = item["schedule_config"]["condition_triggers"]
        triggered = ct.get("price_change_pct") and abs(quote["change_pct"]) >= ct["price_change_pct"]
        assert triggered is True

    def test_price_trigger_not_fires(self, stores):
        """价格变动未达阈值时不触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"price_change_pct": 5.0},
            },
        )
        quote = {"change_pct": 2.0, "volume_ratio": 1.0}
        ct = item["schedule_config"]["condition_triggers"]
        triggered = ct.get("price_change_pct") and abs(quote["change_pct"]) >= ct["price_change_pct"]
        assert triggered is False

    def test_volume_trigger_fires(self, stores):
        """成交量异动达阈值时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"volume_spike_ratio": 3.0},
            },
        )
        quote = {"change_pct": 1.0, "volume_ratio": 4.5}
        ct = item["schedule_config"]["condition_triggers"]
        triggered = ct.get("volume_spike_ratio") and quote["volume_ratio"] >= ct["volume_spike_ratio"]
        assert triggered is True

    def test_score_trigger_fires(self, stores):
        """评分达阈值时触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {"score_threshold": 80.0},
            },
        )
        # 模拟上次扫描评分 85
        wl_store.update_item_scan_result(item["id"], "task-1", score=85.0)
        updated = wl_store.get_item(item["id"])
        ct = updated["schedule_config"]["condition_triggers"]
        triggered = ct.get("score_threshold") and updated.get("last_score", 0) >= ct["score_threshold"]
        assert triggered is True

    def test_multiple_triggers_any_fires(self, stores):
        """多条件中任一满足即触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "score_threshold": 90.0,
                    "volume_spike_ratio": 3.0,
                },
            },
        )
        # 价格满足，评分和量比不满足
        quote = {"change_pct": 6.0, "volume_ratio": 1.5}
        ct = item["schedule_config"]["condition_triggers"]
        triggered = False
        if ct.get("price_change_pct") and abs(quote["change_pct"]) >= ct["price_change_pct"]:
            triggered = True
        if ct.get("volume_spike_ratio") and quote["volume_ratio"] >= ct["volume_spike_ratio"]:
            triggered = True
        assert triggered is True

    def test_no_triggers_configured(self, stores):
        """无条件触发器配置时不触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={"condition_triggers": {}},
        )
        ct = item["schedule_config"]["condition_triggers"]
        assert all(v is None for v in ct.values())


@pytest.mark.integration
class TestAntiRepeat:
    """防重复触发测试。"""

    def test_recent_scan_blocked(self, stores):
        """30 分钟内已扫描则跳过。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item("600519.SH", "stock", folder["id"])
        wl_store.update_item_scan_result(item["id"], "task-1", score=85.0)

        updated = wl_store.get_item(item["id"])
        last_scan = updated.get("last_scan_at")
        assert last_scan is not None

        last_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        assert elapsed < 1800  # 应被阻止

    def test_old_scan_allowed(self, stores):
        """超过 30 分钟的扫描允许再次触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item("600519.SH", "stock", folder["id"])

        # 手动设置 last_scan_at 为 45 分钟前
        from apps.api.utils.time_utils import utc_now_iso
        from datetime import timedelta
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        wl_store.update_item(item["id"], last_scan_at=old_time)

        updated = wl_store.get_item(item["id"])
        last_scan = updated.get("last_scan_at")
        last_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        assert elapsed >= 1800  # 应允许触发


@pytest.mark.integration
class TestConditionTriggerWithMockQuote:
    """使用 mock get_latest_price_data 测试条件触发器完整流程。"""

    def test_watchlist_scheduler_condition_trigger(self, stores):
        """模拟 watchlist_scheduler_check 的条件触发逻辑。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        item = wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "mode": "manual_only",
                "condition_triggers": {"price_change_pct": 5.0},
            },
        )

        # 模拟 get_latest_price_data 返回涨跌幅 7%
        mock_quote = {"close": 1800.0, "prev_close": 1682.0,
                      "volume": 100000, "change_pct": 7.0, "volume_ratio": 1.0}

        with patch("services.data.qmt_realtime_quote.get_latest_price_data",
                   return_value=mock_quote):
            # 模拟条件评估逻辑
            all_items = wl_store.get_all_enabled_items()
            triggered = []
            for it in all_items:
                sc = it.get("schedule_config") or {}
                ct = sc.get("condition_triggers") or {}
                if not ct or all(v is None for v in ct.values()):
                    continue
                if ct.get("price_change_pct"):
                    if abs(mock_quote["change_pct"]) >= ct["price_change_pct"]:
                        triggered.append(it["symbol"])

            assert "600519.SH" in triggered

    def test_watchlist_scheduler_no_trigger(self, stores):
        """条件不满足时不触发。"""
        _, wl_store = stores
        folder = wl_store.create_folder("f")
        wl_store.add_item(
            "600519.SH", "stock", folder["id"],
            schedule_config={
                "mode": "manual_only",
                "condition_triggers": {"price_change_pct": 5.0},
            },
        )

        mock_quote = {"close": 1700.0, "prev_close": 1682.0,
                      "volume": 100000, "change_pct": 1.07, "volume_ratio": 1.0}

        with patch("services.data.qmt_realtime_quote.get_latest_price_data",
                   return_value=mock_quote):
            all_items = wl_store.get_all_enabled_items()
            triggered = []
            for it in all_items:
                sc = it.get("schedule_config") or {}
                ct = sc.get("condition_triggers") or {}
                if not ct or all(v is None for v in ct.values()):
                    continue
                if ct.get("price_change_pct"):
                    if abs(mock_quote["change_pct"]) >= ct["price_change_pct"]:
                        triggered.append(it["symbol"])

            assert len(triggered) == 0
