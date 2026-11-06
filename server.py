#!/usr/bin/env python3
"""H3 视频工作台 —— Flask 版。

在统一入口 app.py 中以蓝图 (console_bp) 注册；
也可独立运行：python3 server.py --host 127.0.0.1 --port 4173
"""

from __future__ import annotations

import argparse
import base64
import io
import itertools
import json
import mimetypes
import os
import re
import hashlib
import shutil
import socket
import ssl
import subprocess
import threading
import time
import unicodedata
import concurrent.futures as futures
import html as html_lib
import urllib.error
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dmm_books
import profile_enrich
import task_store

from flask import Blueprint, Flask, Response, jsonify, render_template_string, request, send_file, stream_with_context
from flask_login import current_user
from admin import is_admin
from media_catalog import approved_cover, catalog_summary, item_metadata, read_records
from media_startup import startup_bp


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
HISTORY_LOCK = threading.RLock()
STATIC_FILES = {
    "/video": ROOT / "index.html",
    "/index.html": ROOT / "index.html",
    "/chat": ROOT / "chat.html",
    "/chat.html": ROOT / "chat.html",
    "/image": ROOT / "image.html",
    "/image.html": ROOT / "image.html",
    "/styles.css": ROOT / "styles.css",
    "/app.js": ROOT / "app.js",
    "/chat-simple.css": ROOT / "chat-simple.css",
    "/chat.js": ROOT / "chat.js",
    "/settings": ROOT / "settings.html",
    "/settings.html": ROOT / "settings.html",
    "/settings.js": ROOT / "settings.js",
    "/image.css": ROOT / "image.css",
    "/ui-framework.css": ROOT / "ui-framework.css",
    "/admin.css": ROOT / "admin.css",
    "/workspace-pages.css": ROOT / "workspace-pages.css",
    "/ui-framework.js": ROOT / "ui-framework.js",
    "/player": ROOT / "video_player.html",
    "/video_player.html": ROOT / "video_player.html",
    "/nya": ROOT / "nya.html",
    "/nya.html": ROOT / "nya.html",
    "/players": ROOT / "players.html",
    "/players.html": ROOT / "players.html",
    "/tasks": ROOT / "tasks.html",
    "/tasks.html": ROOT / "tasks.html",
    "/tasks.js": ROOT / "tasks.js",
    "/tasks.css": ROOT / "tasks.css",
    "/video_player.css": ROOT / "video_player.css",
    "/video_player.js": ROOT / "video_player.js",
    "/templates/warring-states-ref2va.txt": ROOT / "templates" / "warring-states-ref2va.txt",
    "/templates/warring-states-ref2va-15.txt": ROOT / "templates" / "warring-states-ref2va-15.txt",
    "/templates/warring-states-01-meeting-chase-ref2va.txt": ROOT / "templates" / "warring-states-01-meeting-chase-ref2va.txt",
    "/templates/warring-states-02-command-transition-ref2va.txt": ROOT / "templates" / "warring-states-02-command-transition-ref2va.txt",
}
MOVIES_DIR = Path(os.environ.get("MOVIES_DIR", str(Path.home() / "Movies"))).expanduser().resolve()
PLAYER_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"}
REMOTE_TIMEOUT_SECONDS = 30
AUTODL_HOSTS = {"autodl.art", "www.autodl.art"}
AUTODL_WORKFLOW = "minimax_h3_lightx2v_v5_15s"
ZERO_IMAGE_BASE_URL = "https://ai.reeko.net.cn/v1"
QWEN_API_URL = os.environ.get(
    "QWEN_API_URL",
    "https://uu288331-78852a40cf8c.westd.seetacloud.com:8443/v1",
).rstrip("/")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.8-27b-uncensored")

# 番号搜索 / 迅雷下载（sukebei 资源站，经本机代理访问）
NYAA_PROXY = os.environ.get("NYAA_PROXY", "http://127.0.0.1:7897")
NYAA_BASE = os.environ.get("NYAA_BASE", "https://sukebei.nyaa.si").rstrip("/")
NYAA_DIR = Path(os.environ.get("NYAA_DIR", str(Path.home() / "Movies" / "Videos"))).expanduser()
THUNDER_APP = os.environ.get("THUNDER_APP", "Thunder")
JAVDB_BASE = os.environ.get("JAVDB_BASE", "https://javdb.com").rstrip("/")
NYAA_COVER_DIR = DATA_DIR / "nya-covers"
_NYA_COVER_CACHE: dict[str, bytes] = {}
_NYA_COVER_LOCK = threading.Lock()

IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "根据用户描述生成一张图片。只有用户明确要求画图、生成图片、出图时才调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "详细的图片描述，包含主体、风格、构图和光线"},
                "size": {"type": "string", "enum": ["1024x1024", "1024x1536", "1536x1024"]},
                "quality": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}
PHOTO_LAB_URL = os.environ.get("PHOTO_LAB_URL", "http://127.0.0.1:4174").rstrip("/")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def user_history_file() -> Path:
    if is_admin():
        return HISTORY_FILE
    return DATA_DIR / "users" / str(current_user.id) / "history.json"


def load_history() -> list[dict[str, Any]]:
    history_file = user_history_file()
    if not history_file.exists():
        return []
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def write_history(items: list[dict[str, Any]]) -> None:
    with HISTORY_LOCK:
        history_file = user_history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = history_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(items[:200], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, history_file)


def upsert_history(item: dict[str, Any]) -> dict[str, Any]:
    with HISTORY_LOCK:
        return _upsert_history(item)


def _upsert_history(item: dict[str, Any]) -> dict[str, Any]:
    items = load_history()
    key = str(item.get("promptId") or item.get("id") or "").strip()
    if not key:
        raise ValueError("History item requires promptId or id")
    current = next(
        (entry for entry in items if str(entry.get("promptId") or entry.get("id")) == key),
        {},
    )
    merged = {**current, **item, "id": key, "updatedAt": item.get("updatedAt") or utc_now()}
    items = [entry for entry in items if str(entry.get("promptId") or entry.get("id")) != key]
    items.insert(0, merged)
    write_history(items)
    return merged


def validate_base_url(value: Any) -> str:
    base_url = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("服务地址必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("服务地址不能包含账号或密码")
    if not is_admin():
        allowed_urls = {"https://www.autodl.art", "https://autodl.art"}
        allowed_urls.update(url.strip().rstrip("/") for url in os.getenv("PERSONAL_AI_WORKFLOW_BASE_URLS", "").split(",") if url.strip())
        if base_url not in allowed_urls:
            raise ValueError("此服务地址未获管理员授权")
    return base_url


def is_autodl_url(base_url: str) -> bool:
    return urllib.parse.urlparse(base_url).hostname in AUTODL_HOSTS


def env_token(name: str) -> str:
    return os.environ.get(name, "").strip()


# ---------------------------------------------------------------- 设置存取（.env）

ENV_FILE = ROOT / ".env"


def _public_proxy(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlparse(text if "://" in text else "http://" + text)
        if parsed.username:
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{parsed.username}:***@{host}{port}"
    except ValueError:
        pass
    return text


def _ensure_dmm_proxy() -> None:
    """If DMM_PROXY points at the local 7898 listener and it is down, start it."""
    proxy = os.environ.get("DMM_PROXY", "").strip()
    if not proxy:
        return
    try:
        parsed = urllib.parse.urlparse(proxy if "://" in proxy else "http://" + proxy)
        host = parsed.hostname or ""
        port = parsed.port or 80
    except ValueError:
        return
    if host not in {"127.0.0.1", "localhost"} or port != 7898:
        return
    try:
        with socket.create_connection((host, port), timeout=1):
            return
    except OSError:
        pass
    script = ROOT / "tools" / "dmm_jp_proxy.sh"
    if not script.is_file():
        return
    try:
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
        print(f"[dmm-proxy] start: {result.stdout.strip() or result.stderr.strip()}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[dmm-proxy] start failed: {exc}", flush=True)


DEFAULT_COMFY_URL = "https://u288331-788499bf7eab.bjb1.seetacloud.com:8443"


def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse a .env file into a dict (comments and blank lines dropped)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def save_env_values(updates: dict[str, str], path: Path = ENV_FILE) -> dict[str, str]:
    """Merge updates into .env (existing keys preserved) and chmod 600."""
    current = load_env_file(path)
    current.update(updates)
    text = "".join(f"{key}={value}\n" for key, value in sorted(current.items()))
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return current


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}••••{value[-4:]}"


def effective_setting(name: str, default: str = "") -> str:
    """Live value: process environment first, then .env file, then default."""
    value = os.environ.get(name, "").strip() or load_env_file().get(name, "").strip()
    return value or default


def request_remote(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = REMOTE_TIMEOUT_SECONDS,
) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", "application/json")


def decode_json(payload: bytes) -> Any:
    if not payload:
        return {}
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"message": payload.decode("utf-8", errors="replace")}


class UpstreamError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def derive_status(result: Any) -> str:
    if not isinstance(result, dict):
        return "pending"
    if result.get("success") is False or result.get("error"):
        return "error"
    nested = result.get("data") if isinstance(result.get("data"), dict) else {}
    status = str(result.get("status") or nested.get("status") or "").lower()
    if status in {"error", "failed", "failure"}:
        return "error"
    if result.get("pending") is True or status in {"pending", "running", "queued", "processing"}:
        return "pending"
    if result.get("pending") is False or status in {"completed", "complete", "success", "succeeded"}:
        return "completed"
    if result.get("results") or nested.get("results"):
        return "completed"
    return "pending"


MEDIA_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".png", ".jpg", ".jpeg", ".webp", ".gif")
MEDIA_KEYS = {"url", "video_url", "image_url", "download_url", "file_url", "src"}
TRUSTED_MEDIA_HOST_SUFFIXES = (".cos.ap-beijing.myqcloud.com",)


def extract_media(value: Any, base_url: str, found: list[str], key: str = "") -> None:
    if isinstance(value, str):
        clean_path = urllib.parse.urlparse(value).path.lower()
        if key in MEDIA_KEYS or clean_path.endswith(MEDIA_EXTENSIONS):
            resolved = urllib.parse.urljoin(f"{base_url}/", value)
            if resolved not in found and not resolved.startswith("data:"):
                found.append(resolved)
        return
    if isinstance(value, list):
        for item in value:
            extract_media(item, base_url, found, key)
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            extract_media(child, base_url, found, child_key)


def is_trusted_media_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(hostname.endswith(suffix) for suffix in TRUSTED_MEDIA_HOST_SUFFIXES)


def request_media(url: str, byte_range: str | None) -> tuple[int, bytes, str, dict[str, str]]:
    headers = {"Range": byte_range} if byte_range else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("Content-Type", "application/octet-stream"),
                {name: response.headers[name] for name in ("Accept-Ranges", "Content-Range", "ETag", "Last-Modified") if response.headers.get(name)},
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.read(),
            error.headers.get("Content-Type", "application/octet-stream"),
            {name: error.headers[name] for name in ("Accept-Ranges", "Content-Range", "ETag", "Last-Modified") if error.headers.get(name)},
        )


def error_response(status: int, message: str) -> Response:
    return jsonify({"success": False, "error": message}), status


def serve_static(path: Path) -> Response:
    if not path.is_file():
        return error_response(404, "页面文件不存在")
    if path.suffix == ".html":
        return Response(render_template_string(path.read_text(encoding="utf-8")), mimetype="text/html")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or path.suffix in {".js", ".css"}:
        content_type = f"{content_type}; charset=utf-8"
    return send_file(path, mimetype=content_type, conditional=path.suffix != ".html")


console_bp = Blueprint("console", __name__)


# ---------------------------------------------------------------- 静态页面

def _register_static_routes() -> None:
    counter = itertools.count()
    for route_path, file_path in STATIC_FILES.items():
        def make_view(target: Path = file_path) -> Any:
            def view() -> Response:
                return serve_static(target)
            return view
        endpoint = f"static_{next(counter)}"
        console_bp.add_url_rule(route_path, endpoint=endpoint, view_func=make_view())


_register_static_routes()


# ---------------------------------------------------------------- 基础 API

@console_bp.get("/api/health")
def api_health() -> Response:
    result = {"success": True}
    if current_user.is_authenticated and current_user.is_active:
        result["history_count"] = len(load_history())
    return jsonify(result)


# ---------------------------------------------------------------- 选手库（amxiaolin 数据）

_AM_DIR = DATA_DIR / "amxiaolin"
task_store.configure(_AM_DIR)
_AM_STATE: dict[str, Any] = {"mtime": 0.0, "cards": [], "profiles": {}, "tags": {}, "comments": {}, "enrich": {}}
_AM_LOCK = threading.RLock()
# 手动添加的选手单独存放，导入数据重新生成时不会被覆盖。
_AM_USER_FILE = _AM_DIR / "player-user.json"

_STAT_KEYS = ("FAC", "BDY", "SKL", "POP", "CHA", "PRF")


def _am_user_rows() -> list[dict[str, Any]]:
    """读取手动添加的选手记录。"""
    if not _AM_USER_FILE.is_file():
        return []
    try:
        data = json.loads(_AM_USER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and (row.get("card") or {}).get("id")]


def _am_load() -> dict[str, Any]:
    """懒加载 data/amxiaolin 下的数据，按修改时间缓存。"""
    merged = _AM_DIR / "players-merged.json"
    tags_file = _AM_DIR / "player-tags.jsonl"
    comments_file = _AM_DIR / "player-comments.jsonl"
    enrich_file = _AM_DIR / "dmm-enrich.json"
    stamp = max((p.stat().st_mtime for p in (merged, tags_file, comments_file, enrich_file, _AM_USER_FILE) if p.exists()), default=0.0)
    with _AM_LOCK:
        if _AM_STATE["mtime"] == stamp and _AM_STATE["cards"]:
            return _AM_STATE
    cards: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {}
    tags: dict[str, list[str]] = {}
    comments: dict[str, list[dict[str, Any]]] = {}
    try:
        raw = json.loads(merged.read_text(encoding="utf-8")) if merged.exists() else []
    except (OSError, ValueError):
        raw = []
    if not isinstance(raw, list):
        raw = []
    raw = _am_user_rows() + raw
    for item in raw:
        card = item.get("card") or {}
        profile = item.get("profile") or {}
        if not card or not card.get("id"):
            continue
        cards.append(card)
        if profile:
            profiles[card["id"]] = profile
    for line in (tags_file.read_text(encoding="utf-8").splitlines() if tags_file.exists() else []):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        labels = [t.get("label") for t in (row.get("tags") or []) if t.get("label")]
        if labels:
            tags[row.get("playerId", "")] = labels
    for line in (comments_file.read_text(encoding="utf-8").splitlines() if comments_file.exists() else []):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        items = row.get("comments") or []
        if items:
            comments[row.get("playerId", "")] = items
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        groups.setdefault(_person_key(card, profiles.get(card["id"], {})), []).append(card)
    enrich: dict[str, dict[str, Any]] = {}
    if enrich_file.is_file():
        try:
            enrich = json.loads(enrich_file.read_text(encoding="utf-8"))
        except ValueError:
            enrich = {}
    with _AM_LOCK:
        _AM_STATE.update(mtime=stamp, cards=cards, profiles=profiles, tags=tags, comments=comments,
                         groups=groups, enrich=enrich)
    return _AM_STATE


def _person_key(card: dict[str, Any], profile: dict[str, Any]) -> str:
    """按罗马字名归一化去重：Akari Tsumugi 与 Tsumugi Akari 视为同一人。"""
    roman = (card.get("name") or profile.get("name") or "").lower()
    tokens = re.findall(r"[a-z]+", roman)
    if tokens:
        return " ".join(sorted(tokens))
    display = (card.get("displayName") or profile.get("displayName") or "").strip()
    return f"cn:{display.lower()}" if display else f"id:{card.get('id')}"


