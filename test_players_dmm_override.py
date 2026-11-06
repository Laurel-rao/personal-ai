"""Run with: .venv/bin/python test_players_dmm_override.py

The override layer lets imported (read-only) players correct their DMM id
without editing the merged source data.
"""
import json
import shutil
import tempfile
from pathlib import Path

import server
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
tmp = Path(tempfile.mkdtemp(prefix="players-dmm-override-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    (tmp / "players-merged.json").write_text(json.dumps([
        {"card": {"id": "rara-test", "displayName": "RARA", "name": "RARA", "variant": 1,
                  "stats": {"FAC": 80, "BDY": 81, "SKL": 82, "POP": 83, "CHA": 84, "PRF": 85}},
         "profile": {"displayName": "RARA", "name": "RARA"}},
    ], ensure_ascii=False), encoding="utf-8")
    (tmp / "dmm-actresses.json").write_text(json.dumps([
        {"id": "1086062", "name": "白石もも", "nameRuby": "しらいしもも",
         "imageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/mono/actjpgs/siraisi_momo3.jpg"},
    ], ensure_ascii=False), encoding="utf-8")

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    before = client.get("/api/players/detail?id=rara-test").get_json()["item"]
    assert not before.get("dmm_id"), before

    saved = client.post("/api/players/dmm-id", json={"id": "rara-test", "dmmId": "1086062"})
    assert saved.status_code == 200 and saved.get_json()["success"], saved.data
    item = saved.get_json()["item"]
    assert item["dmm_id"] == "1086062" and item["card_image"].endswith("siraisi_momo3.jpg"), item
    assert (tmp / "player-overrides.json").is_file()

    stats = client.post("/api/players/stats", json={"id": "rara-test", "stats": {"FAC": 99, "BDY": 101}})
    assert stats.status_code == 400, stats.data
    stats = client.post("/api/players/stats", json={"id": "rara-test", "stats": {"FAC": "99"}})
    assert stats.status_code == 200 and stats.get_json()["item"]["stats"]["FAC"] == 99, stats.data
    assert client.get("/api/players/detail?id=rara-test").get_json()["item"]["stats"]["FAC"] == 99

    cleared = client.post("/api/players/dmm-id", json={"id": "rara-test", "dmmId": ""})
    assert cleared.get_json()["item"].get("dmm_id") in (None, ""), cleared.data
    assert client.post("/api/players/dmm-id", json={"id": "rara-test", "dmmId": "abc"}).status_code == 400
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player DMM override checks passed")
