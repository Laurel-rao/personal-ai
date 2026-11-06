"""Run with: .venv/bin/python test_players_hide.py

Covers hiding players: default list excludes hidden, show_hidden includes and
flags them, detail exposes the flag, and unhide restores the default list.
"""
import shutil
import tempfile
from pathlib import Path

import server
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
tmp = Path(tempfile.mkdtemp(prefix="players-hide-test-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())

    first, error = server._am_add_player({"displayName": "隐藏甲", "romanName": "Hide One"})
    assert error == "", error
    second, error = server._am_add_player({"displayName": "隐藏乙", "romanName": "Hide Two"})
    assert error == "", error

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    before = client.get("/api/players/list").get_json()
    assert before["total"] == 2 and all(not item["hidden"] for item in before["items"]), before

    hidden = client.post("/api/players/hide", json={"id": first["id"], "hidden": True})
    assert hidden.status_code == 200 and hidden.get_json()["hidden"] is True, hidden.data

    default = client.get("/api/players/list").get_json()
    assert default["total"] == 1 and default["items"][0]["id"] == second["id"], default
    flagged = client.get("/api/players/list?show_hidden=1").get_json()
    assert flagged["total"] == 2, flagged
    hidden_item = next(item for item in flagged["items"] if item["id"] == first["id"])
    assert hidden_item["hidden"] is True, hidden_item
    detail = client.get(f"/api/players/detail?id={first['id']}").get_json()
    assert detail["item"]["hidden"] is True, detail

    shown = client.post("/api/players/hide", json={"id": first["id"], "hidden": False})
    assert shown.get_json()["hidden"] is False, shown.data
    restored = client.get("/api/players/list").get_json()
    assert restored["total"] == 2, restored
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player hide checks passed")
