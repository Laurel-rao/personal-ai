"""Run with: .venv/bin/python test_players_videos.py

Checks local video matching: a player's card gets a video_count and the detail
endpoint returns the matching video list. Uses temp data/movies dirs.
"""
import shutil
import tempfile
from pathlib import Path

import server
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
original_movies = server.MOVIES_DIR
tmp = Path(tempfile.mkdtemp(prefix="players-video-test-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())
    movies = tmp / "movies"
    movies.mkdir()
    (movies / "ABC-123-视频测试.mp4").write_bytes(b"not-a-real-video")
    (movies / "XYZ-999-其他人.mp4").write_bytes(b"other")
    server.MOVIES_DIR = movies
    server._VIDEO_CACHE.update(at=0.0, items=[], warning="")

    player, error = server._am_add_player({"displayName": "视频测试", "romanName": "Video Test"})
    assert error == "", error

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()

    listed = client.get("/api/players/list?q=视频测试").get_json()
    assert listed["total"] == 1, listed
    assert listed["items"][0]["video_count"] == 1, listed["items"][0]

    detail = client.get(f"/api/players/detail?id={player['id']}").get_json()
    assert detail["item"]["video_count"] == 1, detail["item"]
    assert len(detail["videos"]) == 1 and detail["videos"][0]["id"].endswith("ABC-123-视频测试.mp4"), detail
    assert detail["videos"][0]["thumb_url"].startswith("/api/player/thumb?path="), detail["videos"][0]

    other = client.get("/api/players/list?q=其他").get_json()
    assert other["total"] == 0, other
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server.MOVIES_DIR = original_movies
    server._VIDEO_CACHE.update(at=0.0, items=[], warning="")
    server._HIDDEN_STATE.update(path="", stamp=None, ids=set())
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    shutil.rmtree(tmp, ignore_errors=True)

print("Player video checks passed")
