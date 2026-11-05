"""SQLite-backed persistent task store for external data queries.

Tasks and per-task logs live in data/amxiaolin/tasks.db.  The public API is
unchanged from the earlier JSON store; an old tasks.json is imported once.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parent / "data" / "amxiaolin"
_ROOT = _DEFAULT_ROOT
_DB: Path = _DEFAULT_ROOT / "tasks.db"
_CONN: sqlite3.Connection | None = None
_LOCK = threading.RLock()
_MAX_TASKS = 300
_MAX_LOG_ROWS = 1000


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            player_id TEXT NOT NULL DEFAULT '',
            player_name TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'running',
            progress REAL NOT NULL DEFAULT 0,
            result TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            retry_of TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_kind ON tasks(kind);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id, id);
    """)
    connection.commit()
    return connection


def configure(root: Path) -> None:
    global _ROOT, _DB, _CONN
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except sqlite3.Error:
                pass
        _ROOT = Path(root)
        _DB = _ROOT / "tasks.db"
        _CONN = _connect(_DB)
        _migrate_json()


def _connection() -> sqlite3.Connection:
    if _CONN is None:
        configure(_ROOT)
    assert _CONN is not None
    return _CONN


def _migrate_json() -> None:
    """Import the previous tasks.json/log files once, then leave them aside."""
    source = _ROOT / "tasks.json"
    if not source.is_file():
        return
    connection = _connection()
    count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if count:
        return
    try:
        rows = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            connection.execute(
                "INSERT OR IGNORE INTO tasks (id, kind, title, player_id, player_name, payload,"
                " status, progress, result, error, created_at, started_at, finished_at, retry_of)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(item.get("id")), str(item.get("kind") or ""), str(item.get("title") or ""),
                 str(item.get("player_id") or ""), str(item.get("player_name") or ""),
                 json.dumps(item.get("payload") or {}, ensure_ascii=False),
                 str(item.get("status") or "running"), float(item.get("progress") or 0),
                 json.dumps(item.get("result") or {}, ensure_ascii=False),
                 str(item.get("error") or ""), str(item.get("created_at") or _now()),
                 str(item.get("started_at") or _now()), str(item.get("finished_at") or ""),
                 str(item.get("retry_of") or "")))
            log_path = _ROOT / "task-logs" / f"{item['id']}.log"
            try:
                for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip():
                        connection.execute(
                            "INSERT INTO task_logs (task_id, created_at, message) VALUES (?,?,?)",
                            (str(item["id"]), _now(), line.strip()))
            except OSError:
                pass
    connection.commit()
    try:
        source.rename(source.with_suffix(".json.migrated"))
    except OSError:
        pass


def _task(row: sqlite3.Row) -> dict:
    item = dict(row)
    for key in ("payload", "result"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except (TypeError, ValueError):
            item[key] = {}
    return item


def _trim(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM tasks WHERE id NOT IN (SELECT id FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (_MAX_TASKS,))
    connection.execute("DELETE FROM task_logs WHERE task_id NOT IN (SELECT id FROM tasks)")


def _insert_log(connection: sqlite3.Connection, task_id: str, message: str) -> None:
    if not task_id:
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    connection.execute("INSERT INTO task_logs (task_id, created_at, message) VALUES (?,?,?)",
                       (task_id, _now(), f"[{stamp}] {message}"))


def create(kind: str, title: str, payload: dict | None = None, player_id: str = "",
           player_name: str = "", retry_of: str = "") -> dict:
    with _LOCK:
        connection = _connection()
        task = {
            "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
            "kind": str(kind),
            "title": str(title),
            "player_id": str(player_id or ""),
            "player_name": str(player_name or ""),
            "payload": payload or {},
            "status": "running",
            "progress": 0,
            "result": {},
            "error": "",
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": "",
            "retry_of": str(retry_of or ""),
        }
        with connection:
            connection.execute(
                "INSERT INTO tasks (id, kind, title, player_id, player_name, payload, status,"
                " progress, result, error, created_at, started_at, finished_at, retry_of)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task["id"], task["kind"], task["title"], task["player_id"], task["player_name"],
                 json.dumps(task["payload"], ensure_ascii=False), task["status"], 0,
                 "{}", "", task["created_at"], task["started_at"], "", task["retry_of"]))
            _trim(connection)
            _insert_log(connection, task["id"], f"开始：{task['title']}")
        return dict(task)


def log(task_id: str, message: str) -> None:
    if not task_id:
        return
    with _LOCK:
        connection = _connection()
        with connection:
            _insert_log(connection, task_id, str(message))


def update(task_id: str, **fields) -> dict | None:
    allowed = {"kind", "title", "status", "progress", "result", "error", "finished_at",
               "started_at", "player_id", "player_name", "payload", "retry_of"}
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return get(task_id)
    encoded = {}
    for key, value in values.items():
        encoded[key] = json.dumps(value, ensure_ascii=False) if key in {"result", "payload"} else value
    with _LOCK:
        connection = _connection()
        assignments = ", ".join(f"{key} = ?" for key in encoded)
        with connection:
            connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ?",
                               (*encoded.values(), task_id))
        return get(task_id)


