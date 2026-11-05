"""Run with: .venv/bin/python test_players_download.py

Offline check for the per-player DMM download queue: enumeration/download are
mocked, so no network or real ~/Movies data is touched.
"""
import json
import shutil
import tempfile
import time
from pathlib import Path

import dmm_books
import server
import task_store
from flask import Flask

original_dir = server._AM_DIR
original_file = server._AM_USER_FILE
original_photo_dir = server._LOCAL_PHOTO_DIR
original_task_root = task_store._ROOT
original_list = dmm_books.list_books
original_search = dmm_books.search_books
original_download = dmm_books.download_book
tmp = Path(tempfile.mkdtemp(prefix="players-download-test-"))
try:
    server._AM_DIR = tmp
    server._AM_USER_FILE = tmp / "player-user.json"
    server._LOCAL_PHOTO_DIR = tmp / "写真"
    task_store.configure(tmp / "tasks")
    task_store.clear()
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={}, tags={}, comments={}, enrich={})
    server._DOWNLOAD_JOBS.clear()
    (tmp / "dmm-actresses.json").write_text(json.dumps([
        {"id": "1083265", "name": "安位薫", "nameRuby": "やすいかおる", "height": "163",
         "bust": "92(H)", "waist": "62", "hip": "89",
         "imageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/mono/actjpgs/yasui_kaoru.jpg"},
    ], ensure_ascii=False), encoding="utf-8")

    def fake_list(dmm_id, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(1, 1)
        return [{"series": "4166120", "code": "b092agwrk02411"}]

    def fake_search(name, max_pages=5, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(1, max_pages)
        return [{"series": "4166120", "code": "b092agwrk02412"}]

    dmm_books.list_books = fake_list
    dmm_books.search_books = fake_search

    def fake_download(series, code, outdir, on_page=None, should_stop=None):
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "page_001.jpg").write_bytes(b"fake-jpeg")
        if on_page is not None:
            on_page(1, 1)
        return 1

    dmm_books.download_book = fake_download

    item, error = server._am_add_player({
        "displayName": "安位薫", "japaneseName": "安位薫", "romanName": "Yasui Kaoru",
        "dmmId": "1083265",
    })
    assert error == "", error
    assert server._resolve_dmm_id("安位薫", "", "") == "1083265"
    assert server._resolve_dmm_id("完全不存在", "", "") == ""

    job, error = server._start_player_download(item["id"])
    assert error == "" and job and job["status"] == "running", (job, error)
    assert job.get("task_id"), job
    deadline = time.time() + 5
    while time.time() < deadline:
        job = server._download_job(item["id"])
        if job and job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["finished"] == 1 and job["pages"] == 1, job
    book = server._LOCAL_PHOTO_DIR / "安位薫" / "b092agwrk02411"
    assert (book / "page_001.jpg").is_file() and (book / ".done").is_file()
    assert not list((server._LOCAL_PHOTO_DIR / "安位薫").glob(".*.part"))

    app = Flask(__name__)
    app.register_blueprint(server.console_bp)
    client = app.test_client()
    manual = client.post("/api/players/download", json={"id": item["id"]})
    assert manual.status_code == 200, manual.data
    assert manual.get_json()["job"]["status"] in {"running", "done"}

    no_id, error = server._am_add_player({"displayName": "没有DMM资料的选手"})
    assert error == "", error
    rejected = client.post("/api/players/download", json={"id": no_id["id"]})
    assert rejected.status_code == 400, rejected.data
    assert "DMM" in rejected.get_json()["error"]

    search_item, error = server._am_add_player({"displayName": "搜索选手", "japaneseName": "検索用ダミー"})
    assert error == "", error
    assert not search_item["dmm_id"]
    job, error = server._start_player_download(search_item["id"])
    assert error == "" and job["status"] == "running", (job, error)
    deadline = time.time() + 5
    while time.time() < deadline:
        job = server._download_job(search_item["id"])
        if job and job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["finished"] == 1, job
    assert (server._LOCAL_PHOTO_DIR / "搜索选手" / "b092agwrk02412" / ".done").is_file()
    started_task = task_store.get(job["task_id"])
    assert started_task and started_task["status"] == "success", started_task

    created = client.post("/api/players/create", json={
        "displayName": "自动下载选手", "dmmId": "1083265", "autoDownload": True,
    })
    assert created.status_code == 200, created.data
    payload = created.get_json()
    assert payload["success"] is True and payload["item"]["dmm_id"] == "1083265", payload
    assert payload["download"]["status"] in {"running", "done"}, payload
    assert "download_error" not in payload
    deadline = time.time() + 5
    auto_job = server._download_job(payload["item"]["id"])
    while time.time() < deadline and auto_job and auto_job["status"] == "running":
        time.sleep(0.05)
        auto_job = server._download_job(payload["item"]["id"])
    assert auto_job["status"] == "done", auto_job

    cancel_item, error = server._am_add_player({"displayName": "取消测试", "dmmId": "1083265"})
    assert error == "", error

    def blocking_download(series, code, outdir, on_page=None, should_stop=None):
        deadline = time.time() + 3
        while time.time() < deadline:
            if should_stop is not None and should_stop():
                raise dmm_books.DownloadCancelled("已取消")
            time.sleep(0.05)
        raise RuntimeError("测试超时")

    dmm_books.download_book = blocking_download
    job, error = server._start_player_download(cancel_item["id"])
    assert error == "" and job["status"] == "running", (job, error)
    time.sleep(0.2)
    cancelled = client.post("/api/players/download/cancel", json={"id": cancel_item["id"]})
    assert cancelled.status_code == 200, cancelled.data
    deadline = time.time() + 5
    while time.time() < deadline:
        job = server._download_job(cancel_item["id"])
        if job and job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "cancelled", job
    assert task_store.get(job["task_id"])["status"] == "cancelled", task_store.get(job["task_id"])
finally:
    server._AM_DIR = original_dir
    server._AM_USER_FILE = original_file
    server._LOCAL_PHOTO_DIR = original_photo_dir
    task_store.configure(original_task_root)
    server._AM_STATE.update(mtime=0.0, cards=[], profiles={})
    server._DOWNLOAD_JOBS.clear()
    dmm_books.list_books = original_list
    dmm_books.search_books = original_search
    dmm_books.download_book = original_download
    shutil.rmtree(tmp, ignore_errors=True)

print("Player download checks passed")
