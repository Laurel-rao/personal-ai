"""Run with: .venv/bin/python test_players_add.py

Covers the manual "添加选手" path: validation, persistence, duplicate check
and the HTTP endpoint. Uses a temporary data dir; never touches real library data.
"""
import json
import shutil
import tempfile
from pathlib import Path

import server

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
tmp = Path(tempfile.mkdtemp(prefix="players-add-test-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    (tmp / "dmm-actresses.json").write_text(json.dumps([
        {"id": "1114479", "name": "小谷アリサ", "nameRuby": "こたにありさ", "height": None,
         "bust": None, "waist": None, "hip": None,
         "imageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/mono/actjpgs/kotani_arisa.jpg"},
        {"id": "1083265", "name": "安位薫", "nameRuby": "やすいかおる", "height": "163",
         "bust": "92(H)", "waist": "62", "hip": "89",
         "imageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/mono/actjpgs/yasui_kaoru.jpg"},
    ], ensure_ascii=False), encoding="utf-8")

    item, error = server._am_add_player({
        "displayName": "小谷アリサ",
        "japaneseName": "小谷アリサ",
        "romanName": "Otani Arisa",
        "studio": "示例厂牌",
        "note": "手动添加",
    })
    assert error == "", error
    assert item["name"] == "小谷アリサ"
    assert item["studio"] == "示例厂牌"
    assert item["id"].startswith("user-")
    rows = json.loads(server._AM_USER_FILE.read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0]["card"]["id"] == item["id"]
    assert rows[0]["profile"]["note"] == "手动添加"

    _, duplicate = server._am_add_player({"displayName": "小谷アリサ", "romanName": "Otani Arisa"})
    assert "已有" in duplicate, duplicate
    _, same_person = server._am_add_player({"displayName": "Arisa Otani", "romanName": "Arisa Otani"})
    assert "已有" in same_person, same_person
    assert len(json.loads(server._AM_USER_FILE.read_text(encoding="utf-8"))) == 1

    assert server._am_add_player({"displayName": ""})[0] is None
    assert server._am_add_player({"displayName": "x" * 41})[0] is None

    second, error = server._am_add_player({"displayName": "测试选手二", "romanName": "Test Two"})
    assert error == "", error
    assert second["id"] != item["id"]
    assert len(server._am_load()["cards"]) == 2, "both manual players should be merged into the list"

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    found = client.get("/api/players/actresses", query_string={"q": "こたに"})
    payload = found.get_json()
    assert payload["success"] is True and payload["items"], payload
    first = payload["items"][0]
    assert first["name"] == "小谷アリサ", first
    assert first["roman"] == "Kotani Arisa", first
    assert first["in_library"] is True and first["existing_name"] == "小谷アリサ", first
    assert payload["total"] == 1, payload
    by_roman = client.get("/api/players/actresses", query_string={"q": "arisa kotani"}).get_json()
    assert by_roman["items"][0]["id"] == "1114479", by_roman
    assert client.get("/api/players/actresses", query_string={"q": ""}).get_json()["items"] == []

    created = client.post("/api/players/create", json={
        "displayName": "安位薫", "japaneseName": "安位薫", "romanName": "Yasui Kaoru",
        "dmmId": "1083265", "height": "163", "measurements": "B92(H)-W62-H89",
        "image": "https://awsimgsrc.dmm.co.jp/pics_dig/mono/actjpgs/yasui_kaoru.jpg",
    })
    assert created.status_code == 200, created.data
    payload = created.get_json()
    assert payload["success"] is True and payload["item"]["name"] == "安位薫"
    assert payload["item"]["dmm_id"] == "1083265", payload
    assert payload["item"]["height"] == "163" and payload["item"]["measurements"] == "B92(H)-W62-H89"
    rows = json.loads(server._AM_USER_FILE.read_text(encoding="utf-8"))
    saved = next(row for row in rows if row["card"]["id"] == payload["item"]["id"])
    assert saved["profile"]["dmmId"] == "1083265" and saved["profile"]["dmmImage"]

    duplicate_by_name = client.post("/api/players/create", json={"displayName": "安位薫"})
    assert duplicate_by_name.status_code == 400, duplicate_by_name.data
    assert "已有" in duplicate_by_name.get_json()["error"]

    rejected = client.post("/api/players/create", json={"displayName": ""})
    assert rejected.status_code == 400
    assert rejected.get_json()["success"] is False
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player creation checks passed")
