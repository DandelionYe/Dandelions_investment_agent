"""RBAC 观察池访问控制测试。

覆盖：
- alice 和 bob 可以各自创建同名 folder/tag，以及相同 symbol 的 item。
- alice list folders/items/tags 看不到 bob 的。
- alice 不能 update/delete/get bob 的 folder/tag/item。
- alice 不能把 item 放入 bob 的 folder。
- alice 不能给 item 绑定 bob 的 tag。
- batch progress 按 owner 隔离。
- admin 可以查看或管理全部。
"""

import tempfile
from pathlib import Path

import pytest

from apps.api.task_manager.manager import WatchlistManager
from apps.api.task_manager.store import WatchlistStore


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = WatchlistStore(db_path=path)
    yield s
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


class TestFolderIsolation:

    def test_alice_and_bob_create_same_name_folder(self, store):
        """alice 和 bob 可以创建同名文件夹。"""
        f1 = store.create_folder("重点关注", owner_username="alice")
        f2 = store.create_folder("重点关注", owner_username="bob")
        assert f1["id"] != f2["id"]
        assert f1["owner_username"] == "alice"
        assert f2["owner_username"] == "bob"

    def test_alice_list_folders_sees_only_own(self, store):
        """alice list folders 只看到自己的。"""
        store.create_folder("f-alice", owner_username="alice")
        store.create_folder("f-bob", owner_username="bob")

        alice_folders = store.list_folders(owner_username="alice")
        assert len(alice_folders) == 1
        assert alice_folders[0]["name"] == "f-alice"

    def test_admin_list_folders_sees_all(self, store):
        """管理员 list folders 看到全部。"""
        store.create_folder("f-alice", owner_username="alice")
        store.create_folder("f-bob", owner_username="bob")

        all_folders = store.list_folders(owner_username=None)
        assert len(all_folders) == 2

    def test_get_folder_returns_any(self, store):
        """get_folder 不做 owner 过滤（由上层 router 控制）。"""
        f = store.create_folder("test", owner_username="alice")
        got = store.get_folder(f["id"])
        assert got["id"] == f["id"]


class TestTagIsolation:

    def test_alice_and_bob_create_same_name_tag(self, store):
        """alice 和 bob 可以创建同名标签。"""
        t1 = store.create_tag("消费", owner_username="alice")
        t2 = store.create_tag("消费", owner_username="bob")
        assert t1["id"] != t2["id"]

    def test_alice_list_tags_sees_only_own(self, store):
        """alice list tags 只看到自己的。"""
        store.create_tag("t-alice", owner_username="alice")
        store.create_tag("t-bob", owner_username="bob")

        alice_tags = store.list_tags(owner_username="alice")
        assert len(alice_tags) == 1
        assert alice_tags[0]["name"] == "t-alice"

    def test_admin_list_tags_sees_all(self, store):
        """管理员 list tags 看到全部。"""
        store.create_tag("t-alice", owner_username="alice")
        store.create_tag("t-bob", owner_username="bob")

        all_tags = store.list_tags(owner_username=None)
        assert len(all_tags) == 2

    def test_duplicate_tag_name_per_owner_raises(self, store):
        """同一 owner 不能创建同名标签。"""
        store.create_tag("消费", owner_username="alice")
        with pytest.raises(ValueError, match="已存在"):
            store.create_tag("消费", owner_username="alice")


class TestItemIsolation:

    def test_alice_and_bob_add_same_symbol(self, store):
        """alice 和 bob 可以添加相同 symbol 的观察项。"""
        fa = store.create_folder("fa", owner_username="alice")
        fb = store.create_folder("fb", owner_username="bob")

        i1 = store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        i2 = store.add_item("600519.SH", "stock", fb["id"], owner_username="bob")
        assert i1["id"] != i2["id"]
        assert i1["owner_username"] == "alice"
        assert i2["owner_username"] == "bob"

    def test_alice_list_items_sees_only_own(self, store):
        """alice list items 只看到自己的。"""
        fa = store.create_folder("fa", owner_username="alice")
        fb = store.create_folder("fb", owner_username="bob")
        store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        store.add_item("000001.SZ", "stock", fb["id"], owner_username="bob")

        items, total = store.list_items(owner_username="alice")
        assert total == 1
        assert items[0]["symbol"] == "600519.SH"

    def test_admin_list_items_sees_all(self, store):
        """管理员 list items 看到全部。"""
        fa = store.create_folder("fa", owner_username="alice")
        fb = store.create_folder("fb", owner_username="bob")
        store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        store.add_item("000001.SZ", "stock", fb["id"], owner_username="bob")

        items, total = store.list_items(owner_username=None)
        assert total == 2

    def test_alice_cannot_add_item_to_bobs_folder(self, store):
        """alice 不能把 item 放入 bob 的文件夹。"""
        fb = store.create_folder("fb", owner_username="bob")
        with pytest.raises(KeyError, match="文件夹不存在"):
            store.add_item("600519.SH", "stock", fb["id"], owner_username="alice")

    def test_alice_cannot_bind_bobs_tag(self, store):
        """alice 不能给自己的 item 绑定 bob 的标签。"""
        fa = store.create_folder("fa", owner_username="alice")
        item = store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        tag_bob = store.create_tag("bob-tag", owner_username="bob")

        with pytest.raises(KeyError, match="标签不存在"):
            store.set_item_tags(item["id"], [tag_bob["id"]], owner_username="alice")

    def test_alice_cannot_update_item_to_bobs_folder(self, store):
        """alice 不能把已有 item 移动到 bob 的文件夹。"""
        fa = store.create_folder("fa", owner_username="alice")
        fb = store.create_folder("fb", owner_username="bob")
        item = store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")

        with pytest.raises(KeyError, match="文件夹不存在"):
            store.update_item(item["id"], owner_username="alice", folder_id=fb["id"])

    def test_manager_update_validates_tag_owner(self, store):
        """manager 更新 tag_ids 时也必须校验 tag owner。"""
        manager = WatchlistManager(store=store)
        fa = store.create_folder("fa", owner_username="alice")
        item = store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
        tag_bob = store.create_tag("bob-tag", owner_username="bob")

        with pytest.raises(KeyError, match="标签不存在"):
            manager.update_item(item["id"], username="alice", tag_ids=[tag_bob["id"]])

    def test_same_owner_duplicate_symbol_raises(self, store):
        """同一 owner 不能添加重复 symbol。"""
        f = store.create_folder("f", owner_username="alice")
        store.add_item("600519.SH", "stock", f["id"], owner_username="alice")
        with pytest.raises(ValueError, match="已在观察池中"):
            store.add_item("600519.SH", "stock", f["id"], owner_username="alice")