def _pick_primary(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """同组里优先 variant 1，其次总评最高。"""
    return sorted(cards, key=lambda c: ((c.get("variant") or 1) != 1, -(c.get("overall") or 0)))[0]


def _bust(measurements: str) -> int:
    match = re.search(r"B(\d{2,3})", measurements or "")
    return int(match.group(1)) if match else 0


_HIDDEN_STATE: dict[str, Any] = {"path": "", "stamp": None, "ids": set()}
_HIDDEN_LOCK = threading.RLock()


def _hidden_ids() -> set[str]:
    path = _AM_DIR / "player-hidden.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return set()
    with _HIDDEN_LOCK:
        if _HIDDEN_STATE["path"] == str(path) and _HIDDEN_STATE["stamp"] == stamp:
            return set(_HIDDEN_STATE["ids"])
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    ids = {str(item) for item in rows if isinstance(item, str)} if isinstance(rows, list) else set()
    with _HIDDEN_LOCK:
        _HIDDEN_STATE.update(path=str(path), stamp=stamp, ids=ids)
    return ids


def _set_hidden(player_id: str, hidden: bool) -> None:
    with _HIDDEN_LOCK:
        ids = _hidden_ids()
        if hidden:
            ids.add(player_id)
        else:
            ids.discard(player_id)
        path = _AM_DIR / "player-hidden.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(path)
        _HIDDEN_STATE.update(path=str(path), stamp=None, ids=set(ids))


def _am_item(card: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    extra = (_AM_STATE.get("enrich") or {}).get(card.get("id"), {})
    dmm_id = str(extra.get("dmm_id") or profile.get("dmmId") or "")
    dmm = _dmm_entry(dmm_id)
    dmm_measure = "-".join(part for part in (
        f"B{dmm['bust']}" if dmm.get("bust") else "",
        f"W{dmm['waist']}" if dmm.get("waist") else "",
        f"H{dmm['hip']}" if dmm.get("hip") else "",
    ) if part)
    measurements = (card.get("measurements") or profile.get("measurements")
                    or extra.get("measurements") or dmm_measure or "")
    height = profile.get("height") or extra.get("height") or dmm.get("height") or ""
    if card.get("card"):
        card_image = f"/api/players/card/{card.get('id')}"
    else:
        card_image = profile.get("dmmImage") or extra.get("image") or dmm.get("image") or ""
    birthday = card.get("birthday") or profile.get("birthday") or ""
    age = ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", birthday):
        year, month, day = (int(part) for part in birthday.split("-"))
        today = datetime.now(timezone.utc)
        age = today.year - year - ((today.month, today.day) < (month, day))
    return {
        "id": card.get("id"),
        "name": card.get("displayName") or profile.get("displayName") or card.get("name"),
        "ro_name": card.get("name") or profile.get("name") or "",
        "jp_name": profile.get("japaneseName") or "",
        "aliases": profile.get("aliases") or [],
        "studio": card.get("studio") or "",
        "club": card.get("clubId") or "",
        "position": card.get("position") or "",
        "overall": card.get("overall"),
        "stats": card.get("stats") or {},
        "height": height,
        "birthday": birthday,
        "age": age,
        "measurements": measurements,
        "bust": _bust(measurements),
        "debut": profile.get("debutYear") or "",
        "agency": profile.get("agency") or "",
        "followers": card.get("totalFollowers") or 0,
        "social": profile.get("social") or {},
        "sources": profile.get("sources") or [],
        "card_image": card_image,
        "custom": bool(profile.get("custom")),
        "tags": _AM_STATE.get("tags", {}).get(card.get("id"), []),
        "dmm_id": dmm_id,
    }


@console_bp.get("/api/players/list")
def api_players_list() -> Response:
    state = _am_load()
    cards, profiles, groups = state["cards"], state["profiles"], state.get("groups") or {}
    query = (request.args.get("q") or "").strip().lower()
    studio = (request.args.get("studio") or "").strip()
    sort = (request.args.get("sort") or "FAC").strip()
    order = (request.args.get("order") or "desc").strip()
    show_all = request.args.get("show") == "all"
    try:
        limit = max(1, min(int(request.args.get("limit") or 60), 200))
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        limit, offset = 60, 0

    hidden_ids = _hidden_ids()
    show_hidden = request.args.get("show_hidden") == "1"
    if show_all:
        entries = [_am_item(card, profiles.get(card["id"], {})) for card in cards]
    else:
        entries = []
        for group_cards in groups.values():
            primary = _pick_primary(group_cards)
            item = _am_item(primary, profiles.get(primary["id"], {}))
            item["group_size"] = len(group_cards)
            item["variant_ids"] = [c["id"] for c in group_cards]
            entries.append(item)

    if not show_hidden:
        entries = [item for item in entries if item["id"] not in hidden_ids]
    for item in entries:
        item["hidden"] = item["id"] in hidden_ids
    if query:
        entries = [item for item in entries if query in (item["name"] or "").lower()
                   or query in (item["ro_name"] or "").lower()
                   or query in (item["jp_name"] or "").lower()]
    if studio:
        entries = [item for item in entries if item["studio"] == studio]

    def sort_key(item: dict[str, Any]):
        if sort in _STAT_KEYS:
            value = (item["stats"] or {}).get(sort) or 0
        else:
            value = item.get(sort)
            if value in (None, ""):
                value = 0
        return value

    try:
        entries.sort(key=sort_key, reverse=(order != "asc"))
    except TypeError:
        entries.sort(key=lambda item: str(sort_key(item)), reverse=(order != "asc"))

    studios = sorted({card.get("studio") for card in cards if card.get("studio")})
    page_items = entries[offset:offset + limit]
    video_entries = _video_entries(_all_videos()[0])
    for item in page_items:
        item["local_books"], item["local_pages"] = _local_stats(item.get("name") or "")
        item["video_count"] = len(_match_player_videos(item, video_entries))
    return jsonify({"success": True, "total": len(entries), "offset": offset, "limit": limit,
                    "studios": studios, "items": page_items})


# ---------------------------------------------------------------- 女优库检索（添加选手用）

_DMM_ACTRESS_STATE: dict[str, Any] = {"stamp": None, "path": "", "entries": [], "by_id": {}}
_DMM_ACTRESS_LOCK = threading.RLock()


def _kana_fold(text: str) -> str:
    """片假名转平假名并转小写，方便中日文互相检索。"""
    normalized = unicodedata.normalize("NFKC", text or "")
    return "".join(chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch
                   for ch in normalized).lower()


def _name_key(text: str) -> str:
    """名字归一化：统一假名/大小写，并去掉空格。"""
    return re.sub(r"\s+", "", _kana_fold(text))


def _actress_roman(image_url: str) -> str:
    """从 DMM 头像地址反推罗马字：kotani_arisa.jpg -> Kotani Arisa。"""
    file_name = urllib.parse.urlparse(image_url or "").path.rsplit("/", 1)[-1]
    file_name = re.sub(r"\.[A-Za-z0-9]+$", "", file_name)
    file_name = re.sub(r"\d+$", "", file_name)
    words = [word for word in re.split(r"[^A-Za-z]+", file_name) if word]
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def _dmm_actresses() -> list[dict[str, Any]]:
    """懒加载 DMM 女优索引（约 1.5 万条），按文件修改时间缓存。"""
    path = _AM_DIR / "dmm-actresses.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    with _DMM_ACTRESS_LOCK:
        if _DMM_ACTRESS_STATE["entries"] and _DMM_ACTRESS_STATE["stamp"] == stamp \
                and _DMM_ACTRESS_STATE["path"] == str(path):
            return _DMM_ACTRESS_STATE["entries"]
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        name = str(row.get("name") or "").strip()
        kana = str(row.get("nameRuby") or "").strip()
        image = str(row.get("imageUrl") or "").strip()
        roman = _actress_roman(image)
        entries.append({
            "id": str(row.get("id") or ""),
            "name": name,
            "kana": kana,
            "roman": roman,
            "image": image,
            "height": str(row.get("height") or ""),
            "bust": str(row.get("bust") or ""),
            "waist": str(row.get("waist") or ""),
            "hip": str(row.get("hip") or ""),
            "name_fold": _name_key(name),
            "kana_fold": _name_key(kana),
            "roman_l": roman.lower(),
            "roman_tokens": set(re.findall(r"[a-z]+", roman.lower())),
            "person_key": _person_key({"name": roman, "displayName": name},
                                      {"name": roman, "displayName": name}),
        })
    with _DMM_ACTRESS_LOCK:
        _DMM_ACTRESS_STATE.update(stamp=stamp, path=str(path), entries=entries,
                                  by_id={entry["id"]: entry for entry in entries if entry["id"]})
    return entries


def _dmm_entry(dmm_id: str) -> dict[str, Any]:
    if not dmm_id:
        return {}
    _dmm_actresses()
    return (_DMM_ACTRESS_STATE.get("by_id") or {}).get(str(dmm_id), {})


def _resolve_dmm_id(display_name: str, jp_name: str, roman_name: str) -> str:
    """按名字在本地 DMM 女优索引里找唯一匹配的 id；不唯一时返回空。"""
    keys = {_name_key(value) for value in (display_name, jp_name) if value}
    roman_tokens = set(re.findall(r"[a-z]+", (roman_name or "").lower()))
    matched: list[str] = []
    for entry in _dmm_actresses():
        if entry["name_fold"] in keys or entry["kana_fold"] in keys:
            matched.append(entry["id"])
        elif roman_tokens and entry["roman_tokens"] == roman_tokens:
            matched.append(entry["id"])
    ids = list(dict.fromkeys(item for item in matched if item))
    return ids[0] if len(ids) == 1 else ""


def _library_name_index() -> dict[str, dict[str, str]]:
    """已有选手的名字索引，用于在检索结果里标记「已在库」。"""
    state = _am_load()
    index: dict[str, dict[str, str]] = {}
    for card in state["cards"]:
        profile = state["profiles"].get(card["id"], {})
        info = {"id": card["id"],
                "name": card.get("displayName") or profile.get("displayName") or card.get("name") or card["id"]}
        index.setdefault(_person_key(card, profile), info)
        for value in (card.get("displayName"), profile.get("displayName"),
                      profile.get("japaneseName"), card.get("name"), profile.get("name")):
            if value:
                index.setdefault("name:" + _name_key(str(value)), info)
    return index


def _actress_score(entry: dict[str, Any], query_name: str, query_l: str,
                   query_tokens: set[str]) -> int | None:
    if query_name == entry["name_fold"] or query_name == entry["kana_fold"] or query_l == entry["roman_l"]:
        return 0
    if entry["name_fold"].startswith(query_name) or entry["kana_fold"].startswith(query_name) \
            or entry["roman_l"].startswith(query_l):
        return 1
    if query_name in entry["name_fold"] or query_name in entry["kana_fold"] \
            or (entry["roman_l"] and query_l in entry["roman_l"]):
        return 2
    if query_tokens and entry["roman_tokens"] and query_tokens.issubset(entry["roman_tokens"]):
        return 3
    return None


@console_bp.get("/api/players/actresses")
def api_players_actresses() -> Response:
    """按名字检索 DMM 女优库，返回可回填到「添加选手」表单的资料。"""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"success": True, "query": "", "items": []})
    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 40))
    except ValueError:
        limit = 20
    query_fold = _kana_fold(query)
    query_l = query_fold.lower()
    query_name = re.sub(r"\s+", "", query_fold)
    query_tokens = set(re.findall(r"[a-z]+", query_l))
    lookup = _library_name_index()
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for order, entry in enumerate(_dmm_actresses()):
        score = _actress_score(entry, query_name, query_l, query_tokens)
        if score is None:
            continue
        scored.append((score, order, entry))
    scored.sort(key=lambda row: (row[0], row[1]))
    items: list[dict[str, Any]] = []
    for _score, _order, entry in scored[:limit]:
        existing = lookup.get(entry["person_key"]) or lookup.get("name:" + entry["name_fold"])
        if existing is None and entry["roman_l"]:
            existing = lookup.get("name:" + re.sub(r"\s+", "", entry["roman_l"]))
        measurements = "-".join(part for part in (
            f"B{entry['bust']}" if entry["bust"] else "",
            f"W{entry['waist']}" if entry["waist"] else "",
            f"H{entry['hip']}" if entry["hip"] else "",
        ) if part)
        height = entry["height"] if re.fullmatch(r"\d{2,3}", entry["height"]) else ""
        items.append({
            "id": entry["id"],
            "name": entry["name"],
            "kana": entry["kana"],
            "roman": entry["roman"],
            "image": entry["image"],
            "height": height,
            "measurements": measurements,
            "in_library": bool(existing),
            "existing_id": (existing or {}).get("id", ""),
            "existing_name": (existing or {}).get("name", ""),
        })
    return jsonify({"success": True, "query": query, "total": len(scored), "items": items})


def _profile_extras(payload: dict[str, Any]) -> dict[str, Any]:
    """校验可编辑的档案字段；空白表示未填写。"""
    height = str(payload.get("height") or "").strip()
    height = height if re.fullmatch(r"\d{2,3}", height) else ""
    measurements = str(payload.get("measurements") or "").strip()[:60]
    birthday = str(payload.get("birthday") or "").strip()
    if birthday:
        try:
            datetime.strptime(birthday, "%Y-%m-%d")
        except ValueError:
            birthday = ""
    agency = str(payload.get("agency") or "").strip()[:80]
    debut = str(payload.get("debut") or "").strip()
    debut = debut if re.fullmatch(r"\d{4}", debut) else ""
    social: dict[str, str] = {}
    for key, field in (("x", "socialX"), ("instagram", "socialInstagram")):
        value = str(payload.get(field) or "").strip()[:300]
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            social[key] = value
    return {"height": height, "measurements": measurements, "birthday": birthday,
            "agency": agency, "debut": debut, "social": social}


def _write_user_rows(rows: list[dict[str, Any]]) -> None:
    _AM_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _AM_USER_FILE.with_name(f"{_AM_USER_FILE.name}.tmp")
    with _AM_LOCK:
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(_AM_USER_FILE)
        _AM_STATE["mtime"] = 0.0


