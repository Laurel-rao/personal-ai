#!/usr/bin/env python3
"""OpenAI Images API compatible wrapper for the local Qwen-Image-2.1 Q4 runner."""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


ROOT = Path(__file__).resolve().parent
BIN = Path(os.environ.get("QWEN_IMAGE_BIN", str(ROOT / "bin" / "sd-cli"))).resolve()
MODEL_DIR = Path(os.environ.get("QWEN_IMAGE_MODEL_DIR", str(ROOT / "models"))).resolve()
DIFFUSION_MODEL = Path(os.environ.get("QWEN_IMAGE_DIFFUSION_MODEL", str(MODEL_DIR / "qwen-image-2.1-Q4_K_M.gguf"))).resolve()
VAE_MODEL = Path(os.environ.get("QWEN_IMAGE_VAE_MODEL", str(MODEL_DIR / "qwen_image_2.1_vae_bf16.safetensors")).strip()).resolve()
LLM_MODEL = Path(os.environ.get("QWEN_IMAGE_LLM_MODEL", str(MODEL_DIR / "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf"))).resolve()
OUTPUT_DIR = Path(os.environ.get("QWEN_IMAGE_OUTPUT_DIR", str(ROOT / "outputs"))).resolve()
API_KEY = os.environ.get("QWEN_IMAGE_API_KEY", "").strip()
PUBLIC_BASE_URL = os.environ.get("QWEN_IMAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")
DEFAULT_STEPS = max(2, int(os.environ.get("QWEN_IMAGE_STEPS", "20")))
DEFAULT_CFG = float(os.environ.get("QWEN_IMAGE_CFG", "6.0"))
MAX_N = max(1, min(4, int(os.environ.get("QWEN_IMAGE_MAX_N", "4"))))
GENERATION_LOCK = threading.Lock()

app = Flask(__name__)


def error_response(message: str, status: int = 400, *, code: str = "invalid_request_error", param: str | None = None):
    return jsonify({"error": {"message": message, "type": "invalid_request_error", "param": param, "code": code}}), status


def check_api_key():
    if API_KEY and request.headers.get("Authorization", "") != f"Bearer {API_KEY}":
        return error_response("无效或缺少 API Key", 401, code="invalid_api_key")
    return None


def ensure_files():
    files = (BIN, DIFFUSION_MODEL, VAE_MODEL, LLM_MODEL)
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("缺少模型文件: " + ", ".join(missing))


def parse_size(value):
    value = str(value or "1024x1024").lower()
    if value == "auto":
        return 1024, 1024
    try:
        width, height = (int(part) for part in value.split("x", 1))
    except (TypeError, ValueError):
        raise ValueError("size 必须是 auto 或 WIDTHxHEIGHT")
    if not 256 <= width <= 1536 or not 256 <= height <= 1536:
        raise ValueError("size 必须在 256 到 1536 像素之间")
    if width % 32 or height % 32:
        raise ValueError("宽度和高度必须是 32 的倍数")
    return width, height


def parse_payload():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")
    if len(prompt) > 4000:
        raise ValueError("prompt 不能超过 4000 个字符")
    try:
        count = int(payload.get("n", 1))
    except (TypeError, ValueError):
        raise ValueError("n 必须是整数")
    if not 1 <= count <= MAX_N:
        raise ValueError(f"n 必须在 1 到 {MAX_N} 之间")
    width, height = parse_size(payload.get("size", "1024x1024"))
    quality = str(payload.get("quality", "medium")).lower()
    if quality not in {"low", "medium", "high"}:
        raise ValueError("quality 必须是 low、medium 或 high")
    default_steps = {"low": max(2, DEFAULT_STEPS - 8), "medium": DEFAULT_STEPS, "high": DEFAULT_STEPS + 8}[quality]
    try:
        steps = int(payload.get("steps", default_steps))
    except (TypeError, ValueError):
        raise ValueError("steps 必须是整数")
    if not 2 <= steps <= 60:
        raise ValueError("steps 必须在 2 到 60 之间")
    try:
        cfg = float(payload.get("cfg_scale", DEFAULT_CFG))
    except (TypeError, ValueError):
        raise ValueError("cfg_scale 必须是数字")
    if not 1 <= cfg <= 20:
        raise ValueError("cfg_scale 必须在 1 到 20 之间")
    response_format = str(payload.get("response_format", "b64_json")).lower()
    if response_format not in {"b64_json", "url"}:
        raise ValueError("response_format 必须是 b64_json 或 url")
    seed = payload.get("seed")
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            raise ValueError("seed 必须是整数")
        if not 0 <= seed <= 2147483647:
            raise ValueError("seed 必须在 0 到 2147483647 之间")
    return prompt, count, width, height, steps, cfg, response_format, seed


def generate_one(prompt, width, height, steps, cfg, seed, output):
    command = [
        str(BIN),
        "--diffusion-model", str(DIFFUSION_MODEL),
        "--vae", str(VAE_MODEL),
        "--llm", str(LLM_MODEL),
        "--prompt", prompt,
        "--steps", str(steps),
        "--cfg-scale", str(cfg),
        "--sampling-method", "euler",
        "--width", str(width),
        "--height", str(height),
        "--seed", str(seed),
        "--diffusion-fa",
        "--offload-to-cpu",
        "--mmap",
        "--output", str(output),
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0 or not output.is_file():
        detail = (result.stderr or result.stdout)[-2000:]
        raise RuntimeError(f"sd-cli 生成失败: {detail}")


def image_url(filename):
    base = PUBLIC_BASE_URL or request.host_url.rstrip("/")
    return f"{base}/v1/images/{filename}"


@app.get("/health")
def health():
    files = (BIN, DIFFUSION_MODEL, VAE_MODEL, LLM_MODEL)
    return jsonify({
        "ok": all(path.is_file() for path in files),
        "model": "Qwen-Image-2.1-Q4_K_M",
        "backend": "stable-diffusion.cpp",
        "metal": True,
        "busy": GENERATION_LOCK.locked(),
        "missing": [str(path) for path in files if not path.is_file()],
    })


@app.post("/v1/images/generations")
@app.post("/images/generations")
def generations():
    auth_error = check_api_key()
    if auth_error:
        return auth_error
    try:
        prompt, count, width, height, steps, cfg, response_format, requested_seed = parse_payload()
        ensure_files()
    except ValueError as exc:
        return error_response(str(exc))
    except RuntimeError as exc:
        return error_response(str(exc), 503, code="model_unavailable")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    created = int(datetime.now(timezone.utc).timestamp())
    items = []
    with GENERATION_LOCK:
        try:
            for index in range(count):
                seed = requested_seed if requested_seed is not None else secrets.randbelow(2147483647)
                filename = f"{created}-{uuid.uuid4().hex}.png"
                output = OUTPUT_DIR / filename
                generate_one(prompt, width, height, steps, cfg, seed, output)
                item = {"revised_prompt": prompt}
                if response_format == "b64_json":
                    item["b64_json"] = base64.b64encode(output.read_bytes()).decode("ascii")
                else:
                    item["url"] = image_url(filename)
                items.append(item)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return error_response(str(exc), 500, code="image_generation_failed")
    return jsonify({"created": created, "data": items})


@app.get("/v1/images/<path:filename>")
def image_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="image/png", max_age=86400)


if __name__ == "__main__":
    host = os.environ.get("QWEN_IMAGE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("QWEN_IMAGE_API_PORT", "6009"))
    app.run(host=host, port=port, threaded=True)
