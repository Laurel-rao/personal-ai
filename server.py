#!/usr/bin/env python3
"""H3 视频工作台 —— Flask 版。

在统一入口 app.py 中以蓝图 (console_bp) 注册；
也可独立运行：python3 server.py --host 127.0.0.1 --port 4173
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import mimetypes
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request, send_file, stream_with_context


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
HISTORY_LOCK = threading.Lock()
STATIC_FILES = {
    "/": ROOT / "index.html",
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
    "/templates/warring-states-ref2va.txt": ROOT / "templates" / "warring-states-ref2va.txt",
    "/templates/warring-states-ref2va-15.txt": ROOT / "templates" / "warring-states-ref2va-15.txt",
    "/templates/warring-states-01-meeting-chase-ref2va.txt": ROOT / "templates" / "warring-states-01-meeting-chase-ref2va.txt",
    "/templates/warring-states-02-command-transition-ref2va.txt": ROOT / "templates" / "warring-states-02-command-transition-ref2va.txt",
}
REMOTE_TIMEOUT_SECONDS = 30
AUTODL_HOSTS = {"autodl.art", "www.autodl.art"}
AUTODL_WORKFLOW = "minimax_h3_lightx2v_v5_15s"
ZERO_IMAGE_BASE_URL = "https://ai.reeko.net.cn/v1"
QWEN_API_URL = os.environ.get(
    "QWEN_API_URL",
    "https://uu288331-78852a40cf8c.westd.seetacloud.com:8443/v1",
).rstrip("/")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.8-27b-uncensored")

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


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def write_history(items: list[dict[str, Any]]) -> None:
    with HISTORY_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = HISTORY_FILE.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(items[:200], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, HISTORY_FILE)


def upsert_history(item: dict[str, Any]) -> dict[str, Any]:
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
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or path.suffix in {".js", ".css"}:
        content_type = f"{content_type}; charset=utf-8"
    return send_file(path, mimetype=content_type)


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
    return jsonify({"success": True, "history_count": len(load_history())})


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
        saved = upsert_history(item)
        return jsonify({"success": True, "item": saved})
    except Exception as exc:
        return error_response(400, str(exc))


@console_bp.delete("/api/history")
def api_history_delete() -> Response:
    key = str(request.args.get("id", "")).strip()
    if not key:
        write_history([])
        return jsonify({"success": True, "deleted": "all"})
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
    CHAT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = f"{stamp}.png"
    (CHAT_IMAGE_DIR / name).write_bytes(base64.b64decode(encoded))
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
    target = CHAT_IMAGE_DIR / safe
    if not target.exists() or not target.is_file():
        return error_response(404, "图片不存在")
    return send_file(target, mimetype="image/png", max_age=86400)


# ---------------------------------------------------------------- 应用工厂

def create_console_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(console_bp)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the H3 video console (Flask)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()
    app = create_console_app()
    # 单独运行 server.py 时也挂载 Photo Lab（与 app.py 统一入口一致），
    # 避免只起 console 导致 /photo 图片生成页 404。
    try:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from photo_lab.app import app as photo_lab_app

        app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/photo": photo_lab_app.wsgi_app})
    except ImportError:
        # photo_lab 依赖缺失时退化为纯 console
        pass
    print(f"H3 video console: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
