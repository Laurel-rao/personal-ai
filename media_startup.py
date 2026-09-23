"""Manage login startup for the local 4173 backend."""

import os
from pathlib import Path
import plistlib
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request


ROOT = Path(__file__).resolve().parent
LABEL = "local.personal-ai.media.backend"
STARTUP_FILE = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
STARTUP_LOCK = threading.Lock()
startup_bp = Blueprint("media_startup", __name__)


def startup_configuration():
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(ROOT / ".venv" / "bin" / "python"),
            "-u",
            str(ROOT / "app.py"),
            "--host", "127.0.0.1", "--port", "4173",
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StandardOutPath": str(ROOT / "data" / "media" / "service.log"),
        "StandardErrorPath": str(ROOT / "data" / "media" / "service.log"),
    }


def startup_status():
    supported = sys.platform == "darwin"
    enabled = False
    if supported and STARTUP_FILE.exists():
        with STARTUP_FILE.open("rb") as startup_file:
            config = plistlib.load(startup_file)
        expected = startup_configuration()
        if not isinstance(config, dict) or config != expected:
            raise ValueError("现有开机启动配置与当前项目不一致，请检查：" + str(STARTUP_FILE))
        enabled = True
    return {"success": True, "supported": supported, "enabled": enabled}


def set_startup(enabled):
    if sys.platform != "darwin":
        raise ValueError("开机启动设置仅支持 macOS。")
    with STARTUP_LOCK:
        if STARTUP_FILE.is_symlink():
            raise ValueError("开机启动配置是符号链接，无法安全修改。")
        startup_status()
        if enabled:
            python = ROOT / ".venv" / "bin" / "python"
            if not (ROOT / "app.py").is_file() or not os.access(python, os.X_OK):
                raise ValueError("项目入口或 .venv Python 环境不存在，无法启用开机启动。")
            (ROOT / "data" / "media").mkdir(parents=True, exist_ok=True)
            STARTUP_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=STARTUP_FILE.parent, delete=False) as output:
                    temporary = Path(output.name)
                    plistlib.dump(startup_configuration(), output)
                os.replace(temporary, STARTUP_FILE)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        else:
            STARTUP_FILE.unlink(missing_ok=True)
        return startup_status()


@startup_bp.before_request
def require_local_request():
    hostname = urlsplit(request.host_url).hostname
    if request.remote_addr not in {"127.0.0.1", "::1"} or hostname not in {"localhost", "127.0.0.1", "::1"}:
        return jsonify(success=False, error="开机启动设置仅允许从本机访问。"), 403
    origin = request.headers.get("Origin")
    if (origin and origin != request.host_url.rstrip("/")) or request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify(success=False, error="不允许跨站修改开机启动设置。"), 403


@startup_bp.route("/api/settings/startup", methods=["GET", "POST"])
def api_startup():
    try:
        if request.method == "GET":
            return jsonify(startup_status())
        if not request.is_json:
            return jsonify(success=False, error="请求必须使用 application/json 格式。"), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
            return jsonify(success=False, error="enabled 必须为布尔值。"), 400
        return jsonify(set_startup(payload["enabled"]))
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        return jsonify(success=False, error=str(error)), 400
