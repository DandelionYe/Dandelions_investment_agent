"""SQLite 持久化层 — 任务状态 + 观察池。

支持同步调用（Celery worker）和通过 run_in_executor 的异步调用（FastAPI）。
设计为可替换后端 —— 实现相同的接口即可切换到 PostgreSQL。
"""

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from apps.api.schemas.task import TaskStatus
from apps.api.utils.time_utils import utc_now_iso

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "storage" / "tasks.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_tasks (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    data_source     TEXT NOT NULL DEFAULT 'mock',
    use_llm         INTEGER NOT NULL DEFAULT 1,
    max_debate_rounds INTEGER DEFAULT 3,
    use_graph       INTEGER DEFAULT 1,

    status          TEXT NOT NULL DEFAULT 'pending',
    progress        REAL DEFAULT 0.0,
    progress_message TEXT,

    celery_task_id  TEXT,
    schedule_id     TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,

    score           REAL,
    rating          TEXT,
    action          TEXT,
    final_opinion   TEXT,

    report_paths    TEXT,
    error_message   TEXT,
    created_by      TEXT DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON research_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON research_tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_symbol ON research_tasks(symbol);
"""


class TaskStore:
    """SQLite 任务存储，线程安全。"""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    # ── 内部 ──────────────────────────────────────────────────

    def _get_conn(self, writable: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if writable:
            conn.execute("BEGIN IMMEDIATE")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    # ── 写入 ──────────────────────────────────────────────────

    def create_task(
        self,
        task_id: str,
        symbol: str,
        data_source: str = "mock",
        use_llm: bool = True,
        max_debate_rounds: int = 3,
        use_graph: bool = True,
        celery_task_id: str | None = None,
        schedule_id: str | None = None,
        created_at: str = "",
        created_by: str = "default",
    ) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO research_tasks
                       (id, symbol, data_source, use_llm, max_debate_rounds,
                        use_graph, celery_task_id, schedule_id, created_at, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_id, symbol, data_source, int(use_llm), max_debate_rounds,
                        int(use_graph), celery_task_id, schedule_id, created_at, created_by,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_task(task_id)

    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        progress: float | None = None,
        progress_message: str | None = None,
        celery_task_id: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                sets = ["status = ?"]
                params: list = [status]

                if progress is not None:
                    sets.append("progress = ?")
                    params.append(progress)
                if progress_message is not None:
                    sets.append("progress_message = ?")
                    params.append(progress_message)
                if celery_task_id is not None:
                    sets.append("celery_task_id = ?")
                    params.append(celery_task_id)
                if started_at is not None:
                    sets.append("started_at = ?")
                    params.append(started_at)
                if completed_at is not None:
                    sets.append("completed_at = ?")
                    params.append(completed_at)
                if error_message is not None:
                    sets.append("error_message = ?")
                    params.append(error_message)

                params.append(task_id)
                conn.execute(
                    f"UPDATE research_tasks SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_task(task_id)

    def update_result(
        self,
        task_id: str,
        *,
        score: float | None = None,
        rating: str | None = None,
        action: str | None = None,
        final_opinion: str | None = None,
        report_paths: dict | None = None,
        completed_at: str | None = None,
    ) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                sets = []
                params: list = []

                if score is not None:
                    sets.append("score = ?")
                    params.append(score)
                if rating is not None:
                    sets.append("rating = ?")
                    params.append(rating)
                if action is not None:
                    sets.append("action = ?")
                    params.append(action)
                if final_opinion is not None:
                    sets.append("final_opinion = ?")
                    params.append(final_opinion)
                if report_paths is not None:
                    sets.append("report_paths = ?")
                    params.append(json.dumps(report_paths, ensure_ascii=False))
                if completed_at is not None:
                    sets.append("completed_at = ?")
                    params.append(completed_at)

                if sets:
                    params.append(task_id)
                    conn.execute(
                        f"UPDATE research_tasks SET {', '.join(sets)} WHERE id = ?",
                        params,
                    )
                    conn.commit()
            finally:
                conn.close()
        return self.get_task(task_id)

    # ── 查询 ──────────────────────────────────────────────────

    def get_task(self, task_id: str) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM research_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"任务不存在：{task_id}")
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_task_for_user(self, task_id: str, username: str) -> dict:
        task = self.get_task(task_id)
        if task.get("created_by") != username:
            raise KeyError(f"任务不存在：{task_id}")
        return task

    def list_tasks(
        self,
        symbol: str | None = None,
        status: str | None = None,
        username: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        conn = self._get_conn()
        try:
            where = []
            params: list = []
            if symbol:
                where.append("symbol = ?")
                params.append(symbol)
            if status:
                where.append("status = ?")
                params.append(status)
            if username:
                where.append("created_by = ?")
                params.append(username)

            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            count = conn.execute(
                f"SELECT COUNT(*) FROM research_tasks {where_clause}", params
            ).fetchone()[0]

            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM research_tasks {where_clause} "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            return [self._row_to_dict(r) for r in rows], count
        finally:
            conn.close()

    def cancel_task(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if task["status"] not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"只能取消 pending 或 running 状态的任务，当前：{task['status']}")
        return self.update_status(task_id, TaskStatus.CANCELLED)

    # ── 工具 ──────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("report_paths") and isinstance(d["report_paths"], str):
            d["report_paths"] = json.loads(d["report_paths"])
        d["use_llm"] = bool(d.get("use_llm", True))
        d["use_graph"] = bool(d.get("use_graph", True))
        return d


# ═══════════════════════════════════════════════════════════════
# 观察池持久化
# ═══════════════════════════════════════════════════════════════

_WATCHLIST_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS watchlist_folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT DEFAULT 'folder',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'etf')),
    asset_name TEXT DEFAULT '',
    folder_id TEXT NOT NULL REFERENCES watchlist_folders(id) ON DELETE RESTRICT,
    schedule_config TEXT NOT NULL DEFAULT '{}',
    notes TEXT DEFAULT '',
    target_action TEXT DEFAULT '观察',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_scan_task_id TEXT,
    last_score REAL,
    last_rating TEXT,
    last_action TEXT,
    last_scan_at TEXT,
    next_scan_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#6366f1',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_item_tags (
    item_id TEXT NOT NULL REFERENCES watchlist_items(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES watchlist_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE IF NOT EXISTS watchlist_batches (
    id TEXT PRIMARY KEY,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual', 'scheduled', 'condition')),
    status TEXT NOT NULL DEFAULT 'running',
    total_items INTEGER DEFAULT 0,
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    item_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_wl_items_folder ON watchlist_items(folder_id);
CREATE INDEX IF NOT EXISTS idx_wl_items_enabled ON watchlist_items(enabled);
CREATE INDEX IF NOT EXISTS idx_wl_items_next_scan ON watchlist_items(next_scan_at);
CREATE INDEX IF NOT EXISTS idx_wl_items_symbol ON watchlist_items(symbol);
CREATE INDEX IF NOT EXISTS idx_wl_item_tags_tag ON watchlist_item_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_wl_batches_status ON watchlist_batches(status);
CREATE INDEX IF NOT EXISTS idx_wl_batches_created ON watchlist_batches(created_at DESC);
"""



