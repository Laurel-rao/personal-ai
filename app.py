#!/usr/bin/env python3
"""Personal AI —— 统一 Flask 启动入口。

单进程、单端口同时提供：
- 根路径 /       : H3 视频工作台（server.py 的 console 蓝图）
- 前缀 /photo/*  : Photo Lab（photo_lab 独立 Flask 应用，WSGI 挂载）

用法：
    python3 app.py [--host 127.0.0.1] [--port 4173]

配置：启动时会读取项目根目录的 .env（KEY=VALUE 每行一条）。
已存在的环境变量优先，不会被 .env 覆盖；可在「设置」页面写入 .env。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (stdlib only): export KEY=VALUE lines, never override real env."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_env_file(Path(__file__).resolve().parent / ".env")

from flask import Flask  # noqa: E402
from werkzeug.middleware.dispatcher import DispatcherMiddleware  # noqa: E402

from photo_lab.app import app as photo_lab_app  # noqa: E402  (导入即启动 worker 线程)
from server import create_console_app  # noqa: E402


def create_app() -> Flask:
    app = create_console_app()
    app.wsgi_app = DispatcherMiddleware(
        app.wsgi_app,
        {"/photo": photo_lab_app.wsgi_app},
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the unified Personal AI console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()
    app = create_app()
    print(f"Personal AI unified console: http://{args.host}:{args.port}")
    print(f"  /        -> H3 视频工作台")
    print(f"  /photo   -> Photo Lab")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()