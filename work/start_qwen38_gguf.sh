#!/usr/bin/env bash
set -euo pipefail

MODEL="/root/models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-Q4_K_M.gguf"
SERVER="/root/llama.cpp/build/bin/llama-server"
LOG="/root/qwen38-gguf-server.log"

if [[ ! -x "$SERVER" ]]; then
  echo "llama-server is not built: $SERVER" >&2
  exit 1
fi

if [[ ! -f "$MODEL" ]]; then
  echo "model download is not complete: $MODEL" >&2
  exit 1
fi

pkill -f "llama-server.*--port 6008" || true
pkill -f "vllm serve.*--port 6008" || true

exec "$SERVER" \
  --model "$MODEL" \
  --alias qwen3.8-27b-uncensored \
  --host 0.0.0.0 \
  --port 6008 \
  --gpu-layers 99 \
  --ctx-size 8192 \
  --parallel 4 \
  --cont-batching \
  --flash-attn auto \
  --spec-type draft-mtp \
  --spec-draft-n-max 2 \
  --jinja \
  >> "$LOG" 2>&1
