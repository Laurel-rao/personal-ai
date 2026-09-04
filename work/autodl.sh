#!/bin/bash
set -euo pipefail

if ! pgrep -f '[c]omfy launch.*--port 6006' >/dev/null; then
  nohup /bin/bash -lc '/root/1键启动.sh' \
    >> /root/autodl-tmp/comfy-startup.log 2>&1 &
fi

if command -v ollama >/dev/null && ! pgrep -x ollama >/dev/null; then
  screen -dmS qwen3-api /bin/bash -lc \
    'exec env OLLAMA_HOST=0.0.0.0:6008 OLLAMA_MODELS=/root/autodl-tmp/ollama/models /usr/bin/ollama serve >> /root/autodl-tmp/ollama.log 2>&1'
fi
