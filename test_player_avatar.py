"""Run with: .venv/bin/python test_player_avatar.py"""
import io
import shutil
import tempfile
from pathlib import Path

from PIL import Image

import server

original_dir = server._PLAYER_AVATAR_DIR
original_meta = server._PLAYER_AVATAR_META
original_fetch = server._nya_fetch
tmp = Path(tempfile.mkdtemp(prefix="player-avatar-"))
try:
    server._PLAYER_AVATAR_DIR = tmp / "avatars"
    server._PLAYER_AVATAR_META = tmp / "avatar-meta.json"
    image = Image.new("RGB", (480, 600), (220, 210, 200))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    image_bytes = buffer.getvalue()
    page = '<img src="https://image.yingzhiben.info/avatar/TestAvatar.jpg">'

    def fake_fetch(url, timeout=30):
        if "theidolbase.com/actress/" in url:
            return page.encode()
        return image_bytes

    server._nya_fetch = fake_fetch
    card = {"id": "test-avatar", "name": "Siraisi Momo", "displayName": "白石もも"}
    profile = {"name": "Siraisi Momo", "displayName": "白石もも", "aliases": []}
    result = server._ensure_player_avatar(card, profile)
    assert result and result["width"] == 480 and result["height"] == 600, result
    assert server._avatar_path("test-avatar").is_file()
    assert server._avatar_url("test-avatar").startswith("/api/players/avatar/test-avatar?v=")
    cached = server._ensure_player_avatar(card, profile)
    assert cached and cached.get("cached") is True, cached
finally:
    server._PLAYER_AVATAR_DIR = original_dir
    server._PLAYER_AVATAR_META = original_meta
    server._nya_fetch = original_fetch
    shutil.rmtree(tmp, ignore_errors=True)

print("Player avatar checks passed")
