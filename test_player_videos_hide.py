"""Run with: .venv/bin/python test_player_videos_hide.py"""
import shutil
import tempfile
from pathlib import Path

import server
from flask import Flask

original_movies = server.MOVIES_DIR
tmp = Path(tempfile.mkdtemp(prefix="player-videos-hide-"))
try:
    (tmp / "a.mp4").write_bytes(b"a")
    (tmp / "b.mp4").write_bytes(b"b")
    server.MOVIES_DIR = tmp.resolve()
    server._VIDEO_CACHE.update(at=0.0, items=[], warning="")
    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    listed = client.get("/api/player/videos").get_json()
    assert len(listed["items"]) == 2, listed
    first = listed["items"][0]["id"]
    hidden = client.post("/api/player/videos/hide", json={"id": first, "hidden": True})
    assert hidden.status_code == 200 and hidden.get_json()["hidden"] is True, hidden.data
    default = client.get("/api/player/videos").get_json()
    assert len(default["items"]) == 1, default
    shown = client.get("/api/player/videos?show_hidden=1").get_json()
    assert len(shown["items"]) == 2 and any(item["hidden"] for item in shown["items"]), shown

    deleted = client.post("/api/player/videos/delete", json={"id": first})
    assert deleted.status_code == 200 and deleted.get_json()["success"], deleted.data
    assert not (tmp / Path(first).name).exists()
    remaining = client.get("/api/player/videos?show_hidden=1").get_json()
    assert len(remaining["items"]) == 1, remaining
finally:
    server.MOVIES_DIR = original_movies
    server._VIDEO_CACHE.update(at=0.0, items=[], warning="")
    shutil.rmtree(tmp, ignore_errors=True)

print("Player video hide checks passed")
