"""Run with: .venv/bin/python test_player_menu.py"""
from flask import Flask
from admin import MODULES, route_module

app = Flask(__name__)
player = next(item for item in MODULES if item[0] == "player")
assert player[1:3] == ("本地视频", "/player")
for path in ("/player", "/video_player.html", "/api/player/videos", "/api/player/video", "/api/player/cover"):
    with app.test_request_context(path):
        assert route_module() == "player", path
with app.test_request_context("/video"):
    assert route_module() == "video"
print("Player menu and route permission checks passed")
