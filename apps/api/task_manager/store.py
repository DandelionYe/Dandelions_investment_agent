"""SQLite 任务状态持久化层。

支持同步调用（Celery worker）和通过 run_in_executor 的异步调用（FastAPI）。
设计为可替换后端 —— 实现相同的 TaskStore 接口即可切换到 PostgreSQL。
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from apps.api.schemas.task import TaskStatus

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

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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

    def list_tasks(
        self,
        symbol: str | None = None,
        status: str | None = None,
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


# 模块级单例
_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store
