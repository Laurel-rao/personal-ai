#!/usr/bin/env python3
"""Small local server for the H3 video console."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
STATIC_FILES = {
    "/": ROOT / "index.html",
    "/index.html": ROOT / "index.html",
    "/chat": ROOT / "chat.html",
    "/chat.html": ROOT / "chat.html",
    "/image": ROOT / "image.html",
    "/image.html": ROOT / "image.html",
    "/styles.css": ROOT / "styles.css",
    "/app.js": ROOT / "app.js",
    "/chat.css": ROOT / "chat.css",
    "/chat-refined.css": ROOT / "chat-refined.css",
    "/chat-simple.css": ROOT / "chat-simple.css",
    "/chat.js": ROOT / "chat.js",
    "/image.css": ROOT / "image.css",
    "/assets/vendor/nlux/nlux-core-2.17.1.umd.js": ROOT / "assets" / "vendor" / "nlux" / "nlux-core-2.17.1.umd.js",
    "/assets/vendor/nlux/nova-2.17.1.css": ROOT / "assets" / "vendor" / "nlux" / "nova-2.17.1.css",
    "/templates/warring-states-ref2va.txt": ROOT / "templates" / "warring-states-ref2va.txt",
    "/templates/warring-states-ref2va-15.txt": ROOT / "templates" / "warring-states-ref2va-15.txt",
    "/templates/warring-states-01-meeting-chase-ref2va.txt": ROOT / "templates" / "warring-states-01-meeting-chase-ref2va.txt",
    "/templates/warring-states-02-command-transition-ref2va.txt": ROOT / "templates" / "warring-states-02-command-transition-ref2va.txt",
}
HISTORY_LOCK = threading.Lock()
REMOTE_TIMEOUT_SECONDS = 30
AUTODL_HOSTS = {"autodl.art", "www.autodl.art"}
AUTODL_WORKFLOW = "minimax_h3_lightx2v_v5_15s"
ZERO_IMAGE_BASE_URL = "https://ai.reeko.net.cn/v1"
QWEN_API_URL = os.environ.get(
    "QWEN_API_URL",
    "https://uu288331-788499bf7eab.bjb1.seetacloud.com:8443/v1",
).rstrip("/")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3:4b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_history() -> list[dict[str, Any]]:
    with HISTORY_LOCK:
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


class AppHandler(BaseHTTPRequestHandler):
    server_version = "H3VideoConsole/1.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_media_bytes(self, status: int, payload: bytes, content_type: str, response_headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, max-age=300")
        for name, value in response_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def read_body(self, max_bytes: int = 256 * 1024 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > max_bytes:
            raise ValueError("请求内容过大")
        return self.rfile.read(length)

    def read_json_body(self) -> dict[str, Any]:
        # Four PNG data URLs can exceed the previous 8 MiB limit before the
        # request reaches AutoDL. The payload stays local and is still bounded.
        data = decode_json(self.read_body(64 * 1024 * 1024))
        if not isinstance(data, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return data

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in STATIC_FILES:
            return self.serve_static(STATIC_FILES[parsed.path])
        if parsed.path == "/api/health":
            return self.send_json(200, {"success": True, "history_count": len(load_history())})
        if parsed.path == "/api/chat/health":
            return self.handle_chat_health()
        if parsed.path == "/api/service/check":
            return self.handle_service_check(parsed.query)
        if parsed.path == "/api/history":
            return self.send_json(200, {"success": True, "items": load_history()})
        if parsed.path == "/api/assets":
            return self.handle_assets()
        if parsed.path == "/api/media":
            return self.handle_media_proxy(parsed.query)
        if parsed.path == "/api/workflow/result":
            return self.handle_workflow_result(parsed.query)
        self.send_json(404, {"success": False, "error": "未找到该地址"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/history":
            return self.handle_history_upsert()
        if parsed.path == "/api/workflow/generate":
            return self.handle_workflow_generate()
        if parsed.path == "/api/frames/generate":
            return self.handle_frame_generate()
        if parsed.path == "/api/comfy/upload/file":
            return self.handle_file_upload(parsed.query)
        if parsed.path == "/api/chat/completions":
            return self.handle_chat_completions()
        if parsed.path == "/api/chat/stream":
            return self.handle_chat_stream()
        self.send_json(404, {"success": False, "error": "未找到该地址"})

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/history":
            return self.send_json(404, {"success": False, "error": "未找到该地址"})
        query = urllib.parse.parse_qs(parsed.query)
        key = str(query.get("id", [""])[0]).strip()
        if not key:
            write_history([])
            return self.send_json(200, {"success": True, "deleted": "all"})
        items = [entry for entry in load_history() if str(entry.get("promptId") or entry.get("id")) != key]
        write_history(items)
        self.send_json(200, {"success": True, "deleted": key})

    def serve_static(self, path: Path) -> None:
        try:
            payload = path.read_bytes()
        except OSError:
            return self.send_json(404, {"success": False, "error": "页面文件不存在"})
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or path.suffix in {".js", ".css"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_bytes(200, payload, content_type)

    def handle_service_check(self, query_string: str) -> None:
        try:
            query = urllib.parse.parse_qs(query_string)
            base_url = validate_base_url(query.get("base_url", [""])[0])
            if is_autodl_url(base_url):
                if not env_token("AUTODL_ART_TOKEN"):
                    return self.send_json(503, {"success": False, "error": "服务端未配置 AUTODL_ART_TOKEN"})
                return self.send_json(200, {"success": True, "provider": "AutoDL.Art", "status": "configured"})
            status, _, _ = request_remote("HEAD", f"{base_url}/", timeout=12)
            if status >= 400:
                return self.send_json(502, {"success": False, "error": f"远端服务返回 {status}"})
            self.send_json(200, {"success": True, "status": status})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_history_upsert(self) -> None:
        try:
            item = self.read_json_body()
            saved = upsert_history(item)
            self.send_json(200, {"success": True, "item": saved})
        except Exception as error:
            self.send_json(400, {"success": False, "error": str(error)})

    def handle_workflow_generate(self) -> None:
        try:
            request_data = self.read_json_body()
            base_url = validate_base_url(request_data.get("base_url"))
            workflow_id = str(request_data.get("workflow_id") or "").strip()
            input_values = request_data.get("input_values")
            metadata = request_data.get("metadata") if isinstance(request_data.get("metadata"), dict) else {}
            if not workflow_id:
                raise ValueError("Workflow ID 不能为空")
            if not isinstance(input_values, dict):
                raise ValueError("input_values 必须是对象")
            if is_autodl_url(base_url) or workflow_id == AUTODL_WORKFLOW:
                return self.handle_autodl_generate(base_url, workflow_id, input_values, metadata)
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
            self.send_bytes(status, payload, content_type)
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_autodl_generate(
        self,
        base_url: str,
        workflow_id: str,
        input_values: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        token = env_token("AUTODL_ART_TOKEN")
        if not token:
            return self.send_json(503, {"success": False, "error": "服务端未配置 AUTODL_ART_TOKEN"})
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
        remote_url = f"https://www.autodl.art/api/v1/comfyui/comfyui_workflow/{urllib.parse.quote(workflow_id, safe='') }"
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
            return self.send_json(
                200,
                {
                    "success": True,
                    "prompt_id": str(task_id),
                    "provider": "AutoDL.Art",
                    "status": "pending",
                    "remote": result,
                },
            )
        self.send_bytes(status, raw, content_type)

    def handle_frame_generate(self) -> None:
        try:
            request_data = self.read_json_body()
            prompt = str(request_data.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("首尾帧提示词不能为空")
            token = env_token("AZT_API_KEY")
            if not token:
                return self.send_json(503, {"success": False, "error": "服务端未配置 AZT_API_KEY"})
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
                return self.send_bytes(status, raw, content_type)
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
            self.send_json(200, {"success": True, "files": files})
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_workflow_result(self, query_string: str) -> None:
        try:
            query = urllib.parse.parse_qs(query_string)
            prompt_id = str(query.get("prompt_id", [""])[0]).strip()
            base_url = validate_base_url(query.get("base_url", [""])[0])
            if not prompt_id:
                raise ValueError("prompt_id 不能为空")
            if is_autodl_url(base_url):
                return self.handle_autodl_result(prompt_id)
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
            self.send_bytes(status, payload, content_type)
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_media_proxy(self, query_string: str) -> None:
        try:
            query = urllib.parse.parse_qs(query_string)
            task_id = str(query.get("task_id", [""])[0]).strip()
            index = int(query.get("index", ["0"])[0])
            if not task_id or index < 0:
                raise ValueError("媒体参数无效")
            task = next(
                (item for item in load_history() if str(item.get("promptId") or item.get("id")) == task_id),
                None,
            )
            if not task:
                self.send_json(404, {"success": False, "error": "未找到生成任务"})
                return
            urls: list[str] = []
            extract_media(task.get("result"), str(task.get("baseUrl") or ""), urls)
            if index >= len(urls) or not is_trusted_media_url(urls[index]):
                self.send_json(404, {"success": False, "error": "该媒体暂不支持代理预览"})
                return
            status, payload, content_type, response_headers = request_media(urls[index], self.headers.get("Range"))
            self.send_media_bytes(status, payload, content_type, response_headers)
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_autodl_result(self, task_id: str) -> None:
        token = env_token("AUTODL_ART_TOKEN")
        if not token:
            return self.send_json(503, {"success": False, "error": "服务端未配置 AUTODL_ART_TOKEN"})
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
        self.send_json(status, normalized)

    def handle_file_upload(self, query_string: str) -> None:
        try:
            query = urllib.parse.parse_qs(query_string)
            base_url = validate_base_url(query.get("base_url", [""])[0])
            body = self.read_body()
            content_type = self.headers.get("Content-Type", "application/octet-stream")
            status, payload, remote_content_type = request_remote(
                "POST",
                f"{base_url}/api/comfy/upload/file",
                body=body,
                headers={"Content-Type": content_type},
                timeout=120,
            )
            self.send_bytes(status, payload, remote_content_type)
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception as error:
            self.send_json(502, {"success": False, "error": str(error)})

    def handle_chat_health(self) -> None:
        try:
            status, payload, _ = request_remote("GET", f"{QWEN_API_URL}/models", timeout=15)
            result = decode_json(payload)
            if not 200 <= status < 300:
                return self.send_json(502, {"success": False, "error": "Qwen 服务不可用"})
            model_data = result.get("data", []) if isinstance(result, dict) else []
            models = [item.get("id") for item in model_data if isinstance(item, dict) and item.get("id")]
            self.send_json(200, {"success": True, "model": QWEN_MODEL, "available_models": models})
        except Exception:
            self.send_json(502, {"success": False, "error": "Qwen 服务不可用"})

    def build_chat_request(self, stream: bool) -> bytes:
        payload = self.read_json_body()
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
            if not content or len(content) > 12000:
                raise ValueError("单条消息须为 1 到 12000 个字符")
            total_characters += len(content)
            cleaned_messages.append({"role": role, "content": content})
        if total_characters > 36000:
            raise ValueError("对话总长度不能超过 36000 个字符")
        temperature = float(payload.get("temperature", 0.7))
        max_tokens = int(payload.get("max_tokens", 1024))
        if not 0 <= temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        if not 64 <= max_tokens <= 2048:
            raise ValueError("max_tokens 必须在 64 到 2048 之间")
        return json.dumps({
            "model": QWEN_MODEL,
            "messages": cleaned_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }).encode("utf-8")

    def handle_chat_completions(self) -> None:
        try:
            request_payload = self.build_chat_request(False)
            status, response_payload, _ = request_remote(
                "POST",
                f"{QWEN_API_URL}/chat/completions",
                body=request_payload,
                headers={"Content-Type": "application/json"},
                timeout=180,
            )
            result = decode_json(response_payload)
            if not 200 <= status < 300:
                return self.send_json(502, {"success": False, "error": "Qwen 请求失败"})
            self.send_json(200, result)
        except ValueError as error:
            self.send_json(400, {"success": False, "error": str(error)})
        except Exception:
            self.send_json(502, {"success": False, "error": "Qwen 服务不可用"})

    def handle_chat_stream(self) -> None:
        stream_started = False
        try:
            request_payload = self.build_chat_request(True)
            request = urllib.request.Request(
                f"{QWEN_API_URL}/chat/completions",
                data=request_payload,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180, context=ssl.create_default_context()) as response:
                self.send_response(response.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                stream_started = True
                for line in response:
                    self.wfile.write(line)
                    self.wfile.flush()
        except urllib.error.HTTPError as error:
            if stream_started:
                return
            result = decode_json(error.read())
            message = result.get("error", "Qwen 流式请求失败") if isinstance(result, dict) else "Qwen 流式请求失败"
            self.send_json(502, {"success": False, "error": message})
        except ValueError as error:
            if not stream_started:
                self.send_json(400, {"success": False, "error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            if not stream_started:
                self.send_json(502, {"success": False, "error": "Qwen 流式请求失败"})

    def handle_assets(self) -> None:
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
        self.send_json(200, {"success": True, "items": assets})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the H3 video console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"H3 video console: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
