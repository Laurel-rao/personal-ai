# Qwen-Image-2.1 Q4 本地运行

本目录使用 `stable-diffusion.cpp` 的 macOS ARM 预编译 `sd-cli`，适配 Apple Silicon；模型文件来自 `unsloth/Qwen-Image-2.1-GGUF` 配套仓库。

将以下文件放入 `models/`：

```text
qwen-image-2.1-Q4_K_M.gguf
qwen_image_2.1_vae_bf16.safetensors
Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf
```

运行：

```bash
./tools/qwen-image-q4/run.sh
```

默认参数是 `1024x1024`、`20` 步、Euler、CFG `6.0`；可通过 `QWEN_IMAGE_PROMPT`、`QWEN_IMAGE_STEPS`、`QWEN_IMAGE_WIDTH`、`QWEN_IMAGE_HEIGHT`、`QWEN_IMAGE_CFG`、`QWEN_IMAGE_SEED` 和 `QWEN_IMAGE_OUTPUT` 覆盖。

文件来源：

- DiT：`unsloth/Qwen-Image-2.1-GGUF/qwen-image-2.1-Q4_K_M.gguf`
- VAE：`unsloth/Qwen-Image-2.1-FP8/vae/qwen_image_2.1_vae_bf16.safetensors`
- 文本编码器：`unsloth/Qwen3-VL-8B-Instruct-GGUF/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf`