def finish(task_id: str, status: str, result: dict | None = None, error: str = "",
           progress: float | None = None) -> dict | None:
    if not task_id:
        return None
    current = get(task_id)
    if current and current.get("status") == "cancelled" and status != "cancelled":
        log(task_id, "任务已取消，忽略完成")
        return current
    values: dict = {"status": status, "finished_at": _now(), "result": result or {},
                    "error": str(error)[:500]}
    if progress is not None:
        values["progress"] = progress
    task = update(task_id, **values)
    log(task_id, f"完成：{result or ''}" if status == "success" else f"失败：{error or '未知错误'}")
    return task


def cancel(task_id: str, message: str = "用户取消") -> dict | None:
    if not task_id:
        return None
    task = update(task_id, status="cancelled", finished_at=_now(), error=message)
    if task is not None:
        log(task_id, f"已取消：{message}")
    return task


def get(task_id: str, with_logs: bool = True) -> dict | None:
    with _LOCK:
        connection = _connection()
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        task = _task(row)
        if with_logs:
            logs = connection.execute(
                "SELECT message FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, _MAX_LOG_ROWS)).fetchall()
            task["logs"] = "\n".join(item["message"] for item in reversed(logs))
    return task


def list_tasks(kind: str = "", status: str = "", player_id: str = "", q: str = "",
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    clauses = []
    values: list = []
    if q:
        clauses.append("(title LIKE ? OR player_name LIKE ? OR id LIKE ?)")
        like = f"%{q}%"
        values.extend([like, like, like])
    if kind:
        clauses.append("kind = ?")
        values.append(kind)
    if status:
        clauses.append("status = ?")
        values.append(status)
    if player_id:
        clauses.append("player_id = ?")
        values.append(player_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with _LOCK:
        connection = _connection()
        total = connection.execute(f"SELECT COUNT(*) FROM tasks{where}", values).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM tasks{where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (*values, limit, offset)).fetchall()
        items = [_task(row) for row in rows]
    return items, total


def interrupt_running(message: str = "服务重启，任务已中断") -> int:
    """Mark tasks left running by a previous process as failed."""
    with _LOCK:
        connection = _connection()
        rows = connection.execute("SELECT id FROM tasks WHERE status = 'running'").fetchall()
        with connection:
            for row in rows:
                connection.execute(
                    "UPDATE tasks SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                    (message, _now(), row["id"]))
                _insert_log(connection, row["id"], f"失败：{message}")
        return len(rows)


def delete_local_photo_tasks() -> int:
    """Local photo reads are not external tasks; drop old rows from the task list."""
    with _LOCK:
        connection = _connection()
        rows = connection.execute("SELECT id, payload FROM tasks WHERE kind = 'photos'").fetchall()
        stale = []
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except (TypeError, ValueError):
                continue
            if payload.get("kind") == "local":
                stale.append(row["id"])
        with connection:
            for task_id in stale:
                connection.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
                connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return len(stale)


def delete_finished() -> int:
    """Delete all non-running tasks; used by the task center bulk cleanup."""
    with _LOCK:
        connection = _connection()
        with connection:
            cursor = connection.execute("DELETE FROM tasks WHERE status != 'running'")
            connection.execute("DELETE FROM task_logs WHERE task_id NOT IN (SELECT id FROM tasks)")
            return cursor.rowcount


def clear() -> None:
    """Only used by tests."""
    with _LOCK:
        connection = _connection()
        with connection:
            connection.execute("DELETE FROM task_logs")
            connection.execute("DELETE FROM tasks")
