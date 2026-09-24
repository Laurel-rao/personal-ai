# Qwen-Image-2.1 Q4 本地运行

本目录使用 `stable-diffusion.cpp` 的 macOS ARM 预编译 `sd-cli`，适配 Apple Silicon；模型文件来自 `unsloth/Qwen-Image-2.1-GGUF` 配套仓库。

将以下文件放入 `models/`：

```text
qwen-image-2.1-Q4_K_M.gguf
qwen_image_2.1_vae_bf16.safetensors
Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf
```

本次文件通过 `hf-mirror.net` 镜像下载；镜像断线时可使用 `download-ranged.sh` 按 HTTP Range 分片断点续传。模型文件位于本地 `models/`，不会提交到 Git。

运行：

```bash
./tools/qwen-image-q4/run.sh
```

启动 OpenAI-compatible API；Photo Lab 已配置为使用这个本地后端：

```bash
QWEN_IMAGE_API_KEY=local-test ./tools/qwen-image-q4/serve.sh
```

接口地址为 `http://127.0.0.1:6009/v1/images/generations`，请求格式兼容 OpenAI Images API：

```bash
curl http://127.0.0.1:6009/v1/images/generations \
  -H 'Authorization: Bearer local-test' \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen-image-2.1-q4","prompt":"a red apple on a white table","size":"512x512","quality":"low","response_format":"url"}'
```

支持 `response_format=b64_json` 或 `url`；生成任务按单进程串行执行，避免 16 GB 统一内存并发占满。

默认参数是 `1024x1024`、`20` 步、Euler、CFG `6.0`；可通过 `QWEN_IMAGE_PROMPT`、`QWEN_IMAGE_STEPS`、`QWEN_IMAGE_WIDTH`、`QWEN_IMAGE_HEIGHT`、`QWEN_IMAGE_CFG`、`QWEN_IMAGE_SEED` 和 `QWEN_IMAGE_OUTPUT` 覆盖。

Apple M4 实测：`512x512`、20 步、Metal、Q4_K_M 约 `356.94 秒`；3 步会出现明显噪声伪影，质量测试建议至少使用 20 步。

文件来源：

- DiT：`unsloth/Qwen-Image-2.1-GGUF/qwen-image-2.1-Q4_K_M.gguf`
- VAE：`unsloth/Qwen-Image-2.1-FP8/vae/qwen_image_2.1_vae_bf16.safetensors`
- 文本编码器：`unsloth/Qwen3-VL-8B-Instruct-GGUF/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf`
