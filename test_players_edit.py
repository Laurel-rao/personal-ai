"""Run with: .venv/bin/python test_players_edit.py

Offline check for editing a manually added player's profile fields.
"""
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import server
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
tmp = Path(tempfile.mkdtemp(prefix="players-edit-test-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    (tmp / "dmm-actresses.json").write_text("[]", encoding="utf-8")

    item, error = server._am_add_player({
        "displayName": "编辑测试", "japaneseName": "編集テスト", "romanName": "Edit Test",
    })
    assert error == "", error
    assert item["custom"] is True

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()
    response = client.post("/api/players/update", json={
        "id": item["id"],
        "displayName": "编辑测试",
        "japaneseName": "編集テスト",
        "romanName": "Edit Test",
        "height": "163",
        "measurements": "B92(H)-W62-H89",
        "birthday": "1999-12-01",
        "agency": "示例事务所",
        "debut": "2019",
        "socialX": "https://x.com/example",
        "socialInstagram": "https://instagram.com/example",
        "note": "已补全",
    })
    assert response.status_code == 200, response.data
    updated = response.get_json()["item"]
    assert updated["height"] == "163" and updated["measurements"] == "B92(H)-W62-H89", updated
    today = datetime.now(timezone.utc)
    expected_age = today.year - 1999 - ((today.month, today.day) < (12, 1))
    assert updated["birthday"] == "1999-12-01" and updated["age"] == expected_age, updated
    assert updated["agency"] == "示例事务所" and updated["debut"] == "2019", updated
    assert updated["social"]["x"].endswith("/example"), updated

    rows = json.loads(server._AM_USER_FILE.read_text(encoding="utf-8"))
    assert rows[0]["profile"]["note"] == "已补全"
    assert rows[0]["profile"]["height"] == "163"

    missing = client.post("/api/players/update", json={"id": "nope", "displayName": "x"})
    assert missing.status_code == 400, missing.data
    assert client.post("/api/players/update", json={"id": item["id"], "displayName": ""}).status_code == 400
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player edit checks passed")