def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class WatchlistStore:
    """观察池 SQLite 存储，线程安全。"""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    # ── 内部 ──────────────────────────────────────────────────

    def _get_conn(self, writable: bool = False) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            uri = "file::memory:?cache=shared"
        else:
            uri = self._db_path
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        if self._db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if writable:
            conn.execute("BEGIN IMMEDIATE")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript(_WATCHLIST_SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    # ── 文件夹 CRUD ────────────────────────────────────────────

    def create_folder(
        self,
        name: str,
        description: str = "",
        icon: str = "folder",
        sort_order: int = 0,
    ) -> dict:
        folder_id = _new_id()
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO watchlist_folders (id, name, description, icon, sort_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (folder_id, name, description, icon, sort_order, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_folder(folder_id)

    def list_folders(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT f.*, COUNT(wi.id) AS item_count
                   FROM watchlist_folders f
                   LEFT JOIN watchlist_items wi ON wi.folder_id = f.id
                   GROUP BY f.id
                   ORDER BY f.sort_order, f.name"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_folder(self, folder_id: str) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM watchlist_folders WHERE id = ?", (folder_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"文件夹不存在：{folder_id}")
            d = dict(row)
            d["item_count"] = conn.execute(
                "SELECT COUNT(*) FROM watchlist_items WHERE folder_id = ?", (folder_id,)
            ).fetchone()[0]
            return d
        finally:
            conn.close()

    def update_folder(self, folder_id: str, **kwargs) -> dict:
        allowed = {"name", "description", "icon", "sort_order"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_folder(folder_id)
        updates["updated_at"] = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                sets = [f"{k} = ?" for k in updates]
                params = list(updates.values()) + [folder_id]
                conn.execute(
                    f"UPDATE watchlist_folders SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id: str) -> None:
        folder = self.get_folder(folder_id)
        if folder.get("item_count", 0) > 0:
            raise ValueError(
                f"文件夹「{folder['name']}」中还有 {folder['item_count']} 个标的，请先移走或删除它们。"
            )
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM watchlist_folders WHERE id = ?", (folder_id,))
                conn.commit()
            finally:
                conn.close()

    # ── 观察项 CRUD ────────────────────────────────────────────

    def add_item(
        self,
        symbol: str,
        asset_type: str,
        folder_id: str,
        schedule_config: dict | None = None,
        notes: str = "",
        target_action: str = "观察",
        asset_name: str = "",
        tag_ids: list[str] | None = None,
    ) -> dict:
        self.get_folder(folder_id)  # 确保文件夹存在
        item_id = _new_id()
        now = utc_now_iso()
        schedule_json = json.dumps(schedule_config or {}, ensure_ascii=False)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO watchlist_items
                       (id, symbol, asset_type, asset_name, folder_id, schedule_config,
                        notes, target_action, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, symbol, asset_type, asset_name, folder_id, schedule_json,
                     notes, target_action, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        if tag_ids:
            self.set_item_tags(item_id, tag_ids)
        return self.get_item(item_id)

    def get_item(self, item_id: str) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT wi.*, wf.name AS folder_name
                   FROM watchlist_items wi
                   JOIN watchlist_folders wf ON wf.id = wi.folder_id
                   WHERE wi.id = ?""",
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"观察项不存在：{item_id}")
            d = self._row_to_item_dict(row)
            d["tags"] = self._get_item_tags(conn, item_id)
            return d
        finally:
            conn.close()

    def list_items(
        self,
        folder_id: str | None = None,
        tag_id: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        conn = self._get_conn()
        try:
            where = []
            params: list = []
            if folder_id:
                where.append("wi.folder_id = ?")
                params.append(folder_id)
            if enabled is not None:
                where.append("wi.enabled = ?")
                params.append(int(enabled))
            if tag_id:
                where.append("wi.id IN (SELECT item_id FROM watchlist_item_tags WHERE tag_id = ?)")
                params.append(tag_id)

            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            count = conn.execute(
                f"SELECT COUNT(*) FROM watchlist_items wi {where_clause}", params
            ).fetchone()[0]

            offset = (page - 1) * page_size
            rows = conn.execute(
                f"""SELECT wi.*, wf.name AS folder_name
                    FROM watchlist_items wi
                    JOIN watchlist_folders wf ON wf.id = wi.folder_id
                    {where_clause}
                    ORDER BY wi.updated_at DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset],
            ).fetchall()
            items = []
            for row in rows:
                d = self._row_to_item_dict(row)
                d["tags"] = self._get_item_tags(conn, row["id"])
                items.append(d)
            return items, count
        finally:
            conn.close()

    def update_item(self, item_id: str, **kwargs) -> dict:
        allowed = {
            "symbol", "asset_type", "asset_name", "folder_id", "schedule_config",
            "notes", "target_action", "enabled",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if "schedule_config" in updates and isinstance(updates["schedule_config"], dict):
            updates["schedule_config"] = json.dumps(updates["schedule_config"], ensure_ascii=False)
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        if "folder_id" in updates:
            self.get_folder(updates["folder_id"])
        if not updates:
            return self.get_item(item_id)
        updates["updated_at"] = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                sets = [f"{k} = ?" for k in updates]
                params = list(updates.values()) + [item_id]
                conn.execute(
                    f"UPDATE watchlist_items SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_item(item_id)

    def remove_item(self, item_id: str) -> None:
        self.get_item(item_id)  # 确保存在
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM watchlist_items WHERE id = ?", (item_id,))
                conn.commit()
            finally:
                conn.close()

    def update_item_scan_result(
        self,
        item_id: str,
        task_id: str,
        score: float | None = None,
        rating: str | None = None,
        action: str | None = None,
    ) -> None:
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                sets = ["last_scan_task_id = ?", "last_scan_at = ?", "updated_at = ?"]
                params = [task_id, now, now]
                if score is not None:
                    sets.append("last_score = ?")
                    params.append(score)
                if rating is not None:
                    sets.append("last_rating = ?")
                    params.append(rating)
                if action is not None:
                    sets.append("last_action = ?")
                    params.append(action)
                params.append(item_id)
                conn.execute(
                    f"UPDATE watchlist_items SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()

    # ── 标签 CRUD ──────────────────────────────────────────────

    def create_tag(self, name: str, color: str = "#6366f1") -> dict:
        tag_id = _new_id()
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO watchlist_tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
                    (tag_id, name, color, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"标签名称已存在：{name}")
            finally:
                conn.close()
        return self.get_tag(tag_id)

    def list_tags(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT t.*, COUNT(it.item_id) AS item_count
                   FROM watchlist_tags t
                   LEFT JOIN watchlist_item_tags it ON it.tag_id = t.id
                   GROUP BY t.id
                   ORDER BY t.name"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_tag(self, tag_id: str) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM watchlist_tags WHERE id = ?", (tag_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"标签不存在：{tag_id}")
            d = dict(row)
            d["item_count"] = conn.execute(
                "SELECT COUNT(*) FROM watchlist_item_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()[0]
            return d
        finally:
            conn.close()

    def update_tag(self, tag_id: str, **kwargs) -> dict:
        allowed = {"name", "color"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_tag(tag_id)
        with self._lock:
            conn = self._get_conn()
            try:
                sets = [f"{k} = ?" for k in updates]
                params = list(updates.values()) + [tag_id]
                conn.execute(
                    f"UPDATE watchlist_tags SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"标签名称已存在：{updates.get('name')}")
            finally:
                conn.close()
        return self.get_tag(tag_id)

    def delete_tag(self, tag_id: str) -> None:
        self.get_tag(tag_id)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM watchlist_tags WHERE id = ?", (tag_id,))
                conn.commit()
            finally:
                conn.close()

    # ── 项-标签 关联 ────────────────────────────────────────────

    def set_item_tags(self, item_id: str, tag_ids: list[str]) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM watchlist_item_tags WHERE item_id = ?", (item_id,))
                for tid in tag_ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist_item_tags (item_id, tag_id) VALUES (?, ?)",
                        (item_id, tid),
                    )
                conn.commit()
            finally:
                conn.close()

    # ── 批量扫描 ──────────────────────────────────────────────

    def create_batch(self, trigger_type: str, item_ids: list[str]) -> str:
        batch_id = _new_id()
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO watchlist_batches (id, trigger_type, status, total_items, item_ids, created_at)
                       VALUES (?, ?, 'running', ?, ?, ?)""",
                    (batch_id, trigger_type, len(item_ids), json.dumps(item_ids), now),
                )
                conn.commit()
            finally:
                conn.close()
        return batch_id

    def update_batch_progress(self, batch_id: str, completed: int, failed: int) -> dict:
        now = utc_now_iso()
        done = completed + failed
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """UPDATE watchlist_batches
                       SET completed_items = ?,
                           failed_items = ?,
                           status = CASE WHEN ? >= total_items THEN 'completed' ELSE 'running' END,
                           completed_at = CASE WHEN ? >= total_items THEN ? ELSE NULL END
                       WHERE id = ?""",
                    (completed, failed, done, done, now, batch_id),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_batch(batch_id)

    def get_batch(self, batch_id: str) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM watchlist_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"扫描批次不存在：{batch_id}")
            d = dict(row)
            if isinstance(d.get("item_ids"), str):
                d["item_ids"] = json.loads(d["item_ids"])
            return d
        finally:
            conn.close()

    # ── 扫描调度查询 ──────────────────────────────────────────

    def get_due_items(self) -> list[dict]:
        conn = self._get_conn()
        try:
            now = utc_now_iso()
            rows = conn.execute(
                """SELECT wi.*, wf.name AS folder_name
                   FROM watchlist_items wi
                   JOIN watchlist_folders wf ON wf.id = wi.folder_id
                   WHERE wi.enabled = 1
                     AND wi.next_scan_at IS NOT NULL
                     AND wi.next_scan_at <= ?""",
                (now,),
            ).fetchall()
            items = []
            for row in rows:
                d = self._row_to_item_dict(row)
                d["tags"] = self._get_item_tags(conn, row["id"])
                items.append(d)
            return items
        finally:
            conn.close()

    def get_all_enabled_items(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT wi.*, wf.name AS folder_name
                   FROM watchlist_items wi
                   JOIN watchlist_folders wf ON wf.id = wi.folder_id
                   WHERE wi.enabled = 1
                   ORDER BY wi.symbol"""
            ).fetchall()
            items = []
            for row in rows:
                d = self._row_to_item_dict(row)
                d["tags"] = self._get_item_tags(conn, row["id"])
                items.append(d)
            return items
        finally:
            conn.close()

    def get_item_scan_history(self, item_id: str, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, symbol, score, rating, action, status, created_at, completed_at
                   FROM research_tasks
                   WHERE schedule_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (item_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _get_item_tags(conn: sqlite3.Connection, item_id: str) -> list[dict]:
        rows = conn.execute(
            """SELECT t.id, t.name, t.color
               FROM watchlist_tags t
               JOIN watchlist_item_tags it ON it.tag_id = t.id
               WHERE it.item_id = ?""",
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_item_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if isinstance(d.get("schedule_config"), str):
            try:
                d["schedule_config"] = json.loads(d["schedule_config"])
            except (json.JSONDecodeError, TypeError):
                d["schedule_config"] = {}
        if "enabled" in d:
            d["enabled"] = bool(d["enabled"])
        return d


# ═══════════════════════════════════════════════════════════════
# 用户持久化
# ═══════════════════════════════════════════════════════════════

_USER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


class UserStore:
    """用户 SQLite 存储，线程安全。"""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self, writable: bool = False) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            uri = "file::memory:?cache=shared"
        else:
            uri = self._db_path
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        if self._db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if writable:
            conn.execute("BEGIN IMMEDIATE")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript(_USER_SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    def create_user(self, username: str, password_hash: str, role: str = "user") -> dict:
        user_id = _new_id()
        now = utc_now_iso()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, role, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, password_hash, role, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"用户名已存在：{username}")
            finally:
                conn.close()
        return self.get_user_by_username(username)

    def get_user_by_username(self, username: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["enabled"] = bool(d.get("enabled", True))
            return d
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["enabled"] = bool(d.get("enabled", True))
            return d
        finally:
            conn.close()

    def list_users(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, username, role, enabled, created_at FROM users "
                "ORDER BY username"
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["enabled"] = bool(d.get("enabled", True))
                result.append(d)
            return result
        finally:
            conn.close()

    def update_user(self, user_id: str, **kwargs) -> dict | None:
        allowed = {"password_hash", "role", "enabled"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        if not updates:
            return self.get_user_by_id(user_id)
        with self._lock:
            conn = self._get_conn()
            try:
                sets = [f"{k} = ?" for k in updates]
                params = list(updates.values()) + [user_id]
                conn.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
            finally:
                conn.close()


# 模块级单例
_store: TaskStore | None = None
_watchlist_store: WatchlistStore | None = None
_user_store: UserStore | None = None


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


def get_watchlist_store() -> WatchlistStore:
    global _watchlist_store
    if _watchlist_store is None:
        _watchlist_store = WatchlistStore()
    return _watchlist_store


def get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
