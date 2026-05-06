"""观察池存储层测试 — CRUD + 边界条件 + 多对多标签 + batch 进度。"""

import pytest
import tempfile
from pathlib import Path
from apps.api.task_manager.store import WatchlistStore, _new_id, _utc_now_iso


@pytest.fixture
def store():
    """使用临时文件创建隔离的 WatchlistStore。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = WatchlistStore(db_path=path)
    yield s
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


class TestFolders:

    def test_create_and_list(self, store):
        store.create_folder("重点关注")
        store.create_folder("回调观察", description="等待回调的标的")
        folders = store.list_folders()
        assert len(folders) == 2
        names = {f["name"] for f in folders}
        assert names == {"重点关注", "回调观察"}
        assert folders[0]["item_count"] == 0

    def test_get_folder(self, store):
        f = store.create_folder("测试")
        assert store.get_folder(f["id"])["name"] == "测试"

    def test_get_nonexistent(self, store):
        with pytest.raises(KeyError):
            store.get_folder("nonexistent")

    def test_update(self, store):
        f = store.create_folder("old")
        updated = store.update_folder(f["id"], name="new", description="updated")
        assert updated["name"] == "new"
        assert updated["description"] == "updated"
        assert updated["updated_at"] >= f["updated_at"]

    def test_delete_empty(self, store):
        f = store.create_folder("empty")
        store.delete_folder(f["id"])
        with pytest.raises(KeyError):
            store.get_folder(f["id"])

    def test_delete_with_items_raises(self, store):
        f = store.create_folder("has_items")
        store.add_item("600519.SH", "stock", f["id"])
        with pytest.raises(ValueError, match="标的"):
            store.delete_folder(f["id"])


class TestItems:

    def _add_item(self, store, symbol="600519.SH", folder_id=None):
        if folder_id is None:
            folder_id = store.create_folder("默认")["id"]
        return store.add_item(symbol, "stock", folder_id)

    def test_add_and_get(self, store):
        item = self._add_item(store)
        assert item["symbol"] == "600519.SH"
        assert item["asset_type"] == "stock"
        assert item["enabled"] is True
        assert item["folder_name"] is not None
        assert item["tags"] == []

    def test_add_with_tags(self, store):
        folder = store.create_folder("f")
        t1 = store.create_tag("消费")["id"]
        t2 = store.create_tag("白酒")["id"]
        item = store.add_item("600519.SH", "stock", folder["id"], tag_ids=[t1, t2])
        assert len(item["tags"]) == 2
        assert {t["name"] for t in item["tags"]} == {"消费", "白酒"}

    def test_add_duplicate_symbol(self, store):
        folder = store.create_folder("f")
        store.add_item("600519.SH", "stock", folder["id"])
        with pytest.raises(Exception):  # UNIQUE constraint
            store.add_item("600519.SH", "stock", folder["id"])

    def test_list_by_folder(self, store):
        f1 = store.create_folder("f1")
        f2 = store.create_folder("f2")
        store.add_item("600519.SH", "stock", f1["id"])
        store.add_item("000001.SZ", "stock", f2["id"])
        items, total = store.list_items(folder_id=f1["id"])
        assert total == 1
        assert items[0]["symbol"] == "600519.SH"

    def test_list_by_tag(self, store):
        folder = store.create_folder("f")
        t = store.create_tag("银行")["id"]
        store.add_item("600036.SH", "stock", folder["id"], tag_ids=[t])
        store.add_item("000001.SZ", "stock", folder["id"])
        items, total = store.list_items(tag_id=t)
        assert total == 1
        assert items[0]["symbol"] == "600036.SH"

    def test_list_by_enabled(self, store):
        folder = store.create_folder("f")
        i1 = store.add_item("600519.SH", "stock", folder["id"])
        store.add_item("000858.SZ", "stock", folder["id"])
        store.update_item(i1["id"], enabled=False)
        items, total = store.list_items(enabled=True)
        assert total == 1

    def test_pagination(self, store):
        folder = store.create_folder("f")
        for i in range(5):
            store.add_item(f"60051{i}.SH", "stock", folder["id"])
        items, total = store.list_items(page=1, page_size=2)
        assert total == 5
        assert len(items) == 2
        items2, _ = store.list_items(page=3, page_size=2)
        assert len(items2) == 1

    def test_update_item(self, store):
        item = self._add_item(store)
        updated = store.update_item(item["id"], notes="test note", asset_name="测试")
        assert updated["notes"] == "test note"
        assert updated["asset_name"] == "测试"

    def test_update_item_move_folder(self, store):
        f1 = store.create_folder("f1")
        f2 = store.create_folder("f2")
        item = store.add_item("600519.SH", "stock", f1["id"])
        updated = store.update_item(item["id"], folder_id=f2["id"])
        assert updated["folder_name"] == "f2"

    def test_update_item_with_tags(self, store):
        folder = store.create_folder("f")
        t1 = store.create_tag("tag1")["id"]
        t2 = store.create_tag("tag2")["id"]
        item = store.add_item("600519.SH", "stock", folder["id"], tag_ids=[t1])
        store.set_item_tags(item["id"], [t2])
        updated = store.get_item(item["id"])
        assert len(updated["tags"]) == 1
        assert updated["tags"][0]["name"] == "tag2"

    def test_remove_item(self, store):
        item = self._add_item(store)
        store.remove_item(item["id"])
        with pytest.raises(KeyError):
            store.get_item(item["id"])

    def test_get_nonexistent_item(self, store):
        with pytest.raises(KeyError):
            store.get_item("nonexistent")

    def test_update_item_scan_result(self, store):
        item = self._add_item(store)
        store.update_item_scan_result(item["id"], "task-123", score=85.5, rating="A", action="买入")
        updated = store.get_item(item["id"])
        assert updated["last_score"] == 85.5
        assert updated["last_rating"] == "A"
        assert updated["last_action"] == "买入"
        assert updated["last_scan_task_id"] == "task-123"
        assert updated["last_scan_at"] is not None

    def test_default_schedule_config(self, store):
        item = self._add_item(store)
        assert item["schedule_config"] == {}


class TestTags:

    def test_create_and_list(self, store):
        store.create_tag("消费", color="#ff0000")
        store.create_tag("银行")
        tags = store.list_tags()
        assert len(tags) == 2
        assert tags[0]["item_count"] == 0

    def test_create_duplicate_name_raises(self, store):
        store.create_tag("消费")
        with pytest.raises(ValueError, match="已存在"):
            store.create_tag("消费")

    def test_update(self, store):
        t = store.create_tag("old")
        updated = store.update_tag(t["id"], name="new", color="#000")
        assert updated["name"] == "new"
        assert updated["color"] == "#000"

    def test_delete(self, store):
        t = store.create_tag("tmp")
        store.delete_tag(t["id"])
        with pytest.raises(KeyError):
            store.get_tag(t["id"])

    def test_tag_item_count(self, store):
        folder = store.create_folder("f")
        t = store.create_tag("used")["id"]
        store.add_item("600519.SH", "stock", folder["id"], tag_ids=[t])
        store.add_item("000858.SZ", "stock", folder["id"], tag_ids=[t])
        tags = store.list_tags()
        used_tag = next(tg for tg in tags if tg["id"] == t)
        assert used_tag["item_count"] == 2

    def test_cascade_delete_preserves_items(self, store):
        folder = store.create_folder("f")
        t = store.create_tag("tmp")
        tag_id = t["id"]
        item = store.add_item("600519.SH", "stock", folder["id"], tag_ids=[tag_id])
        store.delete_tag(tag_id)
        updated = store.get_item(item["id"])
        assert updated["tags"] == []


class TestBatches:

    def test_create_and_track(self, store):
        batch_id = store.create_batch("manual", ["item1", "item2", "item3"])
        assert batch_id is not None
        batch = store.get_batch(batch_id)
        assert batch["trigger_type"] == "manual"
        assert batch["status"] == "running"
        assert batch["total_items"] == 3
        assert batch["completed_items"] == 0

    def test_update_progress(self, store):
        batch_id = store.create_batch("manual", ["item1", "item2"])
        batch = store.update_batch_progress(batch_id, completed=2, failed=0)
        assert batch["status"] == "completed"
        assert batch["completed_items"] == 2
        assert batch["completed_at"] is not None

    def test_get_nonexistent_batch(self, store):
        with pytest.raises(KeyError):
            store.get_batch("nonexistent")


class TestDueItems:

    def test_get_due_items(self, store):
        folder = store.create_folder("f")
        item = store.add_item("600519.SH", "stock", folder["id"])
        # 无 next_scan_at，不应出现在到期列表中
        due = store.get_due_items()
        assert len(due) == 0

    def test_disabled_item_not_due(self, store):
        folder = store.create_folder("f")
        item = store.add_item("600519.SH", "stock", folder["id"])
        store.update_item(item["id"], next_scan_at="2020-01-01T00:00:00Z", enabled=False)
        due = store.get_due_items()
        assert len(due) == 0

    def test_future_scan_not_due(self, store):
        folder = store.create_folder("f")
        item = store.add_item("600519.SH", "stock", folder["id"])
        store.update_item(item["id"], next_scan_at="2099-01-01T00:00:00Z")
        due = store.get_due_items()
        assert len(due) == 0