def _am_add_player(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """登记一位选手；只写文字资料，不抓取任何图片。"""
    name = str(payload.get("displayName") or "").strip()
    if not 1 <= len(name) <= 40:
        return None, "名字需为 1—40 个字符"
    jp_name = str(payload.get("japaneseName") or "").strip()[:40]
    roman = str(payload.get("romanName") or "").strip()[:60]
    studio = str(payload.get("studio") or "").strip()[:40]
    note = str(payload.get("note") or "").strip()[:500]
    # 从 DMM 女优库检索结果带来的补充资料（可选，手动填写时为空）。
    dmm_id = str(payload.get("dmmId") or "").strip()
    if not re.fullmatch(r"\d{1,12}", dmm_id):
        dmm_id = ""
    height = str(payload.get("height") or "").strip()
    height = height if re.fullmatch(r"\d{2,3}", height) else ""
    measurements = str(payload.get("measurements") or "").strip()[:40]
    image = str(payload.get("image") or "").strip()[:300]
    if not re.match(r"https://awsimgsrc\.dmm\.co\.jp/", image):
        image = ""
    if not dmm_id:
        dmm_id = _resolve_dmm_id(name, jp_name, roman)

    state = _am_load()
    wanted_key = _person_key({"name": roman, "displayName": name}, {"name": roman, "displayName": name})
    wanted_names = {_name_key(value) for value in (name, jp_name) if value}
    for card in state["cards"]:
        profile = state["profiles"].get(card["id"], {})
        same_person = _person_key(card, profile) == wanted_key
        if not same_person:
            existing_names = {_name_key(str(value)) for value in
                              (card.get("displayName"), profile.get("displayName"), profile.get("japaneseName"))
                              if value}
            same_person = bool(wanted_names & existing_names)
        if same_person:
            existing = card.get("displayName") or profile.get("displayName") or card.get("name") or card["id"]
            return None, f"库中已有这位选手：{existing}"

    base = re.sub(r"[^a-z0-9]+", "-", (roman or name).lower()).strip("-") or "player"
    used = {card["id"] for card in state["cards"]}
    player_id, index = f"user-{base}", 2
    while player_id in used:
        player_id, index = f"user-{base}-{index}", index + 1
    card = {"id": player_id, "displayName": name, "name": roman, "studio": studio, "variant": 1}
    profile = {"displayName": name, "name": roman, "japaneseName": jp_name, "aliases": [],
               "sources": [], "note": note, "custom": True}
    if dmm_id:
        profile["dmmId"] = dmm_id
    if height:
        profile["height"] = height
    if measurements:
        profile["measurements"] = measurements
    if image:
        profile["dmmImage"] = image

    extras = _profile_extras(payload)
    if extras["height"]:
        profile["height"] = extras["height"]
    if extras["measurements"]:
        profile["measurements"] = extras["measurements"]
    if extras["birthday"]:
        profile["birthday"] = extras["birthday"]
    if extras["agency"]:
        profile["agency"] = extras["agency"]
    if extras["debut"]:
        profile["debutYear"] = extras["debut"]
    if extras["social"]:
        profile["social"] = extras["social"]

    rows = _am_user_rows()
    rows.append({"card": card, "profile": profile})
    _write_user_rows(rows)
    refreshed = _am_load()
    return _am_item(card, refreshed["profiles"].get(player_id, profile)), ""


def _am_update_player(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """更新手动添加选手的文字资料；导入选手只读。"""
    player_id = str(payload.get("id") or "").strip()
    name = str(payload.get("displayName") or "").strip()
    if not player_id:
        return None, "缺少选手 id"
    if not 1 <= len(name) <= 40:
        return None, "名字需为 1—40 个字符"
    jp_name = str(payload.get("japaneseName") or "").strip()[:40]
    roman = str(payload.get("romanName") or "").strip()[:60]
    studio = str(payload.get("studio") or "").strip()[:40]
    note = str(payload.get("note") or "").strip()[:500]
    extras = _profile_extras(payload)

    rows = _am_user_rows()
    for row in rows:
        card = row.get("card") or {}
        profile = row.get("profile") or {}
        if card.get("id") != player_id:
            continue
        if not profile.get("custom"):
            return None, "只能编辑手动添加的选手"
        card["displayName"] = name
        card["name"] = roman
        card["studio"] = studio
        profile.update(displayName=name, name=roman, japaneseName=jp_name, note=note)
        for key in ("height", "measurements", "birthday", "agency", "debutYear", "social"):
            profile.pop(key, None)
        if extras["height"]:
            profile["height"] = extras["height"]
        if extras["measurements"]:
            profile["measurements"] = extras["measurements"]
        if extras["birthday"]:
            profile["birthday"] = extras["birthday"]
        if extras["agency"]:
            profile["agency"] = extras["agency"]
        if extras["debut"]:
            profile["debutYear"] = extras["debut"]
        if extras["social"]:
            profile["social"] = extras["social"]
        _write_user_rows(rows)
        refreshed = _am_load()
        return _am_item(card, refreshed["profiles"].get(player_id, profile)), ""
    return None, "只能编辑手动添加的选手"


def _am_refresh_profile(player_id: str) -> tuple[dict[str, Any] | None, list[str], str]:
    """从 DMM 索引和 theidolbase 补全手动选手的空白基础字段。"""
    rows = _am_user_rows()
    for row in rows:
        card = row.get("card") or {}
        profile = row.get("profile") or {}
        if card.get("id") != player_id:
            continue
        if not profile.get("custom"):
            return None, [], "只能补充手动添加的选手"
        name = card.get("displayName") or profile.get("displayName") or ""
        jp_name = profile.get("japaneseName") or ""
        roman = card.get("name") or profile.get("name") or ""
        dmm_id = str(profile.get("dmmId") or "")
        if not dmm_id:
            dmm_id = _resolve_dmm_id(name, jp_name, roman)
        dmm = _dmm_entry(dmm_id)
        dmm_measurements = "-".join(part for part in (
            f"B{dmm['bust']}" if dmm.get("bust") else "",
            f"W{dmm['waist']}" if dmm.get("waist") else "",
            f"H{dmm['hip']}" if dmm.get("hip") else "",
        ) if part)
        try:
            external = profile_enrich.enrich(roman, jp_name, name) if roman else {}
        except Exception:  # noqa: BLE001
            external = {}
        idol = {} if external.get("height") or external.get("birthday") else _idolbase_profile(roman)
        source_height = str(dmm.get("height") or "") or str(external.get("height") or "") or str(idol.get("height") or "")
        source_measurements = (dmm_measurements or str(external.get("measurements") or "")
                               or str(idol.get("measurements") or ""))
        source_birthday = str(external.get("birthday") or "") or str(idol.get("birthday") or "")
        source_agency = str(external.get("agency") or "")
        source_debut = str(external.get("debut") or "")
        source_social = external.get("social") if isinstance(external.get("social"), dict) else {}
        available = [label for label, value in (
            ("身高", source_height), ("三围", source_measurements), ("生日", source_birthday),
            ("事务所", source_agency), ("出道", source_debut), ("社媒", source_social)) if value]
        found: list[tuple[str, str, str]] = []
        if not profile.get("dmmId") and dmm_id:
            found.append(("dmmId", dmm_id, "DMM ID"))
        if not profile.get("dmmImage") and dmm.get("image"):
            found.append(("dmmImage", str(dmm["image"]), "DMM 头像"))
        if not profile.get("height") and source_height:
            found.append(("height", source_height, "身高"))
        if not profile.get("measurements") and source_measurements:
            found.append(("measurements", source_measurements, "三围"))
        if not profile.get("birthday") and source_birthday:
            found.append(("birthday", source_birthday, "生日"))
        if not profile.get("agency") and source_agency:
            found.append(("agency", source_agency, "事务所"))
        if not profile.get("debutYear") and source_debut:
            found.append(("debutYear", source_debut, "出道"))
        changed: list[str] = []
        for field, value, label in found:
            profile[field] = value
            changed.append(label)
        social = dict(profile.get("social") or {})
        for key in ("x", "instagram"):
            if source_social.get(key) and not social.get(key):
                social[key] = str(source_social[key])[:300]
                if "社媒" not in changed:
                    changed.append("社媒")
        if social:
            profile["social"] = social
        sources = list(profile.get("sources") or [])
        sources_changed = False
        for url in external.get("sources") or []:
            if url and url not in sources:
                sources.append(url)
                sources_changed = True
        if sources:
            profile["sources"] = sources
        if changed or sources_changed:
            _write_user_rows(rows)
            refreshed = _am_load()
            return _am_item(card, refreshed["profiles"].get(player_id, profile)), changed, ""
        if available:
            return _am_item(card, profile), [], f"资料已是最新（{'、'.join(available)}）"
        return _am_item(card, profile), [], "没有找到更多基础信息，可点「编辑资料」手动补全"
    return None, [], "只能补充手动添加的选手"


@console_bp.post("/api/players/refresh")
def api_players_refresh() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    info = _task_player(card_id)
    if not info:
        return error_response(400, "没有找到这位选手")
    task = task_store.create("refresh", f"刷新资料：{info['name']}",
                             payload={"player_id": card_id}, player_id=card_id,
                             player_name=info["name"])
    task_id = task["id"]
    task_store.log(task_id, "从 DMM 索引与外部资料源（theidolbase / actorbase / javdatabase）获取…")
    item, changed, error = _am_refresh_profile(card_id)
    if item is None:
        task_store.log(task_id, f"失败：{error}")
        task_store.finish(task_id, "failed", error=error)
        return error_response(400, error)
    message = error or (f"已更新：{'、'.join(changed)}" if changed else "")
    task_store.log(task_id, message or "没有可更新字段")
    task_store.finish(task_id, "success", {"updated": changed, "message": message})
    return jsonify({"success": True, "item": item, "updated": changed,
                    "message": message, "task_id": task_id})


def _run_retry_task(task: dict[str, Any]) -> None:
    task_id = task["id"]
    kind = task.get("kind") or ""
    payload = task.get("payload") or {}
    card_id = str(task.get("player_id") or "")
    try:
        if kind == "refresh":
            item, changed, message = _am_refresh_profile(card_id)
            if item is None:
                raise RuntimeError(message)
            task_store.log(task_id, message or f"已更新：{'、'.join(changed)}")
            task_store.finish(task_id, "success", {"updated": changed, "message": message})
        elif kind == "photos":
            photo_kind = str(payload.get("kind") or "stills")
            result = _photos_payload(card_id, photo_kind, bool(payload.get("refresh")))
            count = len(result["photos"])
            task_store.log(task_id, f"来源 {result.get('source') or '-'}，共 {count} 张")
            task_store.finish(task_id, "success", {
                "name": result["name"], "source": result["source"], "count": count,
                "photos": result["photos"],
            })
        elif kind == "works":
            result = _works_payload(card_id)
            count = len(result["works"])
            task_store.log(task_id, f"共 {count} 部作品")
            task_store.finish(task_id, "success", {
                "name": result["name"], "count": count, "works": result["works"][:8],
            })
        elif kind == "books":
            name = str(payload.get("name") or "")
            result = _books_payload(name)
            count = len(result["books"])
            task_store.log(task_id, f"共 {count} 本书目")
            task_store.finish(task_id, "success", {
                "name": name, "count": count,
                "books": [book for book in result["books"] if book.get("cover")][:8],
            })
        elif kind == "preview":
            name = str(payload.get("name") or "")
            result = _preview_payload(name)
            count = len(result["images"])
            task_store.log(task_id, f"共 {count} 张预览图")
            task_store.finish(task_id, "success", {
                "name": name, "count": count, "images": result["images"][:12],
            })
        else:
            raise RuntimeError(f"不支持重试的任务类型：{kind}")
    except Exception as exc:  # noqa: BLE001
        task_store.log(task_id, f"失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:300])


@console_bp.get("/api/tasks")
def api_tasks_list() -> Response:
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 200))
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        limit, offset = 100, 0
    items, total = task_store.list_tasks(
        kind=(request.args.get("kind") or "").strip(),
        status=(request.args.get("status") or "").strip(),
        player_id=(request.args.get("player_id") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        limit=limit, offset=offset,
    )
    for item in items:
        result = dict(item.get("result") or {})
        if isinstance(result.get("photos"), list):
            result["photos"] = result["photos"][:12]
        item["result"] = result
    return jsonify({"success": True, "total": total, "items": items})


@console_bp.get("/api/tasks/<task_id>")
def api_tasks_detail(task_id: str) -> Response:
    task = task_store.get(task_id, with_logs=True)
    if task is None:
        return error_response(404, "任务不存在")
    return jsonify({"success": True, "task": task})


def _retry_task_record(old: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if old.get("status") == "running":
        return None, "任务仍在运行，不能重试"
    if old.get("kind") == "download":
        payload = old.get("payload") or {}
        job, error = _start_player_download(str(old.get("player_id") or ""),
                                            limit=payload.get("limit") or 0,
                                            codes=str(payload.get("codes") or ""))
        if error:
            return None, error
        return (task_store.get(str(job.get("task_id") or ""), with_logs=False) if job else None), ""
    title = old.get("title") or old.get("kind") or "任务"
    if not title.startswith("重试："):
        title = "重试：" + title
    task = task_store.create(
        old.get("kind") or "unknown", title, payload=old.get("payload") or {},
        player_id=old.get("player_id") or "", player_name=old.get("player_name") or "",
        retry_of=str(old.get("id") or ""),
    )
    threading.Thread(target=_run_retry_task, args=(task,), daemon=True).start()
    return task, ""


@console_bp.post("/api/tasks/<task_id>/retry")
def api_tasks_retry(task_id: str) -> Response:
    old = task_store.get(task_id, with_logs=False)
    if old is None:
        return error_response(404, "任务不存在")
    task, error = _retry_task_record(old)
    if error:
        return error_response(400, error)
    return jsonify({"success": True, "task": task})


@console_bp.post("/api/tasks/bulk")
def api_tasks_bulk() -> Response:
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip()
    count = 0
    if action == "retry_failed":
        items, _ = task_store.list_tasks(status="failed", limit=20)
        for item in items:
            task, error = _retry_task_record(item)
            if task and not error:
                count += 1
    elif action == "cancel_running":
        items, _ = task_store.list_tasks(status="running", limit=50)
        for item in items:
            if item.get("kind") == "download":
                player_id = str(item.get("player_id") or "")
                job = _download_job(player_id)
                if job and job.get("status") == "running":
                    event = _DOWNLOAD_CANCEL.get(player_id)
                    if event is not None:
                        event.set()
                    _download_update(player_id, cancel_requested=True, message="正在取消…")
                    task_store.log(str(item.get("id")), "收到取消请求，正在停止…")
                    count += 1
                    continue
            task_store.cancel(str(item.get("id")), "用户取消")
            count += 1
    elif action == "clear_done":
        count = task_store.delete_finished()
    else:
        return error_response(400, "不支持的操作")
    return jsonify({"success": True, "count": count})


@console_bp.post("/api/tasks/<task_id>/cancel")
def api_tasks_cancel(task_id: str) -> Response:
    task = task_store.get(task_id, with_logs=False)
    if task is None:
        return error_response(404, "任务不存在")
    if task.get("status") != "running":
        return error_response(400, "任务已结束，不能取消")
    if task.get("kind") == "download":
        job = _download_job(str(task.get("player_id") or ""))
        if job and job.get("status") == "running":
            event = _DOWNLOAD_CANCEL.get(str(task.get("player_id") or ""))
            if event is not None:
                event.set()
            _download_update(str(task.get("player_id") or ""), cancel_requested=True, message="正在取消…")
            task_store.log(task_id, "收到取消请求，正在停止…")
            return jsonify({"success": True, "task": task_store.get(task_id, with_logs=False)})
    task_store.cancel(task_id, "用户取消")
    return jsonify({"success": True, "task": task_store.get(task_id, with_logs=False)})


@console_bp.post("/api/players/hide")
def api_players_hide() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    if not card_id:
        return error_response(400, "缺少 id")
    state = _am_load()
    if not any(card.get("id") == card_id for card in state["cards"]):
        return error_response(404, "没有找到这位选手")
    hidden = bool(payload.get("hidden"))
    _set_hidden(card_id, hidden)
    return jsonify({"success": True, "id": card_id, "hidden": hidden})


@console_bp.post("/api/players/update")
def api_players_update() -> Response:
    item, error = _am_update_player(request.get_json(silent=True) or {})
    if error:
        return jsonify({"success": False, "error": error}), 400
    return jsonify({"success": True, "item": item})


@console_bp.post("/api/players/create")
def api_players_create() -> Response:
    payload = request.get_json(silent=True) or {}
    item, error = _am_add_player(payload)
    if error:
        return jsonify({"success": False, "error": error}), 400
    result: dict[str, Any] = {"success": True, "item": item}
    if item and payload.get("autoDownload"):
        job, download_error = _start_player_download(item["id"],
                                                     limit=payload.get("downloadLimit") or 0)
        if job:
            result["download"] = job
        if download_error:
            result["download_error"] = download_error
    return jsonify(result)


_PLAYER_PHOTO_DIR = _AM_DIR / "photos"


def _idolbase_slug(roman_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (roman_name or "").lower()).strip("-")


def _idolbase_images(roman_name: str, sources: list[str]) -> list[str]:
    """theidolbase 演员页的写真画廊（1080px 级原图）。"""
    urls = [u for u in (sources or []) if "theidolbase.com/actress/" in u]
    if not urls:
        slug = _idolbase_slug(roman_name)
        if slug:
            urls = [f"https://www.theidolbase.com/actress/{slug}"]
    images: list[str] = []
    for page_url in urls[:1]:
        try:
            html_text = _nya_fetch(page_url, timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        gallery = re.findall(r"https://image\.yingzhiben\.info/gallery/[^\"'\s]+?\.(?:jpg|jpeg|webp)", html_text)
        avatar = re.findall(r"https://image\.yingzhiben\.info/avatar/[^\"'\s]+?\.(?:jpg|jpeg|webp)", html_text)
        seen = set()
        for item in gallery + avatar:
            if item in seen:
                continue
            seen.add(item)
            images.append(item)
    return images


def _html_lines(markup: str) -> list[str]:
    text = re.sub(r"<script.*?</script>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _idolbase_profile(roman_name: str) -> dict[str, str]:
    """从 theidolbase 人物页提取身高/三围/生日（拿不到就返回空）。"""
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", (roman_name or "").lower()) if token]
    if not tokens:
        return {}
    slugs = list(dict.fromkeys(["-".join(tokens), "-".join(reversed(tokens))]))
    for slug in slugs:
        try:
            html_text = _nya_fetch(f"https://www.theidolbase.com/actress/{slug}", timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if "人物信息" not in html_text:
            continue
        lines = _html_lines(html_text)

        def after(label: str, count: int = 1) -> list[str]:
            for index, line in enumerate(lines):
                if line == label:
                    return lines[index + 1:index + 1 + count]
            return []

        birth = after("出生日期", 3)
        year = re.search(r"(\d{4})年", " ".join(birth))
        month_day = re.search(r"(\d{1,2})月(\d{1,2})日", " ".join(birth))
        birthday = ""
        if year and month_day:
            birthday = f"{year.group(1)}-{int(month_day.group(1)):02d}-{int(month_day.group(2)):02d}"
        height_match = re.search(r"(\d{3})\s*cm", " ".join(after("身高", 1)), re.I)
        measure_match = re.search(r"B\s*\d+[^\s]*?[-\(]?W\s*\d+[^\s]*?H\s*\d+", " ".join(after("三围", 1)), re.I)
        measurements = measure_match.group(0).replace(" ", "") if measure_match else ""
        result = {"birthday": birthday, "height": height_match.group(1) if height_match else "",
                  "measurements": measurements}
        if any(result.values()):
            return result
    return {}


_ACTORBASE_ALIASES = {
    "hashimoto-arina": "arata-arina",
    "arina-hashimoto": "arata-arina",
}


def _actorbase_slugs(roman_name: str) -> list[str]:
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", (roman_name or "").lower()) if t]
    if not tokens:
        return []
    base = ["-".join(reversed(tokens)), "-".join(tokens)]
    extra = [_ACTORBASE_ALIASES[key] for key in base if key in _ACTORBASE_ALIASES]
    return list(dict.fromkeys(base + extra))


_ACTORBASE_WORKS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_ACTORBASE_WORKS_TTL = 86400.0


def _actorbase_works(roman_name: str) -> list[dict[str, Any]]:
    """theactorbase /plates：演员作品车牌号列表（番号/时长/发行日/厂牌）。"""
    if not roman_name:
        return []
    cache_key = roman_name.lower()
    now = time.time()
    cached = _ACTORBASE_WORKS_CACHE.get(cache_key)
    if cached and now - cached[0] < _ACTORBASE_WORKS_TTL:
        return cached[1]
    works: list[dict[str, Any]] = []
    for slug in _actorbase_slugs(roman_name):
        try:
            page = _nya_fetch(f"https://www.theactorbase.com/people/{slug}/plates", timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        rows = re.findall(
            r'<td class="col-fanhao">([^<]+)</td>\s*<td class="col-runtime">([^<]*)</td>\s*<td>([^<]*)</td>\s*<td class="col-company">([^<]*)</td>',
            page, re.S)
        if not rows:
            rows = re.findall(
                r'<td[^>]*col-fanhao[^>]*>([^<]+)</td>.*?<td[^>]*col-runtime[^>]*>([^<]*)</td>.*?<td[^>]*>([0-9]{4}-[0-9]{2}-[0-9]{2})</td>.*?<td[^>]*col-company[^>]*>([^<]*)</td>',
                page, re.S)
        for code, runtime, date, studio in rows:
            works.append({
                "code": html_lib.unescape(code).strip(),
                "runtime": html_lib.unescape(runtime).strip(),
                "date": html_lib.unescape(date).strip(),
                "studio": html_lib.unescape(studio).strip(),
            })
        if works:
            break
    _ACTORBASE_WORKS_CACHE[cache_key] = (now, works)
    return works


def _agency_portraits(jp_name: str, roman_name: str) -> list[str]:
    """事务所官方肖像（T-POWERS 1044x1568 / LIFE 800x1200 / LINX 1164x1746）。"""
    urls: list[str] = []
    roman = (roman_name or "").strip()
    if jp_name:
        try:
            page = _nya_fetch(f"https://www.t-powers.co.jp/talent/{urllib.parse.quote(jp_name)}/", timeout=20).decode("utf-8", "ignore")
            found = re.findall(r"background-image:\s*url\((['\"]?)(https://www\.t-powers\.co\.jp/wp2021/wp-content/uploads/[^)'\"]+\.(?:jpg|jpeg|png))", page)
            urls.extend(item[1] for item in found[:2])
        except Exception:  # noqa: BLE001
            pass
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", roman.lower()) if t]
    if tokens:
        slug = "-".join(reversed(tokens))
        urls.append(f"https://life-promotion.com/images/model/{slug}.webp")
        try:
            page = _nya_fetch(f"https://linx.live/model/{slug}/", timeout=20).decode("utf-8", "ignore")
            found = re.findall(r'src="(https://linx\.live/_astro/[^"]+\.webp)"', page)
            urls.extend(found[:2])
        except Exception:  # noqa: BLE001
            pass
    return urls


def _yahoo_images(name: str, limit: int = 24) -> list[str]:
    """Yahoo! JAPAN 画像検索（原图直链，最高 3072px）。"""
    if not name:
        return []
    images: list[str] = []
    for offset in (1, 21):
        try:
            page = _nya_fetch(f"https://search.yahoo.co.jp/image/search?p={urllib.parse.quote(name)}&b={offset}", timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        for url, width in re.findall(r'"original":\{"url":"([^"]+?)"[^}]*?"width":(\d+)', page):
            if int(width) < 800:
                continue
            cleaned = url.replace("\\u0026", "&").replace("\\/", "/")
            images.append(cleaned)
        if len(images) >= limit:
            break
    return list(dict.fromkeys(images))[:limit]


def _actorbase_images(roman_name: str) -> list[str]:
    """theactorbase 日常照（/people/<slug>/photos 的 gallery 图，1080px）。"""
    for slug in _actorbase_slugs(roman_name):
        for path in (f"/people/{slug}/photos", f"/people/{slug}"):
            try:
                page = _nya_fetch(f"https://www.theactorbase.com{path}", timeout=25).decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                continue
            gallery = re.findall(r"https?://image\.theactorbase\.com/gallery/[^\"'\s]+?\.(?:jpg|jpeg|webp|png)", page)
            galleries = [g.replace("http://", "https://") for g in gallery]
            deduped = list(dict.fromkeys(galleries))
            if len(deduped) >= 6:
                return deduped
            if deduped:
                return deduped
    return []


def _all4jp_images(roman_name: str) -> list[str]:
    """all4jp 演员标签页图片（备用源）。"""
    tokens = [t for t in re.split(r"[^a-z0-9]+", (roman_name or "").lower()) if t]
    slugs = ["-".join(reversed(tokens)), "-".join(tokens)] if tokens else []
    images: list[str] = []
    for slug in slugs[:1]:
        try:
            page = _nya_fetch(f"https://all4jp.com/tag/{slug}/", timeout=20).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if "Page not found" in page:
            continue
        images = re.findall(r"https://i\.ibb\.co/[^\"'\s]+?\.(?:jpg|jpeg|png)", page)
        if images:
            break
    return images


def _javdatabase_covers(roman_name: str, limit: int = 6) -> list[bytes]:
    """按女优名取作品封面字节，作为无剧照时的兜底。"""
    covers: list[bytes] = []
    for slug in _javdatabase_codes(roman_name, limit=limit):
        data = _nya_cover_bytes(slug, full=True)
        if data:
            covers.append(data)
        if len(covers) >= limit:
            break
    return covers


def _javdatabase_codes(roman_name: str, limit: int = 6) -> list[str]:
    """按女优名在 javdatabase 搜作品列表，返回番号（用于取官方剧照）。"""
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", roman_name or "") if t]
    queries = [" ".join(reversed(tokens)), " ".join(tokens)] if tokens else []
    codes: list[str] = []
    seen: set[str] = set()
    for query in queries[:1]:
        try:
            page = _nya_fetch(f"https://www.javdatabase.com/?s={urllib.parse.quote(query)}", timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        for slug in re.findall(r"/movies/([a-z0-9-]+)/", page):
            if slug in seen:
                continue
            seen.add(slug)
            codes.append(slug)
            if len(codes) >= limit:
                return codes
    return codes


def _dmm_cid(code: str) -> str:
    """SNIS-946 -> snis00946（DMM 内容 ID）。"""
    match = re.match(r"^([A-Za-z]+)[-_ ]?0*(\d{1,4})", code or "")
    if not match:
        return ""
    return f"{match.group(1).lower()}{match.group(2).zfill(5)}"


_COMPILATION_PREFIXES = ("IDBD", "IPOK", "OFJE", "IBW", "SONE", "OAE", "MIRD")


def _javdb_title_matches(code: str, roman_name: str) -> bool:
    """校验 javdatabase 该作品页标题里确实有这位女优。"""
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", roman_name or "") if t]
    if not tokens:
        return False
    try:
        page = _nya_fetch(f"https://www.javdatabase.com/movies/{code}/", timeout=20).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return False
    title = re.search(r"<title>([^<]+)</title>", page)
    if not title:
        return False
    lowered = title.group(1).lower()
    return all(token.lower() in lowered for token in tokens)


def _dmm_stills(roman_name: str, limit_codes: int = 10) -> list[tuple[str, list[str]]]:
    """按女优作品返回 (番号, 剧照URL列表) 分组，便于逐组尝试。

    作品来源：theactorbase 精确作品表（按发行日倒序，跳过合集），
    并用 javdatabase 页标题校验确实包含该女优。
    """
    codes: list[str] = []
    works = _actorbase_works(roman_name) if roman_name else []
    for work in works:
        code = (work.get("code") or "").strip()
        if not code:
            continue
        prefix = re.match(r"^([A-Za-z]+)", code)
        if prefix and prefix.group(1).upper() in _COMPILATION_PREFIXES:
            continue
        codes.append(code)
        if len(codes) >= limit_codes * 2:
            break
    if not codes:
        codes = [c.upper() for c in _javdatabase_codes(roman_name, limit=limit_codes)]

    verified: list[str] = []
    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda code: (code, _javdb_title_matches(code, roman_name)), codes[:limit_codes * 2]))
    for code, ok in results:
        if ok:
            verified.append(code)
        if len(verified) >= limit_codes:
            break
    if not verified:
        verified = codes[:limit_codes]

    groups: list[tuple[str, list[str]]] = []
    for code in verified:
        cid = _dmm_cid(code)
        if not cid:
            continue
        urls = [f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}jp-{index}.jpg"
                for index in range(1, 11)]
        groups.append((code.upper(), urls))
    return groups


def _player_photos(card_id: str, name: str, roman_name: str = "", sources: list[str] | None = None,
                   limit: int = 30, force: bool = False, kind: str = "stills",
                   jp_name_for_photos: str = "") -> list[str]:
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", card_id)[:80] or "player"
    if kind == "daily":
        key += "~daily"
    elif kind == "covers":
        key += "~covers"
    folder = _PLAYER_PHOTO_DIR / key
    manifest_file = folder / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
    files = sorted(p.name for p in folder.glob("*.jpg")) if folder.is_dir() else []
    cached_limit = int(manifest.get("limit") or 12)
    fresh = ((time.time() - manifest.get("fetched_at", 0)) < 7 * 86400
             and manifest.get("source") in {"theidolbase", "dmm-stills", "dmm-covers", "all4jp",
                                            "javdatabase-covers", "actorbase"}
             and cached_limit >= limit)
    if not force and fresh and files:
        return [f"/api/players/photo/{key}/{name_}" for name_ in files]
    def download(candidate: str) -> bytes | None:
        try:
            data = _nya_fetch(candidate, timeout=20)
        except Exception:  # noqa: BLE001
            return None
        return data if len(data) >= 25000 and data[:2] == b"\xff\xd8" else None

    folder.mkdir(parents=True, exist_ok=True)
    for old_file in folder.glob("*.jpg"):
        old_file.unlink()

    saved = 0
    source_name = "dmm-stills"
    if kind == "covers":
        codes: list[str] = []
        seen: set[str] = set()
        for work in (_actorbase_works(roman_name) if roman_name else []):
            code = str(work.get("code") or "").strip()
            if not code or code.upper() in seen:
                continue
            prefix = re.match(r"^([A-Za-z]+)", code)
            if prefix and prefix.group(1).upper() in _COMPILATION_PREFIXES:
                continue
            seen.add(code.upper())
            codes.append(code)
            if len(codes) >= 20:
                break
        if not codes and roman_name:
            codes = _javdatabase_codes(roman_name, limit=20)
        with futures.ThreadPoolExecutor(max_workers=6) as pool:
            covers = list(pool.map(lambda code: _nya_cover_bytes(code, full=True), codes[:limit]))
        for data in covers:
            if data:
                saved += 1
                (folder / f"{saved:02d}.jpg").write_bytes(data)
        if saved:
            source_name = "dmm-covers"
            manifest_file.write_text(json.dumps({"fetched_at": time.time(), "count": saved,
                                                "source": source_name, "limit": limit},
                                                ensure_ascii=False), encoding="utf-8")
        files = sorted(p.name for p in folder.glob("*.jpg"))
        return [f"/api/players/photo/{key}/{name_}" for name_ in files]

    if kind == "daily":
        candidates = _agency_portraits(jp_name_for_photos, roman_name)
        candidates += _actorbase_images(roman_name) if roman_name else []
        if len(candidates) < 6 and jp_name_for_photos:
            candidates += _yahoo_images(jp_name_for_photos)
        with futures.ThreadPoolExecutor(max_workers=6) as pool:
            for data in pool.map(download, candidates[:40]):
                if saved >= limit:
                    break
                if not data:
                    continue
                saved += 1
                (folder / f"{saved:02d}.jpg").write_bytes(data)
        if saved:
            source_name = "actorbase"
        if saved == 0:
            candidates = _idolbase_images(roman_name, sources or [])
            source_name = "theidolbase"
            with futures.ThreadPoolExecutor(max_workers=6) as pool:
                for data in pool.map(download, candidates[:40]):
                    if saved >= limit:
                        break
                    if not data:
                        continue
                    saved += 1
                    (folder / f"{saved:02d}.jpg").write_bytes(data)
        if saved:
            manifest_file.write_text(json.dumps({"fetched_at": time.time(), "count": saved,
                                                "source": source_name, "limit": limit},
                                                ensure_ascii=False), encoding="utf-8")
        files = sorted(p.name for p in folder.glob("*.jpg"))
        return [f"/api/players/photo/{key}/{name_}" for name_ in files]

    if roman_name:
        tried = 0
        for _code, urls in _dmm_stills(roman_name):
            if saved >= limit:
                break
            tried += 1
            valid = 0
            with futures.ThreadPoolExecutor(max_workers=8) as pool:
                for data in pool.map(download, urls):
                    if saved >= limit:
                        break
                    if not data:
                        continue
                    valid += 1
                    saved += 1
                    (folder / f"{saved:02d}.jpg").write_bytes(data)
            # 第一部就完全没剧照（老片常见）→ 直接走封面兜底，别逐部试
            if tried >= 1 and valid == 0 and saved == 0:
                break
    if saved < 3 and roman_name:
        for data in _javdatabase_covers(roman_name, limit=limit):
            if saved >= limit:
                break
            saved += 1
            (folder / f"{saved:02d}.jpg").write_bytes(data)
        if saved:
            source_name = "javdatabase-covers"
    if saved == 0:
        candidates = _idolbase_images(roman_name, sources or [])
        source_name = "theidolbase"
        if not candidates:
            candidates = _all4jp_images(roman_name)
            source_name = "all4jp"
        with futures.ThreadPoolExecutor(max_workers=6) as pool:
            for data in pool.map(download, candidates[:40]):
                if saved >= limit:
                    break
                if not data:
                    continue
                saved += 1
                (folder / f"{saved:02d}.jpg").write_bytes(data)
    if saved:
        manifest_file.write_text(json.dumps({"fetched_at": time.time(), "count": saved,
                                            "source": source_name, "limit": limit},
                                            ensure_ascii=False), encoding="utf-8")
    files = sorted(p.name for p in folder.glob("*.jpg"))
    return [f"/api/players/photo/{key}/{name_}" for name_ in files]


def _ndl_books(name: str, limit: int = 18) -> list[dict[str, Any]]:
    """国立国会図書館サーチ：写真集书目检索。"""
    queries = [f"{name} 写真集", f"{name} ヌード"]

    def fetch_xml(query: str) -> str:
        url = ("https://ndlsearch.ndl.go.jp/api/opensearch?any="
               f"{urllib.parse.quote(query)}&cnt=20")
        try:
            return _nya_fetch(url, timeout=25).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return ""

    with futures.ThreadPoolExecutor(max_workers=2) as pool:
        pages = list(pool.map(fetch_xml, queries))
    results: list[dict[str, Any]] = []
    seen = set()
    for xml_text in pages:
        for item in re.findall(r"<item>(.*?)</item>", xml_text, re.S):
            title = re.search(r"<title>([^<]+)</title>", item)
            creator = re.search(r"<dc:creator>([^<]*)</dc:creator>", item)
            date = re.search(r"<dc:date>([^<]*)</dc:date>", item)
            link = re.search(r"<link>([^<]+)</link>", item)
            ident = re.search(r"<dc:identifier[^>]*>([^<]+)</dc:identifier>", item)
            if not title:
                continue
            key = title.group(1)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "title": html_lib.unescape(title.group(1)).strip(),
                "creator": html_lib.unescape(creator.group(1)).strip() if creator else "",
                "date": (date.group(1) or "").strip() if date else "",
                "link": (link.group(1) or "").strip() if link else "",
                "isbn": (ident.group(1) or "").strip() if ident else "",
            })
    return results[:limit]


_BOOK_COVER_DIR = _AM_DIR / "book-covers"
_BOOK_COVER_LOCKS: dict[str, threading.Lock] = {}
_BOOK_COVER_LOCK = threading.Lock()


def _isbn_digits(isbn: str) -> str:
    digits = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    return digits


def _book_cover(isbn: str) -> str:
    """Google Books 封面 → 下载到本地缓存，返回可访问路径。"""
    key = _isbn_digits(isbn)
    if len(key) not in (10, 13):
        return ""
    _BOOK_COVER_DIR.mkdir(parents=True, exist_ok=True)
    target = _BOOK_COVER_DIR / f"{key}.jpg"
    if target.is_file() and target.stat().st_size > 2000:
        return f"/api/players/bookcover/{key}"
    with _BOOK_COVER_LOCK:
        lock = _BOOK_COVER_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if target.is_file() and target.stat().st_size > 2000:
            return f"/api/players/bookcover/{key}"
        try:
            raw = _nya_fetch(f"https://books.google.com/books?jscmd=viewapi&bibkeys=ISBN:{key}", timeout=20).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return ""
        match = re.search(r'"thumbnail_url":"([^"]+)"', raw)
        if not match:
            return ""
        url = match.group(1).replace("\\u0026", "&")
        for zoom in (1, 5):
            candidate = re.sub(r"zoom=\d+", f"zoom={zoom}", url)
            try:
                data = _nya_fetch(candidate, timeout=20)
            except Exception:  # noqa: BLE001
                continue
            if len(data) < 3000 or data[:2] != b"\xff\xd8":
                continue
            try:
                from PIL import Image as _Image
                import io as _io
                image = _Image.open(_io.BytesIO(data)).convert("RGB")
                buffer = _io.BytesIO()
                image.save(buffer, format="JPEG", quality=88)
                data = buffer.getvalue()
            except Exception:  # noqa: BLE001
                pass
            target.write_bytes(data)
            return f"/api/players/bookcover/{key}"
    return ""


@console_bp.get("/api/players/bookcover/<isbn>")
def api_players_bookcover(isbn: str) -> Response:
    key = _isbn_digits(isbn)
    target = (_BOOK_COVER_DIR / f"{key}.jpg").resolve()
    base = _BOOK_COVER_DIR.resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return error_response(404, "封面不存在")
    return send_file(target, mimetype="image/jpeg", max_age=86400)


def _books_payload(name: str) -> dict[str, Any]:
    books = _ndl_books(name)

    def with_cover(book: dict[str, Any]) -> dict[str, Any]:
        book["cover"] = _book_cover(book.get("isbn", ""))
        return book

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        books = list(pool.map(with_cover, books))
    return {"name": name, "books": books}


@console_bp.get("/api/players/books")
def api_players_books() -> Response:
    name = (request.args.get("name") or "").strip()
    if not name:
        return error_response(400, "缺少 name")
    card_id = (request.args.get("id") or "").strip()
    info = _task_player(card_id) if card_id else {}
    task = task_store.create("books", f"写真集书目：{info.get('name') or name}",
                             payload={"name": name, "player_id": card_id},
                             player_id=card_id, player_name=info.get("name") or name)
    task_id = task["id"]
    try:
        result = _books_payload(name)
        count = len(result["books"])
        task_store.log(task_id, f"共 {count} 本书目")
        task_store.finish(task_id, "success", {
            "name": name, "count": count,
            "books": [book for book in result["books"] if book.get("cover")][:8],
        })
        return jsonify({"success": True, "name": name, "count": count,
                        "books": result["books"], "task_id": task_id})
    except Exception as exc:  # noqa: BLE001
        task_store.log(task_id, f"失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:300])
        return error_response(502, f"书目获取失败：{exc}")


_PHOTO_PREVIEW_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_PHOTO_PREVIEW_TTL = 3600.0


def _preview_images_from_article(url: str, host_hint: str) -> list[str]:
    try:
        page = _nya_fetch(url, timeout=20).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    found: list[str] = []
    if "wpb.shueisha.co.jp" in host_hint:
        for srcset in re.findall(r'srcset="([^"]+)"', page):
            pairs = re.findall(r'((?:https?://|/)[^\s,]+?)\s+(\d+)w', srcset)
            if not pairs:
                continue
            best = max(pairs, key=lambda x: int(x[1]))
            if int(best[1]) >= 400:
                url = best[0]
                if url.startswith("/"):
                    url = "https://wpb.shueisha.co.jp" + url
                found.append(url)
        for match in re.findall(r'(https://wpb\.shueisha\.co\.jp/[^"\s]+?-\d+\.(?:jpg|jpeg|webp))', page):
            found.append(match)
    elif "nikkan-spa.jp" in host_hint:
        found.extend(re.findall(r'(https://nikkan-spa\.jp/wp-content/uploads/[^"\s]+\.(?:jpg|jpeg|png))', page))
    elif "menscyzo.com" in host_hint:
        found.extend(re.findall(r'(https://www\.menscyzo\.com/wp-content/uploads/[^"\s]+\.(?:jpg|jpeg|png))', page))
    deduped = list(dict.fromkeys(found))
    return [u for u in deduped if not any(x in u.lower() for x in ("logo", "icon", "banner", "sprite", "avatar", "thumb"))]


def _photo_preview(name: str) -> list[dict[str, Any]]:
    """写真集预览：週プレ / メンズサイゾー 的免费先行图。"""
    key = name.strip()
    now = time.time()
    cached = _PHOTO_PREVIEW_CACHE.get(key)
    if cached and now - cached[0] < _PHOTO_PREVIEW_TTL:
        return cached[1]
    results: list[dict[str, Any]] = []
    sources = [
        ("週プレNEWS", f"https://wpb.shueisha.co.jp/search/?keyword={urllib.parse.quote(name)}", r'href="(/gravure/[0-9]{8}-[0-9]+/)"'),
        ("メンズサイゾー", f"https://www.menscyzo.com/?s={urllib.parse.quote(name)}", r'href="(https://www\.menscyzo\.com/[0-9]{4}/[0-9]{2}/post_[0-9]+\.html)"'),
        ("日刊SPA!", f"https://nikkan-spa.jp/wp-json/wp/v2/posts?search={urllib.parse.quote(name)}&per_page=3&_fields=link", r'"link":"(https://nikkan-spa\.jp/[0-9]+)"'),
    ]
    for label, search_url, pattern in sources:
        try:
            listing = _nya_fetch(search_url, timeout=25).decode("utf-8", "ignore")
            listing = listing.replace("\\/", "/")
        except Exception:  # noqa: BLE001
            continue
        links = list(dict.fromkeys(re.findall(pattern, listing)))[:2]
        urls = [link if link.startswith("http") else "https://wpb.shueisha.co.jp" + link for link in links]
        with futures.ThreadPoolExecutor(max_workers=2) as pool:
            page_images = list(pool.map(lambda url: (url, _preview_images_from_article(url, url)), urls))
        for url, images in page_images:
            if not images:
                continue
            results.append({"source": label, "article": url, "images": images[:8]})
            if len(results) >= 4:
                break
        if len(results) >= 4:
            break
    _PHOTO_PREVIEW_CACHE[key] = (now, results)
    return results


def _preview_payload(name: str) -> dict[str, Any]:
    previews = _photo_preview(name)
    images = [url for group in previews for url in (group.get("images") or [])]
    return {"name": name, "previews": previews, "images": images}


@console_bp.get("/api/players/preview")
def api_players_preview() -> Response:
    name = (request.args.get("name") or "").strip()
    if not name:
        return error_response(400, "缺少 name")
    card_id = (request.args.get("id") or "").strip()
    info = _task_player(card_id) if card_id else {}
    task = task_store.create("preview", f"写真集预览：{info.get('name') or name}",
                             payload={"name": name, "player_id": card_id},
                             player_id=card_id, player_name=info.get("name") or name)
    task_id = task["id"]
    try:
        result = _preview_payload(name)
        count = len(result["images"])
        task_store.log(task_id, f"共 {count} 张预览图")
        task_store.finish(task_id, "success", {
            "name": name, "count": count, "images": result["images"][:12],
        })
        return jsonify({"success": True, "name": name, "count": count,
                        "previews": result["previews"], "task_id": task_id})
    except Exception as exc:  # noqa: BLE001
        task_store.log(task_id, f"失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:300])
        return error_response(502, f"预览获取失败：{exc}")


def _works_payload(card_id: str) -> dict[str, Any]:
    info = _task_player(card_id)
    if not info:
        raise LookupError("没有找到这位选手")
    if not info["roman"]:
        raise LookupError("没有罗马字名，无法检索作品")
    works = _actorbase_works(info["roman"])
    return {"name": info["name"], "works": works}


@console_bp.get("/api/players/works")
def api_players_works() -> Response:
    card_id = (request.args.get("id") or "").strip()
    if not card_id:
        return error_response(400, "缺少 id")
    info = _task_player(card_id)
    if not info:
        return error_response(404, "没有找到这位选手")
    task = task_store.create("works", f"作品：{info['name']}",
                             payload={"player_id": card_id}, player_id=card_id,
                             player_name=info["name"])
    task_id = task["id"]
    try:
        result = _works_payload(card_id)
        count = len(result["works"])
        task_store.log(task_id, f"共 {count} 部作品")
        task_store.finish(task_id, "success", {
            "name": result["name"], "count": count, "works": result["works"][:8],
        })
        return jsonify({"success": True, "count": count, "works": result["works"],
                        "task_id": task_id})
    except Exception as exc:  # noqa: BLE001
        task_store.log(task_id, f"失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:300])
        return error_response(502, f"作品获取失败：{exc}")


_LOCAL_PHOTO_DIR = Path.home() / "Movies" / "写真"
_LOCAL_STATS: dict[str, tuple[float, int, int]] = {}
_LOCAL_STATS_TTL = 60.0


def _local_stats(name: str) -> tuple[int, int]:
    """本地写真集数 / 页数；60 秒缓存，新下载的写真最多 1 分钟后出现。"""
    if not name:
        return 0, 0
    now = time.time()
    cached = _LOCAL_STATS.get(name)
    if cached and now - cached[0] < _LOCAL_STATS_TTL:
        return cached[1], cached[2]
    books = pages = 0
    base = _LOCAL_PHOTO_DIR / name
    if base.is_dir():
        for book in base.iterdir():
            if not book.is_dir() or book.name.startswith("."):
                continue
            books += 1
            spreads = list((book / "spreads").glob("spread_*.jpg"))
            pages += len(spreads) if spreads else sum(1 for _ in book.glob("page_*.jpg"))
    _LOCAL_STATS[name] = (now, books, pages)
    return books, pages


def _local_photos(name: str, limit: int = 120) -> list[str]:
    """~/Movies/写真/<女优名>/<作品code>/page_*.jpg 本地已下载写真。"""
    if not name:
        return []
    base = _LOCAL_PHOTO_DIR / name
    if not base.is_dir():
        return []
    files: list[Path] = []
    for book in sorted(base.iterdir()):
        if not book.is_dir() or book.name.startswith("."):
            continue
        spreads = sorted((book / "spreads").glob("spread_*.jpg"))
        files.extend(spreads or sorted(book.glob("page_*.jpg")))
        if len(files) >= limit:
            break
    chosen = files[:limit]

    def prewarm() -> None:
        for path in chosen[:60]:
            try:
                _local_thumb(path, 420)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=prewarm, daemon=True).start()
    return [f"/api/players/local-photo/{urllib.parse.quote(name)}/{page.relative_to(base).as_posix()}"
            for page in chosen]


# ---------------------------------------------------------------- 外部数据任务

def _task_player(card_id: str) -> dict[str, Any]:
    state = _am_load()
    for card in state["cards"]:
        if card.get("id") != card_id:
            continue
        profile = state["profiles"].get(card_id, {})
        return {
            "id": card_id,
            "name": card.get("displayName") or profile.get("displayName") or card.get("name") or card_id,
            "roman": card.get("name") or profile.get("name") or "",
            "jp": profile.get("japaneseName") or "",
            "sources": profile.get("sources") or [],
        }
    return {}


# ---------------------------------------------------------------- 写真下载任务

_DOWNLOAD_JOBS: dict[str, dict[str, Any]] = {}
_DOWNLOAD_CANCEL: dict[str, threading.Event] = {}
_DOWNLOAD_LOCK = threading.RLock()
_DOWNLOAD_SEMAPHORE = threading.Semaphore(2)
_DOWNLOAD_WORKERS = 2


def _safe_player_folder(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and not any(ch in name for ch in ("/", "\\", "\x00"))


def _download_job(card_id: str) -> dict[str, Any] | None:
    with _DOWNLOAD_LOCK:
        job = _DOWNLOAD_JOBS.get(card_id)
        if job is None:
            return None
        snapshot = dict(job)
        snapshot["errors"] = list(job.get("errors") or [])
        return snapshot


def _download_update(card_id: str, **values: Any) -> None:
    with _DOWNLOAD_LOCK:
        job = _DOWNLOAD_JOBS.get(card_id)
        if job is not None:
            job.update(values)


def _download_one(card_id: str, name: str, book: dict[str, str], should_stop=None) -> int:
    """下载一本书到临时目录，成功后再替换正式目录，避免半成品可见。"""
    base = _LOCAL_PHOTO_DIR / name
    target = base / book["code"]
    temporary = base / f".{book['code']}.part"
    if temporary.exists():
        shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True, exist_ok=True)

    def on_page(done: int, total: int) -> None:
        _download_update(card_id, current=book["code"], page_now=done, page_total=total)

    last: Exception | None = None
    for attempt in range(2):
        try:
            pages = dmm_books.download_book(book["series"], book["code"], temporary,
                                            on_page=on_page, should_stop=should_stop)
            if target.exists():
                shutil.rmtree(target)
            temporary.rename(target)
            (target / ".done").write_text(str(time.time()), encoding="utf-8")
            return pages
        except dmm_books.DownloadCancelled:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            shutil.rmtree(temporary, ignore_errors=True)
            if "404" in str(exc) or "410" in str(exc):
                break
            if attempt == 0:
                temporary.mkdir(parents=True, exist_ok=True)
                time.sleep(3)
    raise last or RuntimeError("下载失败")


def _download_worker(card_id: str, name: str, dmm_id: str, search_name: str) -> None:
    job = _download_job(card_id) or {}
    task_id = str(job.get("task_id") or "")
    limit = int(job.get("limit") or 0)
    codes = str(job.get("codes") or "")
    cancel_event = _DOWNLOAD_CANCEL.get(card_id)
    if cancel_event is None:
        cancel_event = threading.Event()
        _DOWNLOAD_CANCEL[card_id] = cancel_event

    def tlog(message: str) -> None:
        if task_id:
            task_store.log(task_id, message)

    def tupdate(**values: Any) -> None:
        if task_id:
            task_store.update(task_id, **values)

    _download_update(card_id, phase="queued", message="等待前序下载完成…")
    tlog("排队中，等待空闲下载槽…")
    _DOWNLOAD_SEMAPHORE.acquire()
    try:
        if cancel_event.is_set():
            raise dmm_books.DownloadCancelled("已取消")
        _download_update(card_id, phase="listing",
                         message="正在检索她的 DMM 作品…" if dmm_id else "正在按日文名搜索作品…")

        def listed(page: int, pages: int) -> None:
            _download_update(card_id, list_page=page, list_pages=pages,
                             message=f"正在检索作品：第 {page}/{pages} 页…")
            tlog(f"检索作品：第 {page}/{pages} 页")

        books: list[dict[str, str]] = []
        list_error = ""
        page_errors: list[int] = []
        if dmm_id:
            try:
                books = dmm_books.list_books(dmm_id, on_progress=listed, errors=page_errors)
            except Exception as exc:  # noqa: BLE001
                list_error = str(exc)
                _download_update(card_id, message="女优作品页不可用…")
        if not books:
            if not codes:
                detail = f"（{list_error[:90]}）" if list_error else ""
                raise RuntimeError(
                    f"DMM 女优作品页不可用或没有作品{detail}；为避免按名字搜索到同名漫画，已停止。"
                    "如需补下，请指定作品编号。")
            books = dmm_books.search_books(search_name, on_progress=listed)
        if not books:
            detail = f"（{list_error[:90]}）" if list_error else ""
            raise RuntimeError(f"DMM 上没有找到可下载的试读作品{detail}")
        if page_errors:
            tlog(f"警告：作品列表第 {', '.join(map(str, page_errors))} 页抓取失败，可能缺少作品")
        tlog(f"找到 {len(books)} 本作品")
        if cancel_event.is_set():
            raise dmm_books.DownloadCancelled("已取消")
        dest = _LOCAL_PHOTO_DIR / name
        if dest.is_dir():
            for stale in dest.glob(".*.part"):
                if stale.is_dir():
                    shutil.rmtree(stale, ignore_errors=True)
        pending = [book for book in books if not (dest / book["code"] / ".done").is_file()]
        wanted = {part for part in re.split(r"[,，\s]+", codes.upper()) if part}
        if wanted:
            pending = [book for book in pending if book["code"].upper() in wanted]
            if not pending:
                raise RuntimeError("指定的作品编号不在她的作品列表里，或已经下载过")
            tlog(f"按指定编号筛选：{len(pending)} 本")
        if limit:
            pending = pending[:limit]
            tlog(f"数量上限：最多 {limit} 本")
        skipped = len(books) - len(pending)
        _download_update(card_id, phase="downloading", total=len(pending), skipped=skipped,
                         message=f"共 {len(books)} 本，待下载 {len(pending)} 本")
        if pending:
            disk_base = _LOCAL_PHOTO_DIR if _LOCAL_PHOTO_DIR.exists() else Path.home()
            free = shutil.disk_usage(disk_base).free
            needed = len(pending) * 30 * 1024 * 1024
            tlog(f"磁盘剩余 {free / 1e9:.1f} GB，预计需要 {needed / 1e9:.1f} GB（按 30 MB/本）")
            if free < needed + 1024 ** 3:
                raise RuntimeError(f"磁盘空间不足：剩余 {free / 1e9:.1f} GB，预计需要 {needed / 1e9:.1f} GB + 1 GB 余量")
        tupdate(progress=0.1, result={"total": len(books), "pending": len(pending), "skipped": skipped,
                                      "limit": limit, "codes": codes})
        tlog(f"共 {len(books)} 本，待下载 {len(pending)} 本，跳过 {skipped} 本")
        if not pending:
            _LOCAL_STATS.pop(name, None)
            _download_update(card_id, status="done", finished_at=time.time(),
                             message=f"共 {len(books)} 本，已全部下载过")
            task_store.finish(task_id, "success",
                              {"total": len(books), "skipped": skipped,
                               "warnings": page_errors,
                               "photos": _local_photos(name)[:12]}, progress=1)
            return
        finished = failed = pages = 0
        errors: list[str] = []
        with futures.ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as pool:
            jobs = {pool.submit(_download_one, card_id, name, book,
                                cancel_event.is_set): book for book in pending}
            for future in futures.as_completed(jobs):
                book = jobs[future]
                if cancel_event.is_set():
                    for other in jobs:
                        other.cancel()
                try:
                    count = future.result()
                    pages += count
                    finished += 1
                    tlog(f"完成 {book['code']}（{count} 页）")
                except (futures.CancelledError, dmm_books.DownloadCancelled):
                    continue
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(f"{book['code']}: {str(exc)[:100]}")
                    tlog(f"失败 {book['code']}：{str(exc)[:160]}")
                _download_update(card_id, finished=finished, failed=failed, pages=pages)
                tupdate(progress=0.1 + 0.9 * finished / max(1, len(pending)),
                        result={"finished": finished, "failed": failed, "pages": pages,
                                "total": len(pending)})
        _LOCAL_STATS.pop(name, None)
        if cancel_event.is_set():
            message = f"已取消（完成 {finished}/{len(pending)} 本，{pages} 张）"
            _download_update(card_id, status="cancelled", message=message,
                             errors=errors[:5], finished_at=time.time())
            task_store.finish(task_id, "cancelled",
                              {"finished": finished, "failed": failed, "pages": pages,
                               "skipped": skipped, "total": len(books)},
                              error="用户取消", progress=0.1 + 0.9 * finished / max(1, len(pending)))
            return
        message = f"完成 {finished} 本 / {pages} 张"
        if skipped:
            message += f"，跳过已下载 {skipped} 本"
        if failed:
            message += f"，失败 {failed} 本"
        _download_update(card_id, status="done" if finished else "error", message=message,
                         errors=errors[:5], finished_at=time.time())
        task_store.finish(task_id, "success" if finished else "failed",
                          {"finished": finished, "failed": failed, "pages": pages,
                           "skipped": skipped, "total": len(books),
                           "warnings": page_errors,
                           "photos": _local_photos(name)[:12] if finished else []},
                          error="" if finished else message, progress=1)
    except dmm_books.DownloadCancelled:
        _LOCAL_STATS.pop(name, None)
        _download_update(card_id, status="cancelled", message="已取消", finished_at=time.time())
        tlog("用户取消")
        task_store.finish(task_id, "cancelled", error="用户取消")
    except Exception as exc:  # noqa: BLE001
        _download_update(card_id, status="error", message=str(exc)[:200], finished_at=time.time())
        tlog(f"任务失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:500])
    finally:
        _BOOK_PLAN_CACHE.pop(card_id, None)
        _DOWNLOAD_SEMAPHORE.release()
        if _DOWNLOAD_CANCEL.get(card_id) is cancel_event:
            _DOWNLOAD_CANCEL.pop(card_id, None)


def _start_player_download(card_id: str, limit: int = 0, codes: str = "") -> tuple[dict[str, Any] | None, str]:
    """启动（或复用）一位选手的写真下载任务。"""
    state = _am_load()
    card = next((item for item in state["cards"] if item.get("id") == card_id), None)
    if card is None:
        return None, "没有找到这位选手"
    profile = state["profiles"].get(card_id, {})
    extra = (state.get("enrich") or {}).get(card_id, {})
    name = card.get("displayName") or profile.get("displayName") or card.get("name") or ""
    jp_name = profile.get("japaneseName") or ""
    roman = card.get("name") or profile.get("name") or ""
    dmm_id = str(extra.get("dmm_id") or profile.get("dmmId") or "")
    if not dmm_id:
        dmm_id = _resolve_dmm_id(name, jp_name, roman)
    if not dmm_id and not jp_name:
        return None, "没有匹配到 DMM 女优 ID，无法定位她的作品"
    if not _safe_player_folder(name):
        return None, "选手名字包含不能用于文件夹的字符"
    current_key = _person_key(card, profile)
    for other in state["cards"]:
        if other.get("id") == card_id:
            continue
        other_profile = state["profiles"].get(other.get("id"), {})
        other_name = other.get("displayName") or other_profile.get("displayName") or ""
        if other_name == name and _person_key(other, other_profile) != current_key:
            return None, f"存在同名选手「{name}」，写真目录会冲突，请先修改显示名"
    try:
        limit = max(0, min(int(limit or 0), 1000))
    except (TypeError, ValueError):
        limit = 0
    codes = ",".join(part.strip().upper() for part in re.split(r"[,，\s]+", str(codes or "")) if part.strip())[:500]
    if not dmm_id and not codes:
        return None, "没有匹配到 DMM 女优 ID；请先补 DMM ID，或用指定作品编号下载"
    with _DOWNLOAD_LOCK:
        existing = _DOWNLOAD_JOBS.get(card_id)
        if existing and existing.get("status") == "running":
            snapshot = dict(existing)
            snapshot["errors"] = list(existing.get("errors") or [])
            return snapshot, ""
        task = task_store.create("download", f"下载写真：{name}",
                                 payload={"player_id": card_id, "limit": limit, "codes": codes},
                                 player_id=card_id, player_name=name)
        job = {"id": card_id, "name": name, "status": "running", "phase": "listing",
               "total": 0, "finished": 0, "skipped": 0, "failed": 0, "pages": 0,
               "page_now": 0, "page_total": 0, "list_page": 0, "list_pages": 0,
               "current": "", "message": "正在检索她的 DMM 作品…" if dmm_id else "正在按日文名搜索作品…",
               "started_at": time.time(), "finished_at": 0, "errors": [],
               "task_id": task["id"], "limit": limit, "codes": codes}
        _DOWNLOAD_JOBS[card_id] = job
        _DOWNLOAD_CANCEL[card_id] = threading.Event()
    threading.Thread(target=_download_worker,
                     args=(card_id, name, dmm_id, jp_name or name), daemon=True).start()
    return _download_job(card_id), ""


@console_bp.post("/api/players/download/cancel")
def api_players_download_cancel() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    job = _download_job(card_id)
    if not job or job.get("status") != "running":
        return error_response(400, "当前没有正在运行的下载任务")
    event = _DOWNLOAD_CANCEL.get(card_id)
    if event is not None:
        event.set()
    _download_update(card_id, cancel_requested=True, message="正在取消…")
    task_store.log(str(job.get("task_id") or ""), "收到取消请求，正在停止…")
    return jsonify({"success": True, "job": _download_job(card_id)})


def _resume_download_tasks() -> None:
    """Restart downloads that were interrupted by the previous process."""
    try:
        tasks, _ = task_store.list_tasks(kind="download", status="failed", limit=20)
    except Exception:  # noqa: BLE001
        return
    seen: set[str] = set()
    for task in tasks:
        if task.get("error") != "服务重启，任务已中断":
            continue
        player_id = str(task.get("player_id") or "")
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        payload = task.get("payload") or {}
        job, error = _start_player_download(player_id, limit=payload.get("limit") or 0,
                                            codes=str(payload.get("codes") or ""))
        if job:
            task_store.log(str(job.get("task_id") or ""), "服务重启后自动恢复下载")
        if len(seen) >= 5:
            break


_BOOK_PLAN_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_BOOK_PLAN_TTL = 600.0


def _download_book_plan(card_id: str) -> dict[str, Any]:
    info = _task_player(card_id)
    if not info:
        raise LookupError("没有找到这位选手")
    now = time.time()
    cached = _BOOK_PLAN_CACHE.get(card_id)
    if cached and now - cached[0] < _BOOK_PLAN_TTL:
        books = cached[1]
    else:
        state = _am_load()
        card = next((item for item in state["cards"] if item.get("id") == card_id), {})
        profile = state["profiles"].get(card_id, {})
        extra = (state.get("enrich") or {}).get(card_id, {})
        dmm_id = str(extra.get("dmm_id") or profile.get("dmmId") or "")
        if not dmm_id:
            dmm_id = _resolve_dmm_id(info["name"], info["jp"], info["roman"])
        if dmm_id:
            try:
                found = dmm_books.list_books(dmm_id)
            except Exception as exc:  # noqa: BLE001
                raise LookupError(f"DMM 女优作品页不可用（{str(exc)[:80]}），未按名字搜索以免混入同名漫画") from exc
        else:
            found = dmm_books.search_books(info["jp"] or info["name"])
        dest = _LOCAL_PHOTO_DIR / info["name"]
        books = []
        for book in found:
            folder = dest / book["code"]
            books.append({
                "code": book["code"],
                "series": book["series"],
                "done": (folder / ".done").is_file(),
                "pages": len(list(folder.glob("page_*.jpg"))),
                "spreads": len(list((folder / "spreads").glob("spread_*.jpg"))),
            })
        _BOOK_PLAN_CACHE[card_id] = (now, books)
    return {"name": info["name"], "books": books, "total": len(books),
            "done": sum(1 for book in books if book["done"])}


@console_bp.get("/api/players/download/books")
def api_players_download_books() -> Response:
    card_id = (request.args.get("id") or "").strip()
    if not card_id:
        return error_response(400, "缺少 id")
    try:
        return jsonify({"success": True, **_download_book_plan(card_id)})
    except Exception as exc:  # noqa: BLE001
        return error_response(502, f"作品列表获取失败：{exc}")


@console_bp.get("/api/players/download/space")
def api_players_download_space() -> Response:
    base = _LOCAL_PHOTO_DIR if _LOCAL_PHOTO_DIR.exists() else Path.home()
    usage = shutil.disk_usage(base)
    per_book = 30 * 1024 * 1024
    reserve = 1024 ** 3
    max_books = max(0, int((usage.free - reserve) // per_book))
    return jsonify({"success": True, "free": usage.free, "total": usage.total,
                    "free_gb": round(usage.free / 1e9, 1),
                    "per_book_mb": 30, "max_books": max_books})


@console_bp.get("/api/players/download/status")
def api_players_download_status() -> Response:
    card_id = (request.args.get("id") or "").strip()
    job = _download_job(card_id) if card_id else None
    return jsonify({"success": True, "job": job or {"id": card_id, "status": "idle"}})


@console_bp.post("/api/players/download")
def api_players_download() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    if not card_id:
        return error_response(400, "缺少 id")
    job, error = _start_player_download(card_id, limit=payload.get("limit") or 0,
                                       codes=str(payload.get("codes") or ""))
    if error:
        return error_response(400, error)
    return jsonify({"success": True, "job": job})


@console_bp.post("/api/players/pack")
def api_players_pack() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    info = _task_player(card_id)
    if not info:
        return error_response(404, "没有找到这位选手")
    folder = _LOCAL_PHOTO_DIR / info["name"]
    if not folder.is_dir():
        return error_response(400, "还没有本地写真，先下载")
    layout = str(payload.get("layout") or "auto").lower()
    if layout not in {"auto", "spread", "page"}:
        layout = "auto"
    task = task_store.create("pack", f"打包：{info['name']}",
                             payload={"player_id": card_id, "layout": layout},
                             player_id=card_id, player_name=info["name"])
    task_id = task["id"]
    task_store.log(task_id, f"打包 {folder}（layout={layout}）…")
    try:
        import player_pack
        stats = player_pack.pack_player(folder, layout=layout)
        pdf = Path(str(stats.get("pdf") or ""))
        pdf_url = ""
        if pdf.is_file():
            try:
                rel = pdf.relative_to(folder).as_posix()
            except ValueError:
                rel = pdf.name
            pdf_url = "/api/players/pack-file/" + urllib.parse.quote(f"{info['name']}/{rel}", safe="/")
        task_store.log(task_id, f"完成：{stats.get('books')} 本 / {stats.get('pages')} 页")
        task_store.finish(task_id, "success", {
            "books": stats.get("books"), "pages": stats.get("pages"),
            "layout": stats.get("layout"), "pdf_url": pdf_url,
        })
        return jsonify({"success": True, "stats": stats, "pdf_url": pdf_url, "task_id": task_id})
    except Exception as exc:  # noqa: BLE001
        task_store.log(task_id, f"失败：{exc}")
        task_store.finish(task_id, "failed", error=str(exc)[:300])
        return error_response(500, f"打包失败：{exc}")


@console_bp.get("/api/players/pack-file/<path:rel>")
def api_players_pack_file(rel: str) -> Response:
    target = (_LOCAL_PHOTO_DIR / rel).resolve()
    base = _LOCAL_PHOTO_DIR.resolve()
    if not str(target).startswith(str(base)) or target.suffix.lower() != ".pdf" or not target.is_file():
        return error_response(404, "PDF 不存在")
    return send_file(target, mimetype="application/pdf", max_age=0)


_LOCAL_THUMB_DIR = DATA_DIR / "amxiaolin" / "thumbs"


def _local_thumb(target: Path, width: int) -> bytes | None:
    """生成/读取本地写真缩略图（磁盘缓存）。"""
    try:
        import hashlib
        import io as _io
        from PIL import Image as _Image
        key = hashlib.md5(f"{target}:{width}".encode()).hexdigest()
        _LOCAL_THUMB_DIR.mkdir(parents=True, exist_ok=True)
        cache = _LOCAL_THUMB_DIR / f"{key}.jpg"
        if cache.is_file() and cache.stat().st_size > 500:
            return cache.read_bytes()
        image = _Image.open(target).convert("RGB")
        ratio = width / max(1, image.width)
        image = image.resize((width, max(1, int(image.height * ratio))), _Image.LANCZOS)
        buffer = _io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        data = buffer.getvalue()
        cache.write_bytes(data)
        return data
    except Exception:  # noqa: BLE001
        return None


@console_bp.get("/api/players/local-photo/<path:rel>")
def api_players_local_photo(rel: str) -> Response:
    target = (_LOCAL_PHOTO_DIR / rel).resolve()
    base = _LOCAL_PHOTO_DIR.resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return error_response(404, "图片不存在")
    width = request.args.get("w", type=int)
    if width and 160 <= width <= 1200:
        thumb = _local_thumb(target, width)
        if thumb:
            return Response(thumb, mimetype="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
    return send_file(target, mimetype="image/jpeg", max_age=86400)


def _photos_payload(card_id: str, kind: str, refresh: bool = False) -> dict[str, Any]:
    state = _am_load()
    name = roman_name = jp_name = ""
    sources: list[str] = []
    for card in state["cards"]:
        if card.get("id") == card_id:
            profile = state["profiles"].get(card_id, {})
            name = card.get("displayName") or profile.get("displayName") or ""
            roman_name = card.get("name") or profile.get("name") or ""
            jp_name = profile.get("japaneseName") or ""
            sources = profile.get("sources") or []
            break
    if not name:
        raise LookupError("没有找到这位选手")
    if kind == "local":
        photos = _local_photos(name)
        prefix = f"/api/players/local-photo/{urllib.parse.quote(name)}/"
        files = [urllib.parse.unquote(src[len(prefix):]) if src.startswith(prefix) else ""
                 for src in photos]
        return {"name": name, "photos": photos, "files": files, "source": "local"}
    photos = _player_photos(card_id, name, roman_name=roman_name, sources=sources, kind=kind,
                            jp_name_for_photos=jp_name, force=refresh)
    source = ""
    suffix = "~daily" if kind == "daily" else ("~covers" if kind == "covers" else "")
    folder_key = re.sub(r"[^A-Za-z0-9_-]+", "-", card_id)[:80] + suffix
    manifest = _PLAYER_PHOTO_DIR / folder_key / "manifest.json"
    if manifest.is_file():
        try:
            source = json.loads(manifest.read_text(encoding="utf-8")).get("source", "")
        except ValueError:
            source = ""
    return {"name": name, "photos": photos, "source": source}


@console_bp.get("/api/players/photos")
def api_players_photos() -> Response:
    card_id = (request.args.get("id") or "").strip()
    if not card_id:
        return error_response(400, "缺少 id")
    info = _task_player(card_id)
    if not info:
        return error_response(404, "没有找到这位选手")
    kind = (request.args.get("kind") or "stills").lower()
    refresh = request.args.get("refresh") == "1"
    try:
        result = _photos_payload(card_id, kind, refresh)
        return jsonify({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        return error_response(502, f"写真加载失败：{exc}")


@console_bp.post("/api/players/photos/delete")
def api_players_photos_delete() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    info = _task_player(card_id)
    if not info:
        return error_response(404, "没有找到这位选手")
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return error_response(400, "请选择要删除的图片")
    base = (_LOCAL_PHOTO_DIR / info["name"]).resolve()
    if not base.is_dir():
        return error_response(400, "没有本地写真")
    deleted: list[str] = []
    failed: list[str] = []
    affected_books: set[Path] = set()
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    for raw in raw_paths[:500]:
        relative = str(raw or "").strip()
        if not relative or relative.startswith("/") or "\\" in relative or "\x00" in relative:
            failed.append(relative)
            continue
        target = (base / relative).resolve()
        if base not in target.parents or not target.is_file() or target.suffix.lower() not in suffixes:
            failed.append(relative)
            continue
        parts = target.relative_to(base).parts
        leaf = parts[-1].lower()
        is_page = len(parts) >= 2 and leaf.startswith("page_")
        is_spread = len(parts) >= 2 and parts[-2] == "spreads" and leaf.startswith("spread_")
        if not (is_page or is_spread):
            failed.append(relative)
            continue
        try:
            target.unlink()
            deleted.append(relative)
            affected_books.add(target.parent.parent if target.parent.name == "spreads" else target.parent)
        except OSError:
            failed.append(relative)
    for book in affected_books:
        try:
            has_pages = any(book.glob("page_*.jpg"))
            has_spreads = any((book / "spreads").glob("spread_*.jpg"))
            if not has_pages and not has_spreads:
                (book / ".done").unlink(missing_ok=True)
        except OSError:
            pass
    return jsonify({"success": True, "deleted": len(deleted), "files": deleted, "failed": failed})


@console_bp.post("/api/players/photos/discard")
def api_players_photos_discard() -> Response:
    payload = request.get_json(silent=True) or {}
    card_id = str(payload.get("id") or "").strip()
    info = _task_player(card_id)
    if not info:
        return error_response(404, "没有找到这位选手")
    kind = str(payload.get("kind") or "stills").lower()
    if kind not in {"stills", "daily", "covers"}:
        return error_response(400, "只能移除剧照、日常照或封面缓存")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return error_response(400, "请选择要移除的图片")
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", card_id)[:80] or "player"
    if kind == "daily":
        key += "~daily"
    elif kind == "covers":
        key += "~covers"
    folder = (_PLAYER_PHOTO_DIR / key).resolve()
    if not folder.is_dir():
        return error_response(400, "没有图片缓存")
    deleted: list[str] = []
    failed: list[str] = []
    for raw in raw_files[:200]:
        name = str(raw or "").strip()
        if not re.fullmatch(r"\d{1,3}\.jpg", name):
            failed.append(name)
            continue
        target = (folder / name).resolve()
        if folder not in target.parents or not target.is_file():
            failed.append(name)
            continue
        try:
            target.unlink()
            deleted.append(name)
        except OSError:
            failed.append(name)
    manifest_file = folder / "manifest.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest["count"] = len(list(folder.glob("*.jpg")))
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return jsonify({"success": True, "deleted": len(deleted), "files": deleted, "failed": failed})


@console_bp.get("/api/players/photo/<path:name>")
def api_players_photo(name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._/-]+", "-", name)
    target = (_PLAYER_PHOTO_DIR / safe).resolve()
    base = _PLAYER_PHOTO_DIR.resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return error_response(404, "图片不存在")
    return send_file(target, mimetype="image/jpeg", max_age=86400)


@console_bp.get("/api/players/detail")
def api_players_detail() -> Response:
    state = _am_load()
    pid = (request.args.get("id") or "").strip()
    if not pid:
        return error_response(400, "缺少 id")
    groups = state.get("groups") or {}
    for card in state["cards"]:
        if card.get("id") != pid:
            continue
        key = _person_key(card, state["profiles"].get(pid, {}))
        group_cards = groups.get(key, [card])
        profile = state["profiles"].get(pid, {})
        variants = []
        for variant_card in sorted(group_cards, key=lambda c: c.get("variant") or 1):
            variants.append({
                "id": variant_card["id"],
                "variant": variant_card.get("variant"),
                "variantCount": variant_card.get("variantCount"),
                "position": variant_card.get("position"),
                "studio": variant_card.get("studio"),
                "overall": variant_card.get("overall"),
                "stats": variant_card.get("stats") or {},
                "card_image": f"/api/players/card/{variant_card['id']}" if variant_card.get("card") else "",
            })
        detail_item = _am_item(card, profile)
        detail_item["hidden"] = pid in _hidden_ids()
        player_videos_list = _match_player_videos(detail_item)
        detail_item["video_count"] = len(player_videos_list)
        return jsonify({
            "success": True,
            "item": detail_item,
            "videos": [_video_public(video) for video in player_videos_list],
            "card": card,
            "profile": profile,
            "tags": state["tags"].get(pid, []),
            "comments": state["comments"].get(pid, []),
            "variants": variants,
        })
    return error_response(404, "没有找到这位选手")


@console_bp.get("/api/players/card/<path:name>")
def api_players_card(name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    target = (_AM_DIR / "cards" / "players" / f"{safe}.webp").resolve()
    base = (_AM_DIR / "cards" / "players").resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return error_response(404, "卡图不存在")
    return send_file(target, mimetype="image/webp", max_age=86400)


# ---------------------------------------------------------------- 番号搜索 / 迅雷下载

_NYAA_ROW = re.compile(r'<tr class="[^"]*">(.*?)</tr>', re.S)
_NYAA_VIEW = re.compile(r'/view/(\d+)')
_NYAA_TITLE = re.compile(r'<a href="/view/\d+"[^>]*?title="([^"]+)"')
_NYAA_CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
_NYAA_MAGNET = re.compile(r'magnet:\?xt=urn:btih:[0-9a-fA-F]{40}[^"\'<>\s]*')
_NYAA_SIZE = re.compile(r'([\d.]+) (GiB|MiB)')


def _nya_open(url: str, timeout: int = 30) -> bytes:
    """经代理抓取（本机 Clash 混合端口），返回原始字节。"""
    proxy = {"http": NYAA_PROXY, "https": NYAA_PROXY} if NYAA_PROXY else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://javdb.com/",
    }
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as response:
        return response.read()


def _nya_post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    """经代理 POST JSON（DMM GraphQL 用）。"""
    proxy = {"http": NYAA_PROXY, "https": NYAA_PROXY} if NYAA_PROXY else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://video.dmm.co.jp",
        "Referer": "https://video.dmm.co.jp/",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def _nya_fetch(url: str, timeout: int = 30) -> bytes:
    """抓取文本/图片：urllib 失败时用 curl 兜底（绕过 Cloudflare 的 TLS 指纹检测）。"""
    try:
        return _nya_open(url, timeout)
    except Exception:  # noqa: BLE001
        command = ["curl", "-sS", "--max-time", str(timeout), "-L"]
        if NYAA_PROXY:
            command += ["-x", NYAA_PROXY]
        command += [
            "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Referer: https://javdb.com/",
            url,
        ]
        proc = subprocess.run(command, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "ignore").strip() or "curl 抓取失败")
        return proc.stdout


_NYA_MULTI = re.compile(r"(共演|W囁き|3P|4P|5P|ハーレム|乱交|輪姦|集団|多人|複数|W[\s・]|×[^×]{1,14}×)")
_NYA_COLLECTION = re.compile(r"(総集編|ベスト|BEST|コレクション|COMPLETE|まとめ|大全|合集|選集|編)")
_NYA_AMATEUR = re.compile(r"(素人|ナンパ|個撮|FC2|ハメ撮り|しろうと|ガチ撮)")
_NYA_QUALITY = (("8K", re.compile(r"8K")), ("4K", re.compile(r"4K")), ("FHD", re.compile(r"FHD|1080p")), ("HD", re.compile(r"(?<!F)HD|720p")))
_NYA_SUB = re.compile(r"(中文字幕|中字|字幕|CHS|Chinese|简体|繁體)")
_NYA_UNC = re.compile(r"(無修正|无码|破壊版|破坏版|Reducing Mosaic|UNC|Uncensored|流出)")
_NYA_DURATION = re.compile(r"(\d{1,2})\s*(?:時間|小时|時間|hr)")


def _nya_classify(title: str) -> dict[str, Any]:
    """从标题推断类型/画质/字幕/无码/时长。"""
    text = title or ""
    if _NYA_COLLECTION.search(text):
        kind = "合集"
    elif _NYA_MULTI.search(text):
        kind = "多人"
    elif _NYA_AMATEUR.search(text):
        kind = "素人"
    else:
        kind = "单体"
    quality = next((name for name, pattern in _NYA_QUALITY if pattern.search(text)), "")
    duration = _NYA_DURATION.search(text)
    return {
        "type": kind,
        "quality": quality,
        "subtitle": bool(_NYA_SUB.search(text)),
        "uncensored": bool(_NYA_UNC.search(text)),
        "duration": f"{duration.group(1)}小时" if duration else "",
    }


def _nya_search(query: str) -> list[dict[str, Any]]:
    url = f"{NYAA_BASE}/?f=0&c=0_0&q={urllib.parse.quote(query)}"
    page = _nya_open(url).decode("utf-8", "ignore")
    results: list[dict[str, Any]] = []
    for row in _NYAA_ROW.findall(page):
        view = _NYAA_VIEW.search(row)
        if not view:
            continue
        title_match = _NYAA_TITLE.search(row)
        title = html_lib.unescape(title_match.group(1)) if title_match else ""
        cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in _NYAA_CELL.findall(row)]
        size_match = _NYAA_SIZE.search(" ".join(cells))
        numbers = [cell for cell in cells if cell.isdigit()]
        magnet_match = _NYAA_MAGNET.search(row)
        uploaded = next((c for c in cells if re.match(r"\d{4}-\d{2}-\d{2}", c)), "")
        meta = _nya_classify(title)
        results.append({
            "view_id": view.group(1),
            "title": title,
            "size": f"{size_match.group(1)} {size_match.group(2)}" if size_match else "",
            "seeders": int(numbers[-2]) if len(numbers) >= 2 else 0,
            "leechers": int(numbers[-1]) if numbers else 0,
            "downloads": int(numbers[-3]) if len(numbers) >= 3 else 0,
            "uploaded_at": uploaded,
            "download_url": f"{NYAA_BASE}/download/{view.group(1)}.torrent",
            "magnet": html_lib.unescape(magnet_match.group(0)) if magnet_match else "",
            "source": "sukebei",
            **meta,
        })
    return results


def _nya_code_dir(code: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", code or "").strip("-") or "nyaa"
    target = NYAA_DIR / safe
    target.mkdir(parents=True, exist_ok=True)
    return target


_BTDIG_DOWN_UNTIL = 0.0


def _btdig_fetch(url: str, timeout: int = 6) -> str:
    """btdig 对 urllib 会返回 429，固定走 curl；失败则熔断 10 分钟。"""
    global _BTDIG_DOWN_UNTIL
    if time.time() < _BTDIG_DOWN_UNTIL:
        return ""
    command = ["curl", "-sS", "--max-time", str(timeout), "-L"]
    if NYAA_PROXY:
        command += ["-x", NYAA_PROXY]
    command += ["-A", "curl/8.0", url]
    proc = subprocess.run(command, capture_output=True)
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout.decode("utf-8", "ignore")
    _BTDIG_DOWN_UNTIL = time.time() + 600
    return ""


def _nya_search_btdig(query: str) -> list[dict[str, Any]]:
    """btdig 搜索（DHT 索引），返回磁力结果。"""
    page = _btdig_fetch(f"https://btdig.com/search?q={urllib.parse.quote(query)}")
    if not page:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="https://btdig\.com/([a-fA-F0-9]{40})/([^"]*)"', page):
        infohash = match.group(1).lower()
        if infohash in seen:
            continue
        seen.add(infohash)
        tail = page[match.start():match.start() + 700]
        magnet_match = re.search(r'magnet:\?xt=urn:btih:' + infohash + r'[^"\'<>\s]*', page)
        if not magnet_match:
            continue
        size_match = re.search(r'(?:개|files?)\s*<span[^>]*>\s*([\d.]+\s*[KMGT]B)', tail)
        if not size_match:
            size_match = re.search(r'([\d.]+\s*(?:GB|MB|TB))', tail)
        slug = urllib.parse.unquote(match.group(2)).replace('=', '-').replace('/', '-')
        title = re.sub(r'-{2,}', '-', slug).strip('-').upper() or infohash[:8]
        results.append({
            "view_id": "",
            "title": title,
            "size": size_match.group(1).strip() if size_match else "",
            "seeders": 0,
            "leechers": 0,
            "downloads": 0,
            "uploaded_at": "",
            "download_url": "",
            "magnet": html_lib.unescape(magnet_match.group(0)),
            "source": "btdig",
            "infohash": infohash,
            **_nya_classify(title),
        })
    return results


_NYA_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NYA_SEARCH_TTL = 600.0
_NYA_SEARCH_LOCK = threading.Lock()


@console_bp.get("/api/nya/search")
def api_nya_search() -> Response:
    query = (request.args.get("q") or "").strip()
    if not query:
        return error_response(400, "请输入番号")
    source = (request.args.get("source") or "all").lower()
    cache_key = f"{source}:{query.lower()}"
    now = time.time()
    with _NYA_SEARCH_LOCK:
        cached = _NYA_SEARCH_CACHE.get(cache_key)
    if cached and now - cached[0] < _NYA_SEARCH_TTL:
        return jsonify(cached[1])

    results: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    if source != "btdig":
        try:
            results = _nya_search(query)
        except Exception as exc:  # noqa: BLE001
            return error_response(502, f"搜索失败：{exc}")
    if source != "sukebei":
        try:
            extra = _nya_search_btdig(query)
        except Exception:  # noqa: BLE001
            extra = []

    if source == "all":
        known_hashes = set()
        for item in results:
            magnet = item.get("magnet") or ""
            found = re.search(r"btih[:=]([a-fA-F0-9]{40})", magnet)
            if found:
                known_hashes.add(found.group(1).lower())
        extra = [item for item in extra if item["infohash"] not in known_hashes]

    payload = {"success": True, "query": query, "source": source,
               "count": len(results) + len(extra),
               "sources": {"sukebei": len(results) if source != "btdig" else 0,
                            "btdig": len(extra) if source != "sukebei" else 0},
               "results": results + extra}
    with _NYA_SEARCH_LOCK:
        _NYA_SEARCH_CACHE[cache_key] = (now, payload)
        if len(_NYA_SEARCH_CACHE) > 300:
            _NYA_SEARCH_CACHE.pop(next(iter(_NYA_SEARCH_CACHE)))
    return jsonify(payload)


@console_bp.get("/api/nya/releases")
def api_nya_releases() -> Response:
    """批量取发售信息（一次请求替代每卡一次），最多 40 个番号。"""
    codes = [c.strip() for c in (request.args.get("codes") or "").split(",") if c.strip()][:40]
    if not codes:
        return error_response(400, "缺少 codes")
    result: dict[str, dict[str, Any]] = {}

    def fetch(code: str) -> tuple[str, dict[str, Any]]:
        return code, _release_date(code)

    with futures.ThreadPoolExecutor(max_workers=12) as pool:
        for code, info in pool.map(fetch, codes):
            result[code.upper()] = info
    return jsonify({"success": True, "items": result})




@console_bp.post("/api/nya/download")
def api_nya_download() -> Response:
    payload = request.get_json(silent=True) or {}
    view_id = str(payload.get("view_id") or "").strip()
    code = str(payload.get("code") or payload.get("title") or "").strip()
    magnet = str(payload.get("magnet") or "").strip()
    if not view_id and not magnet:
        return error_response(400, "缺少 view_id 或 magnet")
    torrent_path: Path | None = None
    if view_id:
        try:
            data = _nya_open(f"{NYAA_BASE}/download/{view_id}.torrent")
        except Exception as exc:  # noqa: BLE001
            return error_response(502, f"下载种子失败：{exc}")
        if len(data) < 200 or b"announce" not in data[:400]:
            return error_response(502, "返回内容不是合法的种子文件")
        folder = _nya_code_dir(code or f"nyaa-{view_id}")
        torrent_path = folder / f"{folder.name}.torrent"
        torrent_path.write_bytes(data)
    target = str(torrent_path) if torrent_path else magnet
    try:
        subprocess.Popen(["open", "-a", THUNDER_APP, target])
    except Exception as exc:  # noqa: BLE001
        return error_response(500, f"调用迅雷失败：{exc}")
    return jsonify({
        "success": True,
        "message": f"已送入 {THUNDER_APP}",
        "torrent": str(torrent_path) if torrent_path else None,
        "folder": str(torrent_path.parent) if torrent_path else None,
        "magnet": magnet or None,
    })


def _nya_cover_urls(code: str) -> list[str]:
    """按番号拼 DMM 官方封面地址：IPX-368 -> ipx00368。"""
    match = re.match(r"^([A-Za-z]{2,8})[-_ ]?0*(\d{1,4})(?:[-_ ]?[A-Z](?![A-Za-z]))?$", (code or "").strip())
    if not match:
        return []
    key = f"{match.group(1).lower()}{match.group(2).zfill(5)}"
    return [
        f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{key}/{key}pl.jpg",
        f"https://pics.dmm.co.jp/digital/video/{key}/{key}pl.jpg",
        f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{key}/{key}ps.jpg",
    ]


class _NyaNoRedirect(urllib.request.HTTPRedirectHandler):
    """DMM 对不存在的番号会 302 到 NOW PRINTING 占位图，不跟随跳转即可识别。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _nya_cover_fetch(url: str, timeout: int = 15) -> bytes | None:
    """只接受 200 直出的 JPEG；302/404 一律视为没有封面。"""
    proxy = {"http": NYAA_PROXY, "https": NYAA_PROXY} if NYAA_PROXY else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy), _NyaNoRedirect())
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Referer": "https://www.dmm.co.jp/",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError:
        return None
    except Exception:  # noqa: BLE001
        return None
    if len(data) < 3000 or data[:2] != b"\xff\xd8":
        return None
    return data


def _nya_cover_is_placeholder(data: bytes) -> bool:
    """DMM 缺图时会返回 147x200、90%+ 白色的 NOW PRINTING 占位图，需要识别并丢弃。"""
    try:
        from PIL import Image  # 项目 venv 自带 Pillow

        image = Image.open(io.BytesIO(data)).convert("RGB")
        pixels = list(image.resize((32, 32)).getdata())
        white = sum(1 for r, g, b in pixels if r > 215 and g > 215 and b > 215) / len(pixels)
        return white >= 0.6
    except Exception:  # noqa: BLE001
        return len(data) < 6000


def _nya_cover_bytes(code: str, full: bool = False) -> bytes | None:
    """取封面图（DMM 官方 CDN 优先），内存+磁盘缓存；full=True 取大图。"""
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", code or "").strip("-").upper()
    if not key:
        return None
    if not full:
        key = key + "~thumb"
    with _NYA_COVER_LOCK:
        cached_bytes = _NYA_COVER_CACHE.get(key)
    if cached_bytes:
        return cached_bytes
    cached_file = NYAA_COVER_DIR / f"{key}.jpg"
    if cached_file.is_file():
        data = cached_file.read_bytes()
        with _NYA_COVER_LOCK:
            _NYA_COVER_CACHE[key] = data
        return data

    urls = _nya_cover_urls(code)
    if not full:
        urls = [u for u in urls if u.endswith("ps.jpg")] + [u for u in urls if not u.endswith("ps.jpg")]
    data = None
    for url in urls:
        candidate = _nya_cover_fetch(url)
        if candidate and not _nya_cover_is_placeholder(candidate):
            data = candidate
            break
    if data is None:
        cover_url = (_release_date(code) or {}).get("cover") or ""
        if cover_url:
            candidate = _nya_cover_fetch(cover_url)
            if candidate and not _nya_cover_is_placeholder(candidate):
                data = candidate
    if data is None:
        return None
    try:
        NYAA_COVER_DIR.mkdir(parents=True, exist_ok=True)
        cached_file.write_bytes(data)
        with _NYA_COVER_LOCK:
            _NYA_COVER_CACHE[key] = data
            if len(_NYA_COVER_CACHE) > 600:
                _NYA_COVER_CACHE.pop(next(iter(_NYA_COVER_CACHE)))
    except OSError:
        pass
    return data


_RELEASE_CACHE_FILE = DATA_DIR / "nya-release.json"
_RELEASE_CACHE: dict[str, dict[str, Any]] = {}
_RELEASE_LOCK = threading.Lock()


def _release_cache_load() -> None:
    global _RELEASE_CACHE
    try:
        if _RELEASE_CACHE_FILE.is_file():
            _RELEASE_CACHE = json.loads(_RELEASE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _RELEASE_CACHE = {}


def _release_cache_save() -> None:
    try:
        _RELEASE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RELEASE_CACHE_FILE.write_text(json.dumps(_RELEASE_CACHE, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _avwiki_release(code: str) -> str:
    """av-wiki 作品页（企划单体系覆盖好），页面里有「配信日：YYYY-MM-DD」。"""
    slug = re.sub(r"[^a-z0-9-]+", "-", code.lower()).strip("-")
    if not slug:
        return ""
    try:
        page = _nya_fetch(f"https://av-wiki.net/{slug}/").decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""
    if "ページが見つかりませんでした" in page:
        return ""
    match = re.search(r"配信日[：:]\s*(\d{4})-(\d{2})-(\d{2})", page)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"', page)
    return match.group(1) if match else ""


def _wiki_release(code: str) -> str:
    """日文维基百科：按番号检索女优条目；表格里通常只写「M月D日」，年份取上方最近的出现处。"""
    parts = [p for p in re.split(r"[-_\s]+", code.strip().upper()) if p]
    if len(parts) < 2:
        return ""
    pattern = re.compile(r"\s*[-‐–—]?\s*".join(re.escape(p) for p in parts[:2]))
    try:
        api = ("https://ja.wikipedia.org/w/api.php?action=query&list=search&srsearch="
               f"{urllib.parse.quote(code)}&srlimit=4&format=json")
        data = json.loads(_nya_fetch(api).decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return ""
    month_day = re.compile(r"(\d{1,2})月(\d{1,2})日")
    year_pattern = re.compile(r"(\d{4})年")
    for hit in data.get("query", {}).get("search", [])[:4]:
        title = hit.get("title", "")
        if not title:
            continue
        try:
            raw = _nya_fetch("https://ja.wikipedia.org/w/index.php?title="
                             f"{urllib.parse.quote(title)}&action=raw").decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        found = pattern.search(raw)
        if not found:
            continue
        before = raw[max(0, found.start() - 2500):found.start()]
        years = year_pattern.findall(before)
        if not years:
            continue
        year = int(years[-1])
        window = raw[max(0, found.start() - 160):found.end() + 160]
        candidates = [(abs(m.start() - 160), int(m.group(1)), int(m.group(2))) for m in month_day.finditer(window)]
        if not candidates:
            continue
        _, month, day = min(candidates)
        if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _javdatabase_info(code: str) -> dict[str, Any]:
    """javdatabase：发售日/厂牌/类型/时长/演员/封面，覆盖率高。"""
    slug = re.sub(r"[^a-z0-9-]+", "-", code.lower()).strip("-")
    if not slug:
        return {}
    try:
        html = _nya_fetch(f"https://www.javdatabase.com/movies/{slug}/").decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return {}
    if "Release Date" not in html:
        return {}
    date = re.search(r"Release Date:\s*</b>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", html)
    studio = re.search(r"Studio:\s*</b>.*?>([^<]+)</a>", html, re.S)
    runtime = re.search(r"Runtime:\s*</b>\s*([0-9]+) min", html)
    genres = re.findall(r"/genres/[^\"]+\"[^>]*>([^<]+)</a>", html)
    cover = re.search(r"(https://www\.javdatabase\.com/covers/[^\"'\s]+\.(?:webp|jpg|jpeg))", html)
    title = re.search(r"<title>([^<]+)</title>", html)
    actress = ""
    if title:
        parts = [p.strip() for p in title.group(1).split(" - ")]
        if len(parts) >= 3:
            actress = parts[1]
    return {
        "date": date.group(1) if date else "",
        "studio": studio.group(1).strip() if studio else "",
        "runtime": f"{runtime.group(1)}分钟" if runtime else "",
        "genres": genres[:6],
        "actress": actress,
        "cover": cover.group(1) if cover else "",
        "source": "javdatabase",
    }


def _release_date(code: str) -> dict[str, Any]:
    """发售信息：javdatabase 优先，其次 av-wiki / 维基；带缓存。"""
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", code or "").strip("-").upper()
    empty = {"date": "", "source": "", "studio": "", "runtime": "", "genres": [], "actress": "", "cover": ""}
    if not key:
        return empty
    with _RELEASE_LOCK:
        cached = _RELEASE_CACHE.get(key)
    if cached and cached.get("date") is not None and "studio" in cached:
        return cached
    info = _javdatabase_info(key)
    if not info.get("date"):
        info = dict(empty)
        info["date"] = _avwiki_release(key)
        info["source"] = "av-wiki" if info["date"] else ""
        if not info["date"]:
            info["date"] = _wiki_release(key)
            info["source"] = "wikipedia" if info["date"] else ""
    with _RELEASE_LOCK:
        _RELEASE_CACHE[key] = info
        _release_cache_save()
    return info


@console_bp.get("/api/nya/release")
def api_nya_release() -> Response:
    code = (request.args.get("code") or "").strip()
    if not code:
        return error_response(400, "缺少 code")
    return jsonify({"success": True, "code": code, **_release_date(code)})


@console_bp.get("/api/nya/cover")
def api_nya_cover() -> Response:
    code = (request.args.get("code") or "").strip()
    if not code:
        return error_response(400, "缺少 code")
    data = _nya_cover_bytes(code, full=(request.args.get("size") or "thumb") == "full")
    if not data:
        return error_response(404, "没有封面")
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


_VIDEO_CACHE: dict[str, Any] = {"at": 0.0, "items": [], "warning": ""}
_VIDEO_LOCK = threading.RLock()
_VIDEO_TTL = 60.0


def _all_videos() -> tuple[list[dict[str, Any]], str]:
    now = time.time()
    with _VIDEO_LOCK:
        if now - float(_VIDEO_CACHE.get("at") or 0) < _VIDEO_TTL:
            return list(_VIDEO_CACHE["items"]), str(_VIDEO_CACHE.get("warning") or "")
    if not MOVIES_DIR.is_dir():
        return [], "Movies 目录不存在"
    items: list[dict[str, Any]] = []
    records, catalog_warning = read_records("catalog.json")
    technical, technical_warning = read_records("technical.json")
    for path in MOVIES_DIR.rglob("*"):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in PLAYER_EXTENSIONS:
            continue
        relative = path.relative_to(MOVIES_DIR).as_posix()
        try:
            file_stat = path.stat()
        except OSError:
            continue
        item = {
            "id": relative,
            "title": path.stem,
            "filename": path.name,
            "extension": path.suffix.lower().lstrip("."),
            "size": file_stat.st_size,
            "modified_at": datetime.fromtimestamp(file_stat.st_mtime, timezone.utc).isoformat(),
            "url": f"/api/player/video?path={urllib.parse.quote(relative, safe='')}",
        }
        item["metadata"] = item_metadata(item, records, technical, file_stat)
        item["metadata"]["thumb_url"] = (
            "/api/player/thumb?path=" + urllib.parse.quote(relative, safe="")
        )
        items.append(item)
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    with _VIDEO_LOCK:
        _VIDEO_CACHE.update(at=now, items=items, warning=catalog_warning or technical_warning)
    return items, catalog_warning or technical_warning


VIDEO_THUMB_DIR = DATA_DIR / "player" / "thumbs"
FFMPEG_BIN = shutil.which("ffmpeg") or ""
FFPROBE_BIN = shutil.which("ffprobe") or ""
_VIDEO_THUMB_SEM = threading.Semaphore(2)


def _video_duration(path: Path) -> float:
    if not FFPROBE_BIN:
        return 0.0
    try:
        result = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        return max(0.0, float((result.stdout or "").strip() or 0))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _video_thumb(relative: str) -> Path | None:
    relative = str(relative or "").strip()
    if not relative:
        return None
    target = (MOVIES_DIR / relative).resolve()
    if MOVIES_DIR not in target.parents or not target.is_file() or target.suffix.lower() not in PLAYER_EXTENSIONS:
        return None
    try:
        stat = target.stat()
    except OSError:
        return None
    key = hashlib.sha1(f"v2|{relative}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")).hexdigest()
    output = VIDEO_THUMB_DIR / f"{key}.jpg"
    if output.is_file() and output.stat().st_size > 0:
        return output
    if not FFMPEG_BIN:
        return None
    VIDEO_THUMB_DIR.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{key}.{os.getpid()}.{threading.get_ident()}.jpg")
    duration = _video_duration(target)
    if duration:
        seek = f"{max(5.0, min(duration * 0.25, 180.0)):.1f}"
    else:
        seek = "15"
    with _VIDEO_THUMB_SEM:
        if output.is_file() and output.stat().st_size > 0:
            return output
        for candidate in (seek, "0"):
            try:
                result = subprocess.run(
                    [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-ss", candidate,
                     "-i", str(target), "-frames:v", "1", "-vf", "scale=480:-2:flags=lanczos",
                     "-q:v", "4", "-an", "-y", str(temporary)],
                    capture_output=True, timeout=25, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and temporary.is_file() and temporary.stat().st_size > 0:
                temporary.replace(output)
                return output
        try:
            temporary.unlink()
        except OSError:
            pass
    return None


def _video_norm(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", "", value)


def _video_tokens(text: str) -> set[str]:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return {_video_norm(part) for part in re.split(r"[\s　・._\-、,，/()（）\[\]【】]+", value)
            if _video_norm(part)}


def _video_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for item in items:
        metadata = item.get("metadata") or {}
        actors = metadata.get("actors") or []
        text = " ".join([item.get("filename") or "", item.get("title") or "", *actors])
        tokens = _video_tokens(item.get("filename") or "")
        for actor in actors:
            tokens |= _video_tokens(actor)
        entries.append({"item": item, "tokens": tokens, "text": _video_norm(text)})
    return entries


def _player_video_keys(item: dict[str, Any]) -> set[str]:
    names = [item.get("name"), item.get("jp_name"), item.get("ro_name")]
    names.extend(item.get("aliases") or [])
    keys = set()
    for name in names:
        key = _video_norm(name or "")
        if len(key) >= 2:
            keys.add(key)
    return keys


def _match_player_videos(item: dict[str, Any], entries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    keys = _player_video_keys(item)
    if not keys:
        return []
    entries = entries if entries is not None else _video_entries(_all_videos()[0])
    matched = []
    for entry in entries:
        if keys & entry["tokens"] or any(len(key) >= 3 and key in entry["text"] for key in keys):
            matched.append(entry["item"])
    return matched


def _video_public(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    technical = metadata.get("technical") or {}
    return {
        "id": item.get("id"), "title": item.get("title"), "filename": item.get("filename"),
        "url": item.get("url"), "extension": item.get("extension"),
        "size": item.get("size"), "modified_at": item.get("modified_at"),
        "code": metadata.get("code") or "", "actors": metadata.get("actors") or [],
        "release_date": metadata.get("release_date") or "", "full_title": metadata.get("full_title") or "",
        "cover_url": metadata.get("cover_url") or "", "thumb_url": metadata.get("thumb_url") or "",
        "duration": technical.get("duration") or 0,
    }


@console_bp.get("/api/player/videos")
def player_videos() -> Response:
    """列出配置的 Movies 目录下可播放的视频及其资料。"""
    items, warning = _all_videos()
    if not MOVIES_DIR.is_dir():
        return jsonify({"items": [], "directory": str(MOVIES_DIR), "error": "Movies 目录不存在"})
    return jsonify({
        "items": items,
        "directory": str(MOVIES_DIR),
        "catalog": catalog_summary(items),
        "catalog_warning": warning,
    })


@console_bp.get("/api/player/cover")
def player_cover() -> Response:
    records, _ = read_records("catalog.json")
    record = records.get(request.args.get("code", ""), {})
    target = approved_cover(record) if isinstance(record, dict) else None
    if target is None:
        return jsonify({"error": "没有已审核的封面"}), 404
    return send_file(target, conditional=True, max_age=300)


@console_bp.get("/api/player/thumb")
def player_thumb() -> Response:
    target = _video_thumb(request.args.get("path", ""))
    if target is None:
        return error_response(404, "没有视频封面")
    return send_file(target, mimetype="image/jpeg", conditional=True, max_age=86400)


@console_bp.get("/api/player/video")
def player_video() -> Response:
    relative = request.args.get("path", "")
    target = (MOVIES_DIR / relative).resolve()
    if MOVIES_DIR not in target.parents or not target.is_file() or target.suffix.lower() not in PLAYER_EXTENSIONS:
        return error_response(404, "视频不存在")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return send_file(target, mimetype=content_type, conditional=True, etag=True, max_age=0)


@console_bp.get("/api/chat/health")
def api_chat_health() -> Response:
    try:
        status, payload, _ = request_remote("GET", f"{QWEN_API_URL}/models", timeout=15)
        result = decode_json(payload)
        if not 200 <= status < 300:
            return error_response(502, "Qwen 服务不可用")
        model_data = result.get("data", []) if isinstance(result, dict) else []
        models = [item.get("id") for item in model_data if isinstance(item, dict) and item.get("id")]
        return jsonify({"success": True, "model": QWEN_MODEL, "available_models": models})
    except Exception:
        return error_response(502, "Qwen 服务不可用")


@console_bp.get("/api/service/check")
def api_service_check() -> Response:
    try:
        base_url = validate_base_url(request.args.get("base_url", ""))
        if is_autodl_url(base_url):
            if not env_token("AUTODL_ART_TOKEN"):
                return error_response(503, "服务端未配置 AUTODL_ART_TOKEN")
            return jsonify({"success": True, "provider": "AutoDL.Art", "status": "configured"})
        status, _, _ = request_remote("HEAD", f"{base_url}/", timeout=12)
        if status >= 400:
            return error_response(502, f"远端服务返回 {status}")
        return jsonify({"success": True, "status": status})
    except Exception as exc:
        return error_response(502, str(exc))


@console_bp.get("/api/settings")
def api_settings_get() -> Response:
    """Return current effective settings; secrets are masked, never sent in full."""
    autodl_token = effective_setting("AUTODL_ART_TOKEN")
    azt_key = effective_setting("AZT_API_KEY")
    return jsonify(
        {
            "success": True,
            "comfy_url": effective_setting("COMFY_URL", DEFAULT_COMFY_URL),
            "autodl_token_set": bool(autodl_token),
            "autodl_token_masked": mask_secret(autodl_token),
            "azt_key_set": bool(azt_key),
            "azt_key_masked": mask_secret(azt_key),
            "dmm_proxy": _public_proxy(effective_setting("DMM_PROXY", "")),
            "dmm_proxy_candidates": [_public_proxy(item) for item in dmm_books.proxy_candidates()],
            "env_file": str(ENV_FILE),
        }
    )


@console_bp.get("/api/settings/dmm-proxy")
def api_settings_dmm_proxy() -> Response:
    """DMM 下载代理：读取候选；check=1 时实测出口与 DMM 可达性。"""
    check = request.args.get("check") == "1"
    try:
        results = dmm_books.check_proxies(timeout=8) if check else []
    except Exception as exc:  # noqa: BLE001
        return error_response(502, f"代理检测失败：{exc}")
    script = ROOT / "tools" / "dmm_jp_proxy.sh"
    return jsonify({
        "success": True,
        "proxy": _public_proxy(effective_setting("DMM_PROXY", "")),
        "candidates": [_public_proxy(item) for item in dmm_books.proxy_candidates()],
        "results": [{**item, "proxy": _public_proxy(str(item.get("proxy") or ""))} for item in results],
        "script_exists": script.is_file(),
    })


@console_bp.post("/api/settings/dmm-proxy")
def api_settings_dmm_proxy_save() -> Response:
    """保存 DMM_PROXY 到 .env 并立即生效（无需重启）。"""
    data = request.get_json(force=True, silent=True) or {}
    try:
        proxy = dmm_books.normalize_proxy(str(data.get("proxy") or ""))
        save_env_values({"DMM_PROXY": proxy})
        os.environ["DMM_PROXY"] = proxy
        return jsonify({"success": True, "proxy": _public_proxy(proxy),
                        "candidates": [_public_proxy(item) for item in dmm_books.proxy_candidates()]})
    except Exception as exc:  # noqa: BLE001
        return error_response(400, str(exc))


@console_bp.post("/api/settings/dmm-proxy/start")
def api_settings_dmm_proxy_start() -> Response:
    """启动本机独立日本出口（tools/dmm_jp_proxy.sh）。"""
    script = ROOT / "tools" / "dmm_jp_proxy.sh"
    if not script.is_file():
        return error_response(404, "找不到 tools/dmm_jp_proxy.sh")
    try:
        process = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return error_response(500, f"启动失败：{exc}")
    output = (process.stdout + process.stderr).strip()[-1200:]
    return jsonify({"success": process.returncode == 0, "output": output,
                    "candidates": dmm_books.proxy_candidates()})


@console_bp.post("/api/settings")
def api_settings_post() -> Response:
    """Persist settings to .env and apply them live (no restart needed)."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        if not isinstance(data, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        updates: dict[str, str] = {}
        comfy_url = str(data.get("comfyUrl") or "").strip().rstrip("/")
        if comfy_url:
            updates["COMFY_URL"] = validate_base_url(comfy_url)
        for env_name, field in (
            ("AUTODL_ART_TOKEN", "autodlToken"),
            ("AZT_API_KEY", "aztKey"),
        ):
            value = str(data.get(field) or "").strip()
            if value:
                updates[env_name] = value
        if updates:
            save_env_values(updates)
            os.environ.update(updates)
            if "COMFY_URL" in updates:
                try:
                    import photo_lab.app as photo_lab
                except ImportError:
                    pass
                else:
                    photo_lab.COMFY_URL = updates["COMFY_URL"]
        return jsonify(
            {
                "success": True,
                "updated": sorted(updates),
                "comfy_url": effective_setting("COMFY_URL", DEFAULT_COMFY_URL),
                "autodl_token_set": bool(env_token("AUTODL_ART_TOKEN")),
                "azt_key_set": bool(env_token("AZT_API_KEY")),
            }
        )
    except Exception as exc:
        return error_response(400, str(exc))


# ---------------------------------------------------------------- 历史记录

@console_bp.get("/api/history")
def api_history_get() -> Response:
    return jsonify({"success": True, "items": load_history()})


@console_bp.post("/api/history")
def api_history_post() -> Response:
    try:
        item = request.get_json(force=True, silent=True) or {}
        if not isinstance(item, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        key = str(item.get("promptId") or item.get("id") or "")
        with HISTORY_LOCK:
            existing = next((entry for entry in load_history() if str(entry.get("promptId") or entry.get("id")) == key), None)
            if not existing:
                return error_response(404, "任务不存在")
            saved = upsert_history({**existing, **{field: item[field] for field in ("status", "error", "updatedAt", "pollCount") if field in item}})
        return jsonify({"success": True, "item": saved})
    except Exception as exc:
        return error_response(400, str(exc))


@console_bp.delete("/api/history")
def api_history_delete() -> Response:
    key = str(request.args.get("id", "")).strip()
    if not key:
        write_history([])
        return jsonify({"success": True, "deleted": "all"})
    with HISTORY_LOCK:
        items = [entry for entry in load_history() if str(entry.get("promptId") or entry.get("id")) != key]
        write_history(items)
    return jsonify({"success": True, "deleted": key})


# ---------------------------------------------------------------- 工作流

@console_bp.post("/api/workflow/generate")
def api_workflow_generate() -> Response:
    try:
        request_data = request.get_json(force=True, silent=True) or {}
        if not isinstance(request_data, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        base_url = validate_base_url(request_data.get("base_url"))
        workflow_id = str(request_data.get("workflow_id") or "").strip()
        input_values = request_data.get("input_values")
        metadata = request_data.get("metadata") if isinstance(request_data.get("metadata"), dict) else {}
        if not workflow_id:
            raise ValueError("Workflow ID 不能为空")
        if not isinstance(input_values, dict):
            raise ValueError("input_values 必须是对象")
        if is_autodl_url(base_url) or workflow_id == AUTODL_WORKFLOW:
            return handle_autodl_generate(base_url, workflow_id, input_values, metadata)
        remote_body = json.dumps(
            {"workflow_id": workflow_id, "input_values": input_values},
            ensure_ascii=False,
        ).encode("utf-8")
        status, payload, content_type = request_remote(
            "POST",
            f"{base_url}/api/workflow/generate",
            body=remote_body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        result = decode_json(payload)
        if status < 400 and isinstance(result, dict) and result.get("prompt_id"):
            prompt_id = str(result["prompt_id"])
            now = utc_now()
            upsert_history(
                {
                    "id": prompt_id,
                    "promptId": prompt_id,
                    "baseUrl": base_url,
                    "workflowId": workflow_id,
                    "workflowKind": metadata.get("workflowKind") or "",
                    "prompt": metadata.get("prompt") or input_values.get("146:prompt") or input_values.get("15:提示词") or "",
                    "images": metadata.get("images") or [],
                    "status": "pending",
                    "createdAt": metadata.get("createdAt") or now,
                    "updatedAt": now,
                    "pollCount": 0,
                    "result": result,
                    "error": "",
                }
            )
        return Response(payload, status=status, content_type=content_type)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        return error_response(502, str(exc))


def handle_autodl_generate(
    base_url: str,
    workflow_id: str,
    input_values: dict[str, Any],
    metadata: dict[str, Any],
) -> Response:
    token = env_token("AUTODL_ART_TOKEN")
    if not token:
        return error_response(503, "服务端未配置 AUTODL_ART_TOKEN")
    prompt = str(input_values.get("prompt") or metadata.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("视频提示词不能为空")
    payload: dict[str, Any] = {
        "duration": int(input_values.get("duration") or 15),
        "prompt": prompt,
        "resolution": str(input_values.get("resolution") or "768p竖"),
        "seed": int(input_values.get("seed") or 212238359716024),
    }
    for index in range(4):
        value = str(input_values.get(f"ref_image_{index}") or "").strip()
        if value:
            payload[f"ref_image_{index}"] = value
    if not payload.get("ref_image_0"):
        raise ValueError("至少需要一张参考图（ref_image_0）")
    remote_url = f"https://www.autodl.art/api/v1/comfyui/comfyui_workflow/{urllib.parse.quote(workflow_id, safe='')}"
    remote_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, raw, content_type = request_remote(
        "POST",
        remote_url,
        body=remote_body,
        headers={"Authorization": token, "Content-Type": "application/json; charset=utf-8"},
        timeout=120,
    )
    result = decode_json(raw)
    data = result.get("data") if isinstance(result, dict) else None
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if status < 400 and task_id:
        now = utc_now()
        upsert_history(
            {
                "id": str(task_id),
                "promptId": str(task_id),
                "baseUrl": "https://www.autodl.art",
                "workflowId": workflow_id,
                "workflowKind": "autodl-video",
                "provider": "AutoDL.Art",
                "prompt": prompt,
                "images": [f"ref_image_{index}" for index in range(4) if payload.get(f"ref_image_{index}")],
                "status": "pending",
                "createdAt": now,
                "updatedAt": now,
                "pollCount": 0,
                "result": result,
                "error": "",
            }
        )
        return jsonify(
            {
                "success": True,
                "prompt_id": str(task_id),
                "provider": "AutoDL.Art",
                "status": "pending",
                "remote": result,
            }
        )
    return Response(raw, status=status, content_type=content_type)


@console_bp.post("/api/frames/generate")
def api_frame_generate() -> Response:
    try:
        request_data = request.get_json(force=True, silent=True) or {}
        if not isinstance(request_data, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        prompt = str(request_data.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("首尾帧提示词不能为空")
        token = env_token("AZT_API_KEY")
        if not token:
            return error_response(503, "服务端未配置 AZT_API_KEY")
        payload = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "n": 2,
            "size": str(request_data.get("size") or "1024x1536"),
            "quality": str(request_data.get("quality") or "medium"),
            "background": "opaque",
            "output_format": "png",
            "response_format": "b64_json",
        }
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, raw, content_type = request_remote(
            "POST",
            f"{ZERO_IMAGE_BASE_URL}/images/generations",
            body=raw_body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=900,
        )
        result = decode_json(raw)
        if status >= 400:
            return Response(raw, status=status, content_type=content_type)
        items = result.get("data") if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError("Zero 未返回两张首尾帧图片")
        files: list[dict[str, Any]] = []
        frame_dir = ROOT / "outputs" / "zero-frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        for index, item in enumerate(items[:2]):
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if not encoded:
                raise ValueError("Zero 返回的图片缺少 b64_json")
            image_bytes = base64.b64decode(encoded)
            role = "first-frame" if index == 0 else "last-frame"
            path = frame_dir / f"{stamp}-{role}.png"
            path.write_bytes(image_bytes)
            files.append(
                {
                    "role": "first_frame" if index == 0 else "last_frame",
                    "path": str(path),
                    "data_url": f"data:image/png;base64,{encoded}",
                    "bytes": len(image_bytes),
                }
            )
        return jsonify({"success": True, "files": files})
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        return error_response(502, str(exc))


@console_bp.get("/api/workflow/result")
def api_workflow_result() -> Response:
    try:
        prompt_id = str(request.args.get("prompt_id", "")).strip()
        base_url = validate_base_url(request.args.get("base_url", ""))
        if not prompt_id:
            raise ValueError("prompt_id 不能为空")
        existing = next((item for item in load_history() if str(item.get("promptId")) == prompt_id), None)
        if not existing:
            return error_response(404, "任务不存在")
        if str(existing.get("baseUrl", "")).rstrip("/") != base_url.rstrip("/"):
            return error_response(400, "任务服务地址不匹配")
        if is_autodl_url(base_url):
            return handle_autodl_result(prompt_id)
        remote_url = f"{base_url}/api/workflow/result?{urllib.parse.urlencode({'prompt_id': prompt_id})}"
        status, payload, content_type = request_remote("GET", remote_url)
        result = decode_json(payload)
        items = load_history()
        existing = next((item for item in items if str(item.get("promptId")) == prompt_id), {})
        if status < 400:
            upsert_history(
                {
                    **existing,
                    "id": prompt_id,
                    "promptId": prompt_id,
                    "baseUrl": base_url,
                    "status": derive_status(result),
                    "updatedAt": utc_now(),
                    "pollCount": int(existing.get("pollCount") or 0) + 1,
                    "result": result,
                    "error": "" if derive_status(result) != "error" else str(result.get("error") or "任务失败"),
                }
            )
        return Response(payload, status=status, content_type=content_type)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        return error_response(502, str(exc))


def handle_autodl_result(task_id: str) -> Response:
    token = env_token("AUTODL_ART_TOKEN")
    if not token:
        return error_response(503, "服务端未配置 AUTODL_ART_TOKEN")
    remote_url = f"https://www.autodl.art/api/v1/comfyui/comfyui_workflow/result/{urllib.parse.quote(task_id, safe='')}"
    status, payload, content_type = request_remote(
        "GET", remote_url, headers={"Authorization": token}, timeout=60
    )
    result = decode_json(payload)
    normalized = {
        "success": status < 400,
        "status": derive_status(result),
        "provider": "AutoDL.Art",
        "task_id": task_id,
        "remote": result,
    }
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        normalized.update({key: data[key] for key in ("results", "duration") if key in data})
    existing = next((item for item in load_history() if str(item.get("promptId")) == task_id), {})
    if status < 400:
        upsert_history(
            {
                **existing,
                "id": task_id,
                "promptId": task_id,
                "baseUrl": "https://www.autodl.art",
                "status": derive_status(result),
                "updatedAt": utc_now(),
                "pollCount": int(existing.get("pollCount") or 0) + 1,
                "result": normalized,
                "error": "" if derive_status(result) != "error" else str(result.get("msg") or "任务失败"),
            }
        )
    return jsonify(normalized), status


# ---------------------------------------------------------------- 媒体与文件

@console_bp.post("/api/comfy/upload/file")
def api_file_upload() -> Response:
    try:
        base_url = validate_base_url(request.args.get("base_url", ""))
        body = request.get_data()
        content_type = request.headers.get("Content-Type", "application/octet-stream")
        status, payload, remote_content_type = request_remote(
            "POST",
            f"{base_url}/api/comfy/upload/file",
            body=body,
            headers={"Content-Type": content_type},
            timeout=120,
        )
        return Response(payload, status=status, content_type=remote_content_type)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        return error_response(502, str(exc))


@console_bp.get("/api/media")
def api_media_proxy() -> Response:
    try:
        task_id = str(request.args.get("task_id", "")).strip()
        index = int(request.args.get("index", "0"))
        if not task_id or index < 0:
            raise ValueError("媒体参数无效")
        task = next(
            (item for item in load_history() if str(item.get("promptId") or item.get("id")) == task_id),
            None,
        )
        if not task:
            return error_response(404, "未找到生成任务")
        urls: list[str] = []
        extract_media(task.get("result"), str(task.get("baseUrl") or ""), urls)
        if index >= len(urls) or not is_trusted_media_url(urls[index]):
            return error_response(404, "该媒体暂不支持代理预览")
        status, payload, content_type, response_headers = request_media(urls[index], request.headers.get("Range"))
        response = Response(payload, status=status, content_type=content_type)
        response.headers["Cache-Control"] = "private, max-age=300"
        for name, value in response_headers.items():
            response.headers[name] = value
        return response
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        return error_response(502, str(exc))


# ---------------------------------------------------------------- 资产

@console_bp.get("/api/assets")
def api_assets() -> Response:
    assets: list[dict[str, Any]] = []
    for item in load_history():
        urls: list[str] = []
        extract_media(item.get("result"), str(item.get("baseUrl") or ""), urls)
        for index, url in enumerate(urls):
            assets.append(
                {
                    "url": url,
                    "mediaIndex": index,
                    "promptId": item.get("promptId"),
                    "prompt": item.get("prompt") or "",
                    "createdAt": item.get("createdAt"),
                    "updatedAt": item.get("updatedAt"),
                    "type": "video" if urllib.parse.urlparse(url).path.lower().endswith((".mp4", ".webm", ".mov", ".m4v")) else "image",
                }
            )
    return jsonify({"success": True, "items": assets})


# ---------------------------------------------------------------- 对话

CHAT_IMAGE_DIR = ROOT / "outputs" / "chat-images"


def parse_chat_payload() -> dict[str, Any]:
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
        raise ValueError("messages 必须为 1 到 40 条")
    cleaned_messages = []
    total_characters = 0
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("消息格式无效")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise ValueError("消息角色或内容无效")
        content = content.strip()
        if not content or len(content) > 200000:
            raise ValueError("单条消息须为 1 到 200000 个字符")
        total_characters += len(content)
        cleaned_messages.append({"role": role, "content": content})
    if total_characters > 400000:
        raise ValueError("对话总长度不能超过 400000 个字符")
    temperature = float(payload.get("temperature", 0.7))
    max_tokens = int(payload.get("max_tokens", 1024))
    if not 0 <= temperature <= 2:
        raise ValueError("temperature 必须在 0 到 2 之间")
    if not 64 <= max_tokens <= 10240:
        raise ValueError("max_tokens 必须在 64 到 10240 之间")
    return {
        "messages": cleaned_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "enable_thinking": bool(payload.get("enable_thinking", False)),
        "use_tools": bool(payload.get("tools", False)),
    }


def build_chat_request(stream: bool) -> bytes:
    parsed = parse_chat_payload()
    body = {
        "model": QWEN_MODEL,
        "messages": parsed["messages"],
        "temperature": parsed["temperature"],
        "max_tokens": parsed["max_tokens"],
        "stream": stream,
        "chat_template_kwargs": {"enable_thinking": parsed["enable_thinking"]},
    }
    if parsed["use_tools"]:
        body["tools"] = [IMAGE_TOOL]
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def call_qwen(
    messages: list[dict[str, Any]],
    enable_thinking: bool,
    max_tokens: int,
    temperature: float,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    if tools:
        body["tools"] = tools
    status, raw, _ = request_remote(
        "POST",
        f"{QWEN_API_URL}/chat/completions",
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=180,
    )
    result = decode_json(raw)
    if status >= 400:
        message = str(result.get("error") or "Qwen 请求失败") if isinstance(result, dict) else "Qwen 请求失败"
        raise UpstreamError(status, "请求太多，请稍后重试" if status == 429 else message)
    return result


def generate_chat_image(prompt: str, size: str = "1024x1024", quality: str = "medium") -> dict[str, Any]:
    token = effective_setting("AZT_API_KEY")
    if not token:
        raise ValueError("服务端未配置 AZT_API_KEY，无法生图")
    payload = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "background": "opaque",
        "output_format": "png",
        "response_format": "b64_json",
    }
    status, raw, _ = request_remote(
        "POST",
        f"{ZERO_IMAGE_BASE_URL}/images/generations",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=900,
    )
    result = decode_json(raw)
    if status >= 400:
        raise ValueError(str(result.get("error") or "生图失败") if isinstance(result, dict) else "生图失败")
    items = result.get("data") if isinstance(result, dict) else None
    if not isinstance(items, list) or not items or not items[0].get("b64_json"):
        raise ValueError("生图接口未返回图片")
    encoded = items[0]["b64_json"]
    image_dir = CHAT_IMAGE_DIR / str(current_user.id)
    image_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = f"{stamp}.png"
    (image_dir / name).write_bytes(base64.b64decode(encoded))
    return {"prompt": prompt, "data_url": f"data:image/png;base64,{encoded}", "url": f"/api/chat-image/{name}"}


def resolve_chat_turn(parsed: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """返回 (回答文本, 生成的图片列表)。含工具时执行 generate_image 工具闭环。"""
    messages = [dict(message) for message in parsed["messages"]]
    first = call_qwen(
        messages,
        enable_thinking=parsed["enable_thinking"],
        max_tokens=parsed["max_tokens"],
        temperature=parsed["temperature"],
        tools=[IMAGE_TOOL] if parsed["use_tools"] else None,
    )
    message = (first.get("choices") or [{}])[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        return (message.get("content") or "").strip(), []

    images: list[dict[str, Any]] = []
    messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
    for index, call in enumerate(tool_calls):
        function = call.get("function") or {}
        name = function.get("name", "")
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if name == "generate_image":
            try:
                image = generate_chat_image(
                    str(arguments.get("prompt") or "").strip(),
                    str(arguments.get("size") or "1024x1024"),
                    str(arguments.get("quality") or "medium"),
                )
                images.append(image)
                tool_content = json.dumps({"success": True, "image_url": image["url"], "prompt": image["prompt"]}, ensure_ascii=False)
            except Exception as exc:  # 生图失败不中断对话
                tool_content = json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
        else:
            tool_content = json.dumps({"success": False, "error": f"未知工具: {name}"}, ensure_ascii=False)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(call.get("id") or f"call_{index}"),
                "content": tool_content,
            }
        )
    final = call_qwen(
        messages,
        enable_thinking=False,
        max_tokens=parsed["max_tokens"],
        temperature=parsed["temperature"],
        tools=None,
    )
    final_message = (final.get("choices") or [{}])[0].get("message") or {}
    return (final_message.get("content") or "").strip(), images


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@console_bp.post("/api/chat/completions")
def api_chat_completions() -> Response:
    try:
        parsed = parse_chat_payload()
        if parsed["use_tools"]:
            text, images = resolve_chat_turn(parsed)
            return jsonify({"choices": [{"message": {"role": "assistant", "content": text}}], "images": images})
        request_payload = build_chat_request(False)
        status, response_payload, _ = request_remote(
            "POST",
            f"{QWEN_API_URL}/chat/completions",
            body=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=180,
        )
        result = decode_json(response_payload)
        if not 200 <= status < 300:
            if status == 429:
                return error_response(429, "请求太多，请稍后重试")
            return error_response(502, "Qwen 请求失败")
        return jsonify(result)
    except ValueError as exc:
        return error_response(400, str(exc))
    except UpstreamError as exc:
        return error_response(exc.status if exc.status == 429 else 502, str(exc))
    except Exception as exc:
        return error_response(502, str(exc) or "Qwen 服务不可用")


@console_bp.post("/api/chat/stream")
def api_chat_stream() -> Response:
    try:
        parsed = parse_chat_payload()
    except ValueError as exc:
        return error_response(400, str(exc))

    def tool_turn() -> Any:
        try:
            text, images = resolve_chat_turn(parsed)
        except Exception as exc:
            yield sse_event({"error": str(exc)})
            return
        if images:
            yield sse_event({"images": [{"data_url": image["data_url"], "url": image["url"], "prompt": image["prompt"]} for image in images]})
        yield sse_event({"choices": [{"delta": {"content": text}}]})
        yield "data: [DONE]\n\n"

    def passthrough() -> Any:
        upstream_request = urllib.request.Request(
            f"{QWEN_API_URL}/chat/completions",
            data=build_chat_request(True),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            upstream = urllib.request.urlopen(upstream_request, timeout=180, context=ssl.create_default_context())
        except urllib.error.HTTPError as error:
            result = decode_json(error.read())
            message = "请求太多，请稍后重试" if error.code == 429 else (result.get("error", "Qwen 流式请求失败") if isinstance(result, dict) else "Qwen 流式请求失败")
            yield sse_event({"error": message})
            return
        except Exception as exc:
            yield sse_event({"error": str(exc)})
            return
        try:
            for line in upstream:
                yield line
        finally:
            upstream.close()

    return Response(
        stream_with_context(tool_turn() if parsed["use_tools"] else passthrough()),
        mimetype="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@console_bp.get("/api/chat-image/<path:name>")
def api_chat_image(name: str) -> Response:
    safe = Path(name).name
    target = CHAT_IMAGE_DIR / str(current_user.id) / safe
    if not target.exists() and is_admin():
        target = CHAT_IMAGE_DIR / safe
    if not target.exists() or not target.is_file():
        return error_response(404, "图片不存在")
    return send_file(target, mimetype="image/png", max_age=86400)


# ---------------------------------------------------------------- 应用工厂

def create_console_app(config=None) -> Flask:
    task_store.interrupt_running("服务重启，任务已中断")
    task_store.delete_photo_tasks()
    threading.Thread(target=_resume_download_tasks, daemon=True).start()
    threading.Thread(target=_ensure_dmm_proxy, daemon=True).start()
    app = Flask(__name__, static_folder=None)
    if config:
        app.config.update(config)
    app.register_blueprint(console_bp)
    app.register_blueprint(startup_bp)
    from admin import init_admin
    init_admin(app)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the H3 video console (Flask)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()
    from app import create_app
    app = create_app()
    print(f"H3 video console: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
