#!/usr/bin/env python3
"""部署自检：目录、依赖、ffmpeg、代理、可选外部站点连通性。

用法：
    .venv/bin/python tools/check_deployment.py
    .venv/bin/python tools/check_deployment.py --network

不打印任何密钥值；只检查是否存在/可达。
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
WARNS: list[str] = []


def load_env(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def ok(label: str, detail: str = "") -> None:
    print(f"[ OK ] {label}{(' — ' + detail) if detail else ''}")


def warn(label: str, detail: str = "") -> None:
    WARNS.append(label)
    print(f"[WARN] {label}{(' — ' + detail) if detail else ''}")


def fail(label: str, detail: str = "") -> None:
    FAILS.append(label)
    print(f"[FAIL] {label}{(' — ' + detail) if detail else ''}")


def check_import(module: str, label: str) -> None:
    try:
        importlib.import_module(module)
        ok(label)
    except Exception as exc:  # noqa: BLE001
        fail(label, str(exc)[:120])


def check_dir(label: str, path: Path) -> None:
    if not path.exists():
        warn(label, f"不存在，启动时可能自动创建：{path}")
        return
    if not path.is_dir():
        fail(label, f"不是目录：{path}")
        return
    probe = path / ".write-check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ok(label, str(path))
    except OSError as exc:
        fail(label, f"不可写：{path}（{exc}）")


def proxy_parts(value: str) -> tuple[str, int] | None:
    if not value:
        return None
    try:
        parsed = urllib.parse.urlparse(value if "://" in value else "http://" + value)
        if not parsed.hostname:
            return None
        return parsed.hostname, int(parsed.port or (443 if parsed.scheme == "https" else 80))
    except ValueError:
        return None


def check_proxy(label: str, value: str) -> None:
    if not value:
        warn(label, "未配置")
        return
    parts = proxy_parts(value)
    if not parts:
        fail(label, "URL 无法解析")
        return
    host, port = parts
    try:
        with socket.create_connection((host, port), timeout=2):
            ok(label, f"{host}:{port}")
    except OSError as exc:
        fail(label, f"{host}:{port} 不可连接（{exc}）")


def fetch(url: str, proxy: str, timeout: int = 8) -> tuple[int | None, str]:
    handlers = []
    if proxy:
        proxy_url = proxy if "://" in proxy else "http://" + proxy
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/json,*/*;q=0.8",
    })
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:100]


def check_network() -> None:
    nyaa = env("NYAA_PROXY")
    dmm = env("DMM_PROXY") or nyaa
    checks = [
        ("sukebei", "https://sukebei.nyaa.si/", nyaa),
        ("JavDatabase", "https://www.javdatabase.com/", dmm),
        ("DMM book", "https://book.dmm.co.jp/", dmm),
        ("NDL", "https://ndlsearch.ndl.go.jp/", nyaa),
    ]
    for label, url, proxy in checks:
        status, detail = fetch(url, proxy)
        if status and 200 <= status < 500:
            ok(f"网络 {label}", f"HTTP {status} {detail}")
        else:
            warn(f"网络 {label}", f"HTTP {status or '无响应'} {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal AI deployment check")
    parser.add_argument("--network", action="store_true", help="额外检查外部站点（会走代理）")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Root:   {ROOT}")
    if sys.version_info < (3, 9):
        fail("Python 版本", "需要 3.9+")

    for name, label in [
        ("flask", "Flask"),
        ("flask_appbuilder", "Flask-AppBuilder"),
        ("PIL", "Pillow"),
        ("requests", "requests"),
        ("websocket", "websocket-client"),
    ]:
        check_import(name, f"依赖 {label}")

    for tool in ("ffmpeg", "ffprobe", "curl"):
        path = shutil.which(tool)
        if path:
            ok(f"命令 {tool}", path)
        elif tool == "curl":
            warn(f"命令 {tool}", "未找到；部分 Cloudflare 抓取兜底会失效")
        else:
            warn(f"命令 {tool}", "未找到；视频技术信息和截帧不可用")

    state_dir = Path(env("PERSONAL_AI_STATE_DIR", str(ROOT / "data"))).expanduser()
    check_dir("状态目录", state_dir)
    check_dir("Photo Lab 数据", ROOT / "photo_lab" / "data")
    movies = Path(env("MOVIES_DIR", str(Path.home() / "Movies"))).expanduser()
    nyaa_dir = Path(env("NYAA_DIR", str(Path.home() / "Movies" / "Videos"))).expanduser()
    photos = Path(env("LOCAL_PHOTO_DIR", str(Path.home() / "Movies" / "写真"))).expanduser()
    check_dir("视频片库 MOVIES_DIR", movies)
    check_dir("下载目录 NYAA_DIR", nyaa_dir)
    check_dir("写真目录 LOCAL_PHOTO_DIR", photos)
    if not (state_dir / "accounts.db").exists():
        warn("账号库", "尚未创建；请执行 flask --app app:create_app fab create-admin")
    if not (state_dir / ".session-secret").exists() and not env("PERSONAL_AI_SECRET_KEY"):
        warn("会话密钥", "尚未生成；首次启动会创建，备份 data/.session-secret")

    check_proxy("代理 NYAA_PROXY", env("NYAA_PROXY", "http://127.0.0.1:7897"))
    check_proxy("代理 DMM_PROXY", env("DMM_PROXY"))

    thunder_enabled = env("THUNDER_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
    if not thunder_enabled:
        ok("下载器", "THUNDER_ENABLED=0：只保存种子")
    elif sys.platform == "darwin":
        ok("下载器", f"macOS open -a {env('THUNDER_APP', 'Thunder')}")
    elif env("THUNDER_CMD"):
        ok("下载器", f"THUNDER_CMD={env('THUNDER_CMD')}")
    else:
        warn("下载器", "Linux 未配置 THUNDER_CMD；磁力发送会失败，种子仍会保存")

    if env("PERSONAL_AI_COOKIE_SECURE") not in {"1", "true", "yes", "on"}:
        warn("HTTPS Cookie", "PERSONAL_AI_COOKIE_SECURE 未开启；公网 HTTPS 部署应设为 1")

    if args.network:
        print("\n外部站点：")
        check_network()

    print("\n结果：")
    print(f"  FAIL {len(FAILS)} · WARN {len(WARNS)}")
    if FAILS:
        for item in FAILS:
            print(f"  - {item}")
        return 1
    print("  基础检查通过；WARN 项请按部署环境确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
