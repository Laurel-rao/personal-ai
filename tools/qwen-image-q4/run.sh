#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="$ROOT/bin/sd-cli"
MODEL_DIR="$ROOT/models"
DIFFUSION_MODEL="${DIFFUSION_MODEL:-$MODEL_DIR/qwen-image-2.1-Q4_K_M.gguf}"
VAE_MODEL="${VAE_MODEL:-$MODEL_DIR/qwen_image_2.1_vae_bf16.safetensors}"
LLM_MODEL="${LLM_MODEL:-$MODEL_DIR/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf}"
PROMPT="${QWEN_IMAGE_PROMPT:-a cinematic high quality portrait on a beach at golden hour, realistic skin texture, sharp focus, natural lighting}"
OUTPUT="${QWEN_IMAGE_OUTPUT:-$ROOT/output.png}"
WIDTH="${QWEN_IMAGE_WIDTH:-1024}"
HEIGHT="${QWEN_IMAGE_HEIGHT:-1024}"
STEPS="${QWEN_IMAGE_STEPS:-20}"
CFG="${QWEN_IMAGE_CFG:-6.0}"
SEED="${QWEN_IMAGE_SEED:-42}"

for file in "$BIN" "$DIFFUSION_MODEL" "$VAE_MODEL" "$LLM_MODEL"; do
  if [ ! -f "$file" ]; then
    echo "缺少文件: $file" >&2
    echo "请将 Q4_K_M DiT、Qwen3-VL Q4 文本编码器和 VAE 放入 $MODEL_DIR" >&2
    exit 2
  fi
done

exec "$BIN" \
  --diffusion-model "$DIFFUSION_MODEL" \
  --vae "$VAE_MODEL" \
  --llm "$LLM_MODEL" \
  --prompt "$PROMPT" \
  --steps "$STEPS" \
  --cfg-scale "$CFG" \
  --sampling-method euler \
  --width "$WIDTH" \
  --height "$HEIGHT" \
  --seed "$SEED" \
  --diffusion-fa \
  --offload-to-cpu \
  --mmap \
  --output "$OUTPUT"
