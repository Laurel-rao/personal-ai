"""Run with: .venv/bin/python test_tasks.py

Offline checks for the persistent external-task store and list/detail API.
"""
import json
import shutil
import tempfile
from pathlib import Path

import server
import task_store
from flask import Flask

original_root = task_store._ROOT
tmp = Path(tempfile.mkdtemp(prefix="tasks-test-"))
try:
    task_store.configure(tmp / "tasks")
    task_store.clear()
    task = task_store.create("photos", "写真：测试", payload={"player_id": "p1"},
                             player_id="p1", player_name="测试")
    assert task["status"] == "running" and task["id"]
    task_store.log(task["id"], "第一步")
    task_store.update(task["id"], progress=0.5, result={"count": 2})
    task_store.finish(task["id"], "success", {"count": 2, "photos": ["/a.jpg"]})
    saved = task_store.get(task["id"])
    assert saved["status"] == "success" and saved["progress"] == 0.5, saved
    assert "第一步" in saved["logs"] and "完成" in saved["logs"], saved["logs"]

    running = task_store.create("works", "运行中的任务")
    assert task_store.interrupt_running() >= 1
    assert task_store.get(running["id"])["status"] == "failed"

    cancel_target = task_store.create("preview", "取消测试")
    task_store.cancel(cancel_target["id"])
    task_store.finish(cancel_target["id"], "success", {"count": 9})
    assert task_store.get(cancel_target["id"])["status"] == "cancelled"
    assert task_store.get(cancel_target["id"])["result"] == {}

    items, total = task_store.list_tasks(kind="photos", status="success", player_id="p1")
    assert total == 1 and items[0]["id"] == task["id"], (items, total)
    assert task_store.list_tasks(kind="download")[1] == 0

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()
    listed = client.get("/api/tasks").get_json()
    assert listed["success"] is True and listed["total"] >= 1, listed
    detail = client.get(f"/api/tasks/{task['id']}").get_json()
    assert detail["success"] is True and detail["task"]["logs"], detail
    assert client.get("/api/tasks/nope").status_code == 404

    local_task = task_store.create("photos", "本地写真", payload={"kind": "local"})
    still_task = task_store.create("photos", "剧照", payload={"kind": "stills"})
    assert task_store.delete_local_photo_tasks() == 1
    assert task_store.get(local_task["id"]) is None
    assert task_store.get(still_task["id"]) is not None
finally:
    task_store.configure(original_root)
    shutil.rmtree(tmp, ignore_errors=True)

print("Task store checks passed")
