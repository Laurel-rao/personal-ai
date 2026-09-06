#!/usr/bin/env bash
# AutoDL 服务器上运行：下载 Qwen3.8-27B-Uncensored GGUF 并注册进 Ollama，替换旧 qwen。
# 用法: bash setup-qwen3.8-uncensored.sh [旧模型名]   传 - 表示不删旧模型，默认删 qwen3:4b
set -euo pipefail

REPO="JonathanColetti/Qwen3.8-27B-Uncensored-GGUF"
FILE="${FILE:-Qwen3.8-27B-Uncensored-noMTP-Q4_K_M.gguf}"   # 可 FILE=xxx.gguf 覆盖选其他量化
DIR="/root/autodl-tmp/Qwen3.8-27B-Uncensored"
MODEL_TAG="Qwen3.8-27B-Uncensored"
OLD_TAG="${1:-qwen3:4b}"

# 环境速览（失败不中断）
nvidia-smi --query-gpu=name,memory.total --format=csv 2>/dev/null || true
df -h /root/autodl-tmp 2>/dev/null || true

# 学术加速 + huggingface_hub
source /etc/network_turbo 2>/dev/null || true
command -v hf >/dev/null 2>&1 || pip install -q -U "huggingface-hub[cli]"

mkdir -p "$DIR" && cd "$DIR"
[ -f "$FILE" ] || hf download "$REPO" "$FILE" --local-dir "$DIR"

command -v ollama >/dev/null 2>&1 || {
  echo "服务器没装 ollama，先安装：curl -fsSL https://ollama.com/install.sh | sh" >&2
  exit 1
}

[ -f Modelfile ] || cat > Modelfile <<EOF
FROM ./$FILE
EOF
ollama create "$MODEL_TAG" -f Modelfile
ollama run "$MODEL_TAG" "用不超过20个字介绍一下你自己"

# 删旧模型（存在才删）
if [ "$OLD_TAG" != "-" ] && ollama list | grep -q "^${OLD_TAG}[[:space:]]"; then
  ollama rm "$OLD_TAG"
  echo "已删除旧模型 $OLD_TAG"
fi

echo "完成。photo_lab 启动时加 QWEN_MODEL=$MODEL_TAG 即可指向新模型"