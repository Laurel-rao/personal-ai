#!/usr/bin/env python3
"""Start the local Media service without keeping a terminal open."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:4173"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def service_ready():
    try:
        with HTTP.open(BASE_URL + "/api/health", timeout=1) as response:
            payload = json.load(response)
        return (
            isinstance(payload, dict)
            and payload.get("success") is True
            and isinstance(payload.get("history_count"), int)
        )
    except (OSError, ValueError, urllib.error.URLError):
        return False


def ensure_service(root):
    if not (root / "app.py").is_file():
        raise RuntimeError("找不到项目入口：" + str(root / "app.py"))
    runtime = root / "data" / "media"
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / "service.log"
    deadline = time.monotonic() + 30
    with (runtime / "launch.lock").open("a") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("另一个 Media 启动进程等待超过 30 秒，请查看：" + str(log_path))
                time.sleep(0.2)
        if service_ready():
            return BASE_URL
        try:
            with socket.create_connection(("127.0.0.1", 4173), timeout=1):
                raise RuntimeError("端口 4173 已被占用且服务检查未通过，请检查现有服务。")
        except ConnectionRefusedError:
            pass
        python = root / ".venv" / "bin" / "python"
        if not python.is_file() or not os.access(python, os.X_OK):
            raise RuntimeError("找不到项目 Python 环境：" + str(python))
        with log_path.open("ab") as log_file:
            process = subprocess.Popen(
                [str(python), "-u", str(root / "app.py"), "--host", "127.0.0.1", "--port", "4173"],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Media 服务启动失败，请查看：" + str(log_path))
            if service_ready():
                return BASE_URL
            time.sleep(0.2)
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise RuntimeError("Media 服务启动超过 30 秒，请查看：" + str(log_path))


def main():
    parser = argparse.ArgumentParser(description="启动 Media 本地服务")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        print(ensure_service(args.project.resolve()))
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
