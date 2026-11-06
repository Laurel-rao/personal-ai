"""Run with: .venv/bin/python test_players_photo_delete.py

Checks local photo listing includes deletable relative files and the delete
endpoint only removes page/spread images inside the player folder.
"""
import shutil
import tempfile
from pathlib import Path

import server
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
original_photos = server._LOCAL_PHOTO_DIR
tmp = Path(tempfile.mkdtemp(prefix="players-photo-delete-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._LOCAL_PHOTO_DIR = tmp / "写真"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())
    player, error = server._am_add_player({"displayName": "删除测试", "romanName": "Delete Test"})
    assert error == "", error

    book = server._LOCAL_PHOTO_DIR / "删除测试" / "book1"
    book.mkdir(parents=True)
    (book / "page_001.jpg").write_bytes(b"one")
    (book / "page_002.jpg").write_bytes(b"two")
    (book / ".done").write_text("1")
    spread_book = server._LOCAL_PHOTO_DIR / "删除测试" / "book2"
    (spread_book / "spreads").mkdir(parents=True)
    (spread_book / "spreads" / "spread_001.jpg").write_bytes(b"spread")
    (spread_book / "page_001.jpg").write_bytes(b"page")

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    listed = client.get(f"/api/players/photos?id={player['id']}&kind=local").get_json()
    assert listed["source"] == "local" and len(listed["photos"]) == 3, listed
    assert len(listed["files"]) == 3 and listed["files"][0].startswith("book"), listed
    assert any(path.endswith("page_001.jpg") for path in listed["files"]), listed

    first = next(path for path in listed["files"] if path.endswith("page_001.jpg"))
    deleted = client.post("/api/players/photos/delete",
                          json={"id": player["id"], "paths": [first, "book1/.done", "../player-user.json"]})
    assert deleted.status_code == 200 and deleted.get_json()["deleted"] == 1, deleted.data
    assert not (book / "page_001.jpg").exists() and (book / "page_002.jpg").exists()
    assert (book / ".done").exists()

    remaining = client.get(f"/api/players/photos?id={player['id']}&kind=local").get_json()
    assert remaining["photos"], remaining
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._LOCAL_PHOTO_DIR = original_photos
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player photo delete checks passed")