class TestBatchIsolation:

    def test_create_batch_with_owner(self, store):
        """batch 创建时写入 owner。"""
        batch_id = store.create_batch("manual", ["item1"], owner_username="alice")
        batch = store.get_batch(batch_id)
        assert batch["owner_username"] == "alice"

    def test_get_batch_for_user(self, store):
        """get_batch_for_user 校验 owner。"""
        batch_id = store.create_batch("manual", ["item1"], owner_username="alice")
        batch = store.get_batch_for_user(batch_id, "alice")
        assert batch["id"] == batch_id

        with pytest.raises(KeyError):
            store.get_batch_for_user(batch_id, "bob")

    def test_admin_can_get_any_batch(self, store):
        """管理员可以访问任何 batch（通过 get_batch）。"""
        batch_id = store.create_batch("manual", ["item1"], owner_username="alice")
        batch = store.get_batch(batch_id)
        assert batch["id"] == batch_id


class TestMigration:

    def test_owner_column_migration(self):
        """测试旧表迁移：创建不含 owner 列的表，然后初始化 store 补列。"""
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name

        try:
            # 创建旧版 schema（不含 owner_username）
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS watchlist_folders (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
                    icon TEXT DEFAULT 'folder', sort_order INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist_items (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL UNIQUE,
                    asset_type TEXT NOT NULL, asset_name TEXT DEFAULT '',
                    folder_id TEXT NOT NULL, schedule_config TEXT NOT NULL DEFAULT '{}',
                    notes TEXT DEFAULT '', target_action TEXT DEFAULT '观察',
                    enabled INTEGER NOT NULL DEFAULT 1, last_scan_task_id TEXT,
                    last_score REAL, last_rating TEXT, last_action TEXT,
                    last_scan_at TEXT, next_scan_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist_tags (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    color TEXT DEFAULT '#6366f1', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist_item_tags (
                    item_id TEXT NOT NULL, tag_id TEXT NOT NULL,
                    PRIMARY KEY (item_id, tag_id)
                );
                CREATE TABLE IF NOT EXISTS watchlist_batches (
                    id TEXT PRIMARY KEY, trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running', total_items INTEGER DEFAULT 0,
                    completed_items INTEGER DEFAULT 0, failed_items INTEGER DEFAULT 0,
                    item_ids TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
                    completed_at TEXT
                );
            """)
            # 插入旧数据
            conn.execute(
                "INSERT INTO watchlist_folders (id, name, description, icon, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("old-folder", "旧文件夹", "", "folder", 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            conn.close()

            # 打开 store 触发迁移
            store = WatchlistStore(db_path=path)

            # 验证 owner_username 列已添加，旧数据默认为 'default'
            folders = store.list_folders(owner_username=None)
            assert len(folders) == 1
            assert folders[0]["owner_username"] == "default"
            assert folders[0]["name"] == "旧文件夹"

            # 新数据可以指定 owner
            store.create_folder("新文件夹", owner_username="alice")
            alice_folders = store.list_folders(owner_username="alice")
            assert len(alice_folders) == 1

            # 旧库的 UNIQUE(symbol/name) 应被迁移为 owner 维度唯一
            fa = store.create_folder("fa", owner_username="alice")
            fb = store.create_folder("fb", owner_username="bob")
            store.add_item("600519.SH", "stock", fa["id"], owner_username="alice")
            store.add_item("600519.SH", "stock", fb["id"], owner_username="bob")
            store.create_tag("消费", owner_username="alice")
            store.create_tag("消费", owner_username="bob")

        finally:
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass
