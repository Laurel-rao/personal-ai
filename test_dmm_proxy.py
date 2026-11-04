"""Run with: .venv/bin/python test_dmm_proxy.py

Offline checks for proxy normalization and the settings endpoints; network
probing and .env writes are avoided.
"""
import os

import dmm_books
import server
from flask import Flask

assert dmm_books.normalize_proxy("127.0.0.1:7898") == "http://127.0.0.1:7898"
assert dmm_books.normalize_proxy("http://127.0.0.1:7898") == "http://127.0.0.1:7898"
assert dmm_books.normalize_proxy("") == ""
for bad in ("ftp://127.0.0.1:7898", "http://127.0.0.1:7898/path", "http://"):
    try:
        dmm_books.normalize_proxy(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"expected invalid proxy: {bad}")

original_env = os.environ.get("DMM_PROXY")
original_save = server.save_env_values
saved: dict[str, str] = {}


def fake_save(updates, path=None):
    saved.update(updates)
    return updates


server.save_env_values = fake_save
app = Flask(__name__)
app.register_blueprint(server.console_bp)
client = app.test_client()
try:
    initial = server.effective_setting("DMM_PROXY", "")
    current = client.get("/api/settings/dmm-proxy").get_json()
    assert current["success"] is True, current
    assert current["candidates"], current
    assert current["proxy"] == initial, current

    os.environ["DMM_PROXY"] = "http://127.0.0.1:7898"
    current = client.get("/api/settings/dmm-proxy").get_json()
    assert current["proxy"] == "http://127.0.0.1:7898", current
    assert current["candidates"][0] == "http://127.0.0.1:7898", current

    updated = client.post("/api/settings/dmm-proxy", json={"proxy": "127.0.0.1:7899"})
    assert updated.status_code == 200, updated.data
    body = updated.get_json()
    assert body["proxy"] == "http://127.0.0.1:7899", body
    assert saved["DMM_PROXY"] == "http://127.0.0.1:7899", saved
    assert os.environ["DMM_PROXY"] == "http://127.0.0.1:7899"

    settings = client.get("/api/settings").get_json()
    assert settings["dmm_proxy"] == "http://127.0.0.1:7899", settings
    assert "http://127.0.0.1:7899" in settings["dmm_proxy_candidates"], settings

    rejected = client.post("/api/settings/dmm-proxy", json={"proxy": "ftp://127.0.0.1:1"})
    assert rejected.status_code == 400, rejected.data
finally:
    server.save_env_values = original_save
    if original_env is None:
        os.environ.pop("DMM_PROXY", None)
    else:
        os.environ["DMM_PROXY"] = original_env

print("DMM proxy checks passed")
