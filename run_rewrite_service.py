#!/usr/bin/env python3
"""统一启动 Photo Lab API 与常驻记忆仿写任务。"""
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = __import__("pathlib").Path(__file__).resolve().parent
PYTHON = str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable
children = []


def stop_all(*_):
    for process in children:
        if process.poll() is None:
            process.terminate()
    for process in children:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    sys.exit(0)


signal.signal(signal.SIGINT, stop_all)
signal.signal(signal.SIGTERM, stop_all)

server = subprocess.Popen([PYTHON, "server.py", "--port", "4173"], cwd=ROOT)
children.append(server)
for _ in range(30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:4173/api/health", timeout=1):
            break
    except Exception:
        if server.poll() is not None:
            raise SystemExit("4173 服务启动失败，请检查 server.py 的 Python 依赖")
        time.sleep(1)
else:
    stop_all()
    raise SystemExit("等待 4173 服务超时")

rewrite = subprocess.Popen([PYTHON, "rewrite_and_generate.py", "--ctx", "32768", "--daemon"], cwd=ROOT)
children.append(rewrite)
try:
    while rewrite.poll() is None:
        time.sleep(1)
finally:
    stop_all()
