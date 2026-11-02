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
import ssl
import subprocess
import threading
import time
import html as html_lib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
_AM_STATE: dict[str, Any] = {"mtime": 0.0, "cards": [], "profiles": {}, "tags": {}, "comments": {}}
_AM_LOCK = threading.RLock()

_STAT_KEYS = ("FAC", "BDY", "SKL", "POP", "CHA", "PRF")


def _am_load() -> dict[str, Any]:
    """懒加载 data/amxiaolin 下的数据，按修改时间缓存。"""
    merged = _AM_DIR / "players-merged.json"
    tags_file = _AM_DIR / "player-tags.jsonl"
    comments_file = _AM_DIR / "player-comments.jsonl"
    stamp = max((p.stat().st_mtime for p in (merged, tags_file, comments_file) if p.exists()), default=0.0)
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
    with _AM_LOCK:
        _AM_STATE.update(mtime=stamp, cards=cards, profiles=profiles, tags=tags, comments=comments,
                         groups=groups)
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


def _am_item(card: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
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
        "height": profile.get("height") or "",
        "birthday": birthday,
        "age": age,
        "measurements": card.get("measurements") or profile.get("measurements") or "",
        "bust": _bust(card.get("measurements") or profile.get("measurements") or ""),
        "debut": profile.get("debutYear") or "",
        "agency": profile.get("agency") or "",
        "followers": card.get("totalFollowers") or 0,
        "social": profile.get("social") or {},
        "sources": profile.get("sources") or [],
        "card_image": f"/api/players/card/{card.get('id')}" if card.get("card") else "",
        "tags": _AM_STATE.get("tags", {}).get(card.get("id"), []),
    }


@console_bp.get("/api/players/list")
def api_players_list() -> Response:
    state = _am_load()
    cards, profiles, groups = state["cards"], state["profiles"], state.get("groups") or {}
    query = (request.args.get("q") or "").strip().lower()
    studio = (request.args.get("studio") or "").strip()
    sort = (request.args.get("sort") or "overall").strip()
    order = (request.args.get("order") or "desc").strip()
    show_all = request.args.get("show") == "all"
    try:
        limit = max(1, min(int(request.args.get("limit") or 60), 200))
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        limit, offset = 60, 0

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
    return jsonify({"success": True, "total": len(entries), "offset": offset, "limit": limit,
                    "studios": studios, "items": entries[offset:offset + limit]})


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
        return jsonify({
            "success": True,
            "item": _am_item(card, profile),
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


def _btdig_fetch(url: str, timeout: int = 25) -> str:
    """btdig 对 urllib 会返回 429，固定走 curl。"""
    command = ["curl", "-sS", "--max-time", str(timeout), "-L"]
    if NYAA_PROXY:
        command += ["-x", NYAA_PROXY]
    command += ["-A", "curl/8.0", url]
    for attempt in range(2):
        proc = subprocess.run(command, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "ignore")
        time.sleep(1.5)  # 限流冷却后重试一次
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


@console_bp.get("/api/nya/search")
def api_nya_search() -> Response:
    query = (request.args.get("q") or "").strip()
    if not query:
        return error_response(400, "请输入番号")
    try:
        results = _nya_search(query)
    except Exception as exc:  # noqa: BLE001
        return error_response(502, f"搜索失败：{exc}")
    known_hashes = set()
    for item in results:
        magnet = item.get("magnet") or ""
        found = re.search(r"btih[:=]([a-fA-F0-9]{40})", magnet)
        if found:
            known_hashes.add(found.group(1).lower())
    extra = [item for item in _nya_search_btdig(query)
             if item["infohash"] not in known_hashes]
    combined = results + extra
    return jsonify({"success": True, "query": query, "count": len(combined),
                    "sources": {"sukebei": len(results), "btdig": len(extra)},
                    "results": combined})


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


def _nya_cover_bytes(code: str) -> bytes | None:
    """取封面图（DMM 官方 CDN 优先），内存+磁盘缓存。"""
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", code or "").strip("-").upper()
    if not key:
        return None
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

    data = None
    for url in _nya_cover_urls(code):
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
    data = _nya_cover_bytes(code)
    if not data:
        return error_response(404, "没有封面")
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@console_bp.get("/api/player/videos")
def player_videos() -> Response:
    """列出配置的 Movies 目录下可播放的视频及其资料。"""
    if not MOVIES_DIR.is_dir():
        return jsonify({"items": [], "directory": str(MOVIES_DIR), "error": "Movies 目录不存在"})
    items = []
    records, catalog_warning = read_records("catalog.json")
    technical, technical_warning = read_records("technical.json")
    for path in MOVIES_DIR.rglob("*"):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in PLAYER_EXTENSIONS:
            continue
        relative = path.relative_to(MOVIES_DIR).as_posix()
        file_stat = path.stat()
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
        items.append(item)
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return jsonify({
        "items": items,
        "directory": str(MOVIES_DIR),
        "catalog": catalog_summary(items),
        "catalog_warning": catalog_warning or technical_warning,
    })


@console_bp.get("/api/player/cover")
def player_cover() -> Response:
    records, _ = read_records("catalog.json")
    record = records.get(request.args.get("code", ""), {})
    target = approved_cover(record) if isinstance(record, dict) else None
    if target is None:
        return jsonify({"error": "没有已审核的封面"}), 404
    return send_file(target, conditional=True, max_age=300)


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
            "env_file": str(ENV_FILE),
        }
    )


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
