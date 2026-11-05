"""Persistent task store for external data queries.

Tasks live in data/amxiaolin/tasks.json; per-task logs are appended to
data/amxiaolin/task-logs/<id>.log.  No database, no extra dependency.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parent / "data" / "amxiaolin"
_ROOT = _DEFAULT_ROOT
_LOCK = threading.RLock()
_MAX_TASKS = 300
_MAX_LOG_BYTES = 200_000


def configure(root: Path) -> None:
    global _ROOT
    _ROOT = Path(root)
    (_ROOT / "task-logs").mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _tasks_file() -> Path:
    return _ROOT / "tasks.json"


def _log_file(task_id: str) -> Path:
    return _ROOT / "task-logs" / f"{task_id}.log"


def _load() -> list[dict]:
    try:
        data = json.loads(_tasks_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(tasks: list[dict]) -> None:
    if len(tasks) > _MAX_TASKS:
        for old in tasks[:-_MAX_TASKS]:
            try:
                _log_file(str(old.get("id"))).unlink(missing_ok=True)
            except OSError:
                pass
        tasks = tasks[-_MAX_TASKS:]
    _ROOT.mkdir(parents=True, exist_ok=True)
    temporary = _tasks_file().with_suffix(".tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(_tasks_file())


def _append_log(task_id: str, message: str) -> None:
    path = _log_file(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
            tail = path.read_text(encoding="utf-8", errors="ignore")[-_MAX_LOG_BYTES // 2:]
            path.write_text("…（较早日志已截断）\n" + tail, encoding="utf-8")
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as output:
        output.write(f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")


def log(task_id: str, message: str) -> None:
    if not task_id:
        return
    with _LOCK:
        _append_log(task_id, str(message))


def create(kind: str, title: str, payload: dict | None = None, player_id: str = "",
           player_name: str = "", retry_of: str = "") -> dict:
    with _LOCK:
        tasks = _load()
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
        tasks.append(task)
        _save(tasks)
        _append_log(task["id"], f"开始：{title}")
        return dict(task)


def update(task_id: str, **fields) -> dict | None:
    with _LOCK:
        tasks = _load()
        for task in tasks:
            if task.get("id") == task_id:
                task.update(fields)
                _save(tasks)
                return dict(task)
    return None


def finish(task_id: str, status: str, result: dict | None = None, error: str = "",
           progress: float | None = None) -> dict | None:
    if not task_id:
        return None
    values = {
        "status": status,
        "finished_at": _now(),
        "result": result or {},
        "error": str(error)[:500],
    }
    if progress is not None:
        values["progress"] = progress
    task = update(task_id, **values)
    if status == "success":
        log(task_id, f"完成：{result or ''}")
    else:
        log(task_id, f"失败：{error or '未知错误'}")
    return task


def get(task_id: str, with_logs: bool = True) -> dict | None:
    with _LOCK:
        task = next((item for item in _load() if item.get("id") == task_id), None)
        if task is None:
            return None
        snapshot = dict(task)
    if with_logs:
        try:
            snapshot["logs"] = _log_file(task_id).read_text(encoding="utf-8", errors="ignore")[-_MAX_LOG_BYTES:]
        except OSError:
            snapshot["logs"] = ""
    return snapshot


def list_tasks(kind: str = "", status: str = "", player_id: str = "",
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    with _LOCK:
        tasks = list(reversed(_load()))
    if kind:
        tasks = [item for item in tasks if item.get("kind") == kind]
    if status:
        tasks = [item for item in tasks if item.get("status") == status]
    if player_id:
        tasks = [item for item in tasks if item.get("player_id") == player_id]
    total = len(tasks)
    return tasks[offset:offset + max(1, min(limit, 200))], total


def interrupt_running(message: str = "服务重启，任务已中断") -> int:
    """Mark tasks left running by a previous process as failed."""
    with _LOCK:
        tasks = _load()
        changed = 0
        for task in tasks:
            if task.get("status") == "running":
                task.update(status="failed", error=message, finished_at=_now())
                _append_log(str(task.get("id")), f"失败：{message}")
                changed += 1
        if changed:
            _save(tasks)
        return changed


def clear() -> None:
    """Only used by tests."""
    with _LOCK:
        _save([])
        for path in (_ROOT / "task-logs").glob("*.log"):
            path.unlink(missing_ok=True)
