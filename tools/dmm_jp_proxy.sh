#!/usr/bin/env bash
# 为 DMM 试读下载启动独立的日本出口（复用 Clash Verge 的 JP 节点）。
# 不修改 Clash Verge 的当前配置；只在 127.0.0.1:7898 起一个单独的 mihomo。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DMM_JP_PORT:-7898}"
CTL="${DMM_JP_CTL:-9098}"
DIR="${DMM_JP_DIR:-/tmp/dmm-jp}"
CONFIG="$DIR/config.yaml"
MIHOMO="/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "DMM JP proxy already listening on 127.0.0.1:$PORT"
  exit 0
fi
if [ ! -x "$MIHOMO" ]; then
  echo "verge-mihomo not found: $MIHOMO" >&2
  exit 1
fi

mkdir -p "$DIR"
"$ROOT/.venv/bin/python" - "$DIR" "$PORT" "$CTL" <<'PY'
import os
import sys
from pathlib import Path

import yaml

out, port, ctl = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
source = Path.home() / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml"
config = yaml.safe_load(source.read_text(encoding="utf-8"))
names = ("kingfast-JP1", "kingfast-JP2")
proxies = [item for item in config.get("proxies", []) if item.get("name") in names]
if not proxies:
    raise SystemExit("no JP nodes found in the active Clash Verge config")

mini = {
    "mixed-port": port,
    "allow-lan": False,
    "bind-address": "127.0.0.1",
    "mode": "rule",
    "log-level": "warning",
    "external-controller": f"127.0.0.1:{ctl}",
    "proxies": proxies,
    "proxy-groups": [{
        "name": "JP",
        "type": "select",
        "proxies": [item["name"] for item in proxies],
    }],
    "rules": ["MATCH,JP"],
}
out.mkdir(parents=True, exist_ok=True)
(out / "config.yaml").write_text(yaml.safe_dump(mini, allow_unicode=True, sort_keys=False), encoding="utf-8")
os.chmod(out / "config.yaml", 0o600)
PY

nohup "$MIHOMO" -d "$DIR" -f "$CONFIG" >> "$DIR/mihomo.log" 2>&1 < /dev/null &
echo $! > "$DIR/pid"

for _ in $(seq 1 40); do
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "DMM JP proxy listening on 127.0.0.1:$PORT"
    exit 0
  fi
  sleep 0.25
done
echo "DMM JP proxy failed to start; see $DIR/mihomo.log" >&2
exit 1
